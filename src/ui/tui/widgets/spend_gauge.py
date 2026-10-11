"""
src/ui/tui/widgets/spend_gauge.py
Visual budget utilization gauge with progress bar and detailed utilization text.
"""

from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import ProgressBar, Static
from textual.containers import Vertical


class SpendGauge(Widget):
    """Component displaying a visual progress bar and spend breakdown."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield ProgressBar(id="budget_bar", total=100.0, show_eta=False)
            yield Static("$0.00 / $25.00 (0.0% utilized)", id="spend_details")
            yield Static("[HEALTHY]", id="budget_status_pill", classes="badge-valid")

    def update_spend(self, current_spend: float, budget_limit: float = 25.0) -> None:
        """Updates progress bar and text labels."""
        pct = (current_spend / budget_limit * 100.0) if budget_limit > 0 else 0.0
        pct = min(pct, 100.0)
        
        try:
            bar = self.query_one("#budget_bar", ProgressBar)
            bar.progress = pct
        except Exception:
            pass

        spend_text = f"${current_spend:.2f} / ${budget_limit:.2f} ({pct:.1f}% utilized)"
        try:
            self.query_one("#spend_details", Static).update(spend_text)
            
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
