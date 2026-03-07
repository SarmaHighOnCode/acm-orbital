"""
telemetry.py — POST /api/telemetry
═══════════════════════════════════
Ingests satellite and debris state vectors from the grading system.
Owner: Dev 2 (API Layer)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from schemas import TelemetryRequest, TelemetryResponse

logger = logging.getLogger("acm.api.telemetry")
router = APIRouter(tags=["telemetry"])


def _get_engine(request: Request):
    return request.app.state.engine


@router.post("/telemetry", response_model=TelemetryResponse)
async def ingest_telemetry(
    payload: TelemetryRequest,
    request: Request,
):
    """Ingest telemetry data for satellites and debris."""
    engine = _get_engine(request)
    async with request.app.state.engine_lock:
        result = engine.ingest_telemetry(
            timestamp=payload.timestamp.isoformat(),
            objects=[obj.model_dump() for obj in payload.objects],
        )
    logger.info(
        "TELEMETRY | Ingested %d objects | CDMs active: %d",
        result.get("processed_count", 0),
        result.get("active_cdm_warnings", 0),
    )
    return TelemetryResponse(**result)
