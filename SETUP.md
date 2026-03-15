# 🚀 ACM-Orbital — Setup & Run Guide

## Prerequisites
- **Python 3.11+** installed
- **Node.js 18+** and npm installed
- A virtual environment (`.venv`) at the project root

---

## Option 1: Quick Start (All-in-One)

```bash
# From project root, with venv activated
python run_dataset.py                    # No dataset
python run_dataset.py --dataset real     # Real satellite data from Celestrak
python run_dataset.py --dataset worst-case  # Stress-test scenario
```

Then start the frontend in a separate terminal:

```bash
cd frontend
npm ci
npm run dev
```

- **Backend:** http://localhost:8000
- **Frontend:** http://localhost:5173

---

## Option 2: Manual (Separate Terminals)

### Terminal 1 — Backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 2 — Frontend

```bash
cd frontend
npm ci
npm run dev
```

---

## Option 3: Docker

```bash
docker build -t acm-orbital .
docker run -p 8000:8000 acm-orbital
```

Or with Docker Compose:

```bash
docker compose up --build
```

---

## Injecting Telemetry Data

If the backend is already running and you want to load satellite data without restarting:

```bash
# Generate real TLE data
python backend/fetch_real_tle.py

# Inject into running server
curl -X POST http://localhost:8000/api/telemetry -H "Content-Type: application/json" -d @live_telemetry.json
```

## Stepping the Simulation

Advance the simulation clock to propagate orbits and trigger conjunction detection:

```bash
curl -X POST http://localhost:8000/api/simulate/step -H "Content-Type: application/json" -d "{\"step_seconds\": 60}"
```

---

## Key Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| `GET`  | http://localhost:8000/health | Health check |
| `GET`  | http://localhost:8000/docs | Swagger API docs |
| `POST` | http://localhost:8000/api/telemetry | Ingest satellite & debris data |
| `POST` | http://localhost:8000/api/simulate/step | Advance simulation |
| `GET`  | http://localhost:8000/api/visualization/snapshot | Frontend data snapshot |
