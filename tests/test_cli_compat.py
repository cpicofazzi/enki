"""
Baseline Opaque-Box CLI Compatibility Test Suite.
Verifies that all 10 pre-existing CLI subcommands:
  run, context, handshake, verify, sync, gateway, models, monitor, status, image
can be executed in dry-run/mock mode and do not crash.
"""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import enki
from src.orchestrator import PAYLOAD_FILE


def execute_cli(argv: list[str]) -> None:
    """Invokes enki CLI with specified arguments."""
    with patch.object(sys, "argv", argv):
        enki.main()


def test_cli_status(fixture_vault, mock_gateway, capsys):
    """Verify `enki status` displays hub overview without crashing."""
    execute_cli(["enki.py", "status"])
    captured = capsys.readouterr()
    assert "ENKI STATUS & ENVIRONMENT OVERVIEW" in captured.out
    assert "Active Gateway" in captured.out
    assert "Obsidian Vault" in captured.out


def test_cli_monitor(capsys):
    """Verify `enki monitor` displays telemetry dashboard without crashing."""
    execute_cli(["enki.py", "monitor"])
    captured = capsys.readouterr()
    assert "ENKI HUB" in captured.out and "TELEMETRY" in captured.out
    assert "MONTHLY SPEND & BUDGET:" in captured.out or "Monthly Spend" in captured.out or "RECENT TRANSACTIONS" in captured.out


def test_cli_gateway_display(capsys):
    """Verify `enki gateway` without flags executes cleanly."""
    execute_cli(["enki.py", "gateway"])
    # Bare gateway currently returns cleanly
    captured = capsys.readouterr()
    assert captured.err == ""


def test_cli_gateway_set(isolated_config, capsys):
    """Verify `enki gateway --set <target>` switches active gateway and handles errors."""
    # 1. Switch to opencode_zen
    execute_cli(["enki.py", "gateway", "--set", "opencode_zen"])
    captured = capsys.readouterr()
    assert "Active gateway switched to: OpenCode Zen (`opencode_zen`)" in captured.out

    # 2. Switch back to openrouter
    execute_cli(["enki.py", "gateway", "--set", "openrouter"])
    captured = capsys.readouterr()
    assert "Active gateway switched to: OpenRouter (`openrouter`)" in captured.out

    # 3. Invalid gateway
    execute_cli(["enki.py", "gateway", "--set", "non_existent_gateway"])
    captured = capsys.readouterr()
    assert "Error: Unknown gateway 'non_existent_gateway'" in captured.out


def test_cli_models_display(capsys):
    """Verify `enki models` displays model architecture catalog without crashing."""
    execute_cli(["enki.py", "models"])
    captured = capsys.readouterr()
    assert "ENKI MODEL & TASK ARCHITECTURE" in captured.out
    assert "Active Gateway" in captured.out
    assert "Hermes (Context)" in captured.out
    assert "OMP (Coding)" in captured.out


def test_cli_models_set(isolated_config, capsys):
    """Verify `enki models --set-hermes`, `--set-omp`, and `--project` configure models."""
    execute_cli(["enki.py", "models", "--set-hermes", "mock/custom-hermes"])
    captured = capsys.readouterr()
    assert "Updated Hermes model" in captured.out

    execute_cli(["enki.py", "models", "--set-omp", "mock/custom-omp"])
    captured = capsys.readouterr()
    assert "Updated OMP model" in captured.out

    execute_cli(["enki.py", "models", "--project", "Trend Scraper", "--set-model", "mock/trend-omp"])
    captured = capsys.readouterr()
    assert "Updated project 'Trend Scraper' model to: mock/trend-omp" in captured.out


def test_cli_image(mock_gateway, capsys):
    """Verify `enki image <prompt>` generates images using mocked gateway without real spend."""
    execute_cli(["enki.py", "image", "A modern geometric logo for Enki"])
    captured = capsys.readouterr()
    assert "Generating image using model" in captured.out
    assert "A modern geometric logo for Enki" in captured.out
    assert "Result: https://mock-openrouter.internal/images/" in captured.out
    assert len(mock_gateway.images) == 1


def test_cli_context(fixture_vault, mock_gateway, capsys):
    """Verify `enki context <task>` extracts requirements from vault into context_payload.json."""
    execute_cli(["enki.py", "context", "Fix Tax Calculation Bug"])
    captured = capsys.readouterr()
    assert "[Step 1: Context Extraction]" in captured.out
    assert "Hermes indexing Obsidian vault" in captured.out
    assert "Generated context_payload.json" in captured.out

    # Verify payload file was written and is valid JSON
    assert enki.PAYLOAD_FILE.is_file()
    payload = json.loads(enki.PAYLOAD_FILE.read_text(encoding="utf-8"))
    assert payload.get("title") == "Fix Tax Calculation Bug"
    assert "Fix calculation error in calculate_tax" in payload.get("requirements", [])


def test_cli_handshake(fixture_vault, mock_gateway, mock_omp, capsys):
    """Verify `enki handshake` dispatches context payload to OMP."""
    # First generate payload via context
    execute_cli(["enki.py", "context", "Fix Tax Calculation Bug"])
    capsys.readouterr()

    # Now execute handshake
    execute_cli(["enki.py", "handshake"])
    captured = capsys.readouterr()
    assert "[Step 2: Execution Handshake]" in captured.out
    assert "Dispatching to Oh My Pi (OMP)" in captured.out
    assert "OMP Status: completed" in captured.out
    assert len(mock_omp.handshake_calls) == 1


def test_cli_verify(fixture_vault, mock_gateway, mock_omp, capsys):
    """Verify `enki verify` runs verification tests on context payload."""
    # Generate payload
    execute_cli(["enki.py", "context", "Fix Tax Calculation Bug"])
    capsys.readouterr()

    # Execute verify
    execute_cli(["enki.py", "verify"])
    captured = capsys.readouterr()
    assert "[Step 3: Verification]" in captured.out
    assert "Running OMP verification loop" in captured.out
    assert "Verification Result: PASSED" in captured.out
    assert len(mock_omp.verification_calls) == 1


def test_cli_sync(fixture_vault, mock_gateway, mock_omp, capsys):
    """Verify `enki sync` updates Obsidian vault activity log and task notes."""
    # Generate payload
    execute_cli(["enki.py", "context", "Fix Tax Calculation Bug"])
    capsys.readouterr()

    # Execute sync
    execute_cli(["enki.py", "sync"])
    captured = capsys.readouterr()
    assert "[Step 4: Sync & Logging]" in captured.out
    assert "Hermes syncing completion to Obsidian" in captured.out
    assert "Activity logged to Obsidian" in captured.out

    # Check activity log in fixture_vault
    log_file = fixture_vault / "01_Dashboard" / "Enki_Activity_Log.md"
    assert log_file.is_file()
    log_content = log_file.read_text(encoding="utf-8")
    assert "Fix Tax Calculation Bug" in log_content


def test_cli_run_full_pipeline(fixture_vault, mock_gateway, mock_omp, capsys):
    """Verify `enki run <task>` runs all 4 steps end-to-end without crashing."""
    execute_cli(["enki.py", "run", "Fix Tax Calculation Bug"])
    captured = capsys.readouterr()
    assert "EXECUTING 4-STEP PIPELINE" in captured.out
    assert "[Step 1: Context Extraction]" in captured.out
    assert "[Step 2: Execution Handshake]" in captured.out
    assert "[Step 3: Verification]" in captured.out
    assert "[Step 4: Sync & Logging]" in captured.out
    assert "ENKI PIPELINE COMPLETED SUCCESSFULLY FOR: 'Fix Tax Calculation Bug'" in captured.out


def test_cli_run_with_preset_and_overrides(fixture_vault, mock_gateway, mock_omp, capsys):
    """Verify `enki run` with --preset and --model overrides."""
    execute_cli([
        "enki.py", "run",
        "--preset", "cost_optimal",
        "--model", "deepseek/deepseek-chat",
        "Fix Tax Calculation Bug"
    ])
    captured = capsys.readouterr()
    assert "[Preset:" in captured.out
    assert "Gateway: openrouter" in captured.out
    assert "Model: deepseek/deepseek-chat" in captured.out
    assert "ENKI PIPELINE COMPLETED SUCCESSFULLY" in captured.out


@pytest.mark.parametrize("subcommand,extra_args", [
    ("status", []),
    ("monitor", []),
    ("gateway", []),
    ("models", []),
    ("image", ["Generate a minimal button design"]),
    ("context", ["Fix Tax Calculation Bug"]),
    ("handshake", []),
    ("verify", []),
    ("sync", []),
    ("run", ["Implement calculator tests"]),
])
def test_all_10_preexisting_subcommands_dry_run(
    subcommand, extra_args, fixture_vault, mock_gateway, mock_omp, capsys
):
    """
    Parametrized requirement test verifying that every single pre-existing CLI
    subcommand (run, context, handshake, verify, sync, gateway, models, monitor, status, image)
    can be invoked in dry-run/mock mode and executes without unhandled exceptions.
    """
    # For subcommands requiring payload, ensure context is run first
    if subcommand in ["handshake", "verify", "sync"]:
        execute_cli(["enki.py", "context", "Setup initial payload"])
        capsys.readouterr()

    argv = ["enki.py", subcommand] + extra_args
    execute_cli(argv)
    captured = capsys.readouterr()
    assert captured.err == "", f"Subcommand '{subcommand}' emitted errors to stderr: {captured.err}"


def test_fixture_sample_repo_deliberate_bug_and_fix(fixture_sample_repo):
    """
    Directly exercises fixture_sample_repo:
    1. Verifies deliberate tax bug initially causes pytest failure (exit code 1).
    2. Verifies apply_tax_bug_fix() updates calculator.py.
    3. Verifies pytest in sample repo passes with exit code 0 post-fix.
    """
    # Verify initial state: calculator has deliberate bug
    calc_content = fixture_sample_repo.calculator_file.read_text(encoding="utf-8")
    assert "return amount + rate" in calc_content
    rc_initial, stdout_initial, _ = fixture_sample_repo.run_pytest()
    assert rc_initial == 1
    assert "FAILED" in stdout_initial

    # Apply fix
    fixture_sample_repo.apply_tax_bug_fix()
    calc_fixed = fixture_sample_repo.calculator_file.read_text(encoding="utf-8")
    assert "return round(amount * rate, 2)" in calc_fixed

    # Verify pytest now passes with exit code 0
    rc_fixed, stdout_fixed, _ = fixture_sample_repo.run_pytest()
    assert rc_fixed == 0
    assert "passed" in stdout_fixed


def test_mock_omp_multi_attempt_repair(fixture_sample_repo, mock_omp):
    """
    Verifies mock_omp multi-attempt repair simulation:
    - Attempt 1 fails verification with exit code 1.
    - Attempt 2 applies bug fix and passes verification with exit code 0.
    """
    mock_omp.verification_attempts_before_pass = 1
    mock_omp.target_repo = fixture_sample_repo

    # Attempt 1: should fail
    passed_1, results_1 = mock_omp.run_verification(["py -m pytest -q"], working_dir=fixture_sample_repo.path)
    assert not passed_1
    assert results_1[0]["exit_code"] == 1
    assert mock_omp.verification_attempts == 1

    # Attempt 2: should apply fix to repo and pass
    passed_2, results_2 = mock_omp.run_verification(["py -m pytest -q"], working_dir=fixture_sample_repo.path)
    assert passed_2
    assert results_2[0]["exit_code"] == 0
    assert mock_omp.verification_attempts == 2

    # Verify repo tests indeed pass now
    rc, stdout, _ = fixture_sample_repo.run_pytest()
    assert rc == 0


def test_cli_sync_dry_run_never_writes_vault(fixture_vault, mock_gateway, mock_omp, capsys):
    """Verify `enki sync --dry-run` does not create or append to vault activity log."""
    execute_cli(["enki.py", "context", "--dry-run", "Fix Tax Calculation Bug"])
    capsys.readouterr()

    # Pre-condition: remove activity log in fixture_vault if present to test creation prevention
    log_file = fixture_vault / "01_Dashboard" / "Enki_Activity_Log.md"
    if log_file.is_file():
        log_file.unlink()
    assert not log_file.is_file()

    # Execute sync with --dry-run
    execute_cli(["enki.py", "sync", "--dry-run"])
    captured = capsys.readouterr()
    assert "[Dry-Run] Simulating Obsidian vault sync (no vault write)" in captured.out

    # Post-condition: log file must still not exist
    assert not log_file.is_file()


def test_cli_sync_dry_run_never_appends_to_existing_vault_log(fixture_vault, mock_gateway, mock_omp, capsys):
    """Verify `enki sync --dry-run` never appends to an existing activity log."""
    execute_cli(["enki.py", "context", "--dry-run", "Fix Tax Calculation Bug"])
    capsys.readouterr()

    log_file = fixture_vault / "01_Dashboard" / "Enki_Activity_Log.md"
    assert log_file.is_file()
    initial_content = log_file.read_text(encoding="utf-8")

    # Execute sync with --dry-run
    execute_cli(["enki.py", "sync", "--dry-run"])
    captured = capsys.readouterr()
    assert "[Dry-Run] Simulating Obsidian vault sync (no vault write)" in captured.out

    # Post-condition: log file content must remain exactly identical
    assert log_file.read_text(encoding="utf-8") == initial_content
    assert "Fix Tax Calculation Bug" not in log_file.read_text(encoding="utf-8")


def test_cli_run_dry_run_never_writes_vault(fixture_vault, mock_gateway, mock_omp, capsys):
    """Verify `enki run --dry-run` does not create or append to vault activity log."""
    log_file = fixture_vault / "01_Dashboard" / "Enki_Activity_Log.md"
    if log_file.is_file():
        log_file.unlink()
    assert not log_file.is_file()

    execute_cli(["enki.py", "run", "--dry-run", "Fix Tax Calculation Bug"])
    captured = capsys.readouterr()
    assert "[Dry-Run] Simulating Obsidian vault sync (no vault write)" in captured.out

    # Post-condition: log file must still not exist
    assert not log_file.is_file()


def test_cli_run_dry_run_never_appends_to_existing_vault_log(fixture_vault, mock_gateway, mock_omp, capsys):
    """Verify `enki run --dry-run` never appends to an existing activity log."""
    log_file = fixture_vault / "01_Dashboard" / "Enki_Activity_Log.md"
    assert log_file.is_file()
    initial_content = log_file.read_text(encoding="utf-8")

    execute_cli(["enki.py", "run", "--dry-run", "Fix Tax Calculation Bug"])
    captured = capsys.readouterr()
    assert "[Dry-Run] Simulating Obsidian vault sync (no vault write)" in captured.out

    # Post-condition: log file content must remain exactly identical
    assert log_file.read_text(encoding="utf-8") == initial_content
    assert "Fix Tax Calculation Bug" not in log_file.read_text(encoding="utf-8")


def test_universal_autouse_isolation_protects_production_vault(mock_gateway, capsys):
    """
    Verify that even when fixture_vault is NOT requested in a test:
    1. ObsidianIndexer resolves to a temporary vault, NOT pico-vault.
    2. Live production pico-vault is never targeted.
    """
    import os
    from src.obsidian_indexer import ObsidianIndexer
    indexer = ObsidianIndexer()
    assert "pico-vault" not in str(indexer.vault_path).replace("\\", "/")
    assert os.environ.get("ENKI_OBSIDIAN_VAULT")
    assert "pico-vault" not in os.environ.get("ENKI_OBSIDIAN_VAULT", "").replace("\\", "/")


