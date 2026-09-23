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
from fastapi.staticfiles import StaticFiles
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


def tile_bytes_to_uint8(tile_bytes: bytes) -> np.ndarray:
    """PNG/JPEG bytes → (H, W, 3) uint8 array."""
    img = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
    return np.array(img, dtype=np.uint8)


def array_to_png(arr: np.ndarray) -> bytes:
    """(3, H, W) float64 array → PNG bytes."""
    img_arr = (arr.transpose(1, 2, 0) * 255).astype(np.uint8)  # (H, W, 3)
    img = Image.fromarray(img_arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def uint8_to_png(arr: np.ndarray) -> bytes:
    """(H, W, 3) uint8 array → PNG bytes."""
    img = Image.fromarray(arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


# ── LUT-based fast color ops ─────────────────────────

def _build_channel_lut(sig_contrast=0, sig_bias=0.5, gam_master=1, gam=1,
                       brightness=1, grayscale=0):
    """Build a 256-entry uint8 LUT for one channel's non-mixing ops."""
    vals = np.linspace(0, 1, 256).reshape(1, 1, 256)
    if sig_contrast > 0:
        vals = sigmoidal(vals, sig_contrast, sig_bias)
    if gam != 1.0:
        vals = gamma(vals, gam)
    if gam_master != 1.0:
        vals = gamma(vals, gam_master)
    if brightness != 1.0:
        vals = np.clip(vals * brightness, 0, 1)
    return (vals[0, 0] * 255 + 0.5).astype(np.uint8)


def _build_luts(sig_contrast=0, sig_bias=0.5, gam_master=1,
                gam_r=1, gam_g=1, gam_b=1, brightness=1, **_kw):
    """Build per-channel LUTs for sigmoidal + gamma + brightness."""
    common = dict(sig_contrast=sig_contrast, sig_bias=sig_bias,
                  gam_master=gam_master, brightness=brightness)
    return (
        _build_channel_lut(gam=gam_r, **common),
        _build_channel_lut(gam=gam_g, **common),
        _build_channel_lut(gam=gam_b, **common),
    )


def _apply_luts(tile_u8, lut_r, lut_g, lut_b):
    """Apply per-channel LUTs to (H, W, 3) uint8 array. Returns (H, W, 3) uint8."""
    out = np.empty_like(tile_u8)
    out[:, :, 0] = lut_r[tile_u8[:, :, 0]]
    out[:, :, 1] = lut_g[tile_u8[:, :, 1]]
    out[:, :, 2] = lut_b[tile_u8[:, :, 2]]
    return out


def _sat_oklch(arr_u8, proportion):
    """Oklch saturation on (H, W, 3) uint8. Returns (H, W, 3) uint8."""
    f = arr_u8.astype(np.float32) / 255.0
    r, g, b = f[:, :, 0], f[:, :, 1], f[:, :, 2]

    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b

    l_ = np.cbrt(l)
    m_ = np.cbrt(m)
    s_ = np.cbrt(s)

    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    A = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_

    A *= proportion
    B *= proportion

    l_ = L + 0.3963377774 * A + 0.2158037573 * B
    m_ = L - 0.1055613458 * A - 0.0638541728 * B
    s_ = L - 0.0894841775 * A - 1.2914855480 * B

    l = l_ * l_ * l_
    m = m_ * m_ * m_
    s = s_ * s_ * s_

    ro = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    go = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bo = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    out = np.stack([ro, go, bo], axis=-1)
    return np.clip(out * 255, 0, 255).astype(np.uint8)


def _grayscale_u8(arr_u8, amount):
    """Apply grayscale blend to (H, W, 3) uint8. Returns (H, W, 3) uint8."""
    f = arr_u8.astype(np.float32)
    lum = (0.2126 * f[:, :, 0] + 0.7152 * f[:, :, 1] + 0.0722 * f[:, :, 2])
    result = f * (1 - amount) + lum[:, :, np.newaxis] * amount
    return np.clip(result, 0, 255).astype(np.uint8)


def _tint_u8(arr_u8, tint_r, tint_g, tint_b, opacity):
    """Apply tint overlay to (H, W, 3) uint8. Returns (H, W, 3) uint8."""
    f = arr_u8.astype(np.float32)
    tint = np.array([tint_r, tint_g, tint_b], dtype=np.float32)
    result = f * (1 - opacity) + tint * opacity
    return np.clip(result, 0, 255).astype(np.uint8)


def apply_color_ops_fast(tile_u8, **kwargs):
    """Fast LUT-based color ops on (H, W, 3) uint8. Returns (H, W, 3) uint8.

    Uses Oklch color space for saturation.
    """
    lut_r, lut_g, lut_b = _build_luts(**kwargs)
    out = _apply_luts(tile_u8, lut_r, lut_g, lut_b)

    sat_val = kwargs.get("sat", 1.0)
    if sat_val != 1.0:
        out = _sat_oklch(out, sat_val)

    gs = kwargs.get("grayscale", 0)
    if gs > 0:
        out = _grayscale_u8(out, gs)

    tint_opacity = kwargs.get("tint_opacity", 0)
    if tint_opacity > 0:
        out = _tint_u8(out, kwargs.get("tint_r", 0),
                       kwargs.get("tint_g", 0), kwargs.get("tint_b", 0), tint_opacity)

    return out



DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ── Product tile compositing ─────────────────────────
# Treatment values loaded from data/product_treatment.json.

_treatment = json.loads((DATA_DIR / "product_treatment.json").read_text())
PRODUCT_BASE = _treatment["base"]
PRODUCT_OUTSIDE = _treatment.get("outside", {})
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

    pluto_path = MASKS_DIR / "pluto_vacant.png"
    pluto_arr = None
    if pluto_path.exists():
        pluto_arr = (np.array(Image.open(pluto_path))[:, :, 3] > 127)

    return {
        "boundary": boundary_arr,
        "pluto_vacant": pluto_arr,
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


def _crop_resize_mask(full_mask, src_top, src_bottom, src_left, src_right,
                      dst_h, dst_w, dst_top, dst_left):
    """Crop a full-resolution boolean mask and resize it into a 256x256 tile."""
    crop = full_mask[src_top:src_bottom, src_left:src_right]
    resized = np.array(
        Image.fromarray(crop.astype(np.uint8) * 255).resize(
            (dst_w, dst_h), Image.NEAREST
        )
    ) > 127
    tile = np.zeros((256, 256), dtype=bool)
    tile[dst_top:dst_top + dst_h, dst_left:dst_left + dst_w] = resized
    return tile


def _get_tile_masks(z, x, y, threshold_str, source="both"):
    """Return (vacant_mask, nonvacant_mask) resized to 256x256 for this tile.

    source: "model" (model only), "pluto" (PLUTO only), "both" (model OR pluto).
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

    src_left = max(0, int(math.floor(px_left)))
    src_top = max(0, int(math.floor(px_top)))
    src_right = min(w, int(math.ceil(px_right)))
    src_bottom = min(h, int(math.ceil(px_bottom)))

    if src_right <= src_left or src_bottom <= src_top:
        return None, None

    dst_left = max(0, (src_left - px_left) / (px_right - px_left) * 256)
    dst_top = max(0, (src_top - px_top) / (px_bottom - px_top) * 256)
    dst_right = min(256, (src_right - px_left) / (px_right - px_left) * 256)
    dst_bottom = min(256, (src_top - px_top + (src_bottom - src_top)) / (px_bottom - px_top) * 256)
    dst_w = max(1, int(round(dst_right - dst_left)))
    dst_h = max(1, int(round(dst_bottom - dst_top)))
    dl, dt = int(round(dst_left)), int(round(dst_top))

    def _crop(full_mask):
        return _crop_resize_mask(
            full_mask, src_top, src_bottom, src_left, src_right, dst_h, dst_w, dt, dl)

    model_vacant = _crop(masks["vacant"])
    model_nonvacant = _crop(masks["nonvacant"])

    if source == "model":
        return model_vacant, model_nonvacant

    shared = _load_shared_masks()
    pluto_full = shared.get("pluto_vacant") if shared else None

    if pluto_full is None:
        if source == "pluto":
            return np.zeros((256, 256), dtype=bool), np.zeros((256, 256), dtype=bool)
        return model_vacant, model_nonvacant

    pluto_tile = _crop(pluto_full)

    if source == "pluto":
        boundary = model_vacant | model_nonvacant
        return pluto_tile, boundary & ~pluto_tile

    vacant_tile = model_vacant | pluto_tile
    nonvacant_tile = model_nonvacant & ~pluto_tile
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


def _aliases_to_color_params(
    sc=0, sb=0.5, g=1.0, gr=1.0, gg=1.0, gb=1.0,
    sat=1.0, gray=0.0, br=1.0, tint="000000", to=0.0,
):
    """Convert short alias names (used by the playground UI) to apply_color_ops kwargs."""
    tc = str(tint).lstrip("#")
    return dict(
        sig_contrast=float(sc), sig_bias=float(sb),
        gam_master=float(g), gam_r=float(gr), gam_g=float(gg), gam_b=float(gb),
        sat=float(sat), grayscale=float(gray), brightness=float(br),
        tint_r=int(tc[0:2], 16) if len(tc) >= 6 else 0,
        tint_g=int(tc[2:4], 16) if len(tc) >= 6 else 0,
        tint_b=int(tc[4:6], 16) if len(tc) >= 6 else 0,
        tint_opacity=float(to),
    )


@app.get("/api/tile/product/{z}/{x}/{y}.png")
async def product_tile(
    z: int, x: int, y: int,
    t: str = Query("t0298"),
    source: str = Query("both"),
    mode: str = Query(None),
    # Basemap treatment (playground mode)
    bm_sc: float = Query(0), bm_sb: float = Query(0.5),
    bm_g: float = Query(1), bm_gr: float = Query(1),
    bm_gg: float = Query(1), bm_gb: float = Query(1),
    bm_sat: float = Query(1), bm_gray: float = Query(0),
    bm_br: float = Query(1),
    # Vacant treatment (playground mode)
    vc_sc: float = Query(0), vc_sb: float = Query(0.5),
    vc_g: float = Query(1), vc_gr: float = Query(1),
    vc_gg: float = Query(1), vc_gb: float = Query(1),
    vc_sat: float = Query(1), vc_gray: float = Query(0),
    vc_br: float = Query(1),
    vc_tint: str = Query("000000"), vc_to: float = Query(0),
    # Non-vacant treatment (playground mode)
    nv_sc: float = Query(0), nv_sb: float = Query(0.5),
    nv_g: float = Query(1), nv_gr: float = Query(1),
    nv_gg: float = Query(1), nv_gb: float = Query(1),
    nv_sat: float = Query(1), nv_gray: float = Query(0),
    nv_br: float = Query(1),
):
    """Return a composited tile with base/outside/non-vacant treatments.

    Zones: base (whole tile, vacant pixels keep this), non-vacant (mask override),
    outside boundary (mask override for pixels outside the study area).

    bm_* = base treatment, vc_* = outside boundary treatment, nv_* = non-vacant.
    Without mode=playground, uses baked-in treatments from product_treatment.json.
    """
    tile_bytes = await fetch_esri_tile(z, x, y)

    if mode == "playground":
        base_kwargs = _aliases_to_color_params(
            sc=bm_sc, sb=bm_sb, g=bm_g, gr=bm_gr, gg=bm_gg, gb=bm_gb,
            sat=bm_sat, gray=bm_gray, br=bm_br,
        )
        outside_kwargs = _aliases_to_color_params(
            sc=vc_sc, sb=vc_sb, g=vc_g, gr=vc_gr, gg=vc_gg, gb=vc_gb,
            sat=vc_sat, gray=vc_gray, br=vc_br, tint=vc_tint, to=vc_to,
        )
        nv_kwargs = _aliases_to_color_params(
            sc=nv_sc, sb=nv_sb, g=nv_g, gr=nv_gr, gg=nv_gg, gb=nv_gb,
            sat=nv_sat, gray=nv_gray, br=nv_br,
        )
    else:
        base_kwargs = PRODUCT_BASE
        outside_kwargs = PRODUCT_OUTSIDE
        nv_kwargs = PRODUCT_NV

    src = source if source in ("model", "pluto", "both") else "both"
    vacant_mask, nonvacant_mask = _get_tile_masks(z, x, y, t, source=src)

    tile_u8 = tile_bytes_to_uint8(tile_bytes)

    # Tile fully outside study area — use outside treatment
    if vacant_mask is None:
        result = apply_color_ops_fast(tile_u8, **outside_kwargs)
        return Response(content=uint8_to_png(result), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})

    # Base applied everywhere (vacant pixels keep this)
    base_out = apply_color_ops_fast(tile_u8, **base_kwargs)
    nv_out = apply_color_ops_fast(tile_u8, **nv_kwargs)

    result = base_out
    result[nonvacant_mask] = nv_out[nonvacant_mask]

    # Outside boundary: pixels in this tile that aren't vacant or non-vacant
    boundary = vacant_mask | nonvacant_mask
    outside_pixels = ~boundary
    if outside_pixels.any():
        outside_out = apply_color_ops_fast(tile_u8, **outside_kwargs)
        result[outside_pixels] = outside_out[outside_pixels]

    cache = "no-cache" if mode == "playground" else "public, max-age=3600"
    return Response(content=uint8_to_png(result), media_type="image/png",
                    headers={"Cache-Control": cache})


def _color_params_to_aliases(params: dict) -> dict:
    """Convert apply_color_ops param names to playground short aliases."""
    mapping = {
        "sig_contrast": "sc", "sig_bias": "sb",
        "gam_master": "g", "gam_r": "gr", "gam_g": "gg", "gam_b": "gb",
        "sat": "sat", "grayscale": "gray", "brightness": "br",
    }
    return {mapping.get(k, k): v for k, v in params.items() if k in mapping}


_STATIC_PRESETS = {
    "planning_view": {
        "label": "Planning View",
        "base": {"br": 1.3, "sat": 1.4},
        "outside": {"gray": 0.8, "br": 0.9},
        "nonvacant": {"gray": 1.0, "br": 0.7},
    },
    "high_contrast": {
        "label": "High Contrast",
        "base": {"sc": 20, "sb": 0.4, "sat": 1.5},
        "outside": {"sc": 15, "sb": 0.5},
        "nonvacant": {"sc": 10, "sb": 0.6, "gray": 0.5},
    },
    "satellite_clean": {
        "label": "Satellite Clean",
        "base": {"sc": 8, "sb": 0.45, "sat": 1.2, "g": 0.9},
        "outside": {},
        "nonvacant": {},
    },
    "dark_mode": {
        "label": "Dark Mode",
        "base": {"br": 0.8, "tint": "1a1a2e", "to": 0.3},
        "outside": {"br": 0.4, "sc": 5, "sb": 0.3},
        "nonvacant": {"br": 0.3, "gray": 0.6},
    },
}


@app.get("/api/presets")
def list_presets():
    """Return presets: production from config file + static exploration presets."""
    treatment = json.loads((DATA_DIR / "product_treatment.json").read_text())
    presets = {
        "production": {
            "label": "Production (" + treatment.get("name", "default") + ")",
            "base": _color_params_to_aliases(treatment.get("base", {})),
            "outside": _color_params_to_aliases(treatment.get("outside", {})),
            "nonvacant": _color_params_to_aliases(treatment.get("nonvacant", {})),
            "cd": treatment.get("cd", {}),
        },
    }
    presets.update(_STATIC_PRESETS)
    return presets


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

# ── Static frontend (production) ─────────────────────
# In dev, Vite serves the frontend directly. In production (Docker),
# FastAPI serves the built dist/ so both run on the same port.
_DIST_DIR = Path(__file__).resolve().parent.parent / "dist"
if _DIST_DIR.exists():
    from starlette.responses import RedirectResponse

    @app.get("/playground")
    async def playground_redirect():
        return RedirectResponse("/playground.html")

    app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="static")

