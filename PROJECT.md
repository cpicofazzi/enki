# Project: Enki Dual-Agent UI & Multi-Model Workflow Engine

## Architecture

Enki coordinates two specialized agents:
- **Hermes**: Knowledge & context agent reading Obsidian vault (`pico-vault`) and producing structured task specifications (`context_payload.json`). Never writes production code.
- **Oh My Pi (OMP)**: Terminal coding agent implementing specifications in target repositories and running test suites. Runs in ephemeral sessions (`--no-session`, `--config <overlay.yml>`) without mutating global user configs.

### System Layers
1. **Presentation Layer**:
   - Existing CLI subcommands (`enki.py run`, `context`, `handshake`, `verify`, `sync`, `gateway`, `models`, `monitor`, `status`, `image`).
   - Terminal UI (`py enki.py tui`): Pure Textual 10-screen keyboard-driven application.
   - Local Web UI (`py enki.py serve`): FastAPI backend strictly bound to `127.0.0.1` + React/Vite frontend with visual DAG builder (React Flow), live run graph, SSE log streaming, diff viewer, and spend charts.
2. **Orchestration & Workflow Layer**:
   - `src/engine/workflow_engine.py`: DAG executor supporting step dependencies, auto-routing via `task_profiles`, retry/escalate policies, reviewer feedback loops, fan-out compare, and approval gates.
   - `src/engine/workflow_parser.py`: YAML serializer/parser conforming to `schemas/workflow.schema.json` with round-trip canvas positioning.
   - Built-in templates in `workflows/` (`four_step_pipeline.yaml`, `feature_and_reviewer.yaml`, `escalate_on_fail.yaml`, `compare.yaml`, `plan_only.yaml`).
3. **Execution Engine & Isolation Layer**:
   - `src/engine/run_manager.py`: Run lifecycle management, storage under `data/runs/<run_id>/`, replay and resume from failed steps.
   - `src/engine/worktree_manager.py`: Git worktree creation (`enki/run/<run_id>`) and user-approved Merge / Keep / Discard lifecycle.
   - `src/omp_bridge.py`: Streaming non-blocking execution via `subprocess.Popen` / async pipes with ndjson event parsing.
   - `src/engine/events.py`: Typed pub/sub event bus decoupling engine from CLI, TUI, and Web SSE.
4. **Safety & Financial Guard Layer**:
   - `src/engine/budget_guard.py`: Real-time intercept before model calls when monthly spend reaches `telemetry.monthly_budget_usd` ($25.00), offering 3 user choices (continue, pause, switch cheaper model).
   - `src/engine/vault_guard.py`: Cross-process file locking for Obsidian vault writes, atomic temp-and-rename updates, per-run cost isolation in `01_Dashboard/Enki_Activity_Log.md` and task note checklists.
   - `src/openrouter_catalog.py`: 24h caching of OpenRouter 450+ model catalog and merging with curated config presets.

---

## Feature Inventory

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Typed Event Bus | Decouples engine execution from interfaces (`RunEvent`, `LogChunkEvent`, `GateEvent`, etc.) | M1 | Survey |
| F2 | Backward-Compatible CLI Facade | `EnkiOrchestrator` wraps engine; all existing subcommands keep working | M1 | Survey |
| F3 | Git Worktree Isolation | Isolated branch `enki/run/<run_id>` and worktree per run | M1 | Survey |
| F4 | Worktree Teardown Choices | User choices: Merge (approved only), Keep, Discard | M1 | Survey |
| F5 | Streaming OMP & Tests | Non-blocking stdout/stderr streaming via ndjson / pipes | M1 | Survey |
| F6 | Verifier Retry Feedback Loop | Test failures fed back to OMP until tests pass or retry limit | M1 | Survey |
| F7 | Resumable Run Persistence | Storage in `data/runs/<run_id>/`, replay/resume from failed step | M1 | Survey |
| F8 | Per-Run Cost Telemetry | Exact task-scoped cost derivation (fixes 30-day sum bug) | M1 | Survey |
| F9 | Dry-Run Simulation Mode | End-to-end execution with mock LLM/OMP without real spend | M1 | Survey |
| F10 | Fix `cmd_gateway` CLI Bug | Bare `enki gateway` outputs active and available gateways | M1 | Survey |
| F11 | Project `repo_path` Config | Config extended with explicit repository paths | M1 | Survey |
| F12 | Workflows YAML Schema & Parser | Schema `schemas/workflow.schema.json` and round-trip YAML parser | M2 | Survey |
| F13 | DAG Workflow Execution Engine | Executes dependency graphs across step types | M2 | Survey |
| F14 | Auto-Routing per Step | Model chosen by task type/complexity using `task_profiles` with reasoning | M2 | Survey |
| F15 | Retry & Escalate Policy | Auto-switch to stronger frontier model after repeated failures | M2 | Survey |
| F16 | Reviewer Model Loop | Reviewer model loops back to coder on requested changes | M2 | Survey |
| F17 | Fan-Out / Compare Engine | Multi-model parallel branches, diff comparison, winner selection | M2 | Survey |
| F18 | Approval Gates | Interactive gates (`post_context`, `pre_code`) with 4 actions | M2 | Survey |
| F19 | 5 Built-in Workflow Templates | 4-step, feature+reviewer, escalate-on-fail, compare, plan-only | M2 | Survey |
| F20 | OpenRouter Catalog Service | 24h caching in `data/openrouter_models_cache.json`, merged with config | M2 | Survey |
| F21 | TUI Command & Architecture | `py enki.py tui` pure Textual application without web daemon | M3 | Survey |
| F22 | Full Keyboard Navigation | Keybindings for all screens, no keyboard traps | M3 | Survey |
| F23 | TUI Screen 1 - Dashboard | Active/queued/gated runs, spend gauge, gateway card | M3 | Survey |
| F24 | TUI Screen 2 - Start Run | Task input, pickers, gates, model override, dry-run, cost estimate | M3 | Survey |
| F25 | TUI Screen 3 - Live Run View | DAG step progress, RichLog ANSI streaming, modal gate overlay | M3 | Survey |
| F26 | TUI Screen 4 - Payload Editor | Form + JSON editor, real-time validation against schema | M3 | Survey |
| F27 | TUI Screen 5 - Workflows | Workflow list, DAG summary, raw YAML preview | M3 | Survey |
| F28 | TUI Screen 6 - Model Browser | Catalogs, active assignments, project overrides | M3 | Survey |
| F29 | TUI Screen 7 - Obsidian Browser | Vault search, markdown preview, start run from note | M3 | Survey |
| F30 | TUI Screen 8 - Telemetry | Monthly spend vs budget, agent/model breakdown, transactions | M3 | Survey |
| F31 | TUI Screen 9 - Run History | History table, replay, resume failed step, git diff | M3 | Survey |
| F32 | TUI Screen 10 - Finished Runs | Worktree branches table, diff inspector, merge/keep/discard | M3 | Survey |
| F33 | Textual Pilot Automated Tests | Automated tests driving all 10 screens and actions | M3 | Survey |
| F34 | Web UI Server Command | `py enki.py serve` single process backend & frontend | M4 | Survey |
| F35 | Strict 127.0.0.1 Binding | Backend binds only to loopback 127.0.0.1, no login required | M4 | Survey |
| F36 | REST API Endpoints | Full API covering runs, workflows, models, vault, diffs | M4 | Survey |
| F37 | Server-Sent Events (SSE) Stream | `/api/runs/{id}/stream` delivering live logs & events in order | M4 | Survey |
| F38 | Visual Drag-and-Drop Builder | React Flow canvas, round-trip YAML safe, model picker, cost pill | M4 | Survey |
| F39 | Live Run Graph & Terminal View | DAG with status styling, live terminal log streaming | M4 | Survey |
| F40 | Web Diff & Compare View | Side-by-side git diffs, multi-candidate compare view | M4 | Survey |
| F41 | Spend Analytics Charts | Recharts spend over time by model, agent, project | M4 | Survey |
| F42 | Playwright E2E Tests | Automated browser tests: canvas, save, dry-run, gate, diff, merge | M4 | Survey |
| F43 | Secret Leakage Prevention | Strict scan ensuring no `.env` keys appear in API, logs, UI | M4 | Survey |
| F44 | Budget Stop Protocol | Stop before model call at monthly budget with 3 choices | M5 | Survey |
| F45 | Obsidian File Locking | Cross-process lock preventing concurrent vault file corruption | M5 | Survey |
| F46 | Obsidian Task Note Write-Back | Mark checklist, update frontmatter, log run cost | M5 | Survey |
| F47 | Agent Boundary Safety | Hermes never writes code; OMP never edits vault | M5 | Survey |
| F48 | Project Exclusion | `Body.me App` excluded from pickers, runs, tests | M5 | Survey |
| F49 | Pytest Engine Test Suite | Comprehensive pytest suite passing with exit code 0 | M6 | Survey |
| F50 | Throwaway Sample Repo Fixture | Math package fixture with failing tax test resolved by fix | M6 | Survey |
| F51 | Real Smoke Run (<$1) | Single real run (real OpenRouter + OMP), spend < $1.00 | M7 | Survey |
| F52 | Independent UI Review Rubric | Agent-as-Judge 5-point rubric verification | M7 | Survey |
| F53 | Complete Documentation | Updated README covering TUI, Web UI, workflows, budget | M7 | Survey |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Shared Engine & Worktree Isolation | F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11 | none | DONE |
| M4 | Web UI (FastAPI + React/Vite) | F34, F35, F36, F37, F38, F39, F40, F41, F42, F43 | M1, M2 | DONE |
| M5 | Budget Enforcement, Obsidian Safe Integration & Safety | F44, F45, F46, F47, F48 | M1, M2, M3, M4 | DONE |
| M6 | E2E Integration (Tiers 1-4) & Adversarial Hardening (Tier 5) | F49, F50 | M1-M5, E2E Track | DONE |
| M7 | Real Smoke Run (<$1), Agent-as-Judge Review & Docs | F51, F52, F53 | M6 | DONE |

---

## Agent Implementation Guide: Next Steps & TODOs

### Milestone 4: Web UI (FastAPI + React/Vite) — DONE
- [x] **Backend Server (`src/web/api.py`, `src/web/server.py`)**:
  - Implement FastAPI application strictly bound to loopback `127.0.0.1`.
  - Expose REST API routes: `/api/runs`, `/api/runs/{id}`, `/api/workflows`, `/api/models`, `/api/vault`, `/api/runs/{id}/diff`.
  - Implement SSE endpoint `/api/runs/{id}/stream` consuming events from `EventBus`.
  - Integrate `py enki.py serve` CLI command.
- [x] **Frontend Application (`web/`)**:
  - Scaffold React 18 + Vite + TypeScript application in `web/`.
  - Implement visual DAG builder canvas with round-trip YAML persistence (`WorkflowEditor.tsx`).
  - Implement live terminal log streaming panel with ANSI and SSE support (`LiveRunView.tsx`).
  - Implement side-by-side Git diff viewer and multi-candidate comparison view for fan-out runs.
  - Implement spend analytics and active run dashboard (`Dashboard.tsx`).
  - Compile production assets into `web/dist` served by FastAPI.
- [x] **Automated Testing (`tests/test_web_api.py`)**:
  - Pytest tests for API endpoints, SSE streaming, and loopback security binding.

### Milestone 5: Budget Enforcement, Obsidian Safe Integration & Safety — DONE
- [x] **Budget Guard (`src/engine/budget_guard.py`)**:
  - Implement real-time intercept before model completions when monthly spend reaches `telemetry.monthly_budget_usd` ($25.00).
  - Expose 3 user decisions: Continue spending, Pause run, or Switch to cheaper model.
- [x] **Obsidian Vault Guard (`src/engine/vault_guard.py`)**:
  - Implement cross-process file locking for vault markdown modifications.
  - Atomic temp-file and rename updates for task note checklists and `01_Dashboard/Enki_Activity_Log.md`.
  - Verify boundary invariants: Hermes never writes code, OMP never writes to Obsidian vault.
  - Exclude `Body.me App` strictly across all pickers, runs, and monitors.

### Milestone 6: E2E Integration & Adversarial Hardening — DONE
- [x] Comprehensive multi-tier test harness validating end-to-end runs using throwaway git repo fixtures (`fixture_sample_repo`).
- [x] Adversarial stress tests for concurrent execution, worktree conflicts, and network interruption simulation (`test_adversarial_m1.py`, `test_adversarial_dag_engine.py`, `test_adversarial_verification_telemetry.py`).
- [x] Verified 129 / 129 test suite passing with exit code 0 (`py -3 -m pytest`).

### Milestone 7: Real Smoke Run (<$1), Agent-as-Judge Review & Docs — DONE
- [x] Pipeline end-to-end dry-run and smoke verification with zero unapproved spend.
- [x] 5-point rubric verification: Clean Code, No Regressions, Safety Boundaries, Ergonomics, Truthfulness.
- [x] Complete user-facing documentation in `README.md`.

---

## Interface Contracts

### 1. Engine Event Bus (`src/engine/events.py`)
```python
class RunEvent(BaseModel):
    event_id: str
    run_id: str
    event_type: str  # run_started, step_started, log_chunk, gate_waiting, budget_stop, etc.
    timestamp: str
    payload: Dict[str, Any]

class EventBus:
    def publish(self, event: RunEvent) -> None: ...
    def subscribe(self, run_id: str, callback: Callable[[RunEvent], None]) -> None: ...
```

### 2. Run Manager (`src/engine/run_manager.py`)
```python
class RunManager:
    def create_run(self, task: str, project: str, workflow_id: str, dry_run: bool = False, overrides: Dict = None) -> Run: ...
    def start_run(self, run_id: str) -> None: ...
    def resolve_gate(self, run_id: str, gate_id: str, action: str, payload: Dict = None, feedback: str = None) -> None: ...
    def resolve_budget(self, run_id: str, decision: str, cheaper_model: str = None) -> None: ...
    def finish_worktree(self, run_id: str, action: Literal["merge", "keep", "discard"]) -> Dict: ...
```

### 3. Worktree Manager (`src/engine/worktree_manager.py`)
```python
class WorktreeManager:
    def create_worktree(self, repo_path: Path, run_id: str, base_branch: str = "feature/enki-ui") -> Path: ...
    def get_diff(self, repo_path: Path, run_id: str) -> str: ...
    def merge_worktree(self, repo_path: Path, run_id: str, target_branch: str) -> bool: ...
    def discard_worktree(self, repo_path: Path, run_id: str) -> None: ...
```

### 4. Workflow DAG Engine (`src/engine/workflow_engine.py`)
```python
class WorkflowEngine:
    def execute_dag(self, run_id: str, workflow_def: Dict, worktree_path: Path, dry_run: bool = False) -> None: ...
```

---

## Code Layout

```
Enki/
├── enki.py                          # CLI entry point (subcommands: run, context, ..., tui, serve)
├── src/
│   ├── orchestrator.py              # Backward-compatible facade wrapping engine
│   ├── omp_bridge.py                # Streaming OMP execution bridge with session isolation
│   ├── openrouter.py                # API client with budget check & secret redaction
│   ├── openrouter_catalog.py        # Live catalog cache & pricing merger
│   ├── obsidian_indexer.py          # Vault indexing
│   ├── token_tracker.py             # SQLite telemetry with per-run cost filtering
│   ├── config.py                    # Configuration manager
│   ├── engine/                      # New Shared Core Engine
│   │   ├── __init__.py
│   │   ├── models.py                # Typed states, schemas, and events
│   │   ├── events.py                # EventBus pub/sub
│   │   ├── run_manager.py           # Run storage, replay, resume
│   │   ├── worktree_manager.py      # Git worktree lifecycle
│   │   ├── workflow_engine.py       # DAG runner (routing, retries, compare, gates)
│   │   ├── workflow_parser.py       # YAML parser & round-trip serializer
│   │   ├── budget_guard.py          # Budget limit intercept & 3 choices
│   │   └── vault_guard.py           # Cross-process file locking for Obsidian
│   ├── ui/
│   │   └── tui/                     # Textual Terminal UI
│   │       ├── app.py               # EnkiTUIApp
│   │       └── screens/             # 10 screens (dashboard, start, live, payload, etc.)
│   └── web/                         # FastAPI Web Backend
│       ├── api.py                   # FastAPI app (127.0.0.1 loopback only)
│       ├── server.py                # Uvicorn server launcher
│       └── routes/                  # API endpoints & SSE stream
├── web/                             # React/Vite Frontend
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       └── components/              # Workflow canvas, live graph, diff, charts
├── workflows/                       # Built-in and user workflow YAMLs
│   ├── four_step_pipeline.yaml
│   ├── feature_and_reviewer.yaml
│   ├── escalate_on_fail.yaml
│   ├── compare.yaml
│   └── plan_only.yaml
├── schemas/
│   ├── context_payload.schema.json
│   └── workflow.schema.json
├── tests/                           # Pytest & E2E Test Suite
│   ├── conftest.py                  # Fixtures: sample_math_repo, fixture_vault, mock_omp
│   ├── test_engine.py               # Runs, worktrees, events, replay, resume
│   ├── test_workflows.py            # YAML validation, routing, escalate, compare
│   ├── test_budget_obsidian.py      # Budget stop choices, vault locking, per-run cost
│   ├── test_tui_pilot.py            # Textual Pilot automated screen tests
│   ├── test_web_api.py              # FastAPI endpoints, loopback check, SSE streaming
│   └── test_cli_compat.py           # CLI subcommands dry-run test
└── data/
    ├── enki_telemetry.db
    └── runs/                        # Run metadata and isolated worktrees
```
