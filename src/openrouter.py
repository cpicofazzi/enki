import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import load_config
from src.token_tracker import record_usage

# Fallback pricing per 1M tokens ($ Prompt, $ Completion)
DEFAULT_MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # OpenRouter models
    "anthropic/claude-3.7-sonnet": {"prompt": 3.00, "completion": 15.00},
    "anthropic/claude-3.7-sonnet:thinking": {"prompt": 3.00, "completion": 15.00},
    "anthropic/claude-3.5-sonnet": {"prompt": 3.00, "completion": 15.00},
    "anthropic/claude-3.5-haiku": {"prompt": 0.80, "completion": 4.00},
    "openai/gpt-6-sol": {"prompt": 2.00, "completion": 10.00},
    "openai/gpt-6-astra": {"prompt": 5.00, "completion": 25.00},
    "openai/gpt-6-luna": {"prompt": 0.50, "completion": 2.50},
    "openai/o3-mini": {"prompt": 1.10, "completion": 4.40},
    "openai/o3-mini-high": {"prompt": 1.10, "completion": 4.40},
    "openai/o1": {"prompt": 15.00, "completion": 60.00},
    "openai/gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "google/gemini-2.0-flash-001": {"prompt": 0.10, "completion": 0.40},
    "google/gemini-2.0-pro-exp-02-05": {"prompt": 0.00, "completion": 0.00},
    "deepseek/deepseek-r1": {"prompt": 0.55, "completion": 2.19},
    "deepseek/deepseek-chat": {"prompt": 0.14, "completion": 0.28},
    "qwen/qwen-2.5-coder-32b-instruct": {"prompt": 0.07, "completion": 0.14},
    "meta-llama/llama-3.3-70b-instruct": {"prompt": 0.12, "completion": 0.30},
    "meta-llama/llama-3.1-405b-instruct": {"prompt": 1.00, "completion": 2.00},
    "nousresearch/hermes-3-llama-3.1-70b": {"prompt": 0.40, "completion": 0.40},
    # OpenRouter Frontier & Discover Champions
    "anthropic/claude-opus-5.5": {"prompt": 15.00, "completion": 75.00},
    "anthropic/claude-fable-5.1": {"prompt": 3.00, "completion": 15.00},
    "anthropic/claude-sonnet": {"prompt": 3.00, "completion": 15.00},
    "openai/gpt-sol": {"prompt": 2.00, "completion": 10.00},
    "qwen/qwen3.8-max": {"prompt": 1.60, "completion": 6.40},
    "x-ai/grok-4.7": {"prompt": 2.00, "completion": 10.00},
    "x-ai/grok": {"prompt": 2.00, "completion": 10.00},
    "google/gemini-3.8-flash": {"prompt": 0.15, "completion": 0.60},
    "google/gemini-flash": {"prompt": 0.10, "completion": 0.40},
    "xiaomi/mimo-v2.6-pro": {"prompt": 0.15, "completion": 0.60},
    "stealth/space-bunny-alpha": {"prompt": 0.00, "completion": 0.00},
    "openai/gpt-oss-120b": {"prompt": 0.15, "completion": 0.60},
    "black-forest-labs/flux-1-schnell": {"prompt": 3.00, "completion": 3.00},
    "black-forest-labs/flux-1-dev": {"prompt": 25.00, "completion": 25.00},
    "openai/dall-e-3": {"prompt": 40.00, "completion": 40.00},
    # OpenRouter Value Leaders
    "inclusionai/ling-3.0-flash-vl": {"prompt": 0.021, "completion": 0.0616},
    "z-ai/glm-5.3-flash": {"prompt": 0.06, "completion": 0.20},
    "z-ai/glm": {"prompt": 0.06, "completion": 0.20},
    "inclusionai/ling-3.0-flash-fin:free": {"prompt": 0.00, "completion": 0.00},
    "xiaomi/mimo-v2.6-flash": {"prompt": 0.07, "completion": 0.28},
    "deepseek/deepseek-v4.1-flash": {"prompt": 0.08, "completion": 0.24},
    "deepseek/deepseek-v4-pro": {"prompt": 0.55, "completion": 2.19},
    "nvidia/nemotron-3-ultra:free": {"prompt": 0.00, "completion": 0.00},
    "poolside/laguna-s-2.1:free": {"prompt": 0.00, "completion": 0.00},
    "nvidia/nemotron-3.5-lightning:free": {"prompt": 0.00, "completion": 0.00},
    "dots-studio/dots3-note-preview:free": {"prompt": 0.00, "completion": 0.00},
    
    # OpenCode Zen models (Rates per 1M tokens from https://opencode.ai/data)
    "space-bunny": {"prompt": 0.00, "completion": 0.00},
    "deepseek-v4.1-flash": {"prompt": 0.30, "completion": 1.20},
    "deepseek-v4-flash": {"prompt": 0.30, "completion": 1.20},
    "deepseek-v4-pro": {"prompt": 0.55, "completion": 2.19},
    "deepseek-v4-flash-vision-exp": {"prompt": 0.30, "completion": 1.20},
    "muse-spark-1.3-contributor": {"prompt": 0.10, "completion": 0.20},
    "muse-spark-1.2-contributor": {"prompt": 0.10, "completion": 0.20},
    "mimo-v2.6-flash": {"prompt": 0.16, "completion": 0.32},
    "mimo-v2.6-pro": {"prompt": 0.15, "completion": 0.60},
    "mimo-v2.5": {"prompt": 0.16, "completion": 0.32},
    "nemotron-3-ultra": {"prompt": 0.00, "completion": 0.00},
    "nemotron-3.5-lightning": {"prompt": 0.00, "completion": 0.00},
    "longcat-2.5-preview": {"prompt": 0.30, "completion": 1.20},
    "glm-5.3-flash": {"prompt": 0.15, "completion": 0.50},
    "gpt-6-luna": {"prompt": 0.05, "completion": 0.25},
    "qwen3.8-flash": {"prompt": 0.10, "completion": 0.30},
    "ling-3.0-flash-fin": {"prompt": 0.042, "completion": 0.1232},
    "claude-3-7-sonnet": {"prompt": 3.00, "completion": 15.00},
    "claude-3-5-sonnet": {"prompt": 3.00, "completion": 15.00},
    "deepseek-r1": {"prompt": 0.55, "completion": 2.19},
    "deepseek-coder": {"prompt": 0.14, "completion": 0.28},
    "qwen-2.5-coder": {"prompt": 0.07, "completion": 0.14},
    "deepseek-v4-flash-free": {"prompt": 0.00, "completion": 0.00},
    "mimo-v2.5-free": {"prompt": 0.00, "completion": 0.00},
}

class GatewayClient:
    """Unified AI Model Gateway supporting OpenRouter and OpenCode Zen."""

    def __init__(self, gateway_name: Optional[str] = None, api_key: Optional[str] = None):
        self.config = load_config()
        self.gateway_name = gateway_name or self.config.get("active_gateway", "openrouter")
        
        gateways = self.config.get("gateways", {})
        gw_cfg = gateways.get(self.gateway_name, {})

        if self.gateway_name == "opencode_zen":
            self.base_url = gw_cfg.get("base_url", "https://opencode.ai/zen/v1")
            self.api_key = api_key or gw_cfg.get("api_key", os.environ.get("OPENCODE_API_KEY", ""))
            self.default_hermes_model = gw_cfg.get("hermes_model", "deepseek-v4.1-flash")
            self.default_omp_model = gw_cfg.get("omp_model", "deepseek-v4.1-flash")
            self.headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            }
        else:
            # Default OpenRouter
            self.gateway_name = "openrouter"
            self.base_url = gw_cfg.get("base_url", self.config.get("openrouter", {}).get("base_url", "https://openrouter.ai/api/v1"))
            self.api_key = api_key or gw_cfg.get("api_key", self.config.get("openrouter", {}).get("api_key", ""))
            self.default_hermes_model = gw_cfg.get("hermes_model", self.config.get("openrouter", {}).get("hermes_model", "anthropic/claude-opus-5.5"))
            self.default_omp_model = gw_cfg.get("omp_model", self.config.get("openrouter", {}).get("omp_model", "anthropic/claude-fable-5.1"))
            self.headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "HTTP-Referer": "https://github.com/enki-hub",
                "X-Title": "Enki Command Hub",
            }

        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    def calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimates cost based on model pricing per 1M tokens."""
        rates = DEFAULT_MODEL_PRICING.get(model, {"prompt": 1.00, "completion": 2.00})
        prompt_cost = (prompt_tokens / 1_000_000.0) * rates["prompt"]
        comp_cost = (completion_tokens / 1_000_000.0) * rates["completion"]
        return round(prompt_cost + comp_cost, 6)

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
        """Dispatches chat completions through the active gateway (OpenRouter or OpenCode Zen)."""
        selected_model = model or (
            self.default_hermes_model if agent_role == "hermes" else self.default_omp_model
        )

        gw_label = "OpenCode Zen" if self.gateway_name == "opencode_zen" else "OpenRouter"
        key_env_var = "OPENCODE_API_KEY" if self.gateway_name == "opencode_zen" else "OPENROUTER_API_KEY"

        if not self.api_key:
            # Simulation / Fallback mode
            sim_prompt_tokens = sum(len(m.get("content", "")) for m in messages) // 4
            sim_comp_tokens = 320
            sim_cost = self.calculate_cost(selected_model, sim_prompt_tokens, sim_comp_tokens)
            record_usage(
                agent_role=agent_role,
                model=f"{selected_model} (simulated via {self.gateway_name})",
                prompt_tokens=sim_prompt_tokens,
                completion_tokens=sim_comp_tokens,
                cost_usd=sim_cost,
                task_id=task_id,
                notes=f"Gateway: {gw_label}. Set {key_env_var} in .env for live calls."
            )
            return {
                "role": "assistant",
                "content": f"[Simulated Response for {agent_role} via {gw_label} using {selected_model}. Configure {key_env_var} to activate live inference.]",
                "model": selected_model,
                "gateway": self.gateway_name,
                "usage": {
                    "prompt_tokens": sim_prompt_tokens,
                    "completion_tokens": sim_comp_tokens,
                    "total_tokens": sim_prompt_tokens + sim_comp_tokens,
                    "cost_usd": sim_cost,
                    "simulated": True
                }
            }

        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if response_format:
            payload["response_format"] = response_format

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=self.headers,
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                usage = data.get("usage", {})
                
                p_tokens = usage.get("prompt_tokens", 0)
                c_tokens = usage.get("completion_tokens", 0)
                cost = self.calculate_cost(selected_model, p_tokens, c_tokens)
                
                record_usage(
                    agent_role=agent_role,
                    model=selected_model,
                    prompt_tokens=p_tokens,
                    completion_tokens=c_tokens,
                    cost_usd=cost,
                    task_id=task_id,
                    notes=f"Gateway: {gw_label}"
                )
                
                return {
                    "role": message.get("role", "assistant"),
                    "content": message.get("content", ""),
                    "model": data.get("model", selected_model),
                    "gateway": self.gateway_name,
                    "usage": {
                        "prompt_tokens": p_tokens,
                        "completion_tokens": c_tokens,
                        "total_tokens": p_tokens + c_tokens,
                        "cost_usd": cost,
                        "simulated": False
                    }
                }
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else ""
            raise RuntimeError(f"{gw_label} HTTP {e.code} Error: {e.reason} - {err_body}")
        except Exception as e:
            raise RuntimeError(f"{gw_label} Connection Error: {str(e)}")

    def generate_image(self, prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
        """Generates images via OpenRouter image generation models (e.g. Flux-1, DALL-E 3)."""
        selected_model = model or "black-forest-labs/flux-1-schnell"
        # OpenCode Zen is specialized for coding; route images through OpenRouter
        client = self if self.gateway_name == "openrouter" else GatewayClient(gateway_name="openrouter")
        return client.complete(
            messages=[{"role": "user", "content": f"Generate an image: {prompt}"}],
            model=selected_model,
            agent_role="system"
        )

# Backwards compatibility alias
OpenRouterClient = GatewayClient
