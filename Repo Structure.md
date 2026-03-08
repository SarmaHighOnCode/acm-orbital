 🛰️ ACM_REPO_STRUCTURE.md — GOLD-MEDAL REPOSITORY SETUP
## Autonomous Constellation Manager (ACM) | National Space Hackathon 2026
### Hosted by IIT Delhi | Professional Codebase Architecture · Docker Deployment Strategy · Zero-Conflict Monorepo

---

> **Prepared for:** Team [YOUR TEAM NAME]
> **Hosted by:** Indian Institute of Technology, Delhi
> **Document Version:** 1.0 · March 2026

---

# 1. GitHub Repository Configuration

Before writing a single line of code, the repository itself must project engineering discipline. Judges and automated graders interact with your repo before they ever see your UI — the repo name, description, topic tags, and root-level file hygiene form their **first impression**.

## 1.1 Repository Identity

### Repository Name
```
acm-orbital
```

### One-Line Description
```
Autonomous satellite constellation manager: J2-perturbed orbital propagation, KDTree conjunction assessment, RTN maneuver planning, and real-time WebGL visualization — National Space Hackathon 2026
```

### GitHub Topics / Tags

Apply these topics to maximize discoverability and signal technical depth to the judging panel:

```
space-debris · orbital-mechanics · collision-avoidance · constellation-management
fastapi · threejs · webgl · kdtree · j2-perturbation · hackathon-2026
docker · python · react · scipy · autonomous-systems
```

### Root-Level File Checklist

These files must exist at the repository root — their presence signals project maturity to judges who clone and inspect before running:

| File | Purpose |
|---|---|
| `README.md` | Architecture overview, quick start, API docs |
| `Dockerfile` | Single-command build + run for autograder |
| `docker-compose.yml` | Local dev convenience with hot-reload |
| `.gitignore` | Python + Node + OS ignores |
| `.dockerignore` | Excludes node_modules, __pycache__, .git from build context |
| `LICENSE` | MIT License |
| `CONTRIBUTING.md` | Branch strategy, PR template, code style |

---

# 2. The Complete Directory Tree

The directory structure is the **physical enforcement layer** of the zero-collision team strategy. Each developer's ownership boundary maps to a discrete directory subtree. There is zero file overlap between domains — which means zero merge conflicts when all three developers commit simultaneously.

## 2.1 Full Tree with Ownership Annotations

```
acm-orbital/                          ← GitHub repo root
│
├── Dockerfile                         [Dev 2]  Autograder entry point
├── docker-compose.yml                 [Dev 2]  Local dev convenience
├── README.md                          [Dev 2]  Project documentation
├── .gitignore                         [Shared] Created on Day 1, frozen
├── .dockerignore                      [Dev 2]  Build context exclusions
├── LICENSE                            [Shared] MIT License
│
├── .github/
│   ├── pull_request_template.md       [Dev 2]  Standardized PR format
│   └── workflows/
│       └── ci.yml                     [Dev 2]  Optional lint + test on PR
│
├── backend/                           ===== PYTHON DOMAIN =====
│   ├── requirements.txt               [Dev 2]  Pinned Python dependencies
│   ├── main.py                        [Dev 2]  FastAPI app factory + lifespan
│   ├── config.py                      [FROZEN] Physical constants (Day 1)
│   ├── schemas.py                     [FROZEN] Pydantic request/response models
│   │
│   ├── api/                           ===== DEV 2 TERRITORY =====
│   │   ├── __init__.py
│   │   ├── telemetry.py               POST /api/telemetry
│   │   ├── maneuver.py                POST /api/maneuver/schedule
│   │   ├── simulate.py                POST /api/simulate/step
│   │   └── visualization.py           GET  /api/visualization/snapshot
│   │
│   ├── engine/                        ===== DEV 1 TERRITORY =====
│   │   ├── __init__.py
│   │   ├── simulation.py              SimulationEngine (master tick loop)
│   │   ├── propagator.py              J2 propagation + DOP853 integrator
│   │   ├── collision.py               KDTree conjunction assessment pipeline
│   │   ├── maneuver_planner.py        RTN-to-ECI, evasion + recovery calc
│   │   ├── fuel_tracker.py            Tsiolkovsky equation + EOL logic
│   │   ├── ground_stations.py         LOS visibility + blackout calculation
│   │   └── models.py                  Dataclasses: Satellite, Debris, CDM
│   │
│   ├── data/                          ===== STATIC DATASETS =====
│   │   └── ground_stations.csv        Provided 6-station network
│   │
│   └── tests/                         ===== DEV 1 TERRITORY =====
│       ├── __init__.py
│       ├── conftest.py                Shared pytest fixtures
│       ├── test_propagator.py         Orbital period validation (92-min LEO)
│       ├── test_collision.py          KDTree + TCA refinement accuracy
│       ├── test_maneuver.py           RTN→ECI rotation matrix correctness
│       ├── test_fuel.py               Tsiolkovsky mass depletion + EOL trigger
│       └── test_simulation.py         Full tick integration test
│
├── frontend/                          ===== DEV 3 TERRITORY =====
│   ├── package.json
│   ├── vite.config.js                 Proxy /api to localhost:8000 in dev
│   ├── tailwind.config.js
│   ├── index.html
│   ├── public/
│   │   ├── earth-texture.jpg          Equirectangular map (2K resolution)
│   │   └── earth-night.jpg            Night-side texture for terminator
│   └── src/
│       ├── App.jsx                    Root layout (4-panel dashboard grid)
│       ├── main.jsx                   React DOM entry point
│       ├── store.js                   Zustand global state store
│       ├── components/
│       │   ├── Dashboard.jsx          Layout orchestrator (CSS Grid)
│       │   ├── GlobeView.jsx          3D R3F globe + debris points
│       │   ├── GroundTrack.jsx        2D Canvas Mercator projection
│       │   ├── BullseyePlot.jsx       Polar conjunction proximity chart
│       │   ├── FuelHeatmap.jsx        Fleet fuel gauges + Δv analysis
│       │   └── ManeuverTimeline.jsx   Gantt scheduler with cooldown blocks
│       ├── workers/
│       │   └── propagation.worker.js  SGP4 in Web Worker (Transferable)
│       └── utils/
│           ├── coordinates.js         ECI → lat/lon conversion
│           ├── api.js                 Fetch wrapper for snapshot polling
│           └── constants.js           Shared rendering constants
│
└── docs/                              ===== DELIVERABLES =====
    ├── technical_report.tex           LaTeX report (expected deliverable)
    ├── figures/                       Diagrams for the report
    └── architecture.mermaid           System architecture diagram
```

## 2.2 Why This Structure Wins

### A. Physical Domain Isolation = Zero Merge Conflicts

The three developer branches map to non-overlapping directory subtrees:
- **Dev 1** exclusively owns `backend/engine/` and `backend/tests/`
- **Dev 2** exclusively owns `backend/api/`, `main.py`, `Dockerfile`, and all infrastructure files
- **Dev 3** exclusively owns the entire `frontend/` directory

The only shared files — `config.py` and `schemas.py` — are written on Day 1 and **frozen**. All three developers can push to their branches simultaneously for five consecutive days without a single Git conflict.

### B. Strict Layered Dependency = No Spaghetti

The directory tree physically enforces the architectural rule: **Frontend → API → Engine**:
- `engine/` contains pure Python modules with zero imports from `api/` or any HTTP library
- `api/` imports only from `engine/` and `schemas`
- `frontend/` communicates exclusively via HTTP polling — no Python imports at all

An AI coding agent working inside `engine/` literally cannot accidentally couple to the API layer because the import paths don't exist.

### C. Judge-Friendly Readability

Judges evaluating Code Quality (10% of total score) will clone the repo and scan the tree. Each filename is self-documenting:

| File | What it contains |
|---|---|
| `propagator.py` | J2-perturbed orbital propagator |
| `collision.py` | KDTree conjunction detection pipeline |
| `fuel_tracker.py` | Tsiolkovsky rocket equation + EOL logic |
| `maneuver_planner.py` | RTN-to-ECI conversion + burn scheduling |

### D. AI Agent Navigation

Modern AI coding tools perform best when file boundaries match logical boundaries. Each file in `engine/` corresponds to exactly **one class with one responsibility**. When you prompt *"implement the J2-perturbed propagator in propagator.py"*, the agent has a clear, isolated sandbox — it won't accidentally modify collision detection logic.

---

# 3. Directory-to-Domain Ownership Map

The following table provides the definitive mapping between every directory in the repository and the developer who owns it.

| Directory / File | Owner | Locked After |
|---|---|---|
| `backend/engine/` | **Dev 1** | Day 1 (interface contract) |
| `backend/tests/` | **Dev 1** | — |
| `backend/api/` | **Dev 2** | — |
| `backend/main.py` | **Dev 2** | — |
| `Dockerfile` | **Dev 2** | — |
| `docker-compose.yml` | **Dev 2** | — |
| `README.md` | **Dev 2** | — |
| `frontend/` | **Dev 3** | — |
| `backend/config.py` | **Shared** | ⛔ Day 1 — FROZEN |
| `backend/schemas.py` | **Shared** | ⛔ Day 1 — FROZEN |
| `.gitignore` | **Shared** | ⛔ Day 1 — FROZEN |
| `LICENSE` | **Shared** | ⛔ Day 1 — FROZEN |

---

# 4. The Docker Deployment Plan

The problem statement in Section 8 specifies hard deployment requirements that, if violated, result in **immediate disqualification**. This section provides the exact Dockerfile logic and rationale, ensuring the automated grading scripts can build and test the submission without human intervention.

## 4.1 Hard Requirements from the Problem Statement

| Requirement | Our Solution |
|---|---|
| Base image: `ubuntu:22.04` | `FROM ubuntu:22.04` — no deviation |
| Single container | Everything runs in one Uvicorn process |
| Port 8000 | `EXPOSE 8000` + `--port 8000` |
| `docker build` must succeed | Pinned deps, `npm ci`, no network calls at runtime |
| API reachable at `0.0.0.0` | `--host 0.0.0.0` in Uvicorn CMD |

## 4.2 Dockerfile Architecture

The Dockerfile follows a logical **four-phase build sequence**: system dependencies → backend setup → frontend build → runtime configuration. It is a single-stage build (not multi-stage) because the `ubuntu:22.04` constraint precludes using optimized slim images.

### Phase 1: System Dependencies

Install Python 3.11, Node.js 18 LTS, and essential build tools on the `ubuntu:22.04` base. Non-interactive mode and apt cache cleanup minimize image size.

```dockerfile
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3-pip \
    curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
```

### Phase 2: Backend Installation

Copy and install Python dependencies **first** (before source code) to maximize Docker layer caching. If `requirements.txt` hasn't changed, this layer is cached and rebuilds are near-instant.

```dockerfile
WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip3 install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/
```

### Phase 3: Frontend Build

Install Node.js dependencies and build the React application into static production assets. The build output is placed in `backend/static/` so FastAPI can serve it via `StaticFiles` mount.

```dockerfile
COPY frontend/package.json frontend/package-lock.json /app/frontend/
RUN cd /app/frontend && npm ci --production=false

COPY frontend/ /app/frontend/
RUN cd /app/frontend && npm run build \
    && mkdir -p /app/backend/static \
    && cp -r dist/* /app/backend/static/
```

### Phase 4: Runtime Configuration

Expose port 8000 and launch Uvicorn bound to `0.0.0.0`. A **single Uvicorn worker** is used intentionally — multiple workers would fragment the in-memory simulation state.

```dockerfile
EXPOSE 8000

WORKDIR /app/backend

CMD ["python3", "-m", "uvicorn", "main:app",
     "--host", "0.0.0.0",
     "--port", "8000",
     "--workers", "1",
     "--log-level", "info"]
```

## 4.3 Key Design Decisions

| Decision | Rationale |
|---|---|
| Single-stage build | `ubuntu:22.04` hard requirement; can't use `node:alpine` + `python:slim` multi-stage |
| `npm ci` not `npm install` | Deterministic install from `package-lock.json`; faster; fails loudly on mismatch |
| `pip install` before `COPY backend/` | Layer cache optimization — deps layer only rebuilds when `requirements.txt` changes |
| Single Uvicorn worker | In-memory `SimulationEngine` state must not be sharded across processes |
| Frontend built into `backend/static/` | FastAPI `StaticFiles` mount serves the SPA; no separate web server needed |

## 4.4 docker-compose.yml for Local Development

The optional `docker-compose.yml` provides a developer-friendly workflow with volume mounts for hot-reloading during local iteration. This is **not used by the autograder** — it is purely for team convenience.

```yaml
version: '3.8'
services:
  acm:
    build: .
    ports:
      - '8000:8000'
    volumes:
      - ./backend:/app/backend        # Hot-reload Python changes
    environment:
      - PYTHONDONTWRITEBYTECODE=1
      - LOG_LEVEL=debug
```

### Local Testing Commands

```bash
# Build and run the complete container (simulates grader)
docker build -t acm-orbital . && docker run -p 8000:8000 acm-orbital

# Verify the API is reachable
curl http://localhost:8000/api/visualization/snapshot

# Run backend tests inside container
docker run acm-orbital python3 -m pytest /app/backend/tests/ -v
```

---

# 5. Dependency Manifests

## 5.1 backend/requirements.txt

Every dependency is pinned to a specific version to guarantee reproducible builds. **No floating versions, no surprises.**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
orjson==3.10.7
pydantic==2.9.0
numpy==1.26.4
scipy==1.14.0
sgp4==2.23
python-dateutil==2.9.0
structlog==24.4.0
pytest==8.3.0
httpx==0.27.0
```

## 5.2 frontend/package.json (Key Dependencies)

```json
{
  "name": "acm-orbital-insight",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "@react-three/fiber": "^8.16.0",
    "@react-three/drei": "^9.105.0",
    "three": "^0.165.0",
    "zustand": "^4.5.0",
    "recharts": "^2.12.0",
    "satellite.js": "^5.0.0"
  },
  "devDependencies": {
    "vite": "^5.4.0",
    "@vitejs/plugin-react": "^4.3.0",
    "tailwindcss": "^3.4.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0"
  }
}
```

---

# 6. Day 1 Repository Bootstrap Sequence

The following is the **exact sequence** the team executes in the first 30 minutes of Day 1. After this sequence, all three developers have their branches, the shared contracts are frozen, and parallel development begins.

## 6.1 Step-by-Step Initialization

1. **Step 1** — One developer creates the GitHub repository named `acm-orbital`, sets it to Public, adds the MIT license, and pastes the one-line description
2. **Step 2** — Clone locally; run the scaffold script (below) to create the entire directory tree with placeholder files
3. **Step 3** — All three developers collaboratively write `config.py` (physical constants from the PRD) and `schemas.py` (Pydantic models matching the PDF API spec); commit to `main` and **freeze**
4. **Step 4** — Each developer creates their branch: `dev/physics`, `dev/api-infra`, `dev/frontend`; development begins independently

## 6.2 Scaffold Script

Run this from the repo root to create the complete directory tree with `__init__.py` files and placeholder stubs:

```bash
#!/bin/bash
# scaffold.sh — Run once on Day 1 to create the full directory tree

mkdir -p backend/{api,engine,data,tests}
mkdir -p frontend/{public,src/{components,workers,utils}}
mkdir -p docs/figures
mkdir -p .github/workflows

# Python init files
touch backend/__init__.py
touch backend/api/__init__.py
touch backend/engine/__init__.py
touch backend/tests/__init__.py
touch backend/tests/conftest.py

# Placeholder stubs (prevents import errors on Day 1)
echo "# Physical Constants — FROZEN AFTER DAY 1" > backend/config.py
echo "# Pydantic Schemas — FROZEN AFTER DAY 1" > backend/schemas.py
echo "# FastAPI Application Factory" > backend/main.py

# Engine module stubs
for f in simulation propagator collision maneuver_planner fuel_tracker ground_stations models; do
  echo "# ${f}.py — Dev 1 (Physics Engine)" > backend/engine/${f}.py
done

# API route stubs
for f in telemetry maneuver simulate visualization; do
  echo "# ${f}.py — Dev 2 (API Layer)" > backend/api/${f}.py
done

echo "Scaffold complete. Ready for parallel development."
