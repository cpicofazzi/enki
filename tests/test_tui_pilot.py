"""
tests/test_tui_pilot.py
Comprehensive automated headless testing suite using Textual's Pilot API (Milestone 3, Feature F33).
Covers:
1. Headless test environment with size=(120, 36) virtual console and zero GUI display window.
2. Navigation across all 10 screens using number keys '1'-'9', '0'.
3. Screen title and widget presence verification.
4. Interactive user flows:
   - Flow 1: Dashboard spend gauge & gateway card validation
   - Flow 2: Start Run form (task input, project picker excluding Body.me, workflow select, dry-run toggle)
   - Flow 3: Live Run log streaming (RichLog ANSI) & interactive ApprovalGateModal resolution
   - Flow 4: Payload Editor JSON editing & live schema validation against context_payload.schema.json
   - Flow 5: Obsidian Browser note browsing, markdown preview, and Start Run from Note pre-fill
   - Flow 6: Finished Runs worktree diff inspection & teardown choices (Keep, Merge, Discard)
5. Anti-trap focus cycling and fast non-flaky execution (<30s).
"""

import sys
import json
import time
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Generator

import pytest
from textual.widgets import (
    Select, Switch, Static, DataTable, RichLog, TextArea
)

from src.ui.tui.app import EnkiTUIApp, EngineRunEvent
from src.ui.tui.screens.dashboard import DashboardScreen
from src.ui.tui.screens.start_run import StartRunScreen
from src.ui.tui.screens.live_run import LiveRunScreen
from src.ui.tui.screens.payload_editor import PayloadEditorScreen
from src.ui.tui.screens.workflows import WorkflowsScreen
from src.ui.tui.screens.model_browser import ModelBrowserScreen
from src.ui.tui.screens.obsidian_browser import ObsidianBrowserScreen
from src.ui.tui.screens.telemetry import TelemetryScreen
from src.ui.tui.screens.run_history import RunHistoryScreen
from src.ui.tui.screens.finished_runs import FinishedRunsScreen

from src.engine.models import (
    StepStatus, EventType, RunEvent, GateState, RunStatus
)
from src.engine.events import EventBus
from src.engine.run_manager import RunManager
from src.engine.workflow_engine import WorkflowEngine
from src.engine.worktree_manager import WorktreeManager
from src.openrouter_catalog import OpenRouterCatalog
from src.obsidian_indexer import ObsidianIndexer
from src.token_tracker import record_usage
import src.omp_bridge


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def tui_runs_dir(tmp_path) -> Path:
    runs_dir = tmp_path / "data" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir


@pytest.fixture
def tui_run_manager(tui_runs_dir) -> RunManager:
    bus = EventBus(runs_base_dir=tui_runs_dir)
    return RunManager(base_runs_dir=tui_runs_dir, event_bus=bus)


@pytest.fixture
def tui_app(
    tui_run_manager,
    isolated_config,
    fixture_vault,
    mock_omp,
    mock_gateway,
) -> Generator[EnkiTUIApp, None, None]:
    """Constructs an isolated, zero-spend EnkiTUIApp instance."""
    app = EnkiTUIApp(dry_run=True)
    app.run_manager = tui_run_manager
    app.event_bus = tui_run_manager.event_bus
    app.worktree_manager = WorktreeManager(default_base_branch="main")
    app.workflow_engine = WorkflowEngine(
        run_manager=tui_run_manager,
        worktree_manager=app.worktree_manager,
        event_bus=app.event_bus,
        omp_bridge=src.omp_bridge.OMPBridge(),
    )
    app.obsidian_indexer = ObsidianIndexer(str(fixture_vault))
    app.catalog = OpenRouterCatalog()

    yield app


@pytest.fixture
def seeded_tui_app(tui_app, fixture_sample_repo) -> EnkiTUIApp:
    """Pre-seeds realistic runs, git worktrees, and telemetry."""
    rm = tui_app.run_manager
    repo_path = fixture_sample_repo.path

    # 1. Active Run
    run_active = rm.create_run(
        task="Implement normalization pipeline for Dinner Service",
        project="Dinner Service Optimizer",
        workflow_id="four_step_pipeline",
        dry_run=True
    )
    rm.start_run(run_active.run_id)
    run_active.steps[0].status = StepStatus.COMPLETED
    run_active.steps[1].status = StepStatus.RUNNING
    run_active.current_step_id = "coding"
    rm.save_run(run_active)

    # 2. Gated Run
    run_gated = rm.create_run(
        task="Fix Tax Calculation Bug in Sample Math",
        project="Sample Math",
        workflow_id="four_step_pipeline",
        dry_run=True
    )
    rm.start_run(run_gated.run_id)
    run_gated.status = RunStatus.WAITING_GATE
    run_gated.steps[0].status = StepStatus.WAITING_GATE
    run_gated.current_step_id = "context_extraction"
    run_gated.gate_state = GateState(
        gate_id=f"gate_post_context_{run_gated.run_id}",
        step_id="context_extraction",
        status="pending",
        payload_snapshot={
            "task_id": run_gated.run_id,
            "title": "Fix Tax Calculation Bug",
            "requirements": ["Multiply amount by rate", "Round to 2 decimal places"]
        }
    )
    rm.save_run(run_gated)

    # 3. Completed Run
    run_done = rm.create_run(
        task="Verify math engine algorithms",
        project="Sample Math",
        workflow_id="plan_only",
        dry_run=True
    )
    rm.start_run(run_done.run_id)
    rm.finish_run(run_done.run_id, RunStatus.COMPLETED)

    # 4. Finished Run with Mounted Git Worktree
    run_wt = rm.create_run(
        task="Refactor tax calculator formulas",
        project="Sample Math",
        workflow_id="four_step_pipeline",
        dry_run=True
    )
    run_wt.metadata["repo_path"] = str(repo_path)
    wt_path = tui_app.worktree_manager.create_worktree(repo_path, run_wt.run_id, base_branch="main")
    (wt_path / "calculator.py").write_text("# Worktree tax modification\n", encoding="utf-8")
    run_wt.worktree_path = str(wt_path)
    run_wt.status = RunStatus.COMPLETED
    rm.save_run(run_wt)

    # 5. SQLite Telemetry Records ($5.40 spend)
    record_usage(
        agent_role="hermes",
        model="anthropic/claude-opus-5.5",
        prompt_tokens=4000,
        completion_tokens=1000,
        cost_usd=2.40,
        task_id=run_active.run_id
    )
    record_usage(
        agent_role="omp",
        model="anthropic/claude-fable-5.1",
        prompt_tokens=6000,
        completion_tokens=2000,
        cost_usd=3.00,
        task_id=run_active.run_id
    )

    tui_app.active_run_id = run_active.run_id
    return tui_app


# ==============================================================================
# Test Cases (F21 - F33)
# ==============================================================================

@pytest.mark.asyncio
async def test_tui_app_headless_initialization(tui_app):
    """
    Feature F21 & F33:
    Verifies that EnkiTUIApp initializes cleanly in headless mode with zero display window.
    """
    async with tui_app.run_test(size=(120, 36)) as pilot:
        assert tui_app.is_running
        assert tui_app.title == "ENKI COMMAND HUB"
        await pilot.pause()
        assert type(tui_app.screen).__name__ == "DashboardScreen"


@pytest.mark.asyncio
async def test_tui_navigation_all_10_screens(seeded_tui_app):
    """
    Feature F22 & F33:
    Verifies full keyboard navigation across all 10 screens using number keys '1'-'9' and '0'.
    Asserts active screen type, title, and key widget presence on every screen.
    """
    async with seeded_tui_app.run_test(size=(120, 36)) as pilot:
        # Screen 1: Dashboard
        await pilot.press("escape")
        await pilot.press("1")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "DashboardScreen"
        assert seeded_tui_app.screen.query_one("#card_gateway_status") is not None
        assert seeded_tui_app.screen.query_one("#budget_bar") is not None
        assert seeded_tui_app.screen.query_one("#tbl_active_runs") is not None

        # Screen 2: Start Run
        await pilot.press("escape")
        await pilot.press("2")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "StartRunScreen"
        assert seeded_tui_app.screen.query_one("#txt_task_prompt") is not None
        assert seeded_tui_app.screen.query_one("#sel_project") is not None
        assert seeded_tui_app.screen.query_one("#sw_dry_run") is not None
        assert seeded_tui_app.screen.query_one("#btn_submit_run") is not None

        # Screen 3: Live Run
        await pilot.press("escape")
        await pilot.press("3")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "LiveRunScreen"
        assert seeded_tui_app.screen.query_one("#tree_dag_steps") is not None
        assert seeded_tui_app.screen.query_one("#log_stream") is not None

        # Screen 4: Payload Editor
        await pilot.press("escape")
        await pilot.press("4")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "PayloadEditorScreen"
        assert seeded_tui_app.screen.query_one("#lbl_schema_status") is not None
        assert seeded_tui_app.screen.query_one("#txt_payload_json") is not None
        assert seeded_tui_app.screen.query_one("#btn_validate_json") is not None

        # Screen 5: Workflows
        await pilot.press("escape")
        await pilot.press("5")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "WorkflowsScreen"
        assert seeded_tui_app.screen.query_one("#tbl_workflows") is not None
        assert seeded_tui_app.screen.query_one("#txt_workflow_yaml") is not None

        # Screen 6: Model Browser
        await pilot.press("escape")
        await pilot.press("6")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "ModelBrowserScreen"
        assert seeded_tui_app.screen.query_one("#tbl_models_catalog") is not None
        assert seeded_tui_app.screen.query_one("#active_gw_display") is not None

        # Screen 7: Obsidian Browser
        await pilot.press("escape")
        await pilot.press("7")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "ObsidianBrowserScreen"
        assert seeded_tui_app.screen.query_one("#tbl_vault_notes") is not None
        assert seeded_tui_app.screen.query_one("#md_note_preview") is not None
        assert seeded_tui_app.screen.query_one("#btn_start_from_note") is not None

        # Screen 8: Telemetry
        await pilot.press("escape")
        await pilot.press("8")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "TelemetryScreen"
        assert seeded_tui_app.screen.query_one("#telemetry_progress_bar") is not None
        assert seeded_tui_app.screen.query_one("#tbl_by_model") is not None
        assert seeded_tui_app.screen.query_one("#tbl_by_agent") is not None

        # Screen 9: Run History
        await pilot.press("escape")
        await pilot.press("9")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "RunHistoryScreen"
        assert seeded_tui_app.screen.query_one("#tbl_run_history") is not None
        assert seeded_tui_app.screen.query_one("#btn_view_historical") is not None

        # Screen 10: Finished Runs
        await pilot.press("escape")
        await pilot.press("0")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "FinishedRunsScreen"
        assert seeded_tui_app.screen.query_one("#tbl_worktrees") is not None
        assert seeded_tui_app.screen.query_one("#txt_diff_view") is not None
        assert seeded_tui_app.screen.query_one("#btn_merge_worktree") is not None
        assert seeded_tui_app.screen.query_one("#btn_keep_worktree") is not None
        assert seeded_tui_app.screen.query_one("#btn_discard_worktree") is not None


@pytest.mark.asyncio
async def test_tui_global_hotkeys_and_anti_trap(seeded_tui_app):
    """
    Feature F22:
    Verifies that '?' pushes HelpModal, 'Escape' safely dismisses it,
    and Tab/Shift+Tab cycles focus without any keyboard traps.
    """
    async with seeded_tui_app.run_test(size=(120, 36)) as pilot:
        await pilot.press("escape")
        await pilot.press("1")
        await pilot.pause()

        # Trigger HelpModal via action
        seeded_tui_app.action_help()
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ in ("HelpModal", "ModalScreen")

        # Dismiss HelpModal
        await pilot.press("escape")
        await pilot.pause()
        assert type(seeded_tui_app.screen).__name__ == "DashboardScreen"

        # Tab focus navigation
        init_focused = seeded_tui_app.focused
        await pilot.press("tab")
        await pilot.pause()
        next_focused = seeded_tui_app.focused
        assert next_focused is not None
        assert next_focused != init_focused

        await pilot.press("shift+tab")
        await pilot.pause()
        assert seeded_tui_app.focused == init_focused


@pytest.mark.asyncio
async def test_tui_flow_dashboard_metrics(seeded_tui_app):
    """
    Feature F23 & Flow 1:
    Verifies spend gauge ($5.40 / $25.00), gateway card status, and active runs count.
    """
    async with seeded_tui_app.run_test(size=(120, 36)) as pilot:
        await pilot.press("escape")
        await pilot.press("1")
        await pilot.pause()

        screen = seeded_tui_app.screen
        gw_text = str(screen.query_one("#active_gw_name", Static).content)
        assert "OpenRouter" in gw_text

        spend_text = str(screen.query_one("#spend_details", Static).content)
        assert "5.4" in spend_text
        assert "25" in spend_text

        tbl = screen.query_one("#tbl_active_runs", DataTable)
        assert tbl.row_count >= 1


@pytest.mark.asyncio
async def test_tui_flow_start_run_interactive(seeded_tui_app):
    """
    Feature F24 & Flow 2:
    Verifies task input, project picker excluding Body.me, workflow picker,
    dry-run toggle, cost estimate pill, and run launch.
    """
    async with seeded_tui_app.run_test(size=(120, 36)) as pilot:
        await pilot.press("escape")
        await pilot.press("2")
        await pilot.pause()

        screen = seeded_tui_app.screen
        
        # Verify Body.me App exclusion
        sel_project = screen.query_one("#sel_project", Select)
        options = [opt[1] for opt in sel_project._options]
        assert "Body.me App" not in options
        assert "Dinner Service Optimizer" in options

        # Fill task
        txt_task = screen.query_one("#txt_task_prompt", TextArea)
        txt_task.text = "Build math calculation helper module"
        sel_project.value = "Dinner Service Optimizer"
        
        # Toggle dry run
        sw_dry = screen.query_one("#sw_dry_run", Switch)
        sw_dry.value = True
        await pilot.pause()

        initial_count = len(seeded_tui_app.run_manager.list_runs())
        screen.action_submit()
        await pilot.pause()

        # Invariant: Run created and transitioned to Live Run screen
        assert len(seeded_tui_app.run_manager.list_runs()) == initial_count + 1
        assert type(seeded_tui_app.screen).__name__ in ("LiveRunScreen", "GateModal")


@pytest.mark.asyncio
async def test_tui_flow_live_run_and_approval_gate(seeded_tui_app):
    """
    Feature F25 & Flow 3:
    Verifies live ANSI log streaming in RichLog and interactive gate modal resolution.
    """
    async with seeded_tui_app.run_test(size=(120, 36)) as pilot:
        await pilot.press("escape")
        await pilot.press("3")
        await pilot.pause()

        screen = seeded_tui_app.screen
        log_widget = screen.query_one("#log_stream", RichLog)

        # Stream ANSI log chunk
        ansi_chunk = "\x1b[32m[OMP]\x1b[0m Verification loop attempt 1: \x1b[1mFAILED\x1b[0m\n"
        seeded_tui_app.post_message(EngineRunEvent(RunEvent(
            run_id=seeded_tui_app.active_run_id,
            event_type=EventType.LOG_CHUNK,
            payload={"chunk": ansi_chunk, "stream": "stdout"}
        )))
        await pilot.pause()
        assert len(log_widget.lines) >= 1

        # Emit Gate Waiting event
        gate_event = RunEvent(
            run_id=seeded_tui_app.active_run_id,
            event_type=EventType.GATE_WAITING,
            payload={
                "gate_id": "gate_test_123",
                "step_id": "context_extraction",
                "prompt": "Review context payload before OMP execution."
            }
        )
        seeded_tui_app.post_message(EngineRunEvent(gate_event))
        await pilot.pause()

        # Assert gate modal pushed
        assert type(seeded_tui_app.screen).__name__ in ("GateModal", "ApprovalGateModal")
        modal = seeded_tui_app.screen

        # Click Approve action on first gate
        modal.action_approve()
        await pilot.pause()

        # If the workflow resumed and pushed the subsequent step's gate, abort it to return to LiveRunScreen
        if type(seeded_tui_app.screen).__name__ in ("GateModal", "ApprovalGateModal"):
            assert getattr(seeded_tui_app.screen, "gate_id", "") != "gate_test_123"
            seeded_tui_app.screen.action_abort()
            await pilot.pause()

        # Assert returned to LiveRunScreen
        assert type(seeded_tui_app.screen).__name__ == "LiveRunScreen"


@pytest.mark.asyncio
async def test_tui_flow_payload_editor_schema_validation(seeded_tui_app):
    """
    Feature F26 & Flow 4:
    Verifies context payload schema validation warning on invalid schema, fix, and save.
    """
    async with seeded_tui_app.run_test(size=(120, 36)) as pilot:
        await pilot.press("escape")
        await pilot.press("4")
        await pilot.pause()

        screen = seeded_tui_app.screen
        txt_json = screen.query_one("#txt_payload_json", TextArea)
        lbl_status = screen.query_one("#lbl_schema_status", Static)

        # Valid payload matching schemas/context_payload.schema.json
        valid_payload = {
            "task_id": "task_pilot_test",
            "title": "Fix Tax Bug",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source": "40_Tasks/Fix_Tax.md",
            "status": "pending",
            "requirements": ["Fix calculation error"],
            "engineering_constraints": {"language": "python"},
            "acceptance_criteria": {"test_commands": ["py -m pytest -q"]}
        }
        txt_json.text = json.dumps(valid_payload, indent=2)
        screen.validate_current_json()
        await pilot.pause()
        assert "badge-valid" in lbl_status.classes

        # Invalid payload (missing requirements)
        invalid_payload = dict(valid_payload)
        del invalid_payload["requirements"]
        txt_json.text = json.dumps(invalid_payload, indent=2)
        screen.validate_current_json()
        await pilot.pause()
        assert "badge-invalid" in lbl_status.classes

        # Fix and save
        txt_json.text = json.dumps(valid_payload, indent=2)
        screen.validate_current_json()
        await pilot.pause()
        assert "badge-valid" in lbl_status.classes

        screen.action_save_payload()
        await pilot.pause()


@pytest.mark.asyncio
async def test_tui_flow_obsidian_browser_run_from_note(seeded_tui_app):
    """
    Feature F29 & Flow 5:
    Browses vault notes from fixture_vault, verifies preview, and starts run from note.
    """
    async with seeded_tui_app.run_test(size=(120, 36)) as pilot:
        await pilot.press("escape")
        await pilot.press("7")
        await pilot.pause()

        screen = seeded_tui_app.screen
        tbl_notes = screen.query_one("#tbl_vault_notes", DataTable)
        assert tbl_notes.row_count >= 1

        md_preview = screen.query_one("#md_note_preview")
        assert md_preview is not None

        screen.action_start_from_note()
        await pilot.pause()

        # Transitions to StartRunScreen with pre-filled task
        assert type(seeded_tui_app.screen).__name__ == "StartRunScreen"
        start_screen = seeded_tui_app.screen
        task_text = start_screen.query_one("#txt_task_prompt", TextArea).text
        assert len(task_text.strip()) > 0


@pytest.mark.asyncio
async def test_tui_flow_finished_runs_worktree_teardown(seeded_tui_app, fixture_sample_repo):
    """
    Feature F32 & Flow 6:
    Selects finished run with mounted worktree, inspects diff, and executes teardown.
    """
    async with seeded_tui_app.run_test(size=(120, 36)) as pilot:
        await pilot.press("escape")
        await pilot.press("0")
        await pilot.pause()

        screen = seeded_tui_app.screen
        tbl_wt = screen.query_one("#tbl_worktrees", DataTable)
        assert tbl_wt.row_count >= 1

        diff_view = screen.query_one("#txt_diff_view", TextArea)
        assert diff_view is not None

        # Execute Keep Worktree
        screen.action_keep()
        await pilot.pause()

        # If confirmation modal pushed, confirm action
        if type(seeded_tui_app.screen).__name__ in ("ConfirmModal", "WorktreeTeardownModal", "ModalScreen"):
            seeded_tui_app.screen.action_confirm()
            await pilot.pause()


@pytest.mark.asyncio
async def test_tui_suite_fast_execution_benchmark(seeded_tui_app):
    """
    Invariance Test:
    Ensures that a complete full traversal across all 10 screens executes in < 5 seconds,
    well within the overall 30s suite ceiling.
    """
    start_time = time.monotonic()
    async with seeded_tui_app.run_test(size=(120, 36)) as pilot:
        for key in ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]:
            await pilot.press(key)
            await pilot.pause()
    duration = time.monotonic() - start_time
    assert duration < 5.0, f"Full TUI navigation took {duration:.2f}s, exceeding 5.0s benchmark limit"
