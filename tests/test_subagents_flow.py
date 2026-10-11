"""
tests/test_subagents_flow.py
Unit tests verifying subagent flow extraction, note tracking, and code diff analysis.
"""

from pathlib import Path
import pytest

from src.engine.models import Run, StepState, StepStatus, RunStatus, RoutingDecision
from src.engine.subagents_flow import extract_subagents_flow
from src.engine.run_manager import RunManager


def test_extract_subagents_flow_structure(tmp_path):
    """Verifies that extract_subagents_flow returns correct stages and maps subagents properly."""
    run = Run(
        run_id="run_test_flow_01",
        task="Implement vector similarity search in SQLite",
        project="General",
        workflow_id="four_step_pipeline",
        status=RunStatus.COMPLETED,
        dry_run=True,
        branch_name="enki/run/run_test_flow_01",
        worktree_path=str(tmp_path / ".worktrees" / "run_test_flow_01"),
        steps=[
            StepState(
                step_id="context_extraction",
                step_type="context_extraction",
                name="Hermes Context Extraction",
                status=StepStatus.COMPLETED,
                model="deepseek/deepseek-r1",
                started_at="2026-10-11T10:00:00+00:00",
                completed_at="2026-10-11T10:00:02+00:00",
                output={"payload": {"requirements": ["Req 1", "Req 2"], "context_sources": []}}
            ),
            StepState(
                step_id="coding",
                step_type="coding",
                name="OMP Coding Handshake",
                status=StepStatus.COMPLETED,
                model="z-ai/glm-5.3-flash",
                started_at="2026-10-11T10:00:02+00:00",
                completed_at="2026-10-11T10:00:06+00:00",
                output={"exit_code": 0, "status": "completed"}
            ),
            StepState(
                step_id="verification",
                step_type="verification",
                name="OMP Test Verification Loop",
                status=StepStatus.COMPLETED,
                model="z-ai/glm-5.3-flash",
                started_at="2026-10-11T10:00:06+00:00",
                completed_at="2026-10-11T10:00:10+00:00",
                output={"passed": True, "results": [{"command": "py -m pytest -q", "passed": True, "exit_code": 0}]}
            ),
            StepState(
                step_id="sync",
                step_type="sync",
                name="Hermes Vault Sync",
                status=StepStatus.COMPLETED,
                model="deepseek/deepseek-r1",
                started_at="2026-10-11T10:00:10+00:00",
                completed_at="2026-10-11T10:00:11+00:00",
                output={"synced": True, "vault_entry": "01_Dashboard/Enki_Activity_Log.md"}
            ),
        ]
    )

    flow = extract_subagents_flow(run, root_dir=tmp_path)

    # 1. Check top-level fields
    assert flow["run_id"] == "run_test_flow_01"
    assert flow["status"] == "completed"
    assert flow["branch_name"] == "enki/run/run_test_flow_01"

    # 2. Check subagent stages
    stages = flow["subagents_flow"]
    assert len(stages) == 4

    # Stage 1: Hermes
    assert stages[0]["subagent_id"] == "hermes"
    assert stages[0]["subagent_name"] == "Hermes"
    assert stages[0]["status"] == "completed"
    assert stages[0]["duration_seconds"] == 2.0
    assert "Extracted 2 requirements" in stages[0]["artifacts_summary"]

    # Stage 2: OMP Coding
    assert stages[1]["subagent_id"] == "omp"
    assert stages[1]["subagent_name"] == "Oh My Pi (OMP)"
    assert stages[1]["status"] == "completed"
    assert stages[1]["duration_seconds"] == 4.0

    # Stage 3: OMP Verification
    assert stages[2]["subagent_id"] == "omp"
    assert stages[2]["subagent_name"] == "Oh My Pi (OMP)"
    assert stages[2]["status"] == "completed"
    assert "acceptance tests passed" in stages[2]["artifacts_summary"]

    # Stage 4: Hermes Sync
    assert stages[3]["subagent_id"] == "hermes"
    assert stages[3]["subagent_name"] == "Hermes"
    assert stages[3]["status"] == "completed"

    # 3. Check Notes Processed
    notes_info = flow["processed_notes"]
    assert notes_info["boundary_enforced"] is True
    assert "Hermes" in notes_info["boundary_rule"]
    assert len(notes_info["notes_written"]) >= 1
    assert notes_info["notes_written"][0]["path"] == "01_Dashboard/Enki_Activity_Log.md"

    # 4. Check Code Processed
    code_info = flow["processed_code"]
    assert code_info["branch_name"] == "enki/run/run_test_flow_01"
    assert code_info["verification"]["passed"] is True
    assert code_info["verification"]["status"] == "PASSED"


def test_subagents_flow_with_reviewer_step(tmp_path):
    """Verifies that an AI reviewer step is mapped to the Reviewer subagent."""
    run = Run(
        run_id="run_review_flow_02",
        task="Refactor async lock with AI code review",
        workflow_id="feature_and_reviewer",
        steps=[
            StepState(
                step_id="review",
                step_type="review",
                name="AI Architectural Review",
                status=StepStatus.COMPLETED,
                model="anthropic/claude-opus-5.5",
                output={"decision": "approved", "score": 92}
            )
        ]
    )

    flow = extract_subagents_flow(run, root_dir=tmp_path)
    stages = flow["subagents_flow"]
    assert len(stages) == 1
    assert stages[0]["subagent_id"] == "reviewer"
    assert stages[0]["subagent_name"] == "AI Reviewer"
    assert stages[0]["subagent_role"] == "Architectural Evaluator"
    assert "APPROVED" in stages[0]["artifacts_summary"]
    assert "92/100" in stages[0]["artifacts_summary"]
