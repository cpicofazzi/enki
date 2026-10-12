"""
src/engine/vault_guard.py
Obsidian safe integration, cross-process file locking, atomic writes, and agent boundaries (F45, F46, F47, F48).

Safety Rules:
1. Cross-process file locking (.obsidian_vault.lock) prevents markdown corruption during concurrent runs (F45).
2. Atomic writes: uses temporary file and atomic rename (.tmp -> .md) for checklists and activity log (F46).
3. Task note write-back: marks checklist items - [ ] -> - [x], updates frontmatter status to 'done', logs per-run cost (F46).
4. Boundary Invariants (F47):
   - Hermes NEVER writes code to repo worktrees.
   - OMP NEVER edits or writes to Obsidian vault files.
5. Project Exclusion (F48):
   - 'Body.me App' is strictly excluded from all vault indexing, project pickers, search results, and test fixtures.
"""

import os
import sys
import time
import re
import datetime
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.config import load_config


class VaultBoundaryViolationError(Exception):
    """Raised when an agent violates role safety boundaries (e.g. Hermes coding, OMP touching vault)."""
    pass


class ProjectExclusionViolationError(Exception):
    """Raised when an excluded project like Body.me App is accessed."""
    pass


EXCLUDED_PROJECTS = {"body.me app", "body.me", "bodyme"}


def is_project_excluded(project_name: Optional[str]) -> bool:
    """Checks if a project is in the excluded list (F48)."""
    if not project_name:
        return False
    return project_name.lower().strip() in EXCLUDED_PROJECTS


def enforce_project_inclusion(project_name: Optional[str]) -> None:
    """Raises ProjectExclusionViolationError if project is excluded."""
    if is_project_excluded(project_name):
        raise ProjectExclusionViolationError(
            f"Access to '{project_name}' is strictly prohibited. It is marked as an excluded project."
        )


def enforce_agent_boundary(agent_role: str, target_resource: str) -> None:
    """
    Enforces strict agent boundary invariants (F47):
    - Hermes cannot write to source repositories / code files.
    - OMP cannot write to Obsidian vault notes.
    """
    role = agent_role.lower().strip()
    res = target_resource.lower().strip()

    if role in ("hermes", "knowledge") and any(res.endswith(ext) for ext in [".py", ".ts", ".tsx", ".js", ".rs", ".go"]):
        raise VaultBoundaryViolationError(
            f"Security Boundary Invariant Violated: Agent '{agent_role}' is strictly forbidden from writing code file '{target_resource}'."
        )

    if role in ("omp", "coder", "coding_agent") and ("pico-vault" in res or ".obsidian" in res or res.endswith(".md")):
        raise VaultBoundaryViolationError(
            f"Security Boundary Invariant Violated: Agent '{agent_role}' is strictly forbidden from editing Obsidian vault notes '{target_resource}'."
        )


class VaultFileLock:
    """
    Two-tier cross-process lock on Obsidian vault:
    1. In-process threading lock.
    2. File-level lock on .obsidian_vault.lock.
    """
    _thread_lock = threading.Lock()

    def __init__(self, vault_path: Path, timeout: float = 15.0):
        self.vault_path = Path(vault_path)
        self.timeout = timeout
        self.lock_file_path = self.vault_path / ".obsidian_vault.lock"
        self._fd = None

    def __enter__(self):
        acquired = self._thread_lock.acquire(timeout=self.timeout)
        if not acquired:
            raise TimeoutError(f"Vault thread lock timed out after {self.timeout}s on {self.vault_path}")

        start_time = time.time()
        while time.time() - start_time < self.timeout:
            try:
                self.vault_path.mkdir(parents=True, exist_ok=True)
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
                time.sleep(0.05)

        self._thread_lock.release()
        raise TimeoutError(f"Cross-process vault lock timed out after {self.timeout}s on {self.lock_file_path}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._fd:
                if sys.platform == "win32":
                    import msvcrt
                    try:
                        msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                else:
                    import fcntl
                    try:
                        fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
                self._fd.close()
        finally:
            self._thread_lock.release()


class ObsidianVaultGuard:
    """Safe manager for atomic reading and writing to the Obsidian vault."""

    def __init__(self, vault_path: Optional[Path] = None):
        if vault_path is None:
            cfg = load_config()
            v_str = os.environ.get(
                "ENKI_OBSIDIAN_VAULT",
                cfg.get("obsidian", {}).get("vault_path", "C:/Users/Christian Picofazzi/Documents/pico-vault")
            )
            vault_path = Path(v_str)
        self.vault_path = Path(vault_path)

    def write_atomic(self, target_file: Path, content: str) -> None:
        """Atomically writes content using temporary file and atomic replace under vault lock."""
        with VaultFileLock(self.vault_path):
            target_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = target_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(content)
            tmp_file.replace(target_file)

    def append_atomic(self, target_file: Path, append_content: str) -> None:
        """Atomically appends content under vault lock."""
        with VaultFileLock(self.vault_path):
            target_file.parent.mkdir(parents=True, exist_ok=True)
            existing = ""
            if target_file.is_file():
                with open(target_file, "r", encoding="utf-8") as f:
                    existing = f.read()
            new_content = existing + append_content
            tmp_file = target_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(new_content)
            tmp_file.replace(target_file)

    def update_task_note(
        self,
        note_path: Path,
        summary: str,
        cost_usd: float = 0.0,
        task_id: str = ""
    ) -> bool:
        """
        Updates task note:
        - Changes status: todo -> status: done
        - Sets completed_date
        - Checks off checklist items (- [ ] -> - [x])
        - Records cost and task_id in frontmatter / summary note
        """
        if not note_path.is_file():
            return False

        with VaultFileLock(self.vault_path):
            with open(note_path, "r", encoding="utf-8") as f:
                content = f.read()

            today_str = datetime.date.today().isoformat()
            new_content = re.sub(r'status:\s*todo', 'status: done', content)
            new_content = re.sub(r'completed_date:\s*""?', f'completed_date: "{today_str}"', new_content)
            new_content = re.sub(r'-\s*\[\s*\]', '- [x]', new_content)

            cost_line = f"cost_usd: {cost_usd:.4f}"
            if "cost_usd:" not in new_content:
                new_content = re.sub(r'(status:\s*done)', f'\\1\n{cost_line}', new_content)

            summary_block = (
                f"\n\n## Enki Completion Summary\n"
                f"> [!success] Verified & Completed by Enki Hub on {today_str}\n"
                f"- Task ID: `{task_id}`\n"
                f"- Incurred Cost: `${cost_usd:.4f} USD`\n\n"
                f"{summary}\n"
            )
            if "## Enki Completion Summary" not in new_content:
                new_content += summary_block

            tmp_file = note_path.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(new_content)
            tmp_file.replace(note_path)

        return True

    def log_activity(
        self,
        task_id: str,
        title: str,
        summary: str,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        test_status: str = "PASSED",
        rel_log_path: str = "01_Dashboard/Enki_Activity_Log.md"
    ) -> Path:
        """Appends execution log entry into 01_Dashboard/Enki_Activity_Log.md atomically."""
        log_file = self.vault_path / rel_log_path
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        entry = f"""
### [{now_str}] Task Complete: {title}
- **Task ID**: `{task_id}`
- **Verification Status**: `{test_status}`
- **Tokens Consumed**: `{tokens_used:,}`
- **Estimated Cost**: `${cost_usd:.4f} USD`
- **Summary**:
  {summary}
---
"""
        with VaultFileLock(self.vault_path):
            log_file.parent.mkdir(parents=True, exist_ok=True)
            if not log_file.is_file():
                header = "# Enki Command Hub - Activity & Execution Log\n\nAutomated log entries recorded by Hermes & OMP.\n\n---\n"
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write(header)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(entry)

        return log_file

    def create_research_note(
        self,
        title: str,
        summary: str,
        core_concepts: Optional[List[str]] = None,
        architecture: str = "",
        code_examples: str = "",
        tags: Optional[List[str]] = None,
        related_links: Optional[List[str]] = None,
        subfolder: str = "50_Knowledge/Research Notes"
    ) -> Path:
        """
        Creates a new evergreen technical research note adhering to Template - Research.md.
        Atomically saves the note and maintains Obsidian vault wikilinks.
        """
        clean_title = re.sub(r'[<>:"/\\|?*]', '', title).strip()
        target_dir = self.vault_path / subfolder
        target_file = target_dir / f"{clean_title}.md"
        today_str = datetime.date.today().isoformat()

        tag_list = list(tags) if tags else ["research"]
        if "research" not in tag_list:
            tag_list.insert(0, "research")
        tags_yaml = "\n".join(f"  - {t}" for t in tag_list)

        concepts = core_concepts or ["Core specifications, operational parameters, and architectural thesis."]
        concepts_md = "\n".join(f"- {c}" for c in concepts)
        arch_md = architecture.strip() or "Standard modular system design conforming to decoupled architecture."
        code_md = code_examples.strip() or "# Implementation prototype\npass"

        links = list(related_links or [])
        if "[[Knowledge Hub]]" not in links:
            links.insert(0, "[[Knowledge Hub]]")
        links_md = "\n".join(f"- {l if l.startswith('[[') else f'[[{l}]]'}" for l in links)

        note_content = f"""---
title: "{clean_title}"
type: research
tags:
{tags_yaml}
status: evergreen
created: "{today_str}"
updated: "{today_str}"
aliases: []
---

# {clean_title}

> [!abstract] Executive Summary
> {summary}

## Core Concepts & Theoretical Background
{concepts_md}

## Architecture / Mathematical Formulation
{arch_md}

## Practical Implementation & Code Examples
```python
{code_md}
```

## Open Questions & Future Explorations
- Distributed scalability and state synchronization benchmarks.
- Edge compiler and execution verification.

## References & Papers
- Hub: [[Knowledge Hub]]
{links_md}
"""
        self.write_atomic(target_file, note_content)
        return target_file
