import os
import re
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import load_config

def parse_frontmatter(content: str) -> Dict[str, Any]:
    """Simple parser for YAML frontmatter in Obsidian notes."""
    metadata = {}
    if not content.startswith("---"):
        return metadata
    
    parts = content.split("---", 2)
    if len(parts) < 3:
        return metadata
    
    fm_text = parts[1]
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            metadata[k] = v
    return metadata

class ObsidianIndexer:
    def __init__(self, vault_path: Optional[str] = None):
        cfg = load_config()
        self.vault_path = Path(vault_path or cfg.get("obsidian", {}).get("vault_path", "C:/Users/Christian Picofazzi/Documents/pico-vault"))
        self.log_rel_path = cfg.get("obsidian", {}).get("log_file", "01_Dashboard/Enki_Activity_Log.md")

    def is_vault_available(self) -> bool:
        return self.vault_path.is_dir()

    def search_vault(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Searches markdown notes in the vault matching keywords in query."""
        if not self.is_vault_available():
            return []

        stopwords = {"for", "and", "the", "with", "from", "that", "this", "have", "are", "were", "will", "your", "can", "build", "all", "out", "how", "what", "when", "where", "which"}
        query_terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2 and t.lower() not in stopwords]
        if not query_terms:
            query_terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
            
        matches = []

        # Target search paths: 10_Projects, 40_Tasks, 50_Knowledge, 00_Inbox
        for root, _, files in os.walk(self.vault_path):
            if ".obsidian" in root or ".trash" in root:
                continue
            for file in files:
                if not file.endswith(".md"):
                    continue
                file_path = Path(root) / file
                rel_path = file_path.relative_to(self.vault_path)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    
                    lower_text = text.lower()
                    lower_file = file.lower()
                    
                    # Heavy weight for title / filename match
                    title_score = sum(lower_file.count(term) * 25 for term in query_terms)
                    body_score = sum(min(lower_text.count(term), 10) for term in query_terms)
                    score = title_score + body_score
                    if score > 0:
                        fm = parse_frontmatter(text)
                        # Extract first 500 characters of meaningful body
                        body = text.split("---", 2)[-1] if text.startswith("---") else text
                        excerpt = " ".join(body.strip().split()[:75]) + "..."
                        matches.append({
                            "path": str(rel_path).replace("\\", "/"),
                            "absolute_path": str(file_path),
                            "title": fm.get("title", file_path.stem),
                            "score": score,
                            "metadata": fm,
                            "excerpt": excerpt
                        })
                except Exception:
                    continue

        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches[:max_results]

    def extract_context(self, task_description: str) -> Dict[str, Any]:
        """Hermes Context Extractor: compiles relevant notes & inferred constraints."""
        search_hits = self.search_vault(task_description, max_results=4)
        
        # Check if query matches a known project
        inferred_language = "python"  # default
        detected_project = None
        for hit in search_hits:
            p_name = hit.get("metadata", {}).get("project", "")
            if p_name:
                detected_project = p_name.strip("[]")
                break
        
        # Heuristics for language based on project notes or task text
        combined_text = (task_description + " " + " ".join(h["excerpt"] for h in search_hits)).lower()
        if "rust" in combined_text or "cargo" in combined_text:
            inferred_language = "rust"
        elif "react" in combined_text or "typescript" in combined_text or "express" in combined_text or "node" in combined_text:
            inferred_language = "typescript"
        elif "fastapi" in combined_text or "streamlit" in combined_text or "python" in combined_text:
            inferred_language = "python"

        return {
            "query": task_description,
            "detected_project": detected_project,
            "inferred_language": inferred_language,
            "hits": search_hits
        }

    def sync_task_note(self, task_title: str, summary: str) -> Optional[Path]:
        """Finds matching task note in 40_Tasks/ and marks it completed with checklist checked."""
        tasks_dir = self.vault_path / "40_Tasks"
        if not tasks_dir.is_dir():
            return None

        # Search for exact or closest task note
        best_file = None
        clean_title = re.sub(r'[^\w\s-]', '', task_title).strip().lower()
        for f in tasks_dir.glob("*.md"):
            stem_clean = re.sub(r'[^\w\s-]', '', f.stem).strip().lower()
            if stem_clean == clean_title or clean_title in stem_clean or stem_clean in clean_title:
                best_file = f
                break

        if not best_file:
            return None

        try:
            with open(best_file, "r", encoding="utf-8") as file_handle:
                content = file_handle.read()

            import datetime
            today_str = datetime.date.today().isoformat()

            # 1. Update frontmatter status and completed_date
            new_content = re.sub(r'status:\s*todo', 'status: done', content)
            new_content = re.sub(r'completed_date:\s*""?', f'completed_date: "{today_str}"', new_content)

            # 2. Check off action checklist items: - [ ] -> - [x]
            new_content = re.sub(r'-\s*\[\s*\]', '- [x]', new_content)

            # 3. Append completion note if not already present
            if "## Enki Completion Summary" not in new_content:
                new_content += f"\n\n## Enki Completion Summary\n> [!success] Verified & Completed by Enki Hub on {today_str}\n{summary}\n"

            with open(best_file, "w", encoding="utf-8") as file_handle:
                file_handle.write(new_content)

            return best_file
        except Exception as e:
            print(f"[Obsidian Sync Warning] Could not update task note {best_file}: {e}")
            return None

    def log_completion(
        self,
        task_id: str,
        title: str,
        summary: str,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        test_status: str = "PASSED"
    ) -> Path:
        """Logs task completion into the Obsidian vault activity log and updates task note."""
        # 1. Update the actual task note in 40_Tasks/
        synced_task = self.sync_task_note(title, summary)
        if synced_task:
            print(f"  -> Task Note Synchronized: {synced_task.name} (marked [x] done)")

        # 2. Append to central activity log
        log_file = self.vault_path / self.log_rel_path
        log_file.parent.mkdir(parents=True, exist_ok=True)

        import datetime
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        log_entry = f"""
### [{now_str}] Task Complete: {title}
- **Task ID**: `{task_id}`
- **Verification Status**: `{test_status}`
- **Tokens Consumed**: `{tokens_used:,}`
- **Estimated Cost**: `${cost_usd:.4f} USD`
- **Summary**:
  {summary}
---
"""
        # Create file if missing
        if not log_file.is_file():
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"# Enki Command Hub - Activity & Execution Log\n\nAutomated log entries recorded by Hermes & OMP.\n\n---\n")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)

        return log_file
