"""
src/omp_bridge.py
Non-blocking streaming execution bridge for Oh My Pi (OMP) and iterative verification.
Supports ndjson event stream parsing, event bus dispatch, ephemeral YAML config overlays,
Windows bun/node direct execution, and iterative verification retry loop with diagnostics.
"""

import os
import sys
import json
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Callable
from contextlib import contextmanager

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import load_config


class OMPBridge:
    def __init__(self, binary_path: Optional[str] = None):
        cfg = load_config()
        self.cmd_name = binary_path or cfg.get("omp", {}).get("binary_command", "omp")
        self.timeout = cfg.get("omp", {}).get("default_timeout_seconds", 300)
        self.bun_path: Optional[str] = None
        self.cli_js_path: Optional[str] = None
        self._detect_runtime()

    def _detect_runtime(self) -> None:
        """
        Detects if bun.exe and cli.js are directly accessible to avoid
        Windows cmd.exe /c batch script quote-stripping issues.
        """
        user_profile = os.environ.get("USERPROFILE", "")
        candidate_bun = Path(user_profile) / ".bun" / "bin" / "bun.exe"
        candidate_cli = Path("C:/Program Files (x86)/Nodist/bin/node_modules/@oh-my-pi/pi-coding-agent/dist/cli.js")

        if candidate_bun.is_file() and candidate_cli.is_file():
            self.bun_path = str(candidate_bun)
            self.cli_js_path = str(candidate_cli)

    def is_available(self) -> bool:
        """Checks if OMP executable or bun runtime exists."""
        if self.bun_path and self.cli_js_path:
            return True
        p = Path(self.cmd_name)
        if p.is_file():
            return True
        return shutil.which(self.cmd_name) is not None

    @contextmanager
    def ephemeral_overlay(self, model: Optional[str] = None, extra_config: Optional[Dict[str, Any]] = None):
        """
        Creates an ephemeral YAML config overlay for this session only.
        Guarantees that user's global ~/.omp config is NEVER mutated.
        """
        temp_file = None
        if model or extra_config:
            content_dict = {}
            if model:
                content_dict["model"] = model
            if extra_config:
                content_dict.update(extra_config)

            lines = ["# Enki Ephemeral OMP Overlay"]
            for k, v in content_dict.items():
                if isinstance(v, (str, int, float, bool)):
                    lines.append(f"{k}: {json.dumps(v)}")
                elif isinstance(v, list):
                    lines.append(f"{k}:")
                    for item in v:
                        lines.append(f"  - {json.dumps(item)}")

            tf = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
            tf.write("\n".join(lines) + "\n")
            tf.close()
            temp_file = Path(tf.name)

        try:
            yield temp_file
        finally:
            if temp_file and temp_file.is_file():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

    def _build_command_args(
        self,
        prompt: str,
        cwd: Path,
        model: Optional[str] = None,
        overlay_path: Optional[Path] = None
    ) -> List[str]:
        """Constructs argument vector with strict isolation flags."""
        if self.bun_path and self.cli_js_path:
            args = [self.bun_path, self.cli_js_path]
        elif self.cmd_name.lower().endswith((".cmd", ".bat")):
            args = ["cmd.exe", "/c", self.cmd_name]
        else:
            args = [self.cmd_name]

        # Standard non-interactive headless flags
        args.extend([
            "-p",
            "--mode", "json",
            "--auto-approve",
            "--no-session",
            "--cwd", str(cwd)
        ])

        if model:
            args.extend(["--model", model])

        if overlay_path:
            args.extend(["--config", str(overlay_path)])

        args.append(prompt)
        return args

    def parse_ndjson_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parses a single ndjson line emitted by OMP."""
        s = line.strip()
        if not s or not (s.startswith("{") and s.endswith("}")):
            return None
        try:
            return json.loads(s)
        except Exception:
            return None

    def format_event_for_log(self, event: Dict[str, Any]) -> Optional[str]:
        """Formats structured OMP events into human-readable terminal log chunks."""
        evt_type = event.get("type", "")
        if evt_type == "message_update":
            am_evt = event.get("assistantMessageEvent", {})
            if isinstance(am_evt, dict):
                if am_evt.get("type") == "text_delta":
                    return am_evt.get("delta", "")
                if am_evt.get("type") == "thinking_delta":
                    return f"[thinking] {am_evt.get('delta', '')}"
            if "delta" in event:
                return str(event.get("delta", ""))
            if "thinkingDelta" in event:
                return f"[thinking] {event.get('thinkingDelta', '')}"
        elif evt_type == "tool_call_start":
            tool_name = event.get("tool", "unknown")
            args = event.get("args", {})
            return f"[OMP Tool] -> {tool_name}({json.dumps(args)[:100]})"
        elif evt_type == "tool_call_end":
            tool_name = event.get("tool", "unknown")
            return f"[OMP Tool] <- {tool_name} completed"
        elif evt_type == "notice":
            return f"[OMP Notice] {event.get('message', '')}"
        elif evt_type == "auto_retry_start":
            return f"[OMP Retry] Attempt {event.get('attempt', 1)}: {event.get('errorMessage', '')}"
        elif evt_type == "agent_end":
            return "[OMP] Turn completed."
        return None

    def stream_execution(
        self,
        prompt: str,
        working_dir: Optional[Path] = None,
        model: Optional[str] = None,
        overlay_config: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        step_id: Optional[str] = None,
        event_bus: Optional[Any] = None,
        dry_run: bool = False,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes OMP non-blockingly, parsing ndjson events in real-time,
        and dispatching log chunks and events to EventBus.
        """
        cwd = working_dir or ROOT_DIR
        effective_timeout = timeout or self.timeout

        # Simulation / Dry-run Handling
        if dry_run or not self.is_available():
            sim_msg = f"[Dry-Run OMP Simulation] Prompt: {prompt[:80]}... (Working Dir: {cwd})"
            if event_bus:
                from src.engine.models import RunEvent, EventType
                event_bus.publish(RunEvent(
                    run_id=run_id or "",
                    event_type=EventType.LOG_CHUNK,
                    payload={"text": sim_msg, "stream": "stdout", "phase": "omp"}
                ))
            return {
                "status": "completed" if dry_run else "simulated",
                "exit_code": 0,
                "command": f"omp [dry_run] \"{prompt[:60]}\"",
                "stdout": sim_msg + "\nExecution completed successfully in simulation mode.",
                "stderr": "",
                "events": [{"type": "agent_end", "simulated": True}]
            }

        # Live Execution with Ephemeral Overlay
        with self.ephemeral_overlay(model=model, extra_config=overlay_config) as overlay_path:
            cmd_args = self._build_command_args(prompt, cwd, model, overlay_path)

            try:
                proc = subprocess.Popen(
                    cmd_args,
                    cwd=str(cwd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="replace"
                )
            except Exception as e:
                err_msg = f"Failed to spawn OMP process: {e}"
                if event_bus:
                    from src.engine.models import RunEvent, EventType
                    event_bus.publish(RunEvent(
                        run_id=run_id or "",
                        event_type=EventType.LOG_CHUNK,
                        payload={"text": err_msg, "stream": "stderr", "phase": "omp"}
                    ))
                return {
                    "status": "error",
                    "exit_code": -1,
                    "command": " ".join(cmd_args),
                    "stdout": "",
                    "stderr": str(e),
                    "events": []
                }

            stdout_lines: List[str] = []
            stderr_lines: List[str] = []
            parsed_events: List[Dict[str, Any]] = []

            # Background thread to drain stderr and prevent pipe deadlocks
            def drain_stderr():
                for line in iter(proc.stderr.readline, ''):
                    stderr_lines.append(line)
                    if event_bus:
                        from src.engine.models import RunEvent, EventType
                        event_bus.publish(RunEvent(
                            run_id=run_id or "",
                            event_type=EventType.LOG_CHUNK,
                            payload={"text": line.rstrip("\r\n"), "stream": "stderr", "phase": "omp"}
                        ))

            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()

            # Main loop: drain stdout line-by-line
            try:
                for line in iter(proc.stdout.readline, ''):
                    stdout_lines.append(line)
                    parsed = self.parse_ndjson_line(line)
                    if parsed:
                        parsed_events.append(parsed)
                        if event_bus:
                            from src.engine.models import RunEvent, EventType
                            event_bus.publish(RunEvent(
                                run_id=run_id or "",
                                event_type=EventType.LOG_CHUNK,
                                payload={"raw_event": parsed, "stream": "stdout", "phase": "omp"}
                            ))
                            chunk_text = self.format_event_for_log(parsed)
                            if chunk_text:
                                event_bus.publish(RunEvent(
                                    run_id=run_id or "",
                                    event_type=EventType.LOG_CHUNK,
                                    payload={"text": chunk_text, "stream": "stdout", "phase": "omp"}
                                ))
                    else:
                        if event_bus and line.strip():
                            from src.engine.models import RunEvent, EventType
                            event_bus.publish(RunEvent(
                                run_id=run_id or "",
                                event_type=EventType.LOG_CHUNK,
                                payload={"text": line.rstrip("\r\n"), "stream": "stdout", "phase": "omp"}
                            ))

                proc.wait(timeout=effective_timeout)
                stderr_thread.join(timeout=2.0)
                exit_code = proc.returncode

                return {
                    "status": "completed" if exit_code == 0 else "failed",
                    "exit_code": exit_code,
                    "command": " ".join(cmd_args),
                    "stdout": "".join(stdout_lines),
                    "stderr": "".join(stderr_lines),
                    "events": parsed_events
                }
            except subprocess.TimeoutExpired:
                proc.kill()
                return {
                    "status": "timeout",
                    "exit_code": -1,
                    "command": " ".join(cmd_args),
                    "stdout": "".join(stdout_lines),
                    "stderr": f"OMP command timed out after {effective_timeout}s",
                    "events": parsed_events
                }

    def execute_handshake(
        self,
        payload_path: Path,
        working_dir: Optional[Path] = None,
        simulate_if_missing: bool = True,
        model: Optional[str] = None,
        run_id: Optional[str] = None,
        event_bus: Optional[Any] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Backward-compatible handshake wrapper using stream_execution."""
        cwd = working_dir or ROOT_DIR
        prompt = f"Implement feature matching {Path(payload_path).resolve()}"
        return self.stream_execution(
            prompt=prompt,
            working_dir=cwd,
            model=model,
            run_id=run_id,
            event_bus=event_bus,
            dry_run=dry_run
        )

    def run_test_command_streaming(
        self,
        cmd_str: str,
        working_dir: Optional[Path] = None,
        run_id: Optional[str] = None,
        event_bus: Optional[Any] = None,
        timeout: int = 180,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Runs a single test command, streaming stdout/stderr line-by-line."""
        cwd = working_dir or ROOT_DIR

        if event_bus:
            from src.engine.models import RunEvent, EventType
            event_bus.publish(RunEvent(
                run_id=run_id or "",
                event_type=EventType.LOG_CHUNK,
                payload={"text": f"\n$ {cmd_str}", "stream": "stdout", "phase": "test"}
            ))

        if dry_run:
            sim_out = f"[Dry-Run Test] Simulated test passed: {cmd_str}"
            if event_bus:
                from src.engine.models import RunEvent, EventType
                event_bus.publish(RunEvent(
                    run_id=run_id or "",
                    event_type=EventType.LOG_CHUNK,
                    payload={"text": sim_out, "stream": "stdout", "phase": "test"}
                ))
            return {
                "command": cmd_str,
                "passed": True,
                "exit_code": 0,
                "stdout": sim_out,
                "stderr": ""
            }

        try:
            proc = subprocess.Popen(
                cmd_str,
                shell=True,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Combine for chronological traceback
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace"
            )

            output_lines = []
            for line in iter(proc.stdout.readline, ''):
                output_lines.append(line)
                if event_bus:
                    from src.engine.models import RunEvent, EventType
                    event_bus.publish(RunEvent(
                        run_id=run_id or "",
                        event_type=EventType.LOG_CHUNK,
                        payload={"text": line.rstrip("\r\n"), "stream": "stdout", "phase": "test"}
                    ))

            proc.wait(timeout=timeout)
            passed = (proc.returncode == 0)
            return {
                "command": cmd_str,
                "passed": passed,
                "exit_code": proc.returncode,
                "stdout": "".join(output_lines),
                "stderr": ""
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            return {
                "command": cmd_str,
                "passed": False,
                "exit_code": -1,
                "stdout": "".join(output_lines),
                "stderr": f"Command timed out after {timeout}s"
            }
        except Exception as e:
            return {
                "command": cmd_str,
                "passed": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e)
            }

    def run_verification(
        self,
        test_commands: List[str],
        working_dir: Optional[Path] = None,
        run_id: Optional[str] = None,
        event_bus: Optional[Any] = None,
        dry_run: bool = False
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Executes test commands, streaming stdout/stderr line-by-line.
        Returns (all_passed, results).
        """
        cwd = working_dir or ROOT_DIR
        results = []
        all_passed = True

        for cmd_str in test_commands:
            if not cmd_str.strip():
                continue
            res = self.run_test_command_streaming(
                cmd_str=cmd_str,
                working_dir=cwd,
                run_id=run_id,
                event_bus=event_bus,
                dry_run=dry_run
            )
            results.append(res)
            if not res["passed"]:
                all_passed = False

        return all_passed, results

    def run_verification_loop(
        self,
        test_commands: List[str],
        working_dir: Optional[Path] = None,
        max_retries: int = 3,
        model: Optional[str] = None,
        overlay_config: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        event_bus: Optional[Any] = None,
        dry_run: bool = False,
        mock_omp_fix_fn: Optional[Callable[[int, str, Path], None]] = None
    ) -> Dict[str, Any]:
        """
        The Verification Retry Loop:
        1. Runs test commands streaming line-by-line.
        2. If any test fails, constructs failure diagnostics and prompts OMP to repair.
        3. Repeats until all tests pass or max_retries reached.
        4. Accurately records OMP iterations.
        """
        import inspect
        cwd = working_dir or ROOT_DIR
        iteration = 1
        history: List[Dict[str, Any]] = []
        all_passed = False

        while iteration <= max_retries:
            if event_bus:
                from src.engine.models import RunEvent, EventType
                event_bus.publish(RunEvent(
                    run_id=run_id or "",
                    event_type=EventType.STEP_PROGRESS,
                    payload={"phase": "verification", "iteration": iteration, "max_retries": max_retries}
                ))

            # Inspect run_verification signature to support both real OMPBridge and monkeypatched mocks
            sig = inspect.signature(self.run_verification)
            kwargs: Dict[str, Any] = {"working_dir": cwd}
            if "run_id" in sig.parameters:
                kwargs["run_id"] = run_id
            if "event_bus" in sig.parameters:
                kwargs["event_bus"] = event_bus
            if "dry_run" in sig.parameters:
                kwargs["dry_run"] = dry_run

            all_passed, current_results = self.run_verification(test_commands, **kwargs)
            failed_tests = [r for r in current_results if not r.get("passed")]

            history.append({
                "iteration": iteration,
                "results": current_results,
                "all_passed": all_passed
            })

            if all_passed:
                if event_bus:
                    from src.engine.models import RunEvent, EventType
                    event_bus.publish(RunEvent(
                        run_id=run_id or "",
                        event_type=EventType.LOG_CHUNK,
                        payload={"text": f"[Verification] All test commands PASSED on iteration {iteration}.", "stream": "stdout", "phase": "test"}
                    ))
                break

            if iteration >= max_retries:
                if event_bus:
                    from src.engine.models import RunEvent, EventType
                    event_bus.publish(RunEvent(
                        run_id=run_id or "",
                        event_type=EventType.LOG_CHUNK,
                        payload={"text": f"[Verification] Max retries ({max_retries}) reached without passing tests.", "stream": "stderr", "phase": "test"}
                    ))
                break

            # Construct failure diagnostics
            diagnostics = []
            for ft in failed_tests:
                diagnostics.append(
                    f"Command '{ft.get('command')}' failed with exit code {ft.get('exit_code')}:\n"
                    f"--- Traceback / Output ---\n{ft.get('stdout', '')[-2500:]}\n--- End Output ---"
                )
            failure_report = "\n\n".join(diagnostics)
            repair_prompt = (
                f"Verification test failure (Attempt {iteration}/{max_retries}):\n\n"
                f"{failure_report}\n\n"
                f"Please inspect the workspace files, fix the bugs causing the test failures, and ensure the test suite passes."
            )

            # Invoke repair attempt
            if mock_omp_fix_fn:
                mock_omp_fix_fn(iteration, repair_prompt, cwd)
            else:
                self.stream_execution(
                    prompt=repair_prompt,
                    working_dir=cwd,
                    model=model,
                    overlay_config=overlay_config,
                    run_id=run_id,
                    event_bus=event_bus,
                    dry_run=dry_run
                )

            iteration += 1

        return {
            "all_passed": all_passed,
            "iterations": iteration,
            "max_retries": max_retries,
            "results": history[-1]["results"] if history else [],
            "history": history,
            "status": "PASSED" if all_passed else "FAILED"
        }
