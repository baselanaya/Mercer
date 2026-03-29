# ============================================================
# Stage 1 — Node.js builder: compile React UI
# ============================================================
FROM node:22-alpine AS ui-builder

WORKDIR /ui
COPY app/ui/package*.json ./
RUN npm ci --ignore-scripts

COPY app/ui/ ./
RUN npm run build          # outputs to /ui/dist


# ============================================================
# Stage 2 — Python builder: install Python deps
# ============================================================
FROM python:3.12-slim AS py-builder

WORKDIR /build

# System deps needed for some Python wheels (psycopg2-binary, duckdb, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ============================================================
# Stage 3 — Final runtime image
# ============================================================
FROM python:3.12-slim AS runtime

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd --system --create-home --uid 1001 mercer

WORKDIR /app

# Python packages from builder
COPY --from=py-builder /install /usr/local

# Application source
COPY --chown=mercer:mercer . .

# Remove dev-only directories
RUN rm -rf app/ui/node_modules app/ui/src tests docker

# React build output — serve as static files from FastAPI
COPY --from=ui-builder --chown=mercer:mercer /ui/dist /app/app/ui/dist

# Persistent volume mount point for audit DB and logs
RUN mkdir -p /app/logs && chown mercer:mercer /app/logs

USER mercer

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# FastAPI + uvicorn production server
CMD ["uvicorn", "app.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info"]
