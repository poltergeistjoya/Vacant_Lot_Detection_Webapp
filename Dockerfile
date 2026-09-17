# ── Stage 1: build the Vite frontend ────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY vite.config.js ./
COPY src/ src/
COPY data/ data/
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
CMD ["uv", "run", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
