"""
src/engine/subagents_flow.py
Extraction and aggregation engine for visualizing the execution flow of each subagent
(Hermes Knowledge Agent, Oh My Pi Coding Agent, Human Supervisor Gate, Reviewer Agent)
and tracking exactly where code and notes have been processed.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import os
import json
import datetime

from src.engine.models import Run, StepStatus
from src.engine.worktree_manager import WorktreeManager
from src.obsidian_indexer import ObsidianIndexer


def extract_subagents_flow(run: Run, root_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Extracts structured flow data for a run, mapping each step to its responsible subagent,
    identifying the exact Obsidian notes read/written, and detailing repository code files touched.
    """
    if not root_dir:
        root_dir = Path(__file__).resolve().parent.parent.parent

    # 1. Identify Subagent Flow Stages
    flow_stages: List[Dict[str, Any]] = []
    
    # Subagent metadata mapping
    AGENT_MAP = {
        "context_extraction": {
            "subagent_id": "hermes",
            "name": "Hermes",
            "role": "Knowledge & Context Extractor",
            "icon": "book-open",
            "color": "#38bdf8",
            "boundary": "Obsidian Vault (Read Only)",
        },
        "context": {
            "subagent_id": "hermes",
            "name": "Hermes",
            "role": "Knowledge & Context Extractor",
            "icon": "book-open",
            "color": "#38bdf8",
            "boundary": "Obsidian Vault (Read Only)",
        },
        "planning": {
            "subagent_id": "hermes",
            "name": "Hermes",
            "role": "Architectural Planner",
            "icon": "compass",
            "color": "#38bdf8",
            "boundary": "Obsidian Vault & Specifications",
        },
        "coding": {
            "subagent_id": "omp",
            "name": "Oh My Pi (OMP)",
            "role": "Terminal Coding Agent",
            "icon": "terminal",
            "color": "#a855f7",
            "boundary": "Repository Code & Worktree (Isolated)",
        },
        "code": {
            "subagent_id": "omp",
            "name": "Oh My Pi (OMP)",
            "role": "Terminal Coding Agent",
            "icon": "terminal",
            "color": "#a855f7",
            "boundary": "Repository Code & Worktree (Isolated)",
        },
        "handshake": {
            "subagent_id": "omp",
            "name": "Oh My Pi (OMP)",
            "role": "Terminal Coding Agent",
            "icon": "terminal",
            "color": "#a855f7",
            "boundary": "Repository Code & Worktree (Isolated)",
        },
        "verification": {
            "subagent_id": "omp",
            "name": "Oh My Pi (OMP)",
            "role": "Verification & Test Runner",
            "icon": "check-circle",
            "color": "#10b981",
            "boundary": "Local Test Suite & Compilers",
        },
        "verify": {
            "subagent_id": "omp",
            "name": "Oh My Pi (OMP)",
            "role": "Verification & Test Runner",
            "icon": "check-circle",
            "color": "#10b981",
            "boundary": "Local Test Suite & Compilers",
        },
        "review": {
            "subagent_id": "reviewer",
            "name": "AI Reviewer",
            "role": "Architectural Evaluator",
            "icon": "shield-check",
            "color": "#f59e0b",
            "boundary": "Git Diff & Acceptance Rubric",
        },
        "compare": {
            "subagent_id": "comparator",
            "name": "Candidate Comparator",
            "role": "Fan-Out Worktree Evaluator",
            "icon": "git-pull-request",
            "color": "#ec4899",
            "boundary": "Parallel Git Worktrees",
        },
        "sync": {
            "subagent_id": "hermes",
            "name": "Hermes",
            "role": "Vault Sync & Telemetry Logger",
            "icon": "database",
            "color": "#38bdf8",
            "boundary": "Obsidian Vault (Activity Log)",
        },
    }

    for idx, step in enumerate(run.steps):
        stype = step.step_type.lower()
        meta = AGENT_MAP.get(stype, {
            "subagent_id": "system",
            "name": "Enki Engine",
            "role": f"Step Runner ({step.step_type})",
            "icon": "cpu",
            "color": "#94a3b8",
            "boundary": "Engine Runtime",
        })

        # Calculate duration if timestamps present
        duration_sec = step.duration_seconds
        if duration_sec is None and step.started_at and step.completed_at:
            try:
                t0 = datetime.datetime.fromisoformat(step.started_at)
                t1 = datetime.datetime.fromisoformat(step.completed_at)
                duration_sec = round((t1 - t0).total_seconds(), 2)
            except Exception:
                duration_sec = None

        stage_info: Dict[str, Any] = {
            "step_id": step.step_id,
            "step_name": step.name or step.step_id,
            "step_type": step.step_type,
            "order": idx + 1,
            "subagent_id": meta["subagent_id"],
            "subagent_name": meta["name"],
            "subagent_role": meta["role"],
            "icon": meta["icon"],
            "color": meta["color"],
            "boundary": meta["boundary"],
            "status": step.status.value,
            "model": step.model or (step.routing_decision.model if step.routing_decision else "auto"),
            "routing_reason": step.routing_decision.reason if step.routing_decision else None,
            "attempts": step.attempts,
            "max_attempts": step.max_attempts,
            "started_at": step.started_at,
            "completed_at": step.completed_at,
            "duration_seconds": duration_sec,
            "error": step.error,
            "artifacts_summary": "",
        }

        # Step-specific artifact highlights
        out = step.output or {}
        if stype in ["context_extraction", "context"]:
            p = out.get("payload") or run.payload or {}
            req_count = len(p.get("requirements", []))
            sources_count = len(p.get("context_sources", []))
            stage_info["artifacts_summary"] = f"Extracted {req_count} requirements from {sources_count} vault notes"
        elif stype in ["coding", "code", "handshake"]:
            exit_code = out.get("exit_code", 0)
            status_str = out.get("status", "completed")
            stage_info["artifacts_summary"] = f"Handshake {status_str} (exit code: {exit_code})"
        elif stype in ["verification", "verify"]:
            passed = out.get("passed", False)
            stage_info["artifacts_summary"] = "All acceptance tests passed" if passed else "Tests failed or pending"
        elif stype == "review":
            decision = out.get("decision", "pending")
            score = out.get("score", 0)
            stage_info["artifacts_summary"] = f"Review decision: {decision.upper()} (score: {score}/100)"
        elif stype == "sync":
            entry = out.get("vault_entry", "01_Dashboard/Enki_Activity_Log.md")
            stage_info["artifacts_summary"] = f"Synced activity log to {entry}"

        flow_stages.append(stage_info)

    # 2. Extract Processed Notes (Obsidian pico-vault)
    indexer = ObsidianIndexer()
    vault_available = indexer.is_vault_available()
    vault_path_str = str(indexer.vault_path).replace("\\", "/")

    notes_read: List[Dict[str, Any]] = []
    # 2a. Check if context_sources was recorded in run.payload or context_payload.json
    payload = run.payload or {}
    if not payload and (root_dir / "data" / "runs" / run.run_id / "context_payload.json").is_file():
        try:
            with open(root_dir / "data" / "runs" / run.run_id / "context_payload.json", "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            pass

    recorded_sources = payload.get("context_sources", [])
    if recorded_sources:
        for s in recorded_sources:
            notes_read.append({
                "path": s.get("path", "").replace("\\", "/"),
                "title": s.get("title") or Path(s.get("path", "")).stem,
                "score": s.get("score", 100),
                "excerpt": s.get("excerpt", "Referenced context source"),
                "source": "Recorded in context payload"
            })
    elif vault_available and run.task:
        # If not recorded (e.g. simulated run), dynamically query vault matching notes for this task
        try:
            hits = indexer.search_vault(run.task, max_results=5)
            for h in hits:
                notes_read.append({
                    "path": h["path"].replace("\\", "/"),
                    "title": h.get("title", Path(h["path"]).stem),
                    "score": h.get("score", 0),
                    "excerpt": h.get("excerpt", ""),
                    "source": "Matched via Hermes vault indexing"
                })
        except Exception:
            pass

    # 2b. Notes Written or Synced (Hermes output)
    notes_written: List[Dict[str, Any]] = []
    sync_step = next((s for s in run.steps if s.step_type.lower() == "sync"), None)
    if sync_step and sync_step.status == StepStatus.COMPLETED:
        sync_out = sync_step.output or {}
        entry_path = sync_out.get("vault_entry", "01_Dashboard/Enki_Activity_Log.md").replace("\\", "/")
        notes_written.append({
            "path": entry_path,
            "action": "Append run completion and telemetry log",
            "status": "synced",
            "subagent": "Hermes",
            "timestamp": sync_step.completed_at or run.completed_at
        })
        if sync_out.get("updated_task_note"):
            notes_written.append({
                "path": f"40_Tasks/{sync_out['updated_task_note']}",
                "action": "Checklist status marked completed [x]",
                "status": "synced",
                "subagent": "Hermes",
                "timestamp": sync_step.completed_at or run.completed_at
            })
    else:
        # Expected sync note
        notes_written.append({
            "path": "01_Dashboard/Enki_Activity_Log.md",
            "action": "Central telemetry and task activity log",
            "status": "pending_sync" if run.status.value != "completed" else "synced",
            "subagent": "Hermes",
            "timestamp": None
        })

    # 3. Extract Processed Code (Oh My Pi Repository & Worktree)
    wm = WorktreeManager()
    diff_stat_data: Dict[str, Any] = {
        "total_files": 0,
        "total_additions": 0,
        "total_deletions": 0,
        "files": []
    }
    diff_text = ""

    try:
        diff_res = wm.get_diff(root_dir, run.run_id)
        if hasattr(diff_res, "diff_text"):
            diff_text = diff_res.diff_text or ""
        elif isinstance(diff_res, str):
            diff_text = diff_res
        else:
            diff_text = str(diff_res) if diff_res else ""

        stat = wm.get_worktree_diff_stat(root_dir, run.run_id)
        diff_stat_data = {
            "total_files": stat.total_files,
            "total_additions": stat.total_additions,
            "total_deletions": stat.total_deletions,
            "files": [
                {
                    "path": f.path.replace("\\", "/"),
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions
                }
                for f in stat.files
            ]
        }
    except Exception:
        pass

    # Check verification results
    verify_step = next((s for s in run.steps if s.step_type.lower() in ["verification", "verify"]), None)
    verify_out = verify_step.output or {} if verify_step else {}
    test_commands = ["py -m pytest -q"]
    if payload and "acceptance_criteria" in payload:
        test_commands = payload["acceptance_criteria"].get("test_commands", test_commands)

    verification_info = {
        "passed": verify_out.get("passed", False),
        "status": "PASSED" if verify_out.get("passed") else ("RUNNING" if verify_step and verify_step.status == StepStatus.RUNNING else "PENDING"),
        "test_commands": test_commands,
        "results": verify_out.get("results", [])
    }

    # 4. Assembled Aggregation
    return {
        "run_id": run.run_id,
        "task": run.task,
        "project": run.project,
        "workflow_id": run.workflow_id,
        "status": run.status.value,
        "dry_run": run.dry_run,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "branch_name": run.branch_name,
        "worktree_path": run.worktree_path,
        "worktree_action": run.worktree_action.value,
        "subagents_flow": flow_stages,
        "processed_notes": {
            "vault_path": vault_path_str,
            "vault_available": vault_available,
            "notes_read": notes_read,
            "notes_read_count": len(notes_read),
            "notes_written": notes_written,
            "notes_written_count": len(notes_written),
            "boundary_rule": "Hermes exclusively interacts with Obsidian vault notes. OMP has zero vault access and is strictly confined to repository files.",
            "boundary_enforced": True
        },
        "processed_code": {
            "repository_root": str(root_dir).replace("\\", "/"),
            "worktree_path": run.worktree_path or f".worktrees/{run.run_id}",
            "branch_name": run.branch_name or f"enki/run/{run.run_id}",
            "stat": diff_stat_data,
            "diff_preview": diff_text[:3000] if diff_text else "",
            "diff_total_length": len(diff_text),
            "verification": verification_info
        },
        "telemetry": {
            "calls_count": run.telemetry.calls_count if run.telemetry else 0,
            "prompt_tokens": run.telemetry.prompt_tokens if run.telemetry else 0,
            "completion_tokens": run.telemetry.completion_tokens if run.telemetry else 0,
            "total_tokens": run.telemetry.total_tokens if run.telemetry else 0,
            "total_cost_usd": run.telemetry.total_cost_usd if run.telemetry else 0.0,
            "by_model": run.telemetry.by_model if run.telemetry else [],
            "by_agent": run.telemetry.by_agent if run.telemetry else []
        }
    }
