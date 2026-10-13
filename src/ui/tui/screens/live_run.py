"""
src/ui/tui/screens/live_run.py
Screen 3: LiveRunScreen (Feature F25)
Real-time execution dashboard with DAG step tree, RichLog ANSI log streaming,
and modal gate / budget overlays.
"""

from typing import Optional, Dict, Any, List
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Label, Button, Static, RichLog
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding
from rich.ansi import AnsiDecoder

from src.ui.tui.widgets.header_bar import HeaderBar
from src.ui.tui.widgets.step_tree import StepTree
from src.ui.tui.modals.gate_modal import GateModal
from src.ui.tui.modals.budget_modal import BudgetModal
from src.ui.tui.modals.subagent_flow_modal import SubagentFlowModal
from src.engine.models import (
    Run, RunEvent, EventType, StepStatus, RunStatus, GateAction, BudgetDecision
)


class LiveRunScreen(Screen):
    """Screen 3: Real-time execution monitor for active or replayed runs."""

    BINDINGS = [
        Binding("escape", "back", "Back", priority=False),
        Binding("f", "view_subagents_flow", "Subagent Flow", priority=False),
        Binding("a", "quick_approve", "Approve Gate", priority=False),
        Binding("e", "quick_edit", "Edit Payload", priority=False),
        Binding("r", "quick_reject", "Reject Gate", priority=False),
        Binding("x", "quick_abort", "Abort Run", priority=False),
        Binding("c", "clear_log", "Clear Log", priority=False),
    ]

    def __init__(self, run_id: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.explicit_run_id = run_id
        self._ansi_decoder = AnsiDecoder()
        self._seen_event_ids = set()
        self._bus_subscribed = False
        self._subscribed_run_id: Optional[str] = None
        self._loaded_run_id: Optional[str] = None
        self._last_suggested_model: str = "z-ai/glm-5.3-flash"

    @property
    def current_run_id(self) -> str:
        if self.explicit_run_id:
            return self.explicit_run_id
        if hasattr(self.app, "active_run_id") and self.app.active_run_id:
            return self.app.active_run_id
        return ""

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="screen_live_run"):
            with Horizontal(id="run_meta_banner", classes="card"):
                yield Static("Run: None", id="lbl_live_run_id")
                yield Static("Task: No task active", id="lbl_live_run_task")
                yield Static("[PENDING]", id="lbl_live_run_status")
                yield Static("Spend: $0.0000", id="lbl_live_run_cost")
                yield Static("Tokens: 0", id="lbl_live_run_time")

            with Horizontal(id="live_split_container", classes="split-container"):
                with Vertical(id="left_dag_pane", classes="pane-35 pane-container"):
                    yield Label("DAG WORKFLOW STEPS", classes="section-title")
                    yield StepTree(id="tree_dag_steps")
                    with Container(id="step_details_card", classes="card"):
                        yield Static("Step Details", id="step_info_title")
                        yield Static("Model: -", id="step_info_model")
                        yield Static("Attempts: 0", id="step_info_attempts")

                with Vertical(id="right_log_pane", classes="pane-65 pane-container"):
                    with Horizontal(id="log_pane_header"):
                        yield Label("TERMINAL OUTPUT STREAM (ANSI)", classes="section-title")
                        yield Button("Clear Log [C]", id="btn_clear_log")
                    yield RichLog(
                        id="log_stream",
                        highlight=False,
                        markup=False,
                        auto_scroll=True,
                        max_lines=10000,
                        wrap=True
                    )

            with Horizontal(id="live_footer_actions", classes="action-bar"):
                yield Button("Back [Esc]", variant="default", id="btn_back_live")
                yield Button("Subagent Flow [F]", variant="primary", id="btn_view_flow")
                yield Button("Approve Gate [A]", variant="success", id="btn_quick_approve")
                yield Button("Edit Payload [E]", variant="default", id="btn_quick_edit")
                yield Button("Reject [R]", variant="warning", id="btn_quick_reject")
                yield Button("Abort Run [X]", variant="error", id="btn_quick_abort")
                yield Button("Delete Run", variant="error", id="btn_delete_run")

    def on_mount(self) -> None:
        self.bind_to_current_run()

    def on_screen_resume(self) -> None:
        """Named screens are cached; rebind if the active run changed while away."""
        if self.current_run_id != self._loaded_run_id:
            self.bind_to_current_run()
        else:
            self.refresh_run_state()

    def on_unmount(self) -> None:
        self.unsubscribe_events()

    def bind_to_current_run(self) -> None:
        """Resets the view and attaches to the current run (state, history, live events)."""
        self.unsubscribe_events()
        self._seen_event_ids.clear()
        try:
            self.query_one("#log_stream", RichLog).clear()
        except Exception:
            pass
        self._loaded_run_id = self.current_run_id
        self.load_run_state()
        self.subscribe_events()
        self.maybe_prompt_pending_gate()

    def refresh_run_state(self) -> None:
        """Reloads banner + DAG tree from persisted run state."""
        run_id = self.current_run_id
        rm = getattr(self.app, "run_manager", None)
        if not rm or not run_id:
            return
        try:
            run = rm.load_run(run_id)
            self.update_meta_banner(run)
            self.query_one("#tree_dag_steps", StepTree).update_steps(run.steps, run.current_step_id)
        except Exception:
            pass

    def load_run_state(self) -> None:
        """Loads run state and streams historical events into RichLog."""
        run_id = self.current_run_id
        if not run_id:
            return

        self.refresh_run_state()

        # Load historical events (replayed without re-opening resolved gate/budget modals)
        eb = getattr(self.app, "event_bus", None)
        if eb:
            try:
                events = eb.get_events(run_id)
                for ev in events:
                    if ev.event_id not in self._seen_event_ids:
                        self._seen_event_ids.add(ev.event_id)
                        self.process_engine_event(ev, replay=True)
            except Exception:
                pass

    def maybe_prompt_pending_gate(self) -> None:
        """Opens the gate modal if the bound run is currently paused at a pending gate."""
        rm = getattr(self.app, "run_manager", None)
        run_id = self.current_run_id
        if not rm or not run_id:
            return
        try:
            run = rm.load_run(run_id)
        except Exception:
            return
        if run.status == RunStatus.WAITING_GATE and run.gate_state and run.gate_state.status == "pending":
            self.open_gate_modal(
                gate_id=run.gate_state.gate_id,
                step_id=run.gate_state.step_id,
                prompt="Run is paused at an approval gate.",
                payload=run.gate_state.payload_snapshot,
            )

    def open_gate_modal(self, gate_id: str, step_id: str, prompt: str, payload: Optional[Dict[str, Any]]) -> None:
        if isinstance(self.app.screen, GateModal):
            return  # never stack duplicate gate dialogs
        self.app.push_screen(
            GateModal(
                run_id=self.current_run_id,
                gate_id=gate_id,
                step_id=step_id,
                prompt=prompt,
                payload=payload
            ),
            callback=self.on_gate_modal_resolved
        )

    def subscribe_events(self) -> None:
        run_id = self.current_run_id
        eb = getattr(self.app, "event_bus", None)
        if eb and run_id and not self._bus_subscribed:
            eb.subscribe(run_id, self._on_bus_event)
            self._bus_subscribed = True
            self._subscribed_run_id = run_id

    def unsubscribe_events(self) -> None:
        eb = getattr(self.app, "event_bus", None)
        if eb and self._subscribed_run_id and self._bus_subscribed:
            try:
                eb.unsubscribe(self._subscribed_run_id, self._on_bus_event)
            except Exception:
                pass
        self._bus_subscribed = False
        self._subscribed_run_id = None

    def _on_bus_event(self, event: RunEvent) -> None:
        """Invoked from EventBus worker threads. Posts message to Textual event loop."""
        from src.ui.tui.app import EngineRunEvent
        try:
            self.app.post_message(EngineRunEvent(event))
        except Exception:
            pass

    def on_engine_run_event(self, event_msg) -> None:
        """Handles EngineRunEvent posted via Textual message loop."""
        ev = event_msg.event
        if ev.event_id in self._seen_event_ids:
            return
        self._seen_event_ids.add(ev.event_id)
        self.process_engine_event(ev)

    def process_engine_event(self, ev: RunEvent, replay: bool = False) -> None:
        """Routes typed engine events to UI components."""
        # Check if event belongs to current run
        if ev.run_id != self.current_run_id and self.current_run_id != "":
            return

        if ev.event_type == EventType.LOG_CHUNK:
            chunk = ev.payload.get("chunk", "")
            stream_type = ev.payload.get("stream", "stdout")
            log_widget = self.query_one("#log_stream", RichLog)
            for line in self._ansi_decoder.decode(chunk):
                if stream_type == "stderr" and not line.style:
                    line.stylize("bold red")
                log_widget.write(line)

        elif ev.event_type in (EventType.STEP_STARTED, EventType.STEP_COMPLETED, EventType.STEP_FAILED, EventType.STEP_PROGRESS):
            rm = getattr(self.app, "run_manager", None)
            if rm:
                try:
                    run = rm.load_run(self.current_run_id)
                    self.update_meta_banner(run)
                    tree = self.query_one("#tree_dag_steps", StepTree)
                    tree.update_steps(run.steps, run.current_step_id)
                except Exception:
                    pass

        elif ev.event_type == EventType.GATE_WAITING:
            if replay:
                return  # pending gates are re-prompted from persisted state instead
            gate_id = ev.payload.get("gate_id", f"gate_{self.current_run_id}")
            step_id = ev.payload.get("step_id", "context_extraction")
            prompt = ev.payload.get("prompt", "Review context payload before proceeding.")
            payload = ev.payload.get("payload")
            self.open_gate_modal(gate_id=gate_id, step_id=step_id, prompt=prompt, payload=payload)

        elif ev.event_type == EventType.BUDGET_STOP:
            if replay:
                return
            current_spend = ev.payload.get("current_spend_usd", 25.0)
            budget_limit = ev.payload.get("budget_limit_usd", 25.0)
            suggested = ev.payload.get("suggested_cheaper_model", "z-ai/glm-5.3-flash")
            self._last_suggested_model = suggested or self._last_suggested_model
            reason = ev.payload.get("reason", "Budget limit reached")
            self.app.push_screen(
                BudgetModal(
                    run_id=self.current_run_id,
                    current_spend_usd=current_spend,
                    budget_limit_usd=budget_limit,
                    suggested_cheaper_model=suggested,
                    suggested_reason=reason
                ),
                callback=self.on_budget_modal_resolved
            )

        elif ev.event_type in (EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.TELEMETRY_UPDATED):
            rm = getattr(self.app, "run_manager", None)
            if rm:
                try:
                    run = rm.load_run(self.current_run_id)
                    self.update_meta_banner(run)
                except Exception:
                    pass

    def update_meta_banner(self, run: Run) -> None:
        """Updates top metadata banner."""
        self.query_one("#lbl_live_run_id", Static).update(f"Run: {run.run_id}")
        self.query_one("#lbl_live_run_task", Static).update(
            f"Task: {(run.task[:32] + '...') if len(run.task) > 32 else run.task}"
        )
        status_styled = f"[{run.status.value.upper()}]"
        self.query_one("#lbl_live_run_status", Static).update(status_styled)
        self.query_one("#lbl_live_run_cost", Static).update(f"Spend: ${run.telemetry.total_cost_usd:.4f}")
        self.query_one("#lbl_live_run_time", Static).update(f"Tokens: {run.telemetry.total_tokens:,}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_view_flow":
            self.action_view_subagents_flow()
        elif btn_id == "btn_quick_approve":
            self.action_quick_approve()
        elif btn_id == "btn_quick_edit":
            self.action_quick_edit()
        elif btn_id == "btn_quick_reject":
            self.action_quick_reject()
        elif btn_id == "btn_quick_abort":
            self.action_quick_abort()
        elif btn_id == "btn_delete_run":
            self.action_delete_run()
        elif btn_id == "btn_clear_log":
            self.action_clear_log()
        elif btn_id == "btn_back_live":
            self.action_back()

    def action_back(self) -> None:
        self.app.action_back()

    def action_view_subagents_flow(self) -> None:
        if self.current_run_id:
            self.app.push_screen(SubagentFlowModal(self.current_run_id))

    def _pending_gate_id(self) -> Optional[str]:
        """Returns the gate id if the bound run is currently waiting at a gate."""
        rm = getattr(self.app, "run_manager", None)
        if not rm or not self.current_run_id:
            return None
        try:
            run = rm.load_run(self.current_run_id)
        except Exception:
            return None
        if run.status != RunStatus.WAITING_GATE:
            return None
        return run.gate_state.gate_id if run.gate_state else f"gate_quick_{self.current_run_id}"

    def _resolve_and_resume(self, gate_id: str, action: str, payload=None, feedback=None) -> None:
        rm = getattr(self.app, "run_manager", None)
        if not rm or not self.current_run_id:
            return
        try:
            rm.resolve_gate(
                run_id=self.current_run_id,
                gate_id=gate_id,
                action=action,
                payload=payload,
                feedback=feedback
            )
        except Exception:
            return
        self.refresh_run_state()
        if action != GateAction.ABORT.value and hasattr(self.app, "resume_run_after_resolution"):
            self.app.resume_run_after_resolution(self.current_run_id)

    def action_quick_approve(self) -> None:
        gate_id = self._pending_gate_id()
        if gate_id:
            self._resolve_and_resume(gate_id, GateAction.APPROVE.value)

    def action_quick_edit(self) -> None:
        self.app.switch_screen("payload_editor")

    def action_quick_reject(self) -> None:
        gate_id = self._pending_gate_id()
        if gate_id:
            self._resolve_and_resume(gate_id, GateAction.REJECT.value, feedback="User manual rejection")

    def action_quick_abort(self) -> None:
        rm = getattr(self.app, "run_manager", None)
        if not rm or not self.current_run_id:
            return
        try:
            run = rm.load_run(self.current_run_id)
        except Exception:
            return
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ABORTED):
            return
        gate_id = run.gate_state.gate_id if run.gate_state else f"gate_quick_{self.current_run_id}"
        self._resolve_and_resume(gate_id, GateAction.ABORT.value)

    def action_delete_run(self) -> None:
        run_id = self.current_run_id
        if not run_id:
            self.notify("No active run to delete.", severity="warning")
            return

        def _do_delete(res) -> None:
            if res and res.get("confirmed"):
                rm = getattr(self.app, "run_manager", None)
                if rm:
                    if rm.delete_run(run_id):
                        self.notify(f"Run {run_id} permanently deleted.", severity="information")
                        self.app.active_run_id = None
                        self.app.switch_screen("dashboard")
                    else:
                        self.notify(f"Failed to delete {run_id}.", severity="error")

        from src.ui.tui.modals.confirm_modal import ConfirmModal
        modal = ConfirmModal(
            title="Permanently Delete Run",
            message=f"Are you sure you want to delete run '{run_id}'?\nThis removes all state files and git worktrees.",
            action="delete",
            run_id=run_id
        )
        self.app.push_screen(modal, callback=_do_delete)

    def action_clear_log(self) -> None:
        self.query_one("#log_stream", RichLog).clear()

    def on_gate_modal_resolved(self, result: Optional[Dict[str, Any]]) -> None:
        """Callback when GateModal dismisses."""
        if not result:
            return
        action = result.get("action")
        gate_id = result.get("gate_id", "")
        feedback = result.get("feedback")
        payload = result.get("payload")

        if action == "edit_and_approve":
            self.app.editing_payload_data = payload
            self.app.editing_payload_gate_id = gate_id
            self.app.switch_screen("payload_editor")
            return

        self._resolve_and_resume(gate_id, action, payload=payload, feedback=feedback)

    def on_budget_modal_resolved(self, decision: Optional[BudgetDecision]) -> None:
        """Callback when BudgetModal dismisses."""
        if not decision:
            return
        rm = getattr(self.app, "run_manager", None)
        if rm and self.current_run_id:
            try:
                cheaper = self._last_suggested_model if decision == BudgetDecision.SWITCH_CHEAPER else None
                rm.resolve_budget(self.current_run_id, decision, cheaper_model=cheaper)
            except Exception:
                return
            self.refresh_run_state()
            if decision != BudgetDecision.PAUSE and hasattr(self.app, "resume_run_after_resolution"):
                self.app.resume_run_after_resolution(self.current_run_id)
