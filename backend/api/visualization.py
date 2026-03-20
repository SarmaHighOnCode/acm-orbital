"""
visualization.py — GET /api/visualization/snapshot
═══════════════════════════════════════════════════
Returns the current simulation state for frontend rendering.
Owner: Dev 2 (API Layer)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import ORJSONResponse

logger = logging.getLogger("acm.api.visualization")
router = APIRouter(tags=["visualization"])


def _get_engine(request: Request):
    return request.app.state.engine


@router.get("/visualization/snapshot", response_class=ORJSONResponse)
async def get_snapshot(request: Request):
    """Return current state snapshot of all satellites and debris."""
    engine = _get_engine(request)
    async with request.app.state.engine_lock:
        snapshot = engine.get_snapshot()
    return snapshot
