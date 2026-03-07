"""
main.py — FastAPI Application Factory
══════════════════════════════════════
Entry point for the ACM-Orbital backend. Initializes the SimulationEngine
via lifespan context manager, mounts API routers, and serves the frontend
static build.

Owner: Dev 2 (API/Infrastructure)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

from api.telemetry import router as telemetry_router
from api.maneuver import router as maneuver_router
from api.simulate import router as simulate_router
from api.visualization import router as visualization_router
from engine.simulation import SimulationEngine

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("acm")

# ── Globals ──────────────────────────────────────────────────────────────
engine: SimulationEngine | None = None
engine_lock = asyncio.Lock()


def get_engine() -> SimulationEngine:
    """Dependency: returns the global SimulationEngine instance."""
    assert engine is not None, "SimulationEngine not initialized"
    return engine


# ── Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize SimulationEngine on startup, cleanup on shutdown."""
    global engine
    logger.info("ACM-Orbital starting up — initializing SimulationEngine")
    engine = SimulationEngine()
    app.state.engine = engine
    app.state.engine_lock = engine_lock
    yield
    logger.info("ACM-Orbital shutting down")
    engine = None


# ── App Factory ──────────────────────────────────────────────────────────

app = FastAPI(
    title="ACM-Orbital",
    description="Autonomous Constellation Manager — Orbital Mechanics API",
    version="1.0.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

# ── Middleware ───────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────
app.include_router(telemetry_router, prefix="/api")
app.include_router(maneuver_router, prefix="/api")
app.include_router(simulate_router, prefix="/api")
app.include_router(visualization_router, prefix="/api")


# ── Health Check ─────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Container health check endpoint."""
    return {
        "status": "healthy",
        "service": "acm-orbital",
        "engine_initialized": engine is not None,
    }


# ── Static Files (Frontend) ─────────────────────────────────────────────
# Mount AFTER routers so API routes take precedence.
# In production, the React build output lives in ./static/
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
