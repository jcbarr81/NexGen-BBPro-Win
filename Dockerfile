# Cloud image for NexGen-BBPro: serves BOTH the FastAPI backend and the built
# React UI from one origin (Cloud Run), so there are no cross-origin/CORS
# concerns and a single public URL hosts the whole app.

# --- Stage 1: build the React UI --------------------------------------------
FROM node:20-slim AS frontend
WORKDIR /desktop
# Install deps against the lockfile first (cached unless deps change).
COPY desktop/package.json desktop/package-lock.json ./
RUN npm ci
# Build the renderer bundle (Vite). base "./" keeps asset paths relative; the
# app uses HashRouter so all routes stay under "/" when served.
COPY desktop/ ./
RUN npm run build:renderer

# --- Stage 2: Python runtime ------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# System lib for OpenCV (headless) — its wheels still link libglib2.0.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt

# Application code (heavy/irrelevant paths excluded via .dockerignore).
COPY . .

# Drop in the built UI; FastAPI serves it at "/" when this dir exists.
COPY --from=frontend /desktop/dist ./desktop/dist

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
