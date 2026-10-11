"""
src/engine/workflow_parser.py
Round-trip YAML parser, serializer, and validator for Enki DAG Workflows.
Preserves comments, formatting, and canvas coordinates using ruamel.yaml.
Validates schemas using jsonschema with exact line/column context.
Validates DAG integrity (cycles, self/dangling dependencies) and computes Kahn's topological tiers.
"""

import io
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from collections import deque
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
import jsonschema


class WorkflowError(Exception):
    """Base exception for workflow schema and parsing errors."""
    pass


class WorkflowSchemaError(WorkflowError, ValueError):
    """Raised when workflow fails JSON Schema validation with line/column context."""
    def __init__(self, message: str, line: Optional[int] = None, col: Optional[int] = None, path: Optional[str] = None):
        super().__init__(message)
        self.line = line
        self.col = col
        self.path = path


class WorkflowDAGError(WorkflowError, ValueError):
    """Raised when workflow step dependencies contain cycles or invalid references."""
    pass


def _to_pure_python(obj: Any) -> Any:
    """Recursively converts ruamel.yaml CommentedMap/Seq to standard python dict/list."""
    if isinstance(obj, dict):
        return {k: _to_pure_python(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_to_pure_python(v) for v in obj]
    return obj


def _extract_line_col(ast: Any, json_path: List[Union[str, int]]) -> Tuple[int, int]:
    """Walks the ruamel.yaml AST along json_path to locate line and column numbers (1-indexed)."""
    line, col = 1, 1
    curr = ast
    for part in json_path:
        if isinstance(part, str):
            if hasattr(curr, 'lc') and hasattr(curr.lc, 'key'):
                lc = curr.lc.key(part)
                if lc:
                    line, col = lc[0] + 1, lc[1] + 1
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
        elif isinstance(part, int):
            if hasattr(curr, 'lc') and hasattr(curr.lc, 'item'):
                lc = curr.lc.item(part)
                if lc:
                    line, col = lc[0] + 1, lc[1] + 1
            if isinstance(curr, list) and 0 <= part < len(curr):
                curr = curr[part]
    return line, col


def detect_cycle_and_sort(steps: List[Dict[str, Any]]) -> Tuple[List[str], List[List[str]]]:
    """
    Validates DAG integrity and computes execution order and parallel execution tiers via Kahn's algorithm:
    1. Ensures unique step IDs.
    2. Detects self-dependencies and dangling dependencies.
    3. Detects cycles using 3-state DFS and provides the exact cycle chain.
    4. Computes topological execution order and parallel tiers.
    """
    seen_ids = set()
    for step in steps:
        s_id = step.get("id")
        if not s_id:
            raise WorkflowDAGError("Step missing required 'id' attribute")
        if s_id in seen_ids:
            raise WorkflowDAGError(f"Duplicate step ID: Step '{s_id}' is defined multiple times")
        seen_ids.add(s_id)

    all_nodes = set(seen_ids)
    adj: Dict[str, List[str]] = {}
    for step in steps:
        s_id = step["id"]
        deps = step.get("dependencies", []) or []
        adj[s_id] = list(deps)

    # Self and dangling dependency checks
    for s_id, deps in adj.items():
        for d in deps:
            if d == s_id:
                raise WorkflowDAGError(f'Self dependency: Step "{s_id}" cannot depend on itself')
            if d not in all_nodes:
                raise WorkflowDAGError(f'Dangling dependency: Step "{s_id}" depends on non-existent step "{d}"')

    # Cycle detection via DFS with 3 states (0=unvisited, 1=visiting, 2=visited)
    state = {n: 0 for n in all_nodes}
    path = []

    def dfs(node: str) -> None:
        state[node] = 1
        path.append(node)
        for dep in adj[node]:
            if state[dep] == 1:
                cycle_start = path.index(dep)
                cycle_str = " -> ".join(path[cycle_start:] + [dep])
                raise WorkflowDAGError(f"Cycle detected in workflow: {cycle_str}")
            if state[dep] == 0:
                dfs(dep)
        path.pop()
        state[node] = 2

    for n in sorted(all_nodes):
        if state[n] == 0:
            dfs(n)

    # Kahn's algorithm for topological sorting and parallel tier computation
    in_degree = {n: 0 for n in all_nodes}
    dependents = {n: [] for n in all_nodes}
    for b, deps in adj.items():
        in_degree[b] = len(deps)
        for a in deps:
            dependents[a].append(b)

    queue = deque([n for n in all_nodes if in_degree[n] == 0])
    order: List[str] = []
    tiers: List[List[str]] = []

    while queue:
        current_tier: List[str] = []
        for _ in range(len(queue)):
            node = queue.popleft()
            current_tier.append(node)
            order.append(node)
            for dep in dependents[node]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)
        tiers.append(current_tier)

    if len(order) != len(all_nodes):
        raise WorkflowDAGError("Failed to order all steps (unresolved dependencies or cycle)")

    return order, tiers


class WorkflowDefinition:
    """In-memory representation of an Enki DAG workflow definition."""
    def __init__(
        self,
        raw_data: CommentedMap,
        pure_data: Dict[str, Any],
        execution_order: List[str],
        execution_tiers: List[List[str]],
        source_name: str = "<string>",
        source_path: Optional[Path] = None,
    ):
        self.raw_data = raw_data
        self.pure_data = pure_data
        self.execution_order = execution_order
        self.execution_tiers = execution_tiers
        self.source_name = source_name
        self.source_path = source_path

        self.id: str = pure_data["id"]
        self.name: str = pure_data["name"]
        self.description: Optional[str] = pure_data.get("description")
        self.version: Optional[str] = pure_data.get("version")
        self.author: Optional[str] = pure_data.get("author")
        self.canvas: Optional[Dict[str, Any]] = pure_data.get("canvas")
        self.parameters: Dict[str, Any] = pure_data.get("parameters", {})
        self.steps: List[Dict[str, Any]] = pure_data.get("steps", [])
        self.steps_by_id: Dict[str, Dict[str, Any]] = {s["id"]: s for s in self.steps}

    def get_step(self, step_id: str) -> Optional[Dict[str, Any]]:
        return self.steps_by_id.get(step_id)

    def __repr__(self) -> str:
        return f"<WorkflowDefinition id={self.id!r} steps={len(self.steps)} tiers={len(self.execution_tiers)}>"


class WorkflowParser:
    """Round-trip YAML parser and validator for Enki workflows."""
    def __init__(self, schema_path: Optional[Union[str, Path]] = None):
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.indent(mapping=2, sequence=4, offset=2)

        if schema_path is None:
            # Walk up to find schemas/workflow.schema.json
            current_path = Path(__file__).resolve()
            candidate = current_path.parent
            while candidate.parent != candidate and not (candidate / "schemas" / "workflow.schema.json").is_file():
                candidate = candidate.parent
            schema_path = candidate / "schemas" / "workflow.schema.json"
        self.schema_path = Path(schema_path) if schema_path else None
        self._schema_data: Optional[Dict[str, Any]] = None

    def _get_schema(self) -> Dict[str, Any]:
        if self._schema_data is not None:
            return self._schema_data
        if self.schema_path and self.schema_path.is_file():
            with open(self.schema_path, "r", encoding="utf-8") as f:
                self._schema_data = json.load(f)
                return self._schema_data
        raise FileNotFoundError(f"Workflow schema not found at {self.schema_path}")

    def validate_schema(self, pure_data: Dict[str, Any], ast: Any = None, source_name: str = "<string>") -> None:
        """Validates pure_data against workflow.schema.json and formats exact line/col errors."""
        schema = self._get_schema()
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(pure_data))
        if errors:
            first_err = errors[0]
            path_list = list(first_err.path)
            line, col = (1, 1)
            if ast is not None:
                line, col = _extract_line_col(ast, path_list)
            path_str = ".".join(str(p) for p in path_list) if path_list else "root"
            msg = f"Schema validation error in {source_name}:{line}:{col} at '{path_str}': {first_err.message}"
            raise WorkflowSchemaError(msg, line=line, col=col, path=path_str)

    def validate_dag(self, steps: List[Dict[str, Any]]) -> Tuple[List[str], List[List[str]]]:
        """Validates DAG integrity using detect_cycle_and_sort."""
        return detect_cycle_and_sort(steps)

    def load_yaml(self, yaml_text: str) -> CommentedMap:
        """Loads YAML text into a CommentedMap AST preserving comments and flow."""
        loaded = self._yaml.load(yaml_text)
        if not isinstance(loaded, CommentedMap) and not isinstance(loaded, dict):
            raise WorkflowSchemaError("Workflow content must be a YAML mapping/object")
        return loaded

    def parse_string(self, yaml_text: str, source_name: str = "<string>") -> WorkflowDefinition:
        """Parses a YAML string into a validated WorkflowDefinition."""
        ast = self.load_yaml(yaml_text)
        pure_data = _to_pure_python(ast)
        self.validate_schema(pure_data, ast, source_name)
        order, tiers = self.validate_dag(pure_data.get("steps", []))
        return WorkflowDefinition(
            raw_data=ast,
            pure_data=pure_data,
            execution_order=order,
            execution_tiers=tiers,
            source_name=source_name,
        )

    def parse_file(self, file_path: Union[str, Path]) -> WorkflowDefinition:
        """Loads and parses a workflow YAML file from disk."""
        p = Path(file_path)
        if not p.is_file():
            raise FileNotFoundError(f"Workflow file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        wf = self.parse_string(content, source_name=p.name)
        wf.source_path = p
        return wf

    def load_file(self, file_path: Union[str, Path]) -> WorkflowDefinition:
        """Alias for parse_file."""
        return self.parse_file(file_path)

    def dump_string(self, raw_data: Union[CommentedMap, WorkflowDefinition]) -> str:
        """Serializes CommentedMap or WorkflowDefinition back to YAML string, preserving comments."""
        ast = raw_data.raw_data if isinstance(raw_data, WorkflowDefinition) else raw_data
        stream = io.StringIO()
        self._yaml.dump(ast, stream)
        return stream.getvalue()

    def dump_yaml(self, raw_data: Union[CommentedMap, WorkflowDefinition]) -> str:
        """Alias for dump_string."""
        return self.dump_string(raw_data)

    def dump_file(self, raw_data: Union[CommentedMap, WorkflowDefinition], file_path: Union[str, Path]) -> None:
        """Atomically saves CommentedMap back to disk using a temporary file and replace."""
        ast = raw_data.raw_data if isinstance(raw_data, WorkflowDefinition) else raw_data
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp_p = p.with_suffix(".tmp")
        with open(tmp_p, "w", encoding="utf-8") as f:
            self._yaml.dump(ast, f)
        tmp_p.replace(p)

    def update_canvas_coordinates(
        self,
        raw_data: Union[CommentedMap, WorkflowDefinition],
        node_positions: Dict[str, Dict[str, float]],
        viewport: Optional[Dict[str, float]] = None,
    ) -> Union[CommentedMap, WorkflowDefinition]:
        """
        Updates canvas layout in-place on CommentedMap or WorkflowDefinition AST while preserving comments.
        Accepts node positions: { step_id: { 'x': 100.0, 'y': 200.0 } }.
        """
        ast = raw_data.raw_data if isinstance(raw_data, WorkflowDefinition) else raw_data

        if "canvas" not in ast or ast["canvas"] is None:
            ast["canvas"] = CommentedMap()
        if viewport:
            if "viewport" not in ast["canvas"] or ast["canvas"]["viewport"] is None:
                ast["canvas"]["viewport"] = CommentedMap()
            ast["canvas"]["viewport"]["x"] = float(viewport.get("x", 0.0))
            ast["canvas"]["viewport"]["y"] = float(viewport.get("y", 0.0))
            ast["canvas"]["viewport"]["zoom"] = float(viewport.get("zoom", 1.0))
        if "nodes" not in ast["canvas"] or ast["canvas"]["nodes"] is None:
            ast["canvas"]["nodes"] = CommentedMap()

        for step_id, pos in node_positions.items():
            if step_id not in ast["canvas"]["nodes"] or ast["canvas"]["nodes"][step_id] is None:
                ast["canvas"]["nodes"][step_id] = CommentedMap()
            ast["canvas"]["nodes"][step_id]["x"] = float(pos["x"])
            ast["canvas"]["nodes"][step_id]["y"] = float(pos["y"])

        if isinstance(raw_data, WorkflowDefinition):
            raw_data.pure_data = _to_pure_python(ast)
            raw_data.canvas = raw_data.pure_data.get("canvas")

        return raw_data


# Convenience module-level API
_DEFAULT_PARSER: Optional[WorkflowParser] = None

def get_default_parser() -> WorkflowParser:
    global _DEFAULT_PARSER
    if _DEFAULT_PARSER is None:
        _DEFAULT_PARSER = WorkflowParser()
    return _DEFAULT_PARSER

def load_workflow(file_path: Union[str, Path]) -> WorkflowDefinition:
    return get_default_parser().parse_file(file_path)

def parse_workflow(yaml_text: str, source_name: str = "<string>") -> WorkflowDefinition:
    return get_default_parser().parse_string(yaml_text, source_name)

def save_workflow(workflow_def: Union[WorkflowDefinition, CommentedMap], file_path: Union[str, Path]) -> None:
    get_default_parser().dump_file(workflow_def, file_path)
