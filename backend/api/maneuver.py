"""
maneuver.py — POST /api/maneuver/schedule
══════════════════════════════════════════
Schedules evasion and recovery burn sequences for satellites.
Owner: Dev 2 (API Layer)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, HTTPException

from schemas import ManeuverRequest, ManeuverResponse

logger = logging.getLogger("acm.api.maneuver")
router = APIRouter(tags=["maneuver"])


def _get_engine(request: Request):
    return request.app.state.engine


@router.post("/maneuver/schedule", response_model=ManeuverResponse, status_code=202)
async def schedule_maneuver(
    payload: ManeuverRequest,
    request: Request,
):
    """Schedule a maneuver sequence for a satellite."""
    engine = _get_engine(request)
    async with request.app.state.engine_lock:
        result = engine.schedule_maneuver(
            satellite_id=payload.satelliteId,
            sequence=[
                {**cmd.model_dump(), "burnTime": cmd.burnTime.isoformat()}
                for cmd in payload.maneuver_sequence
            ],
        )
    logger.info(
        "MANEUVER | %s | Status: %s",
        payload.satelliteId,
        result.get("status", "UNKNOWN"),
    )
    if result.get("status") == "REJECTED" and result.get("reason"):
        if "max thrust" in result["reason"].lower():
            raise HTTPException(status_code=400, detail=result["reason"])
    return ManeuverResponse(**result)
