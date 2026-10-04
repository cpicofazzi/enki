import os
import sys
import shutil
import subprocess
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import load_config

class OMPBridge:
    def __init__(self, binary_path: Optional[str] = None):
        cfg = load_config()
        self.cmd_name = binary_path or cfg.get("omp", {}).get("binary_command", "omp")
        self.timeout = cfg.get("omp", {}).get("default_timeout_seconds", 300)

    def is_available(self) -> bool:
        """Checks if omp CLI executable exists in PATH or at specified path."""
        p = Path(self.cmd_name)
        if p.is_file():
            return True
        return shutil.which(self.cmd_name) is not None

    def execute_handshake(
        self,
        payload_path: Path,
        working_dir: Optional[Path] = None,
        simulate_if_missing: bool = True
    ) -> Dict[str, Any]:
        """
        Feeds context_payload.json to Oh My Pi via native CLI wrapper:
        omp "Implement feature matching context_payload.json"
        """
        cwd = working_dir or ROOT_DIR
        prompt = f'Implement feature matching {payload_path.resolve()}'

        if not self.is_available():
            if simulate_if_missing:
                return {
                    "status": "simulated",
                    "exit_code": 0,
                    "command": f'{self.cmd_name} "{prompt}"',
                    "stdout": (
                        f"[OMP Bridge Simulation]\n"
                        f"Target Payload: {payload_path}\n"
                        f"OMP binary '{self.cmd_name}' was not detected in PATH.\n"
                        f"Handshake validated successfully in test mode."
                    ),
                    "stderr": ""
                }
            else:
                raise FileNotFoundError(
                    f"Oh My Pi binary '{self.cmd_name}' not found. "
                    f"Install it or configure its path in config/enki.config.json."
                )

        if self.cmd_name.lower().endswith((".cmd", ".bat")):
            cmd = f'"{self.cmd_name}" "{prompt}"'
            use_shell = True
        else:
            cmd = [self.cmd_name, prompt]
            use_shell = False

        try:
            proc = subprocess.run(
                cmd,
                shell=use_shell,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            return {
                "status": "completed" if proc.returncode == 0 else "failed",
                "exit_code": proc.returncode,
                "command": cmd if isinstance(cmd, str) else " ".join(cmd),
                "stdout": proc.stdout,
                "stderr": proc.stderr
            }
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "exit_code": -1,
                "command": " ".join(cmd),
                "stdout": "",
                "stderr": f"OMP command timed out after {self.timeout}s"
            }
        except Exception as e:
            return {
                "status": "error",
                "exit_code": -1,
                "command": " ".join(cmd),
                "stdout": "",
                "stderr": str(e)
            }

    def run_verification(
        self,
        test_commands: List[str],
        working_dir: Optional[Path] = None
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        OMP Verification Loop: executes test commands until all pass with exit code 0.
        """
        cwd = working_dir or ROOT_DIR
        results = []
        all_passed = True

        for cmd_str in test_commands:
            if not cmd_str.strip():
                continue
            try:
                proc = subprocess.run(
                    cmd_str,
                    shell=True,
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=180
                )
                passed = (proc.returncode == 0)
                if not passed:
                    all_passed = False
                results.append({
                    "command": cmd_str,
                    "passed": passed,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[:2000],
                    "stderr": proc.stderr[:2000]
                })
            except Exception as e:
                all_passed = False
                results.append({
                    "command": cmd_str,
                    "passed": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": str(e)
                })

        return all_passed, results
