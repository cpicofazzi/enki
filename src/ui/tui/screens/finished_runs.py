"""
src/ui/tui/screens/finished_runs.py
Screen 10: FinishedRunsScreen (Feature F32)
Completed run worktrees, git diff inspector, and teardown choices (Merge, Keep, Discard).
"""

from pathlib import Path
from typing import Optional, Dict, Any, List
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Label, Static, DataTable, TextArea, Input, Button
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding

from src.ui.tui.widgets.header_bar import HeaderBar
from src.ui.tui.modals.confirm_modal import ConfirmModal
from src.engine.models import RunStatus, WorktreeAction
from src.config import resolve_project_repo_path


class FinishedRunsScreen(Screen):
    """Screen 10: Finished run worktrees, diff inspection, and teardown choices."""

    BINDINGS = [
        Binding("escape", "back", "Back", priority=False),
        Binding("m", "merge", "Merge", priority=False),
        Binding("k", "keep", "Keep", priority=False),
        Binding("d", "discard", "Discard", priority=False),
        Binding("x", "delete_run", "Delete Run", priority=False),
        Binding("r", "refresh", "Refresh", priority=False),
    ]

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="screen_finished_runs"):
            with Container(id="worktrees_table_pane", classes="card"):
                yield Label("COMPLETED RUN WORKTREE BRANCHES (enki/run/<run_id>)", classes="section-title")
                yield DataTable(id="tbl_worktrees")

            with Container(id="diff_inspector_pane", classes="card"):
                with Horizontal():
                    yield Label("GIT DIFF INSPECTOR", classes="section-title")
                    yield Static("0 files changed, +0 lines, -0 lines", id="lbl_diff_stats")
                yield TextArea(
                    "# Select a worktree branch above to inspect git diff",
                    read_only=True,
                    language="markdown",
                    id="txt_diff_view",
                    tab_behavior="focus"
                )

            with Vertical(id="teardown_actions_pane", classes="action-bar"):
                yield Static(
                    "Enki never merges into your branch without explicit approval.",
                    id="lbl_teardown_warning"
                )
                with Horizontal(id="teardown_controls"):
                    yield Button("Back [Esc]", variant="default", id="btn_back_finished")
                    yield Label("Target Branch:")
                    yield Input(value="main", id="inp_target_branch")
                    yield Button("Merge [M]", variant="success", id="btn_merge_worktree")
                    yield Button("Keep [K]", variant="primary", id="btn_keep_worktree")
                    yield Button("Discard [D]", variant="error", id="btn_discard_worktree")
                    yield Button("Delete Run [X]", variant="error", id="btn_delete_run")

    def on_mount(self) -> None:
        table = self.query_one("#tbl_worktrees", DataTable)
        table.cursor_type = "row"
        table.add_columns("Run ID", "Branch Name", "Project", "Status", "Teardown Status")
        self.refresh_worktrees()

    def on_screen_resume(self) -> None:
        self.refresh_worktrees()

    def refresh_worktrees(self) -> None:
        """Pulls finished runs with worktrees."""
        table = self.query_one("#tbl_worktrees", DataTable)
        table.clear()

        rm = getattr(self.app, "run_manager", None)
        if not rm:
            return

        runs = rm.list_runs(limit=50)
        finished_runs = [r for r in runs if r.status in (RunStatus.COMPLETED, RunStatus.FAILED) or r.branch_name]
        if not finished_runs and runs:
            finished_runs = runs

        for r in finished_runs:
            teardown_status = "Active"
            try:
                full_run = rm.load_run(r.run_id)
                teardown_status = full_run.worktree_action.value.upper()
            except Exception:
                pass

            table.add_row(
                r.run_id,
                r.branch_name or f"enki/run/{r.run_id}",
                r.project,
                r.status.value,
                teardown_status
            )

        if table.row_count > 0:
            first_run_id = finished_runs[0].run_id
            self.display_diff_for_run(first_run_id)

    def _get_selected_run_id(self) -> Optional[str]:
        table = self.query_one("#tbl_worktrees", DataTable)
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            row = table.get_row(row_key)
            return row[0]
        except Exception:
            return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = event.data_table.get_row(event.row_key)
        self.display_diff_for_run(row[0])

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            try:
                row = event.data_table.get_row(event.row_key)
                self.display_diff_for_run(row[0])
            except Exception:
                pass

    def display_diff_for_run(self, run_id: str) -> None:
        rm = getattr(self.app, "run_manager", None)
        wm = getattr(self.app, "worktree_manager", None)
        if not rm or not wm:
            return

        try:
            run = rm.load_run(run_id)
            repo_path_str = run.metadata.get("repo_path")
            if not repo_path_str and run.worktree_path:
                repo_path_str = str(Path(run.worktree_path).parent.parent.parent)
            if not repo_path_str:
                repo_path_str = str(resolve_project_repo_path(run.project))

            repo_path = Path(repo_path_str)
            if repo_path.is_dir():
                diff_obj = wm.get_diff(repo_path, run.run_id, base_branch="main")
                stats_str = f"{diff_obj.files_changed_count} files changed, +{diff_obj.insertions} lines, -{diff_obj.deletions} lines"
                self.query_one("#lbl_diff_stats", Static).update(stats_str)
                diff_text = diff_obj.diff_text or "No modifications detected in worktree."
                self.query_one("#txt_diff_view", TextArea).text = diff_text
            else:
                self.query_one("#txt_diff_view", TextArea).text = "Target repository path not found on disk."
        except Exception as e:
            self.query_one("#txt_diff_view", TextArea).text = f"Error retrieving git diff: {e}"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_merge_worktree":
            self.action_merge()
        elif btn_id == "btn_keep_worktree":
            self.action_keep()
        elif btn_id == "btn_discard_worktree":
            self.action_discard()
        elif btn_id == "btn_delete_run":
            self.action_delete_run()
        elif btn_id == "btn_back_finished":
            self.action_back()

    def action_back(self) -> None:
        self.app.action_back()

    def action_merge(self) -> None:
        run_id = self._get_selected_run_id()
        if not run_id:
            return
        target = self.query_one("#inp_target_branch", Input).value.strip() or "main"
        self.app.push_screen(
            ConfirmModal(
                title=f"Confirm Merge: enki/run/{run_id}",
                message=f"Explicit approval required. This will merge changes into '{target}' and prune the temporary worktree.",
                action="merge",
                run_id=run_id,
                target_branch=target
            ),
            callback=self.on_teardown_confirmed
        )

    def action_keep(self) -> None:
        run_id = self._get_selected_run_id()
        if not run_id:
            return
        self.app.push_screen(
            ConfirmModal(
                title=f"Keep Branch: enki/run/{run_id}",
                message="Retains the Git branch intact, safely unmounting the temporary worktree directory.",
                action="keep",
                run_id=run_id
            ),
            callback=self.on_teardown_confirmed
        )

    def action_discard(self) -> None:
        run_id = self._get_selected_run_id()
        if not run_id:
            return
        self.app.push_screen(
            ConfirmModal(
                title=f"DANGER: Discard Branch enki/run/{run_id}",
                message="WARNING: Permanently deletes the branch and removes all worktree files. This cannot be undone!",
                action="discard",
                run_id=run_id
            ),
            callback=self.on_teardown_confirmed
        )

    def on_teardown_confirmed(self, result: Optional[Dict[str, Any]]) -> None:
        if not result or not result.get("confirmed"):
            return
        action = result.get("action")
        run_id = result.get("run_id")
        target_branch = result.get("target_branch", "main")
        rm = getattr(self.app, "run_manager", None)
        if rm and run_id and action:
            try:
                rm.finish_worktree(run_id, action=action, target_branch=target_branch)
            except Exception:
                pass
        self.refresh_worktrees()

    def action_refresh(self) -> None:
        self.refresh_worktrees()

    def action_delete_run(self) -> None:
        run_id = self._get_selected_run_id()
        if not run_id:
            self.notify("No run selected to delete.", severity="warning")
            return

        def _do_delete(res) -> None:
            if res and res.get("confirmed"):
                rm = getattr(self.app, "run_manager", None)
                if rm:
                    if rm.delete_run(run_id):
                        self.notify(f"Run {run_id} permanently deleted.", severity="information")
                        self.refresh_worktrees()
                        try:
                            self.query_one("#txt_diff_view", TextArea).text = "# Select a worktree branch above to inspect git diff"
                        except Exception:
                            pass
                    else:
                        self.notify(f"Failed to delete {run_id}.", severity="error")

        self.app.push_screen(
            ConfirmModal(
                title=f"Permanently Delete Run {run_id}",
                message="Are you sure you want to delete this run? All artifacts and worktrees will be removed.",
                action="delete",
                run_id=run_id
            ),
            callback=_do_delete
        )
