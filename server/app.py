"""FastAPI backend for playground tile processing.

Proxies Esri basemap tiles, applies color operations (rio-color) with
mask-based regional treatment (basemap / vacant / non-vacant), and
returns processed PNGs.
"""

import io
import json
import math
import time
from functools import lru_cache
from pathlib import Path

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



DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ── Product tile compositing ─────────────────────────
# Treatment values loaded from data/product_treatment.json.

_treatment = json.loads((DATA_DIR / "product_treatment.json").read_text())
PRODUCT_BM = _treatment["basemap"]
PRODUCT_VC = _treatment["vacant"]
PRODUCT_NV = _treatment["nonvacant"]

MASKS_DIR = DATA_DIR / "masks"


def _lonlat_to_mercator(lon, lat):
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 20037508.34 / math.pi
    return x, y


def _tile_to_mercator_bounds(z, x, y):
    circ = 40075016.686
    tile_size = circ / (2 ** z)
    origin = circ / 2
    left = x * tile_size - origin
    right = (x + 1) * tile_size - origin
    top = origin - y * tile_size
    bottom = origin - (y + 1) * tile_size
    return left, bottom, right, top


@lru_cache(maxsize=1)
def _load_shared_masks():
    """Load the shared boundary mask and Mercator bounds (threshold-independent)."""
    boundary_path = MASKS_DIR / "boundary.png"
    bounds_path = MASKS_DIR / "bounds.json"

    if not boundary_path.exists():
        return None

    bounds = json.loads(bounds_path.read_text())
    ml, mb = _lonlat_to_mercator(bounds["west"], bounds["south"])
    mr, mt = _lonlat_to_mercator(bounds["east"], bounds["north"])

    boundary_arr = (np.array(Image.open(boundary_path))[:, :, 3] > 127)

    return {
        "boundary": boundary_arr,
        "bounds": (ml, mb, mr, mt),
        "shape": boundary_arr.shape,
    }


@lru_cache(maxsize=8)
def _load_product_masks(threshold_str: str):
    """Load vacant mask for a threshold, derive non-vacant from shared boundary."""
    shared = _load_shared_masks()
    if shared is None:
        return None

    vacant_path = MASKS_DIR / threshold_str / "vacant.png"
    if not vacant_path.exists():
        return None

    vacant_arr = (np.array(Image.open(vacant_path))[:, :, 3] > 127)
    nonvacant_arr = shared["boundary"] & ~vacant_arr

    return {
        "vacant": vacant_arr,
        "nonvacant": nonvacant_arr,
        "bounds": shared["bounds"],
        "shape": shared["shape"],
    }


def _get_tile_masks(z, x, y, threshold_str):
    """Return (vacant_mask, nonvacant_mask) resized to 256x256 for this tile.

    Returns (None, None) if the tile is fully outside the mask extent.
    """
    masks = _load_product_masks(threshold_str)
    if masks is None:
        return None, None

    ml, mb, mr, mt = masks["bounds"]
    tl, tb, tr, tt = _tile_to_mercator_bounds(z, x, y)

    if tr <= ml or tl >= mr or tt <= mb or tb >= mt:
        return None, None

    h, w = masks["shape"]
    mx_per_px = (mr - ml) / w
    my_per_px = (mt - mb) / h

    px_left = (tl - ml) / mx_per_px
    px_right = (tr - ml) / mx_per_px
    px_top = (mt - tt) / my_per_px
    px_bottom = (mt - tb) / my_per_px

    # Clamp to mask bounds
    src_left = max(0, int(math.floor(px_left)))
    src_top = max(0, int(math.floor(px_top)))
    src_right = min(w, int(math.ceil(px_right)))
    src_bottom = min(h, int(math.ceil(px_bottom)))

    if src_right <= src_left or src_bottom <= src_top:
        return None, None

    # Crop and resize to 256x256
    # Compute destination rect (where in the 256x256 tile this crop lands)
    dst_left = max(0, (src_left - px_left) / (px_right - px_left) * 256)
    dst_top = max(0, (src_top - px_top) / (px_bottom - px_top) * 256)
    dst_right = min(256, (src_right - px_left) / (px_right - px_left) * 256)
    dst_bottom = min(256, (src_top - px_top + (src_bottom - src_top)) / (px_bottom - px_top) * 256)
    # Simpler: resize the cropped region to fill the destination rect
    dst_w = max(1, int(round(dst_right - dst_left)))
    dst_h = max(1, int(round(dst_bottom - dst_top)))

    vacant_crop = masks["vacant"][src_top:src_bottom, src_left:src_right]
    nonvacant_crop = masks["nonvacant"][src_top:src_bottom, src_left:src_right]

    vacant_resized = np.array(
        Image.fromarray(vacant_crop.astype(np.uint8) * 255).resize((dst_w, dst_h), Image.NEAREST)
    ) > 127
    nonvacant_resized = np.array(
        Image.fromarray(nonvacant_crop.astype(np.uint8) * 255).resize((dst_w, dst_h), Image.NEAREST)
    ) > 127

    # Place into 256x256 tile
    vacant_tile = np.zeros((256, 256), dtype=bool)
    nonvacant_tile = np.zeros((256, 256), dtype=bool)
    dl, dt = int(round(dst_left)), int(round(dst_top))
    vacant_tile[dt:dt + dst_h, dl:dl + dst_w] = vacant_resized
    nonvacant_tile[dt:dt + dst_h, dl:dl + dst_w] = nonvacant_resized

    return vacant_tile, nonvacant_tile


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


@app.get("/api/tile/product/{z}/{x}/{y}.png")
async def product_tile(
    z: int, x: int, y: int,
    t: str = Query("t0298"),
):
    """Return a composited tile with basemap/vacant/non-vacant treatments baked in."""
    tile_bytes = await fetch_esri_tile(z, x, y)
    arr = tile_bytes_to_array(tile_bytes)

    vacant_mask, nonvacant_mask = _get_tile_masks(z, x, y, t)

    if vacant_mask is None:
        # Tile is outside the mask — apply basemap treatment only
        result = apply_color_ops(arr, **PRODUCT_BM)
        return Response(content=array_to_png(result), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})

    bm_arr = apply_color_ops(arr.copy(), **PRODUCT_BM)
    vc_arr = apply_color_ops(arr.copy(), **PRODUCT_VC)
    nv_arr = apply_color_ops(arr.copy(), **PRODUCT_NV)

    # Composite: vacant pixels get vc, non-vacant get nv, rest get bm
    result = bm_arr
    result[:, nonvacant_mask] = nv_arr[:, nonvacant_mask]
    result[:, vacant_mask] = vc_arr[:, vacant_mask]

    return Response(content=array_to_png(result), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


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
