"""
src/ui/tui/modals/budget_modal.py
Budget stop dialog overlay presenting the 3 mandatory options when spend limit is reached:
Continue Spending, Pause Run, or Switch to Cheaper Model.
"""

from typing import Optional
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.widgets import Label, Button, Static
from textual.containers import Vertical, Horizontal
from textual.binding import Binding
from src.engine.models import BudgetDecision


class BudgetModal(ModalScreen[Optional[BudgetDecision]]):
    """Modal dialog triggered when monthly spend reaches configured budget limit."""

    BINDINGS = [
        Binding("c", "continue", "Continue", priority=False),
        Binding("p", "pause", "Pause", priority=False),
        Binding("s", "switch", "Switch Cheaper", priority=False),
        Binding("escape", "pause", "Dismiss/Pause", priority=True),
    ]

    def __init__(
        self,
        run_id: str,
        current_spend_usd: float = 25.0,
        budget_limit_usd: float = 25.0,
        suggested_cheaper_model: Optional[str] = "z-ai/glm-5.3-flash",
        suggested_reason: Optional[str] = "Ultra value tier model for routine tasks",
        **kwargs
    ):
        super().__init__(**kwargs)
        self.run_id = run_id
        self.current_spend = current_spend_usd
        self.budget_limit = budget_limit_usd
        self.suggested_model = suggested_cheaper_model or "z-ai/glm-5.3-flash"
        self.reason = suggested_reason or "Low cost frontier alternative"

    def compose(self) -> ComposeResult:
        with Vertical(id="budget_dialog", classes="modal-dialog budget-dialog"):
            yield Label("MONTHLY FINANCIAL BUDGET LIMIT REACHED", classes="modal-title")
            yield Label(
                f"Current Spend: ${self.current_spend:.2f} / Budget: ${self.budget_limit:.2f} USD",
                id="budget_warning"
            )
            yield Static(
                f"\nExecution is halted before the next model call.\n"
                f"Suggested Cheaper Model: [bold green]{self.suggested_model}[/]\n"
                f"Reason: {self.reason}\n\n"
                f"Choose how to proceed:"
            )

            with Horizontal(classes="modal-btn-row"):
                yield Button("Continue Spending [C]", variant="warning", id="btn_continue")
                yield Button("Pause Run [P]", variant="default", id="btn_pause")
                yield Button("Switch to Cheaper Model [S]", variant="success", id="btn_switch")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_continue":
            self.action_continue()
        elif btn_id == "btn_pause":
            self.action_pause()
        elif btn_id == "btn_switch":
            self.action_switch()

    def action_continue(self) -> None:
        self.dismiss(BudgetDecision.CONTINUE)

    def action_pause(self) -> None:
        self.dismiss(BudgetDecision.PAUSE)

    def action_switch(self) -> None:
        self.dismiss(BudgetDecision.SWITCH_CHEAPER)


# Backward compatibility alias
BudgetStopModal = BudgetModal
