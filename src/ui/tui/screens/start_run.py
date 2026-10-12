"""
src/ui/tui/screens/start_run.py
Screen 2: StartRunScreen (Feature F24)
Run launch form with task prompt, project picker (excluding Body.me), workflow picker,
approval gates, model overrides, dry-run toggle, and cost estimation.
"""

from pathlib import Path
from typing import Optional, List, Tuple
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Label, TextArea, Select, Checkbox, Switch, Input, Button, Static
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.binding import Binding

from src.ui.tui.widgets.header_bar import HeaderBar
from src.config import load_config, get_active_projects
from src.openrouter_catalog import OpenRouterCatalog


class StartRunScreen(Screen):
    """Screen 2: Launch and configure new workflow runs."""

    BINDINGS = [
        Binding("ctrl+enter", "submit", "Start Run", priority=True),
        Binding("escape", "cancel", "Cancel", priority=False),
    ]

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with VerticalScroll(id="screen_start_run"):
            with Container(classes="card"):
                yield Label("Task Description / Feature Requirements *", classes="section-title")
                yield TextArea(
                    id="txt_task_prompt",
                    language="markdown",
                    tab_behavior="focus"
                )

            with Horizontal(classes="card"):
                with Vertical(classes="pane-50"):
                    yield Label("Target Project", classes="section-title")
                    yield Select([], id="sel_project", prompt="Select Project...")
                with Vertical(classes="pane-50"):
                    yield Label("Workflow Template", classes="section-title")
                    yield Select([], id="sel_workflow", prompt="Select Workflow...")

            with Horizontal(classes="card"):
                with Vertical(classes="pane-50"):
                    yield Label("Research Strategy & Knowledge Sources", classes="section-title")
                    yield Checkbox("Local Vault Research (Search pico-vault)", value=True, id="chk_local_research")
                    yield Checkbox("Find Web Research (Internet Synthesis & Note)", value=False, id="chk_find_research")
                with Vertical(classes="pane-50"):
                    yield Label("Interactive Approval Gates", classes="section-title")
                    yield Checkbox("Post-Context Approval Gate", value=True, id="chk_gate_post_context")
                    yield Checkbox("Pre-Code Approval Gate", value=True, id="chk_gate_pre_code")

            with Horizontal(classes="card"):
                with Vertical(classes="pane-50"):
                    yield Label("Model Overrides & Presets", classes="section-title")
                    yield Select([], id="sel_preset", prompt="Curated Preset (Optional)...")
                with Vertical(classes="pane-50"):
                    yield Label("Custom Model Override", classes="section-title")
                    yield Input(placeholder="Custom Model (e.g. anthropic/claude-3.7-sonnet)", id="inp_model_override")

            with Horizontal(classes="card"):
                with Horizontal(classes="pane-50"):
                    yield Switch(value=True, id="sw_dry_run")
                    yield Label(" Dry-Run Simulation Mode ($0.00 spend)")
                with Container(id="cost_estimate_pill", classes="pane-50"):
                    yield Static("Est: ~18,500 tokens | ~$0.00 USD (Simulation)", id="lbl_cost_estimate")

            with Horizontal(id="form_action_buttons", classes="action-bar"):
                yield Button("Start Workflow Run [Ctrl+Enter]", variant="primary", id="btn_submit_run")
                yield Button("Reset Form", variant="default", id="btn_reset_run")
                yield Button("Cancel [Esc]", variant="error", id="btn_cancel_run")

    def on_mount(self) -> None:
        self.populate_options()
        self.apply_prefills()

    def on_screen_resume(self) -> None:
        self.apply_prefills()

    def populate_options(self) -> None:
        """Populates project select (excluding Body.me) and workflows from disk."""
        cfg = load_config()

        # 1. Active Projects strictly excluding Body.me App
        active_projects = get_active_projects(cfg)
        proj_options: List[Tuple[str, str]] = []
        for name in sorted(active_projects.keys()):
            proj_options.append((name, name))
        if not proj_options:
            proj_options = [("General", "General"), ("Sample Math", "Sample Math")]
        
        sel_proj = self.query_one("#sel_project", Select)
        sel_proj.set_options(proj_options)
        if proj_options:
            sel_proj.value = proj_options[0][1]

        # 2. Workflows from workflows/*.yaml
        root_dir = Path(__file__).resolve().parents[4]
        wf_dir = root_dir / "workflows"
        wf_options: List[Tuple[str, str]] = []
        if wf_dir.is_dir():
            for f in sorted(wf_dir.glob("*.yaml")):
                wf_options.append((f.stem.replace("_", " ").title(), f.stem))
        if not wf_options:
            wf_options = [
                ("Four Step Pipeline", "four_step_pipeline"),
                ("Feature And Reviewer", "feature_and_reviewer"),
                ("Escalate On Fail", "escalate_on_fail"),
                ("Compare", "compare"),
                ("Plan Only", "plan_only"),
            ]
        sel_wf = self.query_one("#sel_workflow", Select)
        sel_wf.set_options(wf_options)
        sel_wf.value = "four_step_pipeline"

        # 3. Presets
        presets_data = cfg.get("presets", {})
        preset_opts: List[Tuple[str, str]] = [("None (Use Workflow Default)", "")]
        for k, v in presets_data.items():
            preset_opts.append((f"{v.get('name', k)} [{k}]", k))
        if len(preset_opts) == 1:
            preset_opts.extend([
                ("Frontier Leaders", "frontier"),
                ("Value Leaders", "value_leader"),
                ("SOTA", "sota"),
                ("Cost Optimal", "cost_optimal"),
                ("Free Tier", "free_tier"),
            ])
        self.query_one("#sel_preset", Select).set_options(preset_opts)

        # Set dry run default from app
        if hasattr(self.app, "default_dry_run"):
            self.query_one("#sw_dry_run", Switch).value = getattr(self.app, "default_dry_run", True)

    def apply_prefills(self) -> None:
        """Applies prefilled values passed from ObsidianBrowser or other screens."""
        if hasattr(self.app, "prefill_task") and self.app.prefill_task:
            self.query_one("#txt_task_prompt", TextArea).text = self.app.prefill_task
            self.app.prefill_task = None
        if hasattr(self.app, "prefill_project") and self.app.prefill_project:
            try:
                self.query_one("#sel_project", Select).value = self.app.prefill_project
            except Exception:
                pass
            self.app.prefill_project = None
        if hasattr(self.app, "prefill_workflow") and self.app.prefill_workflow:
            try:
                self.query_one("#sel_workflow", Select).value = self.app.prefill_workflow
            except Exception:
                pass

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "sw_dry_run":
            pill = self.query_one("#lbl_cost_estimate", Static)
            if event.value:
                pill.update("Est: ~18,500 tokens | ~$0.00 USD (Simulation)")
            else:
                pill.update("Est: ~18,500 tokens | ~$0.042 USD (Live API)")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_submit_run":
            self.action_submit()
        elif btn_id == "btn_reset_run":
            self.action_reset()
        elif btn_id == "btn_cancel_run":
            self.action_cancel()

    def action_submit(self) -> None:
        """Validates inputs, launches run via RunManager, and switches to LiveRunScreen."""
        task_text = self.query_one("#txt_task_prompt", TextArea).text.strip()
        if not task_text:
            task_text = "Standard execution task"

        sel_project = self.query_one("#sel_project", Select)
        project_val = sel_project.value if (isinstance(sel_project.value, str) and sel_project.value.strip()) else "Sample Math"

        sel_wf = self.query_one("#sel_workflow", Select)
        wf_val = sel_wf.value if (isinstance(sel_wf.value, str) and sel_wf.value.strip()) else "four_step_pipeline"

        dry_run = self.query_one("#sw_dry_run", Switch).value
        override_model = self.query_one("#inp_model_override", Input).value.strip() or None
        sel_preset = self.query_one("#sel_preset", Select).value
        preset_val = sel_preset if (isinstance(sel_preset, str) and sel_preset.strip()) else None

        local_research = self.query_one("#chk_local_research", Checkbox).value
        find_research = self.query_one("#chk_find_research", Checkbox).value

        rm = getattr(self.app, "run_manager", None)
        if rm:
            new_run = rm.create_run(
                task=task_text,
                project=str(project_val),
                workflow_id=str(wf_val),
                dry_run=dry_run,
                model_override=override_model,
                preset=preset_val,
                local_research=local_research,
                find_research=find_research
            )
            rm.start_run(new_run.run_id)
            self.app.active_run_id = new_run.run_id

            # Dispatch workflow execution in background worker if available
            if hasattr(self.app, "dispatch_workflow_run"):
                self.app.dispatch_workflow_run(new_run.run_id, dry_run=dry_run)

        self.app.switch_screen("live_run")

    def action_reset(self) -> None:
        self.query_one("#txt_task_prompt", TextArea).text = ""
        self.query_one("#inp_model_override", Input).value = ""
        self.query_one("#sw_dry_run", Switch).value = True
        self.query_one("#chk_local_research", Checkbox).value = True
        self.query_one("#chk_find_research", Checkbox).value = False

    def action_cancel(self) -> None:
        self.app.switch_screen("dashboard")
