# ── Stage 1: build the Vite frontend ────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY vite.config.js ./
COPY src/ src/
COPY data/ data/
ARG VITE_PMTILES_BASE_URL="https://storage.googleapis.com/vacant-lot-tiles/pmtiles"
ENV VITE_PMTILES_BASE_URL=$VITE_PMTILES_BASE_URL
# Vacancy sources with uploaded archives; others are served by the API
ARG VITE_PMTILES_SOURCES="both"
ENV VITE_PMTILES_SOURCES=$VITE_PMTILES_SOURCES
RUN npm run build

# ── Stage 2: Python runtime ──────────────────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

COPY server/ server/
COPY data/ data/
COPY --from=frontend /app/dist/ dist/

EXPOSE 8000
ENV PYTHONUNBUFFERED=1
CMD ["uv", "run", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--log-level", "info"]
