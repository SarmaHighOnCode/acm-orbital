# 🚀 ACM_PRD.md — PRODUCT REQUIREMENTS DOCUMENT
## Autonomous Constellation Manager (ACM) | National Space Hackathon 2026
### Hosted by IIT Delhi | The Winning Architecture · Zero-Conflict Team Strategy · 5-Day Execution Plan

---

> **Prepared for:** Team [YOUR TEAM NAME]
> **Hosted by:** Indian Institute of Technology, Delhi
> **Document Version:** 1.0 · March 2026

---

# SECTION A — The Architectural PRD

## 1. Executive Summary & Scope

### What We Are Building

A single-container application comprising three layers:
1. A **Python/FastAPI REST API layer** exposing the exact endpoints specified in the problem statement
2. A **pure-math Physics Engine** that handles orbital propagation, spatial indexing, conjunction assessment, maneuver calculation, and fuel tracking
3. A **React + Three.js frontend dashboard** (the "Orbital Insight Visualizer") served as static files through the same FastAPI process

The grading system communicates exclusively with our API; the frontend is for human oversight and the UI/UX evaluation criteria.

---

## 2. Tech Stack Selection

Every technology choice is optimized for two constraints:
- **(a)** AI-assisted code generation quality (well-documented libraries with massive training data)
- **(b)** Hackathon speed (minimal boilerplate, battle-tested integrations)

### Backend: Python + FastAPI
### Frontend: React + Three.js
### Infrastructure

---

## 3. Core System Architecture

### 3.1 Three-Layer Architecture

The system is divided into three layers with strict unidirectional dependencies:
- The **Physics Engine** knows nothing about HTTP
- The **API Layer** translates HTTP to function calls
- The **Frontend** is a static SPA that polls the API

### 3.2 Project Directory Structure (Monorepo)

This is the exact folder structure your Git repository must follow. Each developer works exclusively within their assigned directories.

### 3.3 The Interface Contract: How Layers Communicate

The single most important file in the project is the interface between the API layer and the Physics Engine. Dev 1 and Dev 2 must agree on this contract on Day 1 and never break it. Here is the exact Python interface.

---

## 4. The Physics Engine Blueprint

This section translates the advanced orbital mechanics from the problem statement into plain algorithmic logic. You do not need to understand the physics — treat each subsection as a function specification that your AI tool must implement.

### 4.1 State Vectors: The Data Model

Every object (satellite or debris) is defined by **6 numbers** at any given time:
- 3D position **(x, y, z)** in kilometers
- 3D velocity **(vx, vy, vz)** in km/s

These are in the **ECI (Earth-Centered Inertial)** frame — origin is Earth's center, axes don't rotate with the Earth.

### 4.2 Orbital Propagation: Moving Objects Forward in Time

Propagation answers: *"If an object is at position P with velocity V right now, where will it be in T seconds?"*

Earth's gravity pulls everything toward the center, but Earth is not a perfect sphere — it bulges at the equator. The **J2 perturbation** accounts for this bulge and is the single most important correction for LEO accuracy.

The propagation function takes a current state vector and a time span, and returns the new state vector.

### 4.3 Conjunction Assessment: The Collision Detection Pipeline

> ⚠️ This is the highest-scoring algorithmic challenge — **25% Safety + 15% Speed = 40% of total grade**

The naive approach of checking every satellite against every debris object at every timestep is **O(N²)** per timestep:
- 50 satellites × 10,000 debris × 144 timesteps = **72 million distance calculations**
- Our multi-stage filter pipeline reduces this to **~7,200 actual calculations**

#### The Four-Stage Filter Cascade:

| Stage | Method | Purpose |
|---|---|---|
| Stage 1 | Altitude Band Filter | Reject debris outside ±50 km altitude shell |
| Stage 2 | KDTree Spatial Index | scipy.spatial.KDTree radius query at each timestep |
| Stage 3 | TCA Refinement | minimize_scalar on distance function around candidate window |
| Stage 4 | CDM Generation | Produce Conjunction Data Message for CRITICAL pairs |

### 4.4 Maneuver Planning: Evasion and Recovery Burns

When a **CRITICAL** conjunction is detected (miss distance < 100 meters), the system must calculate a delta-v vector to push the satellite to safety. Maneuvers are planned in the **RTN (Radial-Transverse-Normal)** frame:

| Axis | Effect |
|---|---|
| **R (Radial)** | Changes orbital altitude |
| **T (Transverse)** | Changes orbital phase (timing) — most fuel-efficient |
| **N (Normal)** | Changes orbital inclination |

The default evasion strategy is a **Transverse (T-axis) burn** — it slightly speeds up or slows down the satellite so it arrives at the conjunction point earlier or later than the debris. The recovery burn is an equal-and-opposite T-axis burn after the debris has passed.

### 4.5 Fuel Tracking: The Tsiolkovsky Equation

Every burn consumes fuel. The amount consumed depends on the **delta-v magnitude AND the current satellite mass** (heavier satellites burn more fuel for the same velocity change). This is the Tsiolkovsky rocket equation.

### 4.6 Ground Station Line-of-Sight

A maneuver command can only be sent when the satellite is **visible from at least one ground station**. Visibility requires:
- Satellite above the station's minimum elevation angle
- Accounting for Earth's curvature
- Mandatory **10-second signal delay**

### 4.7 The Simulation Tick: What Happens Every Step

When the grader calls `POST /api/simulate/step` with a `step_seconds` value, this is the exact sequence of operations:

1. **Propagate all objects** — For each satellite and debris, advance position and velocity by `step_seconds` using the propagator
2. **Execute scheduled maneuvers** — Apply `deltaV` to satellite velocity; deduct fuel via Tsiolkovsky; enforce 600s cooldown and 15 m/s max thrust
3. **Run conjunction assessment** — Check for collisions at the new timestamp; any pair with distance < 0.1 km is a collision; log it
4. **Update station-keeping status** — Check if each satellite is within 10 km of its nominal slot; if outside, mark as service outage; update uptime score
5. **Auto-plan maneuvers** — If new conjunctions predicted in next 24 hours, autonomously queue evasion + recovery burns; check LOS; pre-schedule if in blackout
6. **Check EOL thresholds** — If any satellite has `fuel_kg <= 2.5 kg`, schedule graveyard orbit maneuver
7. **Generate snapshot** — Update the immutable state snapshot for the visualization endpoint

---

## 5. Evaluation Criteria Alignment

Every architectural choice maps directly to the scoring rubric. Here is how we win each category.

---

# SECTION B — Zero-Collision Work Domains

This section divides the project into **3 strictly non-overlapping ownership domains**. If followed correctly, the three developers can work simultaneously for 5 days without a single merge conflict.

## Branching Strategy

The **ONLY** shared files are `backend/config.py` (physical constants) and `backend/schemas.py` (Pydantic models). These are defined on Day 1 and **frozen**. If they need changes, one person makes the change and both others pull.

---

## Domain 1: The Physics Engine

### Core Responsibilities

- **`OrbitalPropagator` class** — Implement J2-perturbed equations of motion; use `scipy solve_ivp` with DOP853; provide `propagate(state, dt)`; handle batch propagation for all 50 satellites
- **`ConjunctionAssessor` class** — Implement 4-stage filter cascade; KDTree spatial indexing via scipy; TCA refinement via `minimize_scalar`; generate CDM warnings
- **`ManeuverPlanner` class** — RTN-to-ECI conversion; evasion burn calculation (T-axis preferred); recovery burn calculation; enforce 600s cooldown, 15 m/s max thrust, 10s signal delay; check ground station LOS
- **`FuelTracker` class** — Implement Tsiolkovsky mass depletion; track per-satellite fuel; trigger EOL graveyard maneuver at 5% threshold
- **`SimulationEngine` class** — Master orchestrator; maintains simulation clock; calls propagator, collision assessor, maneuver planner, and fuel tracker in correct sequence on each tick; produces immutable state snapshots

### AI Prompting Strategy for Dev 1

---

## Domain 2: REST API Layer & Infrastructure

### Core Responsibilities

- **FastAPI Application Factory** — Lifespan context manager initializing `SimulationEngine`; configure `ORJSONResponse`, `GZipMiddleware`, CORS; mount API routers under `/api/`; mount frontend static files at root `/`
- **Pydantic Schemas (`schemas.py`)** — Define exact request/response models: `TelemetryRequest`, `ManeuverRequest`, `SimulateStepRequest`, `SnapshotResponse` — these ARE the interface contract
- **Four API Route Handlers**:
  - `POST /api/telemetry`
  - `POST /api/maneuver/schedule`
  - `POST /api/simulate/step`
  - `GET /api/visualization/snapshot`
- **Dockerfile** — `ubuntu:22.04` base; Python 3.11 + Node.js 18; pip install backend deps; `npm ci + npm run build` frontend; copy build output to `backend/static/`; expose port 8000; CMD uvicorn
- **Structured Logging** — Log every maneuver execution, collision event, and EOL trigger with timestamps (scores under Code Quality — 10%)

### AI Prompting Strategy for Dev 2

---

## Domain 3: The 60FPS Orbital Insight Frontend

### Core Responsibilities — The 5 Required Visualization Modules

#### 1. 3D Globe View (`GlobeView.jsx`)
- Textured Earth sphere (`Three.js SphereGeometry`)
- Debris as `THREE.Points` with `BufferGeometry` (single draw call for 10K+)
- Satellites as `THREE.InstancedMesh` with per-instance color by status (`green=nominal`, `yellow=evading`, `red=EOL`)
- Orbit trail lines for selected satellite

#### 2. 2D Ground Track Map (`GroundTrack.jsx`)
- Equirectangular (Mercator-ish) projection with Earth texture background
- Real-time satellite position markers
- 90-minute historical trail (solid line) + 90-minute predicted trajectory (dashed line)
- Day/night terminator shadow overlay

#### 3. Conjunction Bullseye Plot (`BullseyePlot.jsx`)
- Polar chart centered on selected satellite
- Radial axis = Time to Closest Approach; Angular axis = approach vector direction
- Debris markers color-coded: `Green (>5km)` · `Yellow (<5km)` · `Red (<1km)`

#### 4. Telemetry Heatmaps (`FuelHeatmap.jsx`)
- Visual fuel gauge bar for every satellite (gradient: `green > yellow > red`)
- Delta-v cost analysis chart: "Fuel Consumed vs Collisions Avoided" (Recharts)
- Fleet status summary: nominal / evading / recovering / EOL counts

#### 5. Maneuver Timeline Gantt (`ManeuverTimeline.jsx`)
- Chronological schedule of past and future burns
- Color blocks: `Burn Start/End (blue)` · `600s Cooldown (gray)` · `Conflicting commands (red)` · `Blackout zone overlaps (orange)`
- Horizontal scrollable timeline

### Performance Architecture
### AI Prompting Strategy for Dev 3

---
