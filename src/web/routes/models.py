"""
src/web/routes/models.py
REST API endpoints for AI models catalog, active assignments, and spend analytics (F36, F41).
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import load_config
from src.openrouter_catalog import OpenRouterCatalog
from src.token_tracker import get_summary, get_all_models_usage, get_task_usage_summary
from src.web.security import redact_data

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
def get_models_catalog():
    """Fetches full model catalog from OpenRouter catalog cache with fallback."""
    catalog_service = OpenRouterCatalog()
    cache = catalog_service.get_catalog(force_refresh=False)
    cfg = load_config()
    active_gw = cfg.get("active_gateway", "openrouter")
    gw_info = cfg.get("gateways", {}).get(active_gw, {})

    models_list = [
        item.model_dump() if hasattr(item, "model_dump") else item
        for item in cache.values()
    ]

    return redact_data({
        "active_gateway": active_gw,
        "gateway_name": gw_info.get("name", active_gw),
        "hermes_model": gw_info.get("hermes_model"),
        "omp_model": gw_info.get("omp_model"),
        "presets": cfg.get("presets", {}),
        "total_models": len(models_list),
        "models": models_list
    })


@router.get("/metrics")
def get_telemetry_metrics():
    """Returns aggregated spend analytics by model, agent, per-task usage, and overall monthly progress (F41)."""
    cfg = load_config()
    monthly_budget = float(cfg.get("telemetry", {}).get("monthly_budget_usd", 25.0))
    summary = get_summary(days=30)
    current_month_spend = summary.get("total_cost_usd", 0.0)
    all_models = get_all_models_usage(days=90)
    task_usages = get_task_usage_summary(limit=50)

    return redact_data({
        "monthly_budget_usd": monthly_budget,
        "current_month_spend_usd": current_month_spend,
        "percent_budget_used": min(100.0, round((current_month_spend / monthly_budget) * 100.0, 1)) if monthly_budget > 0 else 0.0,
        "total_calls": summary.get("total_calls", 0),
        "total_tokens": summary.get("total_tokens", 0),
        "prompt_tokens": summary.get("prompt_tokens", 0),
        "completion_tokens": summary.get("completion_tokens", 0),
        "by_model": summary.get("by_model", []),
        "all_models_usage": all_models,
        "task_usage_summary": task_usages,
        "by_agent": summary.get("by_agent", []),
        "recent_transactions": summary.get("recent_records", [])
    })


@router.get("/usage/by-model")
def get_usage_by_model():
    """Returns detailed individual token and cost usage for every model invoked."""
    return redact_data({
        "models": get_all_models_usage(days=90)
    })


@router.get("/usage/by-task")
def get_usage_by_task():
    """Returns aggregated token and cost usage grouped per task_id."""
    return redact_data({
        "tasks": get_task_usage_summary(limit=50)
    })

