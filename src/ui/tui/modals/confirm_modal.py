"""
src/ui/tui/modals/confirm_modal.py
Confirmation modal dialog for worktree teardown (Merge, Keep, Discard) and destructive operations.
"""

from typing import Optional, Dict, Any, Literal
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.widgets import Label, Button, Static, Input
from textual.containers import Vertical, Horizontal
from textual.binding import Binding


class ConfirmModal(ModalScreen[Optional[Dict[str, Any]]]):
    """Confirmation modal dialog for destructive or critical actions."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    def __init__(
        self,
        title: str = "Confirm Action",
        message: str = "Are you sure you want to proceed?",
        action: Literal["merge", "keep", "discard", "confirm"] = "confirm",
        run_id: str = "",
        branch_name: str = "",
        target_branch: str = "main",
        diff_stats: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.modal_title = title
        self.message = message
        self.action = action
        self.run_id = run_id
        self.branch_name = branch_name
        self.target_branch = target_branch
        self.diff_stats = diff_stats or {}

    def compose(self) -> ComposeResult:
        dialog_class = "danger-dialog" if self.action == "discard" else "confirm-dialog"
        with Vertical(id="teardown_dialog", classes=f"modal-dialog {dialog_class}"):
            yield Label(self.modal_title, id="td_title", classes="modal-title")
            yield Static(self.message, id="td_message")

            if self.action == "merge":
                yield Label("Target Branch to Merge into:")
                yield Input(value=self.target_branch, id="target_branch_input")

            with Horizontal(classes="modal-btn-row"):
                btn_variant = "error" if self.action == "discard" else "success"
                confirm_label = f"Confirm {self.action.capitalize()} [Enter]"
                yield Button(confirm_label, variant=btn_variant, id="btn_confirm")
                yield Button("Cancel [Esc]", variant="default", id="btn_cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_confirm":
            self.action_confirm()
        elif event.button.id == "btn_cancel":
            self.action_cancel()

    def action_confirm(self) -> None:
        target = self.target_branch
        if self.action == "merge":
            try:
                target = self.query_one("#target_branch_input", Input).value.strip() or self.target_branch
            except Exception:
                pass
        self.dismiss({
            "confirmed": True,
            "action": self.action,
            "run_id": self.run_id,
            "branch_name": self.branch_name,
            "target_branch": target,
        })

    def action_cancel(self) -> None:
        self.dismiss(None)


# Backward compatibility alias
WorktreeTeardownModal = ConfirmModal
