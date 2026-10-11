"""
src/web/security.py
Secret redaction filters and loopback validation for Enki Web UI (F35, F43).
Strictly prevents leakage of API keys, bearer tokens, and secrets in responses,
and enforces local loopback binding (127.0.0.1 / localhost).
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Union
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

# Root dir resolution
ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def get_secret_tokens() -> Set[str]:
    """
    Harvests sensitive tokens from environment and .env to redact from any output.
    Filters out short or trivial values to avoid false positives.
    """
    secrets: Set[str] = set()

    # Read from .env if present
    env_file = ROOT_DIR / ".env"
    if env_file.is_file():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    val = v.strip().strip("'\"")
                    if len(val) >= 6 and not val.startswith("your_") and "placeholder" not in val.lower():
                        secrets.add(val)
        except Exception:
            pass

    # Read from current process environment for key names
    secret_key_names = [
        "OPENROUTER_API_KEY", "OPENCODE_API_KEY", "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "API_KEY", "SECRET_KEY"
    ]
    for key in secret_key_names:
        val = os.environ.get(key, "").strip()
        if len(val) >= 6 and not val.startswith("your_") and "placeholder" not in val.lower():
            secrets.add(val)

    return secrets


SECRET_PATTERNS = [
    re.compile(r"sk-or-v1-[a-zA-Z0-9]{32,}", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE),
]


def redact_string(text: str, secrets: Set[str] = None) -> str:
    """Scans and redacts known API keys and regex patterns in a string."""
    if not isinstance(text, str) or not text:
        return text

    if secrets is None:
        secrets = get_secret_tokens()

    # Redact known explicit secret values
    for secret in secrets:
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED_API_KEY]")

    # Redact standard key patterns
    for pat in SECRET_PATTERNS:
        text = pat.sub("[REDACTED_KEY_PATTERN]", text)

    return text


def redact_data(data: Any, secrets: Set[str] = None) -> Any:
    """Recursively traverses dictionaries, lists, and strings to sanitize secrets."""
    if secrets is None:
        secrets = get_secret_tokens()

    if isinstance(data, str):
        return redact_string(data, secrets)
    elif isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            # If the dictionary key itself indicates an API key / secret, mask the value
            if any(term in k.lower() for term in ["api_key", "secret", "token", "password", "auth"]):
                if isinstance(v, str) and len(v) > 0:
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = v
            else:
                sanitized[k] = redact_data(v, secrets)
        return sanitized
    elif isinstance(data, list):
        return [redact_data(item, secrets) for item in data]
    elif isinstance(data, tuple):
        return tuple(redact_data(item, secrets) for item in data)
    return data


class LoopbackEnforcementMiddleware(BaseHTTPMiddleware):
    """
    Strict security middleware: only allows requests originating from loopback
    (127.0.0.1, ::1, or testclient).
    Rejects any remote host with HTTP 403 Forbidden.
    """
    async def dispatch(self, request: Request, call_next):
        client_host = request.client.host if request.client else "unknown"
        allowed_hosts = {"127.0.0.1", "::1", "localhost", "testclient"}
        
        # In Starlette TestClient, client.host is 'testclient'
        if client_host not in allowed_hosts and not client_host.startswith("127."):
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied: Enki Web UI binds strictly to loopback (127.0.0.1)."}
            )
        return await call_next(request)
