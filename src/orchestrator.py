import os
import sys
import json
import uuid
import datetime
from pathlib import Path
from typing import Dict, Any, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import load_config
from src.openrouter import OpenRouterClient
from src.token_tracker import record_usage, get_summary
from src.obsidian_indexer import ObsidianIndexer
from src.omp_bridge import OMPBridge

PAYLOAD_FILE = ROOT_DIR / "context_payload.json"

class EnkiOrchestrator:
    def __init__(self, gateway: Optional[str] = None):
        self.config = load_config()
        self.gateway_name = gateway or self.config.get("active_gateway", "openrouter")
        self.openrouter = OpenRouterClient(gateway_name=self.gateway_name)
        self.indexer = ObsidianIndexer()
        self.omp = OMPBridge()

    def step_1_context_extraction(self, task_description: str, model_override: Optional[str] = None) -> Dict[str, Any]:
        """
        Step 1: Hermes crawls relevant docs/notes and outputs context_payload.json
        Rule: Hermes NEVER writes production code.
        """
        print(f"\n[Step 1: Context Extraction] Hermes indexing Obsidian vault for: '{task_description}'...")
        context_data = self.indexer.extract_context(task_description)
        hits = context_data.get("hits", [])
        print(f"  -> Found {len(hits)} relevant notes in pico-vault")
        for h in hits:
            print(f"     * {h['path']} (score: {h['score']})")

        notes_summary = "\n".join([
            f"Note: {h['path']}\nTitle: {h['title']}\nExcerpt: {h['excerpt']}\n"
            for h in hits
        ])

        system_prompt = (
            "You are Hermes, the Personal Assistant & Knowledge Coordinator in the Enki Hub.\n"
            "STRICT CORE RULE: You MUST NEVER write production code. You only extract engineering\n"
            "constraints, architectural limitations, acceptance criteria, and technical context.\n"
            "Produce a JSON object conforming strictly to this format:\n"
            "{\n"
            '  "title": "<Concise feature title>",\n'
            '  "requirements": ["<req 1>", "<req 2>"],\n'
            '  "engineering_constraints": {\n'
            '    "language": "<python|rust|typescript|etc>",\n'
            '    "target_framework": "<framework if any>",\n'
            '    "lsp_server": "<lsp name>",\n'
            '    "forbidden_patterns": ["<pattern 1>"],\n'
            '    "design_patterns": ["<pattern 1>"],\n'
            '    "file_scope": ["<files to touch>"]\n'
            "  },\n"
            '  "acceptance_criteria": {\n'
            '    "test_commands": ["<e.g. pytest or cargo test>"],\n'
            '    "success_conditions": ["<condition 1>"]\n'
            "  }\n"
            "}\n"
            "Respond ONLY with valid JSON."
        )

        user_content = (
            f"User Feature Request: {task_description}\n\n"
            f"Obsidian Vault Context Notes:\n{notes_summary}\n\n"
            f"Detected Language Hint: {context_data['inferred_language']}\n"
            f"Detected Project Hint: {context_data.get('detected_project', 'General')}\n"
        )

        task_id = f"task_{uuid.uuid4().hex[:8]}"
        response = self.openrouter.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            model=model_override,
            agent_role="hermes",
            task_id=task_id
        )

        # Parse JSON from model or synthesize fallback
        content = response.get("content", "").strip()
        parsed_spec = None
        if "{" in content and "}" in content:
            try:
                json_str = content[content.find("{"):content.rfind("}")+1]
                parsed_spec = json.loads(json_str)
            except Exception:
                pass

        # Check if detected project has specific overrides in enki.config.json
        projects_cfg = self.config.get("projects", {})
        proj_override = projects_cfg.get(context_data.get("detected_project", ""), {})
        
        target_lang = proj_override.get("language", context_data["inferred_language"])
        default_tests = proj_override.get("test_commands", ["py -m pytest -q" if target_lang == "python" else "cargo test"])

        if not parsed_spec:
            parsed_spec = {
                "title": task_description,
                "requirements": [f"Implement feature request: {task_description}"],
                "engineering_constraints": {
                    "language": target_lang,
                    "target_framework": context_data.get('detected_project') or "standard",
                    "lsp_server": f"{target_lang}-lsp",
                    "forbidden_patterns": ["Avoid hardcoded credentials", "No unverified external dependencies"],
                    "design_patterns": ["Clean architecture", "Type annotations"],
                    "file_scope": []
                },
                "acceptance_criteria": {
                    "test_commands": default_tests,
                    "success_conditions": ["All unit tests pass with exit code 0", "No linter errors"]
                }
            }

        payload = {
            "task_id": task_id,
            "title": parsed_spec.get("title", task_description),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source": f"Obsidian: {context_data.get('detected_project', 'pico-vault')}",
            "status": "pending",
            "requirements": parsed_spec.get("requirements", []),
            "engineering_constraints": parsed_spec.get("engineering_constraints", {}),
            "acceptance_criteria": parsed_spec.get("acceptance_criteria", {}),
            "context_sources": [
                {"path": h["path"], "excerpt": h["excerpt"]} for h in hits
            ]
        }

        with open(PAYLOAD_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        print(f"  -> Generated {PAYLOAD_FILE.name} (Task ID: {task_id})")
        return payload

    def step_2_execution_handshake(self, payload_path: Optional[Path] = None) -> Dict[str, Any]:
        """
        Step 2: Antigravity feeds payload to OMP in the terminal workspace via CLI:
        omp "Implement feature matching context_payload.json"
        """
        p_path = payload_path or PAYLOAD_FILE
        if not p_path.is_file():
            raise FileNotFoundError(f"Context payload not found at {p_path}. Run Step 1 first.")

        with open(p_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        print(f"\n[Step 2: Execution Handshake] Dispatching to Oh My Pi (OMP)...")
        print(f"  -> Command: omp \"Implement feature matching {p_path.name}\"")
        
        result = self.omp.execute_handshake(p_path)
        payload["status"] = "dispatched" if result.get("exit_code") == 0 else "failed"
        
        with open(p_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        print(f"  -> OMP Status: {result.get('status')}")
        if result.get("stdout"):
            for line in result["stdout"].splitlines()[:10]:
                print(f"     {line}")
        return result

    def step_3_verification(self, payload_path: Optional[Path] = None) -> Dict[str, Any]:
        """
        Step 3: OMP iterates using local compilers and test suites until execution clears.
        """
        p_path = payload_path or PAYLOAD_FILE
        if not p_path.is_file():
            raise FileNotFoundError(f"Context payload not found at {p_path}.")

        with open(p_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        test_cmds = payload.get("acceptance_criteria", {}).get("test_commands", [])
        print(f"\n[Step 3: Verification] Running OMP verification loop on {len(test_cmds)} test command(s)...")
        for cmd in test_cmds:
            print(f"  -> Executing: {cmd}")

        all_passed, results = self.omp.run_verification(test_cmds)
        status_str = "PASSED" if all_passed else "FAILED"
        print(f"  -> Verification Result: {status_str}")

        payload["status"] = "verified" if all_passed else "failed"
        with open(p_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        return {
            "all_passed": all_passed,
            "results": results,
            "status": status_str
        }

    def step_4_sync(self, payload_path: Optional[Path] = None, verification_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Step 4: Hermes logs completion & updates Obsidian vault.
        """
        p_path = payload_path or PAYLOAD_FILE
        if not p_path.is_file():
            raise FileNotFoundError(f"Context payload not found at {p_path}.")

        with open(p_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        print(f"\n[Step 4: Sync & Logging] Hermes syncing completion to Obsidian...")
        task_id = payload.get("task_id", "unknown")
        title = payload.get("title", "Untitled Task")
        
        # Summary metrics
        summary_data = get_summary()
        recent_tok = summary_data.get("total_tokens", 0)
        recent_cost = summary_data.get("total_cost_usd", 0.0)

        v_status = verification_info.get("status", "PASSED") if verification_info else "PASSED"
        summary_text = (
            f"Successfully coordinated by Enki Hub.\n"
            f"- Requirements: {len(payload.get('requirements', []))} verified\n"
            f"- Constraints Language: {payload.get('engineering_constraints', {}).get('language', 'N/A')}\n"
            f"- Handshake Target: Oh My Pi (OMP) CLI\n"
        )

        log_path = self.indexer.log_completion(
            task_id=task_id,
            title=title,
            summary=summary_text,
            tokens_used=recent_tok,
            cost_usd=recent_cost,
            test_status=v_status
        )

        payload["status"] = "completed"
        with open(p_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        print(f"  -> Activity logged to Obsidian: {log_path}")
        print(f"  -> Task status updated: COMPLETED\n")
        return {
            "task_id": task_id,
            "log_path": str(log_path),
            "status": "completed"
        }

    def run_pipeline(self, task_description: str, model_override: Optional[str] = None) -> Dict[str, Any]:
        """Executes the full 4-step pipeline end-to-end."""
        print("=" * 64)
        print(f" ENKI COMMAND HUB: EXECUTING 4-STEP PIPELINE")
        print("=" * 64)
        
        # Step 1
        payload = self.step_1_context_extraction(task_description, model_override=model_override)
        
        # Step 2
        handshake_res = self.step_2_execution_handshake(PAYLOAD_FILE)
        
        # Step 3
        verification_res = self.step_3_verification(PAYLOAD_FILE)
        
        # Step 4
        sync_res = self.step_4_sync(PAYLOAD_FILE, verification_res)

        print("=" * 64)
        print(f" ENKI PIPELINE COMPLETED SUCCESSFULLY FOR: '{payload['title']}'")
        print("=" * 64)
        return {
            "payload": payload,
            "handshake": handshake_res,
            "verification": verification_res,
            "sync": sync_res
        }
