"""Backend settings: read from env with sensible defaults.

All knobs are resolved at import time from environment variables so the engine
provider and FastAPI app share one source of truth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Repo root = three levels up from this file: webapp/backend/settings.py -> repo/
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_STORE = "./.mdgraph"
DEFAULT_EMBEDDER = "mdgraph.providers.fastembed_embedder:FastEmbedProvider"

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@dataclass
class Settings:
    store_dir: Path
    embedder_path: str
    llm_path: str | None
    cors_origins: list[str] = field(default_factory=lambda: list(CORS_ORIGINS))


def _resolve_store(raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    return p


def get_settings() -> Settings:
    store_raw = os.environ.get("MDGRAPH_STORE", DEFAULT_STORE)
    embedder = os.environ.get("MDGRAPH_EMBEDDER", DEFAULT_EMBEDDER)
    llm = os.environ.get("MDGRAPH_LLM") or None
    return Settings(
        store_dir=_resolve_store(store_raw),
        embedder_path=embedder,
        llm_path=llm,
        cors_origins=list(CORS_ORIGINS),
    )
