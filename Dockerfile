# ============================================================================
# ACM-Orbital | Autonomous Constellation Manager
# Single-container build on ubuntu:22.04 — DO NOT CHANGE BASE IMAGE
# ============================================================================
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ── Phase 1: System Dependencies ──────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-distutils \
    curl ca-certificates \
    && curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3.11 - \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Phase 2: Backend Installation ─────────────────────────────────────────
WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python3.11 -m pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/

# ── Phase 3: Frontend Build ───────────────────────────────────────────────
COPY frontend/package.json frontend/package-lock.json* /app/frontend/
RUN cd /app/frontend && npm install --production=false

COPY frontend/ /app/frontend/
RUN cd /app/frontend && npm run build \
    && rm -rf /app/backend/static \
    && mkdir -p /app/backend/static \
    && cp -r dist/* /app/backend/static/

# ── Phase 4: Runtime Configuration ────────────────────────────────────────
EXPOSE 8000

WORKDIR /app/backend

CMD ["python3.11", "-m", "uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info"]
