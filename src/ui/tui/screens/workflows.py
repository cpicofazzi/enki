"""
src/ui/tui/screens/workflows.py
Screen 5: WorkflowsScreen (Feature F27)
Workflow template catalog from workflows/*.yaml, DAG dependency topological summary, and YAML preview.
"""

from pathlib import Path
from typing import Dict, Any, List
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Label, Static, DataTable, TextArea, Button
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding

from src.ui.tui.widgets.header_bar import HeaderBar
from src.engine.workflow_parser import WorkflowParser, WorkflowDefinition


class WorkflowsScreen(Screen):
    """Screen 5: Workflow DAG templates and specification browser."""

    BINDINGS = [
        Binding("escape", "back", "Back", priority=False),
        Binding("enter", "use_workflow", "Use Workflow", priority=False),
        Binding("r", "reload", "Reload", priority=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.parser = WorkflowParser()
        self.loaded_workflows: Dict[str, WorkflowDefinition] = {}

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="screen_workflows"):
            with Horizontal(id="workflows_main_split", classes="split-container"):
                with Vertical(id="workflows_list_pane", classes="pane-40 pane-container"):
                    yield Label("AVAILABLE WORKFLOW TEMPLATES (workflows/*.yaml)", classes="section-title")
                    yield DataTable(id="tbl_workflows")

                with Vertical(id="workflow_detail_pane", classes="pane-60 pane-container"):
                    with Container(id="dag_step_summary_card", classes="card"):
                        yield Label("DAG TOPOLOGICAL EXECUTION TIERS", classes="section-title")
                        yield Static("Tier 1: [context] -> Tier 2: [coding]", id="lbl_dag_tiers_summary")

                    yield Label("WORKFLOW SPECIFICATION (YAML)", classes="section-title")
                    yield TextArea(
                        id="txt_workflow_yaml",
                        read_only=True,
                        language="yaml",
                        tab_behavior="focus"
                    )

            with Horizontal(id="workflow_actions", classes="action-bar"):
                yield Button("Back [Esc]", variant="default", id="btn_back_workflows")
                yield Button("Start Run with this Workflow [Enter]", variant="primary", id="btn_use_workflow")
                yield Button("Reload from Disk [R]", variant="default", id="btn_reload_workflows")

    def on_mount(self) -> None:
        table = self.query_one("#tbl_workflows", DataTable)
        table.cursor_type = "row"
        table.add_columns("ID", "Name", "Steps", "Version")
        self.load_workflows_from_disk()

    def load_workflows_from_disk(self) -> None:
        """Scans workflows/*.yaml and populates DataTable and cache."""
        root_dir = Path(__file__).resolve().parents[4]
        wf_dir = root_dir / "workflows"
        self.loaded_workflows.clear()

        table = self.query_one("#tbl_workflows", DataTable)
        table.clear()

        if wf_dir.is_dir():
            for f in sorted(wf_dir.glob("*.yaml")):
                try:
                    wf_def = self.parser.parse_file(f)
                    self.loaded_workflows[wf_def.id] = wf_def
                    table.add_row(
                        wf_def.id,
                        wf_def.name,
                        str(len(wf_def.steps)),
                        wf_def.version or "1.0.0"
                    )
                except Exception:
                    continue

        if self.loaded_workflows:
            first_id = next(iter(self.loaded_workflows))
            self.display_workflow_details(first_id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = event.data_table.get_row(event.row_key)
        wf_id = row[0]
        self.display_workflow_details(wf_id)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            try:
                row = event.data_table.get_row(event.row_key)
                wf_id = row[0]
                self.display_workflow_details(wf_id)
            except Exception:
                pass

    def display_workflow_details(self, wf_id: str) -> None:
        wf_def = self.loaded_workflows.get(wf_id)
        if not wf_def:
            return

        # Topological tiers string
        tier_parts = []
        for idx, tier in enumerate(wf_def.execution_tiers, start=1):
            tier_parts.append(f"Tier {idx}: [{' | '.join(tier)}]")
        tiers_str = " -> ".join(tier_parts) if tier_parts else "No dependencies defined"
        self.query_one("#lbl_dag_tiers_summary", Static).update(tiers_str)

        # Raw YAML text
        yaml_text = self.parser.dump_string(wf_def)
        self.query_one("#txt_workflow_yaml", TextArea).text = yaml_text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_use_workflow":
            self.action_use_workflow()
        elif event.button.id == "btn_reload_workflows":
            self.action_reload()
        elif event.button.id == "btn_back_workflows":
            self.action_back()

    def action_back(self) -> None:
        self.app.action_back()

    def action_use_workflow(self) -> None:
        table = self.query_one("#tbl_workflows", DataTable)
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            row = table.get_row(row_key)
            wf_id = row[0]
            self.app.prefill_workflow = wf_id
            self.app.switch_screen("start_run")
        except Exception:
            self.app.switch_screen("start_run")

    def action_reload(self) -> None:
        self.load_workflows_from_disk()
