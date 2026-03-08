# 🛰️ NSH_PROBLEM_STATEMENT.md — OFFICIAL PROBLEM STATEMENT
## Orbital Debris Avoidance & Constellation Management System | National Space Hackathon 2026
### Hosted by IIT Delhi | Autonomous Constellation Manager (ACM)

---

# 1. Background

Over the past decade, Low Earth Orbit (LEO) has transformed from a vast frontier into a highly congested orbital highway. The rapid deployment of commercial mega-constellations has exponentially increased the number of active payloads. Alongside these operational satellites, millions of pieces of space debris — ranging from defunct rocket bodies and shattered solar panels to stray bolts — orbit the Earth at hypervelocity speeds exceeding **27,000 km/h**.

This severe congestion brings us perilously close to the **Kessler Syndrome** — a theoretical scenario where the density of objects in LEO becomes high enough that a single collision generates a cloud of shrapnel, triggering a cascading chain reaction of further collisions. Because kinetic energy scales with the square of velocity, even a collision with a centimeter-sized fragment can completely destroy a satellite and instantly generate thousands of new trackable debris pieces.

Currently, satellite collision avoidance is a heavily **manual, human-in-the-loop process**. Ground-based radar networks (such as the US Space Surveillance Network) track large debris and issue **Conjunction Data Messages (CDMs)** when a close approach is predicted. Flight Dynamics Officers (FDOs) on Earth must manually evaluate these warnings, calculate the necessary orbital perturbations, and uplink thruster maneuver commands.

This legacy approach suffers from critical bottlenecks that make it unsustainable for the future of spaceflight:

- **Scalability Limits** — Manual evaluation cannot scale to handle constellations comprising thousands of satellites, which may collectively face hundreds of conjunction warnings daily
- **Communication Latency & Blackouts** — Satellites frequently pass through "blackout zones" where no ground station has line-of-sight; if a conjunction is predicted while a satellite is out of contact, ground control is entirely helpless
- **Suboptimal Resource Management** — Fuel in space is a finite, non-replenishable resource; human operators struggle to globally optimize ∆v across an entire fleet while ensuring satellites return to their assigned orbital slots

> **The Challenge:** Design an **Autonomous Constellation Manager (ACM)** — a robust, high-performance software suite capable of ingesting high-volume orbital telemetry, predicting conjunctions efficiently without O(N²) bottlenecks, and autonomously executing optimal evasion and return maneuvers.

---

# 2. Core Objectives

The primary objective is to architect, develop, and deploy an **Autonomous Constellation Manager (ACM)** — a centralized, high-performance "brain" for a fleet of **50+ active satellites** navigating a hazardous environment populated by tens of thousands of tracked space debris fragments.

Your ACM must handle the following core responsibilities:

- **High-Frequency Telemetry Ingestion** — Continuously process incoming orbital state vectors — position (r⃗) and velocity (v⃗) in the ECI coordinate frame — representing the real-time kinematic states of both your controlled constellation and the uncontrolled debris field
- **Predictive Conjunction Assessment (CA)** — Forecast potential collisions (CDMs) up to **24 hours** in the future using efficient spatial indexing algorithms to calculate the Time of Closest Approach (TCA) without O(N²) bottlenecks
- **Autonomous Collision Avoidance (COLA)** — When a critical conjunction (miss distance < 100 meters) is predicted, autonomously calculate and schedule an evasion maneuver, determining the optimal burn window and exact ∆v vector, factoring in thruster cooldowns and orbital mechanics
- **Station-Keeping and Orbital Recovery** — Calculate and execute a subsequent "recovery burn" to correct orbital drift and return the payload to its designated spatial bounding box as quickly as possible
- **Propellant Budgeting & EOL Management** — Strictly track fuel budgets per the Tsiolkovsky rocket equation; if a satellite's fuel reserves drop to a critical threshold (~5%), preemptively schedule a final maneuver to move it into a safe graveyard orbit
- **Global Multi-Objective Optimization** — Balance two opposing metrics: maximize **Constellation Uptime** (time satellites spend in their assigned slots) while minimizing total **Fuel Expenditure** across the fleet

---

# 3. Physics, Coordinate Systems, and Orbital Mechanics

## 3.1 Reference Frames and State Vectors

All kinematic data is grounded in the **Earth-Centered Inertial (ECI)** coordinate system (J2000 epoch). The ECI frame is non-rotating relative to the stars, making it the standard for calculating orbital trajectories without fictitious forces.

Every object in the simulation is defined by a **6-dimensional State Vector** at a given time `t`:

```
S(t) = [r⃗(t), v⃗(t)]ᵀ = [x, y, z, vx, vy, vz]ᵀ
```

- Position `r⃗` is in **kilometers (km)**
- Velocity `v⃗` is in **kilometers per second (km/s)**

## 3.2 Orbital Propagation Models

Participants **cannot** assume simple unperturbed two-body Keplerian orbits. Due to Earth's equatorial bulge, orbits experience nodal regression and apsidal precession. Your propagation engine must account for the **J2 perturbation**.

The equations of motion are:

```
d²r⃗/dt² = -(µ / |r⃗|³) · r⃗ + a⃗_J2
```

Where the J2 acceleration vector is:

```
a⃗_J2 = (3/2) · (J2 · µ · RE²) / |r⃗|⁵  ×  [x(5z²/|r⃗|² - 1),  y(5z²/|r⃗|² - 1),  z(5z²/|r⃗|² - 3)]
```

**Physical Constants:**

| Constant | Value |
|---|---|
| `µ` (Earth gravitational parameter) | `398600.4418 km³/s²` |
| `RE` (Earth radius) | `6378.137 km` |
| `J2` (oblateness coefficient) | `1.08263 × 10⁻³` |

> Use robust numerical integration methods (e.g., **Runge-Kutta 4th Order / DOP853**) to propagate states forward in time.

## 3.3 Conjunction Thresholds

A collision is defined mathematically when the Euclidean distance between a satellite and any debris object falls below the critical threshold:

```
|r⃗_sat(t) - r⃗_deb(t)| < 0.100 km  (100 meters)
```

---

# 4. API Specifications and Constraints

Your ACM must expose a robust **RESTful API on port 8000**. The simulation engine communicates with your software exclusively through these endpoints.

## 4.1 Telemetry Ingestion API

This endpoint will be flooded with high-frequency state vector updates. Your system must parse this data and asynchronously update its internal physics state.

**Endpoint:** `POST /api/telemetry`

**Request Body:**
```json
{
  "timestamp": "2026-03-12T08:00:00.000Z",
  "objects": [
    {
      "id": "DEB-99421",
      "type": "DEBRIS",
      "r": {"x": 4500.2, "y": -2100.5, "z": 4800.1},
      "v": {"x": -1.25, "y": 6.84, "z": 3.12}
    }
  ]
}
```

**Response (200 OK):**
```json
{
  "status": "ACK",
  "processed_count": 1,
  "active_cdm_warnings": 3
}
```

## 4.2 Maneuver Scheduling API

When your system calculates an evasion or recovery burn, it must submit the maneuver sequence here. The simulation will validate line-of-sight constraints, apply the ∆v instantaneously at the specified `burnTime`, and deduct the corresponding fuel mass.

**Endpoint:** `POST /api/maneuver/schedule`

**Request Body:**
```json
{
  "satelliteId": "SAT-Alpha-04",
  "maneuver_sequence": [
    {
      "burn_id": "EVASION_BURN_1",
      "burnTime": "2026-03-12T14:15:30.000Z",
      "deltaV_vector": {"x": 0.002, "y": 0.015, "z": -0.001}
    },
    {
      "burn_id": "RECOVERY_BURN_1",
      "burnTime": "2026-03-12T15:45:30.000Z",
      "deltaV_vector": {"x": -0.0019, "y": -0.014, "z": 0.001}
    }
  ]
}
```

**Response (202 Accepted):**
```json
{
  "status": "SCHEDULED",
  "validation": {
    "ground_station_los": true,
    "sufficient_fuel": true,
    "projected_mass_remaining_kg": 548.12
  }
}
```

## 4.3 Simulation Fast-Forward (Tick) API

The grader will advance the simulation time by arbitrary steps. During this "tick", your engine must integrate the physics for all objects and execute any maneuvers scheduled within that time window.

**Endpoint:** `POST /api/simulate/step`

**Request Body:**
```json
{
  "step_seconds": 3600
}
```

**Response (200 OK):**
```json
{
  "status": "STEP_COMPLETE",
  "new_timestamp": "2026-03-12T09:00:00.000Z",
  "collisions_detected": 0,
  "maneuvers_executed": 2
}
```

---

# 5. Detailed Maneuver & Navigation Logic

## 5.1 Propulsion Constraints and Fuel Mass Depletion

Every satellite in the constellation uses a **monopropellant chemical thruster system** with **impulsive burns** (∆v applied instantaneously without changing position).

**Spacecraft Physical Constants:**

| Parameter | Value |
|---|---|
| Dry Mass (`m_dry`) | `500.0 kg` |
| Initial Propellant Mass (`m_fuel`) | `50.0 kg` (Total wet mass = `550.0 kg`) |
| Specific Impulse (`Isp`) | `300.0 s` |
| Max Thrust Limit | `|∆v⃗| ≤ 15.0 m/s` per individual burn |
| Thermal Cooldown | **600 seconds** mandatory rest between any two burns on the same satellite |

**Tsiolkovsky Rocket Equation** — propellant consumed `∆m` for a given maneuver:

```
∆m = m_current × (1 - e^(- |∆v⃗| / (Isp × g0)))
```

Where `g0 = 9.80665 m/s²` (standard gravity).

> ⚠️ As fuel is depleted, the satellite becomes lighter, making subsequent maneuvers slightly more fuel-efficient. Your API must dynamically account for this mass change.

## 5.2 The Station-Keeping Box

Each satellite is assigned a **Nominal Orbital Slot** — a dynamic reference point propagating along the ideal, unperturbed orbit.

| Parameter | Value |
|---|---|
| Drift Tolerance | **10 km** spherical radius from nominal slot |
| Uptime Penalty | Uptime Score degrades **exponentially** for every second spent outside the box |
| Status | `NOMINAL` if within box · `SERVICE OUTAGE` if outside |

Every evasion maneuver must be paired with a calculated **recovery trajectory** (phasing orbit or Hohmann transfer) to return the satellite to its slot once the debris threat has safely passed.

## 5.3 Maneuver Vectors: The RTN Frame

Maneuver planning is calculated in the satellite's local **Radial-Transverse-Normal (RTN)** coordinate frame:

| Axis | Direction | Effect |
|---|---|---|
| **R (Radial)** | Earth's center → satellite | Alters eccentricity and argument of perigee |
| **T (Transverse)** | Direction of velocity, ⊥ to R | Most fuel-efficient — changes semi-major axis and orbital period (phasing maneuver) |
| **N (Normal)** | R⃗ × T⃗, orthogonal to orbital plane | Alters inclination and RAAN — **very fuel-expensive, avoid unless necessary** |

Participants must calculate the required ∆v⃗ in the RTN frame and apply the appropriate **rotation matrix** to convert back into ECI frame before submitting to the API.

## 5.4 Communication Latency and Blackout Zones

The ACM is assumed to be running on **ground servers**.

| Constraint | Detail |
|---|---|
| **LOS Requirement** | Maneuver command can only be transmitted if the target satellite has unobstructed line-of-sight to at least one active Ground Station (accounting for Earth's curvature and minimum elevation mask angle) |
| **Signal Delay** | Hardcoded **10-second latency** — burns cannot be scheduled earlier than `Current Simulation Time + 10s` |
| **Blind Conjunctions** | If a collision is predicted over an ocean or pole (blackout zone), your system must schedule and upload the evasion sequence **before** the satellite leaves the last available ground station coverage area |

## 5.5 Provided Datasets

### Ground Station Network (`ground_stations.csv`)

```csv
Station_ID, Station_Name, Latitude, Longitude, Elevation_m, Min_Elevation_Angle_deg
GS-001, ISTRAC_Bengaluru, 13.0333, 77.5167, 820, 5.0
GS-002, Svalbard_Sat_Station, 78.2297, 15.4077, 400, 5.0
GS-003, Goldstone_Tracking, 35.4266, -116.8900, 1000, 10.0
GS-004, Punta_Arenas, -53.1500, -70.9167, 30, 5.0
GS-005, IIT_Delhi_Ground_Node, 28.5450, 77.1926, 225, 15.0
GS-006, McMurdo_Station, -77.8463, 166.6682, 10, 5.0
```

---

# 6. Frontend: The "Orbital Insight" Visualizer

Teams must build a **2D Operational Dashboard** analogous to software utilized by Flight Dynamics Officers (FDOs) at mission control.

## 6.1 Performance Constraints

The visualizer must render **50+ active satellites** and **10,000+ debris objects** in real-time at a stable **60 FPS**. Standard DOM manipulation will severely bottleneck the browser.

> ✅ Use the **Canvas API or WebGL** via libraries such as `PixiJS`, `Deck.gl`, or `Three.js`

## 6.2 Required Visualization Modules

### 1. Ground Track Map (Mercator Projection)
A dynamic 2D world map displaying sub-satellite points over Earth's surface:
- Real-time location markers for the entire active constellation
- Historical trailing path for the **last 90 minutes** of orbit
- Dashed predicted trajectory line for the **next 90 minutes**
- Dynamic shadow overlay for the **Terminator Line** (day/night boundary) indicating solar eclipse zones

### 2. Conjunction "Bullseye" Plot (Polar Chart)
A relative proximity view of debris approaching a selected satellite:
- **Center Point** — Selected satellite fixed at origin
- **Radial Distance** — Represents Time to Closest Approach (TCA)
- **Angle** — Represents the relative approach vector
- **Risk Indexing** — Color-coded debris markers:
  - `🟢 Green` — Safe
  - `🟡 Yellow` — Warning < 5 km
  - `🔴 Red` — Critical < 1 km

### 3. Telemetry & Resource Heatmaps
Fleet-wide health monitoring:
- Visual fuel gauge for `m_fuel` for every satellite
- ∆v cost analysis graph — "Fuel Consumed" vs "Collisions Avoided" to demonstrate evasion algorithm efficiency

### 4. Maneuver Timeline (Gantt Scheduler)
Chronological schedule of past and future automated actions:
- Distinct color blocks for `Burn Start`, `Burn End`, and mandatory **600s thruster cooldowns**
- Clearly flag any **conflicting commands** or **blackout zone overlaps**

## 6.3 Visualization API Integration

**Endpoint:** `GET /api/visualization/snapshot`

**Response (200 OK):**
```json
{
  "timestamp": "2026-03-12T08:00:00.000Z",
  "satellites": [
    {
      "id": "SAT-Alpha-04",
      "lat": 28.545,
      "lon": 77.192,
      "fuel_kg": 48.5,
      "status": "NOMINAL"
    }
  ],
  "debris_cloud": [
    ["DEB-99421", 12.42, -45.21, 400.5],
    ["DEB-99422", 12.55, -45.10, 401.2]
  ]
}
```

> **Note:** The `debris_cloud` array uses a flattened tuple structure `[ID, Latitude, Longitude, Altitude]` to drastically compress the JSON payload size for rapid network transfer.

---

# 7. Evaluation Criteria

The hackathon employs a **two-phase evaluation process** — Phase 1 is automated objective assessment; Phase 2 is manual evaluation by the judging panel.

| Criteria | Weight | Description |
|---|---|---|
| **Safety Score** *(Objective)* | 25% | Percentage of conjunctions successfully avoided. A single collision (miss distance < 100m) results in severe penalty points |
| **Fuel Efficiency** *(Objective)* | 20% | Total ∆v consumed across the constellation. Evaluates mathematical optimization of evasion algorithms |
| **Constellation Uptime** | 15% | Total time satellites spend within 10 km of their Nominal Orbital Slots |
| **Algorithmic Speed** | 15% | Time complexity of the backend API — must maintain high performance while calculating spatial indices and numerical integrations |
| **UI/UX & Visualization** | 15% | Clarity, frame rate, and situational awareness of the Orbital Insight dashboard |
| **Code Quality & Logging** | 10% | Modularity, documentation, and accuracy of system maneuver logging |

---

# 8. Deployment Requirements

> ⛔ **HARD REQUIREMENT** — If the repository does not build using Docker and does not use the specified base image, your submission **cannot be auto-tested and will be disqualified.**

| Requirement | Specification |
|---|---|
| **Dockerfile** | Must exist at the root of your GitHub repository |
| **Base Image** | Must use `ubuntu:22.04` — prevents dependency conflicts during automated grading |
| **Port Binding** | Port `8000` must be exported; application must bind to `0.0.0.0` (not `localhost`) |

---

# 9. Expected Deliverables

By the final submission deadline, teams must provide:

1. **GitHub Repo Link** — Public repository containing complete application (Backend + Frontend + Database)
2. **Docker Environment** — Valid `Dockerfile` at the root of the repository as specified above
3. **Technical Report** — Brief PDF document (preferably in LaTeX) detailing the numerical methods, spatial optimization algorithms, and overall architecture
4. **Video Demonstration** — Video demo (under 5 minutes) showcasing the idea, implementation, Orbital Insight frontend, and core functionalities

