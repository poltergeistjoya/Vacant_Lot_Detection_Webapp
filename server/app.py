"""FastAPI app: serves the PMTiles archives from the private bucket and the built frontend.

All tile imagery is prerendered (scripts/prerender_tiles.py, scripts/generate_pmtiles.py);
nothing here composites tiles or reads data/masks. The color-tuning playground runs
from server/dev.py, which adds its routes (server/playground.py) to this app.
"""

import asyncio
import logging
import os
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# Bucket holding pmtiles/ (gs://TILE_STORE_BUCKET/pmtiles/), set in .env / on Cloud Run
TILE_STORE_BUCKET = os.environ.get("TILE_STORE_BUCKET", "")

_DIST_DIR = Path(__file__).resolve().parent.parent / "dist"

# ── PMTiles archives ─────────────────────────────────
# The bucket is private. The browser's pmtiles library makes HTTP range requests to
# /api/pmtiles/<archive>; they're forwarded to gs://TILE_STORE_BUCKET/pmtiles/ with the
# service account's credentials (same region, so GCS → Cloud Run transfer is free).
# Locally the same happens with your gcloud application-default credentials.

PMTILES_PREFIX = "pmtiles"
# Largest range served per request. pmtiles reads headers, directories and single tiles
# (all well under this); the cap stops whole archives being pulled through the API.
PMTILES_MAX_RANGE = 16 * 1024 * 1024
PMTILES_CACHE_CONTROL = "public, max-age=86400"
_PMTILES_NAME = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.pmtiles$")
_RANGE = re.compile(r"^bytes=(\d+)-(\d+)$")

_gcs_http = httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=100))
_gcs_credentials = None
_gcs_credentials_lock = asyncio.Lock()

pmtiles_router = APIRouter()


def _parse_range(header):
    """(start, end) inclusive from 'bytes=start-end'; 416 if missing, malformed or too large."""
    m = _RANGE.match(header or "")
    if not m:
        raise HTTPException(416, "Range header 'bytes=start-end' required")
    start, end = int(m.group(1)), int(m.group(2))
    if end < start or end - start + 1 > PMTILES_MAX_RANGE:
        raise HTTPException(416, "Invalid or too large range")
    return start, end


async def _gcs_token():
    global _gcs_credentials
    async with _gcs_credentials_lock:
        if _gcs_credentials is None:
            import google.auth
            _gcs_credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
        if not _gcs_credentials.valid:
            from google.auth.transport.requests import Request as AuthRequest
            await asyncio.to_thread(_gcs_credentials.refresh, AuthRequest())
        return _gcs_credentials.token


async def _pmtiles_range(name, start, end):
    url = f"https://storage.googleapis.com/{TILE_STORE_BUCKET}/{PMTILES_PREFIX}/{name}"
    r = await _gcs_http.get(url, headers={
        "Authorization": f"Bearer {await _gcs_token()}",
        "Range": f"bytes={start}-{end}",
    })
    if r.status_code == 404:
        raise HTTPException(404, "Archive not found")
    if r.status_code == 416:
        raise HTTPException(416, "Range not satisfiable")
    if r.status_code != 206:
        logger.warning("pmtiles gcs %s %s: %s", name, r.status_code, r.text[:200])
        raise HTTPException(502, "Archive read failed")
    return r.content, r.headers["content-range"], r.headers.get("etag", "")


@pmtiles_router.get("/api/pmtiles/{name:path}")
async def pmtiles_archive(name: str, request: Request):
    """Byte range of a PMTiles archive (see "PMTiles archives" above)."""
    if not TILE_STORE_BUCKET:
        raise HTTPException(503, "TILE_STORE_BUCKET is not set (see .env.example)")
    if not _PMTILES_NAME.match(name):
        raise HTTPException(404, "Archive not found")
    start, end = _parse_range(request.headers.get("range"))
    data, content_range, etag = await _pmtiles_range(name, start, end)
    headers = {"Content-Range": content_range, "Accept-Ranges": "bytes",
               "Cache-Control": PMTILES_CACHE_CONTROL}
    if etag:
        headers["ETag"] = etag
    return Response(content=data, status_code=206, media_type="application/octet-stream",
                    headers=headers)


# ── App ──────────────────────────────────────────────

def create_app(playground: bool = False) -> FastAPI:
    app = FastAPI(title="Vacant Lot Detection")
    app.include_router(pmtiles_router)
    if playground:
        from server.playground import router
        app.include_router(router)
    # Production (Docker) serves the built frontend; in dev, Vite serves it. Mounted
    # last: "/" matches everything, so routes added after it would never be reached.
    if _DIST_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="static")
    return app


app = create_app()
