"""
tests/test_budget_obsidian.py
Automated tests for Milestone 5:
- F44: Budget Stop Protocol & 3 user decisions (continue, pause, switch_cheaper)
- F45: Cross-process Obsidian vault file locking (.obsidian_vault.lock)
- F46: Obsidian Task Note Write-Back (checklist - [x], status done, per-run cost log)
- F47: Agent Boundary Safety (Hermes never writes code; OMP never edits vault)
- F48: Project Exclusion ('Body.me App' strictly prohibited across pickers and runs)
"""

import os
import re
import pytest
from pathlib import Path

from src.engine.models import Run, StepState, RunStatus, StepStatus, BudgetDecision
from src.engine.budget_guard import BudgetGuard, BudgetLimitReachedError
from src.engine.vault_guard import (
    ObsidianVaultGuard,
    VaultFileLock,
    VaultBoundaryViolationError,
    ProjectExclusionViolationError,
    enforce_agent_boundary,
    enforce_project_inclusion,
    is_project_excluded,
)
from src.obsidian_indexer import ObsidianIndexer


def test_budget_stop_protocol(tmp_path):
    """Test F44: Budget guard triggers when spend >= monthly budget ($25.00)."""
    guard = BudgetGuard(budget_override=10.0)

    run = Run(
        run_id="run_test_budget",
        task="Test budget stop",
        project="TestProject",
        workflow_id="four_step_pipeline",
        status=RunStatus.PENDING,
        steps=[StepState(step_id="coding", step_type="coding", name="Code Step")]
    )

    # 1. Simulate current spend below budget
    guard.get_current_spend = lambda: 5.0
    check = guard.check_budget()
    assert check.is_budget_exceeded is False
    assert check.decision_required is False

    # 2. Simulate current spend exceeding budget
    guard.get_current_spend = lambda: 12.50
    check_over = guard.check_budget()
    assert check_over.is_budget_exceeded is True
    assert check_over.decision_required is True

    # 3. Intercept raises BudgetLimitReachedError
    with pytest.raises(Exception):
        guard.intercept_before_call(run, step_id="coding", raise_on_intercept=True)

    assert run.status == RunStatus.WAITING_BUDGET
    assert run.budget_state.status == "pending"

    # 4. Apply decision: switch_cheaper
    updated_run = guard.apply_decision(run, decision=BudgetDecision.SWITCH_CHEAPER, cheaper_model="deepseek/deepseek-chat")
    assert updated_run.status == RunStatus.RUNNING
    assert updated_run.model_override == "deepseek/deepseek-chat"
    assert updated_run.budget_state.status == "resolved"

    # 5. Intercept allows pass once resolved
    pass_check = guard.intercept_before_call(updated_run, step_id="coding", raise_on_intercept=True)
    assert pass_check is not None


def test_obsidian_vault_locking(tmp_path):
    """Test F45: Cross-process file locking on the vault."""
    vault_dir = tmp_path / "mock_vault"
    vault_dir.mkdir(parents=True, exist_ok=True)

    # Test lock acquisition and release
    with VaultFileLock(vault_dir) as lock:
        assert lock.lock_file_path.is_file()
        assert (vault_dir / ".obsidian_vault.lock").is_file()

    # Verify atomic write under vault guard
    vg = ObsidianVaultGuard(vault_dir)
    target = vault_dir / "01_Dashboard" / "test_note.md"
    vg.write_atomic(target, "# Title\nContent under lock")
    assert target.is_file()
    assert "Content under lock" in target.read_text(encoding="utf-8")


def test_obsidian_task_note_write_back(fixture_vault):
    """Test F46: Task note checklist check-off and activity log append."""
    vg = ObsidianVaultGuard(fixture_vault)
    task_file = fixture_vault / "40_Tasks" / "Test_Dinner_Task.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    
    initial_content = """---
title: Test Dinner Task
project: Dinner Service Optimizer
status: todo
completed_date: ""
---

# Tasks
- [ ] Implement recipe normalizer
- [ ] Add pytest fixtures
"""
    task_file.write_text(initial_content, encoding="utf-8")

    # Perform update_task_note
    updated = vg.update_task_note(
        note_path=task_file,
        summary="All tests passed with $0.05 spend",
        cost_usd=0.05,
        task_id="run_123"
    )
    assert updated is True

    result_text = task_file.read_text(encoding="utf-8")
    assert "status: done" in result_text
    assert "- [x] Implement recipe normalizer" in result_text
    assert "- [x] Add pytest fixtures" in result_text
    assert "## Enki Completion Summary" in result_text
    assert "0.0500" in result_text

    # Log activity
    log_file = vg.log_activity(
        task_id="run_123",
        title="Test Dinner Task",
        summary="Completed normalization pipeline",
        tokens_used=1200,
        cost_usd=0.05,
        test_status="PASSED"
    )
    assert log_file.is_file()
    log_content = log_file.read_text(encoding="utf-8")
    assert "Task Complete: Test Dinner Task" in log_content
    assert "run_123" in log_content


def test_agent_boundary_invariants():
    """Test F47: Strict agent boundary enforcement."""
    # Hermes must never write code
    with pytest.raises(VaultBoundaryViolationError):
        enforce_agent_boundary("hermes", "src/engine/run_manager.py")

    with pytest.raises(VaultBoundaryViolationError):
        enforce_agent_boundary("knowledge", "web/src/App.tsx")

    # Hermes CAN touch markdown / JSON payloads
    enforce_agent_boundary("hermes", "context_payload.json")
    enforce_agent_boundary("hermes", "01_Dashboard/Activity.md")

    # OMP must never touch Obsidian vault notes
    with pytest.raises(VaultBoundaryViolationError):
        enforce_agent_boundary("omp", "pico-vault/40_Tasks/Task.md")

    with pytest.raises(VaultBoundaryViolationError):
        enforce_agent_boundary("coding_agent", "01_Dashboard/Activity.md")

    # OMP CAN touch code files
    enforce_agent_boundary("omp", "src/engine/run_manager.py")
    enforce_agent_boundary("coder", "tests/test_something.py")


def test_project_exclusion_bodyme():
    """Test F48: Strict exclusion of Body.me App."""
    assert is_project_excluded("Body.me App") is True
    assert is_project_excluded("body.me") is True
    assert is_project_excluded("bodyme") is True
    assert is_project_excluded("Dinner Service Optimizer") is False

    with pytest.raises(ProjectExclusionViolationError):
        enforce_project_inclusion("Body.me App")

    enforce_project_inclusion("Dinner Service Optimizer")


def test_obsidian_research_note_creation(fixture_vault):
    """Test automated creation and linking of new research notes in 50_Knowledge/."""
    indexer = ObsidianIndexer(fixture_vault)
    note_path = indexer.create_research_note(
        title="Swarm Drone Fleet Simulation",
        summary="Decentralized consensus and physics engine benchmark for autonomous micro-drones.",
        core_concepts=["Decentralized POMDP", "Centralized Training with Decentralized Execution (CTDE)"],
        architecture="ROS2 multi-node simulation with Ray RLLIB backend.",
        code_examples="def update_swarm_positions(): pass",
        tags=["research", "robotics", "swarm-drones"],
        related_links=["[[Knowledge Hub]]", "[[Multiagent RL]]"]
    )

    assert note_path.is_file()
    content = note_path.read_text(encoding="utf-8")
    assert "type: research" in content
    assert "status: evergreen" in content
    assert "Swarm Drone Fleet Simulation" in content
    assert "[[Knowledge Hub]]" in content
    assert "[[Multiagent RL]]" in content
    assert "Decentralized POMDP" in content
    assert "ROS2 multi-node simulation" in content


def test_obsidian_search_relevance_exclusion(fixture_vault):
    """Test that lifestyle/athletics notes and action verbs like 'run' are excluded from technical context searches."""
    # Create mock athletics note and technical note in fixture vault
    ath_dir = fixture_vault / "60_Inspiration" / "Athletics & Training"
    ath_dir.mkdir(parents=True, exist_ok=True)
    (ath_dir / "Running (findyourstridecoach).md").write_text("# Running\nRunning form and gait.", encoding="utf-8")

    tech_dir = fixture_vault / "50_Knowledge" / "Reinforcement Learning"
    tech_dir.mkdir(parents=True, exist_ok=True)
    (tech_dir / "Multiagent RL.md").write_text("# Multiagent RL\nSwarm coordination and drone simulation.", encoding="utf-8")

    indexer = ObsidianIndexer(fixture_vault)

    # Technical query containing verb 'run' must NOT return Running note
    hits = indexer.search_vault("run swarm drone fleet simulation")
    paths = [h["path"] for h in hits]
    assert not any("Running" in p for p in paths)
    assert any("Multiagent RL" in p for p in paths)
