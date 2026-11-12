"""Vacancy tile compositing: color treatments + vacancy masks (data/masks/).

Used to prerender the PMTiles archives (scripts/prerender_tiles.py,
scripts/generate_pmtiles.py) and by the dev-only playground (server/playground.py).
The production app (server/app.py) never imports this: it only serves the archives.
"""

import io
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from color_operations import sigmoidal, gamma, saturation
from PIL import Image

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


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


def uint8_to_jpeg(arr: np.ndarray, quality: int = 85) -> bytes:
    """(H, W, 3) uint8 array → JPEG bytes."""
    img = Image.fromarray(arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
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


# ── Product tile compositing ─────────────────────────
# Treatment values loaded from data/product_treatment.json.

_treatment = json.loads((DATA_DIR / "product_treatment.json").read_text())
PRODUCT_BASE = _treatment["base"]
PRODUCT_OUTSIDE = _treatment.get("outside", {})
PRODUCT_NV = _treatment["nonvacant"]

MASKS_DIR = DATA_DIR / "masks"

# Threshold names, ascending (the index order model_levels tiles encode). Defined in
# data/thresholds.json (scripts/extract_metrics.py), which the frontend slider also reads;
# data/masks/ must have a mask for each (test_every_threshold_has_a_mask).
THRESHOLDS = [cp["tStr"] for cp in json.loads((DATA_DIR / "thresholds.json").read_text())["checkpoints"]]


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


def _tile_cropper(z, x, y, bounds, shape):
    """Return crop(full_array, fill=0) mapping a full-extent mask onto this 256x256 tile.

    Nearest-neighbor, so any per-pixel value (bool mask or uint8 level) samples the
    same source pixels. Returns None if the tile is fully outside the mask extent.
    """
    ml, mb, mr, mt = bounds
    tl, tb, tr, tt = _tile_to_mercator_bounds(z, x, y)

    if tr <= ml or tl >= mr or tt <= mb or tb >= mt:
        return None

    h, w = shape
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
        return None

    dst_left = max(0, (src_left - px_left) / (px_right - px_left) * 256)
    dst_top = max(0, (src_top - px_top) / (px_bottom - px_top) * 256)
    dst_right = min(256, (src_right - px_left) / (px_right - px_left) * 256)
    dst_bottom = min(256, (src_top - px_top + (src_bottom - src_top)) / (px_bottom - px_top) * 256)
    dst_w = max(1, int(round(dst_right - dst_left)))
    dst_h = max(1, int(round(dst_bottom - dst_top)))
    dl, dt = int(round(dst_left)), int(round(dst_top))

    def crop(full, fill=0):
        if full.dtype == bool:
            return _crop_resize_mask(
                full, src_top, src_bottom, src_left, src_right, dst_h, dst_w, dt, dl)
        part = full[src_top:src_bottom, src_left:src_right]
        resized = np.array(Image.fromarray(part).resize((dst_w, dst_h), Image.NEAREST))
        tile = np.full((256, 256), fill, dtype=full.dtype)
        tile[dt:dt + dst_h, dl:dl + dst_w] = resized
        return tile

    return crop


def _get_tile_masks(z, x, y, threshold_str, source="both"):
    """Return (vacant_mask, nonvacant_mask) resized to 256x256 for this tile.

    source: "model" (model only), "pluto" (PLUTO only), "both" (model OR pluto).
    Returns (None, None) if the tile is fully outside the mask extent.
    """
    masks = _load_product_masks(threshold_str)
    if masks is None:
        return None, None

    _crop = _tile_cropper(z, x, y, masks["bounds"], masks["shape"])
    if _crop is None:
        return None, None

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


def composite_tile_u8(tile_u8, z, x, y, t, src, base_kwargs, outside_kwargs, nv_kwargs):
    """Composite an Esri tile array with the vacancy treatments. Returns (256, 256, 3) uint8."""
    vacant_mask, nonvacant_mask = _get_tile_masks(z, x, y, t, source=src)

    if vacant_mask is None:
        return apply_color_ops_fast(tile_u8, **outside_kwargs)

    base_out = apply_color_ops_fast(tile_u8, **base_kwargs)
    nv_out = apply_color_ops_fast(tile_u8, **nv_kwargs)

    result = base_out
    result[nonvacant_mask] = nv_out[nonvacant_mask]

    boundary = vacant_mask | nonvacant_mask
    outside_pixels = ~boundary
    if outside_pixels.any():
        outside_out = apply_color_ops_fast(tile_u8, **outside_kwargs)
        result[outside_pixels] = outside_out[outside_pixels]

    return result


# ── Model-only from Model + PLUTO ────────────────────
# Model-only differs from Model + PLUTO only on PLUTO pixels the model doesn't call
# vacant at the current threshold: those need the non-vacant treatment instead of
# the vacant one. The browser builds Model-only tiles from both/{t}.pmtiles plus two
# threshold-independent archives (src/lib/tiles.js, scripts/generate_pmtiles.py):
#   pluto_nonvacant: Esri with the non-vacant treatment, tiles containing PLUTO only
#   model_levels:    per PLUTO pixel, how many thresholds the model calls it vacant
#                    (vacant masks are nested, so vacant at thresholds[i] <=> level > i);
#                    LEVEL_NOT_PLUTO elsewhere, meaning never replace
# Take the pluto_nonvacant pixel at threshold index i  <=>  level <= i.

LEVEL_NOT_PLUTO = 255


@lru_cache(maxsize=1)
def _load_model_levels():
    """Full-extent uint8 raster: number of thresholds at which each pixel is model-vacant."""
    shared = _load_shared_masks()
    level = np.zeros(shared["shape"], dtype=np.uint8)
    for t in THRESHOLDS:
        vacant_path = MASKS_DIR / t / "vacant.png"
        level += (np.array(Image.open(vacant_path))[:, :, 3] > 127)
    return level


def get_model_level_tile(z, x, y):
    """uint8 256x256 model_levels tile, or None if the tile has no PLUTO pixels."""
    shared = _load_shared_masks()
    if shared is None or shared.get("pluto_vacant") is None:
        return None
    crop = _tile_cropper(z, x, y, shared["bounds"], shared["shape"])
    if crop is None:
        return None
    pluto_tile = crop(shared["pluto_vacant"])
    if not pluto_tile.any():
        return None
    level_tile = crop(_load_model_levels())
    return np.where(pluto_tile, level_tile, LEVEL_NOT_PLUTO).astype(np.uint8)


def select_model_only(both_u8, nonvacant_u8, level_tile, threshold_index):
    """Model-only tile from a Model + PLUTO tile: pixel selection only, no color math."""
    out = both_u8.copy()
    replace = level_tile <= threshold_index
    out[replace] = nonvacant_u8[replace]
    return out
