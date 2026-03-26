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
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from api.telemetry import router as telemetry_router
from api.maneuver import router as maneuver_router
from api.simulate import router as simulate_router
from api.visualization import router as visualization_router
from engine.simulation import SimulationEngine

import structlog

# ── Logging ──────────────────────────────────────────────────────────────
# Structured logging via structlog — JSON output for production,
# human-readable colored output for dev. All log entries carry key-value
# context (satellite_id, CDM count, etc.) for distributed tracing.
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%S"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger("acm")

# ── Globals ──────────────────────────────────────────────────────────────
engine: SimulationEngine | None = None
engine_lock = asyncio.Lock()


def get_engine() -> SimulationEngine:
    """Dependency: returns the global SimulationEngine instance."""
    assert engine is not None, "SimulationEngine not initialized"
    return engine


# ── Auto-Seed ────────────────────────────────────────────────────────────

def _auto_seed(eng: SimulationEngine) -> None:
    """Seed the engine with demo data so the dashboard is populated on boot.

    Runs synchronously during startup (before the server accepts requests).
    Controlled by ACM_AUTO_SEED env var (defaults to "1" = enabled).
    """
    if os.environ.get("ACM_AUTO_SEED", "1") == "0":
        logger.info("AUTO_SEED | Skipped (ACM_AUTO_SEED=0)")
        return

    from generate_telemetry import build_telemetry_payload

    logger.info("AUTO_SEED | Generating 50 satellites + 10,000 debris (LEO mode)...")
    t0 = time.perf_counter()

    payload = build_telemetry_payload(
        n_satellites=50,
        n_debris=10_000,
        mode="leo",
        seed=42,
        timestamp="2026-03-12T08:00:00.000Z",
    )

    # Inject 20 threat debris on near-collision courses
    sat_objects = [o for o in payload["objects"] if o["type"] == "SATELLITE"]
    threats = _generate_threat_debris(sat_objects)
    payload["objects"].extend(threats)

    gen_t = time.perf_counter() - t0
    logger.info("AUTO_SEED | Generated %d objects in %.2fs", len(payload["objects"]), gen_t)

    # Ingest directly into the engine (no HTTP round-trip)
    t0 = time.perf_counter()
    result = eng.ingest_telemetry(payload["timestamp"], payload["objects"])
    logger.info(
        "AUTO_SEED | Ingested %d objects | CDMs: %d | %.2fs",
        result["processed_count"], result["active_cdm_warnings"],
        time.perf_counter() - t0,
    )

    # Run 5 simulation steps (600s each = 50 min) to activate the full pipeline
    logger.info("AUTO_SEED | Running 5 x 600s simulation steps...")
    for i in range(5):
        t0 = time.perf_counter()
        step_result = eng.step(600)
        logger.info(
            "AUTO_SEED | Step %d/5 | collisions=%d maneuvers=%d | %.2fs",
            i + 1,
            step_result.get("collisions_detected", 0),
            step_result.get("maneuvers_executed", 0),
            time.perf_counter() - t0,
        )

    logger.info("AUTO_SEED | Complete — dashboard ready")


def _generate_threat_debris(satellites: list[dict], n_per_sat: int = 3) -> list[dict]:
    """Create debris on genuinely crossing orbits that naturally produce CDMs.

    Instead of co-orbital offsets that diverge under J2, we seed debris on
    orbits at **different inclinations** that cross the satellite orbital
    planes at their ascending/descending nodes. The physics engine's 4-stage
    conjunction pipeline naturally detects these recurring close approaches.

    Three threat classes per target satellite:
    - YELLOW-band: same altitude, ±5° inclination offset → node-crossing
      conjunctions every half-orbit, producing persistent YELLOW CDMs.
    - RED-band: same altitude, ±15° inclination + 0.5–2 km radial offset →
      close approaches that trigger evasion burns.
    - Fast-crossing: ±25–30° inclination → high relative velocity encounters
      that test the conjunction assessment pipeline.
    """
    rng = np.random.default_rng(99)
    threats = []
    targets = satellites[:min(20, len(satellites))]

    for sat in targets:
        r_sat = np.array([sat["r"]["x"], sat["r"]["y"], sat["r"]["z"]])
        v_sat = np.array([sat["v"]["x"], sat["v"]["y"], sat["v"]["z"]])
        r_mag = np.linalg.norm(r_sat)
        v_mag = np.linalg.norm(v_sat)

        # Orbital frame: h = r × v (angular momentum), then build R/T/N
        h = np.cross(r_sat, v_sat)
        h_hat = h / np.linalg.norm(h)  # Normal to orbital plane
        r_hat = r_sat / r_mag
        t_hat = np.cross(h_hat, r_hat)  # Transverse (approx velocity dir)

        # Type 1: YELLOW-band — small inclination change (±5°)
        # Debris at same altitude but rotated orbital plane → node crossing
        for j in range(2):
            inc_offset = rng.uniform(3.0, 7.0) * (1 if j == 0 else -1)
            inc_rad = np.radians(inc_offset)
            # Rotate velocity vector around radial axis by inc_offset degrees
            cos_i, sin_i = np.cos(inc_rad), np.sin(inc_rad)
            v_deb = v_mag * (cos_i * t_hat + sin_i * h_hat)
            # Small position offset along track (±50–200 km) for phase diversity
            along_track_km = rng.uniform(50, 200) * (1 if j == 0 else -1)
            r_deb = r_sat + t_hat * along_track_km
            # Re-normalize to same altitude
            r_deb = r_deb / np.linalg.norm(r_deb) * r_mag

            threats.append({
                "id": f"THREAT-{sat['id']}-{j:02d}",
                "type": "DEBRIS",
                "r": {"x": float(r_deb[0]), "y": float(r_deb[1]), "z": float(r_deb[2])},
                "v": {"x": float(v_deb[0]), "y": float(v_deb[1]), "z": float(v_deb[2])},
            })

        # Type 2: RED-band — larger inclination (±12–18°) + small radial offset
        inc_offset = rng.uniform(12, 18) * rng.choice([-1, 1])
        inc_rad = np.radians(inc_offset)
        cos_i, sin_i = np.cos(inc_rad), np.sin(inc_rad)
        v_deb2 = v_mag * (cos_i * t_hat + sin_i * h_hat)
        radial_offset = rng.uniform(0.5, 2.0)  # 0.5–2 km → RED CDMs
        r_deb2 = r_sat + r_hat * radial_offset

        threats.append({
            "id": f"THREAT-{sat['id']}-02",
            "type": "DEBRIS",
            "r": {"x": float(r_deb2[0]), "y": float(r_deb2[1]), "z": float(r_deb2[2])},
            "v": {"x": float(v_deb2[0]), "y": float(v_deb2[1]), "z": float(v_deb2[2])},
        })

    return threats


# ── Lifespan ─────────────────────────────────────────────────────────────


async def _auto_step_loop(eng: SimulationEngine, lock: asyncio.Lock):
    """Background task: advance the simulation by 100s every 2s so the dashboard
    shows continuous orbital motion and trails build up in real-time."""
    step_interval = float(os.environ.get("ACM_AUTO_STEP_INTERVAL", "2"))
    step_size = int(float(os.environ.get("ACM_AUTO_STEP_SIZE", "100")))
    if step_size <= 0:
        return
    logger.info("AUTO_STEP | Running %ds sim every %.0fs", step_size, step_interval)
    loop = asyncio.get_running_loop()
    step_count = 0
    while True:
        await asyncio.sleep(step_interval)
        try:
            async with lock:
                if getattr(eng, "auto_step_enabled", True):
                    await loop.run_in_executor(None, eng.step, step_size)
                    step_count += 1
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("AUTO_STEP | Error: %s", exc, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize SimulationEngine on startup, auto-seed, cleanup on shutdown."""
    global engine
    logger.info("ACM-Orbital starting up — initializing SimulationEngine")
    engine = SimulationEngine()
    app.state.engine = engine
    app.state.engine_lock = engine_lock

    # Auto-seed in a thread so we don't block the event loop
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _auto_seed, engine)

    # Auto-step: disabled by default (README contract). Set ACM_AUTO_STEP=1 to enable.
    engine.auto_step_enabled = os.environ.get("ACM_AUTO_STEP", "0") == "1"
    auto_step_task = asyncio.create_task(_auto_step_loop(engine, engine_lock))

    yield
    auto_step_task.cancel()
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

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class NoCacheHTMLMiddleware(BaseHTTPMiddleware):
    """Prevent browsers from caching index.html so they always get the latest build."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        ct = response.headers.get("content-type", "")
        if "text/html" in ct:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheHTMLMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
# In production (Docker), the React build output lives in ./static/
# Skipped if ACM_NO_STATIC=1 (dev mode with Vite proxy).
static_dir = (Path(__file__).parent / "static").resolve()
if static_dir.exists() and os.environ.get("ACM_NO_STATIC", "0") != "1":
    
    # Mount assets properly for caching
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # SPA client-side routing fallback
    @app.get("/{full_path:path}")
    async def serve_spa_or_static(full_path: str):
        target_path = static_dir / full_path
        # Prevent path traversal
        if not str(target_path.resolve()).startswith(str(static_dir)):
            return FileResponse(static_dir / "index.html")
            
        if target_path.is_file():
            return FileResponse(target_path)
            
        return FileResponse(static_dir / "index.html")
