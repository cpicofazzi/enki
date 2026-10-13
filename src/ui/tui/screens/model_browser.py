"""
src/ui/tui/screens/model_browser.py
Screen 6: ModelBrowserScreen (Feature F28)
OpenRouter catalog browser, active Hermes/OMP assignments, and per-project overrides.
"""

from pathlib import Path
import json
from typing import Dict, Optional
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Label, Static, DataTable, Input, Button
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding

from src.ui.tui.widgets.header_bar import HeaderBar
from src.openrouter_catalog import OpenRouterCatalog, ModelCatalogItem
from src.config import load_config, get_active_projects


class ModelBrowserScreen(Screen):
    """Screen 6: AI Model catalog and assignment configuration browser."""

    BINDINGS = [
        Binding("escape", "back", "Back", priority=False),
        Binding("h", "set_hermes", "Set Hermes", priority=False),
        Binding("o", "set_omp", "Set OMP", priority=False),
        Binding("p", "set_project", "Set Project", priority=False),
        Binding("u", "refresh_catalog", "Refresh Catalog", priority=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.catalog_service = OpenRouterCatalog()
        self.cached_models: Dict[str, ModelCatalogItem] = {}

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="screen_model_browser"):
            with Horizontal(id="model_filter_bar", classes="card"):
                yield Input(
                    placeholder="Search models by ID or name (e.g. claude, qwen, flash, gpt)...",
                    id="inp_filter_models"
                )

            with Container(id="catalog_table_container", classes="card"):
                yield Label("OPENROUTER AI MODEL CATALOG", classes="section-title")
                yield DataTable(id="tbl_models_catalog")

            with Horizontal(id="model_config_panels", classes="card"):
                with Vertical(id="panel_active_assignments", classes="pane-50"):
                    yield Label("ACTIVE GATEWAY MODEL ASSIGNMENTS", classes="section-title")
                    yield Static("Active Gateway: OpenRouter", id="active_gw_display")
                    yield Static("Hermes (Context): nousresearch/hermes-3-llama-3.1-70b", id="active_hermes_display")
                    yield Static("OMP (Coding): anthropic/claude-3.5-sonnet", id="active_omp_display")

                with Vertical(id="panel_project_overrides", classes="pane-50"):
                    yield Label("PER-PROJECT OVERRIDES (config/enki.config.json)", classes="section-title")
                    yield DataTable(id="tbl_project_overrides")

            with Horizontal(id="model_action_bar", classes="action-bar"):
                yield Button("Back [Esc]", variant="default", id="btn_back_models")
                yield Button("Set as Hermes Model [H]", variant="primary", id="btn_set_hermes")
                yield Button("Set as OMP Model [O]", variant="success", id="btn_set_omp")
                yield Button("Set for Project [P]", variant="default", id="btn_set_project_model")
                yield Button("Refresh Catalog Cache [U]", variant="default", id="btn_refresh_catalog")

    def on_mount(self) -> None:
        cat_table = self.query_one("#tbl_models_catalog", DataTable)
        cat_table.cursor_type = "row"
        cat_table.add_columns("Model ID", "Display Name", "Prompt / 1M", "Comp / 1M", "Context", "Curated Tier")

        proj_table = self.query_one("#tbl_project_overrides", DataTable)
        proj_table.cursor_type = "row"
        proj_table.add_columns("Project", "OMP Model Override", "Repo Path")

        self.refresh_catalog_data()
        self.refresh_assignments_display()

    def refresh_catalog_data(self, filter_text: str = "") -> None:
        """Loads catalog items into DataTable, applying optional substring filter."""
        cat_svc = getattr(self.app, "catalog", self.catalog_service)
        try:
            self.cached_models = cat_svc.get_catalog()
        except Exception:
            self.cached_models = cat_svc.get_builtin_fallback_models()

        table = self.query_one("#tbl_models_catalog", DataTable)
        table.clear()

        query = filter_text.strip().lower()
        for m_id, item in sorted(self.cached_models.items(), key=lambda x: (not x[1].is_curated, x[0])):
            if query and query not in m_id.lower() and query not in item.name.lower():
                continue
            p_price = f"${item.pricing.prompt_per_1m:.3f}" if item.pricing else "$0.000"
            c_price = f"${item.pricing.completion_per_1m:.3f}" if item.pricing else "$0.000"
            tier = item.curated_tier or ("Curated" if item.is_curated else "Standard")
            table.add_row(
                item.id,
                item.name,
                p_price,
                c_price,
                f"{item.context_length:,}",
                tier
            )

    def refresh_assignments_display(self) -> None:
        """Pulls active model configuration and per-project overrides."""
        cfg = load_config()
        active_gw = cfg.get("active_gateway", "openrouter")
        gw_info = cfg.get("gateways", {}).get(active_gw, {})
        has_key = bool(gw_info.get("api_key"))

        self.query_one("#active_gw_display", Static).update(
            f"Active Gateway: {gw_info.get('name', active_gw)} [{'Live' if has_key else 'Simulation'}]"
        )
        self.query_one("#active_hermes_display", Static).update(
            f"Hermes (Context): {gw_info.get('hermes_model', 'Auto')}"
        )
        self.query_one("#active_omp_display", Static).update(
            f"OMP (Coding): {gw_info.get('omp_model', 'Auto')}"
        )

        proj_table = self.query_one("#tbl_project_overrides", DataTable)
        proj_table.clear()
        active_projects = get_active_projects(cfg)
        for p_name, p_cfg in active_projects.items():
            proj_table.add_row(
                p_name,
                p_cfg.get("omp_model", "(Default)"),
                p_cfg.get("repo_path", "")
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "inp_filter_models":
            self.refresh_catalog_data(filter_text=event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_set_hermes":
            self.action_set_hermes()
        elif btn_id == "btn_set_omp":
            self.action_set_omp()
        elif btn_id == "btn_set_project_model":
            self.action_set_project()
        elif btn_id == "btn_refresh_catalog":
            self.action_refresh_catalog()
        elif btn_id == "btn_back_models":
            self.action_back()

    def action_back(self) -> None:
        self.app.action_back()

    def _get_selected_model_id(self) -> Optional[str]:
        table = self.query_one("#tbl_models_catalog", DataTable)
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            row = table.get_row(row_key)
            return row[0]
        except Exception:
            return None

    def action_set_hermes(self) -> None:
        m_id = self._get_selected_model_id()
        if not m_id:
            return
        root_dir = Path(__file__).resolve().parents[4]
        cfg_file = root_dir / "config" / "enki.config.json"
        if cfg_file.is_file():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                active_gw = data.get("active_gateway", "openrouter")
                data.setdefault("gateways", {}).setdefault(active_gw, {})["hermes_model"] = m_id
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
        self.refresh_assignments_display()

    def action_set_omp(self) -> None:
        m_id = self._get_selected_model_id()
        if not m_id:
            return
        root_dir = Path(__file__).resolve().parents[4]
        cfg_file = root_dir / "config" / "enki.config.json"
        if cfg_file.is_file():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                active_gw = data.get("active_gateway", "openrouter")
                data.setdefault("gateways", {}).setdefault(active_gw, {})["omp_model"] = m_id
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
        self.refresh_assignments_display()

    def action_set_project(self) -> None:
        m_id = self._get_selected_model_id()
        if not m_id:
            return
        proj_table = self.query_one("#tbl_project_overrides", DataTable)
        try:
            row_key, _ = proj_table.coordinate_to_cell_key(proj_table.cursor_coordinate)
            row = proj_table.get_row(row_key)
            p_name = row[0]
            root_dir = Path(__file__).resolve().parents[4]
            cfg_file = root_dir / "config" / "enki.config.json"
            if cfg_file.is_file():
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data.setdefault("projects", {}).setdefault(p_name, {})["omp_model"] = m_id
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
        except Exception:
            pass
        self.refresh_assignments_display()

    def action_refresh_catalog(self) -> None:
        cat_svc = getattr(self.app, "catalog", self.catalog_service)
        try:
            self.cached_models = cat_svc.get_catalog(force_refresh=True)
        except Exception:
            pass
        self.refresh_catalog_data()
