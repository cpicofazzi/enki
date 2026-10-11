"""
src/ui/tui/modals/gate_modal.py
Approval gate dialog overlay prompting the user for decision on workflow gates.
Supports Approve, Edit & Approve, Reject with feedback, and Abort.
"""

import json
from typing import Optional, Dict, Any, List
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.widgets import Label, Button, Input, Static, TextArea
from textual.containers import Vertical, Horizontal
from textual.binding import Binding


class GateModal(ModalScreen[Optional[Dict[str, Any]]]):
    """Modal dialog prompting user approval at workflow gates."""

    BINDINGS = [
        Binding("a", "approve", "Approve", priority=False),
        Binding("e", "edit", "Edit & Approve", priority=False),
        Binding("r", "reject", "Reject", priority=False),
        Binding("x", "abort", "Abort", priority=False),
        Binding("escape", "abort", "Dismiss", priority=True),
    ]

    def __init__(
        self,
        run_id: str,
        gate_id: str,
        step_id: str = "context_extraction",
        prompt: str = "Review payload before proceeding.",
        allowed_actions: Optional[List[str]] = None,
        payload: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.run_id = run_id
        self.gate_id = gate_id
        self.step_id = step_id
        self.prompt_text = prompt
        self.allowed_actions = allowed_actions or ["approve", "edit_and_approve", "reject", "abort"]
        self.payload = payload or {}

    def compose(self) -> ComposeResult:
        with Vertical(id="gate_dialog", classes="modal-dialog gate-dialog"):
            yield Label("APPROVAL GATE INTERCEPT REQUIRED", classes="modal-title")
            yield Label(f"Step: {self.step_id} | Gate: {self.gate_id}", id="lbl_gate_details")
            yield Label(self.prompt_text, id="lbl_gate_prompt")

            preview_str = json.dumps(self.payload, indent=2) if self.payload else "No payload attached."
            yield TextArea(
                preview_str,
                read_only=True,
                language="json",
                id="txt_gate_payload_excerpt",
                tab_behavior="focus"
            )

            yield Label("Rejection / Retry Feedback (Optional):")
            yield Input(placeholder="e.g. Include negative number validation tests", id="inp_gate_feedback")

            with Horizontal(id="gate_modal_buttons", classes="modal-btn-row"):
                yield Button("Approve [A]", variant="success", id="btn_gate_approve")
                yield Button("Edit & Approve [E]", variant="primary", id="btn_gate_edit")
                yield Button("Reject [R]", variant="warning", id="btn_gate_reject")
                yield Button("Abort [X]", variant="error", id="btn_gate_abort")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id in ("btn_gate_approve", "btn_approve"):
            self.action_approve()
        elif btn_id in ("btn_gate_edit", "btn_edit"):
            self.action_edit()
        elif btn_id in ("btn_gate_reject", "btn_reject"):
            self.action_reject()
        elif btn_id in ("btn_gate_abort", "btn_abort"):
            self.action_abort()

    def action_approve(self) -> None:
        self.dismiss({"action": "approve", "gate_id": self.gate_id, "run_id": self.run_id})

    def action_edit(self) -> None:
        self.dismiss({
            "action": "edit_and_approve",
            "gate_id": self.gate_id,
            "run_id": self.run_id,
            "payload": self.payload
        })

    def action_reject(self) -> None:
        try:
            feedback = self.query_one("#inp_gate_feedback", Input).value.strip()
        except Exception:
            feedback = ""
        self.dismiss({
            "action": "reject",
            "gate_id": self.gate_id,
            "run_id": self.run_id,
            "feedback": feedback
        })

    def action_abort(self) -> None:
        self.dismiss({"action": "abort", "gate_id": self.gate_id, "run_id": self.run_id})


# Backward compatibility alias
ApprovalGateModal = GateModal
