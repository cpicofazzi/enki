import os
import sys
import sqlite3
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def get_db_path() -> Path:
    from src.config import load_config
    cfg = load_config()
    db_rel = cfg.get("telemetry", {}).get("db_path", "data/enki_telemetry.db")
    db_path = ROOT_DIR / db_rel
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path

def init_db() -> None:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telemetry_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                agent_role TEXT NOT NULL,
                task_id TEXT,
                model TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                notes TEXT
            );
        """)
        conn.commit()

def record_usage(
    agent_role: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float = 0.0,
    task_id: str = "",
    notes: str = ""
) -> int:
    init_db()
    total_tokens = prompt_tokens + completion_tokens
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO telemetry_records (
                timestamp, agent_role, task_id, model,
                prompt_tokens, completion_tokens, total_tokens, cost_usd, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, agent_role, task_id, model,
            prompt_tokens, completion_tokens, total_tokens, cost_usd, notes
        ))
        conn.commit()
        return cursor.lastrowid

def get_summary(days: int = 30) -> Dict[str, Any]:
    init_db()
    db_path = get_db_path()
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Totals
        cursor.execute("""
            SELECT 
                COUNT(*) as total_calls,
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens,
                SUM(total_tokens) as grand_total_tokens,
                SUM(cost_usd) as total_cost_usd
            FROM telemetry_records
            WHERE timestamp >= ?
        """, (cutoff,))
        row = cursor.fetchone()
        
        total_calls = row["total_calls"] or 0
        total_prompt = row["total_prompt_tokens"] or 0
        total_comp = row["total_completion_tokens"] or 0
        total_tokens = row["grand_total_tokens"] or 0
        total_cost = row["total_cost_usd"] or 0.0

        # By Agent Role
        cursor.execute("""
            SELECT 
                agent_role,
                COUNT(*) as calls,
                SUM(total_tokens) as tokens,
                SUM(cost_usd) as cost
            FROM telemetry_records
            WHERE timestamp >= ?
            GROUP BY agent_role
        """, (cutoff,))
        by_agent = [dict(r) for r in cursor.fetchall()]

        # By Model (including prompt, completion, total tokens, avg tokens, cost)
        cursor.execute("""
            SELECT 
                model,
                COUNT(*) as calls,
                COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                COALESCE(SUM(total_tokens), 0) as tokens,
                COALESCE(SUM(cost_usd), 0.0) as cost,
                ROUND(AVG(total_tokens), 1) as avg_tokens_per_call
            FROM telemetry_records
            WHERE timestamp >= ?
            GROUP BY model
            ORDER BY cost DESC, tokens DESC
        """, (cutoff,))
        by_model = [dict(r) for r in cursor.fetchall()]

        # Recent 50 entries
        cursor.execute("""
            SELECT id, timestamp, agent_role, model, prompt_tokens, completion_tokens, total_tokens, cost_usd, task_id, notes
            FROM telemetry_records
            ORDER BY id DESC
            LIMIT 50
        """)
        recent = [dict(r) for r in cursor.fetchall()]

    return {
        "period_days": days,
        "total_calls": total_calls,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_comp,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
        "by_agent": by_agent,
        "by_model": by_model,
        "recent_records": recent
    }

def get_all_models_usage(days: int = 90) -> List[Dict[str, Any]]:
    """
    Returns comprehensive lifetime/period usage aggregated for each model individually.
    Includes model name, total calls, prompt tokens, completion tokens, total tokens,
    total cost, and the tasks/runs that called this model.
    """
    init_db()
    db_path = get_db_path()
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                model,
                COUNT(*) as total_calls,
                COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(cost_usd), 0.0) as total_cost_usd,
                COUNT(DISTINCT task_id) as distinct_tasks_count,
                MIN(timestamp) as first_used,
                MAX(timestamp) as last_used
            FROM telemetry_records
            WHERE timestamp >= ?
            GROUP BY model
            ORDER BY total_cost_usd DESC, total_tokens DESC
        """, (cutoff,))
        models = [dict(r) for r in cursor.fetchall()]

    return models

def get_task_usage_summary(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Returns usage aggregated per task_id / run_id.
    Includes task_id, total calls, models used, prompt tokens, completion tokens,
    total tokens, and total cost incurred.
    """
    init_db()
    db_path = get_db_path()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                COALESCE(NULLIF(task_id, ''), 'standalone') as task_id,
                COUNT(*) as total_calls,
                GROUP_CONCAT(DISTINCT model) as models_used,
                COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(cost_usd), 0.0) as total_cost_usd,
                MIN(timestamp) as started_at,
                MAX(timestamp) as last_activity
            FROM telemetry_records
            GROUP BY COALESCE(NULLIF(task_id, ''), 'standalone')
            ORDER BY last_activity DESC
            LIMIT ?
        """, (limit,))
        tasks = [dict(r) for r in cursor.fetchall()]

    return tasks

def get_run_telemetry(run_id: str) -> Dict[str, Any]:
    """
    Derives exact token usage, cost, and call records strictly scoped to a specific run_id.
    Fixes the 30-day sum bug where get_summary() was used across all historical records.
    """
    init_db()
    db_path = get_db_path()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Exact Totals for this run_id
        cursor.execute("""
            SELECT 
                COUNT(*) as calls_count,
                COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(cost_usd), 0.0) as total_cost_usd
            FROM telemetry_records
            WHERE task_id = ?
        """, (run_id,))
        row = cursor.fetchone()

        calls_count = row["calls_count"] if row else 0
        prompt_tokens = row["prompt_tokens"] if row else 0
        comp_tokens = row["completion_tokens"] if row else 0
        total_tokens = row["total_tokens"] if row else 0
        total_cost = row["total_cost_usd"] if row else 0.0

        # Breakdown by Agent Role for this run_id
        cursor.execute("""
            SELECT 
                agent_role,
                COUNT(*) as calls,
                COALESCE(SUM(total_tokens), 0) as tokens,
                COALESCE(SUM(cost_usd), 0.0) as cost
            FROM telemetry_records
            WHERE task_id = ?
            GROUP BY agent_role
        """, (run_id,))
        by_agent = [dict(r) for r in cursor.fetchall()]

        # Breakdown by Model for this run_id
        cursor.execute("""
            SELECT 
                model,
                COUNT(*) as calls,
                COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                COALESCE(SUM(total_tokens), 0) as tokens,
                COALESCE(SUM(cost_usd), 0.0) as cost
            FROM telemetry_records
            WHERE task_id = ?
            GROUP BY model
            ORDER BY cost DESC
        """, (run_id,))
        by_model = [dict(r) for r in cursor.fetchall()]

        # Individual call records for this run_id
        cursor.execute("""
            SELECT id, timestamp, agent_role, model, prompt_tokens, completion_tokens, total_tokens, cost_usd, notes
            FROM telemetry_records
            WHERE task_id = ?
            ORDER BY id ASC
        """, (run_id,))
        records = [dict(r) for r in cursor.fetchall()]

    return {
        "run_id": run_id,
        "calls_count": calls_count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": comp_tokens,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "by_agent": by_agent,
        "by_model": by_model,
        "records": records
    }

def print_dashboard() -> None:
    from src.config import load_config
    cfg = load_config()
    budget = cfg.get("telemetry", {}).get("monthly_budget_usd", 25.0)
    summary = get_summary()
    
    cost = summary["total_cost_usd"]
    pct = (cost / budget * 100.0) if budget > 0 else 0.0

    print("=" * 64)
    print(" ENKI HUB - OPENROUTER TELEMETRY & COST MONITOR")
    print("=" * 64)
    print(f" Monthly Budget    : ${budget:.2f} USD")
    print(f" Current Spend     : ${cost:.4f} USD ({pct:.1f}% utilized)")
    print(f" Total Invocations : {summary['total_calls']}")
    print(f" Total Tokens      : {summary['total_tokens']:,} (Prompt: {summary['prompt_tokens']:,} | Comp: {summary['completion_tokens']:,})")
    print("-" * 64)
    
    print(" BREAKDOWN BY AGENT:")
    if not summary["by_agent"]:
        print("   (No agent activity logged yet)")
    for ag in summary["by_agent"]:
        role = ag["agent_role"].upper()
        tokens = ag["tokens"] or 0
        c = ag["cost"] or 0.0
        calls = ag["calls"]
        print(f"   [{role:<8}] Calls: {calls:<4} | Tokens: {tokens:>8,} | Cost: ${c:.4f}")
        
    print("-" * 64)
    print(" BREAKDOWN BY MODEL:")
    if not summary["by_model"]:
        print("   (No model usage recorded yet)")
    for md in summary["by_model"]:
        m_name = md["model"]
        tokens = md["tokens"] or 0
        c = md["cost"] or 0.0
        print(f"   {m_name:<36} | Tokens: {tokens:>8,} | Cost: ${c:.4f}")

    print("-" * 64)
    print(" RECENT TRANSACTIONS:")
    if not summary["recent_records"]:
        print("   (No recent records)")
    for r in summary["recent_records"]:
        ts = r["timestamp"][:19].replace("T", " ")
        print(f"   #{r['id']:<3} {ts} | {r['agent_role']:<7} | {r['model']:<25} | {r['total_tokens']:>5} tok | ${r['cost_usd']:.4f}")
    print("=" * 64)

if __name__ == "__main__":
    if "--audit-heartbeat" in sys.argv:
        # Silent hook check
        init_db()
        sys.exit(0)
    print_dashboard()
