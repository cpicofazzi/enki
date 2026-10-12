"""
src/engine/models.py
Core typed data structures and domain models for the Enki Shared Engine.
Built using Pydantic v2.
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field
import datetime


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_GATE = "waiting_gate"
    WAITING_BUDGET = "waiting_budget"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_GATE = "waiting_gate"
    WAITING_BUDGET = "waiting_budget"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class EventType(str, Enum):
    RUN_CREATED = "run_created"
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_PAUSED = "run_paused"
    RUN_RESUMED = "run_resumed"
    RUN_ABORTED = "run_aborted"
    STEP_STARTED = "step_started"
    STEP_PROGRESS = "step_progress"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_SKIPPED = "step_skipped"
    STEP_RETRY = "step_retry"
    LOG_CHUNK = "log_chunk"
    GATE_WAITING = "gate_waiting"
    GATE_RESOLVED = "gate_resolved"
    BUDGET_STOP = "budget_stop"
    BUDGET_RESOLVED = "budget_resolved"
    TELEMETRY_UPDATED = "telemetry_updated"
    WORKTREE_CREATED = "worktree_created"
    WORKTREE_RESOLVED = "worktree_resolved"


class GateAction(str, Enum):
    APPROVE = "approve"
    EDIT_AND_APPROVE = "edit_and_approve"
    REJECT = "reject"
    ABORT = "abort"


class BudgetDecision(str, Enum):
    CONTINUE = "continue"
    PAUSE = "pause"
    SWITCH_CHEAPER = "switch_cheaper"


class WorktreeAction(str, Enum):
    MERGE = "merge"
    KEEP = "keep"
    DISCARD = "discard"
    NONE = "none"


class RoutingDecision(BaseModel):
    model: str
    task_category: str
    complexity_tier: str
    reason: str
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


class GateState(BaseModel):
    gate_id: str
    step_id: str
    created_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    status: Literal["pending", "approved", "edited_and_approved", "rejected", "aborted"] = "pending"
    payload_snapshot: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None
    resolved_at: Optional[str] = None


class BudgetState(BaseModel):
    run_id: str
    step_id: str
    current_spend_usd: float
    budget_limit_usd: float
    suggested_cheaper_model: Optional[str] = None
    suggested_reason: Optional[str] = None
    status: Literal["pending", "resolved"] = "pending"
    decision: Optional[BudgetDecision] = None
    resolved_at: Optional[str] = None


class RunTelemetry(BaseModel):
    run_id: str
    calls_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    by_agent: List[Dict[str, Any]] = Field(default_factory=list)
    by_model: List[Dict[str, Any]] = Field(default_factory=list)
    records: List[Dict[str, Any]] = Field(default_factory=list)


class StepState(BaseModel):
    step_id: str
    step_type: str  # e.g., "context_extraction", "coding", "verification", "sync", "review"
    name: str
    status: StepStatus = StepStatus.PENDING
    model: Optional[str] = None
    routing_decision: Optional[RoutingDecision] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    attempts: int = 0
    max_attempts: int = 1
    error: Optional[str] = None
    output: Optional[Dict[str, Any]] = None


class RunEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S%f')}")
    run_id: str
    event_type: EventType
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    payload: Dict[str, Any] = Field(default_factory=dict)


class Run(BaseModel):
    run_id: str
    task: str
    project: str = "General"
    workflow_id: str = "four_step_pipeline"
    status: RunStatus = RunStatus.PENDING
    dry_run: bool = False
    gateway: str = "openrouter"
    model_override: Optional[str] = None
    preset: Optional[str] = None
    local_research: bool = True
    find_research: bool = False
    created_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    worktree_path: Optional[str] = None
    branch_name: Optional[str] = None
    base_branch: str = "HEAD"
    worktree_action: WorktreeAction = WorktreeAction.NONE
    current_step_id: Optional[str] = None
    steps: List[StepState] = Field(default_factory=list)
    payload: Optional[Dict[str, Any]] = None
    telemetry: RunTelemetry = Field(default_factory=lambda: RunTelemetry(run_id=""))
    gate_state: Optional[GateState] = None
    budget_state: Optional[BudgetState] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    run_id: str
    task: str
    project: str
    workflow_id: str
    status: RunStatus
    dry_run: bool
    created_at: str
    duration_seconds: Optional[float] = None
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    branch_name: Optional[str] = None
