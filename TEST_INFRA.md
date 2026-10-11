# Enki Test Infrastructure Specification & Feature Mapping (Tiers 1-4)

This document establishes the end-to-end testing architecture, test philosophy, fixture standards, runner protocols, and complete feature coverage mapping across Tiers 1–4 for the Enki Dual-Agent UI & Multi-Model Workflow Engine.

---

## 1. Test Philosophy & Core Invariants

Testing in Enki adheres strictly to an **opaque-box, requirement-driven, zero-spend paradigm**:

1. **Opaque-Box Requirement Verification**:
   - Tests evaluate system behavior against documented interface contracts (`PROJECT.md`) and original user requirements (`ORIGINAL_REQUEST.md`), not ephemeral internal implementation details.
   - Tests assert observable outputs: return payloads, exit codes, git worktree states, event streams, vault markdown updates, and CLI/TUI/Web presentations.

2. **Absolute Resource & Environment Isolation**:
   - **Zero Vault Contamination**: Tests MUST NEVER touch the user's real Obsidian vault (`C:/Users/Christian Picofazzi/Documents/pico-vault`). All vault tests execute inside isolated temporary fixtures mimicking vault folder structures (`00_Inbox`, `01_Dashboard/Enki_Activity_Log.md`, `10_Projects`, `40_Tasks`, `50_Knowledge`).
   - **Zero Repository Contamination**: Tests MUST NEVER touch real development repositories. All multi-worktree and code-generation tests run against throwaway sample git repositories (`fixture_sample_repo`).
   - **Zero User Config Mutation**: Tests MUST NEVER edit the user's global Oh My Pi configuration (`~/.omp/config.yaml`, `model.yaml`) or local `.env` API keys.
   - **Zero Unauthorized Monetary Spend**: Automated test suites execute exclusively using mocked gateways (`mock_gateway`) and mocked OMP bridges (`mock_omp`) with $0.00 cost. The single live smoke run (< $1.00) in Milestone M7 is guarded by explicit manual confirmation.

3. **Progressive Testability**:
   - Test suites are designed modularly. Milestone M1 tests verify M1 functionality without requiring M2 DAG workflows or M3/M4 UI layers. Each milestone builds upon verified foundational tiers.

4. **Authenticity & Integrity (Anti-Cheating Policy)**:
   - Tests must exercise genuine logic. Facade tests that pass vacuously, hardcoded assertion bypasses, and tests tuned to pass faulty code without exercising requirements are strictly forbidden.

---

## 2. Test Architecture Tiers

The test suite is structured into four functional tiers plus adversarial hardening:

| Tier | Name | Scope & Characteristics | Execution Time | Test Files |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | **Unit & Primitive Tests** | In-memory validation of individual algorithms: EventBus pub/sub, YAML round-trip parser, catalog cache TTL & pricing mergers, token math, regex parsers. | < 5s | `tests/test_workflows.py`, `tests/test_engine.py` |
| **Tier 2** | **Integration & Contract Tests** | Subsystem interaction with ephemeral file systems and git: WorktreeManager branch lifecycles, Verifier retry loops, DAG execution with routing/escalation, BudgetGuard intercepts, VaultGuard atomic file locks. | 5s – 30s | `tests/test_engine.py`, `tests/test_workflows.py`, `tests/test_budget_obsidian.py` |
| **Tier 3** | **CLI & TUI Interface Tests** | Presentation tests via terminal: Backward-compatible CLI subcommands in dry-run mode, Textual `Pilot` headless screen automation driving all 10 TUI screens and keyboard navigation. | 10s – 40s | `tests/test_cli_compat.py`, `tests/test_tui_pilot.py` |
| **Tier 4** | **Local Web UI & E2E System Tests** | Full stack integration: FastAPI localhost-only binding, REST endpoints, SSE live log streams, and Playwright browser tests driving the React Flow canvas, diff inspector, and spend charts. | 30s – 90s | `tests/test_web_api.py`, `tests/e2e/` (Playwright) |
| **Tier 5** | **Adversarial Hardening** | Stress tests: Concurrent vault file writes under locking, malformed YAML DAG cycles, budget race conditions, secret leakage scanning across all endpoints and logs. | 15s – 45s | `tests/test_budget_obsidian.py`, `tests/test_engine.py` |

---

## 3. Directory Layout

All tests reside under `tests/`, structured cleanly to match project architectural layers:

```
Enki/
├── tests/
│   ├── conftest.py                  # Core pytest fixtures: sample repo, temp vault, mock OMP, mock gateway
│   ├── test_cli_compat.py           # Pre-existing CLI subcommands dry-run tests (Tier 3)
│   ├── test_engine.py               # Shared engine, worktrees, events, replay, resume, retry (Tiers 1 & 2)
│   ├── test_workflows.py            # Workflow schema, YAML parser, DAG routing, escalate, compare (Tiers 1 & 2)
│   ├── test_budget_obsidian.py      # Budget stop choices, vault locking, per-run cost, safety (Tiers 2 & 5)
│   ├── test_tui_pilot.py            # Textual Pilot automated tests for all 10 TUI screens (Tier 3)
│   ├── test_web_api.py              # FastAPI endpoints, loopback check, SSE streaming, secrets (Tier 4)
│   └── fixtures/                    # Test-specific data fixtures (schemas, sample payloads, workflows)
│       ├── test_workflow.yaml
│       └── sample_payload.json
├── TEST_INFRA.md                    # This document
└── pytest.ini                       # Pytest configuration, markers, warning filters
```

---

## 4. Complete Feature Inventory Coverage Mapping (F1 to F53)

The following table maps every feature from `PROJECT.md § Feature Inventory` across Tiers 1–4 to its authoritative test file and verification methodology:

| # | Feature Name | Milestone | Tier | Primary Test Target | Test Methodology & Verification Invariants |
| :- | :--- | :--- | :--- | :--- | :--- |
| **F1** | Typed Event Bus | M1 | Tier 1 | `tests/test_engine.py` | Verify `EventBus` pub/sub handles `RunEvent`, `LogChunkEvent`, `GateEvent`, preserving order and asynchronous listener execution without blocking engine. |
| **F2** | Backward-Compatible CLI Facade | M1 | Tier 3 | `tests/test_cli_compat.py` | Verify all 10 pre-existing CLI subcommands (`run`, `context`, `handshake`, `verify`, `sync`, `gateway`, `models`, `monitor`, `status`, `image`) run without crashing in dry-run/mock mode. |
| **F3** | Git Worktree Isolation | M1 | Tier 2 | `tests/test_engine.py` | Verify runs create isolated worktrees under branch `enki/run/<run_id>` in `fixture_sample_repo`. Assert 3 parallel runs have zero file cross-contamination. |
| **F4** | Worktree Teardown Choices | M1 | Tier 2 | `tests/test_engine.py` | Verify user choices on completion: Merge (only merges into target branch with explicit approval), Keep (leaves branch intact), Discard (removes worktree and branch). |
| **F5** | Streaming OMP & Tests | M1 | Tier 2 | `tests/test_engine.py` | Verify non-blocking streaming execution parses ndjson events / line chunks, publishing `LogChunkEvent` to EventBus in real-time. |
| **F6** | Verifier Retry Feedback Loop | M1 | Tier 2 | `tests/test_engine.py` | Mock OMP failing on attempt 1 and fixing tax bug on attempt 2. Verify loop passes failure output back to OMP and records 2 iterations before green. |
| **F7** | Resumable Run Persistence | M1 | Tier 2 | `tests/test_engine.py` | Kill run after Step 2. Verify run can be resumed from Step 3 without re-executing Steps 1 or 2. Verify state storage in `data/runs/<run_id>/run.json`. |
| **F8** | Per-Run Cost Telemetry | M1 | Tier 1 | `tests/test_engine.py` | Verify per-run telemetry query returns only tokens/cost consumed by specific `task_id` / `run_id`, fixing 30-day sum bug. |
| **F9** | Dry-Run Simulation Mode | M1 | Tier 1 | `tests/test_engine.py` | Verify dry-run flag runs entire pipeline end-to-end with simulated outputs and $0.00 spend. |
| **F10** | Fix `cmd_gateway` CLI Bug | M1 | Tier 3 | `tests/test_cli_compat.py` | Verify invoking bare `enki gateway` outputs active gateway and all available gateways rather than silent exit. |
| **F11** | Project `repo_path` Config | M1 | Tier 1 | `tests/test_engine.py` | Verify config loader parses and validates explicit `repo_path` on projects in `enki.config.json`. |
| **F12** | Workflows YAML Schema & Parser | M2 | Tier 1 | `tests/test_workflows.py` | Round-trip YAML test: load YAML, serialize, reload, assert equality. Validate against `schemas/workflow.schema.json`. Canvas node positions preserved. |
| **F13** | DAG Workflow Execution Engine | M2 | Tier 2 | `tests/test_workflows.py` | Verify dependency DAG execution resolves step topological sort, handles step dependencies, passes artifacts between dependent steps. |
| **F14** | Auto-Routing per Step | M2 | Tier 2 | `tests/test_workflows.py` | Verify steps with `model: auto` select model based on task category/complexity using `task_profiles`, recording reasoning in step state. |
| **F15** | Retry & Escalate Policy | M2 | Tier 2 | `tests/test_workflows.py` | Verify step configured with escalate policy auto-switches to stronger model after configured failure threshold. |
| **F16** | Reviewer Model Loop | M2 | Tier 2 | `tests/test_workflows.py` | Verify reviewer model step rejecting code sends feedback back to coding step until reviewer approves or retry limit reached. |
| **F17** | Fan-Out / Compare Engine | M2 | Tier 2 | `tests/test_workflows.py` | Verify fan-out step launches N parallel worktrees with different models, compares diffs, records selected winner. |
| **F18** | Approval Gates | M2 | Tier 2 | `tests/test_workflows.py` | Verify gates (`post_context`, `pre_code`) pause run, emit `gate_waiting`, and support 4 user actions: approve, edit payload & approve, reject with feedback, abort. |
| **F19** | 5 Built-in Workflow Templates | M2 | Tier 1 | `tests/test_workflows.py` | Validate all 5 built-in YAMLs (`four_step_pipeline.yaml`, `feature_and_reviewer.yaml`, `escalate_on_fail.yaml`, `compare.yaml`, `plan_only.yaml`) against schema and dry-run execution. |
| **F20** | OpenRouter Catalog Service | M2 | Tier 1 | `tests/test_workflows.py` | Verify catalog cache stores model list with 24h TTL in `data/openrouter_models_cache.json` and merges live pricing with curated config presets. |
| **F21** | TUI Command & Architecture | M3 | Tier 3 | `tests/test_tui_pilot.py` | Verify `py enki.py tui` instantiates pure Textual application without requiring web server daemon. |
| **F22** | Full Keyboard Navigation | M3 | Tier 3 | `tests/test_tui_pilot.py` | Verify Textual `Pilot` can navigate through all 10 screens using keyboard shortcuts (`1`-`9`, `0`, `Tab`, `Escape`) without traps. |
| **F23** | TUI Screen 1 - Dashboard | M3 | Tier 3 | `tests/test_tui_pilot.py` | Textual `Pilot` test verifying dashboard displays active/queued/gated runs, spend gauge, and gateway status card. |
| **F24** | TUI Screen 2 - Start Run | M3 | Tier 3 | `tests/test_tui_pilot.py` | Textual `Pilot` test filling task input, selecting project, toggling dry-run, verifying cost estimate pill, and dispatching run. |
| **F25** | TUI Screen 3 - Live Run View | M3 | Tier 3 | `tests/test_tui_pilot.py` | Textual `Pilot` test streaming logs via RichLog, displaying step DAG status, and rendering modal gate overlay. |
| **F26** | TUI Screen 4 - Payload Editor | M3 | Tier 3 | `tests/test_tui_pilot.py` | Textual `Pilot` test editing context payload fields with live schema validation feedback. |
| **F27** | TUI Screen 5 - Workflows | M3 | Tier 3 | `tests/test_tui_pilot.py` | Textual `Pilot` test listing workflows, viewing DAG step graph, and previewing raw YAML. |
| **F28** | TUI Screen 6 - Model Browser | M3 | Tier 3 | `tests/test_tui_pilot.py` | Textual `Pilot` test browsing OpenRouter catalog, inspecting active gateway models, setting project override. |
| **F29** | TUI Screen 7 - Obsidian Browser | M3 | Tier 3 | `tests/test_tui_pilot.py` | Textual `Pilot` test browsing vault notes from `fixture_vault`, previewing markdown, clicking "Start Run from Note". |
| **F30** | TUI Screen 8 - Telemetry | M3 | Tier 3 | `tests/test_tui_pilot.py` | Textual `Pilot` test viewing monthly spend vs budget bar, agent breakdown table, and recent transaction log. |
| **F31** | TUI Screen 9 - Run History | M3 | Tier 3 | `tests/test_tui_pilot.py` | Textual `Pilot` test viewing historical runs, triggering replay, and resuming a failed run. |
| **F32** | TUI Screen 10 - Finished Runs | M3 | Tier 3 | `tests/test_tui_pilot.py` | Textual `Pilot` test selecting completed worktree, inspecting diff, executing Merge, Keep, and Discard actions. |
| **F33** | Textual Pilot Automated Tests | M3 | Tier 3 | `tests/test_tui_pilot.py` | Comprehensive test harness executing headless Pilot tests across all 10 screens with zero UI hangs. |
| **F34** | Web UI Server Command | M4 | Tier 4 | `tests/test_web_api.py` | Verify `py enki.py serve` starts FastAPI backend and serves static Vite bundle. |
| **F35** | Strict 127.0.0.1 Binding | M4 | Tier 4 | `tests/test_web_api.py` | Verify server strictly binds to `127.0.0.1` and fails/rejects attempts to bind to public `0.0.0.0` or external interfaces. |
| **F36** | REST API Endpoints | M4 | Tier 4 | `tests/test_web_api.py` | FastTestClient test verifying all endpoints: `/api/runs`, `/api/workflows`, `/api/models`, `/api/vault`, `/api/diff/{id}`, `/api/budget`. |
| **F37** | Server-Sent Events (SSE) Stream | M4 | Tier 4 | `tests/test_web_api.py` | Verify `/api/runs/{id}/stream` delivers live log chunks and state change events in chronological order. |
| **F38** | Visual Drag-and-Drop Builder | M4 | Tier 4 | Playwright E2E | Browser test adding step nodes, connecting DAG edges, configuring model picker, verifying round-trip YAML persistence. |
| **F39** | Live Run Graph & Terminal View | M4 | Tier 4 | Playwright E2E | Browser test verifying live run DAG visualization reflects step states (pending, running, completed, failed) and terminal renders streamed stdout. |
| **F40** | Web Diff & Compare View | M4 | Tier 4 | Playwright E2E | Browser test inspecting side-by-side git diff and comparing candidate branches from a fan-out run. |
| **F41** | Spend Analytics Charts | M4 | Tier 4 | Playwright E2E | Browser test verifying spend charts render telemetry data by model, agent, and project over time. |
| **F42** | Playwright E2E Tests | M4 | Tier 4 | Playwright E2E | Automated browser test suite driving the web app end-to-end: build workflow, dry-run, approve gate, view diff, merge. |
| **F43** | Secret Leakage Prevention | M4 | Tier 4 & 5 | `tests/test_web_api.py` | Automated audit scanning all API responses, log files, event streams, and serialized runs to ensure `.env` keys never leak. |
| **F44** | Budget Stop Protocol | M5 | Tier 2 | `tests/test_budget_obsidian.py` | When monthly spend reaches budget ($25.00), engine halts before next model call, presenting 3 user choices (continue, pause, switch cheaper model). Verify all 3 behaviors. |
| **F45** | Obsidian File Locking | M5 | Tier 2 & 5 | `tests/test_budget_obsidian.py` | Stress test simulating concurrent process writes to `fixture_vault`. Verify cross-process file locking prevents data corruption. |
| **F46** | Obsidian Task Note Write-Back | M5 | Tier 2 | `tests/test_budget_obsidian.py` | After task completion, verify vault note in `40_Tasks/` has checkboxes marked `[x]`, frontmatter updated to `done`, and exact task cost logged to `Enki_Activity_Log.md`. |
| **F47** | Agent Boundary Safety | M5 | Tier 2 | `tests/test_budget_obsidian.py` | Inviolable boundary verification: assert Hermes never writes production code files in repo, and OMP never accesses or writes to Obsidian vault notes. |
| **F48** | Project Exclusion | M5 | Tier 2 | `tests/test_budget_obsidian.py` | Verify `Body.me App` remains in config but is excluded from project pickers, batch runs, and test executions. |
| **F49** | Pytest Engine Test Suite | M6 | Tier 2 & 3 | `tests/test_engine.py` | Full test suite execution across all components passing with exit code 0 via `py -3 -m pytest`. |
| **F50** | Throwaway Sample Repo Fixture | M6 | Tier 2 | `tests/conftest.py` | Provide `fixture_sample_repo` with deliberate tax calculation bug in `calculator.py` and initially failing pytest suite. |
| **F51** | Real Smoke Run (<$1) | M7 | Tier 4 | Manual / Review | Single capped real run against sample repo using real OpenRouter and real OMP with spend < $1.00. Log saved to `data/smoke_run.log`. |
| **F52** | Independent UI Review Rubric | M7 | Tier 3 & 4 | Review Artifact | Agent-as-Judge 5-point rubric verification: reachability, visual feedback, zero crashes, keyboard nav, budget visibility. |
| **F53** | Complete Documentation | M7 | Tier 3 | Documentation Audit | Verify README accurately details TUI, Web UI, YAML workflow format, budget protocol, and runner instructions. |

---

## 5. Core Pytest Fixture Specifications (`tests/conftest.py`)

### 5.1 `fixture_sample_repo`
- **Objective**: Create a pristine, isolated Git repository with a reproducible tax calculation bug and an initially failing test suite.
- **Specification**:
  - Creates a temporary directory via `tempfile.TemporaryDirectory`.
  - Runs `git init` on branch `main` (or `feature/enki-ui`).
  - Configures local `user.name = "Enki Test"` and `user.email = "test@enki.internal"`.
  - Creates `calculator.py`:
    ```python
    def calculate_tax(amount: float, rate: float) -> float:
        """Calculate tax on an amount given a percentage rate.
        
        DELIBERATE BUG: Performs addition instead of multiplication!
        """
        return amount + rate
    ```
  - Creates `test_calculator.py`:
    ```python
    from calculator import calculate_tax

    def test_calculate_tax_basic():
        assert calculate_tax(100.0, 0.05) == 5.0

    def test_calculate_tax_zero():
        assert calculate_tax(0.0, 0.10) == 0.0
    ```
  - Commits all files to Git with message `"Initial commit: calculator with deliberate tax bug"`.
  - Initial `pytest test_calculator.py` fails with exit code 1 (`100.0 + 0.05 == 100.05 != 5.0`).
  - Helper method `apply_tax_bug_fix()` rewrites `calculator.py` to `return round(amount * rate, 2)`, enabling tests to pass with exit code 0.

### 5.2 `fixture_vault`
- **Objective**: Create a replica of the user's Obsidian vault (`pico-vault`) completely isolated from the user's filesystem.
- **Specification**:
  - Creates folders: `00_Inbox/`, `01_Dashboard/`, `10_Projects/`, `40_Tasks/`, `50_Knowledge/`.
  - Pre-populates `01_Dashboard/Enki_Activity_Log.md` with an activity log header.
  - Pre-populates `10_Projects/Sample_Math.md` with project metadata (`project: Sample Math`, `language: python`, `test_commands: ["py -m pytest -q"]`).
  - Pre-populates `40_Tasks/Fix_Tax_Calculation_Bug.md` with frontmatter (`status: todo`) and checklist (`- [ ] Fix calculation error`).
  - Sets environment variable `ENKI_OBSIDIAN_VAULT` to this directory during test execution.

### 5.3 `mock_omp`
- **Objective**: Simulate OMP CLI execution and multi-iteration repair without invoking external processes or modifying the user's system.
- **Specification**:
  - Simulates Step 2 Handshake returning exit code 0 and structured status.
  - Simulates Step 3 Verification with configurable behavior:
    - Attempt 1: Returns exit code 1 with traceback output.
    - Attempt 2: Applies bug fix to target repo and returns exit code 0 (verified).
  - Records total iterations and dispatched prompts for assertion.

### 5.4 `mock_gateway`
- **Objective**: Simulate OpenRouter and OpenCode Zen API completions with zero spend.
- **Specification**:
  - Intercepts calls to `src.openrouter.GatewayClient.complete` and `calculate_cost`.
  - Returns schema-compliant JSON payloads for Hermes context extraction.
  - Returns mock responses for router decisions, reviewer evaluations, and compare judgements.
  - Enforces prompt token and completion token tracking with $0.00 actual monetary spend.

---

## 6. How to Run the Tests

Execute tests from the repository root using Python 3:

```powershell
# Run the complete test suite
py -3 -m pytest

# Run CLI compatibility baseline tests
py -3 -m pytest tests/test_cli_compat.py -v

# Run engine & worktree tests
py -3 -m pytest tests/test_engine.py -v

# Run workflow DAG & parser tests
py -3 -m pytest tests/test_workflows.py -v

# Run budget guard and Obsidian vault integration tests
py -3 -m pytest tests/test_budget_obsidian.py -v

# Run Textual Pilot TUI screen tests
py -3 -m pytest tests/test_tui_pilot.py -v

# Run FastAPI Web backend & SSE tests
py -3 -m pytest tests/test_web_api.py -v
```

---

## 7. Verification Invariants & Exit Criteria

Before any code is accepted or merged:
1. `py -3 -m pytest` must terminate with **exit code 0** and zero failures or errors.
2. The real Obsidian vault at `C:/Users/Christian Picofazzi/Documents/pico-vault` must show zero file modifications (verified via git status / file hashing).
3. The root `.env` must remain uncommitted and untracked.
4. Total automated test suite execution spend must remain exactly **$0.00**.
