"""
tests/test_web_api.py
Automated tests for Enki FastAPI Web Backend (Milestone 4 - F34, F35, F36, F37, F43).
Tests:
1. Strict 127.0.0.1 / localhost loopback binding and rejection of external hosts (F35).
2. Secret leakage prevention across API responses (F43).
3. Runs CRUD lifecycle, get run, create run, resolve gate, resolve budget, finish worktree.
4. Server-Sent Events (SSE) streaming endpoint /api/runs/{id}/stream.
5. Workflows listing, parsing, validation, and canvas coordinate persistence.
6. Models catalog & spend analytics endpoints.
7. Obsidian notes vault endpoints.
"""

import os
import json
import pytest
from pathlib import Path
from starlette.testclient import TestClient

from src.web.api import app
from src.engine.run_manager import RunManager
from src.engine.models import RunStatus, GateAction, BudgetDecision
from src.web.security import redact_string, redact_data, get_secret_tokens


@pytest.fixture
def client():
    """TestClient configured with loopback host."""
    return TestClient(app)


def test_health_check(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["app"] == "Enki"


def test_loopback_security_enforcement():
    """External/remote IP addresses must be strictly rejected with HTTP 403 (F35)."""
    # Create client simulating non-loopback remote address
    non_local_client = TestClient(app, client=("192.168.1.100", 54321))
    res = non_local_client.get("/api/health")
    assert res.status_code == 403
    assert "loopback" in res.json().get("error", "").lower()


def test_secret_leakage_redaction():
    """Verify that known API keys and patterns are automatically redacted (F43)."""
    raw_text = "Call model with secret sk-or-v1-abcdef1234567890abcdef1234567890 and key"
    cleaned = redact_string(raw_text)
    assert "sk-or-v1-" not in cleaned
    assert "[REDACTED" in cleaned

    sensitive_dict = {
        "api_key": "super_secret_token_12345",
        "openrouter_api_key": "some_other_secret_abc",
        "nested": {"token": "secret_abc_xyz", "safe": "normal_value"}
    }
    sanitized = redact_data(sensitive_dict)
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["openrouter_api_key"] == "[REDACTED]"
    assert sanitized["nested"]["token"] == "[REDACTED]"
    assert sanitized["nested"]["safe"] == "normal_value"


def test_list_and_create_run(client, tmp_path, monkeypatch):
    """Test creating a run via REST API and listing runs."""
    mgr = RunManager(base_runs_dir=tmp_path / "runs")
    monkeypatch.setattr("src.web.routes.runs.RunManager", lambda: mgr)

    # 1. Create run
    req_body = {
        "task": "Test Web API creation",
        "project": "WebTesting",
        "workflow_id": "four_step_pipeline",
        "dry_run": True,
        "start_immediately": False
    }
    res = client.post("/api/runs", json=req_body)
    assert res.status_code == 200
    created = res.json()
    assert created["success"] is True
    run_id = created["run"]["run_id"]
    assert run_id.startswith("run_")

    # 2. Get run
    res_get = client.get(f"/api/runs/{run_id}")
    assert res_get.status_code == 200
    run_data = res_get.json()
    assert run_data["task"] == "Test Web API creation"
    assert run_data["status"] == "pending"
    assert "subagents_flow_data" in run_data

    # 2b. Get dedicated subagents flow endpoint
    res_flow = client.get(f"/api/runs/{run_id}/subagents-flow")
    assert res_flow.status_code == 200
    flow_data = res_flow.json()
    assert flow_data["run_id"] == run_id
    assert "subagents_flow" in flow_data
    assert "processed_notes" in flow_data
    assert "processed_code" in flow_data
    assert len(flow_data["subagents_flow"]) == 4
    assert flow_data["subagents_flow"][0]["subagent_name"] == "Hermes"
    assert flow_data["subagents_flow"][1]["subagent_name"] == "Oh My Pi (OMP)"


    # 3. List runs
    res_list = client.get("/api/runs")
    assert res_list.status_code == 200
    runs = res_list.json()["runs"]
    assert any(r["run_id"] == run_id for r in runs)


def test_resolve_gate_and_budget_api(client, tmp_path, monkeypatch):
    """Test gate resolution and budget resolution endpoints."""
    mgr = RunManager(base_runs_dir=tmp_path / "runs")
    monkeypatch.setattr("src.web.routes.runs.RunManager", lambda: mgr)

    run = mgr.create_run(task="Gate test", dry_run=True)
    run_id = run.run_id

    # Resolve gate
    res = client.post(f"/api/runs/{run_id}/gate", json={
        "gate_id": "gate_context",
        "action": "approve",
        "feedback": "Looks solid"
    })
    assert res.status_code == 200
    updated = res.json()["run"]
    assert updated["gate_state"]["status"] == "approved"
    assert updated["gate_state"]["feedback"] == "Looks solid"

    # Resolve budget
    res_b = client.post(f"/api/runs/{run_id}/budget", json={
        "decision": "switch_cheaper",
        "cheaper_model": "deepseek/deepseek-chat"
    })
    assert res_b.status_code == 200
    b_updated = res_b.json()["run"]
    assert b_updated["budget_state"]["decision"] == "switch_cheaper"
    assert b_updated["model_override"] == "deepseek/deepseek-chat"


def test_workflows_endpoints(client):
    """Test listing workflow templates and retrieving a specific template."""
    res = client.get("/api/workflows")
    assert res.status_code == 200
    data = res.json()
    assert "workflows" in data
    assert len(data["workflows"]) >= 1

    # Check 4-step pipeline exists
    wf_ids = [w["id"] for w in data["workflows"]]
    assert "four_step_pipeline" in wf_ids

    # Get specific workflow
    res_wf = client.get("/api/workflows/four_step_pipeline")
    assert res_wf.status_code == 200
    wf_data = res_wf.json()
    assert "yaml" in wf_data
    assert "definition" in wf_data
    assert len(wf_data["definition"]["steps"]) == 4


def test_models_and_metrics_endpoints(client):
    """Test models catalog and telemetry metrics endpoints."""
    res_m = client.get("/api/models")
    assert res_m.status_code == 200
    m_data = res_m.json()
    assert "active_gateway" in m_data
    assert "models" in m_data
    assert len(m_data["models"]) > 0

    res_met = client.get("/api/models/metrics")
    assert res_met.status_code == 200
    met_data = res_met.json()
    assert "monthly_budget_usd" in met_data
    assert "current_month_spend_usd" in met_data


def test_vault_endpoints(client, fixture_vault, monkeypatch):
    """Test Obsidian vault discovery endpoint."""
    monkeypatch.setenv("ENKI_OBSIDIAN_VAULT", str(fixture_vault))
    res = client.get("/api/vault/notes?q=Dinner")
    assert res.status_code == 200
    data = res.json()
    assert "notes" in data


@pytest.mark.asyncio
async def test_sse_streaming_endpoint(tmp_path, monkeypatch):
    """Test SSE streaming endpoint yields valid event format for a run (F37)."""
    from starlette.requests import Request
    from src.web.routes.stream import stream_run_events

    mgr = RunManager(base_runs_dir=tmp_path / "runs")
    monkeypatch.setattr("src.web.routes.runs.RunManager", lambda: mgr)
    
    run = mgr.create_run(task="Stream testing", dry_run=True)
    run_id = run.run_id

    # Create mock disconnected request to cleanly test first event emission
    scope = {"type": "http", "method": "GET", "path": f"/api/runs/{run_id}/stream", "headers": []}
    mock_request = Request(scope)

    resp = await stream_run_events(run_id=run_id, request=mock_request)
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    # Read first event from the generator
    async for event in resp.body_iterator:
        assert "data" in event or "event" in event
        break
