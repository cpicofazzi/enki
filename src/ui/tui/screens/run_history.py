"""
src/ui/tui/screens/run_history.py
Screen 9: RunHistoryScreen (Feature F31)
Historical run browser from data/runs/, replay, resuming failed steps, and git diff inspector.
"""

from typing import Optional
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Label, Static, DataTable, Button
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding

from src.ui.tui.widgets.header_bar import HeaderBar
from src.ui.tui.modals.subagent_flow_modal import SubagentFlowModal
from src.engine.models import RunStatus
from src.engine.subagents_flow import extract_subagents_flow


class RunHistoryScreen(Screen):
    """Screen 9: Run History, replay, and resume failed steps."""

    BINDINGS = [
        Binding("escape", "back", "Back", priority=False),
        Binding("f", "view_subagents_flow", "Subagent Flow", priority=False),
        Binding("v", "view_historical", "View Live", priority=False),
        Binding("p", "replay_run", "Replay", priority=False),
        Binding("r", "resume_failed", "Resume Failed", priority=False),
        Binding("d", "history_diff", "View Diff", priority=False),
        Binding("x", "delete_run", "Delete Run", priority=False),
        Binding("u", "refresh_history", "Refresh", priority=False),
    ]

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="screen_run_history"):
            with Container(classes="card"):
                yield Label("HISTORICAL RUNS (data/runs/<run_id>/run_state.json)", classes="section-title")
                yield DataTable(id="tbl_run_history")

            with Container(id="selected_run_card", classes="card"):
                yield Label("SELECTED RUN DETAILS", classes="section-title")
                yield Static("Select a run above to view execution details.", id="lbl_history_details")

            with Horizontal(id="history_action_bar", classes="action-bar"):
                yield Button("Back [Esc]", variant="default", id="btn_back_history")
                yield Button("Flow [F]", variant="primary", id="btn_view_flow")
                yield Button("Live [V]", variant="default", id="btn_view_historical")
                yield Button("Replay [P]", variant="default", id="btn_replay_run")
                yield Button("Resume [R]", variant="warning", id="btn_resume_failed")
                yield Button("Diff [D]", variant="default", id="btn_history_diff")
                yield Button("Payload [E]", variant="default", id="btn_history_payload")
                yield Button("Delete Run [X]", variant="error", id="btn_delete_run")

    def on_mount(self) -> None:
        table = self.query_one("#tbl_run_history", DataTable)
        table.cursor_type = "row"
        table.add_columns("Run ID", "Task", "Project", "Workflow", "Status", "Dry Run", "Tokens", "Cost ($)", "Created")
        self.refresh_history()

    def on_screen_resume(self) -> None:
        self.refresh_history()

    def refresh_history(self) -> None:
        """Pulls list of historical runs from RunManager."""
        table = self.query_one("#tbl_run_history", DataTable)
        table.clear()

        rm = getattr(self.app, "run_manager", None)
        if rm:
            runs = rm.list_runs(limit=100)
            for r in runs:
                status_styled = f"[red]{r.status.value}[/]" if r.status in (RunStatus.FAILED, RunStatus.ABORTED) else r.status.value
                table.add_row(
                    r.run_id,
                    (r.task[:32] + "...") if len(r.task) > 32 else r.task,
                    r.project,
                    r.workflow_id,
                    status_styled,
                    "Yes" if r.dry_run else "No",
                    f"{r.total_tokens:,}",
                    f"${r.total_cost_usd:.4f}",
                    r.created_at[:19].replace("T", " ")
                )

    def _get_selected_run_id(self) -> Optional[str]:
        table = self.query_one("#tbl_run_history", DataTable)
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            row = table.get_row(row_key)
            return row[0]
        except Exception:
            return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = event.data_table.get_row(event.row_key)
        self.display_run_details(row[0])

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            try:
                row = event.data_table.get_row(event.row_key)
                self.display_run_details(row[0])
            except Exception:
                pass

    def display_run_details(self, run_id: str) -> None:
        rm = getattr(self.app, "run_manager", None)
        if not rm:
            return
        try:
            from src.token_tracker import get_run_telemetry
            run = rm.load_run(run_id)
            steps_summary = " -> ".join(f"[{s.step_id}: {s.status.value}]" for s in run.steps)
            err_info = f"\n[bold red]Error:[/] {run.error}" if run.error else ""
            
            # Extract subagent flow & processed artifact statistics
            flow_info = extract_subagents_flow(run)
            stages = flow_info.get("subagents_flow", [])
            subagent_flow_str = " -> ".join(
                f"[bold cyan]{s['subagent_name']}[/] [{s['step_id']}]"
                for s in stages
            )

            p_notes = flow_info.get("processed_notes", {})
            notes_read_cnt = p_notes.get("notes_read_count", 0)
            notes_written_cnt = p_notes.get("notes_written_count", 0)
            notes_info = f"[cyan]Notes Processed (Hermes):[/] {notes_read_cnt} read from pico-vault | {notes_written_cnt} synced to activity log"

            p_code = flow_info.get("processed_code", {})
            c_stat = p_code.get("stat", {})
            v_info = p_code.get("verification", {})
            v_status = v_info.get("status", "PENDING")
            code_info = f"[magenta]Code Processed (OMP):[/] {c_stat.get('total_files', 0)} files (+{c_stat.get('total_additions', 0)}/-{c_stat.get('total_deletions', 0)}) | Branch: {p_code.get('branch_name', '-')} | Tests: [{v_status}]"

            # Fetch per-task model breakdown
            telemetry = get_run_telemetry(run_id)
            model_breakdowns = telemetry.get("by_model", [])
            model_summary = ""
            if model_breakdowns:
                model_lines = [
                    f"   * [cyan]{m['model']}[/]: {m['calls']} call(s), {m.get('tokens', 0):,} tok, ${m.get('cost', 0.0):.4f}"
                    for m in model_breakdowns
                ]
                model_summary = "\n[bold]Model Usage for Task:[/\n" + "\n".join(model_lines)

            details = (
                f"[bold]Run ID:[/] {run.run_id} | [bold]Branch:[/] {run.branch_name}\n"
                f"[bold]Task:[/] {run.task}\n"
                f"[bold yellow]Subagent Flow:[/] {subagent_flow_str}\n"
                f"{notes_info}\n"
                f"{code_info}\n"
                f"[bold]Total Spend:[/] ${run.telemetry.total_cost_usd:.4f} | [bold]Total Tokens:[/] {run.telemetry.total_tokens:,}\n"
                f"[bold]Steps:[/] {steps_summary}{model_summary}{err_info}"
            )
            self.query_one("#lbl_history_details", Static).update(details)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_view_flow":
            self.action_view_subagents_flow()
        elif btn_id == "btn_view_historical":
            self.action_view_historical()
        elif btn_id == "btn_replay_run":
            self.action_replay_run()
        elif btn_id == "btn_resume_failed":
            self.action_resume_failed()
        elif btn_id == "btn_history_diff":
            self.action_history_diff()
        elif btn_id == "btn_history_payload":
            self.action_history_payload()

    def action_view_subagents_flow(self) -> None:
        run_id = self._get_selected_run_id()
        if run_id:
            self.app.push_screen(SubagentFlowModal(run_id))

    def action_view_historical(self) -> None:
        run_id = self._get_selected_run_id()
        if run_id:
            self.app.active_run_id = run_id
            self.app.switch_screen("live_run")


    def action_replay_run(self) -> None:
        run_id = self._get_selected_run_id()
        if run_id:
            self.app.active_run_id = run_id
            self.app.switch_screen("live_run")

    def action_resume_failed(self) -> None:
        run_id = self._get_selected_run_id()
        rm = getattr(self.app, "run_manager", None)
        if rm and run_id:
            try:
                rm.resume_run(run_id)
                self.app.active_run_id = run_id
                if hasattr(self.app, "dispatch_workflow_run"):
                    self.app.dispatch_workflow_run(run_id, dry_run=True)
                self.app.switch_screen("live_run")
            except Exception:
                pass

    def action_history_diff(self) -> None:
        run_id = self._get_selected_run_id()
        if run_id:
            self.app.active_run_id = run_id
            self.app.switch_screen("finished_runs")

    def action_history_payload(self) -> None:
        run_id = self._get_selected_run_id()
        if run_id:
            self.app.active_run_id = run_id
            self.app.switch_screen("payload_editor")

    def action_refresh_history(self) -> None:
        self.refresh_history()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_view_flow":
            self.action_view_subagents_flow()
        elif btn_id == "btn_view_historical":
            self.action_view_historical()
        elif btn_id == "btn_replay_run":
            self.action_replay_run()
        elif btn_id == "btn_resume_failed":
            self.action_resume_failed()
        elif btn_id == "btn_history_diff":
            self.action_history_diff()
        elif btn_id == "btn_history_payload":
            self.action_history_payload()
        elif btn_id == "btn_delete_run":
            self.action_delete_run()
        elif btn_id == "btn_back_history":
            self.action_back()

    def action_back(self) -> None:
        self.app.action_back()

    def action_delete_run(self) -> None:
        run_id = self._get_selected_run_id()
        if not run_id:
            self.notify("No run selected to delete.", severity="warning")
            return

        def _do_delete(res) -> None:
            if res and res.get("confirmed"):
                rm = getattr(self.app, "run_manager", None)
                if rm:
                    if rm.delete_run(run_id):
                        self.notify(f"Run {run_id} permanently deleted.", severity="information")
                        self.refresh_history()
                        try:
                            self.query_one("#lbl_history_details", Static).update("Select a run above to view execution details.")
                        except Exception:
                            pass
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
