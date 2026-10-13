"""
src/ui/tui/modals/help_modal.py
Keybindings and keyboard shortcut guide overlay dialog.
"""

from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.widgets import Label, Button, DataTable
from textual.containers import Vertical, Horizontal
from textual.binding import Binding


class HelpModal(ModalScreen[None]):
    """Modal dialog displaying global and screen-specific keyboard shortcuts."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", priority=True),
        Binding("enter", "dismiss_modal", "Close", priority=False),
        Binding("question_mark", "dismiss_modal", "Close", priority=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("ENKI COMMAND HUB — KEYBOARD SHORTCUTS", classes="modal-title")
            yield DataTable(id="tbl_help_shortcuts")
            with Horizontal(classes="modal-btn-row"):
                yield Button("Close [Esc / Enter]", variant="primary", id="btn_close_help")

    def on_mount(self) -> None:
        table = self.query_one("#tbl_help_shortcuts", DataTable)
        table.add_columns("Category", "Key / Hotkey", "Action / Target")
        
        shortcuts = [
            ("Screens", "1 / F1", "Dashboard (Mission Control)"),
            ("Screens", "2 / F2", "Start Run (Launch Form)"),
            ("Screens", "3 / F3", "Live Run (Streaming Logs & DAG Tree)"),
            ("Screens", "4 / F4", "Payload Editor (Schema Validation)"),
            ("Screens", "5 / F5", "Workflows (DAG Templates & YAML)"),
            ("Screens", "6 / F6", "Model Browser (OpenRouter Catalog)"),
            ("Screens", "7 / F7", "Obsidian Browser (Vault Notes)"),
            ("Screens", "8 / F8", "Telemetry (Spend & Financial Budget)"),
            ("Screens", "9 / F9", "Run History (Replay & Resume)"),
            ("Screens", "0 / F10", "Finished Runs (Worktrees & Diffs)"),
            ("Global", "?", "Open this Help Guide"),
            ("Global", "q / Ctrl+C", "Quit Enki TUI"),
            ("Global", "Escape / b", "Go Back to previous screen / Blur input focus"),
            ("Global", "Ctrl+B", "Unconditional Back to Dashboard / previous screen"),
            ("Global", "Tab / Shift+Tab", "Cycle focus forward / backward"),
            ("Live Run", "A / E / R / X", "Gate: Approve / Edit / Reject / Abort"),
            ("Budget", "C / P / S", "Budget: Continue / Pause / Switch Cheaper"),
            ("Worktrees", "M / K / D", "Teardown: Merge / Keep / Discard Branch"),
        ]
        for cat, key, act in shortcuts:
            table.add_row(cat, key, act)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_close_help":
            self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)
