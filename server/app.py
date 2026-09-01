"""FastAPI backend for playground tile processing.

Proxies Esri basemap tiles, applies color operations (rio-color) with
mask-based regional treatment (basemap / vacant / non-vacant), and
returns processed PNGs.
"""

import hashlib
import io
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
from color_operations import sigmoidal, gamma, saturation
from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

app = FastAPI(title="Vacancy Playground API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# ── Esri tile fetching ───────────────────────────────
ESRI_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

_client = httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=20))


async def fetch_esri_tile(z: int, x: int, y: int) -> bytes:
    """Fetch a single Esri basemap tile."""
    url = ESRI_URL.format(z=z, y=y, x=x)
    resp = await _client.get(url)
    resp.raise_for_status()
    return resp.content


# ── Color operations ─────────────────────────────────

def apply_color_ops(
    arr: np.ndarray,
    sig_contrast: float = 0.0,
    sig_bias: float = 0.5,
    gam_master: float = 1.0,
    gam_r: float = 1.0,
    gam_g: float = 1.0,
    gam_b: float = 1.0,
    sat: float = 1.0,
    grayscale: float = 0.0,
    brightness: float = 1.0,
    tint_r: int = 0,
    tint_g: int = 0,
    tint_b: int = 0,
    tint_opacity: float = 0.0,
) -> np.ndarray:
    """Apply color operations to a (3, H, W) float64 array scaled 0-1.

    Returns array in same format.
    """
    # Sigmoidal contrast (only if contrast > 0)
    if sig_contrast > 0:
        arr = sigmoidal(arr, sig_contrast, sig_bias)

    # Per-channel gamma
    if gam_r != 1.0:
        arr[0] = gamma(arr[0:1], gam_r)[0]
    if gam_g != 1.0:
        arr[1] = gamma(arr[1:2], gam_g)[0]
    if gam_b != 1.0:
        arr[2] = gamma(arr[2:3], gam_b)[0]

    # Master gamma
    if gam_master != 1.0:
        arr = gamma(arr, gam_master)

    # Saturation
    if sat != 1.0:
        arr = saturation(arr, sat)

    # Brightness (simple multiply + clip)
    if brightness != 1.0:
        arr = np.clip(arr * brightness, 0, 1)

    # Grayscale blend
    if grayscale > 0:
        lum = 0.2126 * arr[0] + 0.7152 * arr[1] + 0.0722 * arr[2]
        gray = np.stack([lum, lum, lum])
        arr = arr * (1 - grayscale) + gray * grayscale

    # Tint overlay
    if tint_opacity > 0:
        tint = np.array([tint_r, tint_g, tint_b], dtype=np.float64).reshape(3, 1, 1) / 255.0
        arr = arr * (1 - tint_opacity) + tint * tint_opacity

    return np.clip(arr, 0, 1)


def tile_bytes_to_array(tile_bytes: bytes) -> np.ndarray:
    """PNG/JPEG bytes → (3, H, W) float64 array scaled 0-1."""
    img = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
    arr = np.array(img, dtype=np.float64) / 255.0  # (H, W, 3)
    return arr.transpose(2, 0, 1)  # (3, H, W)


def array_to_png(arr: np.ndarray) -> bytes:
    """(3, H, W) float64 array → PNG bytes."""
    img_arr = (arr.transpose(1, 2, 0) * 255).astype(np.uint8)  # (H, W, 3)
    img = Image.fromarray(img_arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def add_bloom(arr: np.ndarray, radius: float, intensity: float,
              color_r: int, color_g: int, color_b: int,
              mask: Optional[np.ndarray] = None) -> np.ndarray:
    """Apply bloom effect — Gaussian blur of bright mask-edge pixels,
    composited additively."""
    from scipy.ndimage import gaussian_filter

    if mask is None or radius <= 0 or intensity <= 0:
        return arr

    # Create edge from mask
    from scipy.ndimage import binary_dilation, binary_erosion
    edge = binary_dilation(mask, iterations=2) & ~binary_erosion(mask, iterations=1)

    # Color the edge
    color = np.array([color_r, color_g, color_b], dtype=np.float64).reshape(3, 1, 1) / 255.0
    edge_f = edge.astype(np.float64)
    bloom_layer = color * edge_f[np.newaxis, :, :]

    # Blur it
    for c in range(3):
        bloom_layer[c] = gaussian_filter(bloom_layer[c], sigma=radius)

    # Additive composite
    arr = arr + bloom_layer * intensity
    return np.clip(arr, 0, 1)


# ── Mask loading ─────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def load_mask_and_bounds():
    """Load the vacancy mask PNG and its bounds. Cached."""
    mask_path = DATA_DIR / "mask_overlay.png"
    bounds_path = DATA_DIR / "mask_overlay.json"

    if not mask_path.exists():
        return None, None

    img = Image.open(mask_path)
    # Alpha channel is the mask: opaque = vacant
    arr = np.array(img)
    mask = arr[:, :, 3] > 127  # bool (H, W)

    bounds = json.loads(bounds_path.read_text()) if bounds_path.exists() else None
    return mask, bounds


# ── API endpoints ────────────────────────────────────

@app.get("/api/tile/{z}/{x}/{y}.png")
async def processed_tile(
    z: int, x: int, y: int,
    # Basemap treatment
    bm_sig_contrast: float = Query(0, alias="bm_sc"),
    bm_sig_bias: float = Query(0.5, alias="bm_sb"),
    bm_gamma: float = Query(1.0, alias="bm_g"),
    bm_gamma_r: float = Query(1.0, alias="bm_gr"),
    bm_gamma_g: float = Query(1.0, alias="bm_gg"),
    bm_gamma_b: float = Query(1.0, alias="bm_gb"),
    bm_saturation: float = Query(1.0, alias="bm_sat"),
    bm_grayscale: float = Query(0.0, alias="bm_gray"),
    bm_brightness: float = Query(1.0, alias="bm_br"),
    # Vacant treatment
    vc_sig_contrast: float = Query(0, alias="vc_sc"),
    vc_sig_bias: float = Query(0.5, alias="vc_sb"),
    vc_gamma: float = Query(1.0, alias="vc_g"),
    vc_gamma_r: float = Query(1.0, alias="vc_gr"),
    vc_gamma_g: float = Query(1.0, alias="vc_gg"),
    vc_gamma_b: float = Query(1.0, alias="vc_gb"),
    vc_saturation: float = Query(1.0, alias="vc_sat"),
    vc_grayscale: float = Query(0.0, alias="vc_gray"),
    vc_brightness: float = Query(1.0, alias="vc_br"),
    vc_tint_color: str = Query("000000", alias="vc_tint"),
    vc_tint_opacity: float = Query(0.0, alias="vc_to"),
    # Non-vacant treatment
    nv_sig_contrast: float = Query(0, alias="nv_sc"),
    nv_sig_bias: float = Query(0.5, alias="nv_sb"),
    nv_gamma: float = Query(1.0, alias="nv_g"),
    nv_gamma_r: float = Query(1.0, alias="nv_gr"),
    nv_gamma_g: float = Query(1.0, alias="nv_gg"),
    nv_gamma_b: float = Query(1.0, alias="nv_gb"),
    nv_saturation: float = Query(1.0, alias="nv_sat"),
    nv_grayscale: float = Query(0.0, alias="nv_gray"),
    nv_brightness: float = Query(1.0, alias="nv_br"),
    # Boundary — bloom
    bloom_radius: float = Query(0, alias="bl_r"),
    bloom_intensity: float = Query(0, alias="bl_i"),
    bloom_color: str = Query("ff8c00", alias="bl_c"),
):
    """Fetch an Esri tile, apply per-region color treatments, return PNG."""
    # Fetch source tile
    tile_bytes = await fetch_esri_tile(z, x, y)
    arr = tile_bytes_to_array(tile_bytes)

    # Check if all treatments are default — if so, return original tile
    is_default = (
        bm_sig_contrast == 0 and bm_gamma == 1 and bm_gamma_r == 1 and
        bm_gamma_g == 1 and bm_gamma_b == 1 and bm_saturation == 1 and
        bm_grayscale == 0 and bm_brightness == 1 and
        vc_sig_contrast == 0 and vc_gamma == 1 and vc_gamma_r == 1 and
        vc_gamma_g == 1 and vc_gamma_b == 1 and vc_saturation == 1 and
        vc_grayscale == 0 and vc_brightness == 1 and vc_tint_opacity == 0 and
        nv_sig_contrast == 0 and nv_gamma == 1 and nv_gamma_r == 1 and
        nv_gamma_g == 1 and nv_gamma_b == 1 and nv_saturation == 1 and
        nv_grayscale == 0 and nv_brightness == 1 and
        bloom_radius == 0
    )
    if is_default:
        return Response(content=tile_bytes, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})

    # Apply basemap treatment to the whole tile first
    result = apply_color_ops(
        arr.copy(),
        sig_contrast=bm_sig_contrast, sig_bias=bm_sig_bias,
        gam_master=bm_gamma, gam_r=bm_gamma_r, gam_g=bm_gamma_g, gam_b=bm_gamma_b,
        sat=bm_saturation, grayscale=bm_grayscale, brightness=bm_brightness,
    )

    # TODO: Apply per-region treatments when we can map tile coords to mask pixels.
    # For now, vacant/non-vacant treatments are applied if any non-default params
    # are set, using the mask overlay. This requires computing the intersection
    # of the tile's geographic bounds with the mask bounds.
    #
    # For the initial version, we apply vacant/non-vacant as full-tile effects
    # (the CSS mask on the frontend still handles the spatial clipping).

    # Parse tint color
    tc = vc_tint_color.lstrip("#")
    tint_r, tint_g, tint_b = int(tc[0:2], 16), int(tc[2:4], 16), int(tc[4:6], 16)

    # Vacant treatment — applied to a copy, frontend CSS-masks to vacant pixels
    vc_has_ops = (
        vc_sig_contrast != 0 or vc_gamma != 1 or vc_gamma_r != 1 or
        vc_gamma_g != 1 or vc_gamma_b != 1 or vc_saturation != 1 or
        vc_grayscale != 0 or vc_brightness != 1 or vc_tint_opacity != 0
    )
    nv_has_ops = (
        nv_sig_contrast != 0 or nv_gamma != 1 or nv_gamma_r != 1 or
        nv_gamma_g != 1 or nv_gamma_b != 1 or nv_saturation != 1 or
        nv_grayscale != 0 or nv_brightness != 1
    )

    # If only basemap ops, return single processed tile
    if not vc_has_ops and not nv_has_ops and bloom_radius <= 0:
        png = array_to_png(result)
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=300"})

    # Return basemap-treated tile — vacant/non-vacant panes will request
    # their own tiles from separate endpoints
    png = array_to_png(result)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/api/tile/vacant/{z}/{x}/{y}.png")
async def vacant_tile(
    z: int, x: int, y: int,
    sig_contrast: float = Query(0, alias="sc"),
    sig_bias: float = Query(0.5, alias="sb"),
    gam_master: float = Query(1.0, alias="g"),
    gam_r: float = Query(1.0, alias="gr"),
    gam_g: float = Query(1.0, alias="gg"),
    gam_b: float = Query(1.0, alias="gb"),
    sat: float = Query(1.0, alias="sat"),
    grayscale: float = Query(0.0, alias="gray"),
    brightness: float = Query(1.0, alias="br"),
    tint_color: str = Query("000000", alias="tint"),
    tint_opacity: float = Query(0.0, alias="to"),
):
    """Process a tile with vacant area treatment. Frontend CSS-masks to vacant pixels."""
    tile_bytes = await fetch_esri_tile(z, x, y)

    is_default = (
        sig_contrast == 0 and gam_master == 1 and gam_r == 1 and
        gam_g == 1 and gam_b == 1 and sat == 1 and
        grayscale == 0 and brightness == 1 and tint_opacity == 0
    )
    if is_default:
        return Response(content=tile_bytes, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})

    arr = tile_bytes_to_array(tile_bytes)
    tc = tint_color.lstrip("#")
    tint_r, tint_g, tint_b = int(tc[0:2], 16), int(tc[2:4], 16), int(tc[4:6], 16)

    result = apply_color_ops(
        arr, sig_contrast=sig_contrast, sig_bias=sig_bias,
        gam_master=gam_master, gam_r=gam_r, gam_g=gam_g, gam_b=gam_b,
        sat=sat, grayscale=grayscale, brightness=brightness,
        tint_r=tint_r, tint_g=tint_g, tint_b=tint_b, tint_opacity=tint_opacity,
    )
    png = array_to_png(result)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/api/tile/nonvacant/{z}/{x}/{y}.png")
async def nonvacant_tile(
    z: int, x: int, y: int,
    sig_contrast: float = Query(0, alias="sc"),
    sig_bias: float = Query(0.5, alias="sb"),
    gam_master: float = Query(1.0, alias="g"),
    gam_r: float = Query(1.0, alias="gr"),
    gam_g: float = Query(1.0, alias="gg"),
    gam_b: float = Query(1.0, alias="gb"),
    sat: float = Query(1.0, alias="sat"),
    grayscale: float = Query(0.0, alias="gray"),
    brightness: float = Query(1.0, alias="br"),
):
    """Process a tile with non-vacant area treatment. Frontend CSS-masks to non-vacant pixels."""
    tile_bytes = await fetch_esri_tile(z, x, y)

    is_default = (
        sig_contrast == 0 and gam_master == 1 and gam_r == 1 and
        gam_g == 1 and gam_b == 1 and sat == 1 and
        grayscale == 0 and brightness == 1
    )
    if is_default:
        return Response(content=tile_bytes, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})

    arr = tile_bytes_to_array(tile_bytes)
    result = apply_color_ops(
        arr, sig_contrast=sig_contrast, sig_bias=sig_bias,
        gam_master=gam_master, gam_r=gam_r, gam_g=gam_g, gam_b=gam_b,
        sat=sat, grayscale=grayscale, brightness=brightness,
    )
    png = array_to_png(result)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/api/presets")
def list_presets():
    """Return available treatment presets."""
    return PRESETS


# ── Snapshot persistence ─────────────────────────────
# Playground state (the active working state + named snapshots) is kept
# in a JSON file on disk instead of browser localStorage, so it survives
# clearing browser data and is inspectable/portable on this machine.

SNAPSHOTS_PATH = DATA_DIR / "playground_snapshots.json"


def _read_snapshots_file() -> dict:
    if not SNAPSHOTS_PATH.exists():
        return {"active": None, "snapshots": []}
    return json.loads(SNAPSHOTS_PATH.read_text())


def _write_snapshots_file(data: dict) -> None:
    SNAPSHOTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_PATH.write_text(json.dumps(data, indent=2))


@app.get("/api/snapshots")
def get_snapshots():
    """Return {active, snapshots} — the full persisted playground state."""
    return _read_snapshots_file()


@app.put("/api/snapshots/active")
def put_active_snapshot(state: dict = Body(...)):
    """Overwrite the active working state (auto-saved on every control change)."""
    data = _read_snapshots_file()
    data["active"] = state
    _write_snapshots_file(data)
    return {"ok": True}


@app.post("/api/snapshots")
def post_snapshot(payload: dict = Body(...)):
    """Save (or overwrite, by name) a named snapshot."""
    name = payload.get("name")
    state = payload.get("state")
    if not name or state is None:
        raise HTTPException(400, "name and state are required")
    data = _read_snapshots_file()
    data["snapshots"] = [s for s in data["snapshots"] if s["name"] != name]
    data["snapshots"].append({"name": name, "state": state, "timestamp": time.time() * 1000})
    _write_snapshots_file(data)
    return {"ok": True}


@app.delete("/api/snapshots/{name}")
def delete_snapshot_endpoint(name: str):
    """Delete a named snapshot."""
    data = _read_snapshots_file()
    data["snapshots"] = [s for s in data["snapshots"] if s["name"] != name]
    _write_snapshots_file(data)
    return {"ok": True}


# ── Presets ──────────────────────────────────────────

PRESETS = {
    "default": {
        "label": "Default",
        "basemap": {},
        "vacant": {},
        "nonvacant": {},
    },
    "planning_view": {
        "label": "Planning View",
        "basemap": {"gray": 0.8, "br": 0.9},
        "vacant": {"br": 1.3, "sat": 1.4},
        "nonvacant": {"gray": 1.0, "br": 0.7},
    },
    "high_contrast": {
        "label": "High Contrast",
        "basemap": {"sc": 15, "sb": 0.5},
        "vacant": {"sc": 20, "sb": 0.4, "sat": 1.5},
        "nonvacant": {"sc": 10, "sb": 0.6, "gray": 0.5},
    },
    "satellite_clean": {
        "label": "Satellite Clean",
        "basemap": {"sc": 8, "sb": 0.45, "sat": 1.2, "g": 0.9},
        "vacant": {},
        "nonvacant": {},
    },
    "dark_mode": {
        "label": "Dark Mode",
        "basemap": {"br": 0.4, "sc": 5, "sb": 0.3},
        "vacant": {"br": 0.8, "tint": "1a1a2e", "to": 0.3},
        "nonvacant": {"br": 0.3, "gray": 0.6},
    },
    "vacant_highlight": {
        "label": "Vacant Highlight",
        "basemap": {"gray": 0.6, "br": 0.8},
        "vacant": {"sat": 1.8, "br": 1.2, "sc": 10, "sb": 0.5},
        "nonvacant": {"gray": 0.9, "br": 0.6},
    },
}
