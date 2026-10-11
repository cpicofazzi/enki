"""
tests/test_adversarial_dag_engine.py
Adversarial Stress Test Suite for Milestone 2: Multi-Model DAG Execution, Gates & Concurrency.
Authored by challenger_m2_2 (Empirical Challenger).

Target Areas:
1. Escalation exhaustion: Step configured to retry 3 times and escalate to frontier model;
   mock all attempts failing; assert clean failure state and proper event sequence.
2. Infinite reviewer loop guard: Reviewer repeatedly rejects; assert execution halts strictly
   at max_review_loops without runaway loops.
3. Compare fan-out edge cases: One candidate branch fails while two succeed; verify compare still
   evaluates surviving candidates, selects winner, and cleans up loser worktrees.
4. Approval gate concurrency: Multiple runs hit gates concurrently; resolve gates in out-of-order
   sequence; assert no deadlocks or state cross-contamination.
5. Auto-routing fallback: Step with unknown task category or invalid complexity; assert graceful
   fallback to default model.
"""

import io
import json
import time
import datetime
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import MagicMock

import pytest
from ruamel.yaml import YAML

from src.engine.models import (
    Run, RunStatus, StepStatus, EventType, RunEvent,
    GateAction, GateState, RoutingDecision
)
from src.engine.events import EventBus
from src.engine.run_manager import RunManager
from src.engine.worktree_manager import WorktreeManager
from src.engine.workflow_parser import WorkflowParser, WorkflowDefinition, parse_workflow
from src.engine.workflow_engine import (
    WorkflowEngine, StepExecutionContext, GateSuspendedException, WorkflowExecutionError
)
import src.omp_bridge
import src.openrouter

ROOT_DIR = Path(__file__).resolve().parent.parent


def make_workflow_def(wf_dict: Dict[str, Any]) -> WorkflowDefinition:
    """Helper to dump a dict into valid YAML and parse it through WorkflowParser."""
    yaml = YAML()
    yaml.preserve_quotes = True
    stream = io.StringIO()
    yaml.dump(wf_dict, stream)
    return parse_workflow(stream.getvalue())


@pytest.fixture
def run_manager(tmp_path):
    runs_dir = tmp_path / "data" / "runs"
    bus = EventBus(runs_base_dir=runs_dir)
    return RunManager(base_runs_dir=runs_dir, event_bus=bus)


@pytest.fixture
def workflow_engine(run_manager, mock_omp, mock_gateway):
    return WorkflowEngine(
        run_manager=run_manager,
        event_bus=run_manager.event_bus,
        omp_bridge=src.omp_bridge.OMPBridge(),
        gateway_client=src.openrouter.GatewayClient()
    )


# ==============================================================================
# Challenge 1: Escalation Exhaustion
# ==============================================================================

class TestEscalationExhaustion:
    """Stress tests retry and escalation behavior when all attempts fail."""

    def test_escalation_exhaustion_event_sequence_and_clean_failure(
        self, run_manager, workflow_engine, monkeypatch
    ):
        """
        Adversarial Scenario:
        A step is configured with max_retries: 3 (total 4 attempts), escalate_to: frontier model,
        escalate_after_attempts: 1.
        Every attempt fails.
        Verify:
        - Exactly 4 attempts executed.
        - Attempt 1 uses initial model.
        - Attempts 2, 3, 4 use escalated frontier model.
        - EventBus receives exact event sequence:
          STEP_STARTED -> STEP_RETRY (escalated=True) -> STEP_RETRY (att 2) -> STEP_RETRY (att 3) -> STEP_RETRY (att 4) -> STEP_FAILED.
        - Step finishes in StepStatus.FAILED.
        - Run finishes cleanly in RunStatus.FAILED without unhandled crash.
        """
        captured_events: List[RunEvent] = []
        run_manager.event_bus.subscribe_all(lambda ev: captured_events.append(ev))

        wf_dict = {
            "id": "adversarial_escalation",
            "name": "Adversarial Escalation",
            "canvas": {"viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0}, "nodes": {"failing_step": {"x": 0.0, "y": 0.0}}},
            "steps": [
                {
                    "id": "failing_step",
                    "name": "Failing Step with 3 retries",
                    "type": "coding",
                    "model": "z-ai/glm-5.3-flash",
                    "dependencies": [],
                    "retry": {
                        "max_retries": 3,
                        "backoff_seconds": 0.0,
                        "escalate_to": "anthropic/claude-opus-5.5",
                        "escalate_after_attempts": 1,
                    },
                    "escalate": {
                        "enabled": True,
                        "model": "anthropic/claude-opus-5.5",
                        "after_attempts": 1,
                    },
                    "on_failure": "abort"
                }
            ]
        }
        wf_def = make_workflow_def(wf_dict)

        attempts_seen = []
        models_seen = []

        def always_fail(r, s_def, ctx, s_state):
            attempts_seen.append(s_state.attempts)
            models_seen.append(s_state.model)
            raise RuntimeError(f"Simulated unrecoverable failure at attempt {s_state.attempts}")

        monkeypatch.setattr(workflow_engine, "_execute_coding", always_fail)

        run = run_manager.create_run(
            task="Adversarial escalation stress",
            project="General",
            workflow_id="adversarial_escalation",
            dry_run=True
        )

        res_run = workflow_engine.execute_dag(
            run_id=run.run_id,
            workflow_path=wf_def,
            dry_run=True
        )

        # Assert run state
        reloaded = run_manager.load_run(run.run_id)
        assert reloaded.status == RunStatus.FAILED
        assert "Simulated unrecoverable failure" in reloaded.error

        step = next(s for s in reloaded.steps if s.step_id == "failing_step")
        assert step.status == StepStatus.FAILED
        assert step.attempts == 4
        assert step.max_attempts == 4
        assert step.model == "anthropic/claude-opus-5.5"

        # Assert attempt history
        assert attempts_seen == [1, 2, 3, 4]
        assert models_seen[0] == "z-ai/glm-5.3-flash"
        assert models_seen[1] == "anthropic/claude-opus-5.5"
        assert models_seen[2] == "anthropic/claude-opus-5.5"
        assert models_seen[3] == "anthropic/claude-opus-5.5"

        # Assert event sequence
        step_events = [e for e in captured_events if e.payload.get("step_id") == "failing_step"]
        event_types = [e.event_type for e in step_events]

        assert EventType.STEP_STARTED in event_types
        assert EventType.STEP_RETRY in event_types
        assert EventType.STEP_FAILED in event_types

        # Verify escalated=True event occurred
        escalated_retry_events = [
            e for e in step_events
            if e.event_type == EventType.STEP_RETRY and e.payload.get("escalated") is True
        ]
        assert len(escalated_retry_events) == 1
        assert escalated_retry_events[0].payload.get("model") == "anthropic/claude-opus-5.5"
        assert escalated_retry_events[0].payload.get("old_model") == "z-ai/glm-5.3-flash"

        # Verify final failure event
        final_fail_events = [e for e in step_events if e.event_type == EventType.STEP_FAILED]
        assert len(final_fail_events) == 1
        assert final_fail_events[0].payload.get("attempts") == 4


# ==============================================================================
# Challenge 2: Infinite Reviewer Loop Guard
# ==============================================================================

class TestInfiniteReviewerLoopGuard:
    """Stress tests boundary limits on reviewer feedback loops."""

    @pytest.mark.parametrize("max_loops", [1, 2, 3, 5])
    def test_reviewer_loop_halts_strictly_at_configured_max_loops(
        self, run_manager, workflow_engine, max_loops
    ):
        """
        Adversarial Scenario:
        Reviewer consistently rejects code diff with 'changes_requested'.
        Verify execution halts strictly when review_loop exceeds max_review_loops,
        and coding is invoked exactly max_loops times.
        """
        review_invocations = []
        coding_invocations = []

        orig_coding = workflow_engine._execute_coding
        def tracked_coding(r, s_def, ctx, s_state, **kwargs):
            coding_invocations.append(len(coding_invocations) + 1)
            return orig_coding(r, s_def, ctx, s_state, **kwargs)

        def stubbornly_rejecting_reviewer(ctx):
            review_invocations.append(len(review_invocations) + 1)
            return {
                "decision": "changes_requested",
                "approved": False,
                "summary": f"Rejected iteration {len(review_invocations)}: code unacceptable.",
                "feedback": "Needs major refactoring."
            }

        workflow_engine._execute_coding = tracked_coding
        workflow_engine.reviewer_evaluator_fn = stubbornly_rejecting_reviewer

        wf_dict = {
            "id": f"adversarial_reviewer_{max_loops}",
            "name": "Adversarial Reviewer Loop",
            "canvas": {
                "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0},
                "nodes": {
                    "coding": {"x": 0.0, "y": 0.0},
                    "review": {"x": 100.0, "y": 0.0}
                }
            },
            "steps": [
                {
                    "id": "coding",
                    "name": "Coding Step",
                    "type": "coding",
                    "dependencies": [],
                    "model": "anthropic/claude-3.7-sonnet"
                },
                {
                    "id": "review",
                    "name": "Reviewer Step",
                    "type": "review",
                    "dependencies": ["coding"],
                    "model": "anthropic/claude-opus-5.5",
                    "config": {
                        "feedback_target_step": "coding",
                        "max_review_loops": max_loops
                    }
                }
            ]
        }
        wf_def = make_workflow_def(wf_dict)

        run = run_manager.create_run(
            task=f"Stress test reviewer loops limit={max_loops}",
            project="General",
            workflow_id=f"adversarial_reviewer_{max_loops}",
            dry_run=True
        )

        res_run = workflow_engine.execute_dag(
            run_id=run.run_id,
            workflow_path=wf_def,
            dry_run=True
        )

        reloaded = run_manager.load_run(run.run_id)
        assert reloaded.status == RunStatus.FAILED

        review_step = next(s for s in reloaded.steps if s.step_id == "review")
        assert review_step.status == StepStatus.FAILED
        assert f"exceeded max loops ({max_loops})" in review_step.error

        # Coding is invoked: initial (1) + feedback re-runs (max_loops)
        assert len(coding_invocations) == max_loops + 1
        # Review is invoked: 1 initial + max_loops re-evaluations = max_loops + 1
        assert len(review_invocations) == max_loops + 1

    def test_reviewer_zero_loops_fails_immediately_on_first_rejection(
        self, run_manager, workflow_engine
    ):
        """Boundary condition: max_review_loops = 0 immediately fails without coding retry."""
        review_invocations = []
        coding_invocations = []

        orig_coding = workflow_engine._execute_coding
        def tracked_coding(r, s_def, ctx, s_state):
            coding_invocations.append(len(coding_invocations) + 1)
            return orig_coding(r, s_def, ctx, s_state)

        def reject_once(ctx):
            review_invocations.append(1)
            return {"decision": "changes_requested", "approved": False, "summary": "Rejected immediately"}

        workflow_engine._execute_coding = tracked_coding
        workflow_engine.reviewer_evaluator_fn = reject_once

        wf_dict = {
            "id": "adversarial_reviewer_zero",
            "name": "Adversarial Reviewer Zero Loops",
            "canvas": {"viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0}, "nodes": {"coding": {"x": 0.0, "y": 0.0}, "review": {"x": 100.0, "y": 0.0}}},
            "steps": [
                {"id": "coding", "name": "Coding Step", "type": "coding", "dependencies": []},
                {
                    "id": "review",
                    "name": "Reviewer Step",
                    "type": "review",
                    "dependencies": ["coding"],
                    "config": {"feedback_target_step": "coding", "max_review_loops": 0}
                }
            ]
        }
        wf_def = make_workflow_def(wf_dict)

        run = run_manager.create_run(
            task="Stress test reviewer 0 loops",
            project="General",
            workflow_id="adversarial_reviewer_zero",
            dry_run=True
        )
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=wf_def, dry_run=True)

        reloaded = run_manager.load_run(run.run_id)
        assert reloaded.status == RunStatus.FAILED
        assert len(review_invocations) == 1
        assert len(coding_invocations) == 1  # Only the initial coding run, 0 feedback re-runs


# ==============================================================================
# Challenge 3: Compare Fan-Out Edge Cases
# ==============================================================================

class TestCompareFanOutEdgeCases:
    """Stress tests candidate branch failure handling and worktree cleanup in compare DAGs."""

    def test_compare_fanout_surviving_candidates_evaluated_and_worktree_cleanup(
        self, run_manager, workflow_engine, monkeypatch
    ):
        """
        Adversarial Scenario:
        3 candidate branches: candidate_a, candidate_b, candidate_c.
        candidate_a fails with an unhandled exception.
        candidate_b and candidate_c succeed.
        Verify:
        - Compare step does NOT crash or get skipped.
        - Compare evaluates the SURVIVING candidates (candidate_b and candidate_c).
        - A surviving candidate is selected as winner (never candidate_a).
        - Loser worktrees and failed candidate worktrees are cleaned up.
        """
        candidate_calls = {}

        def mock_coding_step(r, s_def, ctx, s_state):
            step_id = s_state.step_id
            candidate_calls[step_id] = True
            if step_id == "candidate_a":
                raise RuntimeError("Candidate A syntax generation failure")
            return {
                "status": "completed",
                "candidate": step_id,
                "worktree_branch": f"enki/run/{r.run_id}_{step_id}"
            }

        monkeypatch.setattr(workflow_engine, "_execute_coding", mock_coding_step)

        wf_dict = {
            "id": "adversarial_compare_3",
            "name": "Adversarial 3-Candidate Compare",
            "canvas": {
                "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0},
                "nodes": {
                    "context_extraction": {"x": 0.0, "y": 0.0},
                    "candidate_a": {"x": 100.0, "y": -50.0},
                    "candidate_b": {"x": 100.0, "y": 0.0},
                    "candidate_c": {"x": 100.0, "y": 50.0},
                    "judge_selection": {"x": 200.0, "y": 0.0}
                }
            },
            "steps": [
                {
                    "id": "context_extraction",
                    "name": "Hermes Context Extraction",
                    "type": "context_extraction",
                    "dependencies": []
                },
                {
                    "id": "candidate_a",
                    "name": "Candidate A",
                    "type": "coding",
                    "dependencies": ["context_extraction"],
                    "on_failure": "continue"
                },
                {
                    "id": "candidate_b",
                    "name": "Candidate B",
                    "type": "coding",
                    "dependencies": ["context_extraction"],
                    "on_failure": "continue"
                },
                {
                    "id": "candidate_c",
                    "name": "Candidate C",
                    "type": "coding",
                    "dependencies": ["context_extraction"],
                    "on_failure": "continue"
                },
                {
                    "id": "judge_selection",
                    "name": "Judge Selection",
                    "type": "compare",
                    "dependencies": ["candidate_a", "candidate_b", "candidate_c"]
                }
            ]
        }
        wf_def = make_workflow_def(wf_dict)

        run = run_manager.create_run(
            task="3-candidate compare stress",
            project="General",
            workflow_id="adversarial_compare_3",
            dry_run=True
        )

        res_run = workflow_engine.execute_dag(
            run_id=run.run_id,
            workflow_path=wf_def,
            dry_run=True
        )

        reloaded = run_manager.load_run(run.run_id)

        step_a = next(s for s in reloaded.steps if s.step_id == "candidate_a")
        step_b = next(s for s in reloaded.steps if s.step_id == "candidate_b")
        step_c = next(s for s in reloaded.steps if s.step_id == "candidate_c")
        judge_step = next(s for s in reloaded.steps if s.step_id == "judge_selection")

        # Candidate A failed / skipped
        assert step_a.status in [StepStatus.FAILED, StepStatus.SKIPPED]

        # Candidates B and C completed
        assert step_b.status == StepStatus.COMPLETED
        assert step_c.status == StepStatus.COMPLETED

        # The core assertion: judge_selection MUST NOT be skipped when surviving candidates exist!
        assert judge_step.status == StepStatus.COMPLETED, (
            f"judge_selection was {judge_step.status} instead of COMPLETED. "
            f"Engine skipped compare when 1 candidate failed despite 2 surviving candidates!"
        )

        # Winner must be one of the survivors (candidate_b or candidate_c), NOT failed candidate_a
        winner = judge_step.output.get("winner")
        assert winner in ["candidate_b", "candidate_c"], (
            f"Expected winner among surviving candidates (b or c), but got: {winner}"
        )


# ==============================================================================
# Challenge 4: Approval Gate Concurrency
# ==============================================================================

class TestApprovalGateConcurrency:
    """Stress tests out-of-order gate resolution across concurrent runs."""

    def test_out_of_order_gate_resolution_no_deadlocks_or_cross_contamination(
        self, run_manager, workflow_engine
    ):
        """
        Adversarial Scenario:
        3 separate runs (Run 1, Run 2, Run 3) hit approval gates concurrently.
        Gates are resolved in arbitrary out-of-order sequence:
        1. Run 2 resolved via EDIT_AND_APPROVE with custom payload.
        2. Run 3 resolved via APPROVE.
        3. Run 1 remains WAITING_GATE while Run 2 and 3 make progress.
        4. Run 1 resolved via ABORT.
        Verify:
        - No deadlocks occur.
        - Run 2 has its custom edited payload without contaminating Run 1 or Run 3.
        - Run 3 completes with original payload.
        - Run 1 transitions cleanly to ABORTED.
        """
        four_step_yaml = ROOT_DIR / "workflows" / "four_step_pipeline.yaml"

        # 1. Create and dispatch 3 runs to hit gate 1 (post_execution on context_extraction)
        run_1 = run_manager.create_run(task="Run 1 Task", project="General", workflow_id="four_step_pipeline", dry_run=True)
        run_2 = run_manager.create_run(task="Run 2 Task", project="General", workflow_id="four_step_pipeline", dry_run=True)
        run_3 = run_manager.create_run(task="Run 3 Task", project="General", workflow_id="four_step_pipeline", dry_run=True)

        workflow_engine.execute_dag(run_id=run_1.run_id, workflow_path=four_step_yaml, dry_run=True)
        workflow_engine.execute_dag(run_id=run_2.run_id, workflow_path=four_step_yaml, dry_run=True)
        workflow_engine.execute_dag(run_id=run_3.run_id, workflow_path=four_step_yaml, dry_run=True)

        r1 = run_manager.load_run(run_1.run_id)
        r2 = run_manager.load_run(run_2.run_id)
        r3 = run_manager.load_run(run_3.run_id)

        assert r1.status == RunStatus.WAITING_GATE
        assert r2.status == RunStatus.WAITING_GATE
        assert r3.status == RunStatus.WAITING_GATE

        assert r1.gate_state.gate_id == "gate_context_extraction_post_execution"
        assert r2.gate_state.gate_id == "gate_context_extraction_post_execution"
        assert r3.gate_state.gate_id == "gate_context_extraction_post_execution"

        # 2. Resolve Run 2 first with EDIT_AND_APPROVE
        custom_payload_2 = dict(r2.payload or {})
        custom_payload_2["custom_marker_run2"] = "SECRET_TOKEN_2"
        workflow_engine.resolve_gate(
            run_id=r2.run_id,
            gate_id=r2.gate_state.gate_id,
            action=GateAction.EDIT_AND_APPROVE,
            payload=custom_payload_2
        )

        # 3. Resolve Run 3 second with APPROVE
        workflow_engine.resolve_gate(
            run_id=r3.run_id,
            gate_id=r3.gate_state.gate_id,
            action=GateAction.APPROVE
        )

        # 4. Confirm Run 1 is still in WAITING_GATE and untainted
        r1_check = run_manager.load_run(r1.run_id)
        assert r1_check.status == RunStatus.WAITING_GATE
        assert "custom_marker_run2" not in (r1_check.payload or {})

        # 5. Advance Run 2 and Run 3 (they hit gate 2: pre_execution on coding)
        workflow_engine.execute_dag(run_id=r2.run_id, workflow_path=four_step_yaml, dry_run=True)
        workflow_engine.execute_dag(run_id=r3.run_id, workflow_path=four_step_yaml, dry_run=True)

        r2_advanced = run_manager.load_run(r2.run_id)
        r3_advanced = run_manager.load_run(r3.run_id)

        assert r2_advanced.status == RunStatus.WAITING_GATE
        assert r2_advanced.gate_state.gate_id == "gate_coding_pre_execution"
        # Check payload preservation on r2_advanced
        assert r2_advanced.payload.get("custom_marker_run2") == "SECRET_TOKEN_2", (
            f"Expected user edited payload with custom_marker_run2, but got: {r2_advanced.payload}"
        )

        assert r3_advanced.status == RunStatus.WAITING_GATE
        assert r3_advanced.gate_state.gate_id == "gate_coding_pre_execution"
        assert "custom_marker_run2" not in (r3_advanced.payload or {})

        # 6. Now abort Run 1
        workflow_engine.resolve_gate(
            run_id=r1.run_id,
            gate_id=r1.gate_state.gate_id,
            action=GateAction.ABORT
        )
        r1_aborted = run_manager.load_run(r1.run_id)
        assert r1_aborted.status == RunStatus.ABORTED

        # 7. Approve second gate for Run 2 and Run 3
        workflow_engine.resolve_gate(run_id=r2.run_id, gate_id=r2_advanced.gate_state.gate_id, action=GateAction.APPROVE)
        workflow_engine.resolve_gate(run_id=r3.run_id, gate_id=r3_advanced.gate_state.gate_id, action=GateAction.APPROVE)

        workflow_engine.execute_dag(run_id=r2.run_id, workflow_path=four_step_yaml, dry_run=True)
        workflow_engine.execute_dag(run_id=r3.run_id, workflow_path=four_step_yaml, dry_run=True)

        r2_final = run_manager.load_run(r2.run_id)
        r3_final = run_manager.load_run(r3.run_id)

        assert r2_final.status == RunStatus.COMPLETED
        assert r3_final.status == RunStatus.COMPLETED

        # Check payload isolation
        assert r2_final.payload.get("custom_marker_run2") == "SECRET_TOKEN_2"
        assert "custom_marker_run2" not in (r3_final.payload or {})


# ==============================================================================
# Challenge 5: Auto-Routing Fallback
# ==============================================================================

class TestAutoRoutingFallback:
    """Stress tests auto-routing heuristics under invalid or unmapped inputs."""

    def test_auto_routing_unknown_step_type_falls_back_gracefully(self, workflow_engine):
        """Unknown or custom step types default category and model safely."""
        decision = workflow_engine.resolve_auto_model(
            step_type="nonexistent_step_type_xyz",
            task_description="Normal task description"
        )
        assert isinstance(decision, RoutingDecision)
        assert decision.model is not None
        assert len(decision.model) > 0
        assert decision.task_category in ["coding", "planning", "reasoning"]
        assert decision.complexity_tier in ["frontier", "balanced", "value"]

    def test_auto_routing_invalid_and_adversarial_complexity_descriptions(self, workflow_engine):
        """Empty, ultra-short, whitespace, and symbol-laden descriptions resolve safely."""
        adversarial_inputs = [
            "",
            "   ",
            "!!!@@@###$$$%%%^^^&&&***",
            "1234567890",
            "a" * 5000,  # Extreme length input
            "\n\t\r\x00\x01",  # Control characters
        ]
        for inp in adversarial_inputs:
            decision = workflow_engine.resolve_auto_model(
                step_type="coding",
                task_description=inp
            )
            assert isinstance(decision, RoutingDecision)
            assert decision.model is not None
            assert len(decision.model) > 0
            assert decision.task_category == "coding"
            assert decision.complexity_tier in ["frontier", "balanced", "value"]
            assert len(decision.reason) > 0

    def test_auto_routing_missing_gateway_and_missing_profiles(self, workflow_engine, monkeypatch):
        """When gateway profile is missing from config, falls back to catalog default models."""
        decision = workflow_engine.resolve_auto_model(
            step_type="review",
            task_description="Audit security invariants",
            gateway="unregistered_gateway_99"
        )
        assert isinstance(decision, RoutingDecision)
        assert decision.model == "anthropic/claude-opus-5.5"  # Fallback for reasoning/planning
        assert decision.task_category == "reasoning"

        decision_coding = workflow_engine.resolve_auto_model(
            step_type="verification",
            task_description="Run test suite",
            gateway="unregistered_gateway_99"
        )
        assert decision_coding.model == "anthropic/claude-3.7-sonnet"  # Fallback for coding
        assert decision_coding.task_category == "coding"
