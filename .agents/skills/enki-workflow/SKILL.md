---
name: enki-workflow
description: Automated workflow orchestrating Hermes (Knowledge & Context Agent) and Oh My Pi (Terminal Coding Agent) through the 4-step Enki pipeline with OpenRouter telemetry.
---

# Enki Workflow Runbook

This skill automates the collaboration between **Hermes** (Knowledge Agent) and **Oh My Pi / OMP** (Terminal Coding Agent).

## Prerequisites
- Working Directory: `C:/Users/Christian Picofazzi/Documents/Enki`
- Obsidian Vault: `C:/Users/Christian Picofazzi/Documents/pico-vault`
- Python Runtime: Python 3.13 (`py -3`)
- OpenRouter API key configured in `.env` or `config/enki.config.json`

---

## The 4 Steps

### Step 1: Context Extraction (Hermes)
Extract technical requirements and constraints from the Obsidian vault and generate `context_payload.json`:

```powershell
py enki.py context "<Task or Feature Description>"
```

Output generated: `context_payload.json` containing:
- `task_id` & `title`
- `requirements` list
- `engineering_constraints` (LSP server, language version, prohibited patterns)
- `acceptance_criteria` (test commands, exit criteria)
- `context_sources` (referenced notes and code paths)

### Step 2: Execution Handshake (Antigravity -> OMP)
Dispatches the technical constraints into the active repository using OMP:

```powershell
py enki.py handshake --payload context_payload.json
```

Or invoke directly via OMP CLI:
```powershell
omp "Implement feature matching context_payload.json"
```

### Step 3: Verification (OMP)
Runs local compilers and test suites specified in `context_payload.json`:

```powershell
py enki.py verify
```

If tests fail, OMP refactors and reruns until the test suite passes.

### Step 4: Sync & Documentation (Hermes)
Hermes logs the completed task, summary of changes, and token telemetry back to the Obsidian vault:

```powershell
py enki.py sync
```

---

## Token & Cost Telemetry
Check real-time OpenRouter token usage and pricing:

```powershell
py enki.py monitor
```

---

## End-to-End Execution
Run the full 4-step pipeline in a single automated command:

```powershell
py enki.py run "<Task Description>"
```
