"""
tests/test_engine.py
Comprehensive test suite for the Enki Shared Engine & Worktree Isolation layer (Milestone 1).
Covers:
1. Run creation, lifecycle, atomic persistence, and events
2. Worktree lifecycle: creation on enki/run/<run_id>, diff generation, keep, merge, discard
3. 3 parallel dry-run tasks against fixture_sample_repo with worktree isolation
4. Verification retry loop reaching green and recording 2 OMP iterations
5. Kill mid-way and resume from failed step without re-executing completed steps
6. Per-run cost and token telemetry isolation (fixing the 30-day sum bug)
7. Config repo path resolution and project filtering (excluding Body.me App)
8. Ephemeral OMP configuration overlays
"""

import sys
import json
import time
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.engine.models import (
    Run, RunStatus, StepStatus, EventType, RunEvent,
    GateAction, BudgetDecision, WorktreeAction
)
from src.engine.events import EventBus
from src.engine.run_manager import RunManager
from src.engine.worktree_manager import (
    WorktreeManager, RepoLock, WorktreeError,
    DirtyWorkingTreeError, WorktreeNotFoundError
)
from src.omp_bridge import OMPBridge
from src.token_tracker import record_usage, get_run_telemetry, get_summary
from src.config import (
    get_active_projects, get_project_config, resolve_project_repo_path,
    EXCLUDED_PROJECTS
)
from src.orchestrator import EnkiOrchestrator


def test_run_creation_lifecycle_and_persistence(tmp_path):
    """
    Verifies run creation, atomic persistence to disk, event bus publishing,
    and state transitions from PENDING -> RUNNING -> COMPLETED.
    """
    runs_dir = tmp_path / "data" / "runs"
    event_bus = EventBus(runs_base_dir=runs_dir)
    rm = RunManager(base_runs_dir=runs_dir, event_bus=event_bus)

    captured_events = []
    def on_event(ev: RunEvent):
        captured_events.append(ev)

    # 1. Create run
    run = rm.create_run(
        task="Implement normalization module",
        project="Trend Scraper",
        workflow_id="four_step_pipeline",
        dry_run=True
    )
    event_bus.subscribe(run.run_id, on_event)

    assert run.run_id.startswith("run_")
    assert run.status == RunStatus.PENDING
    assert run.dry_run is True
    assert len(run.steps) == 4
    assert (runs_dir / run.run_id / "run_state.json").is_file()

    # Verify atomic load
    loaded = rm.load_run(run.run_id)
    assert loaded.run_id == run.run_id
    assert loaded.task == "Implement normalization module"

    # 2. Start run
    started_run = rm.start_run(run.run_id)
    assert started_run.status == RunStatus.RUNNING
    assert started_run.started_at is not None
    assert started_run.current_step_id == "context_extraction"

    # 3. Complete run
    finished_run = rm.finish_run(run.run_id, RunStatus.COMPLETED)
    assert finished_run.status == RunStatus.COMPLETED
    assert finished_run.completed_at is not None

    # Verify list_runs
    summaries = rm.list_runs()
    assert len(summaries) == 1
    assert summaries[0].run_id == run.run_id
    assert summaries[0].status == RunStatus.COMPLETED

    # Verify persisted events in events.jsonl
    persisted_events = event_bus.get_events(run.run_id)
    event_types = [e.event_type for e in persisted_events]
    assert EventType.RUN_CREATED in event_types
    assert EventType.RUN_STARTED in event_types
    assert EventType.RUN_COMPLETED in event_types


def test_worktree_lifecycle_create_diff_keep_merge_discard(fixture_sample_repo):
    """
    Verifies full git worktree isolation lifecycle:
    - Creation of branch enki/run/<run_id> and isolated worktree
    - Automatic inclusion of .enki/ in .git/info/exclude
    - Diff computation capturing uncommitted changes
    - User choice: Keep worktree branch while unmounting folder
    - User choice: Merge worktree with explicit approval into target branch
    - User choice: Discard worktree and branch
    """
    repo = fixture_sample_repo
    wm = WorktreeManager(default_base_branch="main")

    # 1. Create worktree
    run_id_keep = "test_keep_lifecycle"
    wt_keep = wm.create_worktree(repo.path, run_id_keep, base_branch="main")

    assert wt_keep.is_dir()
    assert (wt_keep / "calculator.py").is_file()

    # Check parent repo exclude
    exclude_file = repo.path / ".git" / "info" / "exclude"
    assert exclude_file.is_file()
    assert ".enki" in exclude_file.read_text(encoding="utf-8")

    # Parent repo status must be clean
    parent_st = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo.path), capture_output=True, text=True)
    assert parent_st.stdout.strip() == ""

    # Modify file in worktree
    (wt_keep / "calculator.py").write_text("# modification in keep wt\n", encoding="utf-8")

    # Verify diff captures changes
    diff = wm.get_diff(repo.path, run_id_keep, base_branch="main")
    assert diff.has_changes is True
    assert diff.files_changed_count == 1
    assert diff.changed_files[0].path == "calculator.py"

    # Test keep_worktree: folder unmounted, branch retained
    keep_res = wm.keep_worktree(repo.path, run_id_keep)
    assert keep_res.success is True
    assert not wt_keep.exists()
    branch_check = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/enki/run/{run_id_keep}"],
        cwd=str(repo.path),
        capture_output=True
    )
    assert branch_check.returncode == 0

    # 2. Test merge_worktree
    run_id_merge = "test_merge_lifecycle"
    wt_merge = wm.create_worktree(repo.path, run_id_merge, base_branch="main")

    # Apply the tax bug fix inside this isolated worktree
    fixed_calc = '''"""
Calculator module with standard tax calculation.
"""

def calculate_tax(amount: float, rate: float) -> float:
    return round(amount * rate, 2)
'''
    (wt_merge / "calculator.py").write_text(fixed_calc, encoding="utf-8")

    # Approval required invariant
    with pytest.raises(WorktreeError, match="Explicit user approval"):
        wm.merge_worktree(repo.path, run_id_merge, target_branch="main", require_approval=False)

    # Approved merge
    merge_res = wm.merge_worktree(repo.path, run_id_merge, target_branch="main", require_approval=True)
    assert merge_res.success is True
    assert not wt_merge.exists()

    # Main branch now has the fix; pytest in sample repo should pass
    rc, stdout, _ = repo.run_pytest()
    assert rc == 0
    assert "passed" in stdout

    # 3. Test discard_worktree
    run_id_discard = "test_discard_lifecycle"
    wt_discard = wm.create_worktree(repo.path, run_id_discard, base_branch="main")
    (wt_discard / "dummy.txt").write_text("temporary scratchpad", encoding="utf-8")

    discard_res = wm.discard_worktree(repo.path, run_id_discard)
    assert discard_res.success is True
    assert not wt_discard.exists()
    branch_check_discard = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/enki/run/{run_id_discard}"],
        cwd=str(repo.path),
        capture_output=True
    )
    assert branch_check_discard.returncode != 0


def test_parallel_dry_run_worktree_isolation(fixture_sample_repo):
    """
    Requirement Test:
    3 parallel dry-run tasks against fixture_sample_repo finishing on separate
    worktrees with no cross-contamination of files or branches.
    Exercises RepoLock and index.lock concurrency safety.
    """
    repo = fixture_sample_repo
    wm = WorktreeManager(default_base_branch="main")
    run_ids = ["parallel_run_alpha", "parallel_run_beta", "parallel_run_gamma"]

    def worker_task(run_id: str) -> dict:
        wt_path = wm.create_worktree(repo.path, run_id, base_branch="main")
        # Write unique task-specific file in each worktree
        unique_filename = f"{run_id}_artifact.txt"
        unique_content = f"Payload and isolated state for {run_id}"
        (wt_path / unique_filename).write_text(unique_content, encoding="utf-8")

        diff = wm.get_diff(repo.path, run_id, base_branch="main")
        return {
            "run_id": run_id,
            "worktree_path": wt_path,
            "artifact_file": unique_filename,
            "diff": diff
        }

    # Run all 3 concurrently in thread pool
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(worker_task, run_ids))

    assert len(results) == 3

    # Verify no cross-contamination: each worktree only contains its own artifact
    for r in results:
        wt_path = r["worktree_path"]
        my_file = r["artifact_file"]
        assert (wt_path / my_file).is_file()

        # Other run files MUST NOT exist in this worktree
        for other_id in run_ids:
            if other_id != r["run_id"]:
                other_file = f"{other_id}_artifact.txt"
                assert not (wt_path / other_file).exists(), (
                    f"Cross-contamination detected: {other_file} found in worktree of {r['run_id']}"
                )

        # Diff must show only 1 changed file
        diff = r["diff"]
        assert diff.files_changed_count == 1
        assert diff.changed_files[0].path == my_file

    # Teardown all 3 worktrees
    for run_id in run_ids:
        wm.discard_worktree(repo.path, run_id)


def test_verification_retry_loop_with_mock_omp_fix(fixture_sample_repo):
    """
    Requirement Test:
    With a mocked OMP that fixes the failing test on its second attempt,
    the verify loop reaches green, and the run records 2 OMP iterations.
    """
    repo = fixture_sample_repo
    omp = OMPBridge()

    # Verify initial state: test fails
    rc_initial, _, _ = repo.run_pytest()
    assert rc_initial == 1

    def mock_omp_fix_action(iteration: int, failure_report: str, working_dir: Path):
        # On attempt 1 failure, inspect report and apply fix
        assert "FAILED" in failure_report or "AssertionError" in failure_report
        # Fix the bug in calculator.py
        calc_path = working_dir / "calculator.py"
        calc_path.write_text(
            '"""Fixed calculator"""\n\ndef calculate_tax(amount: float, rate: float) -> float:\n    return round(amount * rate, 2)\n',
            encoding="utf-8"
        )

    # Run verification loop with max_retries=3
    res = omp.run_verification_loop(
        test_commands=["py -m pytest -q"],
        working_dir=repo.path,
        max_retries=3,
        mock_omp_fix_fn=mock_omp_fix_action
    )

    assert res["all_passed"] is True
    assert res["status"] == "PASSED"
    assert res["iterations"] == 2
    assert len(res["history"]) == 2
    assert res["history"][0]["all_passed"] is False
    assert res["history"][1]["all_passed"] is True


def test_run_kill_and_resume_from_failed_step(tmp_path):
    """
    Requirement Test:
    A run killed mid-way can be resumed from the failed step,
    and earlier completed steps are NOT re-executed.
    """
    runs_dir = tmp_path / "data" / "runs"
    event_bus = EventBus(runs_base_dir=runs_dir)
    rm = RunManager(base_runs_dir=runs_dir, event_bus=event_bus)

    # Create run with 4 steps
    run = rm.create_run(task="Resumable pipeline task", dry_run=True)
    run_id = run.run_id

    # Simulate steps 1 and 2 completing successfully
    run.status = RunStatus.RUNNING
    run.steps[0].status = StepStatus.COMPLETED
    run.steps[0].completed_at = "2026-10-09T12:00:00Z"
    run.steps[0].output = {"context_hits": 3}

    run.steps[1].status = StepStatus.COMPLETED
    run.steps[1].completed_at = "2026-10-09T12:01:00Z"
    run.steps[1].output = {"handshake": "success"}

    # Simulate step 3 failing
    run.steps[2].status = StepStatus.FAILED
    run.steps[2].error = "Test runner assertion error on attempt 3"
    run.status = RunStatus.FAILED
    run.error = "Pipeline failed at verification"

    # Persist failed state to disk
    rm.save_run(run)

    # Simulate process reboot with fresh RunManager
    rm_fresh = RunManager(base_runs_dir=runs_dir)
    resumed = rm_fresh.resume_run(run_id)

    # Invariants:
    # 1. Step 1 and Step 2 MUST NOT be reset (remain COMPLETED)
    assert resumed.steps[0].status == StepStatus.COMPLETED
    assert resumed.steps[0].output == {"context_hits": 3}
    assert resumed.steps[1].status == StepStatus.COMPLETED
    assert resumed.steps[1].output == {"handshake": "success"}

    # 2. Failed Step 3 is reset to PENDING and becomes current step
    assert resumed.steps[2].status == StepStatus.PENDING
    assert resumed.steps[2].error is None
    assert resumed.current_step_id == "verification"

    # 3. Subsequent Step 4 remains PENDING
    assert resumed.steps[3].status == StepStatus.PENDING

    # 4. Overall run status is RUNNING
    assert resumed.status == RunStatus.RUNNING
    assert resumed.error is None


def test_per_run_telemetry_isolation(tmp_path):
    """
    Requirement Test:
    Verifies per-run cost derivation (cost matches run records, NOT 30-day total).
    Fixes Gap 5 where get_summary() was returning cumulative spend of all runs.
    """
    # 1. Record telemetry for Run A ($0.12, 600 tokens)
    run_a_id = "run_telemetry_alpha"
    record_usage(
        agent_role="hermes",
        model="nousresearch/hermes-3-llama-3.1-70b",
        prompt_tokens=300,
        completion_tokens=100,
        cost_usd=0.04,
        task_id=run_a_id
    )
    record_usage(
        agent_role="omp",
        model="anthropic/claude-3.5-sonnet",
        prompt_tokens=150,
        completion_tokens=50,
        cost_usd=0.08,
        task_id=run_a_id
    )

    # 2. Record telemetry for Run B ($0.50, 2000 tokens)
    run_b_id = "run_telemetry_beta"
    record_usage(
        agent_role="omp",
        model="anthropic/claude-3.5-sonnet",
        prompt_tokens=1500,
        completion_tokens=500,
        cost_usd=0.50,
        task_id=run_b_id
    )

    # 3. Cumulative 30-day summary includes BOTH runs
    summary_30d = get_summary()
    assert summary_30d["total_calls"] >= 3
    assert summary_30d["total_tokens"] >= 2600
    assert summary_30d["total_cost_usd"] >= 0.62

    # 4. Exact per-run telemetry MUST isolate Run A only
    tel_a = get_run_telemetry(run_a_id)
    assert tel_a["run_id"] == run_a_id
    assert tel_a["calls_count"] == 2
    assert tel_a["total_tokens"] == 600
    assert abs(tel_a["total_cost_usd"] - 0.12) < 1e-5
    assert len(tel_a["by_agent"]) == 2

    # 5. Exact per-run telemetry MUST isolate Run B only
    tel_b = get_run_telemetry(run_b_id)
    assert tel_b["run_id"] == run_b_id
    assert tel_b["calls_count"] == 1
    assert tel_b["total_tokens"] == 2000
    assert abs(tel_b["total_cost_usd"] - 0.50) < 1e-5

    # 6. Verify RunManager integration
    runs_dir = tmp_path / "data" / "runs"
    rm = RunManager(base_runs_dir=runs_dir)
    run = rm.create_run(task="Check telemetry", dry_run=True)
    # Re-use run_a_id
    record_usage(agent_role="hermes", model="mock", prompt_tokens=10, completion_tokens=10, cost_usd=0.01, task_id=run.run_id)
    rec_tel = rm.record_run_telemetry(run.run_id)
    assert rec_tel.total_tokens == 20
    assert abs(rec_tel.total_cost_usd - 0.01) < 1e-5


def test_config_project_repo_resolution_and_exclusion():
    """
    Verifies project configuration extension:
    - Body.me App is excluded from active projects
    - Valid projects resolve their repository path safely
    """
    active_projects = get_active_projects()
    assert "Body.me App" not in active_projects
    assert "Body.me App" in EXCLUDED_PROJECTS

    # Dinner Service Optimizer is present
    assert "Dinner Service Optimizer" in active_projects
    dinner_cfg = get_project_config("Dinner Service Optimizer")
    assert dinner_cfg is not None
    assert "repo_path" in dinner_cfg
    assert Path(dinner_cfg["repo_path"]).exists()

    # Excluded project config lookup returns None
    assert get_project_config("Body.me App") is None


def test_ephemeral_omp_overlay():
    """
    Verifies that ephemeral OMP YAML overlays are safely created
    and immediately deleted without mutating persistent global state.
    """
    omp = OMPBridge()
    with omp.ephemeral_overlay(model="anthropic/claude-3.5-sonnet", extra_config={"auto_approve": True}) as overlay_path:
        assert overlay_path is not None
        assert overlay_path.is_file()
        content = overlay_path.read_text(encoding="utf-8")
        assert "anthropic/claude-3.5-sonnet" in content

    # File unlinked upon context manager exit
    assert not overlay_path.exists()


def test_orchestrator_facade_end_to_end_dry_run(fixture_vault):
    """
    Verifies that EnkiOrchestrator backward-compatible facade runs
    end-to-end in dry-run mode and syncs completion with isolated per-run cost.
    """
    orchestrator = EnkiOrchestrator(dry_run=True)
    res = orchestrator.run_pipeline("Implement dry-run pipeline test")

    assert res["payload"]["title"] == "Implement dry-run pipeline test"
    assert res["handshake"]["exit_code"] == 0
    assert res["verification"]["status"] == "PASSED"
    assert res["sync"]["status"] == "completed"
    assert "log_path" in res["sync"]


def test_run_manager_gates_and_budget_resolution(tmp_path):
    """
    Verifies interactive gate approval / rejection and budget stop resolution
    in RunManager.
    """
    runs_dir = tmp_path / "data" / "runs"
    event_bus = EventBus(runs_base_dir=runs_dir)
    rm = RunManager(base_runs_dir=runs_dir, event_bus=event_bus)

    run = rm.create_run(task="Gate & Budget Task", dry_run=True)
    rm.start_run(run.run_id)

    # 1. Resolve Gate
    gated_run = rm.resolve_gate(
        run_id=run.run_id,
        gate_id="gate_pre_coding",
        action=GateAction.APPROVE,
        feedback="Approved by test pilot"
    )
    assert gated_run.gate_state is not None
    assert gated_run.gate_state.status == "approved"
    assert gated_run.gate_state.feedback == "Approved by test pilot"
    assert gated_run.status == RunStatus.RUNNING

    # 2. Resolve Budget Stop: switch cheaper model
    budget_run = rm.resolve_budget(
        run_id=run.run_id,
        decision=BudgetDecision.SWITCH_CHEAPER,
        cheaper_model="deepseek/deepseek-chat"
    )
    assert budget_run.budget_state is not None
    assert budget_run.budget_state.decision == BudgetDecision.SWITCH_CHEAPER
    assert budget_run.model_override == "deepseek/deepseek-chat"
    assert budget_run.status == RunStatus.RUNNING


def test_worktree_merge_conflict_handling(fixture_sample_repo):
    """
    Verifies that a merge conflict during merge_worktree is cleanly aborted,
    preserves target branch integrity, and returns conflict diagnostics.
    """
    repo = fixture_sample_repo
    wm = WorktreeManager(default_base_branch="main")

    run_id = "test_merge_conflict"
    wt_path = wm.create_worktree(repo.path, run_id, base_branch="main")

    # In worktree: edit calculator.py line
    (wt_path / "calculator.py").write_text("def calculate_tax(): return 111\n", encoding="utf-8")

    # In main repo: commit conflicting change
    (repo.path / "calculator.py").write_text("def calculate_tax(): return 999\n", encoding="utf-8")
    subprocess.run(["git", "add", "calculator.py"], cwd=str(repo.path), check=True)
    subprocess.run(["git", "commit", "-m", "conflicting main commit"], cwd=str(repo.path), check=True)

    # Attempt merge
    merge_res = wm.merge_worktree(repo.path, run_id, target_branch="main", require_approval=True)
    assert merge_res.success is False
    assert "conflict" in merge_res.message.lower()

    # Target repo must NOT be in a conflicted merge state
    st = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo.path), capture_output=True, text=True)
    # No unmerged paths (UU)
    assert "UU" not in st.stdout

    # Clean up
    wm.discard_worktree(repo.path, run_id)


def test_worktree_dirty_working_tree_error(fixture_sample_repo):
    """
    Verifies that merge_worktree refuses to merge if the target repo has dirty uncommitted files.
    """
    repo = fixture_sample_repo
    wm = WorktreeManager(default_base_branch="main")

    run_id = "test_dirty_tree"
    wt_path = wm.create_worktree(repo.path, run_id, base_branch="main")
    (wt_path / "new_file.txt").write_text("some content", encoding="utf-8")

    # Make parent repo dirty with an unstaged modified tracked file
    (repo.path / "calculator.py").write_text("# dirty modification", encoding="utf-8")

    with pytest.raises(DirtyWorkingTreeError, match="uncommitted changes"):
        wm.merge_worktree(repo.path, run_id, target_branch="main", require_approval=True)

    # Revert parent repo dirty change and cleanup
    subprocess.run(["git", "checkout", "calculator.py"], cwd=str(repo.path), check=True)
    wm.discard_worktree(repo.path, run_id)


def test_run_manager_replay_run(tmp_path):
    """
    Verifies that historical events can be replayed from events.jsonl.
    """
    runs_dir = tmp_path / "data" / "runs"
    event_bus = EventBus(runs_base_dir=runs_dir)
    rm = RunManager(base_runs_dir=runs_dir, event_bus=event_bus)

    run = rm.create_run(task="Replay test task", dry_run=True)
    rm.start_run(run.run_id)
    rm.finish_run(run.run_id, RunStatus.COMPLETED)

    replayed = []
    rm.replay_run(run.run_id, lambda ev: replayed.append(ev))

    assert len(replayed) >= 3
    event_types = [e.event_type for e in replayed]
    assert EventType.RUN_CREATED in event_types
    assert EventType.RUN_STARTED in event_types
    assert EventType.RUN_COMPLETED in event_types
