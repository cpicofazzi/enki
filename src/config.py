import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def load_env_file(env_path: Optional[Path] = None) -> None:
    """Lightweight .env parser without external dependencies."""
    if env_path is None:
        env_path = ROOT_DIR / ".env"
    if not env_path.is_file():
        return
    
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val

def load_config() -> Dict[str, Any]:
    """Loads and resolves Enki configuration."""
    load_env_file()
    config_path = ROOT_DIR / "config" / "enki.config.json"
    
    default_config = {
        "hub_name": "Enki Command Hub",
        "openrouter": {
            "api_key_env": "OPENROUTER_API_KEY",
            "base_url": "https://openrouter.ai/api/v1",
            "hermes_model": "nousresearch/hermes-3-llama-3.1-70b",
            "omp_model": "anthropic/claude-3.5-sonnet",
            "temperature": 0.2,
            "max_tokens": 4096
        },
        "obsidian": {
            "vault_path": "C:/Users/Christian Picofazzi/Documents/pico-vault",
            "tasks_folder": "40_Tasks",
            "projects_folder": "10_Projects",
            "knowledge_folder": "50_Knowledge",
            "inbox_folder": "00_Inbox",
            "log_file": "01_Dashboard/Enki_Activity_Log.md"
        },
        "omp": {
            "binary_command": "omp",
            "default_timeout_seconds": 300,
            "auto_verify": True,
            "lsp_enabled": True
        },
        "telemetry": {
            "db_path": "data/enki_telemetry.db",
            "monthly_budget_usd": 25.0
        }
    }
    
    if config_path.is_file():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                # merge top levels
                for k, v in user_config.items():
                    if isinstance(v, dict) and k in default_config:
                        default_config[k].update(v)
                    else:
                        default_config[k] = v
        except Exception as e:
            print(f"[Enki Config] Warning: Failed to parse {config_path}: {e}")

    # Active gateway resolution
    active_gw = os.environ.get("ENKI_ACTIVE_GATEWAY", default_config.get("active_gateway", "openrouter"))
    default_config["active_gateway"] = active_gw

    # Ensure gateways dict exists
    gateways = default_config.get("gateways", {})
    def clean_key(val: str) -> str:
        if not val or val.startswith("your_") or "placeholder" in val.lower():
            return ""
        return val

    if "openrouter" in gateways:
        openrouter_env = gateways["openrouter"].get("api_key_env", "OPENROUTER_API_KEY")
        raw_key = os.environ.get("OPENROUTER_API_KEY", os.environ.get(openrouter_env, ""))
        gateways["openrouter"]["api_key"] = clean_key(raw_key)
    if "opencode_zen" in gateways:
        zen_env = gateways["opencode_zen"].get("api_key_env", "OPENCODE_API_KEY")
        raw_key = os.environ.get("OPENCODE_API_KEY", os.environ.get(zen_env, ""))
        gateways["opencode_zen"]["api_key"] = clean_key(raw_key)

    default_config["gateways"] = gateways

    # Legacy openrouter block sync
    if "OPENROUTER_API_KEY" in os.environ:
        default_config["openrouter"]["api_key"] = os.environ["OPENROUTER_API_KEY"]
    else:
        api_env_key = default_config["openrouter"].get("api_key_env", "OPENROUTER_API_KEY")
        default_config["openrouter"]["api_key"] = os.environ.get(api_env_key, "")

    if "ENKI_OBSIDIAN_VAULT" in os.environ:
        default_config["obsidian"]["vault_path"] = os.environ["ENKI_OBSIDIAN_VAULT"]
    if "ENKI_HERMES_MODEL" in os.environ:
        default_config["openrouter"]["hermes_model"] = os.environ["ENKI_HERMES_MODEL"]
    if "ENKI_OMP_MODEL" in os.environ:
        default_config["openrouter"]["omp_model"] = os.environ["ENKI_OMP_MODEL"]

    return default_config


EXCLUDED_PROJECTS = {"Body.me App"}
DEFAULT_BASE_BRANCH = "feature/enki-ui"


def resolve_project_repo_path(
    project_name: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    fallback_path: Optional[Path] = None,
) -> Path:
    """
    Safely resolves repository path for a project with multi-tier fallback:
    1. Config: projects[project_name]["repo_path"] (expanded and validated).
    2. Environment Variable: ENKI_REPO_PATH_<PROJECT_SLUG> or ENKI_DEFAULT_REPO_PATH.
    3. Adjacent Folder: ROOT_DIR.parent / project_name (if exists).
    4. Safe Fallback: fallback_path if provided, else ROOT_DIR.
    """
    if config is None:
        config = load_config()

    projects = config.get("projects", {})

    if project_name and project_name in projects:
        proj_cfg = projects[project_name]
        raw_path = proj_cfg.get("repo_path")
        if raw_path:
            p = Path(raw_path).expanduser()
            if not p.is_absolute():
                p = (ROOT_DIR / p).resolve()
            if p.is_dir():
                return p

    # Tier 2: Environment variables
    if project_name:
        slug = project_name.upper().replace(" ", "_").replace("-", "_").replace(".", "_")
        env_key = f"ENKI_REPO_PATH_{slug}"
        if env_key in os.environ:
            p = Path(os.environ[env_key]).expanduser().resolve()
            if p.is_dir():
                return p

    if "ENKI_DEFAULT_REPO_PATH" in os.environ:
        p = Path(os.environ["ENKI_DEFAULT_REPO_PATH"]).expanduser().resolve()
        if p.is_dir():
            return p

    # Tier 3: Adjacent directory heuristic
    if project_name:
        adjacent = (ROOT_DIR.parent / project_name).resolve()
        if adjacent.is_dir() and (adjacent / ".git").exists():
            return adjacent

    # Tier 4: Safe fallback
    return (fallback_path or ROOT_DIR).resolve()


def get_active_projects(config: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """
    Returns only active projects, strictly filtering out excluded projects (e.g. Body.me App).
    """
    if config is None:
        config = load_config()

    projects = config.get("projects", {})
    active: Dict[str, Dict[str, Any]] = {}

    for name, p_cfg in projects.items():
        if name in EXCLUDED_PROJECTS or p_cfg.get("excluded") is True:
            continue
        normalized = dict(p_cfg)
        normalized["repo_path"] = str(resolve_project_repo_path(name, config))
        active[name] = normalized

    return active


def get_project_config(
    project_name: str,
    config: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """
    Returns normalized configuration for a specific project with resolved repo_path,
    or None if excluded / not found.
    """
    active = get_active_projects(config)
    return active.get(project_name)

