import os
import sys
import json
import stat
import shutil
import tempfile
import dataclasses
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Generator
from unittest.mock import MagicMock

import pytest

# Ensure repository root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _remove_readonly(func, path, exc_info):
    """Helper to remove read-only files on Windows during temp cleanup."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


@dataclasses.dataclass
class SampleRepo:
    """Helper wrapper around the throwaway sample git repository."""
    path: Path

    @property
    def calculator_file(self) -> Path:
        return self.path / "calculator.py"

    @property
    def test_file(self) -> Path:
        return self.path / "tests" / "test_calculator.py"

    def apply_tax_bug_fix(self) -> None:
        """Fixes the deliberate tax calculation bug in calculator.py."""
        fixed_code = '''"""
Calculator module with standard tax calculation.
"""

def calculate_tax(amount: float, rate: float) -> float:
    """Calculate tax for a given amount and rate.
    
    Fixed implementation: accurately multiplies amount by rate and rounds to 2 decimals.
    """
    return round(amount * rate, 2)
'''
        self.calculator_file.write_text(fixed_code, encoding="utf-8")

    def run_pytest(self) -> Tuple[int, str, str]:
        """Runs pytest inside the sample repository."""
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(self.path),
            capture_output=True,
            text=True,
            timeout=60
        )
        return proc.returncode, proc.stdout, proc.stderr

    def __fspath__(self) -> str:
        return str(self.path)

    def __str__(self) -> str:
        return str(self.path)


@pytest.fixture
def fixture_sample_repo() -> Generator[SampleRepo, None, None]:
    """
    Creates a throwaway git repository with deliberate tax bug in calculator.py
    (amount + rate instead of round(amount * rate, 2)) and a pytest test in
    test_calculator.py that initially fails with exit code 1.
    """
    temp_dir = tempfile.mkdtemp(prefix="enki_test_sample_repo_")
    repo_path = Path(temp_dir)

    try:
        # 1. Initialize git repo
        subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Enki Test"], cwd=str(repo_path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@enki.internal"], cwd=str(repo_path), capture_output=True, check=True)

        # 2. Write calculator.py with deliberate bug (addition instead of multiplication)
        buggy_calculator = '''"""
Calculator module with tax calculation.
"""

def calculate_tax(amount: float, rate: float) -> float:
    """Calculate tax for a given amount and rate.
    
    DELIBERATE BUG: Adds rate instead of multiplying amount by rate!
    amount + rate instead of round(amount * rate, 2)
    """
    return amount + rate
'''
        (repo_path / "calculator.py").write_text(buggy_calculator, encoding="utf-8")

        # 3. Create tests/test_calculator.py
        tests_dir = repo_path / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "__init__.py").write_text("", encoding="utf-8")

        test_content = '''import pytest
from calculator import calculate_tax

def test_calculate_tax_basic():
    # 100.0 * 0.05 should be 5.0. Buggy calculator yields 100.0 + 0.05 = 100.05
    assert calculate_tax(100.0, 0.05) == 5.0

def test_calculate_tax_zero():
    # 0.0 * 0.10 should be 0.0. Buggy calculator yields 0.0 + 0.10 = 0.10
    assert calculate_tax(0.0, 0.10) == 0.0

def test_calculate_tax_standard():
    assert calculate_tax(50.0, 0.20) == 10.0
'''
        (tests_dir / "test_calculator.py").write_text(test_content, encoding="utf-8")

        # 4. Create pyproject.toml to ensure pytest finds repo root in pythonpath
        pyproject_content = """[tool.pytest.ini_options]
pythonpath = ["."]
"""
        (repo_path / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")

        # 5. Commit all files to git
        subprocess.run(["git", "add", "."], cwd=str(repo_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit: deliberate tax bug"], cwd=str(repo_path), capture_output=True, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(repo_path), capture_output=True, check=True)

        sample = SampleRepo(path=repo_path)

        # 6. Verify deliberate bug: pytest must fail with exit code 1 initially
        rc, stdout, stderr = sample.run_pytest()
        assert rc == 1, f"Sample repo pytest was expected to fail with code 1, but exited with {rc}. stdout: {stdout}"

        yield sample
    finally:
        shutil.rmtree(temp_dir, onerror=_remove_readonly)


@pytest.fixture
def fixture_vault(monkeypatch) -> Generator[Path, None, None]:
    """
    Creates an isolated temporary directory mimicking pico-vault
    (00_Inbox, 01_Dashboard/Enki_Activity_Log.md, 10_Projects, 40_Tasks, 50_Knowledge)
    so tests never touch the real user vault.
    """
    temp_dir = tempfile.mkdtemp(prefix="enki_test_vault_")
    vault_path = Path(temp_dir)

    try:
        # Create folder structure
        (vault_path / "00_Inbox").mkdir(parents=True, exist_ok=True)
        (vault_path / "01_Dashboard").mkdir(parents=True, exist_ok=True)
        (vault_path / "10_Projects").mkdir(parents=True, exist_ok=True)
        (vault_path / "40_Tasks").mkdir(parents=True, exist_ok=True)
        (vault_path / "50_Knowledge").mkdir(parents=True, exist_ok=True)

        # 01_Dashboard/Enki_Activity_Log.md
        log_file = vault_path / "01_Dashboard" / "Enki_Activity_Log.md"
        log_file.write_text(
            "# Enki Command Hub - Activity & Execution Log\n\nAutomated log entries recorded by Hermes & OMP.\n\n---\n",
            encoding="utf-8"
        )

        # 10_Projects/Sample_Math.md
        (vault_path / "10_Projects" / "Sample_Math.md").write_text(
            "---\n"
            "title: Sample Math Package\n"
            "project: Sample Math\n"
            "language: python\n"
            "status: active\n"
            "---\n\n"
            "# Sample Math Package\n\n"
            "Core mathematics package with tax calculator.\n",
            encoding="utf-8"
        )

        # 40_Tasks/Fix_Tax_Calculation_Bug.md
        (vault_path / "40_Tasks" / "Fix_Tax_Calculation_Bug.md").write_text(
            "---\n"
            "title: Fix Tax Calculation Bug\n"
            "status: todo\n"
            "project: Sample Math\n"
            'created_date: "2026-10-09"\n'
            'completed_date: ""\n'
            "---\n\n"
            "# Fix Tax Calculation Bug\n\n"
            "Fix the tax calculation bug in the calculator module.\n\n"
            "## Action Checklist\n"
            "- [ ] Fix calculation error in calculate_tax\n"
            "- [ ] Ensure all unit tests pass with exit code 0\n",
            encoding="utf-8"
        )

        # 50_Knowledge/Tax_Calculation_Specs.md
        (vault_path / "50_Knowledge" / "Tax_Calculation_Specs.md").write_text(
            "---\n"
            "title: Tax Calculation Architecture Specs\n"
            "project: Sample Math\n"
            "---\n\n"
            "# Tax Calculation Specifications\n\n"
            "Tax must be calculated by multiplying taxable amount by tax rate:\n"
            "Formula: round(amount * rate, 2)\n",
            encoding="utf-8"
        )

        # Point environment variable to isolated vault
        monkeypatch.setenv("ENKI_OBSIDIAN_VAULT", str(vault_path))

        # Also patch ObsidianIndexer default vault_path if imported
        import src.obsidian_indexer
        orig_init = src.obsidian_indexer.ObsidianIndexer.__init__
        def patched_indexer_init(self, v_path=None, *args, **kwargs):
            orig_init(self, v_path or vault_path, *args, **kwargs)
            self.vault_path = vault_path
        monkeypatch.setattr(src.obsidian_indexer.ObsidianIndexer, "__init__", patched_indexer_init)

        yield vault_path
    finally:
        shutil.rmtree(temp_dir, onerror=_remove_readonly)


class MockOMP:
    """Configurable mock controller for Oh My Pi (OMP) execution."""

    def __init__(self):
        self.handshake_calls: List[Dict[str, Any]] = []
        self.verification_calls: List[Dict[str, Any]] = []
        self.handshake_exit_code: int = 0
        self.verification_attempts: int = 0
        self.verification_attempts_before_pass: int = 0  # 0 means passes immediately
        self.target_repo: Optional[SampleRepo] = None

    def execute_handshake(
        self,
        payload_path: Path,
        working_dir: Optional[Path] = None,
        simulate_if_missing: bool = True,
        dry_run: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        call_info = {
            "payload_path": Path(payload_path),
            "working_dir": working_dir,
            "simulate_if_missing": simulate_if_missing,
            "dry_run": dry_run,
            **kwargs
        }
        self.handshake_calls.append(call_info)
        return {
            "status": "completed" if self.handshake_exit_code == 0 else "failed",
            "exit_code": self.handshake_exit_code,
            "command": f'omp "Implement feature matching {Path(payload_path).name}"',
            "stdout": f"[Mock OMP] Handshake completed successfully for {Path(payload_path).name}",
            "stderr": ""
        }

    def run_verification(
        self,
        test_commands: List[str],
        working_dir: Optional[Path] = None
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        self.verification_attempts += 1
        self.verification_calls.append({
            "attempt": self.verification_attempts,
            "test_commands": test_commands,
            "working_dir": working_dir
        })

        if self.verification_attempts <= self.verification_attempts_before_pass:
            # Simulated failure attempt
            results = []
            for cmd in test_commands:
                results.append({
                    "command": cmd,
                    "passed": False,
                    "exit_code": 1,
                    "stdout": "FAILED test_calculator.py::test_calculate_tax_basic",
                    "stderr": "AssertionError: assert 100.05 == 5.0"
                })
            return False, results

        # Simulated successful attempt
        if self.target_repo:
            self.target_repo.apply_tax_bug_fix()

        results = []
        for cmd in test_commands:
            results.append({
                "command": cmd,
                "passed": True,
                "exit_code": 0,
                "stdout": "1 passed in 0.05s",
                "stderr": ""
            })
        return True, results


@pytest.fixture
def mock_omp(monkeypatch) -> Generator[MockOMP, None, None]:
    """Fixture providing simulated OMP runs without running external processes."""
    mock_instance = MockOMP()
    import src.omp_bridge

    monkeypatch.setattr(src.omp_bridge.OMPBridge, "execute_handshake", mock_instance.execute_handshake)
    monkeypatch.setattr(src.omp_bridge.OMPBridge, "run_verification", mock_instance.run_verification)
    monkeypatch.setattr(src.omp_bridge.OMPBridge, "is_available", lambda self: True)

    yield mock_instance


class MockGateway:
    """Configurable mock for OpenRouter and OpenCode Zen gateways with zero spend."""

    def __init__(self):
        self.completions: List[Dict[str, Any]] = []
        self.images: List[Dict[str, Any]] = []
        self.custom_responses: Dict[str, Any] = {}
        self.default_spec = {
            "title": "Fix Tax Calculation Bug",
            "requirements": [
                "Fix calculation error in calculate_tax",
                "Ensure all unit tests pass with exit code 0"
            ],
            "engineering_constraints": {
                "language": "python",
                "target_framework": "Sample Math",
                "lsp_server": "python-lsp",
                "forbidden_patterns": ["Avoid hardcoded credentials"],
                "design_patterns": ["Clean architecture", "Type annotations"],
                "file_scope": ["calculator.py", "tests/test_calculator.py"]
            },
            "acceptance_criteria": {
                "test_commands": ["py -m pytest -q"],
                "success_conditions": [
                    "All unit tests pass with exit code 0",
                    "No linter errors"
                ]
            }
        }

    def calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        return 0.0

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        agent_role: str = "hermes",
        task_id: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        self.completions.append({
            "messages": messages,
            "model": model,
            "agent_role": agent_role,
            "task_id": task_id
        })

        if agent_role in self.custom_responses:
            val = self.custom_responses[agent_role]
            if isinstance(val, list) and len(val) > 0:
                resp_content = val.pop(0) if len(val) > 1 else val[0]
            else:
                resp_content = val
        elif agent_role == "hermes":
            resp_content = json.dumps(self.default_spec)
        elif agent_role == "evaluator":
            resp_content = json.dumps({
                "decision": "approved",
                "approved": True,
                "score": 92,
                "summary": "Mock reviewer approved diff against rubric.",
                "rubric_scores": {
                    "clean_code": 95,
                    "no_regressions": 90,
                    "safety_boundaries": 95,
                    "architecture_compliance": 90
                },
                "feedback": ""
            })
        else:
            resp_content = "[Mocked Assistant Response]"

        return {
            "role": "assistant",
            "content": resp_content,
            "model": model or "mock/model",
            "gateway": "mock_gateway",
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
                "cost_usd": 0.0,
                "simulated": True
            }
        }

    def generate_image(self, prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
        self.images.append({"prompt": prompt, "model": model})
        return {
            "role": "assistant",
            "content": f"https://mock-openrouter.internal/images/mock_{abs(hash(prompt))}.png",
            "model": model or "black-forest-labs/flux-1-schnell",
            "gateway": "mock_gateway",
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 0,
                "total_tokens": 20,
                "cost_usd": 0.0,
                "simulated": True
            }
        }


@pytest.fixture
def mock_gateway(monkeypatch) -> Generator[MockGateway, None, None]:
    """Fixture simulating OpenRouter completions with zero spend."""
    mock_gw = MockGateway()
    import src.openrouter

    monkeypatch.setattr(src.openrouter.GatewayClient, "complete", mock_gw.complete)
    monkeypatch.setattr(src.openrouter.GatewayClient, "calculate_cost", mock_gw.calculate_cost)
    monkeypatch.setattr(src.openrouter.GatewayClient, "generate_image", mock_gw.generate_image)

    # Strictly prohibit real network requests during automated tests
    def forbidden_urlopen(*args, **kwargs):
        raise RuntimeError("Network calls are forbidden during automated test execution!")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_urlopen)

    yield mock_gw


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch, tmp_path_factory):
    """
    Autouse fixture protecting against accidental writes to:
    1. data/enki_telemetry.db (diverted to temp sqlite db)
    2. root context_payload.json (diverted to temp file)
    """
    temp_dir = tmp_path_factory.mktemp("enki_test_isolation")

    # 1. Telemetry DB isolation
    temp_db = temp_dir / "test_telemetry.db"
    import src.token_tracker
    monkeypatch.setattr(src.token_tracker, "get_db_path", lambda: temp_db)

    # 2. Payload file isolation
    temp_payload = temp_dir / "context_payload.json"
    import src.orchestrator
    import enki
    monkeypatch.setattr(src.orchestrator, "PAYLOAD_FILE", temp_payload)
    monkeypatch.setattr(enki, "PAYLOAD_FILE", temp_payload)

    # 3. Universal Obsidian vault isolation
    temp_vault = temp_dir / "vault"
    temp_vault.mkdir(parents=True, exist_ok=True)
    (temp_vault / "01_Dashboard").mkdir(parents=True, exist_ok=True)
    (temp_vault / "40_Tasks").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ENKI_OBSIDIAN_VAULT", str(temp_vault))

    yield


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Provides an isolated copy of enki.config.json for tests that mutate configuration."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    temp_cfg = cfg_dir / "enki.config.json"
    
    src_cfg = ROOT_DIR / "config" / "enki.config.json"
    shutil.copyfile(src_cfg, temp_cfg)

    import enki
    monkeypatch.setattr(enki, "ROOT_DIR", tmp_path)
    return temp_cfg
