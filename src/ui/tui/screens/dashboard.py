"""
src/ui/tui/screens/dashboard.py
Screen 1: DashboardScreen (Feature F23)
Mission control center displaying active/gated runs, spend gauge vs budget, and gateway status.
"""

from typing import Optional
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Label, Static, DataTable, Button, ProgressBar
from textual.containers import Container, Horizontal, Vertical, Grid
from textual.binding import Binding

from src.ui.tui.widgets.header_bar import HeaderBar
from src.token_tracker import get_summary
from src.config import load_config
from src.engine.models import RunStatus


class DashboardScreen(Screen):
    """Screen 1: Enki Command Hub Dashboard."""

    BINDINGS = [
        Binding("n", "new_run", "New Run", priority=False),
        Binding("r", "refresh", "Refresh", priority=False),
        Binding("g", "resolve_gate", "Resolve Gate", priority=False),
        Binding("enter", "view_selected", "View Selected", priority=False),
    ]

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="screen_dashboard"):
            with Grid(id="dash_overview_grid", classes="card"):
                with Container(id="card_gateway_status"):
                    yield Label("AI MODEL GATEWAYS", classes="section-title")
                    yield Static("OpenRouter [ACTIVE]", id="active_gw_name")
                    yield Static("[Configured - Ready]", id="active_gw_key_status")
                    yield Static("Hermes: Auto | OMP: claude-3.5-sonnet", id="active_models_summary")

                with Container(id="card_spend_budget"):
                    yield Label("MONTHLY SPEND & BUDGET", classes="section-title")
                    yield ProgressBar(id="budget_bar", total=100.0, show_eta=False)
                    yield Static("$0.00 / $25.00 (0.0% utilized)", id="spend_details")
                    yield Static("[HEALTHY]", id="budget_status_pill", classes="badge-valid")

                with Container(id="card_run_metrics"):
                    yield Label("RUN EXECUTION METRICS", classes="section-title")
                    yield Static("Active: 0 | Gated: 0 | Queued: 0", id="metric_active_runs")
                    yield Static("Completed: 0 | Failed: 0", id="metric_historical_runs")

            with Container(id="dash_active_runs_container", classes="card"):
                yield Label("ACTIVE & GATED WORKFLOW RUNS", classes="section-title")
                yield DataTable(id="tbl_active_runs")

            with Horizontal(id="dash_quick_actions", classes="action-bar"):
                yield Button("New Run [N]", variant="primary", id="btn_new_run")
                yield Button("View Selected [Enter]", variant="default", id="btn_view_run")
                yield Button("Resolve Gate [G]", variant="warning", id="btn_resolve_gate")
                yield Button("Refresh [R]", variant="default", id="btn_refresh_dash")

    def on_mount(self) -> None:
        table = self.query_one("#tbl_active_runs", DataTable)
        table.cursor_type = "row"
        table.add_columns("Run ID", "Task Description", "Project", "Status", "Dry Run", "Cost ($)", "Created")
        self.refresh_dashboard()

    def on_screen_resume(self) -> None:
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        """Pulls latest engine runs, token usage, and gateway configurations."""
        try:
            cfg = load_config()
            active_gw = cfg.get("active_gateway", "openrouter")
            gw_data = cfg.get("gateways", {}).get(active_gw, {})
            gw_name = gw_data.get("name", active_gw.replace("_", " ").title())
            has_key = bool(gw_data.get("api_key"))
            
            self.query_one("#active_gw_name", Static).update(f"{gw_name} [ACTIVE]")
            self.query_one("#active_gw_key_status", Static).update(
                "[Configured - Live]" if has_key else "[Not configured - Simulation Mode]"
            )
            hermes_m = gw_data.get("hermes_model", "Auto")
            omp_m = gw_data.get("omp_model", "Auto")
            self.query_one("#active_models_summary", Static).update(
                f"Hermes: {hermes_m} | OMP: {omp_m}"
            )
        except Exception:
            pass

        # Telemetry & Budget
        try:
            summary = get_summary(days=30)
            cost = summary.get("total_cost_usd", 0.0)
            cfg = load_config()
            budget = cfg.get("telemetry", {}).get("monthly_budget_usd", 25.0)
            pct = (cost / budget * 100.0) if budget > 0 else 0.0
            
            bar = self.query_one("#budget_bar", ProgressBar)
            bar.progress = min(pct, 100.0)

            self.query_one("#spend_details", Static).update(
                f"${cost:.2f} / ${budget:.2f} ({pct:.1f}% utilized)"
            )
            pill = self.query_one("#budget_status_pill", Static)
            if pct >= 100.0:
                pill.update("[STOPPED >=100%]")
                pill.set_classes("badge-invalid")
            elif pct >= 80.0:
                pill.update("[WARNING >=80%]")
                pill.set_classes("badge-warning")
            else:
                pill.update("[HEALTHY]")
                pill.set_classes("badge-valid")
        except Exception:
            pass

        # Runs table & metrics
        try:
            rm = getattr(self.app, "run_manager", None)
            if rm:
                all_runs = rm.list_runs(limit=50)
                active_count = sum(1 for r in all_runs if r.status == RunStatus.RUNNING)
                gated_count = sum(1 for r in all_runs if r.status in (RunStatus.WAITING_GATE, RunStatus.WAITING_BUDGET))
                completed_count = sum(1 for r in all_runs if r.status == RunStatus.COMPLETED)
                failed_count = sum(1 for r in all_runs if r.status in (RunStatus.FAILED, RunStatus.ABORTED))

                self.query_one("#metric_active_runs", Static).update(
                    f"Active: {active_count} | Gated: {gated_count} | Queued: 0"
                )
                self.query_one("#metric_historical_runs", Static).update(
                    f"Completed: {completed_count} | Failed: {failed_count}"
                )

                table = self.query_one("#tbl_active_runs", DataTable)
                table.clear()
                for r in all_runs:
                    status_styled = f"[yellow]{r.status.value}[/]" if "waiting" in r.status.value else r.status.value
                    table.add_row(
                        r.run_id,
                        (r.task[:40] + "...") if len(r.task) > 40 else r.task,
                        r.project,
                        status_styled,
                        "Yes" if r.dry_run else "No",
                        f"${r.total_cost_usd:.4f}",
                        r.created_at[:19].replace("T", " ")
                    )
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_new_run":
            self.action_new_run()
        elif btn_id == "btn_refresh_dash":
            self.action_refresh()
        elif btn_id == "btn_view_run":
            self.action_view_selected()
        elif btn_id == "btn_resolve_gate":
            self.action_resolve_gate()

    def action_new_run(self) -> None:
        self.app.switch_screen("start_run")

    def action_refresh(self) -> None:
        self.refresh_dashboard()

    def action_view_selected(self) -> None:
        table = self.query_one("#tbl_active_runs", DataTable)
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            row_data = table.get_row(row_key)
            run_id = row_data[0]
            if hasattr(self.app, "view_run"):
                self.app.view_run(run_id)
            else:
                self.app.active_run_id = run_id
                self.app.switch_screen("live_run")
        except Exception:
            pass

    def action_resolve_gate(self) -> None:
        table = self.query_one("#tbl_active_runs", DataTable)
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            row_data = table.get_row(row_key)
            run_id = row_data[0]
            self.app.active_run_id = run_id
            self.app.switch_screen("live_run")
        except Exception:
            pass
