"""
src/web/api.py
FastAPI application instance for Enki Web UI (F34, F35, F36, F43).
Enforces loopback-only requests, registers all REST/SSE routes, and mounts static SPA assets.
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.web.security import LoopbackEnforcementMiddleware
from src.web.routes.runs import router as runs_router
from src.web.routes.stream import router as stream_router
from src.web.routes.workflows import router as workflows_router
from src.web.routes.models import router as models_router
from src.web.routes.vault import router as vault_router

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DIST_DIR = ROOT_DIR / "web" / "dist"

app = FastAPI(
    title="Enki Web UI",
    description="Dual-Agent Command Hub & Multi-Model DAG Orchestrator API",
    version="1.0.0"
)

# 1. Enforce strict local loopback binding & access (127.0.0.1)
app.add_middleware(LoopbackEnforcementMiddleware)

# 2. CORS policy restricted to local loopback origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Mount API Routers
app.include_router(runs_router)
app.include_router(stream_router)
app.include_router(workflows_router)
app.include_router(models_router)
app.include_router(vault_router)


@app.get("/api/health")
def health_check():
    """Health check endpoint for CLI and daemon monitors."""
    return {"status": "ok", "app": "Enki", "version": "1.0.0"}


# 4. Mount Built Frontend SPA Assets (if web/dist exists)
if DIST_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # Don't hijack /api calls
        if full_path.startswith("api"):
            return {"error": "Endpoint not found"}
        file_path = DIST_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        index_file = DIST_DIR / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return {"error": "UI assets not built yet"}
