"""
simulate.py — POST /api/simulate/step
══════════════════════════════════════
Advances the simulation clock by the requested number of seconds.
Owner: Dev 2 (API Layer)
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request

from schemas import SimulateStepRequest, SimulateStepResponse, SimulateAutoStepRequest

logger = logging.getLogger("acm.api.simulate")
router = APIRouter(tags=["simulate"])


def _get_engine(request: Request):
    return request.app.state.engine


@router.post("/reset")
@router.post("/simulate/reset")
async def simulate_reset(request: Request):
    """Reset the simulation engine state cleanly."""
    engine = _get_engine(request)
    async with request.app.state.engine_lock:
        engine.reset()
    logger.info("SIMULATE | Engine reset requested via API.")
    return {"status": "SUCCESS", "message": "Simulation reset completely."}


@router.post("/simulate/step", response_model=SimulateStepResponse)
async def simulate_step(
    payload: SimulateStepRequest,
    request: Request,
):
    """Advance simulation by step_seconds. Propagate, execute burns, detect collisions."""
    engine = _get_engine(request)
    loop = asyncio.get_running_loop()
    async with request.app.state.engine_lock:
        result = await loop.run_in_executor(None, engine.step, int(payload.step_seconds))
    logger.info(
        "SIMULATE | Step %.1fs | Collisions: %d | Maneuvers: %d",
        payload.step_seconds,
        result.get("collisions_detected", 0),
        result.get("maneuvers_executed", 0),
    )
    return SimulateStepResponse(**result)


@router.post("/simulate/autostep")
async def toggle_autostep(
    payload: SimulateAutoStepRequest,
    request: Request,
):
    """Toggle the background auto-step loop."""
    engine = _get_engine(request)
    async with request.app.state.engine_lock:
        engine.auto_step_enabled = payload.enabled
    logger.info("SIMULATE | Auto-step enabled set to: %s", payload.enabled)
    return {"status": "SUCCESS", "auto_step_enabled": getattr(engine, "auto_step_enabled", payload.enabled)}
