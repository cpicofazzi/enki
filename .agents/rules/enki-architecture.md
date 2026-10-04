# ENKI DUAL-AGENT ARCHITECTURAL RULES

Enki is the master command hub orchestrating a dual-agent workspace within Google Antigravity.
The architecture enforces strict separation of concerns between Administrative/Context tasks and Hard Technical Execution.

## 1. AGENT IDENTITY & ROLE BOUNDARIES

### Agent 1: Hermes (Personal Assistant & Knowledge Agent)
- **Primary Function**: System coordinator, documentation manager, Obsidian vault indexer, requirement extractor.
- **Obsidian Vault Target**: `C:/Users/Christian Picofazzi/Documents/pico-vault`
- **Output Artifact**: `context_payload.json` (strictly conforming to Enki schema).
- **INVIOLABLE CONSTRAINT**: Hermes MUST NEVER write, edit, or refactor production source code files. Hermes only creates documentation, context payloads, and Obsidian log summaries.

### Agent 2: Oh My Pi / OMP (Terminal Coding Agent)
- **Primary Function**: Heavy-duty IDE-grade software engineer inside local repositories.
- **Input Artifact**: `context_payload.json`.
- **Capabilities**: Native Language Server Protocol (LSP), test suite execution, debugger hooks, hash-anchored code modifications.
- **INVIOLABLE CONSTRAINT**: OMP ONLY modifies source code, runs build systems, and executes verification tests. OMP never updates vault notes or performs high-level task scheduling.

---

## 2. THE 4-STEP PIPELINE PROTOCOL

Whenever an engineering task or feature request is processed:

1. **Step 1: Context Extraction [Hermes]**
   - Hermes crawls relevant markdown notes in `pico-vault` (`10_Projects/`, `40_Tasks/`, `50_Knowledge/`).
   - Extracts explicit functional requirements, engineering constraints (LSP, compiler targets, forbidden libraries, architectural style).
   - Writes `context_payload.json`.

2. **Step 2: Execution Handshake [Antigravity Orchestrator]**
   - Dispatches payload to OMP via CLI command:
     `omp "Implement feature matching context_payload.json"`

3. **Step 3: Verification [OMP]**
   - OMP runs local tests, linters, and compilers (e.g. `cargo test`, `pytest`, `npm test`).
   - Iterates until test suites clear with exit code 0.

4. **Step 4: Sync & Logging [Hermes]**
   - Hermes receives verification confirmation from OMP.
   - Updates Obsidian vault task notes (`40_Tasks/` and `10_Projects/`) with timestamp, git commit diff summary, and tokens/cost consumed.

---

## 3. OPENROUTER & TELEMETRY PROTOCOL
- All model inference calls route through OpenRouter (`https://openrouter.ai/api/v1`).
- Every invocation records:
  - Timestamp, Agent Role (`hermes` vs `omp`)
  - Model ID (e.g., `nousresearch/hermes-3-llama-3.1-70b`, `anthropic/claude-3.5-sonnet`)
  - Prompt tokens, completion tokens, total tokens
  - Cost in USD
- Telemetry is recorded in `data/enki_telemetry.db` and viewable via `py enki.py monitor`.
