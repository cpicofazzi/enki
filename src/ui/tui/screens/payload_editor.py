"""
src/ui/tui/screens/payload_editor.py
Screen 4: PayloadEditorScreen (Feature F26)
Context payload viewer and raw JSON editor with live validation against schemas/context_payload.schema.json.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Label, Static, TextArea, Button, TabbedContent, TabPane, Input
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.binding import Binding
import jsonschema

from src.ui.tui.widgets.header_bar import HeaderBar
from src.ui.tui.widgets.schema_badge import SchemaBadge


class PayloadEditorScreen(Screen):
    """Screen 4: Context Payload Editor with live JSON schema validation."""

    BINDINGS = [
        Binding("ctrl+s", "save_payload", "Save", priority=True),
        Binding("ctrl+f", "format_json", "Format", priority=False),
        Binding("escape", "discard", "Cancel", priority=False),
    ]

    def __init__(self, run_id: Optional[str] = None, initial_payload: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(**kwargs)
        self.run_id = run_id
        self.initial_payload = initial_payload
        self._schema: Optional[Dict[str, Any]] = None
        self._load_schema()

    def _load_schema(self) -> None:
        root_dir = Path(__file__).resolve().parents[4]
        schema_file = root_dir / "schemas" / "context_payload.schema.json"
        if schema_file.is_file():
            try:
                with open(schema_file, "r", encoding="utf-8") as f:
                    self._schema = json.load(f)
            except Exception:
                self._schema = None

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="screen_payload_editor"):
            with Horizontal(id="payload_status_bar", classes="card"):
                yield Static("Context Payload Editor (context_payload.json)", id="lbl_payload_title")
                yield SchemaBadge(id="lbl_schema_status")

            with Container(id="editor_pane", classes="card"):
                yield TextArea(
                    id="txt_payload_json",
                    language="json",
                    tab_behavior="focus"
                )

            with Horizontal(id="payload_action_bar", classes="action-bar"):
                yield Button("Discard / Back [Esc]", variant="error", id="btn_discard_payload")
                yield Button("Validate Schema", variant="default", id="btn_validate_json")
                yield Button("Format JSON", variant="default", id="btn_format_json")
                yield Button("Save Payload", variant="primary", id="btn_save_payload")
                yield Button("Save & Approve Gate", variant="success", id="btn_save_approve_gate")

    def on_mount(self) -> None:
        self._loaded_for_run = self.run_id or getattr(self.app, "active_run_id", "")
        self.load_initial_payload()
        self.validate_current_json()

    def on_screen_resume(self) -> None:
        """Cached screen: reload if a gate handed over new payload data or the run changed."""
        current_run = self.run_id or getattr(self.app, "active_run_id", "")
        if getattr(self.app, "editing_payload_data", None) or current_run != self._loaded_for_run:
            self._loaded_for_run = current_run
            self.load_initial_payload()
            self.validate_current_json()

    def load_initial_payload(self) -> None:
        """Loads payload from parameters, app state, active run, or root context_payload.json."""
        target_data = None
        if self.initial_payload:
            target_data = self.initial_payload
        elif hasattr(self.app, "editing_payload_data") and self.app.editing_payload_data:
            target_data = self.app.editing_payload_data
            self.app.editing_payload_data = None

        if not target_data:
            run_id = self.run_id or getattr(self.app, "active_run_id", "")
            rm = getattr(self.app, "run_manager", None)
            if rm and run_id:
                try:
                    payload_file = rm.get_context_payload_file(run_id)
                    if payload_file.is_file():
                        with open(payload_file, "r", encoding="utf-8") as f:
                            target_data = json.load(f)
                except Exception:
                    pass

        if not target_data:
            # Fallback to default template
            target_data = {
                "task_id": "task_default_spec",
                "title": "Default Task Specification",
                "timestamp": "2026-10-10T14:00:00Z",
                "source": "40_Tasks/Default.md",
                "status": "pending",
                "requirements": ["Build normalization pipeline", "Verify tests pass"],
                "engineering_constraints": {
                    "language": "python",
                    "framework": "pytest",
                    "prohibited_actions": ["No hardcoded strings"]
                },
                "acceptance_criteria": {
                    "test_commands": ["py -m pytest -q"]
                }
            }

        txt_editor = self.query_one("#txt_payload_json", TextArea)
        txt_editor.text = json.dumps(target_data, indent=2)

    def validate_current_json(self) -> bool:
        """Validates current TextArea content against JSON syntax and Draft-07 schema."""
        txt_editor = self.query_one("#txt_payload_json", TextArea)
        badge = self.query_one("#lbl_schema_status", SchemaBadge)

        try:
            parsed = json.loads(txt_editor.text)
        except json.JSONDecodeError as err:
            badge.set_invalid(f"Syntax Error: {err.msg} at line {err.lineno}")
            return False

        if self._schema:
            try:
                jsonschema.validate(instance=parsed, schema=self._schema)
                badge.set_valid("[VALID: Draft-07]")
                return True
            except jsonschema.ValidationError as v_err:
                field = ".".join(str(p) for p in v_err.path) if v_err.path else "root"
                badge.set_invalid(f"{field}: {v_err.message}")
                return False
            except Exception as e:
                badge.set_invalid(str(e))
                return False

        badge.set_valid("[VALID: JSON Syntax]")
        return True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_validate_json":
            self.validate_current_json()
        elif btn_id == "btn_format_json":
            self.action_format_json()
        elif btn_id == "btn_save_payload":
            self.action_save_payload()
        elif btn_id == "btn_save_approve_gate":
            self.action_save_and_approve()
        elif btn_id == "btn_discard_payload":
            self.action_discard()

    def action_format_json(self) -> None:
        txt_editor = self.query_one("#txt_payload_json", TextArea)
        try:
            data = json.loads(txt_editor.text)
            txt_editor.text = json.dumps(data, indent=2)
            self.validate_current_json()
        except Exception:
            pass

    def action_save_payload(self) -> None:
        txt_editor = self.query_one("#txt_payload_json", TextArea)
        try:
            data = json.loads(txt_editor.text)
        except Exception:
            self.validate_current_json()
            return

        run_id = self.run_id or getattr(self.app, "active_run_id", "")
        rm = getattr(self.app, "run_manager", None)
        if rm and run_id:
            try:
                p_file = rm.get_context_payload_file(run_id)
                with open(p_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                run = rm.load_run(run_id)
                run.payload = data
                rm.save_run(run)
            except Exception:
                pass

        self.validate_current_json()

    def action_save_and_approve(self) -> None:
        if not self.validate_current_json():
            return  # never approve a gate with a schema-invalid payload
        self.action_save_payload()
        run_id = self.run_id or getattr(self.app, "active_run_id", "")
        rm = getattr(self.app, "run_manager", None)
        resolved = False
        if rm and run_id:
            try:
                run = rm.load_run(run_id)
                gate_id = (
                    getattr(self.app, "editing_payload_gate_id", None)
                    or (run.gate_state.gate_id if run.gate_state else f"gate_edit_{run_id}")
                )
                data = json.loads(self.query_one("#txt_payload_json", TextArea).text)
                rm.resolve_gate(run_id, gate_id, "edit_and_approve", payload=data)
                resolved = True
            except Exception:
                pass
        self.app.editing_payload_gate_id = None
        if resolved and hasattr(self.app, "resume_run_after_resolution"):
            self.app.resume_run_after_resolution(run_id)
        self.app.switch_screen("live_run")

    def action_discard(self) -> None:
        self.app.action_back()
