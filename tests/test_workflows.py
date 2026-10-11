"""
tests/test_workflows.py
Comprehensive test suite for Enki Milestone 2: Multi-Model Workflows & DAG Engine.
Covers features F12 through F20:
- F12: Workflows YAML Schema & Parser (schemas/workflow.schema.json, round-trip serialization)
- F13: DAG Workflow Execution Engine (topological tiers, dependency resolution)
- F14: Auto-Routing per Step (task_profiles, complexity reasoning)
- F15: Retry & Escalate Policy (switching to stronger model on repeated failure)
- F16: Reviewer Model Loop (evaluating code, feeding back to coder)
- F17: Fan-Out / Compare Engine (parallel candidate branches, diff comparison, winner selection)
- F18: Approval Gates (pre/post execution gates, 4 actions, non-blocking concurrency)
- F19: 5 Built-in Workflow Templates (four_step_pipeline, feature_and_reviewer, escalate_on_fail, compare, plan_only)
- F20: OpenRouter Catalog Service (24h TTL caching in data/openrouter_models_cache.json, fallback, config merging)
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
import jsonschema

from src.engine.models import (
    Run, RunStatus, StepStatus, EventType, RunEvent,
    GateAction, GateState, RoutingDecision
)
from src.engine.events import EventBus
from src.engine.run_manager import RunManager
from src.engine.worktree_manager import WorktreeManager
from src.engine.workflow_parser import (
    WorkflowParser, WorkflowDefinition, WorkflowSchemaError, WorkflowDAGError,
    detect_cycle_and_sort, load_workflow, parse_workflow
)
from src.engine.workflow_engine import (
    WorkflowEngine, StepExecutionContext, GateSuspendedException, WorkflowExecutionError
)
from src.openrouter_catalog import (
    OpenRouterCatalog, CatalogCache, ModelCatalogItem, ModelPricing
)
import src.omp_bridge
import src.openrouter

ROOT_DIR = Path(__file__).resolve().parent.parent


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def workflow_schema():
    schema_path = ROOT_DIR / "schemas" / "workflow.schema.json"
    assert schema_path.is_file(), f"Missing schema file: {schema_path}"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def builtin_workflow_paths():
    wf_dir = ROOT_DIR / "workflows"
    templates = sorted(list(wf_dir.glob("*.yaml")))
    assert len(templates) == 5, f"Expected 5 built-in templates, found {len(templates)}"
    return templates


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
# 1. Schema Validation Tests (F12, F19)
# ==============================================================================

class TestWorkflowSchemaValidation:
    """Verifies workflow YAML schema validation against schemas/workflow.schema.json."""

    def test_all_5_builtin_templates_validate_against_schema(self, workflow_schema, builtin_workflow_paths):
        """All 5 built-in workflow YAML files must strictly validate against the JSON schema."""
        yaml = YAML()
        yaml.preserve_quotes = True

        for path in builtin_workflow_paths:
            assert path.is_file(), f"Workflow file missing: {path}"
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.load(f)
            raw_dict = json.loads(json.dumps(data))
            jsonschema.validate(instance=raw_dict, schema=workflow_schema)

    def test_schema_rejects_missing_required_fields(self, workflow_schema):
        """Workflow definition missing 'id', 'name', or 'steps' must be rejected."""
        yaml = YAML()
        incomplete_yamls = [
            "name: Missing ID\nsteps: []",
            "id: missing_name\nsteps: []",
            "id: missing_steps\nname: Missing Steps",
        ]
        for yml in incomplete_yamls:
            data = yaml.load(yml)
            raw = json.loads(json.dumps(data))
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(instance=raw, schema=workflow_schema)

    def test_schema_rejects_invalid_step_types(self, workflow_schema):
        """Step with unrecognized type must raise ValidationError."""
        bad_yaml = """
        id: bad_step
        name: Bad Step Test
        steps:
          - id: step1
            name: Step 1
            type: unsupported_future_type
        """
        yaml = YAML()
        raw = json.loads(json.dumps(yaml.load(bad_yaml)))
        with pytest.raises(jsonschema.ValidationError) as exc_info:
            jsonschema.validate(instance=raw, schema=workflow_schema)
        assert "unsupported_future_type" in str(exc_info.value)

    def test_schema_rejects_negative_retry_values(self, workflow_schema):
        """Step retry policy with negative retry counts must be rejected."""
        bad_yaml = """
        id: negative_retry
        name: Negative Retry
        steps:
          - id: step1
            name: Step 1
            type: coding
            retry:
              max_retries: -1
        """
        yaml = YAML()
        raw = json.loads(json.dumps(yaml.load(bad_yaml)))
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=raw, schema=workflow_schema)

    def test_schema_validates_canvas_coordinates(self, workflow_schema):
        """Canvas node coordinates must be valid numbers."""
        valid_yaml = """
        id: canvas_test
        name: Canvas Test
        canvas:
          viewport: { x: 0.0, y: 0.0, zoom: 1.0 }
          nodes:
            step1: { x: 100.5, y: 200.0 }
        steps:
          - id: step1
            name: Step 1
            type: context_extraction
        """
        yaml = YAML()
        raw = json.loads(json.dumps(yaml.load(valid_yaml)))
        jsonschema.validate(instance=raw, schema=workflow_schema)


# ==============================================================================
# 2. Round-Trip Serialization Tests (F12)
# ==============================================================================

class TestWorkflowRoundTripSerialization:
    """Verifies round-trip YAML parsing, canvas node editing, and comment preservation."""

    def test_round_trip_preserves_comments_and_structure(self):
        """Modifying node canvas coordinates from visual builder must preserve all comments."""
        yaml_content = """# Header comment explaining the workflow
id: comment_test
name: Comment Test
# Canvas layout section
canvas:
  viewport: { x: 0.0, y: 0.0, zoom: 1.0 }
  nodes:
    step_a: { x: 100.0, y: 200.0 } # inline step comment
steps:
  # First step
  - id: step_a
    name: Step A
    type: context_extraction
"""
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)

        data = yaml.load(yaml_content)
        data['canvas']['nodes']['step_a']['x'] = 450.0
        data['canvas']['nodes']['step_a']['y'] = 300.0

        out_stream = io.StringIO()
        yaml.dump(data, out_stream)
        res = out_stream.getvalue()

        assert "# Header comment explaining the workflow" in res
        assert "# Canvas layout section" in res
        assert "# First step" in res
        assert "450.0" in res
        assert "300.0" in res

    def test_round_trip_injects_canvas_if_missing(self):
        """Workflows created manually without canvas section get canvas added safely."""
        raw_yaml = """id: no_canvas
name: No Canvas Flow
steps:
  - id: s1
    name: S1
    type: context_extraction
"""
        parser = WorkflowParser()
        parsed = parser.load_yaml(raw_yaml)
        updated = parser.update_canvas_coordinates(parsed, {"s1": {"x": 120.0, "y": 300.0}})
        serialized = parser.dump_yaml(updated)

        assert "canvas:" in serialized
        assert "120.0" in serialized


# ==============================================================================
# 3. DAG Topological Sorting & Cycle Detection Tests (F13)
# ==============================================================================

class TestDAGTopologicalSorting:
    """Verifies topological sorting, execution tiers, and cycle detection."""

    def test_linear_pipeline_tiers(self):
        """Linear pipeline produces sequential execution tiers."""
        steps = [
            {"id": "context", "dependencies": []},
            {"id": "code", "dependencies": ["context"]},
            {"id": "verify", "dependencies": ["code"]},
            {"id": "sync", "dependencies": ["verify"]},
        ]
        order, tiers = detect_cycle_and_sort(steps)
        assert order == ["context", "code", "verify", "sync"]
        assert tiers == [["context"], ["code"], ["verify"], ["sync"]]

    def test_diamond_fan_out_parallel_tiers(self):
        """Diamond topology produces parallel tiers for fan-out candidate branches."""
        steps = [
            {"id": "context", "dependencies": []},
            {"id": "cand_a", "dependencies": ["context"]},
            {"id": "cand_b", "dependencies": ["context"]},
            {"id": "judge", "dependencies": ["cand_a", "cand_b"]},
        ]
        order, tiers = detect_cycle_and_sort(steps)
        assert tiers[0] == ["context"]
        assert set(tiers[1]) == {"cand_a", "cand_b"}
        assert tiers[2] == ["judge"]

    def test_cycle_detection_reports_exact_path(self):
        """Circular dependency raises ValueError specifying the exact cycle path."""
        steps = [
            {"id": "step_a", "dependencies": ["step_c"]},
            {"id": "step_b", "dependencies": ["step_a"]},
            {"id": "step_c", "dependencies": ["step_b"]},
        ]
        with pytest.raises(ValueError) as exc:
            detect_cycle_and_sort(steps)
        assert "Cycle detected" in str(exc.value)
        assert "step_a" in str(exc.value)

    def test_self_dependency_rejected(self):
        """Step depending on itself raises ValueError."""
        steps = [{"id": "step_self", "dependencies": ["step_self"]}]
        with pytest.raises(ValueError) as exc:
            detect_cycle_and_sort(steps)
        assert "Self dependency" in str(exc.value)

    def test_dangling_dependency_rejected(self):
        """Step depending on a non-existent step raises ValueError."""
        steps = [{"id": "step_valid", "dependencies": ["ghost_step"]}]
        with pytest.raises(ValueError) as exc:
            detect_cycle_and_sort(steps)
        assert "Dangling dependency" in str(exc.value)


# ==============================================================================
# 4. DAG Execution Engine Tests (F13)
# ==============================================================================

class TestDAGExecutionEngine:
    """Verifies end-to-end execution of workflow DAGs in dry-run mode."""

    def test_dry_run_execution_all_5_templates(self, run_manager, workflow_engine, builtin_workflow_paths):
        """All 5 built-in workflows must execute in dry-run mode with $0.00 spend."""
        for path in builtin_workflow_paths:
            run = run_manager.create_run(
                task="Dry run smoke test for template",
                project="General",
                workflow_id=path.stem,
                dry_run=True
            )
            workflow_engine.execute_dag(
                run_id=run.run_id,
                workflow_path=path,
                dry_run=True
            )
            reloaded = run_manager.load_run(run.run_id)
            assert reloaded.status.value in ["completed", "waiting_gate"]
            assert reloaded.telemetry.total_cost_usd == 0.0

    def test_step_artifacts_passed_downstream(self, run_manager, workflow_engine):
        """Output artifacts (like context_payload.json) pass from context step to coding step."""
        run = run_manager.create_run(
            task="Verify context payload pass-down",
            project="General",
            workflow_id="plan_only",
            dry_run=True
        )
        plan_yaml = ROOT_DIR / "workflows" / "plan_only.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=plan_yaml, dry_run=True)
        reloaded = run_manager.load_run(run.run_id)

        assert reloaded.status == RunStatus.COMPLETED
        assert reloaded.payload is not None
        assert "requirements" in reloaded.payload
        assert len(reloaded.payload["requirements"]) > 0


# ==============================================================================
# 5. Auto-Routing per Step Tests (F14)
# ==============================================================================

class TestAutoRoutingPerStep:
    """Verifies dynamic model selection via task_profiles and reasoning logging."""

    def test_auto_routing_selects_model_from_task_profile(self, workflow_engine):
        """Step with model: auto selects model based on task category and records rationale."""
        decision = workflow_engine.resolve_auto_model(
            step_type="coding",
            task_description="Refactor database connection pool helper",
            project_config={"language": "python"}
        )
        assert decision.model is not None
        assert decision.task_category == "coding"
        assert len(decision.reason) > 0
        assert decision.complexity_tier == "frontier"

    def test_auto_routing_persists_in_step_state(self, run_manager, workflow_engine):
        """Auto-routing decisions are persisted in StepState and emitted to EventBus."""
        run = run_manager.create_run(
            task="Refactor async lock",
            project="General",
            workflow_id="plan_only",
            dry_run=True
        )
        plan_yaml = ROOT_DIR / "workflows" / "plan_only.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=plan_yaml, dry_run=True)
        reloaded = run_manager.load_run(run.run_id)

        context_step = next(s for s in reloaded.steps if s.step_id == "context_extraction")
        assert context_step.routing_decision is not None
        assert context_step.routing_decision.task_category == "planning"
        assert context_step.model is not None


# ==============================================================================
# 6. Retry & Escalation Policy Tests (F15)
# ==============================================================================

class TestRetryAndEscalatePolicy:
    """Verifies automatic model escalation upon step failure threshold."""

    def test_step_escalates_to_frontier_model_after_threshold(self, run_manager, workflow_engine, monkeypatch):
        """When value model fails attempt 1, engine retries and escalates to frontier model."""
        run = run_manager.create_run(
            task="Escalate test task",
            project="General",
            workflow_id="escalate_on_fail",
            dry_run=True
        )

        attempts_seen = []
        models_seen = []

        orig_execute = workflow_engine._execute_coding
        def failing_first_attempt(r, s_def, ctx, s_state):
            attempts_seen.append(s_state.attempts)
            models_seen.append(s_state.model)
            if s_state.attempts == 1:
                raise RuntimeError("Simulated transient coding failure on attempt 1")
            return orig_execute(r, s_def, ctx, s_state)

        monkeypatch.setattr(workflow_engine, "_execute_coding", failing_first_attempt)

        escalate_yaml = ROOT_DIR / "workflows" / "escalate_on_fail.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=escalate_yaml, dry_run=True)
        reloaded = run_manager.load_run(run.run_id)

        coding_step = next(s for s in reloaded.steps if s.step_id == "coding")
        assert coding_step.status == StepStatus.COMPLETED
        assert coding_step.attempts == 2
        assert coding_step.model == "anthropic/claude-opus-5.5"
        assert len(models_seen) == 2
        assert models_seen[0] == "z-ai/glm-5.3-flash"
        assert models_seen[1] == "anthropic/claude-opus-5.5"

    def test_max_retries_exhaustion_aborts_run(self, run_manager, workflow_engine, monkeypatch):
        """Repeated failures exceeding max_retries mark step failed and abort run."""
        run = run_manager.create_run(
            task="Always fail task",
            project="General",
            workflow_id="escalate_on_fail",
            dry_run=True
        )

        def always_fail(r, s_def, ctx, s_state):
            raise RuntimeError("Permanent coding failure")

        monkeypatch.setattr(workflow_engine, "_execute_coding", always_fail)

        escalate_yaml = ROOT_DIR / "workflows" / "escalate_on_fail.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=escalate_yaml, dry_run=True)
        reloaded = run_manager.load_run(run.run_id)

        coding_step = next(s for s in reloaded.steps if s.step_id == "coding")
        assert coding_step.status == StepStatus.FAILED
        assert reloaded.status == RunStatus.FAILED
        assert "Permanent coding failure" in coding_step.error


# ==============================================================================
# 7. Reviewer Model Loop Tests (F16)
# ==============================================================================

class TestReviewerModelLoop:
    """Verifies AI code reviewer feedback loop and changes requested handling."""

    def test_reviewer_rejection_feeds_back_to_coding_step(self, run_manager, workflow_engine):
        """When reviewer rejects code, feedback is fed back to coding step for re-implementation."""
        review_calls = []
        coding_calls = []

        orig_coding = workflow_engine._execute_coding
        def tracked_coding(r, s_def, ctx, s_state, **kwargs):
            coding_calls.append(s_state.attempts)
            return orig_coding(r, s_def, ctx, s_state, **kwargs)

        def mock_reviewer_fn(context_dict):
            review_calls.append(len(review_calls) + 1)
            if len(review_calls) == 1:
                return {
                    "decision": "changes_requested",
                    "approved": False,
                    "summary": "Missing unit tests",
                    "feedback": "Add test_calculate_tax_zero"
                }
            return {
                "decision": "approved",
                "approved": True,
                "score": 95,
                "summary": "Unit tests added, code approved."
            }

        workflow_engine._execute_coding = tracked_coding
        workflow_engine.reviewer_evaluator_fn = mock_reviewer_fn

        run = run_manager.create_run(
            task="Feature with reviewer loop",
            project="General",
            workflow_id="feature_and_reviewer",
            dry_run=True
        )
        feat_yaml = ROOT_DIR / "workflows" / "feature_and_reviewer.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=feat_yaml, dry_run=True)
        reloaded = run_manager.load_run(run.run_id)

        assert reloaded.status == RunStatus.COMPLETED
        assert len(review_calls) == 2
        assert len(coding_calls) >= 2

    def test_reviewer_max_loops_guard(self, run_manager, workflow_engine):
        """Reviewer loop terminates after max_review_loops to avoid infinite billing loops."""
        def never_approve(context_dict):
            return {
                "decision": "changes_requested",
                "approved": False,
                "summary": "Always rejecting"
            }

        workflow_engine.reviewer_evaluator_fn = never_approve

        run = run_manager.create_run(
            task="Feature with infinite reject reviewer",
            project="General",
            workflow_id="feature_and_reviewer",
            dry_run=True
        )
        feat_yaml = ROOT_DIR / "workflows" / "feature_and_reviewer.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=feat_yaml, dry_run=True)
        reloaded = run_manager.load_run(run.run_id)

        review_step = next(s for s in reloaded.steps if s.step_id == "review")
        assert review_step.status == StepStatus.FAILED
        assert "exceeded max loops" in review_step.error.lower()

    def test_reviewer_genuine_dry_run_diff_inspection(self, run_manager, workflow_engine):
        """Feature F16: Reviewer genuinely evaluates code diff and rubric in dry-run without test hook."""
        workflow_engine.reviewer_evaluator_fn = None

        run = run_manager.create_run(
            task="Feature without reviewer evaluator mock",
            project="General",
            workflow_id="feature_and_reviewer",
            dry_run=True
        )
        feat_yaml = ROOT_DIR / "workflows" / "feature_and_reviewer.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=feat_yaml, dry_run=True)
        reloaded = run_manager.load_run(run.run_id)

        assert reloaded.status == RunStatus.COMPLETED
        review_step = next(s for s in reloaded.steps if s.step_id == "review")
        assert review_step.status == StepStatus.COMPLETED
        assert review_step.output.get("decision") == "approved"
        assert review_step.output.get("score") >= 80
        assert "rubric_scores" in review_step.output

    def test_reviewer_genuine_gateway_client_evaluation(self, run_manager, workflow_engine, mock_gateway):
        """Feature F16: Reviewer invokes GatewayClient in production mode (dry_run=False) with rubric and diff."""
        workflow_engine.reviewer_evaluator_fn = None
        workflow_engine.gateway_client = mock_gateway

        run = run_manager.create_run(
            task="Feature with production reviewer model",
            project="General",
            workflow_id="feature_and_reviewer",
            dry_run=False
        )
        feat_yaml = ROOT_DIR / "workflows" / "feature_and_reviewer.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=feat_yaml, dry_run=False)
        reloaded = run_manager.load_run(run.run_id)

        assert reloaded.status == RunStatus.COMPLETED
        review_step = next(s for s in reloaded.steps if s.step_id == "review")
        assert review_step.status == StepStatus.COMPLETED
        assert review_step.output.get("decision") == "approved"
        assert review_step.output.get("gateway") == "mock_gateway"

        eval_completions = [c for c in mock_gateway.completions if c.get("agent_role") == "evaluator"]
        assert len(eval_completions) > 0


# ==============================================================================
# 8. Fan-Out / Compare Engine Tests (F17)
# ==============================================================================

class TestCompareFanOutEngine:
    """
    Verifies Feature F17: Multi-model parallel candidate execution across isolated git worktrees,
    diff calculation, quality scoring, winner selection, and loser worktree pruning.
    """

    def test_compare_executes_and_selects_winner(self, run_manager, workflow_engine):
        """Candidates A and B execute in compare workflow and judge selects winner."""
        run = run_manager.create_run(
            task="Evaluate sorting algorithms",
            project="General",
            workflow_id="compare",
            dry_run=True
        )
        compare_yaml = ROOT_DIR / "workflows" / "compare.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=compare_yaml, dry_run=True)
        reloaded = run_manager.load_run(run.run_id)

        assert reloaded.status == RunStatus.COMPLETED
        judge_step = next(s for s in reloaded.steps if s.step_id == "judge_selection")
        assert judge_step.status == StepStatus.COMPLETED
        assert judge_step.output is not None
        assert "winner" in judge_step.output
        assert judge_step.output["winner"] in ["candidate_a", "candidate_b"]

    def test_compare_fanout_creates_isolated_worktrees(
        self, run_manager, workflow_engine, fixture_sample_repo, monkeypatch
    ):
        """Feature F17: Fan-out steps spawn isolated git worktrees per candidate branch."""
        repo_path = fixture_sample_repo.path
        created_worktrees = {}

        orig_coding = workflow_engine._execute_coding
        def mock_candidate_coding(r, s_def, ctx, s_state):
            step_id = s_state.step_id
            created_worktrees[step_id] = ctx.worktree_path
            assert ctx.worktree_path is not None
            assert ctx.worktree_path.is_dir()
            assert (ctx.worktree_path / ".git").exists()
            calc_file = ctx.worktree_path / "calculator.py"
            assert calc_file.is_file()
            calc_file.write_text(f"# Candidate {step_id}\ndef calculate_tax(a, r): return round(a * r, 2)\n")
            return orig_coding(r, s_def, ctx, s_state)

        monkeypatch.setattr(workflow_engine, "_execute_coding", mock_candidate_coding)

        run = run_manager.create_run(
            task="Evaluate candidate implementations",
            project="General",
            workflow_id="compare",
            dry_run=True
        )
        run.metadata["repo_path"] = str(repo_path)
        run_manager.save_run(run)

        compare_yaml = ROOT_DIR / "workflows" / "compare.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=compare_yaml, dry_run=True)

        reloaded = run_manager.load_run(run.run_id)
        assert reloaded.status == RunStatus.COMPLETED

        assert "candidate_a" in created_worktrees
        assert "candidate_b" in created_worktrees
        assert created_worktrees["candidate_a"] != created_worktrees["candidate_b"]

        step_a = next(s for s in reloaded.steps if s.step_id == "candidate_a")
        step_b = next(s for s in reloaded.steps if s.step_id == "candidate_b")
        assert step_a.output["worktree_branch"] == f"enki/run/{run.run_id}_candidate_a"
        assert step_b.output["worktree_branch"] == f"enki/run/{run.run_id}_candidate_b"

    def test_compare_partial_failure_evaluates_surviving_candidates(
        self, run_manager, workflow_engine, fixture_sample_repo, monkeypatch
    ):
        """Feature F17: Partial candidate failure does not skip compare step; survivors are evaluated."""
        repo_path = fixture_sample_repo.path

        def mock_coding(r, s_def, ctx, s_state):
            step_id = s_state.step_id
            if step_id == "candidate_a":
                raise RuntimeError("Candidate A compilation failed")
            if ctx.worktree_path:
                calc_file = ctx.worktree_path / "calculator.py"
                calc_file.write_text("def calculate_tax(a, r): return round(a * r, 2)\n")
            return {"status": "completed", "passed": True}

        monkeypatch.setattr(workflow_engine, "_execute_coding", mock_coding)

        run = run_manager.create_run(
            task="Evaluate partial candidate failure",
            project="General",
            workflow_id="compare",
            dry_run=True
        )
        run.metadata["repo_path"] = str(repo_path)
        run_manager.save_run(run)

        compare_yaml = ROOT_DIR / "workflows" / "compare.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=compare_yaml, dry_run=True)

        reloaded = run_manager.load_run(run.run_id)
        judge_step = next(s for s in reloaded.steps if s.step_id == "judge_selection")

        assert judge_step.status == StepStatus.COMPLETED
        assert judge_step.output["winner"] == "candidate_b"
        assert "candidate_b" in judge_step.output["surviving_candidates"]
        assert "candidate_a" in judge_step.output["failed_candidates"]

    def test_compare_discards_loser_worktrees(
        self, run_manager, workflow_engine, fixture_sample_repo, monkeypatch
    ):
        """Feature F17: Loser candidate worktrees and branches are discarded, winner is retained."""
        repo_path = fixture_sample_repo.path

        workflow_engine.reviewer_evaluator_fn = lambda c: {"winner": "candidate_b"}

        run = run_manager.create_run(
            task="Compare and prune losers",
            project="General",
            workflow_id="compare",
            dry_run=True
        )
        run.metadata["repo_path"] = str(repo_path)
        run_manager.save_run(run)

        compare_yaml = ROOT_DIR / "workflows" / "compare.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=compare_yaml, dry_run=True)

        reloaded = run_manager.load_run(run.run_id)
        judge_step = next(s for s in reloaded.steps if s.step_id == "judge_selection")
        assert judge_step.output["winner"] == "candidate_b"

        loser_run_id = f"{run.run_id}_candidate_a"
        loser_wt = workflow_engine.worktree_manager.get_worktree_path(repo_path, loser_run_id)
        assert not loser_wt.exists(), f"Loser worktree {loser_wt} was not discarded!"

        winner_run_id = f"{run.run_id}_candidate_b"
        winner_wt = workflow_engine.worktree_manager.get_worktree_path(repo_path, winner_run_id)
        assert winner_wt.exists(), f"Winner worktree {winner_wt} should be retained!"


# ==============================================================================
# 9. Approval Gates Tests (F18)
# ==============================================================================

class TestApprovalGates:
    """Verifies interactive approval gates and concurrency non-blocking invariant."""

    def test_gate_pauses_run_and_emits_event(self, run_manager, workflow_engine):
        """Step configured with post_execution gate pauses run in WAITING_GATE status."""
        captured_events = []
        run_manager.event_bus.subscribe_all(lambda ev: captured_events.append(ev))

        run = run_manager.create_run(
            task="Test gate pausing",
            project="General",
            workflow_id="four_step_pipeline",
            dry_run=True
        )
        four_step_yaml = ROOT_DIR / "workflows" / "four_step_pipeline.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=four_step_yaml, dry_run=True)
        reloaded = run_manager.load_run(run.run_id)

        assert reloaded.status == RunStatus.WAITING_GATE
        assert reloaded.gate_state is not None
        assert reloaded.gate_state.status == "pending"

        event_types = [e.event_type for e in captured_events]
        assert EventType.GATE_WAITING in event_types

    def test_gate_action_approve_resumes_run(self, run_manager, workflow_engine):
        """Action 'approve' transitions run from WAITING_GATE and resumes execution."""
        run = run_manager.create_run(
            task="Test gate approval resume",
            project="General",
            workflow_id="four_step_pipeline",
            dry_run=True
        )
        four_step_yaml = ROOT_DIR / "workflows" / "four_step_pipeline.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=four_step_yaml, dry_run=True)

        reloaded = run_manager.load_run(run.run_id)
        assert reloaded.status == RunStatus.WAITING_GATE
        gate_id = reloaded.gate_state.gate_id

        # 1. Resolve first gate (post_execution on context_extraction)
        workflow_engine.resolve_gate(run_id=run.run_id, gate_id=gate_id, action=GateAction.APPROVE)
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=four_step_yaml, dry_run=True)

        # 2. Check next gate (pre_execution on coding)
        reloaded2 = run_manager.load_run(run.run_id)
        assert reloaded2.status == RunStatus.WAITING_GATE
        gate_id2 = reloaded2.gate_state.gate_id

        # 3. Resolve second gate
        workflow_engine.resolve_gate(run_id=run.run_id, gate_id=gate_id2, action=GateAction.APPROVE)
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=four_step_yaml, dry_run=True)

        reloaded3 = run_manager.load_run(run.run_id)
        assert reloaded3.status == RunStatus.COMPLETED

    def test_gate_action_edit_and_approve_updates_payload(self, run_manager, workflow_engine):
        """Action 'edit_and_approve' updates context_payload.json before resuming and prevents re-execution."""
        run = run_manager.create_run(
            task="Test gate edit and approve",
            project="General",
            workflow_id="four_step_pipeline",
            dry_run=True
        )
        four_step_yaml = ROOT_DIR / "workflows" / "four_step_pipeline.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=four_step_yaml, dry_run=True)

        reloaded = run_manager.load_run(run.run_id)
        gate_id = reloaded.gate_state.gate_id

        edited_payload = dict(reloaded.payload or {})
        edited_payload["edited_by_user"] = True

        workflow_engine.resolve_gate(
            run_id=run.run_id,
            gate_id=gate_id,
            action=GateAction.EDIT_AND_APPROVE,
            payload=edited_payload
        )

        resumed_run = run_manager.load_run(run.run_id)
        assert resumed_run.payload.get("edited_by_user") is True
        assert resumed_run.gate_state.status == "edited_and_approved"

        # Verify target step marked COMPLETED
        target_step = next(s for s in resumed_run.steps if s.step_id == "context_extraction")
        assert target_step.status == StepStatus.COMPLETED

        # Verify disk payload updated
        payload_file = run_manager.get_context_payload_file(run.run_id)
        assert payload_file.is_file()
        with open(payload_file, "r", encoding="utf-8") as f:
            disk_payload = json.load(f)
        assert disk_payload.get("edited_by_user") is True

        # Resuming execution does NOT re-execute context_extraction and preserves edited payload downstream
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=four_step_yaml, dry_run=True)
        resumed_run2 = run_manager.load_run(run.run_id)
        assert resumed_run2.status == RunStatus.WAITING_GATE
        assert resumed_run2.payload.get("edited_by_user") is True

        # Resolve second gate (coding pre_execution) and complete run
        workflow_engine.resolve_gate(
            run_id=run.run_id,
            gate_id=resumed_run2.gate_state.gate_id,
            action=GateAction.APPROVE
        )
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=four_step_yaml, dry_run=True)
        final_run = run_manager.load_run(run.run_id)
        assert final_run.status == RunStatus.COMPLETED
        assert final_run.payload.get("edited_by_user") is True

    def test_gate_action_abort_terminates_run(self, run_manager, workflow_engine):
        """Action 'abort' terminates the workflow immediately."""
        run = run_manager.create_run(
            task="Test gate abort",
            project="General",
            workflow_id="four_step_pipeline",
            dry_run=True
        )
        four_step_yaml = ROOT_DIR / "workflows" / "four_step_pipeline.yaml"
        workflow_engine.execute_dag(run_id=run.run_id, workflow_path=four_step_yaml, dry_run=True)

        reloaded = run_manager.load_run(run.run_id)
        gate_id = reloaded.gate_state.gate_id

        workflow_engine.resolve_gate(
            run_id=run.run_id,
            gate_id=gate_id,
            action=GateAction.ABORT
        )

        aborted_run = run_manager.load_run(run.run_id)
        assert aborted_run.status == RunStatus.ABORTED

    def test_gate_concurrency_isolation(self, run_manager, workflow_engine):
        """Run A waiting at a gate does not block Run B from completing concurrently."""
        four_step_yaml = ROOT_DIR / "workflows" / "four_step_pipeline.yaml"
        plan_yaml = ROOT_DIR / "workflows" / "plan_only.yaml"

        # Run A: Four step pipeline has approval gates -> pauses in WAITING_GATE
        run_a = run_manager.create_run(task="Run A (with gates)", workflow_id="four_step_pipeline", dry_run=True)
        workflow_engine.execute_dag(run_id=run_a.run_id, workflow_path=four_step_yaml, dry_run=True)
        reloaded_a = run_manager.load_run(run_a.run_id)
        assert reloaded_a.status == RunStatus.WAITING_GATE

        # Run B: Plan only workflow has no gates -> completes immediately
        run_b = run_manager.create_run(task="Run B (no gates)", workflow_id="plan_only", dry_run=True)
        workflow_engine.execute_dag(run_id=run_b.run_id, workflow_path=plan_yaml, dry_run=True)
        reloaded_b = run_manager.load_run(run_b.run_id)
        assert reloaded_b.status == RunStatus.COMPLETED

        # Confirm Run A is still untouched in WAITING_GATE
        assert run_manager.load_run(run_a.run_id).status == RunStatus.WAITING_GATE


# ==============================================================================
# 10. OpenRouter Catalog Service Tests (F20)
# ==============================================================================

class TestOpenRouterCatalogService:
    """Verifies 24h caching, offline fallback, and curated config presets merging."""

    def test_catalog_cache_hit_within_24h_ttl(self, tmp_path):
        """Valid cache is read from disk without invoking external network requests."""
        cache_file = tmp_path / "test_cache.json"
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sample_model = ModelCatalogItem(
            id="test/model",
            name="Test Model",
            context_length=100000,
            pricing=ModelPricing(prompt_per_1m=1.0, completion_per_1m=2.0)
        )
        cache_data = CatalogCache(
            fetched_at=now_str,
            ttl_seconds=86400,
            models_count=1,
            models={"test/model": sample_model}
        )
        catalog = OpenRouterCatalog(cache_file=cache_file)
        catalog.save_cache(cache_data)

        assert catalog.is_cache_valid() is True
        loaded = catalog.get_catalog(force_refresh=False)
        assert "test/model" in loaded

    def test_catalog_offline_fallback_to_builtins_when_no_cache(self, tmp_path):
        """Offline execution without existing cache falls back to built-in model definitions."""
        empty_cache = tmp_path / "non_existent_cache.json"
        catalog = OpenRouterCatalog(cache_file=empty_cache)

        models = catalog.get_catalog(force_refresh=True)
        assert len(models) > 0
        assert "anthropic/claude-opus-5.5" in models
        assert "z-ai/glm-5.3-flash" in models

    def test_catalog_merges_curated_presets_from_config(self, tmp_path):
        """Catalog items are enriched with curated tags, scores, and roles from enki.config.json."""
        catalog = OpenRouterCatalog(cache_file=tmp_path / "cache.json")
        models = catalog.get_catalog()

        opus = models.get("anthropic/claude-opus-5.5")
        assert opus is not None
        assert opus.is_curated is True
        assert opus.curated_tier == "frontier"
        assert opus.intelligence_score == 58

    def test_catalog_pricing_lookup(self, tmp_path):
        """Pricing lookup returns prompt and completion rates per 1M tokens."""
        catalog = OpenRouterCatalog(cache_file=tmp_path / "cache.json")
        pricing = catalog.get_pricing("anthropic/claude-opus-5.5")
        assert "prompt" in pricing
        assert "completion" in pricing
        assert pricing["prompt"] > 0
        assert pricing["completion"] > 0
