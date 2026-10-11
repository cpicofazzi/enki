"""
src/openrouter_catalog.py
OpenRouter Model Catalog Service for Enki.
Fetches, caches (24h TTL), merges curated presets from config/enki.config.json,
and provides robust offline fallbacks to built-in model definitions.
"""

import os
import sys
import json
import logging
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
import urllib.request
import urllib.error
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ModelPricing(BaseModel):
    """Normalized pricing per 1M tokens."""
    prompt_per_1m: float
    completion_per_1m: float
    raw_prompt_per_token: Optional[str] = None
    raw_completion_per_token: Optional[str] = None


class ModelCatalogItem(BaseModel):
    """Unified representation of a model in the OpenRouter catalog."""
    id: str
    name: str
    description: str = ""
    context_length: int = 128000
    pricing: ModelPricing
    is_curated: bool = False
    curated_tier: Optional[str] = None  # "frontier", "value", "champion", etc.
    intelligence_score: Optional[int] = None
    role: Optional[str] = None
    architecture: Dict[str, Any] = Field(default_factory=dict)
    top_provider: Dict[str, Any] = Field(default_factory=dict)


class CatalogCache(BaseModel):
    """Structure of data/openrouter_models_cache.json."""
    fetched_at: str
    ttl_seconds: int = 86400  # 24 hours
    models_count: int
    models: Dict[str, ModelCatalogItem]


class OpenRouterCatalog:
    """Service providing model catalog metadata, live pricing, and curated presets."""

    def __init__(
        self,
        cache_file: Optional[Union[str, Path]] = None,
        config_path: Optional[Union[str, Path]] = None,
        ttl_seconds: int = 86400,
        api_key: Optional[str] = None
    ):
        current_file = Path(__file__).resolve()
        root_dir = current_file.parent
        while root_dir.parent != root_dir and not (root_dir / "config" / "enki.config.json").is_file():
            root_dir = root_dir.parent

        self.root_dir = root_dir
        self.cache_file = Path(cache_file) if cache_file else (self.root_dir / "data" / "openrouter_models_cache.json")
        self.config_path = Path(config_path) if config_path else (self.root_dir / "config" / "enki.config.json")
        self.ttl_seconds = ttl_seconds
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")

    def is_cache_valid(self) -> bool:
        """Checks if local cache exists and was fetched within the 24-hour TTL."""
        if not self.cache_file.is_file():
            return False
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            fetched_at_str = data.get("fetched_at")
            if not fetched_at_str:
                return False
            fetched_at = datetime.datetime.fromisoformat(fetched_at_str)
            now = datetime.datetime.now(datetime.timezone.utc)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=datetime.timezone.utc)
            return (now - fetched_at).total_seconds() < self.ttl_seconds
        except Exception:
            return False

    def load_cache(self) -> Optional[CatalogCache]:
        """Loads and parses data/openrouter_models_cache.json."""
        if not self.cache_file.is_file():
            return None
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CatalogCache.model_validate(data)
        except Exception as e:
            logger.warning(f"Failed to load catalog cache: {e}")
            return None

    def save_cache(self, cache: CatalogCache) -> None:
        """Atomically persists cache to avoid corruption on abrupt process termination."""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.cache_file.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(cache.model_dump_json(indent=2))
            tmp_file.replace(self.cache_file)
        except Exception as e:
            logger.error(f"Failed to save catalog cache: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    def get_builtin_fallback_models(self) -> Dict[str, ModelCatalogItem]:
        """Provides hardcoded baseline model definitions matching src/openrouter.py."""
        baseline = {
            "anthropic/claude-opus-5.5": {"prompt": 15.00, "completion": 75.00, "name": "Claude Opus 5.5", "ctx": 200000},
            "anthropic/claude-fable-5.1": {"prompt": 3.00, "completion": 15.00, "name": "Claude Fable 5.1", "ctx": 200000},
            "anthropic/claude-3.7-sonnet": {"prompt": 3.00, "completion": 15.00, "name": "Claude 3.7 Sonnet", "ctx": 200000},
            "openai/gpt-6-astra": {"prompt": 5.00, "completion": 25.00, "name": "GPT-6 Astra", "ctx": 128000},
            "openai/gpt-6-sol": {"prompt": 2.00, "completion": 10.00, "name": "GPT-6 Sol", "ctx": 1050000},
            "openai/gpt-6-luna": {"prompt": 0.50, "completion": 2.50, "name": "GPT-6 Luna", "ctx": 128000},
            "z-ai/glm-5.3-flash": {"prompt": 0.06, "completion": 0.20, "name": "GLM 5.3 Flash", "ctx": 128000},
            "inclusionai/ling-3.0-flash-vl": {"prompt": 0.021, "completion": 0.0616, "name": "Ling 3.0 Flash VL", "ctx": 128000},
            "deepseek/deepseek-v4.1-flash": {"prompt": 0.08, "completion": 0.24, "name": "DeepSeek V4.1 Flash", "ctx": 128000},
            "google/gemini-2.0-flash-001": {"prompt": 0.10, "completion": 0.40, "name": "Gemini 2.0 Flash", "ctx": 1048576},
            "google/gemini-3.8-flash": {"prompt": 0.15, "completion": 0.60, "name": "Gemini 3.8 Flash", "ctx": 1048576},
            "qwen/qwen-2.5-coder-32b-instruct": {"prompt": 0.07, "completion": 0.14, "name": "Qwen 2.5 Coder 32B", "ctx": 32768},
            "qwen/qwen3.8-max": {"prompt": 1.60, "completion": 6.40, "name": "Qwen 3.8 Max", "ctx": 128000},
            "x-ai/grok-4.7": {"prompt": 2.00, "completion": 10.00, "name": "Grok 4.7", "ctx": 131072},
            "xiaomi/mimo-v2.6-flash": {"prompt": 0.07, "completion": 0.28, "name": "MiMo-V2.6-Flash", "ctx": 128000},
            "xiaomi/mimo-v2.6-pro": {"prompt": 0.15, "completion": 0.60, "name": "MiMo-V2.6-Pro", "ctx": 128000},
        }
        res: Dict[str, ModelCatalogItem] = {}
        for m_id, info in baseline.items():
            res[m_id] = ModelCatalogItem(
                id=m_id,
                name=info["name"],
                context_length=info["ctx"],
                pricing=ModelPricing(
                    prompt_per_1m=info["prompt"],
                    completion_per_1m=info["completion"]
                )
            )
        return res

    def merge_with_config(self, models: Dict[str, ModelCatalogItem]) -> Dict[str, ModelCatalogItem]:
        """Merges live/cached catalog items with curated presets from config/enki.config.json."""
        if not self.config_path.is_file():
            return models

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            gw = cfg.get("gateways", {}).get("openrouter", {})
            curated = gw.get("curated_leaders", {})

            # 1. Frontier leaders
            for item in curated.get("frontier_leaders", []):
                m_id = item.get("model_id")
                if m_id:
                    if m_id not in models:
                        models[m_id] = ModelCatalogItem(
                            id=m_id,
                            name=item.get("name", m_id),
                            pricing=ModelPricing(prompt_per_1m=5.0, completion_per_1m=25.0)
                        )
                    models[m_id].is_curated = True
                    models[m_id].curated_tier = "frontier"
                    models[m_id].intelligence_score = item.get("intelligence_score")
                    models[m_id].role = item.get("role")
                    if item.get("name"):
                        models[m_id].name = item["name"]

            # 2. Value leaders
            for item in curated.get("value_leaders", []):
                m_id = item.get("model_id")
                if m_id:
                    if m_id not in models:
                        models[m_id] = ModelCatalogItem(
                            id=m_id,
                            name=item.get("name", m_id),
                            pricing=ModelPricing(prompt_per_1m=0.06, completion_per_1m=0.20)
                        )
                    models[m_id].is_curated = True
                    models[m_id].curated_tier = "value"
                    models[m_id].role = item.get("role")
                    if item.get("name"):
                        models[m_id].name = item["name"]

            # 3. Category champions
            for _, item in curated.get("category_champions", {}).items():
                m_id = item.get("model_id")
                if m_id and m_id in models:
                    models[m_id].is_curated = True
                    models[m_id].curated_tier = "champion"
                    models[m_id].role = item.get("metric")

            # 4. Always latest aliases
            for alias, target_id in curated.get("always_latest_aliases", {}).items():
                if target_id in models and alias not in models:
                    alias_item = models[target_id].model_copy()
                    alias_item.id = alias
                    alias_item.name = f"{alias_item.name} (Latest Alias)"
                    models[alias] = alias_item

        except Exception as e:
            logger.error(f"Error merging enki.config.json curated leaders: {e}")

        return models

    def parse_api_models(self, raw_data: List[Dict[str, Any]]) -> Dict[str, ModelCatalogItem]:
        """Parses OpenRouter /api/v1/models response, converting per-token pricing to per-1M."""
        parsed: Dict[str, ModelCatalogItem] = {}
        for m in raw_data:
            m_id = m.get("id")
            if not m_id:
                continue
            name = m.get("name", m_id)
            desc = m.get("description", "")
            ctx = m.get("context_length") or m.get("top_provider", {}).get("context_length", 128000)

            raw_pricing = m.get("pricing", {})
            try:
                p_per_tok = float(raw_pricing.get("prompt", 0.0) or 0.0)
                c_per_tok = float(raw_pricing.get("completion", 0.0) or 0.0)
                p_1m = round(p_per_tok * 1_000_000, 4)
                c_1m = round(c_per_tok * 1_000_000, 4)
            except Exception:
                p_1m, c_1m = 1.0, 2.0

            pricing = ModelPricing(
                prompt_per_1m=p_1m,
                completion_per_1m=c_1m,
                raw_prompt_per_token=str(raw_pricing.get("prompt", "")),
                raw_completion_per_token=str(raw_pricing.get("completion", ""))
            )

            item = ModelCatalogItem(
                id=m_id,
                name=name,
                description=desc,
                context_length=int(ctx),
                pricing=pricing,
                architecture=m.get("architecture") or {},
                top_provider=m.get("top_provider") or {}
            )
            parsed[m_id] = item
        return parsed

    def fetch_live_catalog(self, timeout: float = 2.0) -> Optional[Dict[str, ModelCatalogItem]]:
        """Performs live HTTP GET to OpenRouter /api/v1/models."""
        try:
            url = "https://openrouter.ai/api/v1/models"
            headers = {"User-Agent": "Enki-Command-Hub/1.0"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_models = data.get("data", [])
                return self.parse_api_models(raw_models)
        except Exception as e:
            logger.info(f"OpenRouter catalog fetch failed ({e}); falling back.")
            return None

    def get_catalog(self, force_refresh: bool = False) -> Dict[str, ModelCatalogItem]:
        """
        Retrieves the model catalog.
        1. Returns valid cache (< 24h) unless force_refresh is True.
        2. Tries live fetch from OpenRouter API.
        3. Falls back to stale cache if API is unavailable.
        4. Falls back to built-in models if no cache exists.
        5. Merges with curated config presets.
        """
        # Step 1: Valid cache
        if not force_refresh and self.is_cache_valid():
            cached = self.load_cache()
            if cached and cached.models:
                return self.merge_with_config(cached.models)

        # Step 2: Attempt live fetch
        fetched = self.fetch_live_catalog()
        if fetched:
            merged = self.merge_with_config(fetched)
            cache_obj = CatalogCache(
                fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                ttl_seconds=self.ttl_seconds,
                models_count=len(merged),
                models=merged
            )
            self.save_cache(cache_obj)
            return merged

        # Step 3: Stale cache fallback
        stale = self.load_cache()
        if stale and stale.models:
            logger.warning("Using stale OpenRouter catalog cache due to offline/rate-limit state.")
            return self.merge_with_config(stale.models)

        # Step 4: Built-in definitions fallback
        logger.warning("Using built-in fallback model definitions (no cache available).")
        builtins = self.get_builtin_fallback_models()
        return self.merge_with_config(builtins)

    def get_model(self, model_id: str) -> Optional[ModelCatalogItem]:
        """Looks up a model by ID or alias."""
        catalog = self.get_catalog()
        return catalog.get(model_id)

    def get_pricing(self, model_id: str) -> Dict[str, float]:
        """Returns {'prompt': float, 'completion': float} cost per 1M tokens."""
        model = self.get_model(model_id)
        if model:
            return {
                "prompt": model.pricing.prompt_per_1m,
                "completion": model.pricing.completion_per_1m
            }
        return {"prompt": 1.00, "completion": 2.00}

    def list_models(
        self,
        curated_only: bool = False,
        tier: Optional[str] = None,
        query: Optional[str] = None
    ) -> List[ModelCatalogItem]:
        """Filters and searches models in catalog."""
        catalog = self.get_catalog()
        results = list(catalog.values())

        if curated_only:
            results = [m for m in results if m.is_curated]

        if tier:
            results = [m for m in results if m.curated_tier == tier]

        if query:
            q = query.lower()
            results = [m for m in results if q in m.id.lower() or q in m.name.lower()]

        return results

    def get_task_profile_model(self, task_category: str, tier: str = "frontier") -> str:
        """Returns the recommended model ID for a given task category and tier from enki.config.json."""
        default_model = "anthropic/claude-3.7-sonnet"
        if not self.config_path.is_file():
            return default_model

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            profiles = cfg.get("gateways", {}).get("openrouter", {}).get("task_profiles", {})
            cat_profile = profiles.get(task_category, {})

            if tier == "frontier":
                return cat_profile.get("frontier_opus") or cat_profile.get("sota_frontier") or default_model
            elif tier == "value":
                return cat_profile.get("value_leader") or default_model
            elif tier == "coding":
                return cat_profile.get("smartest_coding") or default_model
            return list(cat_profile.values())[0] if cat_profile else default_model
        except Exception:
            return default_model
