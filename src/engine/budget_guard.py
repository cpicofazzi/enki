"""
src/engine/budget_guard.py
Real-time budget limit intercept and safety protocol for Enki (F44).
Monitors cumulative monthly spend across gateways from SQLite telemetry,
checks threshold against config.telemetry.monthly_budget_usd ($25.00),
and intercepts execution before model completion or step dispatch.
Exposes 3 user decisions:
1. 'continue': Proceed beyond budget for this run.
2. 'pause': Halt/pause the run until budget increases or user resumes.
3. 'switch_cheaper': Automatically switch run model to a cost-effective alternative.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Literal
from pydantic import BaseModel

from src.config import load_config
from src.token_tracker import get_summary
from src.engine.models import Run, RunStatus, StepStatus, BudgetDecision, BudgetState, EventType, RunEvent
from src.engine.events import EventBus, get_event_bus


class BudgetLimitReachedError(Exception):
    """Raised when monthly spend budget limit is reached."""
    pass


# Cost-effective fallback champions
CHEAPER_MODEL_FALLBACKS: Dict[str, str] = {
    "openrouter": "deepseek/deepseek-chat",
    "opencode_zen": "qwen/qwen-2.5-coder-32b-instruct",
}


class BudgetCheckResult(BaseModel):
    is_budget_exceeded: bool
    current_spend_usd: float
    monthly_budget_usd: float
    decision_required: bool
    suggested_cheaper_model: str


class BudgetGuard:
    def __init__(
        self,
        config_path: Optional[Path] = None,
        event_bus: Optional[EventBus] = None,
        budget_override: Optional[float] = None
    ):
        self.config_path = config_path
        self.event_bus = event_bus or get_event_bus()
        self.budget_override = budget_override

    def get_monthly_budget(self) -> float:
        if self.budget_override is not None:
            return float(self.budget_override)
        cfg = load_config()
        return float(cfg.get("telemetry", {}).get("monthly_budget_usd", 25.0))

    def get_current_spend(self) -> float:
        summary = get_summary(days=30)
        return float(summary.get("total_cost_usd", 0.0))

    def check_budget(self, gateway: str = "openrouter") -> BudgetCheckResult:
        budget_limit = self.get_monthly_budget()
        current_spend = self.get_current_spend()
        is_exceeded = current_spend >= budget_limit and budget_limit > 0.0

        suggested = CHEAPER_MODEL_FALLBACKS.get(gateway, "deepseek/deepseek-chat")

        return BudgetCheckResult(
            is_budget_exceeded=is_exceeded,
            current_spend_usd=current_spend,
            monthly_budget_usd=budget_limit,
            decision_required=is_exceeded,
            suggested_cheaper_model=suggested
        )

    def intercept_before_call(
        self,
        run: Run,
        step_id: str,
        gateway: str = "openrouter",
        raise_on_intercept: bool = True
    ) -> BudgetCheckResult:
        """
        Intercepts execution before an AI model API call if monthly budget is reached.
        Emits BUDGET_STOP event and sets run to WAITING_BUDGET unless decision was already made.
        """
        # If budget decision was already resolved to CONTINUE or SWITCH_CHEAPER, allow pass
        if run.budget_state and run.budget_state.status == "resolved":
            if run.budget_state.decision in (BudgetDecision.CONTINUE, BudgetDecision.SWITCH_CHEAPER):
                check = self.check_budget(gateway)
                return check

        check = self.check_budget(gateway)
        if not check.is_budget_exceeded:
            return check

        # Budget exceeded - trigger intercept
        run.status = RunStatus.WAITING_BUDGET
        run.budget_state = BudgetState(
            run_id=run.run_id,
            step_id=step_id,
            current_spend_usd=check.current_spend_usd,
            budget_limit_usd=check.monthly_budget_usd,
            status="pending",
            suggested_cheaper_model=check.suggested_cheaper_model
        )

        for s in run.steps:
            if s.step_id == step_id:
                s.status = StepStatus.WAITING_BUDGET
                break

        # Publish event
        self.event_bus.publish(RunEvent(
            run_id=run.run_id,
            event_type=EventType.BUDGET_STOP,
            payload={
                "step_id": step_id,
                "current_spend_usd": check.current_spend_usd,
                "monthly_budget_usd": check.monthly_budget_usd,
                "suggested_cheaper_model": check.suggested_cheaper_model,
                "choices": ["continue", "pause", "switch_cheaper"]
            }
        ))

        if raise_on_intercept:
            from src.engine.workflow_engine import BudgetLimitReachedError
            raise BudgetLimitReachedError(
                f"Monthly budget limit ${check.monthly_budget_usd:.2f} reached (current: ${check.current_spend_usd:.4f}). "
                f"Run {run.run_id} is waiting for user decision (continue | pause | switch_cheaper)."
            )

        return check

    def apply_decision(
        self,
        run: Run,
        decision: BudgetDecision,
        cheaper_model: Optional[str] = None
    ) -> Run:
        """Applies user budget decision (continue, pause, switch_cheaper)."""
        check = self.check_budget(run.gateway)
        if not run.budget_state:
            run.budget_state = BudgetState(
                run_id=run.run_id,
                step_id=run.current_step_id or "",
                current_spend_usd=check.current_spend_usd,
                budget_limit_usd=check.monthly_budget_usd,
                status="resolved",
                decision=decision,
                suggested_cheaper_model=cheaper_model or check.suggested_cheaper_model
            )
        else:
            run.budget_state.decision = decision
            run.budget_state.status = "resolved"
            if cheaper_model:
                run.budget_state.suggested_cheaper_model = cheaper_model

        if decision == BudgetDecision.SWITCH_CHEAPER:
            target_model = cheaper_model or check.suggested_cheaper_model
            run.model_override = target_model
            for s in run.steps:
                if s.status == StepStatus.WAITING_BUDGET:
                    s.model = target_model
                    s.status = StepStatus.PENDING
            run.status = RunStatus.RUNNING

        elif decision == BudgetDecision.CONTINUE:
            for s in run.steps:
                if s.status == StepStatus.WAITING_BUDGET:
                    s.status = StepStatus.PENDING
            run.status = RunStatus.RUNNING

        elif decision == BudgetDecision.PAUSE:
            run.status = RunStatus.PAUSED

        self.event_bus.publish(RunEvent(
            run_id=run.run_id,
            event_type=EventType.BUDGET_RESOLVED,
            payload={
                "decision": decision.value,
                "cheaper_model": cheaper_model or check.suggested_cheaper_model
            }
        ))
        return run
