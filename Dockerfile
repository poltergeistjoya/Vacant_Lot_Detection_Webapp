# ── Stage 1: build the Vite frontend ────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY vite.config.js ./
COPY src/ src/
# The build picks the files it needs from data/ (WEB_DATA in vite.config.js)
COPY data/ data/
RUN npm run build

# ── Stage 2: Python runtime ──────────────────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

# Only the archive proxy (server/app.py); compositing, the playground and data/ stay out
COPY server/__init__.py server/app.py server/
COPY --from=frontend /app/dist/ dist/

EXPOSE 8000
ENV PYTHONUNBUFFERED=1
CMD ["uv", "run", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--log-level", "info"]
