"""
src/web/routes/vault.py
REST API endpoints for Obsidian vault notes discovery and task browsing (F36).
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Query, HTTPException

from src.obsidian_indexer import ObsidianIndexer
from src.config import load_config
from src.web.security import redact_data

router = APIRouter(prefix="/api/vault", tags=["vault"])


@router.get("/notes")
def list_or_search_notes(q: Optional[str] = Query(default=None)):
    """Searches or lists notes across the Obsidian vault."""
    indexer = ObsidianIndexer()
    if not indexer.is_vault_available():
        return {"available": False, "vault_path": str(indexer.vault_path), "notes": []}

    if q and q.strip():
        results = indexer.search_vault(q.strip(), max_results=20)
    else:
        results = indexer.search_vault("task", max_results=20)

    # Sanitize paths and content
    for item in results:
        if "abs_path" in item:
            item["abs_path"] = str(item["abs_path"])

    return redact_data({
        "available": True,
        "vault_path": str(indexer.vault_path),
        "notes": results
    })


@router.get("/notes/{rel_path:path}")
def get_note_content(rel_path: str):
    """Retrieves full content and frontmatter of a specific note."""
    indexer = ObsidianIndexer()
    if not indexer.is_vault_available():
        raise HTTPException(status_code=503, detail="Obsidian vault path is not accessible")

    note_file = (indexer.vault_path / rel_path).resolve()
    # Security: enforce that the target note is strictly within the vault directory
    if not str(note_file).startswith(str(indexer.vault_path.resolve())):
        raise HTTPException(status_code=403, detail="Access denied: outside vault boundary")

    if not note_file.is_file():
        raise HTTPException(status_code=404, detail=f"Note '{rel_path}' not found")

    try:
        with open(note_file, "r", encoding="utf-8") as f:
            content = f.read()
        return redact_data({
            "path": rel_path,
            "filename": note_file.name,
            "content": content
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
