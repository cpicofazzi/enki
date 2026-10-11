"""
src/ui/tui/widgets/header_bar.py
Top status header bar displaying active gateway, financial spend pill, and navigation shortcuts.
"""

from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import Horizontal
from src.token_tracker import get_summary
from src.config import load_config


class HeaderBar(Widget):
    """Global top navigation header bar."""

    can_focus = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("ENKI COMMAND HUB", id="header_hub_title")
            yield Static("Gateway: Loading...", id="header_gateway_badge")
            yield Static("Spend: $0.00 / $25.00", id="header_spend_pill")
            yield Static("[?] Help | [1-0] Screens | [Q] Quit", id="header_nav_hint")

    def on_mount(self) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        """Fetches active gateway and SQLite telemetry spend to update header."""
        try:
            cfg = load_config()
            active_gw = cfg.get("active_gateway", "openrouter")
            gw_data = cfg.get("gateways", {}).get(active_gw, {})
            gw_name = gw_data.get("name", active_gw.replace("_", " ").title())
            has_key = bool(gw_data.get("api_key"))
            badge_str = f"Gateway: {gw_name} [{'Live' if has_key else 'Sim'}]"
            self.query_one("#header_gateway_badge", Static).update(badge_str)

            summary = get_summary(days=30)
            cost = summary.get("total_cost_usd", 0.0)
            budget = cfg.get("telemetry", {}).get("monthly_budget_usd", 25.0)
            spend_str = f"Spend: ${cost:.2f} / ${budget:.2f}"
            self.query_one("#header_spend_pill", Static).update(spend_str)
        except Exception:
            pass
