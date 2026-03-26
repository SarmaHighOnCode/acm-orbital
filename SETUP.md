# 🚀 ACM-Orbital — Setup & Run Guide

## Prerequisites
- **Docker** and **Docker Compose** (Recommended for most users)
- *Alternatively, for local dev:* **Python 3.11+**, **Node.js 18+**, and **npm**

---

## Option 1: Quick Start (Docker - Recommended)

The engine automatically seeds **50 satellites + 10,000 debris objects** and advances the clock by 5 steps on first load so the dashboard is fully populated immediately.

```bash
git clone https://github.com/SarmaHighOnCode/acm-orbital.git
cd acm-orbital
docker compose build --no-cache
docker compose up
```

- **Dashboard:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs

*Note: Wait for `AUTO_SEED | Complete — dashboard ready` in the terminal logs before opening the dashboard.*

---

## Option 2: Local Development (Separate Terminals)

If you are a developer modifying the code, run the engine and frontend locally:

### Terminal 1 — Backend (Engine & API)

```bash
python -m venv .venv
# Activate venv: `source .venv/bin/activate` or `.\.venv\Scripts\Activate.ps1`
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 2 — Frontend (UI)

```bash
cd frontend
npm ci
npm run dev
```

- **Backend / API:** http://localhost:8000
- **Frontend / Dev UI:** http://localhost:5173

*(Note: The auto-seed will run exactly as it does in Docker if `ACM_AUTO_SEED=1` is enabled. You can disable it by exporting `ACM_AUTO_SEED=0`)*

---

## Injecting Custom Telemetry Data

If you want to load massive stress-test scenarios or custom satellites mid-simulation:

```bash
# 1. Generate a custom payload (e.g., 50k debris in worst-case collision orbit)
python backend/generate_telemetry.py --n 50000 --mode worst --output custom_telemetry.json

# 2. Inject into the running server
curl -X POST http://localhost:8000/api/telemetry \
  -H "Content-Type: application/json" \
  -d @custom_telemetry.json
```

## Stepping the Simulation

While auto-stepped in real-time, you can manually advance the simulation clock to propagate orbits and trigger conjunction detection:

```bash
curl -X POST http://localhost:8000/api/simulate/step \
  -H "Content-Type: application/json" \
  -d "{\"step_seconds\": 60}"
```

---

## Key Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| `GET`  | http://localhost:8000/health | Health check |
| `GET`  | http://localhost:8000/docs | Swagger/OpenAPI docs |
| `POST` | http://localhost:8000/api/telemetry | Ingest satellite & debris data |
| `POST` | http://localhost:8000/api/simulate/step | Advance simulation |
| `GET`  | http://localhost:8000/api/visualization/snapshot | Frontend data snapshot |
