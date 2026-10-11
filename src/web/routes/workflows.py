"""
src/web/routes/workflows.py
REST API endpoints for listing, reading, and saving DAG workflow templates (F36, F38).
Preserves YAML round-trip formatting and updates visual canvas coordinates.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.engine.workflow_parser import WorkflowParser, WorkflowSchemaError, WorkflowDAGError
from src.web.security import redact_data

router = APIRouter(prefix="/api/workflows", tags=["workflows"])
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
WORKFLOWS_DIR = ROOT_DIR / "workflows"


class SaveWorkflowRequest(BaseModel):
    filename: str
    yaml_content: str
    canvas_layout: Optional[Dict[str, Any]] = None


class CanvasUpdateRequest(BaseModel):
    node_positions: Dict[str, Dict[str, float]]
    viewport: Optional[Dict[str, float]] = None


@router.get("")
def list_workflows():
    """Lists all available workflow YAML templates in workflows/."""
    parser = WorkflowParser()
    templates = []
    
    if WORKFLOWS_DIR.is_dir():
        for file in sorted(WORKFLOWS_DIR.glob("*.yaml")):
            try:
                wf = parser.parse_file(file)
                data = wf.pure_data
                templates.append({
                    "id": file.stem,
                    "filename": file.name,
                    "name": data.get("name", file.stem),
                    "description": data.get("description", ""),
                    "step_count": len(data.get("steps", [])),
                    "execution_order": wf.execution_order,
                    "execution_tiers": wf.execution_tiers,
                })
            except Exception as e:
                templates.append({
                    "id": file.stem,
                    "filename": file.name,
                    "name": file.stem,
                    "description": f"Failed to parse: {e}",
                    "error": str(e)
                })

    return redact_data({"workflows": templates})


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str):
    """Retrieves full YAML content, pure parsed JSON, and execution tiers for a workflow."""
    parser = WorkflowParser()
    filename = f"{workflow_id}.yaml" if not workflow_id.endswith(".yaml") else workflow_id
    wf_file = WORKFLOWS_DIR / filename
    
    if not wf_file.is_file():
        raise HTTPException(status_code=404, detail=f"Workflow template '{filename}' not found")

    try:
        wf = parser.parse_file(wf_file)
        with open(wf_file, "r", encoding="utf-8") as f:
            raw_yaml = f.read()

        return redact_data({
            "id": wf_file.stem,
            "filename": wf_file.name,
            "yaml": raw_yaml,
            "definition": wf.pure_data,
            "execution_order": wf.execution_order,
            "execution_tiers": wf.execution_tiers
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error parsing workflow: {e}")


@router.post("")
def save_workflow(req: SaveWorkflowRequest):
    """Validates and saves a workflow YAML file, round-trip preserving layout."""
    parser = WorkflowParser()
    filename = req.filename if req.filename.endswith(".yaml") else f"{req.filename}.yaml"
    target_path = WORKFLOWS_DIR / filename

    try:
        wf = parser.parse_string(req.yaml_content, source_name=filename)
        
        # If canvas layout was provided, update coordinates
        if req.canvas_layout:
            node_pos = req.canvas_layout.get("node_positions", {})
            viewport = req.canvas_layout.get("viewport")
            parser.update_canvas_coordinates(wf.raw_data, node_pos, viewport=viewport)

        parser.dump_file(wf.raw_data, target_path)
        
        return redact_data({
            "success": True,
            "filename": filename,
            "definition": wf.pure_data,
            "execution_order": wf.execution_order
        })
    except (WorkflowSchemaError, WorkflowDAGError) as e:
        raise HTTPException(status_code=422, detail=f"Validation failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{workflow_id}/layout")
def update_workflow_layout(workflow_id: str, req: CanvasUpdateRequest):
    """Updates only node coordinates and viewport in the workflow YAML preserving comments."""
    parser = WorkflowParser()
    filename = f"{workflow_id}.yaml" if not workflow_id.endswith(".yaml") else workflow_id
    wf_file = WORKFLOWS_DIR / filename

    if not wf_file.is_file():
        raise HTTPException(status_code=404, detail=f"Workflow template '{filename}' not found")

    try:
        wf = parser.parse_file(wf_file)
        parser.update_canvas_coordinates(wf.raw_data, req.node_positions, viewport=req.viewport)
        parser.dump_file(wf.raw_data, wf_file)
        return {"success": True, "message": "Canvas coordinates updated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
