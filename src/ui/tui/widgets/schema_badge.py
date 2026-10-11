"""
src/ui/tui/widgets/schema_badge.py
Live JSON schema validation indicator badge.
"""

from textual.widgets import Static


class SchemaBadge(Static):
    """Badge indicating JSON schema validation status."""

    def __init__(self, id: str = "lbl_schema_status", **kwargs):
        super().__init__("[VALID: Draft-07]", id=id, classes="badge-valid", **kwargs)

    def set_valid(self, message: str = "[VALID: Draft-07]") -> None:
        self.update(message)
        self.remove_class("badge-invalid")
        self.add_class("badge-valid")

    def set_invalid(self, error: str) -> None:
        self.update(f"[INVALID: {error}]")
        self.remove_class("badge-valid")
        self.add_class("badge-invalid")
