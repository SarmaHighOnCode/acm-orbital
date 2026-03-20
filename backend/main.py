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


# ── Auto-Seed ────────────────────────────────────────────────────────────

def _auto_seed(eng: SimulationEngine) -> None:
    """Seed the engine with demo data so the dashboard is populated on boot.

    Runs synchronously during startup (before the server accepts requests).
    Controlled by ACM_AUTO_SEED env var (defaults to "1" = enabled).
    """
    if os.environ.get("ACM_AUTO_SEED", "1") == "0":
        logger.info("AUTO_SEED | Skipped (ACM_AUTO_SEED=0)")
        return

    from generate_telemetry import build_telemetry_payload, generate_satellite_batch

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
    """Create debris on near-collision courses with the first 20 satellites.

    Three types of threats per satellite:
    - YELLOW-band (1-4 km, co-orbital): persists in conjunction for many orbits
      producing sustained YELLOW CDMs for the bullseye plot. These DON'T trigger
      evasion (only CRITICAL/RED do) so they stay visible permanently.
    - RED-band (0.2-0.8 km, slow approach): triggers evasion → delta-v chart data.
    - Crossing (2-5 km, fast approach): triggers maneuvers on close pass.
    """
    rng = np.random.default_rng(99)
    threats = []
    targets = satellites[:min(20, len(satellites))]

    for sat in targets:
        r_sat = np.array([sat["r"]["x"], sat["r"]["y"], sat["r"]["z"]])
        v_sat = np.array([sat["v"]["x"], sat["v"]["y"], sat["v"]["z"]])

        # Type 1: YELLOW-band co-orbital debris (1-4 km offset, same velocity)
        # These generate YELLOW CDMs that PERSIST because evasion only fires
        # on CRITICAL/RED, and YELLOW (1-5 km) is below the evasion threshold.
        for j in range(2):
            offset_dir = rng.normal(0, 1, 3)
            offset_dir /= np.linalg.norm(offset_dir)
            offset_km = rng.uniform(1.5, 3.5)  # 1.5-3.5 km → YELLOW CDMs
            r_deb = r_sat + offset_dir * offset_km
            # Nearly co-orbital: tiny velocity perturbation
            v_deb = v_sat.copy() + rng.normal(0, 0.00003, 3)

            threats.append({
                "id": f"THREAT-{sat['id']}-{j:02d}",
                "type": "DEBRIS",
                "r": {"x": float(r_deb[0]), "y": float(r_deb[1]), "z": float(r_deb[2])},
                "v": {"x": float(v_deb[0]), "y": float(v_deb[1]), "z": float(v_deb[2])},
            })

        # Type 2: RED-band approach debris (triggers evasion → delta-v data)
        cross_dir = rng.normal(0, 1, 3)
        cross_dir /= np.linalg.norm(cross_dir)
        offset_km2 = rng.uniform(2.0, 5.0)
        r_deb2 = r_sat + cross_dir * offset_km2
        closing_speed = rng.uniform(0.001, 0.003)
        v_deb2 = v_sat - cross_dir * closing_speed
        v_deb2 += rng.normal(0, 0.0003, 3)

        threats.append({
            "id": f"THREAT-{sat['id']}-02",
            "type": "DEBRIS",
            "r": {"x": float(r_deb2[0]), "y": float(r_deb2[1]), "z": float(r_deb2[2])},
            "v": {"x": float(v_deb2[0]), "y": float(v_deb2[1]), "z": float(v_deb2[2])},
        })

    return threats


# ── Lifespan ─────────────────────────────────────────────────────────────

def _reinject_threats(eng: SimulationEngine) -> None:
    """Re-position co-orbital YELLOW-band threats near current satellite positions.

    Called every step to ensure the bullseye plot always has CDMs to display.
    Directly updates debris positions (no full ingest/assessment — cheap O(S)).
    The next step()'s 4-stage assessment will pick them up.
    """
    rng = np.random.default_rng()
    sats = list(eng.satellites.values())
    targets = sats[:min(20, len(sats))]
    count = 0

    for sat in targets:
        r_sat = sat.position
        v_sat = sat.velocity
        for j in range(2):
            deb_id = f"THREAT-{sat.id}-{j:02d}"
            offset_dir = rng.normal(0, 1, 3)
            offset_dir /= np.linalg.norm(offset_dir)
            offset_km = rng.uniform(1.0, 3.0)

            if deb_id in eng.debris:
                eng.debris[deb_id].position = r_sat + offset_dir * offset_km
                eng.debris[deb_id].velocity = v_sat.copy()
                count += 1

    logger.debug("AUTO_STEP | Repositioned %d threat debris", count)


async def _auto_step_loop(eng: SimulationEngine, lock: asyncio.Lock):
    """Background task: advance the simulation by 100s every 2s so the dashboard
    shows continuous orbital motion and trails build up in real-time."""
    step_interval = float(os.environ.get("ACM_AUTO_STEP_INTERVAL", "2"))
    step_size = int(float(os.environ.get("ACM_AUTO_STEP_SIZE", "100")))
    if step_size <= 0:
        return
    logger.info("AUTO_STEP | Running %ds sim every %.0fs", step_size, step_interval)
    loop = asyncio.get_event_loop()
    step_count = 0
    while True:
        await asyncio.sleep(step_interval)
        try:
            async with lock:
                await loop.run_in_executor(None, eng.step, step_size)
                step_count += 1
                # Re-inject threats every step so CDMs persist across the
                # J2-perturbed propagation (co-orbital debris diverges within
                # a single 100s step due to differential RAAN precession)
                await loop.run_in_executor(None, _reinject_threats, eng)
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
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _auto_seed, engine)

    # Start background auto-stepping so the dashboard shows continuous motion
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
