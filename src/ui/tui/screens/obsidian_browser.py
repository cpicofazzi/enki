"""
src/ui/tui/screens/obsidian_browser.py
Screen 7: ObsidianBrowserScreen (Feature F29)
Obsidian vault explorer across 00_Inbox, 10_Projects, 40_Tasks, 50_Knowledge,
markdown preview, and 'Start Run from Note' action.
"""

import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Label, Static, DataTable, Input, Button, MarkdownViewer
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding

from src.ui.tui.widgets.header_bar import HeaderBar
from src.obsidian_indexer import ObsidianIndexer, parse_frontmatter
from src.config import load_config


class ObsidianBrowserScreen(Screen):
    """Screen 7: Obsidian Vault note browser and task launcher."""

    BINDINGS = [
        Binding("escape", "back", "Back", priority=False),
        Binding("enter", "start_from_note", "Start Run from Note", priority=False),
        Binding("r", "refresh_vault", "Refresh Vault", priority=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.notes_cache: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="screen_obsidian_browser"):
            with Horizontal(id="vault_search_bar", classes="card"):
                yield Input(
                    placeholder="Search Obsidian vault notes (keywords, tasks, projects)...",
                    id="inp_search_vault"
                )

            with Horizontal(id="vault_split_container", classes="split-container"):
                with Vertical(id="vault_notes_list_pane", classes="pane-40 pane-container"):
                    yield Label("VAULT NOTES (pico-vault)", classes="section-title")
                    yield DataTable(id="tbl_vault_notes")

                with Vertical(id="vault_preview_pane", classes="pane-60 pane-container"):
                    yield Label("MARKDOWN PREVIEW", classes="section-title")
                    yield MarkdownViewer(
                        "# Select a Note to Preview\n\nChoose a markdown note from the list.",
                        id="md_note_preview",
                        show_table_of_contents=False
                    )

            with Horizontal(id="vault_action_bar", classes="action-bar"):
                yield Button("Back [Esc]", variant="default", id="btn_back_vault")
                yield Button("Start Run from Note [Enter]", variant="primary", id="btn_start_from_note")
                yield Button("Refresh Vault Index [R]", variant="default", id="btn_refresh_vault")

    def on_mount(self) -> None:
        table = self.query_one("#tbl_vault_notes", DataTable)
        table.cursor_type = "row"
        table.add_columns("Title", "Folder", "Status", "Relative Path")
        self.load_vault_notes()

    def get_vault_path(self) -> Path:
        indexer = getattr(self.app, "obsidian_indexer", None)
        if indexer and hasattr(indexer, "vault_path"):
            return Path(indexer.vault_path)
        cfg = load_config()
        return Path(cfg.get("obsidian", {}).get("vault_path", "C:/Users/Christian Picofazzi/Documents/pico-vault"))

    def load_vault_notes(self, query: str = "") -> None:
        """Indexes markdown notes from vault folders."""
        vault_p = self.get_vault_path()
        self.notes_cache.clear()
        table = self.query_one("#tbl_vault_notes", DataTable)
        table.clear()

        if not vault_p.is_dir():
            table.add_row("(Vault path not found)", "-", "-", str(vault_p))
            return

        q_lower = query.strip().lower()
        for root, _, files in os.walk(vault_p):
            if ".obsidian" in root or ".trash" in root:
                continue
            for f in sorted(files):
                if not f.endswith(".md"):
                    continue
                file_path = Path(root) / f
                try:
                    rel_p = file_path.relative_to(vault_p)
                    folder_name = rel_p.parts[0] if len(rel_p.parts) > 1 else "Root"
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                        content = fp.read()
                    
                    fm = parse_frontmatter(content)
                    title = fm.get("title", file_path.stem.replace("_", " "))
                    status = fm.get("status", "open")

                    if q_lower:
                        if (q_lower not in title.lower() and 
                            q_lower not in content.lower() and 
                            q_lower not in str(rel_p).lower()):
                            continue

                    note_info = {
                        "path": str(file_path),
                        "rel_path": str(rel_p).replace("\\", "/"),
                        "title": title,
                        "folder": folder_name,
                        "status": status,
                        "content": content,
                        "metadata": fm
                    }
                    self.notes_cache.append(note_info)
                    table.add_row(title, folder_name, status, str(rel_p).replace("\\", "/"))
                except Exception:
                    continue

        if self.notes_cache:
            self.display_note_preview(self.notes_cache[0])

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "inp_search_vault":
            self.load_vault_notes(query=event.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self.notes_cache):
            self.display_note_preview(self.notes_cache[idx])

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            table = event.data_table
            idx = event.cursor_row
            if 0 <= idx < len(self.notes_cache):
                self.display_note_preview(self.notes_cache[idx])

    def display_note_preview(self, note_info: Dict[str, Any]) -> None:
        content = note_info.get("content", "")
        viewer = self.query_one("#md_note_preview", MarkdownViewer)
        try:
            viewer.document.update(content)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_start_from_note":
            self.action_start_from_note()
        elif event.button.id == "btn_refresh_vault":
            self.action_refresh_vault()
        elif event.button.id == "btn_back_vault":
            self.action_back()

    def action_back(self) -> None:
        self.app.action_back()

    def action_start_from_note(self) -> None:
        """Extracts task requirements and project from selected note, then launches StartRunScreen."""
        table = self.query_one("#tbl_vault_notes", DataTable)
        idx = table.cursor_coordinate.row if table.row_count > 0 else 0
        if 0 <= idx < len(self.notes_cache):
            note = self.notes_cache[idx]
            title = note.get("title", "")
            fm = note.get("metadata", {})
            project = fm.get("project", "")
            if project:
                project = project.strip("[]'\"")
            
            # Extract checklist items if present
            content = note.get("content", "")
            check_lines = [line.strip() for line in content.splitlines() if line.strip().startswith("- [ ]") or line.strip().startswith("- [x]")]
            prompt = title
            if check_lines:
                prompt += "\n\nRequirements:\n" + "\n".join(check_lines)

            self.app.prefill_task = prompt
            if project:
                self.app.prefill_project = project
        else:
            self.app.prefill_task = "Task from vault note"

        self.app.switch_screen("start_run")

    def action_refresh_vault(self) -> None:
        self.load_vault_notes()
