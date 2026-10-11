"""
src/ui/tui/screens/telemetry.py
Screen 8: TelemetryScreen (Feature F30)
Financial and token analytics, spend vs budget gauge, agent/model breakdown tables,
and SQLite transaction log.
"""

from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Label, Static, DataTable, ProgressBar, Button
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding

from src.ui.tui.widgets.header_bar import HeaderBar
from src.token_tracker import get_summary
from src.config import load_config


class TelemetryScreen(Screen):
    """Screen 8: Telemetry, spend monitoring, and token analytics."""

    BINDINGS = [
        Binding("r", "refresh_telemetry", "Refresh Telemetry", priority=False),
    ]

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="screen_telemetry"):
            with Container(id="telemetry_budget_card", classes="card"):
                yield Label("MONTHLY FINANCIAL BUDGET UTILIZATION", classes="section-title")
                yield ProgressBar(id="telemetry_progress_bar", total=100.0, show_eta=False)
                with Horizontal(id="telemetry_budget_stats"):
                    yield Static("Budget Limit: $25.00 USD", id="lbl_budget_limit")
                    yield Static("Actual Spend: $0.00 USD", id="lbl_actual_spend")
                    yield Static("0.0% Utilized", id="lbl_utilization_pct")
                    yield Static("Total Calls: 0", id="lbl_invocations_count")

            with Horizontal(id="telemetry_breakdowns", classes="card"):
                with Vertical(id="breakdown_by_model_pane", classes="pane-50"):
                    yield Label("USAGE BY INDIVIDUAL MODEL", classes="section-title")
                    yield DataTable(id="tbl_by_model")

                with Vertical(id="breakdown_by_agent_pane", classes="pane-50"):
                    yield Label("USAGE BY AGENT ROLE", classes="section-title")
                    yield DataTable(id="tbl_by_agent")

            with Container(id="task_usage_pane", classes="card"):
                yield Label("USAGE PER TASK / RUN (Aggregated Invocations & Cost)", classes="section-title")
                yield DataTable(id="tbl_by_task")

            with Container(id="recent_transactions_pane", classes="card"):
                yield Label("RECENT INDIVIDUAL MODEL INVOCATIONS (SQLite)", classes="section-title")
                yield DataTable(id="tbl_recent_tx")

            with Horizontal(id="telemetry_action_bar", classes="action-bar"):
                yield Button("Refresh Telemetry [R]", variant="primary", id="btn_refresh_telemetry")

    def on_mount(self) -> None:
        tbl_model = self.query_one("#tbl_by_model", DataTable)
        tbl_model.cursor_type = "row"
        tbl_model.add_columns("Model ID", "Calls", "Prompt", "Completion", "Total Tokens", "Total Cost ($)")

        tbl_agent = self.query_one("#tbl_by_agent", DataTable)
        tbl_agent.cursor_type = "row"
        tbl_agent.add_columns("Agent Role", "Calls", "Total Tokens", "Cost ($)")

        tbl_task = self.query_one("#tbl_by_task", DataTable)
        tbl_task.cursor_type = "row"
        tbl_task.add_columns("Task / Run ID", "Calls", "Models Invoked", "Prompt", "Completion", "Total Tokens", "Cost ($)")

        tbl_tx = self.query_one("#tbl_recent_tx", DataTable)
        tbl_tx.cursor_type = "row"
        tbl_tx.add_columns("ID", "Timestamp", "Agent", "Model", "Prompt", "Comp", "Total", "Cost ($)", "Task ID")

        self.refresh_telemetry_data()

    def on_screen_resume(self) -> None:
        self.refresh_telemetry_data()

    def refresh_telemetry_data(self) -> None:
        """Pulls telemetry summary, model metrics, and per-task analytics from SQLite."""
        from src.token_tracker import get_all_models_usage, get_task_usage_summary
        cfg = load_config()
        budget_limit = cfg.get("telemetry", {}).get("monthly_budget_usd", 25.0)

        try:
            summary = get_summary(days=30)
            models_usage = get_all_models_usage(days=90)
            task_usage = get_task_usage_summary(limit=50)

            actual_spend = summary.get("total_cost_usd", 0.0)
            calls_count = summary.get("total_calls", 0)
            pct = (actual_spend / budget_limit * 100.0) if budget_limit > 0 else 0.0

            bar = self.query_one("#telemetry_progress_bar", ProgressBar)
            bar.progress = min(pct, 100.0)

            self.query_one("#lbl_budget_limit", Static).update(f"Budget Limit: ${budget_limit:.2f} USD")
            self.query_one("#lbl_actual_spend", Static).update(f"Actual Spend: ${actual_spend:.4f} USD")
            self.query_one("#lbl_utilization_pct", Static).update(f"{pct:.1f}% Utilized")
            self.query_one("#lbl_invocations_count", Static).update(f"Total Calls: {calls_count}")

            # By Individual Model table (granular prompt / completion / total / cost)
            tbl_model = self.query_one("#tbl_by_model", DataTable)
            tbl_model.clear()
            for m in models_usage:
                tbl_model.add_row(
                    m.get("model", "unknown"),
                    str(m.get("total_calls", 0)),
                    f"{m.get('prompt_tokens', 0):,}",
                    f"{m.get('completion_tokens', 0):,}",
                    f"{m.get('total_tokens', 0):,}",
                    f"${m.get('total_cost_usd', 0.0):.4f}"
                )

            # By Agent table
            tbl_agent = self.query_one("#tbl_by_agent", DataTable)
            tbl_agent.clear()
            for a in summary.get("by_agent", []):
                tbl_agent.add_row(
                    a.get("agent_role", "unknown").upper(),
                    str(a.get("calls", 0)),
                    f"{a.get('tokens', 0):,}",
                    f"${a.get('cost', 0.0):.4f}"
                )

            # Per-Task Usage Table
            tbl_task = self.query_one("#tbl_by_task", DataTable)
            tbl_task.clear()
            for t in task_usage:
                m_used = t.get("models_used") or "none"
                if len(m_used) > 28:
                    m_used = m_used[:25] + "..."
                tbl_task.add_row(
                    str(t.get("task_id", "")),
                    str(t.get("total_calls", 0)),
                    m_used,
                    f"{t.get('prompt_tokens', 0):,}",
                    f"{t.get('completion_tokens', 0):,}",
                    f"{t.get('total_tokens', 0):,}",
                    f"${t.get('total_cost_usd', 0.0):.4f}"
                )

            # Recent transactions table with prompt & completion breakdown
            tbl_tx = self.query_one("#tbl_recent_tx", DataTable)
            tbl_tx.clear()
            for tx in summary.get("recent_records", []):
                tbl_tx.add_row(
                    str(tx.get("id", "")),
                    str(tx.get("timestamp", ""))[:19].replace("T", " "),
                    str(tx.get("agent_role", "")).upper(),
                    str(tx.get("model", "")),
                    f"{tx.get('prompt_tokens', 0):,}",
                    f"{tx.get('completion_tokens', 0):,}",
                    f"{tx.get('total_tokens', 0):,}",
                    f"${tx.get('cost_usd', 0.0):.4f}",
                    str(tx.get("task_id", ""))
                )
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_refresh_telemetry":
            self.action_refresh_telemetry()

    def action_refresh_telemetry(self) -> None:
        self.refresh_telemetry_data()
