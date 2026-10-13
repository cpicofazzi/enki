"""
src/web/routes/runs.py
REST API endpoints for runs lifecycle, states, gates, budgets, and worktree actions (F36).
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Literal
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from src.engine.run_manager import RunManager
from src.engine.models import RunStatus, GateAction, BudgetDecision
from src.engine.worktree_manager import WorktreeManager
from src.web.security import redact_data

logger = logging.getLogger("enki.web.runs")
router = APIRouter(prefix="/api/runs", tags=["runs"])
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent


def _dispatch_run_execution(run_id: str, dry_run: bool = False) -> None:
    """Starts run state and executes workflow DAG in background."""
    mgr = RunManager()
    try:
        mgr.start_run(run_id)
    except Exception as e:
        logger.error(f"Error starting run {run_id}: {e}")
        return

    try:
        from src.engine.workflow_engine import WorkflowEngine
        engine = WorkflowEngine(run_manager=mgr)
        engine.execute_dag(run_id=run_id, dry_run=dry_run, raise_on_gate=False)
    except Exception as e:
        logger.info(f"Workflow execution finished or paused for {run_id}: {e}")


class CreateRunRequest(BaseModel):
    task: str
    project: str = "General"
    workflow_id: str = "four_step_pipeline"
    dry_run: bool = False
    gateway: str = "openrouter"
    model_override: Optional[str] = None
    preset: Optional[str] = None
    local_research: bool = True
    find_research: bool = False
    start_immediately: bool = True


class ResolveGateRequest(BaseModel):
    gate_id: str
    action: str  # approve, reject, edit_payload, abort
    payload: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None


class ResolveBudgetRequest(BaseModel):
    decision: str  # continue, pause, switch_model
    cheaper_model: Optional[str] = None


class WorktreeActionRequest(BaseModel):
    action: Literal["merge", "keep", "discard"]
    target_branch: str = "main"


@router.get("")
def list_runs(status: Optional[str] = None, limit: int = 50):
    """Lists runs sorted newest first with optional status filtering."""
    mgr = RunManager()
    runs = mgr.list_runs()
    if status:
        runs = [r for r in runs if r.status.value.lower() == status.lower()]
    summaries = [r.model_dump() for r in runs[:limit]]
    return redact_data({"runs": summaries, "total": len(summaries)})


@router.post("")
def create_run(req: CreateRunRequest, background_tasks: BackgroundTasks):
    """Creates a new run, sets up worktree and state, and optionally starts it."""
    mgr = RunManager()
    run = mgr.create_run(
        task=req.task,
        project=req.project,
        workflow_id=req.workflow_id,
        dry_run=req.dry_run,
        gateway=req.gateway,
        model_override=req.model_override,
        preset=req.preset,
        local_research=req.local_research,
        find_research=req.find_research
    )

    if req.start_immediately:
        # Launch run execution in background
        background_tasks.add_task(_dispatch_run_execution, run.run_id, req.dry_run)

    return redact_data({
        "success": True,
        "run": run.model_dump()
    })


@router.get("/{run_id}")
def get_run(run_id: str):
    """Fetches full state of a specific run enriched with subagents flow."""
    mgr = RunManager()
    try:
        run = mgr.load_run(run_id)
        data = run.model_dump()
        try:
            from src.engine.subagents_flow import extract_subagents_flow
            data["subagents_flow_data"] = extract_subagents_flow(run, ROOT_DIR)
        except Exception:
            pass
        return redact_data(data)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")


@router.get("/{run_id}/subagents-flow")
@router.get("/{run_id}/flow")
def get_run_subagents_flow(run_id: str):
    """Fetches full subagent flow and notes/code processing details for a specific run."""
    mgr = RunManager()
    try:
        run = mgr.load_run(run_id)
        from src.engine.subagents_flow import extract_subagents_flow
        flow_data = extract_subagents_flow(run, ROOT_DIR)
        return redact_data(flow_data)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")



@router.post("/{run_id}/start")
def start_run(run_id: str, background_tasks: BackgroundTasks):
    """Starts or triggers execution of an existing pending run."""
    mgr = RunManager()
    try:
        run = mgr.load_run(run_id)
        background_tasks.add_task(_dispatch_run_execution, run_id, run.dry_run)
        return {"success": True, "message": f"Run {run_id} started."}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")


@router.post("/{run_id}/resume")
def resume_run(run_id: str, from_step_id: Optional[str] = None, background_tasks: BackgroundTasks = None):
    """Resumes a failed or stopped run from the first failed step or specified step."""
    mgr = RunManager()
    try:
        run = mgr.resume_run(run_id, from_step_id=from_step_id)
        if background_tasks:
            background_tasks.add_task(_dispatch_run_execution, run_id, run.dry_run)
        return redact_data({"success": True, "run": run.model_dump()})
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{run_id}/gate")
def resolve_gate(run_id: str, req: ResolveGateRequest):
    """Submits human gate resolution (approve, reject, edit_payload, abort)."""
    mgr = RunManager()
    try:
        run = mgr.resolve_gate(
            run_id=run_id,
            gate_id=req.gate_id,
            action=req.action,
            payload=req.payload,
            feedback=req.feedback
        )
        return redact_data({"success": True, "run": run.model_dump()})
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{run_id}/budget")
def resolve_budget(run_id: str, req: ResolveBudgetRequest):
    """Submits budget limit decision (continue, pause, switch_model)."""
    mgr = RunManager()
    try:
        decision = BudgetDecision(req.decision)
        run = mgr.resolve_budget(
            run_id=run_id,
            decision=decision,
            cheaper_model=req.cheaper_model
        )
        return redact_data({"success": True, "run": run.model_dump()})
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{run_id}/diff")
def get_run_diff(run_id: str):
    """Calculates git diff of the run worktree against its base branch (F40)."""
    mgr = RunManager()
    try:
        run = mgr.load_run(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    wm = WorktreeManager()
    try:
        diff_text = wm.get_diff(ROOT_DIR, run_id)
        stat = wm.get_worktree_diff_stat(ROOT_DIR, run_id)
        return redact_data({
            "run_id": run_id,
            "diff": diff_text,
            "stat": {
                "total_files": stat.total_files,
                "total_additions": stat.total_additions,
                "total_deletions": stat.total_deletions,
                "files": [
                    {
                        "status": f.status,
                        "path": f.path,
                        "additions": f.additions,
                        "deletions": f.deletions
                    }
                    for f in stat.files
                ]
            }
        })
    except Exception as e:
        return {
            "run_id": run_id,
            "diff": "",
            "stat": {"total_files": 0, "total_additions": 0, "total_deletions": 0, "files": []},
            "error": str(e)
        }


@router.post("/{run_id}/worktree")
def resolve_worktree(run_id: str, req: WorktreeActionRequest):
    """Handles user choice to merge, keep, or discard the run worktree."""
    mgr = RunManager()
    try:
        res = mgr.finish_worktree(
            run_id=run_id,
            action=req.action,
            target_branch=req.target_branch,
            repo_path=ROOT_DIR
        )
        return redact_data({"success": True, "action": req.action, "result": res})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{run_id}")
def delete_run(run_id: str):
    """Permanently deletes a run, its persisted state artifacts, and associated worktree."""
    mgr = RunManager()
    deleted = mgr.delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {"success": True, "message": f"Run '{run_id}' deleted successfully."}
