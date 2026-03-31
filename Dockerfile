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
    python3.11 python3.11-venv \
    curl ca-certificates \
    && python3.11 -m ensurepip --upgrade \
    && python3.11 -m pip install --upgrade pip \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Phase 2: Backend Installation ─────────────────────────────────────────
WORKDIR /app

# ── Non-root user (security best practice) ────────────────────────────────
RUN useradd -m appuser

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python3.11 -m pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/

# ── Phase 3: Frontend Build ───────────────────────────────────────────────
COPY frontend/package.json frontend/package-lock.json* /app/frontend/
RUN cd /app/frontend && npm ci --production=false

COPY frontend/ /app/frontend/
RUN cd /app/frontend && npm run build \
    && rm -rf /app/backend/static \
    && mkdir -p /app/backend/static \
    && cp -r dist/* /app/backend/static/

# ── Phase 4: Runtime Configuration ────────────────────────────────────────
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

RUN chown -R appuser /app

WORKDIR /app/backend

USER appuser

CMD ["python3.11", "-m", "uvicorn", "main:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--workers", "1", \
    "--log-level", "info"]
