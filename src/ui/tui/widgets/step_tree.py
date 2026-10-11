"""
src/ui/tui/widgets/step_tree.py
DAG step tree visualization widget displaying workflow steps and execution state.
"""

from typing import List, Optional, Dict, Any
from textual.widgets import Tree
from textual.widgets.tree import TreeNode
from src.engine.models import StepState, StepStatus


class StepTree(Tree):
    """Tree visualizer for DAG workflow step execution."""

    def __init__(self, label: str = "Workflow Steps", id: str = "tree_dag_steps", **kwargs):
        super().__init__(label, id=id, **kwargs)
        self.show_root = False
        self.guide_depth = 2

    def update_steps(self, steps: List[StepState], current_step_id: Optional[str] = None) -> None:
        """Rerenders tree nodes based on current StepState list."""
        self.clear()
        self.root.expand()

        for step in steps:
            status_icon = self._get_status_icon(step.status)
            model_info = f" ({step.model})" if step.model else ""
            attempts_info = f" [Try {step.attempts}]" if step.attempts > 1 else ""
            label_text = f"{status_icon} {step.name or step.step_id}{model_info}{attempts_info}"

            node = self.root.add(label_text, data={"step_id": step.step_id, "status": step.status})
            if step.error:
                node.add_leaf(f"[red]Error: {step.error}[/]")
            if step.routing_decision:
                node.add_leaf(f"[cyan]Routing: {step.routing_decision.reason}[/]")
            node.expand()

    @staticmethod
    def _get_status_icon(status: StepStatus) -> str:
        icons = {
            StepStatus.COMPLETED: "[green][✅][/]",
            StepStatus.RUNNING: "[cyan][🔄][/]",
            StepStatus.WAITING_GATE: "[yellow][⏸️][/]",
            StepStatus.WAITING_BUDGET: "[red][🛑][/]",
            StepStatus.FAILED: "[red][❌][/]",
            StepStatus.SKIPPED: "[dim][⏭️][/]",
            StepStatus.PENDING: "[dim][⏳][/]",
        }
        return icons.get(status, "[⏳]")
