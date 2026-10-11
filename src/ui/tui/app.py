"""
src/ui/tui/app.py
EnkiTUIApp: Main application container for Enki Terminal UI.
Registers all 10 screens, global keybindings, EventBus pub/sub bridging, and background workers.
"""

from pathlib import Path
import logging
from typing import Optional, Dict, Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual import work
from textual.screen import ModalScreen

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

from src.ui.tui.modals.help_modal import HelpModal
from src.ui.tui.modals.gate_modal import GateModal, ApprovalGateModal
from src.ui.tui.modals.budget_modal import BudgetModal, BudgetStopModal
from src.ui.tui.modals.confirm_modal import ConfirmModal, WorktreeTeardownModal

from src.engine.models import RunEvent
from src.engine.events import get_event_bus
from src.engine.run_manager import RunManager
from src.engine.workflow_engine import WorkflowEngine
from src.engine.worktree_manager import WorktreeManager
from src.openrouter_catalog import OpenRouterCatalog
from src.obsidian_indexer import ObsidianIndexer
from src.config import load_config

logger = logging.getLogger(__name__)


class EngineRunEvent(Message):
    """Encapsulates an engine RunEvent for thread-safe Textual event dispatch."""

    def __init__(self, event: RunEvent) -> None:
        super().__init__()
        self.event = event


class EnkiTUIApp(App):
    """Enki Command Hub: Terminal UI for Hermes & Oh My Pi dual-agent orchestration."""

    TITLE = "ENKI COMMAND HUB"
    SUB_TITLE = "Dual-Agent Orchestration & Multi-Model Workflows"
    CSS_PATH = Path(__file__).parent / "styles" / "enki.tcss"

    SCREENS = {
        "dashboard": DashboardScreen,
        "start_run": StartRunScreen,
        "live_run": LiveRunScreen,
        "payload_editor": PayloadEditorScreen,
        "workflows": WorkflowsScreen,
        "model_browser": ModelBrowserScreen,
        "obsidian_browser": ObsidianBrowserScreen,
        "telemetry": TelemetryScreen,
        "run_history": RunHistoryScreen,
        "finished_runs": FinishedRunsScreen,
    }

    BINDINGS = [
        # Single-key Screen Navigation ('1' through '9', '0')
        Binding("1", "nav_screen('dashboard')", "Dashboard", show=True, priority=False),
        Binding("2", "nav_screen('start_run')", "Start", show=True, priority=False),
        Binding("3", "nav_screen('live_run')", "Live", show=True, priority=False),
        Binding("4", "nav_screen('payload_editor')", "Payload", show=True, priority=False),
        Binding("5", "nav_screen('workflows')", "Workflows", show=True, priority=False),
        Binding("6", "nav_screen('model_browser')", "Models", show=True, priority=False),
        Binding("7", "nav_screen('obsidian_browser')", "Vault", show=True, priority=False),
        Binding("8", "nav_screen('telemetry')", "Spend", show=True, priority=False),
        Binding("9", "nav_screen('run_history')", "History", show=True, priority=False),
        Binding("0", "nav_screen('finished_runs')", "Finished", show=True, priority=False),

        # Unconditional Priority Function Key Aliases (F1 to F10)
        Binding("f1", "force_nav('dashboard')", "F1:Dash", show=False, priority=True),
        Binding("f2", "force_nav('start_run')", "F2:Start", show=False, priority=True),
        Binding("f3", "force_nav('live_run')", "F3:Live", show=False, priority=True),
        Binding("f4", "force_nav('payload_editor')", "F4:Payload", show=False, priority=True),
        Binding("f5", "force_nav('workflows')", "F5:Workflows", show=False, priority=True),
        Binding("f6", "force_nav('model_browser')", "F6:Models", show=False, priority=True),
        Binding("f7", "force_nav('obsidian_browser')", "F7:Vault", show=False, priority=True),
        Binding("f8", "force_nav('telemetry')", "F8:Spend", show=False, priority=True),
        Binding("f9", "force_nav('run_history')", "F9:History", show=False, priority=True),
        Binding("f10", "force_nav('finished_runs')", "F10:Finished", show=False, priority=True),

        # Global Control & Anti-Trap
        Binding("escape", "handle_escape", "Escape/Blur", show=True, priority=True),
        Binding("question_mark", "help", "Help (?)", show=True, priority=False),
        Binding("q", "quit_app", "Quit", show=True, priority=False),
        Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
    ]

    def __init__(self, dry_run: bool = False, initial_workflow: str = "four_step_pipeline", **kwargs):
        super().__init__(**kwargs)
        self.default_dry_run = dry_run
        self.initial_workflow = initial_workflow

        # Core Engine Singletons
        self.event_bus = get_event_bus()
        self.run_manager = RunManager(event_bus=self.event_bus)
        self.worktree_manager = WorktreeManager()
        self.workflow_engine = WorkflowEngine(
            run_manager=self.run_manager,
            worktree_manager=self.worktree_manager,
            event_bus=self.event_bus
        )
        self.catalog = OpenRouterCatalog()
        self.obsidian_indexer = ObsidianIndexer()
        self.config = load_config()

        # Cross-Screen Shared State
        self.active_run_id: Optional[str] = None
        self.prefill_task: Optional[str] = None
        self.prefill_project: Optional[str] = None
        self.prefill_workflow: Optional[str] = initial_workflow
        self.editing_payload_run_id: Optional[str] = None
        self.editing_payload_gate_id: Optional[str] = None
        self.editing_payload_data: Optional[Dict[str, Any]] = None

    def on_mount(self) -> None:
        """Pushes initial screen on mount (base of the navigable stack)."""
        self.push_screen("dashboard")

    def action_nav_screen(self, screen_name: str) -> None:
        """Navigates to the specified screen."""
        if screen_name in self.SCREENS:
            self._close_modals()
            self.switch_screen(screen_name)

    def action_force_nav(self, screen_name: str) -> None:
        """Unconditionally navigates to the specified screen, bypassing focus."""
        if screen_name in self.SCREENS:
            self._close_modals()
            self.switch_screen(screen_name)

    def _close_modals(self) -> None:
        """Pops any modal overlays so screen switching targets the base screen."""
        while isinstance(self.screen, ModalScreen) and len(self.screen_stack) > 2:
            self.pop_screen()

    def action_help(self) -> None:
        """Pushes HelpModal dialog overlay."""
        if not isinstance(self.screen, HelpModal):
            self.push_screen(HelpModal())

    def action_handle_escape(self) -> None:
        """Anti-trap escape handler: dismisses active modal or blurs current focused widget.

        If the active screen declares its own ``escape`` binding (e.g. a modal whose
        escape means "abort"/"pause"), that action is run so result callbacks fire.
        """
        screen = self.screen
        for binding in getattr(screen, "BINDINGS", []):
            key = binding.key if isinstance(binding, Binding) else binding[0]
            action = binding.action if isinstance(binding, Binding) else binding[1]
            if key == "escape":
                handler = getattr(screen, f"action_{action}", None)
                if handler is not None:
                    handler()
                    return
        if isinstance(screen, ModalScreen):
            self.pop_screen()
        else:
            screen.set_focus(None)

    def action_quit_app(self) -> None:
        """Exits the application cleanly."""
        self.exit()

    def view_run(self, run_id: str) -> None:
        """Sets active run and switches immediately to LiveRunScreen."""
        self.active_run_id = run_id
        self.switch_screen("live_run")

    def on_engine_run_event(self, message: EngineRunEvent) -> None:
        """Delivers engine events down to active screen or LiveRunScreen."""
        if hasattr(self.screen, "on_engine_run_event"):
            self.screen.on_engine_run_event(message)
        elif self.is_screen_installed("live_run"):
            live = self.get_screen("live_run")
            if live.is_mounted:
                live.on_engine_run_event(message)

    @work(thread=True, name="tui_workflow_executor", group="engine_runs", exit_on_error=False)
    def dispatch_workflow_run(self, run_id: str, dry_run: bool = False) -> None:
        """Executes a workflow DAG in a background worker thread."""
        try:
            self.workflow_engine.execute_dag(
                run_id=run_id,
                dry_run=dry_run,
                raise_on_gate=False
            )
        except Exception as e:
            logger.info(f"Workflow execution paused or stopped for {run_id}: {e}")

    def resume_run_after_resolution(self, run_id: str) -> bool:
        """Re-dispatches a run's DAG after a gate/budget decision unblocked it.

        ``execute_dag`` returns (rather than blocks) when it hits a gate, so the
        TUI must restart execution once the user resolves it. Returns True if a
        resume was dispatched.
        """
        from src.engine.models import RunStatus
        try:
            run = self.run_manager.load_run(run_id)
        except Exception:
            return False
        if run.status != RunStatus.RUNNING:
            return False
        self.dispatch_workflow_run(run_id, dry_run=run.dry_run)
        return True
