# ============================================================================
# ACM-Orbital | Autonomous Constellation Manager
# ============================================================================
# -- Phase 1: Frontend Build -----------------------------------------------
FROM node:18-slim AS builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --production=false
COPY frontend/ ./
RUN npm run build

# -- Phase 2: Runtime Configuration ----------------------------------------
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN useradd -m appuser

COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/
COPY --from=builder /app/frontend/dist /app/backend/static

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsSL http://localhost:8000/health || exit 1

RUN chown -R appuser:appuser /app
WORKDIR /app/backend
USER appuser

CMD ["python3.11", "-m", "uvicorn", "main:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--workers", "1", \
    "--log-level", "info"]
