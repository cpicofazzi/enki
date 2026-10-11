"""
src/engine/run_manager.py
Manages run persistence under data/runs/<run_id>/run_state.json,
run lifecycle, atomic serialization, replay, and resume from failed steps.
"""

import os
import json
import uuid
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Literal, Callable, Union

from src.engine.models import (
    Run, StepState, RunStatus, StepStatus, RunSummary,
    RunEvent, EventType, GateAction, BudgetDecision, WorktreeAction,
    RunTelemetry, GateState, BudgetState
)
from src.engine.events import EventBus, get_event_bus
from src.token_tracker import get_run_telemetry


class RunManager:
    def __init__(self, base_runs_dir: Optional[Path] = None, event_bus: Optional[EventBus] = None):
        if base_runs_dir is None:
            root_dir = Path(__file__).resolve().parent.parent.parent
            base_runs_dir = root_dir / "data" / "runs"
        self.base_runs_dir = Path(base_runs_dir)
        self.base_runs_dir.mkdir(parents=True, exist_ok=True)
        self.event_bus = event_bus or get_event_bus()
        self.event_bus.set_runs_base_dir(self.base_runs_dir)

    def _generate_run_id(self) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        rand_hex = uuid.uuid4().hex[:8]
        return f"run_{now.strftime('%Y%m%d_%H%M%S')}_{rand_hex}"

    def get_run_dir(self, run_id: str) -> Path:
        return self.base_runs_dir / run_id

    def get_run_state_file(self, run_id: str) -> Path:
        return self.get_run_dir(run_id) / "run_state.json"

    def get_context_payload_file(self, run_id: str) -> Path:
        return self.get_run_dir(run_id) / "context_payload.json"

    def create_run(
        self,
        task: str,
        project: str = "General",
        workflow_id: str = "four_step_pipeline",
        dry_run: bool = False,
        gateway: str = "openrouter",
        model_override: Optional[str] = None,
        preset: Optional[str] = None,
        base_branch: str = "HEAD",
        step_definitions: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Run:
        run_id = self._generate_run_id()
        run_dir = self.get_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        steps: List[StepState] = []
        if step_definitions:
            for s_def in step_definitions:
                m_val = s_def.get("model")
                if isinstance(m_val, dict):
                    m_val = m_val.get("model_id") or m_val.get("preset") or "auto"
                steps.append(StepState(
                    step_id=s_def["id"],
                    step_type=s_def.get("type", "custom"),
                    name=s_def.get("name", s_def["id"]),
                    model=m_val if isinstance(m_val, str) else None
                ))
        else:
            steps = [
                StepState(step_id="context_extraction", step_type="context_extraction", name="Hermes Context Extraction"),
                StepState(step_id="coding", step_type="coding", name="OMP Coding Handshake"),
                StepState(step_id="verification", step_type="verification", name="OMP Test Verification Loop"),
                StepState(step_id="sync", step_type="sync", name="Hermes Vault Sync")
            ]

        run = Run(
            run_id=run_id,
            task=task,
            project=project,
            workflow_id=workflow_id,
            status=RunStatus.PENDING,
            dry_run=dry_run,
            gateway=gateway,
            model_override=model_override,
            preset=preset,
            branch_name=f"enki/run/{run_id}",
            base_branch=base_branch,
            steps=steps,
            telemetry=RunTelemetry(run_id=run_id),
            metadata=metadata or {}
        )

        self.save_run(run)
        self.event_bus.publish(RunEvent(
            run_id=run_id,
            event_type=EventType.RUN_CREATED,
            payload={"task": task, "project": project, "workflow_id": workflow_id, "dry_run": dry_run}
        ))
        return run

    def save_run(self, run: Run) -> None:
        """Atomic write: writes to .tmp file then renames to prevent corruption on abrupt termination."""
        state_file = self.get_run_state_file(run.run_id)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = state_file.with_suffix(".tmp")
        content = run.model_dump_json(indent=2)
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(content)
        tmp_file.replace(state_file)

        # Mirror context payload if present
        if run.payload:
            payload_file = self.get_context_payload_file(run.run_id)
            tmp_payload = payload_file.with_suffix(".tmp")
            with open(tmp_payload, "w", encoding="utf-8") as f:
                json.dump(run.payload, f, indent=2)
            tmp_payload.replace(payload_file)

    def load_run(self, run_id: str) -> Run:
        state_file = self.get_run_state_file(run_id)
        if not state_file.is_file():
            raise FileNotFoundError(f"Run {run_id} does not exist at {state_file}")
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Run.model_validate(data)

    def list_runs(self, limit: int = 100) -> List[RunSummary]:
        summaries: List[RunSummary] = []
        if not self.base_runs_dir.exists():
            return summaries

        for entry in self.base_runs_dir.iterdir():
            if entry.is_dir() and (entry / "run_state.json").is_file():
                try:
                    run = self.load_run(entry.name)
                    dur = None
                    if run.started_at and run.completed_at:
                        s_dt = datetime.datetime.fromisoformat(run.started_at)
                        c_dt = datetime.datetime.fromisoformat(run.completed_at)
                        dur = (c_dt - s_dt).total_seconds()
                    summaries.append(RunSummary(
                        run_id=run.run_id,
                        task=run.task,
                        project=run.project,
                        workflow_id=run.workflow_id,
                        status=run.status,
                        dry_run=run.dry_run,
                        created_at=run.created_at,
                        duration_seconds=dur,
                        total_tokens=run.telemetry.total_tokens,
                        total_cost_usd=run.telemetry.total_cost_usd,
                        branch_name=run.branch_name
                    ))
                except Exception:
                    continue

        summaries.sort(key=lambda s: s.created_at, reverse=True)
        return summaries[:limit]

    def start_run(self, run_id: str) -> Run:
        run = self.load_run(run_id)
        run.status = RunStatus.RUNNING
        run.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if run.steps and not run.current_step_id:
            run.current_step_id = run.steps[0].step_id
            run.steps[0].status = StepStatus.RUNNING
            run.steps[0].started_at = run.started_at
        self.save_run(run)
        self.event_bus.publish(RunEvent(
            run_id=run_id,
            event_type=EventType.RUN_STARTED,
            payload={"started_at": run.started_at}
        ))
        return run

    def resume_run(self, run_id: str, from_step_id: Optional[str] = None) -> Run:
        """
        Resumes a failed or interrupted run from the failed step.
        Crucial requirement: earlier completed steps are NOT re-executed.
        """
        run = self.load_run(run_id)
        if run.status == RunStatus.COMPLETED:
            raise ValueError(f"Run {run_id} is already completed; cannot resume.")

        # Determine target resume step index
        target_idx = -1
        if from_step_id:
            for idx, s in enumerate(run.steps):
                if s.step_id == from_step_id:
                    target_idx = idx
                    break
            if target_idx == -1:
                raise ValueError(f"Step {from_step_id} not found in run {run_id}")
        else:
            # Find the first step that is not COMPLETED
            for idx, s in enumerate(run.steps):
                if s.status != StepStatus.COMPLETED:
                    target_idx = idx
                    break

        if target_idx == -1:
            # All steps were completed
            run.status = RunStatus.COMPLETED
            self.save_run(run)
            return run

        # Reset target step and subsequent steps, leaving prior steps intact
        for i in range(target_idx, len(run.steps)):
            run.steps[i].status = StepStatus.PENDING
            run.steps[i].error = None

        run.status = RunStatus.RUNNING
        run.current_step_id = run.steps[target_idx].step_id
        run.error = None
        self.save_run(run)

        self.event_bus.publish(RunEvent(
            run_id=run_id,
            event_type=EventType.RUN_RESUMED,
            payload={
                "from_step_id": run.steps[target_idx].step_id,
                "target_step_index": target_idx
            }
        ))
        return run

    def replay_run(self, run_id: str, callback: Callable[[RunEvent], None]) -> None:
        """Streams historical events for replay in UI or terminal."""
        events = self.event_bus.get_events(run_id)
        for ev in events:
            callback(ev)

    def record_run_telemetry(self, run_id: str) -> RunTelemetry:
        """Derives exact telemetry from SQLite telemetry_records scoped strictly to run_id."""
        telemetry_dict = get_run_telemetry(run_id)
        run = self.load_run(run_id)
        run.telemetry = RunTelemetry.model_validate(telemetry_dict)
        self.save_run(run)
        self.event_bus.publish(RunEvent(
            run_id=run_id,
            event_type=EventType.TELEMETRY_UPDATED,
            payload=run.telemetry.model_dump()
        ))
        return run.telemetry

    def finish_run(self, run_id: str, status: RunStatus, error: Optional[str] = None) -> Run:
        run = self.load_run(run_id)
        run.status = status
        run.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        run.error = error

        # Pull final exact scoped telemetry
        telemetry_dict = get_run_telemetry(run_id)
        run.telemetry = RunTelemetry.model_validate(telemetry_dict)

        self.save_run(run)

        evt_type = EventType.RUN_COMPLETED if status == RunStatus.COMPLETED else EventType.RUN_FAILED
        self.event_bus.publish(RunEvent(
            run_id=run_id,
            event_type=evt_type,
            payload={
                "status": status.value,
                "error": error,
                "completed_at": run.completed_at,
                "total_tokens": run.telemetry.total_tokens,
                "total_cost_usd": run.telemetry.total_cost_usd
            }
        ))
        return run

    def resolve_gate(
        self,
        run_id: str,
        gate_id: str,
        action: Union[GateAction, str],
        payload: Optional[Dict[str, Any]] = None,
        feedback: Optional[str] = None
    ) -> Run:
        action_enum = GateAction(action) if isinstance(action, str) else action
        run = self.load_run(run_id)

        # 1. Determine target step
        target_step_id = None
        if run.gate_state and run.gate_state.step_id:
            target_step_id = run.gate_state.step_id
        elif run.current_step_id:
            target_step_id = run.current_step_id

        # Fallback: locate step by step_id in gate_id
        if not target_step_id or not any(s.step_id == target_step_id for s in run.steps):
            for s in run.steps:
                if s.step_id in gate_id:
                    target_step_id = s.step_id
                    break

        target_step = next((s for s in run.steps if s.step_id == target_step_id), None)

        # 2. Determine gate type (post-execution vs pre-execution)
        is_post_execution = False
        if "post_execution" in gate_id:
            is_post_execution = True
        elif "pre_execution" in gate_id or "pre_" in gate_id:
            is_post_execution = False
        elif target_step:
            step_defs = run.metadata.get("step_defs", []) if run.metadata else []
            s_def = next((sd for sd in step_defs if sd.get("id") == target_step.step_id), None)
            if s_def and s_def.get("gate", {}).get("gate_type") == "post_execution":
                is_post_execution = True
            elif target_step.output is not None or target_step.completed_at is not None:
                is_post_execution = True

        # 3. Handle payload persistence
        if payload is not None:
            run.payload = payload
            if target_step:
                if target_step.output is None:
                    target_step.output = {"payload": payload}
                elif isinstance(target_step.output, dict):
                    target_step.output["payload"] = payload
            # Immediately persist edited payload to context_payload.json
            payload_file = self.get_context_payload_file(run.run_id)
            tmp_payload = payload_file.with_suffix(".tmp")
            with open(tmp_payload, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            tmp_payload.replace(payload_file)
        elif run.payload:
            # Ensure existing payload is mirrored to context_payload.json on disk
            payload_file = self.get_context_payload_file(run.run_id)
            if not payload_file.is_file():
                tmp_payload = payload_file.with_suffix(".tmp")
                with open(tmp_payload, "w", encoding="utf-8") as f:
                    json.dump(run.payload, f, indent=2)
                tmp_payload.replace(payload_file)

        # 4. State transitions based on action
        if action_enum in (GateAction.APPROVE, GateAction.EDIT_AND_APPROVE):
            gate_status = "approved" if action_enum == GateAction.APPROVE else "edited_and_approved"
            run.status = RunStatus.RUNNING
            if target_step:
                if is_post_execution:
                    target_step.status = StepStatus.COMPLETED
                    if not target_step.completed_at:
                        target_step.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                else:
                    target_step.status = StepStatus.PENDING

        elif action_enum == GateAction.ABORT:
            gate_status = "aborted"
            run.status = RunStatus.ABORTED
            if target_step and target_step.status == StepStatus.WAITING_GATE:
                target_step.status = StepStatus.FAILED

        elif action_enum == GateAction.REJECT:
            gate_status = "rejected"
            run.status = RunStatus.RUNNING
            if target_step:
                target_step.status = StepStatus.PENDING

        else:
            gate_status = "pending"

        # 5. Update gate state
        run.gate_state = GateState(
            gate_id=gate_id,
            step_id=target_step_id or (run.current_step_id or ""),
            status=gate_status,
            payload_snapshot=payload or run.payload,
            feedback=feedback,
            resolved_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
        )

        self.save_run(run)

        self.event_bus.publish(RunEvent(
            run_id=run_id,
            event_type=EventType.GATE_RESOLVED,
            payload={
                "gate_id": gate_id,
                "step_id": target_step_id,
                "action": action_enum.value,
                "feedback": feedback
            }
        ))
        return run

    def resolve_budget(
        self,
        run_id: str,
        decision: BudgetDecision,
        cheaper_model: Optional[str] = None
    ) -> Run:
        run = self.load_run(run_id)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if not run.budget_state:
            run.budget_state = BudgetState(
                run_id=run_id,
                step_id=run.current_step_id or "",
                current_spend_usd=run.telemetry.total_cost_usd,
                budget_limit_usd=25.0,
                status="resolved",
                decision=decision,
                suggested_cheaper_model=cheaper_model,
                resolved_at=now_iso
            )
        else:
            run.budget_state.decision = decision
            run.budget_state.status = "resolved"
            run.budget_state.resolved_at = now_iso
            if cheaper_model:
                run.budget_state.suggested_cheaper_model = cheaper_model

        if cheaper_model:
            run.model_override = cheaper_model

        if decision == BudgetDecision.PAUSE:
            run.status = RunStatus.PAUSED
        else:
            run.status = RunStatus.RUNNING

        self.save_run(run)
        self.event_bus.publish(RunEvent(
            run_id=run_id,
            event_type=EventType.BUDGET_RESOLVED,
            payload={
                "decision": decision.value,
                "cheaper_model": cheaper_model
            }
        ))
        return run

    def finish_worktree(
        self,
        run_id: str,
        action: Literal["merge", "keep", "discard"],
        target_branch: str = "main",
        repo_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """Coordinates worktree teardown choices with WorktreeManager."""
        from src.engine.worktree_manager import WorktreeManager
        run = self.load_run(run_id)
        wm = WorktreeManager()

        r_path = repo_path or Path(run.worktree_path or ".").parent.parent.parent
        res_dict = {}

        if action == "merge":
            res = wm.merge_worktree(r_path, run_id, target_branch=target_branch, require_approval=True)
            res_dict = {"success": res.success, "message": res.message, "commit": res.merged_commit}
            run.worktree_action = WorktreeAction.MERGE
        elif action == "keep":
            res = wm.keep_worktree(r_path, run_id)
            res_dict = {"success": res.success, "message": res.message, "commit": res.commit_hash}
            run.worktree_action = WorktreeAction.KEEP
        elif action == "discard":
            res = wm.discard_worktree(r_path, run_id)
            res_dict = {"success": res.success, "message": res.message}
            run.worktree_action = WorktreeAction.DISCARD

        self.save_run(run)
        self.event_bus.publish(RunEvent(
            run_id=run_id,
            event_type=EventType.WORKTREE_RESOLVED,
            payload={"action": action, "result": res_dict}
        ))
        return res_dict
