"""FastAPI application factory + module-level ``app``.

Mounts all 7 routers under /api, configures CORS from settings, and serves the
built frontend (webapp/frontend/dist) at / when present.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config_store import apply_overlay_to_env, load_overlay
from .routers import (
    config,
    documents,
    entities,
    graph,
    health,
    index,
    query,
    sag,
    stats,
    upload,
)
from .settings import get_settings

_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app() -> FastAPI:
    # Apply the persisted config overlay to os.environ BEFORE reading settings /
    # building the engine, so a saved overlay auto-takes-effect on a fresh process.
    apply_overlay_to_env(load_overlay())

    settings = get_settings()
    app = FastAPI(title="mdgraph webapp")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in (
        health,
        stats,
        query,
        graph,
        documents,
        entities,
        index,
        upload,
        config,
        sag,
    ):
        app.include_router(module.router)

    # Serve the built SPA at / if it exists. html=True so client-side routes
    # (e.g. /graph, /doc/:id) fall back to index.html.
    if _FRONTEND_DIST.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(_FRONTEND_DIST), html=True),
            name="frontend",
        )

    return app


app = create_app()
