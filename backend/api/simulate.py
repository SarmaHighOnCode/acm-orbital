"""
simulate.py — POST /api/simulate/step
══════════════════════════════════════
Advances the simulation clock by the requested number of seconds.
Owner: Dev 2 (API Layer)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from schemas import SimulateStepRequest, SimulateStepResponse

logger = logging.getLogger("acm.api.simulate")
router = APIRouter(tags=["simulate"])


def _get_engine(request: Request):
    return request.app.state.engine


@router.post("/simulate/step", response_model=SimulateStepResponse)
async def simulate_step(
    payload: SimulateStepRequest,
    request: Request,
):
    """Advance simulation by step_seconds. Propagate, execute burns, detect collisions."""
    engine = _get_engine(request)
    async with request.app.state.engine_lock:
        result = engine.step(step_seconds=int(payload.step_seconds))
    logger.info(
        "SIMULATE | Step %.1fs | Collisions: %d | Maneuvers: %d",
        payload.step_seconds,
        result.get("collisions_detected", 0),
        result.get("maneuvers_executed", 0),
    )
    return SimulateStepResponse(**result)
