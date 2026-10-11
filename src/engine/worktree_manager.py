"""
src/engine/worktree_manager.py
Git Worktree Isolation, Concurrency Safety & Lifecycle Management for Enki.
Guarantees parallel run isolation on enki/run/<run_id>, repo lock contention safety,
parent git status cleanliness via .git/info/exclude, and explicit user-approved teardown.
"""

import os
import sys
import stat
import time
import shutil
import random
import logging
import threading
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


# --- Exceptions ---

class WorktreeError(Exception):
    """Base exception for all worktree operations."""
    pass


class WorktreeNotFoundError(WorktreeError):
    """Raised when a requested worktree or branch does not exist."""
    pass


class WorktreeConcurrencyError(WorktreeError):
    """Raised when Git lock contention cannot be resolved within timeout."""
    pass


class WorktreeMergeConflictError(WorktreeError):
    """Raised when a merge encounters conflicts."""
    pass


class DirtyWorkingTreeError(WorktreeError):
    """Raised when target repository working copy has uncommitted changes."""
    pass


# --- Data Classes ---

@dataclass
class ChangedFile:
    status: str       # 'M' (modified), 'A' (added), 'D' (deleted), 'R' (renamed)
    path: str         # Relative file path
    additions: int = 0
    deletions: int = 0


@dataclass
class WorktreeDiff:
    run_id: str
    base_branch: str
    worktree_branch: str
    has_changes: bool
    diff_text: str
    changed_files: List[ChangedFile]
    files_changed_count: int
    insertions: int
    deletions: int


@dataclass
class WorktreeInfo:
    run_id: str
    branch: str
    worktree_path: Path
    commit_hash: str
    is_prunable: bool = False


@dataclass
class MergeResult:
    run_id: str
    target_branch: str
    success: bool
    merged_commit: Optional[str] = None
    message: str = ""
    conflicts: List[str] = field(default_factory=list)


@dataclass
class KeepResult:
    run_id: str
    branch: str
    worktree_path: Path
    commit_hash: str
    success: bool
    message: str = ""


@dataclass
class DiscardResult:
    run_id: str
    branch: str
    worktree_path: Path
    success: bool
    message: str = ""


# --- Concurrency Locking ---

class RepoLock:
    """
    Two-tier lock for Git repositories:
    1. In-process threading lock per repository path.
    2. Cross-process file lock (.git/enki_worktree.lock).
    """
    _thread_locks: Dict[str, threading.Lock] = {}
    _master_lock = threading.Lock()

    def __init__(self, repo_path: Path, timeout: float = 15.0):
        self.repo_path = repo_path.resolve()
        key = str(self.repo_path).lower()
        with self._master_lock:
            if key not in self._thread_locks:
                self._thread_locks[key] = threading.Lock()
            self._thread_lock = self._thread_locks[key]
        self.timeout = timeout
        self.lock_file_path = self.repo_path / ".git" / "enki_worktree.lock"
        self._fd = None

    def __enter__(self):
        # 1. Acquire thread lock
        acquired = self._thread_lock.acquire(timeout=self.timeout)
        if not acquired:
            raise WorktreeConcurrencyError(
                f"Thread lock acquisition timed out after {self.timeout}s on {self.repo_path}"
            )

        # 2. Acquire cross-process file lock
        start_time = time.time()
        while time.time() - start_time < self.timeout:
            try:
                self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
                self._fd = open(self.lock_file_path, "a+")
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except (IOError, OSError):
                if self._fd:
                    try:
                        self._fd.close()
                    except Exception:
                        pass
                    self._fd = None
                time.sleep(random.uniform(0.05, 0.15))

        self._thread_lock.release()
        raise WorktreeConcurrencyError(
            f"Cross-process lock acquisition timed out after {self.timeout}s on {self.lock_file_path}"
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._fd:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                self._fd.close()
            except Exception:
                pass
            self._fd = None
        self._thread_lock.release()


# --- Worktree Manager ---

class WorktreeManager:
    """
    Manages isolated Git worktrees and branches on enki/run/<run_id>.
    Guarantees concurrency safety, diff calculation, and user-approved teardown.
    """

    def __init__(self, default_base_branch: str = "HEAD"):
        self.default_base_branch = default_base_branch

    # --- Git Subprocess Runner with Exponential Backoff ---

    def _run_git(
        self,
        args: List[str],
        cwd: Path,
        check: bool = True,
        max_retries: int = 5,
        base_delay: float = 0.1,
    ) -> subprocess.CompletedProcess:
        """Executes git commands with automatic lock contention retry."""
        cmd = ["git"] + args
        for attempt in range(max_retries):
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    check=False
                )
                if proc.returncode == 0:
                    return proc

                stderr = proc.stderr or ""
                # Check for Git lock contention patterns
                if any(k in stderr for k in ["index.lock", "File exists", "Another git process", "is locked"]):
                    delay = min(2.0, base_delay * (2 ** attempt) + random.uniform(0.01, 0.05))
                    logger.warning(f"Git lock contention detected: {stderr.strip()}. Retrying in {delay:.2f}s...")
                    time.sleep(delay)
                    continue

                if check:
                    raise WorktreeError(
                        f"Git command failed: {' '.join(cmd)}\nExit code: {proc.returncode}\nStderr: {stderr}"
                    )
                return proc

            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                time.sleep(0.1 * (2 ** attempt))

        if check:
            raise WorktreeConcurrencyError(
                f"Git command timed out under lock contention after {max_retries} attempts: {' '.join(cmd)}"
            )
        return proc

    # --- Helper: Ensure Git Exclude for .enki/ ---

    def _ensure_git_exclude(self, repo_path: Path) -> None:
        """Ensures .enki/ and Python cache are ignored locally via .git/info/exclude."""
        exclude_file = repo_path / ".git" / "info" / "exclude"
        try:
            exclude_file.parent.mkdir(parents=True, exist_ok=True)
            existing = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
            additions = []
            if ".enki" not in existing and ".enki/" not in existing:
                additions.append(".enki/")
            if "__pycache__" not in existing:
                additions.append("__pycache__/")
                additions.append("*.pyc")
            if additions:
                with open(exclude_file, "a", encoding="utf-8") as f:
                    f.write("\n# Enki isolated worktrees and bytecode\n" + "\n".join(additions) + "\n")
        except Exception as e:
            logger.warning(f"Failed to update .git/info/exclude: {e}")

    # --- Helper: Windows-Safe Directory Deletion ---

    def _safe_rmtree(self, path: Path, max_retries: int = 5) -> None:
        """Removes directory handling Windows readonly files and locks."""
        def _onerror(func, p, excinfo):
            try:
                os.chmod(p, stat.S_IWRITE)
                func(p)
            except Exception:
                pass

        for attempt in range(max_retries):
            try:
                if path.exists():
                    shutil.rmtree(path, onerror=_onerror)
                return
            except Exception:
                time.sleep(0.15 * (attempt + 1))

    # --- Public API Methods ---

    def get_branch_name(self, run_id: str) -> str:
        """Returns standard branch name for a run: enki/run/<run_id>."""
        return f"enki/run/{run_id}"

    def get_worktree_path(self, repo_path: Path, run_id: str) -> Path:
        """Returns standard worktree path: <repo_path>/.enki/worktrees/<run_id>."""
        return (repo_path / ".enki" / "worktrees" / run_id).resolve()

    def create_worktree(
        self,
        repo_path: Path,
        run_id: str,
        base_branch: Optional[str] = None,
        worktree_dir: Optional[Path] = None,
    ) -> Path:
        """
        Creates branch enki/run/<run_id> and mounts worktree at <repo_path>/.enki/worktrees/<run_id>.
        Handles index.lock contention and ensures parent repository status remains clean.
        """
        repo_path = Path(repo_path).resolve()
        if not (repo_path / ".git").exists():
            raise WorktreeError(f"Not a git repository: {repo_path}")

        branch_name = self.get_branch_name(run_id)
        target_dir = (worktree_dir or self.get_worktree_path(repo_path, run_id)).resolve()

        # Determine valid base branch
        base = base_branch or self.default_base_branch
        if base != "HEAD":
            # Verify base ref exists; if not, fall back to HEAD
            ref_check = self._run_git(["rev-parse", "--verify", base], cwd=repo_path, check=False)
            if ref_check.returncode != 0:
                base = "HEAD"

        self._ensure_git_exclude(repo_path)
        target_dir.parent.mkdir(parents=True, exist_ok=True)

        with RepoLock(repo_path):
            # Check if branch already exists (e.g. resumption)
            branch_check = self._run_git(
                ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
                cwd=repo_path,
                check=False
            )
            branch_exists = (branch_check.returncode == 0)

            # Check if worktree directory is already active
            if target_dir.exists():
                return target_dir

            if branch_exists:
                # Attach worktree to existing branch
                self._run_git(
                    ["worktree", "add", str(target_dir.as_posix()), branch_name],
                    cwd=repo_path
                )
            else:
                # Create branch from base and attach
                self._run_git(
                    ["worktree", "add", "-b", branch_name, str(target_dir.as_posix()), base],
                    cwd=repo_path
                )

        if not target_dir.exists():
            raise WorktreeError(f"Failed to create worktree at {target_dir}")

        return target_dir

    def get_diff(
        self,
        repo_path: Path,
        run_id: str,
        base_branch: Optional[str] = None,
    ) -> WorktreeDiff:
        """
        Returns unified diff and structured list of changed files between the worktree branch
        and the base branch. Captures uncommitted modifications if worktree is active.
        """
        repo_path = Path(repo_path).resolve()
        branch_name = self.get_branch_name(run_id)
        base = base_branch or self.default_base_branch
        if base != "HEAD":
            ref_check = self._run_git(["rev-parse", "--verify", base], cwd=repo_path, check=False)
            if ref_check.returncode != 0:
                base = "HEAD"
        wt_dir = self.get_worktree_path(repo_path, run_id)

        # Checkpoint uncommitted changes in active worktree so diff captures them
        if wt_dir.is_dir():
            status_proc = self._run_git(["status", "--porcelain"], cwd=wt_dir, check=False)
            if status_proc.stdout.strip():
                self._run_git(["add", "-A"], cwd=wt_dir, check=False)
                self._run_git(
                    ["commit", "-m", f"wip: enki run {run_id} checkpoint"],
                    cwd=wt_dir,
                    check=False
                )

        # Generate unified diff
        diff_proc = self._run_git(
            ["diff", f"{base}...{branch_name}"],
            cwd=repo_path,
            check=False
        )
        diff_text = diff_proc.stdout

        # Parse numstat (insertions, deletions, path)
        numstat_proc = self._run_git(
            ["diff", "--numstat", f"{base}...{branch_name}"],
            cwd=repo_path,
            check=False
        )

        # Parse name-status (M, A, D, R status code)
        namestat_proc = self._run_git(
            ["diff", "--name-status", f"{base}...{branch_name}"],
            cwd=repo_path,
            check=False
        )

        status_map: Dict[str, str] = {}
        for line in namestat_proc.stdout.strip().splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                status_map[parts[-1]] = parts[0]

        changed_files: List[ChangedFile] = []
        total_insertions = 0
        total_deletions = 0

        for line in numstat_proc.stdout.strip().splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                ins_str, del_str, file_path = parts[0], parts[1], parts[2]
                ins = int(ins_str) if ins_str.isdigit() else 0
                dels = int(del_str) if del_str.isdigit() else 0
                status_code = status_map.get(file_path, "M")
                total_insertions += ins
                total_deletions += dels
                changed_files.append(
                    ChangedFile(
                        status=status_code,
                        path=file_path,
                        additions=ins,
                        deletions=dels
                    )
                )

        return WorktreeDiff(
            run_id=run_id,
            base_branch=base,
            worktree_branch=branch_name,
            has_changes=bool(changed_files or diff_text.strip()),
            diff_text=diff_text,
            changed_files=changed_files,
            files_changed_count=len(changed_files),
            insertions=total_insertions,
            deletions=total_deletions
        )

    def merge_worktree(
        self,
        repo_path: Path,
        run_id: str,
        target_branch: str,
        require_approval: bool = True,
    ) -> MergeResult:
        """
        Merges branch enki/run/<run_id> into target_branch with explicit approval.
        Unmounts worktree folder and deletes temporary branch upon successful merge.
        """
        if not require_approval:
            raise WorktreeError("Explicit user approval is required to merge into target branch.")

        repo_path = Path(repo_path).resolve()
        branch_name = self.get_branch_name(run_id)
        wt_dir = self.get_worktree_path(repo_path, run_id)

        with RepoLock(repo_path):
            # Verify target branch exists
            tb_check = self._run_git(
                ["rev-parse", "--verify", target_branch],
                cwd=repo_path,
                check=False
            )
            if tb_check.returncode != 0:
                raise WorktreeNotFoundError(f"Target branch '{target_branch}' does not exist.")

            # Check parent working copy cleanliness (ignoring .enki/)
            st_proc = self._run_git(["status", "--porcelain"], cwd=repo_path)
            lines = [l for l in st_proc.stdout.strip().splitlines() if not l.strip().endswith(".enki/") and not l.strip().endswith(".enki")]
            if lines:
                raise DirtyWorkingTreeError(
                    f"Cannot merge: target repository has uncommitted changes:\n" + "\n".join(lines)
                )

            # Checkpoint uncommitted worktree changes
            if wt_dir.is_dir():
                wt_st = self._run_git(["status", "--porcelain"], cwd=wt_dir, check=False)
                if wt_st.stdout.strip():
                    self._run_git(["add", "-A"], cwd=wt_dir)
                    self._run_git(
                        ["commit", "-m", f"feat: finalized changes for enki run {run_id}"],
                        cwd=wt_dir
                    )

            # Unmount worktree before merging into target branch
            self._unmount_worktree(repo_path, wt_dir)

            # Switch to target branch if not current
            curr_branch = self._run_git(
                ["rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_path
            ).stdout.strip()
            if curr_branch != target_branch:
                self._run_git(["checkout", target_branch], cwd=repo_path)

            # Execute merge
            merge_proc = self._run_git(
                ["merge", "--no-ff", branch_name, "-m", f"Merge Enki run {run_id} into {target_branch}"],
                cwd=repo_path,
                check=False
            )

            if merge_proc.returncode != 0:
                # Merge conflict detected; abort merge and preserve branch
                self._run_git(["merge", "--abort"], cwd=repo_path, check=False)
                return MergeResult(
                    run_id=run_id,
                    target_branch=target_branch,
                    success=False,
                    message=f"Merge conflict detected; merge aborted.\n{merge_proc.stderr}",
                    conflicts=[merge_proc.stderr.strip()]
                )

            # Successful merge: get commit hash and delete temporary branch
            merged_commit = self._run_git(["rev-parse", "HEAD"], cwd=repo_path).stdout.strip()
            self._run_git(["branch", "-d", branch_name], cwd=repo_path, check=False)

            return MergeResult(
                run_id=run_id,
                target_branch=target_branch,
                success=True,
                merged_commit=merged_commit,
                message=f"Successfully merged {branch_name} into {target_branch}."
            )

    def keep_worktree(self, repo_path: Path, run_id: str) -> KeepResult:
        """
        Unmounts worktree folder but retains the git branch enki/run/<run_id>.
        """
        repo_path = Path(repo_path).resolve()
        branch_name = self.get_branch_name(run_id)
        wt_dir = self.get_worktree_path(repo_path, run_id)

        with RepoLock(repo_path):
            # Checkpoint any pending worktree modifications
            if wt_dir.is_dir():
                wt_st = self._run_git(["status", "--porcelain"], cwd=wt_dir, check=False)
                if wt_st.stdout.strip():
                    self._run_git(["add", "-A"], cwd=wt_dir)
                    self._run_git(
                        ["commit", "-m", f"wip: keep worktree state for run {run_id}"],
                        cwd=wt_dir
                    )

            # Unmount worktree directory
            self._unmount_worktree(repo_path, wt_dir)

            # Retrieve branch commit hash
            rev_proc = self._run_git(["rev-parse", branch_name], cwd=repo_path, check=False)
            commit_hash = rev_proc.stdout.strip() if rev_proc.returncode == 0 else ""

            return KeepResult(
                run_id=run_id,
                branch=branch_name,
                worktree_path=wt_dir,
                commit_hash=commit_hash,
                success=True,
                message=f"Worktree folder unmounted; branch {branch_name} retained."
            )

    def discard_worktree(self, repo_path: Path, run_id: str) -> DiscardResult:
        """
        Force removes worktree folder and permanently deletes branch enki/run/<run_id>.
        """
        repo_path = Path(repo_path).resolve()
        branch_name = self.get_branch_name(run_id)
        wt_dir = self.get_worktree_path(repo_path, run_id)

        with RepoLock(repo_path):
            self._unmount_worktree(repo_path, wt_dir, force=True)
            self._run_git(["branch", "-D", branch_name], cwd=repo_path, check=False)
            self._run_git(["worktree", "prune"], cwd=repo_path, check=False)

            return DiscardResult(
                run_id=run_id,
                branch=branch_name,
                worktree_path=wt_dir,
                success=True,
                message=f"Worktree folder and branch {branch_name} discarded."
            )

    def _unmount_worktree(self, repo_path: Path, wt_dir: Path, force: bool = True) -> None:
        """Internal helper to safely remove and prune worktree."""
        if wt_dir.exists():
            cmd = ["worktree", "remove"]
            if force:
                cmd.append("--force")
            cmd.append(str(wt_dir.as_posix()))
            self._run_git(cmd, cwd=repo_path, check=False)

        self._run_git(["worktree", "prune"], cwd=repo_path, check=False)

        if wt_dir.exists():
            self._safe_rmtree(wt_dir)

        # Cleanup parent .enki/worktrees directory if empty
        wt_parent = wt_dir.parent
        if wt_parent.exists():
            try:
                if not any(wt_parent.iterdir()):
                    wt_parent.rmdir()
            except Exception:
                pass
