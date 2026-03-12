# 🛰️ ACM-Orbital: AI Development Guide

This document provides foundational mandates and technical context for the **Autonomous Constellation Manager (ACM)** project. It supplements the core system instructions and takes precedence for project-specific conventions.

## 📌 Project Overview
ACM-Orbital is a high-performance system for managing 50+ satellites navigating 10,000+ debris objects.
- **Architecture:** 3-Layer (Physics Engine → API Layer → Frontend Dashboard).
- **Core Tech:** Python 3.11 (FastAPI/NumPy/SciPy), React 18 (Three.js/WebGL), Docker (Ubuntu 22.04).
- **Key Algorithms:** J2-perturbed propagation (DOP853), O(N log N) KDTree conjunction assessment, RTN-frame maneuver planning, and Tsiolkovsky fuel tracking.

## 🛠️ Building & Running

### Docker (Production/Grader)
```bash
docker build -t acm-orbital .
docker run -p 8000:8000 acm-orbital
```

### Development (Manual)
- **Backend:** `cd backend && pip install -r requirements.txt && uvicorn main:app --reload`
- **Frontend:** `cd frontend && npm install && npm run dev`
- **Docker Compose:** `docker compose up --build`

### Testing
- **Backend:** `cd backend && pytest`
- **Benchmark:** `python backend/benchmark.py`

## ⚖️ Core Mandates & Conventions

### 1. Strict Layered Separation
- **Physics Engine (`backend/engine/`):** Pure math/physics. **FORBIDDEN:** Imports from `fastapi`, `uvicorn`, or any HTTP library.
- **API Layer (`backend/api/`):** Request validation and schema translation. **FORBIDDEN:** Orbital math, NumPy/SciPy operations, or direct physics logic in routers. Use the `SimulationEngine` orchestrator.
- **Frontend (`frontend/`):** React SPA. **FORBIDDEN:** Direct `fetch` calls outside of `src/utils/api.js` or `src/hooks/useSnapshot.js`.

### 2. Numerical Standards (FROZEN)
- **Constants:** All physical constants MUST be imported from `backend/config.py`.
- **Integrator:** Use `scipy.integrate.solve_ivp` with `method='DOP853'`, `rtol=1e-10`, `atol=1e-12`.
- **Units:** 
    - Internal Physics: Distance (km), Velocity (km/s), Time (seconds), Delta-V (m/s for fuel calculations).
    - API Interface: Delta-V (km/s). **Mandatory conversion at the router boundary.**
- **Spatial Indexing:** Use `scipy.spatial.KDTree` for conjunction assessment. **O(N²) nested loops are strictly prohibited.**

### 3. Engineering Quality
- **File Limits:** No file should exceed 300 lines. Split logic into modular sub-modules if limits are reached.
- **TDD:** Physics functions MUST have corresponding tests in `backend/tests/` before implementation.
- **Logging:** Use structured logging for: `TELEMETRY`, `CONJUNCTION`, `MANEUVER`, `COLLISION`, `EOL`.
- **Performance:** Frontend must maintain 60FPS using `THREE.Points` (debris) and `InstancedMesh` (satellites).

## 📂 Directory Map
- `backend/engine/`: Orbital mechanics, propagator, collision detection.
- `backend/api/`: FastAPI routers and schema definitions.
- `frontend/src/components/`: Modular visualization dashboard (Globe, GroundTrack, Bullseye, etc.).
- `docs/`: Technical reports and architecture diagrams.

## 🚨 Security & Safety
- **No Secrets:** Never commit API keys or credentials.
- **System Integrity:** The `ubuntu:22.04` base image in the `Dockerfile` is a hard requirement for the autograder. Do not change it.
- **Port:** The application MUST bind to `0.0.0.0:8000`.

*Refer to `AI guide.md` for the full "Tech Lead" persona and uncompromising enforcement rules.*
