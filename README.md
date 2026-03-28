# ACM-Orbital — Autonomous Constellation Manager

**Real-time collision avoidance for 50 satellites navigating 10,000+ debris objects in Low Earth Orbit.**

J2-perturbed DOP853 orbital propagation | 4-stage KDTree conjunction assessment | RTN-frame evasion planning | Tsiolkovsky fuel tracking | Real-Time operational dashboard

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Three.js](https://img.shields.io/badge/Three.js-WebGL-000000?logo=three.js&logoColor=white)](https://threejs.org)
[![Docker](https://img.shields.io/badge/Docker-ubuntu:22.04-2496ED?logo=docker&logoColor=white)](https://docker.com)

**[Technical Report (PDF)](docs/Technical%20Report.pdf)** | **[Video Demo](#)** *(link TBD)*

---

## Requirements

### Docker (recommended)

| Dependency | Version |
|---|---|
| Docker Engine | 24+ |
| Docker Compose | v2 (bundled with Docker Desktop) |

No other local tooling required — everything runs inside `ubuntu:22.04`.

### Manual / Development

**Backend (Python)**

| Package | Version |
|---|---|
| Python | 3.11 |
| fastapi | 0.135.1 |
| uvicorn | 0.41.0 |
| pydantic | 2.12.5 |
| numpy | 2.4.3 |
| scipy | 1.17.1 |
| sgp4 | 2.25 |
| orjson | 3.11.7 |
| structlog | 25.5.0 |
| python-dateutil | 2.9.0 |
| pytest | 9.0.2 |
| httpx | 0.28.1 |

**Frontend (Node)**

| Package | Version |
|---|---|
| Node.js | 18+ |
| React | ^18.3 |
| Three.js | ^0.165 |
| @react-three/fiber | ^8.16 |
| @react-three/drei | ^9.105 |
| Zustand | ^4.5 |
| Recharts | ^2.12 |
| satellite.js | ^5.0 |
| Vite | ^5.4 |
| Tailwind CSS | ^3.4 |

---

## Quick Start

```bash
git clone https://github.com/SarmaHighOnCode/acm-orbital.git
cd acm-orbital
docker compose build --no-cache
docker compose up
```

Wait for `AUTO_SEED | Complete — dashboard ready` in the terminal (~60 seconds), then open **http://localhost:8000**.

The engine automatically seeds **50 satellites + 10,000 debris objects** and runs 5 simulation steps so the dashboard is fully populated on first load.

**Note:** The engine starts paused. Auto-step is **disabled by default**. To start the autonomous simulation loop, toggle the **Auto-Step** switch in the dashboard header.

**Safety score starts at ~75%** — this is intentional. The initial seed deliberately places several satellites in high-risk proximity to debris so the collision avoidance engine has active threats to respond to on first load. As the simulation runs and the engine executes evasion burns, the safety score climbs toward 100%. This demonstrates the engine working in real-time rather than starting from a clean, threat-free state.

### Running Tests & API Injection

While the engine runs (when auto-step is toggled on), you can inject test vectors, schedule manual maneuvers, or run automated verification mid-simulation via the REST API:

**Inject Custom Telemetry:**
```bash
curl -X POST http://localhost:8000/api/telemetry \
  -H "Content-Type: application/json" \
  -d '{"timestamp": "2026-03-01T12:00:00Z", "objects": [{"id": "TEST-01", "type": "DEBRIS", "r": {"x": 7000, "y": 0, "z": 0}, "v": {"x": 0, "y": 7.5, "z": 0}}]}'
```

**Schedule Evasion Burns:**
```bash
curl -X POST http://localhost:8000/api/maneuver/schedule \
  -H "Content-Type: application/json" \
  -d '{"satelliteId": "SAT-01", "maneuver_sequence": [{"burn_id": "TEST-BURN", "burnTime": "2026-03-01T12:30:00Z", "deltaV_vector": {"x": 0.005, "y": 0, "z": 0}}]}'
```

**Run the Automated Test Suite:**
To run the 1,165 physics engine tests directly on your machine:
```bash
cd backend
pip install -r requirements.txt
python -m pytest tests/ -v
```

### Manual (Development)

```bash
# Backend
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend
npm ci && npm run dev
```

### Verify

```bash
curl http://localhost:8000/health
# {"status":"healthy","service":"acm-orbital","engine_initialized":true}
```

---

## Evaluation Criteria Mapping

How our implementation maps to each scoring category:

### Safety — 25%

| Requirement | Implementation | Location |
|---|---|---|
| Collision detection | 4-stage filter: altitude band (kills 85% debris) &#8594; KDTree spatial index &#8594; Brent TCA refinement &#8594; CDM emission | `backend/engine/collision.py` |
| Conjunction threshold | 100 m hard threshold (0.100 km); KDTree uses 200 km search radius for candidate filtering | `backend/config.py:CONJUNCTION_THRESHOLD_KM` |
| Autonomous evasion | CRITICAL/RED CDMs trigger automatic evasion + recovery burn sequences | `backend/engine/simulation.py:_auto_plan_maneuvers()` |
| Instantaneous scan | Separate KDTree scan at current positions catches inter-step collisions | `backend/engine/collision.py:check_collisions()` |
| 24-hour lookahead | CDM prediction window spans full 24h via DOP853 dense output | `backend/engine/collision.py:assess()` |
| Impulsive burn model | Velocity-only delta-v application, no position displacement during burn | `backend/engine/simulation.py:_execute_maneuvers()` |

### Fuel Efficiency — 20%

| Requirement | Implementation | Location |
|---|---|---|
| Tsiolkovsky tracking | Mass-aware exponential fuel depletion: `dm = m * (1 - exp(-dv / (Isp * g0)))` | `backend/engine/fuel_tracker.py` |
| T-axis priority | Burns prioritized along transverse axis (most fuel-efficient for phasing) | `backend/engine/maneuver_planner.py` |
| 36-point optimizer | Searches 3h window in 5-min steps for minimum-dv burn time | `backend/engine/maneuver_planner.py:plan_evasion()` |
| 15 m/s burn cap | Hard reject for user burns; auto-split with 610s spacing for planned burns | `backend/engine/maneuver_planner.py`, `fuel_tracker.py` |
| EOL graveyard | Hohmann deorbit at 2.5 kg fuel (5% threshold) prevents uncontrolled debris | `backend/engine/simulation.py:_check_eol()` |
| Recovery burns | Every evasion paired with Clohessy-Wiltshire recovery to nominal slot | `backend/engine/maneuver_planner.py:plan_recovery()` |

### Constellation Uptime — 15%

| Requirement | Implementation | Location |
|---|---|---|
| Station-keeping box | 10 km radius nominal slot tracking per satellite | `backend/config.py:STATION_KEEPING_RADIUS_KM` |
| Uptime scoring | Continuous time-outside-box tracking with exponential decay penalty | `backend/engine/simulation.py:_check_station_keeping()` |
| Fast recovery | Recovery burn scheduled when debris exceeds 50 km separation | `backend/engine/maneuver_planner.py` |
| Nominal drift prevention | Satellites re-checked for slot deviation after each propagation step | `backend/engine/simulation.py` |

### Algorithmic Speed — 15%

| Benchmark | Target | Achieved | How |
|---|---|---|---|
| 100K debris ingest | < 5 s | ~2 s | Vectorized NumPy array packing |
| KDTree build (100K) | < 3 s | < 100 ms | SciPy cKDTree |
| 50 queries into 100K | < 1 s | < 1 ms | Ball-point spatial query |
| Batch propagation (15K) | < 30 s | PASS | Single 6N-dimensional DOP853 call |
| Full tick (50 sats x 10K) | < 120 s | ~10 s | 4-stage filter eliminates 85% before indexing |
| Sub-O(N^2) proof | Required | Verified | Doubling D increases time < 2x (log scaling) |

### UI/UX — 15%

All six required visualization modules in real-time:

| Module | Spec Requirement | Implementation | Location |
|---|---|---|---|
| Ground Track Map | Mercator 2D projection (default view) | Canvas equirectangular with satellite markers, 90-min trails, predicted trajectories, terminator line, debris cloud, 6 ground stations, continental outlines | `frontend/src/components/GroundTrack.jsx` |
| 3D Globe | Optional enhancement | Three.js WebGL globe with day/night lighting, GMST rotation, city lights, sun-position tracking | `frontend/src/components/GlobeView.jsx` |
| Bullseye Plot | Polar conjunction chart | Canvas polar chart: radial = TCA, angle = Relative Approach Vector (atan2(δr_N, δr_T)), color = risk level, pulsing | `frontend/src/components/BullseyePlot.jsx` |
| Fuel Heatmap | Per-satellite fuel gauges | Sorted bar gauges with gradient coloring, fleet status counters, click-to-select | `frontend/src/components/FuelHeatmap.jsx` |
| Delta-V Chart | Fuel consumed vs collisions avoided | XY area chart with gradient fill, cumulative tracking | `frontend/src/components/DeltaVChart.jsx` |
| Maneuver Timeline | Gantt-style burn schedule | Per-satellite rows with burn blocks, 600s cooldown periods, blackout zone flagging, CDM markers, cooldown violations | `frontend/src/components/ManeuverTimeline.jsx` |

Additional: 2D/3D view toggle, click-to-select satellite across all panels, Zustand state management with 2s polling.

### Code Quality & Logging — 10%

| Aspect | Evidence |
|---|---|
| Architecture | 3-layer separation: Physics Engine (pure Python, zero HTTP) &#8594; API Layer (FastAPI + Pydantic) &#8594; Frontend (React + Canvas) |
| Single source of truth | All 16 physical constants frozen in `backend/config.py` |
| Type safety | Pydantic request/response schemas with strict validation |
| Test suite | 1,165 pytest-collected tests across 30 files (all passing) |
| Structured logging | `structlog` with JSON output for distributed tracing |
| No O(N^2) | Architectural invariant enforced across all modules |
| Configuration | `backend/config.py` imported everywhere, no magic numbers |

---

## Architecture

```
                    +---------------------------+
                    |   React 18 Dashboard      |
                    |   Canvas 2D + Three.js 3D  |
                    |   Zustand State Store      |
                    +------------+--------------+
                                 | HTTP/JSON (2s polling)
                    +------------+--------------+
                    |   FastAPI + Pydantic       |
                    |   5+ REST endpoints        |
                    |   orjson serialization      |
                    +------------+--------------+
                                 | Python calls
          +----------+-----------+-----------+----------+
          |          |           |           |          |
     Propagator  Collision  Maneuver    Fuel      Ground
      (DOP853)   (KDTree)   Planner   Tracker   Stations
                            (RTN)  (Tsiolkovsky)  (LOS)
```

| Layer | Technology | Lines of Code |
|---|---|---|
| Physics Engine | Python 3.11 + NumPy + SciPy | ~3,700 |
| API Layer | FastAPI + Pydantic + orjson | ~570 |
| Frontend | React 18 + Canvas + Three.js + Zustand | ~3,560 |
| Tests | pytest | ~11,300 |
| **Total** | | **~19,130** |

---

## API Reference

### POST `/api/telemetry`

Ingest ECI state vectors for satellites and debris.

```bash
curl -X POST http://localhost:8000/api/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": "2026-03-01T12:00:00Z",
    "objects": [{
      "id": "SAT-01", "type": "SATELLITE",
      "r": {"x": 7000, "y": 0, "z": 0},
      "v": {"x": 0, "y": 7.546, "z": 0}
    }]
  }'
```

**Response:** `{"status": "ACK", "processed_count": 1, "active_cdm_warnings": 0}`

### POST `/api/maneuver/schedule`

Schedule evasion/recovery burn sequences with full constraint validation.

```bash
curl -X POST http://localhost:8000/api/maneuver/schedule \
  -H "Content-Type: application/json" \
  -d '{
    "satelliteId": "SAT-01",
    "maneuver_sequence": [{
      "burn_id": "EVA-001",
      "burnTime": "2026-03-01T12:30:00Z",
      "deltaV_vector": {"x": 0.005, "y": 0, "z": 0}
    }]
  }'
```

**Response:** `{"status": "SCHEDULED", "validation": {"ground_station_los": true, "sufficient_fuel": true, "projected_mass_remaining_kg": 548.2}}`

### POST `/api/simulate/step`

Advance simulation by N seconds with full physics pipeline.

```bash
curl -X POST http://localhost:8000/api/simulate/step \
  -H "Content-Type: application/json" \
  -d '{"step_seconds": 600}'
```

**Response:** `{"status": "STEP_COMPLETE", "new_timestamp": "...", "collisions_detected": 0, "maneuvers_executed": 2}`

### GET `/api/visualization/snapshot`

Compressed frontend state: satellites, CDMs, debris cloud, maneuver log.
To drastically compress the JSON payload, `debris_cloud` uses flattened tuples format: `["DEB-99421", 12.42, -45.21, 400.5]` representing `[ID, lat, lon, alt]`.

```bash
curl http://localhost:8000/api/visualization/snapshot
```

### POST `/api/simulate/autostep`

Toggle the background auto-step simulation loop on or off.

```bash
curl -X POST http://localhost:8000/api/simulate/autostep \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

**Response:** `{"status": "AUTO_STEP_UPDATED", "auto_step_enabled": true}`

Auto-step is **disabled by default**. Use the dashboard toggle or this endpoint to start/stop the background simulation loop.

### GET `/health`

Container health check.

---

## Project Structure

```
acm-orbital/
  Dockerfile                    # Single-container ubuntu:22.04 build
  docker-compose.yml            # Local dev convenience
  TESTING.md                    # Detailed testing guide and strategies
  backend/
    main.py                     # FastAPI app + lifespan + auto-step loop
    config.py                   # 16 physical constants (single source of truth)
    schemas.py                  # Pydantic API contracts
    api/
      telemetry.py              # POST /api/telemetry
      simulate.py               # POST /api/simulate/step + /autostep
      maneuver.py               # POST /api/maneuver/schedule
      visualization.py          # GET /api/visualization/snapshot + /kessler-risk + /debris-density + /physics-proof + /mission-report
    engine/
      propagator.py             # J2-perturbed DOP853 batch propagation
      collision.py              # 4-stage KDTree conjunction assessment
      maneuver_planner.py       # RTN-frame evasion + recovery burns
      fuel_tracker.py           # Tsiolkovsky mass depletion
      ground_stations.py        # LOS elevation + ECEF/ECI transforms
      simulation.py             # 7-stage tick orchestrator
      models.py                 # Satellite/Debris data classes
      kessler.py                # Kessler cascade risk scoring
    data/
      ground_stations.csv       # 6 stations (Bengaluru, Svalbard, Goldstone, Punta Arenas, IIT Delhi, McMurdo)
    tests/                      # 1,165 tests across 30 files
  frontend/
    src/
      App.jsx                   # Root + 2s snapshot polling
      store.js                  # Zustand global state
      components/
        Dashboard.jsx           # 6-panel grid with 2D/3D toggle
        GroundTrack.jsx         # 2D Mercator ground track (default)
        GlobeView.jsx           # 3D Three.js globe with day/night
        BullseyePlot.jsx        # Polar conjunction proximity chart
        FuelHeatmap.jsx         # Fleet fuel gauges
        DeltaVChart.jsx         # Fuel vs collisions avoided
        ManeuverTimeline.jsx    # Gantt burn timeline with blackouts
        KesslerRiskGauge.jsx    # Kessler cascade risk visualization
      utils/
        api.js                  # Snapshot fetcher with retry
        coordinates.js          # ECI/geodetic transforms
        constants.js            # Shared frontend constants
  docs/
    technical_report.tex        # LaTeX source
    Technical Report.pdf        # Compiled 15-page report
```

---

## Testing

See the **[Testing Guide](TESTING.md)** for extensive details on test fixtures, stress profiles, precision benchmarks, and how to write new tests.

**1,165 tests collected | all passing | 30 test files**

```bash
cd backend && python -m pytest tests/ -q
```

| Category | Tests | What it validates |
|---|---|---|
| Core physics engine | 76 | J2 propagation, collision detection, fuel tracking, RTN burns, tick loop |
| Stress and flood | 47 | 100K debris ingest, KDTree scaling, ground station LOS, Tsiolkovsky precision |
| End-to-end integration | 31 | Full API + engine pipelines, CDM lifecycle, evasion sequences |
| Adversarial judge vectors | 20 | Burn timing edge cases, GMST accuracy, fast-path drift bounds |
| Extreme boundary cases | 16 | Numerical edge cases, near-zero fuel, simultaneous threats |
| System stress tests | 15 | Fleet wipeout recovery, race conditions, 50K snapshot serialization |
| Parametric sweeps | 100+ | Coverage gap audits, breaking audit vectors, chaos invariants |
| Unit tests | 850+ | Individual module validation across all engine components |

12 critical physics bugs discovered during development, all fixed with dedicated regression tests. Full details in the [Technical Report](docs/Technical%20Report.pdf).

---

## Key Algorithms

**Orbital Propagation** — J2-perturbed two-body dynamics integrated via DOP853 (8th-order Dormand-Prince, adaptive step-size). Vectorized batch: all N objects packed into a single 6N-dimensional ODE call. Energy conservation < 0.05% over 50 orbital periods.

**Conjunction Assessment** — Four-stage filter cascade reducing O(S*D) to O(S log D):
1. Altitude band pre-filter eliminates ~85% of debris
2. cKDTree spatial index with 200 km search radius
3. Brent's method TCA refinement on DOP853 dense polynomial
4. CDM emission with risk classification (CRITICAL/RED/YELLOW/GREEN)

**Maneuver Planning** — RTN orbital frame with T-axis priority for fuel efficiency. 36-point burn time search over 3-hour window. Paired evasion + Clohessy-Wiltshire recovery burns. LOS blackout guard with bidirectional rescheduling.

**Fuel Tracking** — Tsiolkovsky rocket equation with mass-aware depletion. EOL graveyard deorbit at 5% fuel threshold via Hohmann transfer.

---

## Limitations & Known Issues

**Pass-through collisions** — The endpoint-only instantaneous collision scan can miss objects closing at >14 km/s that pass through each other between check intervals. The 24-hour lookahead CDM pipeline (DOP853 dense polynomial + Brent TCA refinement) catches the vast majority of these events in advance, but sub-second midstep transits may be invisible to the post-step scan. This is a fundamental trade-off between scan resolution and computational cost.

**CW recovery accuracy** — Recovery burns use the Clohessy-Wiltshire linear relative motion model, which assumes near-circular orbits. For eccentricities above ~0.05 the linearization error grows and return-to-slot accuracy degrades. All LEO constellations targeted by this system operate well within this regime (e < 0.01).

**Step-duration uptime charging** — The station-keeping uptime metric charges the full step duration as "time outside the box" if the satellite is beyond the 10 km threshold at the endpoint check, even if it was inside for most of the step. This is a conservative design choice that avoids rewarding satellites that briefly exit and re-enter their slot.

## Deployment

- **Base image**: `ubuntu:22.04` (as required)
- **Port**: `8000` bound to `0.0.0.0`
- **Single container**: Frontend Vite build copied to `backend/static/`, served by FastAPI
- **Auto-seed**: 50 satellites + 10,000 debris populated on startup
- **Auto-step**: Disabled by default — toggleable via dashboard button or `POST /api/simulate/autostep`. When enabled, advances 100s every 2s. Manual `+100s Step` button available when paused.
- **Health check**: `GET /health` for container orchestration

---

## Deliverables

| Deliverable | Status | Location |
|---|---|---|
| Source code (GitHub) | Complete | This repository |
| Dockerfile (ubuntu:22.04) | Complete | `./Dockerfile` |
| Technical Report (PDF) | Complete | [`docs/Technical Report.pdf`](docs/Technical%20Report.pdf) |
| Video Demo (< 5 min) | Pending | *Link TBD* |

---

Built at IIT Delhi for the National Space Hackathon 2026.

## Known Limitations (Hackathon Context)
- **Physics Propagation:** The propagator is currently limited to J2 perturbations. Atmospheric drag, solar radiation pressure, and third-body effects are omitted. This may result in slightly optimistic lifetime and collision assessments for low-Earth orbit objects (<500km).
- **Worker Concurrency:** The engine shares state in-memory on a single API worker. Heavy simulation steps are pushed to an asyncio executor thread (with periodic GIL yielding) rather than a separate asynchronous worker queue.
- **REST vs WebSockets:** The high-frequency dashboard relies on HTTP polling. An optimization to pure Server-Sent Events (SSE) or WebSockets is recommended for scaling visualization bandwidth.
