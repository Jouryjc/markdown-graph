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

# Upload / archive-extraction safe defaults (all overridable via env).
DEFAULT_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024  # 50 MB upload cap
DEFAULT_MAX_ENTRIES = 5000  # max archive members
DEFAULT_MAX_TOTAL_UNCOMPRESSED = 200 * 1024 * 1024  # 200 MB total written
DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB per extracted file


@dataclass
class Settings:
    store_dir: Path
    embedder_path: str
    llm_path: str | None
    cors_origins: list[str] = field(default_factory=lambda: list(CORS_ORIGINS))
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES
    max_entries: int = DEFAULT_MAX_ENTRIES
    max_total_uncompressed: int = DEFAULT_MAX_TOTAL_UNCOMPRESSED
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES


def _resolve_store(raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    return p


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_settings() -> Settings:
    store_raw = os.environ.get("MDGRAPH_STORE", DEFAULT_STORE)
    embedder = os.environ.get("MDGRAPH_EMBEDDER", DEFAULT_EMBEDDER)
    llm = os.environ.get("MDGRAPH_LLM") or None
    return Settings(
        store_dir=_resolve_store(store_raw),
        embedder_path=embedder,
        llm_path=llm,
        cors_origins=list(CORS_ORIGINS),
        max_archive_bytes=_env_int(
            "MDGRAPH_MAX_ARCHIVE_BYTES", DEFAULT_MAX_ARCHIVE_BYTES
        ),
        max_entries=_env_int("MDGRAPH_MAX_ENTRIES", DEFAULT_MAX_ENTRIES),
        max_total_uncompressed=_env_int(
            "MDGRAPH_MAX_TOTAL_UNCOMPRESSED", DEFAULT_MAX_TOTAL_UNCOMPRESSED
        ),
        max_file_bytes=_env_int("MDGRAPH_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES),
    )
