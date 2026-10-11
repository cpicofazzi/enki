"""
src/web/server.py
Uvicorn server launcher for Enki Web UI (F34, F35).
Strictly enforces loopback binding (127.0.0.1) and prevents external exposure.
"""

import sys
import uvicorn
from typing import Optional


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    reload: bool = False,
    log_level: str = "info"
) -> None:
    """
    Launches FastAPI server on strictly 127.0.0.1.
    Rejects any attempt to bind to non-local interfaces (such as 0.0.0.0).
    """
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"\n[SECURITY VIOLATION] Enki Web UI cannot bind to non-local interface '{host}'.")
        print("Enki strictly enforces local loopback binding (127.0.0.1) to prevent unauthorized network exposure.\n")
        sys.exit(1)

    print(f"\n" + "=" * 64)
    print(f"  ENKI WEB UI SERVER (FastAPI + React)")
    print(f"=" * 64)
    print(f"  Local Address : http://{host}:{port}")
    print(f"  API Docs      : http://{host}:{port}/docs")
    print(f"  Health Check  : http://{host}:{port}/api/health")
    print(f"  Security      : Loopback Only (127.0.0.1)")
    print(f"=" * 64 + "\n")

    uvicorn.run(
        "src.web.api:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level
    )


if __name__ == "__main__":
    run_server()
