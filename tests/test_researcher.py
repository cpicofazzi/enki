"""
tests/test_researcher.py
Automated tests for Local Research and Find Web Research capabilities.
- Test synthesize_web_research payload structure
- Test execute_find_research_and_create_note writes note conforming to Template - Research.md
- Test local_research=False skips vault indexing
- Test find_research=True incorporates web research into context payload and creates vault note
"""

import os
import json
import pytest
from pathlib import Path

from src.engine.models import Run, RunStatus
from src.engine.run_manager import RunManager
from src.engine.researcher import (
    synthesize_web_research,
    execute_find_research_and_create_note
)
from src.engine.workflow_engine import WorkflowEngine, StepExecutionContext
from src.obsidian_indexer import ObsidianIndexer


def test_synthesize_web_research_dry_run():
    """Verify web research synthesis produces structured technical research payload."""
    data = synthesize_web_research("Swarm Drone Fleet Simulation", dry_run=True)
    assert "title" in data
    assert "summary" in data
    assert "core_concepts" in data
    assert "architecture" in data
    assert "code_examples" in data
    assert "open_questions" in data
    assert "references" in data
    assert len(data["core_concepts"]) > 0
    assert "[[Knowledge Hub]]" in data["references"]


def test_execute_find_research_and_create_note(fixture_vault):
    """Verify executing find research writes note to 50_Knowledge/Research Notes/."""
    result = execute_find_research_and_create_note(
        topic="Swarm Drone Fleet Simulation",
        vault_path=fixture_vault,
        dry_run=True,
        task_id="test_run_research"
    )

    note_path = Path(result["note_path"])
    assert note_path.is_file()
    assert "50_Knowledge/Research Notes" in result["vault_relative_path"]

    content = note_path.read_text(encoding="utf-8")
    assert "type: research" in content
    assert "status: evergreen" in content
    assert "Swarm Drone Fleet Simulation" in content
    assert "[[Knowledge Hub]]" in content
    assert "Executive Summary" in content
    assert "Practical Implementation & Code Examples" in content


def test_workflow_engine_with_find_research(fixture_vault, mock_gateway):
    """Verify WorkflowEngine executes find_research, creating vault note and updating payload."""
    rm = RunManager()
    run = rm.create_run(
        task="Autonomous Swarm Drone Coordination",
        project="General",
        workflow_id="four_step_pipeline",
        dry_run=True,
        local_research=True,
        find_research=True
    )

    engine = WorkflowEngine(run_manager=rm, gateway_client=mock_gateway)
    context = StepExecutionContext(run=run, runs_base_dir=rm.base_runs_dir)

    step_def = {"id": "context_extraction", "type": "context_extraction", "name": "Context Extraction"}
    output = engine._execute_context_extraction(run, step_def, context)

    payload = output["payload"]
    assert "context_sources" in payload
    assert any("Find Web Research" in str(s.get("source", "")) for s in payload["context_sources"])
    assert output.get("web_research_note") is not None

    # Check note was created in vault
    created_note = fixture_vault / "50_Knowledge" / "Research Notes" / output["web_research_note"]
    assert created_note.is_file()


def test_workflow_engine_local_research_toggle_off(fixture_vault, mock_gateway):
    """Verify local_research=False bypasses vault note searching."""
    # Put a note in vault
    note = fixture_vault / "50_Knowledge" / "Reinforcement Learning" / "Multiagent RL.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Multiagent RL\nSwarm coordination.", encoding="utf-8")

    rm = RunManager()
    run = rm.create_run(
        task="Multiagent RL Swarm",
        project="General",
        workflow_id="four_step_pipeline",
        dry_run=True,
        local_research=False,  # Toggle OFF
        find_research=False
    )

    engine = WorkflowEngine(run_manager=rm, gateway_client=mock_gateway)
    context = StepExecutionContext(run=run, runs_base_dir=rm.base_runs_dir)

    step_def = {"id": "context_extraction", "type": "context_extraction", "name": "Context Extraction"}
    output = engine._execute_context_extraction(run, step_def, context)

    payload = output["payload"]
    # Since local_research is False and find_research is False, context_sources must be empty
    assert len(payload.get("context_sources", [])) == 0
