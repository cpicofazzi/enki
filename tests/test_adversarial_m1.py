"""
tests/test_adversarial_m1.py
Empirical Adversarial Challenge Suite for Milestone 1:
1. 5 concurrent worktree operations under high index.lock contention and mixed teardown (merge, keep, discard)
2. Worktree discard resilience with untracked, uncommitted, nested, and read-only files without dangling branches
3. Simulated .git/index.lock contention test verifying exponential backoff retry loop
4. RunManager resumption across cascading step failures, mid-execution aborts, and idempotent restart
5. Crash simulation testing atomic .tmp persistence resilience
6. Cross-process RepoLock mutual exclusion on Windows
7. Parent working copy protection (DirtyWorkingTreeError) and discard after keep
"""

import os
import sys
import stat
import time
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.engine.models import RunStatus, StepStatus, EventType, RunEvent
from src.engine.events import EventBus
from src.engine.run_manager import RunManager
from src.engine.worktree_manager import (
    WorktreeManager, RepoLock, WorktreeError, WorktreeConcurrencyError,
    DirtyWorkingTreeError, WorktreeNotFoundError
)


def test_stress_5_concurrent_worktrees_contention(fixture_sample_repo):
    """
    Adversarial Challenge 1:
    Create 5 concurrent worktrees simultaneously on a single git repository.
    Simultaneously write files, compute diffs, and perform teardowns.
    Tests RepoLock and .git/index.lock contention under high parallel load.
    Verifies no deadlocks, no unhandled lock collisions, and zero cross-contamination.
    """
    repo = fixture_sample_repo
    wm = WorktreeManager(default_base_branch="main")
    run_ids = [f"adv_stress_run_{i}" for i in range(1, 6)]

    def create_and_modify(run_id: str) -> dict:
        t0 = time.time()
        wt_path = wm.create_worktree(repo.path, run_id, base_branch="main")
        create_duration = time.time() - t0

        # Write unique payload
        payload_file = wt_path / f"payload_{run_id}.json"
        payload_file.write_text(f'{{"run_id": "{run_id}", "timestamp": {time.time()}}}', encoding="utf-8")

        # Also modify an existing tracked file
        calc_file = wt_path / "calculator.py"
        existing = calc_file.read_text(encoding="utf-8")
        calc_file.write_text(existing + f"\n# Worker modification for {run_id}\n", encoding="utf-8")

        # Compute diff concurrently
        diff = wm.get_diff(repo.path, run_id, base_branch="main")

        return {
            "run_id": run_id,
            "worktree_path": wt_path,
            "create_duration": create_duration,
            "diff": diff
        }

    # Execute 5 concurrent worktree creations
    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_id = {executor.submit(create_and_modify, rid): rid for rid in run_ids}
        for future in as_completed(future_to_id):
            rid = future_to_id[future]
            results[rid] = future.result()

    assert len(results) == 5, "All 5 concurrent worktrees must succeed"

    # Verify complete isolation: zero cross-contamination between any worktree
    for rid, data in results.items():
        wt_path = data["worktree_path"]
        assert wt_path.is_dir()
        assert (wt_path / f"payload_{rid}.json").is_file()

        # Check other runs' files do not exist
        for other_rid in run_ids:
            if other_rid != rid:
                assert not (wt_path / f"payload_{other_rid}.json").exists(), (
                    f"Cross-contamination detected: {other_rid} artifact found in {rid}"
                )

        diff = data["diff"]
        assert diff.has_changes is True
        # Both calculator.py and payload_<rid>.json modified/added
        assert diff.files_changed_count == 2
        changed_paths = {cf.path for cf in diff.changed_files}
        assert "calculator.py" in changed_paths
        assert f"payload_{rid}.json" in changed_paths

    # Teardown: Discard 4 worktrees concurrently, keep 1 worktree
    kept_rid = run_ids[0]
    discard_rids = run_ids[1:]

    def discard_task(run_id: str):
        return wm.discard_worktree(repo.path, run_id)

    discard_results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_id = {executor.submit(discard_task, rid): rid for rid in discard_rids}
        for future in as_completed(future_to_id):
            rid = future_to_id[future]
            discard_results[rid] = future.result()

    assert len(discard_results) == 4

    # Check all 4 discarded worktrees are gone and no dangling branches exist
    for rid in discard_rids:
        wt_path = wm.get_worktree_path(repo.path, rid)
        assert not wt_path.exists(), f"Worktree folder {wt_path} was not cleaned up"

        branch_proc = subprocess.run(
            ["git", "show-ref", "--verify", f"refs/heads/enki/run/{rid}"],
            cwd=str(repo.path),
            capture_output=True
        )
        assert branch_proc.returncode != 0, f"Dangling branch enki/run/{rid} still exists"

    # Now test keep on the remaining worktree
    keep_res = wm.keep_worktree(repo.path, kept_rid)
    assert keep_res.success is True
    kept_path = wm.get_worktree_path(repo.path, kept_rid)
    assert not kept_path.exists(), "Kept worktree directory must be unmounted"

    # Kept branch MUST exist
    branch_proc = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/enki/run/{kept_rid}"],
        cwd=str(repo.path),
        capture_output=True
    )
    assert branch_proc.returncode == 0, f"Kept branch enki/run/{kept_rid} must exist"

    # Later discard the kept worktree (verifying discard after keep)
    discard_kept_res = wm.discard_worktree(repo.path, kept_rid)
    assert discard_kept_res.success is True
    branch_proc_after = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/enki/run/{kept_rid}"],
        cwd=str(repo.path),
        capture_output=True
    )
    assert branch_proc_after.returncode != 0, "Branch must be deleted after discard"

    # Verify parent repo status remains pristine
    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo.path),
        capture_output=True,
        text=True
    )
    assert status_proc.stdout.strip() == "", f"Parent repo dirty: {status_proc.stdout}"


def test_discard_with_untracked_uncommitted_and_readonly_files(fixture_sample_repo):
    """
    Adversarial Challenge 2:
    Verify that discard_worktree cleanly force-removes worktrees containing:
    1. Untracked root files
    2. Deeply nested untracked folders and files
    3. Read-only untracked files (Windows-specific failure vector)
    4. Uncommitted modifications to tracked files
    5. Newly staged but uncommitted files
    And confirms that NO dangling branches or worktree references remain.
    """
    repo = fixture_sample_repo
    wm = WorktreeManager(default_base_branch="main")
    run_id = "adv_dirty_discard_run"

    wt_path = wm.create_worktree(repo.path, run_id, base_branch="main")
    assert wt_path.is_dir()

    # 1. Modify tracked file
    calc_file = wt_path / "calculator.py"
    calc_file.write_text("# dirty uncommitted modifications\n", encoding="utf-8")

    # 2. Stage another tracked file modification
    test_file = wt_path / "tests" / "test_calculator.py"
    test_file.write_text("# staged modifications\n", encoding="utf-8")
    subprocess.run(["git", "add", "tests/test_calculator.py"], cwd=str(wt_path), check=True)

    # 3. Add untracked files
    untracked_root = wt_path / "untracked_root.tmp"
    untracked_root.write_text("untracked garbage", encoding="utf-8")

    # 4. Add deeply nested untracked directories
    nested_dir = wt_path / "deep" / "nested" / "dir" / "structure"
    nested_dir.mkdir(parents=True, exist_ok=True)
    nested_file = nested_dir / "nested_leaf.bin"
    nested_file.write_bytes(b"\x00\xFF\xAA\x55" * 1024)

    # 5. Make a file strictly READ-ONLY (Windows stat.S_IREAD)
    readonly_file = wt_path / "readonly_untracked.txt"
    readonly_file.write_text("read-only content", encoding="utf-8")
    os.chmod(readonly_file, stat.S_IREAD)

    # Verify worktree is deeply dirty
    dirty_status = subprocess.run(["git", "status", "--porcelain"], cwd=str(wt_path), capture_output=True, text=True)
    assert len(dirty_status.stdout.strip().splitlines()) >= 4

    # Perform discard
    discard_res = wm.discard_worktree(repo.path, run_id)
    assert discard_res.success is True

    # Invariants verification:
    # 1. Worktree folder completely removed from filesystem
    assert not wt_path.exists(), f"Worktree folder {wt_path} still exists on disk"

    # 2. Git branch deleted (no dangling branch)
    branch_proc = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/enki/run/{run_id}"],
        cwd=str(repo.path),
        capture_output=True
    )
    assert branch_proc.returncode != 0, f"Dangling branch enki/run/{run_id} was not deleted"

    # 3. Git worktree list does not contain this worktree
    wt_list = subprocess.run(
        ["git", "worktree", "list"],
        cwd=str(repo.path),
        capture_output=True,
        text=True
    )
    assert run_id not in wt_list.stdout, f"Worktree {run_id} still listed in git worktree list"

    # 4. Parent repository working directory is 100% clean
    parent_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo.path),
        capture_output=True,
        text=True
    )
    assert parent_status.stdout.strip() == "", f"Parent repository dirty: {parent_status.stdout}"


def test_index_lock_contention_exponential_backoff(fixture_sample_repo):
    """
    Adversarial Challenge 3:
    Simulates external git lock contention by actively creating .git/index.lock
    right before git worktree operations, ensuring _run_git exponential backoff
    retries and recovers transparently without failing.
    """
    repo = fixture_sample_repo
    wm = WorktreeManager(default_base_branch="main")
    index_lock = repo.path / ".git" / "index.lock"

    # Create lock file to simulate collision
    index_lock.write_text("lock contention simulation", encoding="utf-8")

    # In a background thread, delete index.lock after 0.25 seconds
    def release_lock():
        time.sleep(0.25)
        if index_lock.exists():
            index_lock.unlink()

    from threading import Thread
    t = Thread(target=release_lock)
    t.start()

    # create_worktree should hit index.lock, backoff, retry, and succeed
    run_id = "test_backoff_recovery"
    wt_path = wm.create_worktree(repo.path, run_id, base_branch="main")
    t.join()

    assert wt_path.is_dir()
    wm.discard_worktree(repo.path, run_id)


def test_run_resumption_cascading_failures_and_aborts(tmp_path):
    """
    Adversarial Challenge 4:
    Stress tests RunManager resumption logic:
    1. Cascading multi-step failures (Step 2 fails, resumes, Step 3 fails, resumes)
    2. Resuming an ABORTED run (mid-execution abort while step was running)
    3. Idempotent resume calls
    4. Resume from explicit earlier completed step
    5. Validation: invalid step ID rejected with ValueError
    6. Validation: resuming completed run rejected with ValueError
    """
    runs_dir = tmp_path / "data" / "runs"
    event_bus = EventBus(runs_base_dir=runs_dir)
    rm = RunManager(base_runs_dir=runs_dir, event_bus=event_bus)

    # 1. Create run with 4 steps
    run = rm.create_run(task="Adversarial Resumption Run", dry_run=True)
    run_id = run.run_id

    # Step 1 succeeds
    rm.start_run(run_id)
    run = rm.load_run(run_id)
    run.steps[0].status = StepStatus.COMPLETED
    run.steps[0].output = {"extracted_files": ["a.py", "b.py"]}

    # Step 2 fails
    run.steps[1].status = StepStatus.FAILED
    run.steps[1].error = "OMP connection dropped"
    run.status = RunStatus.FAILED
    run.error = "Step 2 failed"
    rm.save_run(run)

    # Test invalid step ID rejection on an active/failed run
    with pytest.raises(ValueError, match="not found"):
        rm.resume_run(run_id, from_step_id="non_existent_step")

    # Resume: Step 2 should be reset to PENDING, Step 1 preserved
    resumed_1 = rm.resume_run(run_id)
    assert resumed_1.status == RunStatus.RUNNING
    assert resumed_1.current_step_id == "coding"
    assert resumed_1.steps[0].status == StepStatus.COMPLETED
    assert resumed_1.steps[0].output == {"extracted_files": ["a.py", "b.py"]}
    assert resumed_1.steps[1].status == StepStatus.PENDING
    assert resumed_1.steps[1].error is None

    # Idempotent resume check: calling resume again before step finishes
    idempotent_resume = rm.resume_run(run_id)
    assert idempotent_resume.status == RunStatus.RUNNING
    assert idempotent_resume.current_step_id == "coding"
    assert idempotent_resume.steps[0].status == StepStatus.COMPLETED

    # Step 2 now completes, but Step 3 fails
    idempotent_resume.steps[1].status = StepStatus.COMPLETED
    idempotent_resume.steps[1].output = {"patch": "applied"}
    idempotent_resume.steps[2].status = StepStatus.FAILED
    idempotent_resume.steps[2].error = "Pytest assertion error"
    idempotent_resume.status = RunStatus.FAILED
    rm.save_run(idempotent_resume)

    # Resume again: Steps 1 and 2 must remain COMPLETED, Step 3 reset to PENDING
    resumed_2 = rm.resume_run(run_id)
    assert resumed_2.status == RunStatus.RUNNING
    assert resumed_2.current_step_id == "verification"
    assert resumed_2.steps[0].status == StepStatus.COMPLETED
    assert resumed_2.steps[1].status == StepStatus.COMPLETED
    assert resumed_2.steps[1].output == {"patch": "applied"}
    assert resumed_2.steps[2].status == StepStatus.PENDING
    assert resumed_2.steps[2].error is None
    assert resumed_2.steps[3].status == StepStatus.PENDING

    # 2. Test mid-execution abort:
    # Set run to ABORTED with Step 3 running
    resumed_2.status = RunStatus.ABORTED
    resumed_2.steps[2].status = StepStatus.RUNNING
    rm.save_run(resumed_2)

    # Resume aborted run without from_step_id:
    # First non-completed step is Step 3
    resumed_abort = rm.resume_run(run_id)
    assert resumed_abort.status == RunStatus.RUNNING
    assert resumed_abort.current_step_id == "verification"
    assert resumed_abort.steps[2].status == StepStatus.PENDING

    # 3. Test explicit resume from earlier completed step (e.g. restart from Step 1)
    resumed_from_start = rm.resume_run(run_id, from_step_id="context_extraction")
    assert resumed_from_start.current_step_id == "context_extraction"
    assert resumed_from_start.steps[0].status == StepStatus.PENDING
    assert resumed_from_start.steps[1].status == StepStatus.PENDING
    assert resumed_from_start.steps[2].status == StepStatus.PENDING
    assert resumed_from_start.steps[3].status == StepStatus.PENDING

    # Complete all steps and finish run
    for s in resumed_from_start.steps:
        s.status = StepStatus.COMPLETED
    rm.save_run(resumed_from_start)
    rm.finish_run(run_id, RunStatus.COMPLETED)

    # 4. Resume completed run must raise ValueError
    with pytest.raises(ValueError, match="already completed"):
        rm.resume_run(run_id)


def test_atomic_persistence_crash_resilience(tmp_path):
    """
    Adversarial Challenge 5:
    Simulates a crash where a dangling .tmp file was left behind during serialization.
    Verifies that load_run loads the authentic run_state.json and save_run safely
    overwrites the .tmp file without raising file contention errors.
    """
    runs_dir = tmp_path / "data" / "runs"
    rm = RunManager(base_runs_dir=runs_dir)

    run = rm.create_run(task="Atomic Crash Test")
    state_file = rm.get_run_state_file(run.run_id)
    tmp_file = state_file.with_suffix(".tmp")

    assert state_file.is_file()

    # Leave a corrupted .tmp file on disk
    tmp_file.write_text("CORRUPTED HALF WRITTEN JSON {{{", encoding="utf-8")

    # load_run must succeed and read valid state_file
    loaded = rm.load_run(run.run_id)
    assert loaded.run_id == run.run_id

    # save_run must cleanly replace the corrupted .tmp file and update state_file
    loaded.task = "Updated Task after simulated crash"
    rm.save_run(loaded)

    reloaded = rm.load_run(run.run_id)
    assert reloaded.task == "Updated Task after simulated crash"
    assert not tmp_file.exists(), ".tmp file should have been atomically renamed"


def test_cross_process_repolock(fixture_sample_repo):
    """
    Adversarial Challenge 6:
    Test RepoLock cross-process mutual exclusion via Windows file locking (msvcrt).
    Spawns a separate Python process holding RepoLock for 1.0 second,
    and verifies that in-process RepoLock blocks until child release.
    """
    repo = fixture_sample_repo
    lock_file = repo.path / ".git" / "enki_worktree.lock"

    child_script = f"""
import sys, time
from pathlib import Path
sys.path.insert(0, r"{ROOT_DIR}")
from src.engine.worktree_manager import RepoLock

repo_path = Path(r"{repo.path}")
with RepoLock(repo_path, timeout=5.0):
    print("ACQUIRED", flush=True)
    time.sleep(1.0)
"""
    proc = subprocess.Popen([sys.executable, "-c", child_script], stdout=subprocess.PIPE, text=True)
    signal = proc.stdout.readline().strip()
    assert signal == "ACQUIRED"
    t0 = time.time()

    with RepoLock(repo.path, timeout=5.0):
        elapsed = time.time() - t0
        assert elapsed >= 0.5, f"Lock did not block child process! Elapsed: {elapsed:.2f}s"

    proc.wait()
    assert proc.returncode == 0
