"""
src/ui/tui/modals/subagent_flow_modal.py
Modal dialog overlay visualizing the execution flow of each subagent
(Hermes, OMP, Supervisor Gate, Reviewer) and where notes & code were processed.
"""

from typing import Optional, Dict, Any, List
from pathlib import Path
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.widgets import Label, Button, Static, DataTable, TextArea
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding

from src.engine.run_manager import RunManager
from src.engine.subagents_flow import extract_subagents_flow


class SubagentFlowModal(ModalScreen[None]):
    """Modal dialog visualizing subagent pipeline flow, notes processed, and code modified."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", priority=True),
        Binding("q", "dismiss_modal", "Close", priority=True),
        Binding("enter", "dismiss_modal", "Close", priority=False),
    ]

    DEFAULT_CSS = """
    SubagentFlowModal #subagent_flow_dialog {
        width: 92%;
        height: 90%;
        background: #0f172a;
        border: solid #38bdf8;
        padding: 1;
    }

    SubagentFlowModal .flow-header-row {
        height: auto;
        margin-bottom: 1;
        border-bottom: solid #1e293b;
        padding-bottom: 1;
    }

    SubagentFlowModal #flow_modal_title {
        color: #38bdf8;
        text-style: bold;
        width: 80%;
    }

    SubagentFlowModal #btn_close_flow_modal {
        width: 20%;
    }

    SubagentFlowModal #subagent_flow_scroll {
        height: 1fr;
    }

    SubagentFlowModal .flow-section-title-1 {
        color: #f59e0b;
        text-style: bold;
        margin-top: 1;
    }

    SubagentFlowModal .flow-section-title-2 {
        color: #38bdf8;
        text-style: bold;
        margin-top: 1;
    }

    SubagentFlowModal .flow-section-title-3 {
        color: #a855f7;
        text-style: bold;
        margin-top: 1;
    }

    SubagentFlowModal #lbl_subagent_pipeline_art {
        background: #020617;
        padding: 1;
        border: solid #1e293b;
        margin-bottom: 1;
    }

    SubagentFlowModal #lbl_notes_boundary_status,
    SubagentFlowModal #lbl_code_location_status {
        color: #94a3b8;
        margin-bottom: 1;
    }

    SubagentFlowModal .flow-subtitle {
        color: #e2e8f0;
        text-style: italic;
    }

    SubagentFlowModal #tbl_flow_notes_read {
        height: 7;
        margin-bottom: 1;
    }

    SubagentFlowModal #tbl_flow_notes_written {
        height: 5;
        margin-bottom: 1;
    }

    SubagentFlowModal #tbl_flow_code_files {
        height: 6;
        margin-bottom: 1;
    }

    SubagentFlowModal .flow-verification-title {
        color: #10b981;
        text-style: bold;
    }

    SubagentFlowModal #lbl_verification_summary {
        background: #020617;
        padding: 1;
        border: solid #1e293b;
        margin-bottom: 1;
    }
    """

    def __init__(self, run_id: str, **kwargs):
        super().__init__(**kwargs)
        self.run_id = run_id
        self.flow_data: Dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="subagent_flow_dialog", classes="modal-dialog"):
            with Horizontal(classes="flow-header-row"):
                yield Label(f"SUBAGENT FLOW & PROCESSED ARTIFACTS: {self.run_id}", id="flow_modal_title", classes="modal-title")
                yield Button("Close [Esc]", variant="error", id="btn_close_flow_modal")

            with ScrollableContainer(id="subagent_flow_scroll"):
                # Subagent Pipeline Flow
                yield Label("1. SUBAGENT EXECUTION PIPELINE FLOW", classes="flow-section-title-1")
                yield Static(id="lbl_subagent_pipeline_art")

                # Notes Processed by Hermes
                yield Label("2. WHERE NOTES HAVE PROCESSED (Hermes - pico-vault)", classes="flow-section-title-2")
                yield Static(id="lbl_notes_boundary_status")
                yield Label("Notes Read & Indexed for Technical Context:", classes="flow-subtitle")
                yield DataTable(id="tbl_flow_notes_read")
                yield Label("Notes Written & Synchronized:", classes="flow-subtitle")
                yield DataTable(id="tbl_flow_notes_written")

                # Code Processed by Oh My Pi
                yield Label("3. WHERE CODE HAS PROCESSED (Oh My Pi - Repository Worktree)", classes="flow-section-title-3")
                yield Static(id="lbl_code_location_status")
                yield Label("Repository Code Files Touched:", classes="flow-subtitle")
                yield DataTable(id="tbl_flow_code_files")
                yield Label("Acceptance Criteria Verification Suite:", classes="flow-verification-title")
                yield Static(id="lbl_verification_summary")

    def on_mount(self) -> None:
        tbl_read = self.query_one("#tbl_flow_notes_read", DataTable)
        tbl_read.cursor_type = "row"
        tbl_read.add_columns("Score", "Vault Note Path", "Title", "Excerpt Preview")

        tbl_written = self.query_one("#tbl_flow_notes_written", DataTable)
        tbl_written.cursor_type = "row"
        tbl_written.add_columns("Subagent", "Target Vault Note", "Action", "Status")

        tbl_code = self.query_one("#tbl_flow_code_files", DataTable)
        tbl_code.cursor_type = "row"
        tbl_code.add_columns("Status", "File Path", "Additions (+)", "Deletions (-)")

        self.load_flow_data()

    def load_flow_data(self) -> None:
        rm = getattr(self.app, "run_manager", None)
        if not rm:
            rm = RunManager()

        try:
            run = rm.load_run(self.run_id)
            self.flow_data = extract_subagents_flow(run)
        except Exception as e:
            self.query_one("#lbl_subagent_pipeline_art", Static).update(f"[red]Error loading flow: {e}[/]")
            return

        # Render Pipeline Art
        stages = self.flow_data.get("subagents_flow", [])
        pipeline_lines = []
        pipeline_art_nodes = []
        for s in stages:
            status_color = "green" if s["status"] == "completed" else ("cyan" if s["status"] == "running" else ("yellow" if "gate" in s["status"] else "white"))
            pipeline_art_nodes.append(f"[{status_color}][{s['order']}. {s['subagent_name']}: {s['step_name']} ({s['status'].upper()})][/]")
        
        flow_chain = "  ==>  ".join(pipeline_art_nodes)
        pipeline_lines.append(f"[bold]{flow_chain}[/]\n")

        for s in stages:
            dur = f"{s['duration_seconds']}s" if s['duration_seconds'] is not None else "-"
            model = s.get("model") or "auto"
            reason = f" ({s['routing_reason']})" if s.get("routing_reason") else ""
            summary = f" | [italic]{s['artifacts_summary']}[/]" if s.get("artifacts_summary") else ""
            pipeline_lines.append(
                f" * [bold cyan]{s['subagent_name']}[/] [{s['subagent_role']}] -> Step: [bold]{s['step_id']}[/] | Status: [{s['status']}] | Model: [yellow]{model}[/]{reason} | Dur: {dur}{summary}"
            )

        self.query_one("#lbl_subagent_pipeline_art", Static).update("\n".join(pipeline_lines))

        # Render Processed Notes
        p_notes = self.flow_data.get("processed_notes", {})
        vault_path = p_notes.get("vault_path", "pico-vault")
        rule_desc = p_notes.get("boundary_rule", "")
        self.query_one("#lbl_notes_boundary_status", Static).update(
            f"Vault Location: [bold green]{vault_path}[/]\n[italic cyan]{rule_desc}[/]"
        )

        tbl_read = self.query_one("#tbl_flow_notes_read", DataTable)
        tbl_read.clear()
        for nr in p_notes.get("notes_read", []):
            tbl_read.add_row(
                str(nr.get("score", 0)),
                nr.get("path", ""),
                nr.get("title", ""),
                (nr.get("excerpt", "")[:60] + "...") if len(nr.get("excerpt", "")) > 60 else nr.get("excerpt", "")
            )

        tbl_written = self.query_one("#tbl_flow_notes_written", DataTable)
        tbl_written.clear()
        for nw in p_notes.get("notes_written", []):
            tbl_written.add_row(
                nw.get("subagent", "Hermes"),
                nw.get("path", ""),
                nw.get("action", ""),
                f"[green]{nw.get('status', '').upper()}[/]"
            )

        # Render Processed Code
        p_code = self.flow_data.get("processed_code", {})
        repo_root = p_code.get("repository_root", "")
        worktree = p_code.get("worktree_path", "")
        branch = p_code.get("branch_name", "")
        stat = p_code.get("stat", {})
        self.query_one("#lbl_code_location_status", Static).update(
            f"Repository: [bold]{repo_root}[/] | Worktree: [cyan]{worktree}[/] | Branch: [bold yellow]{branch}[/]\n"
            f"Total Files Touched: [bold]{stat.get('total_files', 0)}[/] | Additions: [green]+{stat.get('total_additions', 0)}[/] | Deletions: [red]-{stat.get('total_deletions', 0)}[/]"
        )

        tbl_code = self.query_one("#tbl_flow_code_files", DataTable)
        tbl_code.clear()
        for f in stat.get("files", []):
            tbl_code.add_row(
                f.get("status", "M"),
                f.get("path", ""),
                f"+{f.get('additions', 0)}",
                f"-{f.get('deletions', 0)}"
            )

        # Verification summary
        v_info = p_code.get("verification", {})
        v_status = v_info.get("status", "PENDING")
        v_color = "green" if v_status == "PASSED" else ("red" if v_status == "FAILED" else "yellow")
        cmd_str = ", ".join(v_info.get("test_commands", []))
        self.query_one("#lbl_verification_summary", Static).update(
            f"Status: [{v_color} bold]{v_status}[/] | Commands Executed: [cyan]{cmd_str}[/]"
        )

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_close_flow_modal":
            self.action_dismiss_modal()
