"""GET /api/health — fully implemented liveness probe."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import Health

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok")
