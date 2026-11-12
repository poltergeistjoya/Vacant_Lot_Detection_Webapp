"""Color-tuning playground API (local dev only; served by server/dev.py, never deployed).

Proxies Esri basemap tiles and composites them live with the vacancy masks
(server/compositing.py) so color treatments can be tuned before prerendering.
"""

import asyncio
import concurrent.futures
import json
import time
from collections import OrderedDict

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request, Response

from server.compositing import (
    DATA_DIR, apply_color_ops, array_to_png, composite_tile_u8, tile_bytes_to_array,
    tile_bytes_to_uint8, uint8_to_jpeg,
)

router = APIRouter()

# ── Esri tile fetching ───────────────────────────────
ESRI_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

_client = httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=20))


async def _fetch_esri_raw(z: int, x: int, y: int) -> bytes:
    url = ESRI_URL.format(z=z, y=y, x=x)
    resp = await _client.get(url)
    resp.raise_for_status()
    return resp.content


_ESRI_CACHE_MAX = 512
_esri_cache: OrderedDict[tuple, bytes] = OrderedDict()
_esri_inflight: dict[tuple, asyncio.Future] = {}


async def fetch_esri_tile(z: int, x: int, y: int) -> bytes:
    """Fetch an Esri basemap tile, with in-memory LRU cache."""
    key = (z, x, y)

    if key in _esri_cache:
        _esri_cache.move_to_end(key)
        return _esri_cache[key]

    if key in _esri_inflight:
        return await _esri_inflight[key]

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[bytes] = loop.create_future()
    _esri_inflight[key] = fut
    try:
        data = await _fetch_esri_raw(z, x, y)
        _esri_cache[key] = data
        _esri_cache.move_to_end(key)
        while len(_esri_cache) > _ESRI_CACHE_MAX:
            _esri_cache.popitem(last=False)
        fut.set_result(data)
        return data
    except Exception as e:
        fut.set_exception(e)
        raise
    finally:
        _esri_inflight.pop(key, None)


# ── Single-treatment tiles ───────────────────────────

@router.get("/api/tile/{z}/{x}/{y}.png")
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

    # Apply basemap treatment to the whole tile; vacant/non-vacant panes
    # request their own tiles from separate endpoints
    result = apply_color_ops(
        arr.copy(),
        sig_contrast=bm_sig_contrast, sig_bias=bm_sig_bias,
        gam_master=bm_gamma, gam_r=bm_gamma_r, gam_g=bm_gamma_g, gam_b=bm_gamma_b,
        sat=bm_saturation, grayscale=bm_grayscale, brightness=bm_brightness,
    )
    png = array_to_png(result)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@router.get("/api/tile/vacant/{z}/{x}/{y}.png")
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


@router.get("/api/tile/nonvacant/{z}/{x}/{y}.png")
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


# ── Composited product tiles ─────────────────────────

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


_composite_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _composite_tile_sync(tile_bytes, z, x, y, t, src, base_kwargs, outside_kwargs, nv_kwargs):
    """CPU-heavy tile compositing. Runs in thread pool to keep the event loop free."""
    tile_u8 = tile_bytes_to_uint8(tile_bytes)
    return uint8_to_jpeg(composite_tile_u8(tile_u8, z, x, y, t, src, base_kwargs, outside_kwargs, nv_kwargs))


@router.get("/api/tile/product/{z}/{x}/{y}.jpg")
async def product_tile(
    request: Request,
    z: int, x: int, y: int,
    t: str = Query("t0298"),
    source: str = Query("both"),
    # Basemap treatment
    bm_sc: float = Query(0), bm_sb: float = Query(0.5),
    bm_g: float = Query(1), bm_gr: float = Query(1),
    bm_gg: float = Query(1), bm_gb: float = Query(1),
    bm_sat: float = Query(1), bm_gray: float = Query(0),
    bm_br: float = Query(1),
    # Outside-boundary treatment
    vc_sc: float = Query(0), vc_sb: float = Query(0.5),
    vc_g: float = Query(1), vc_gr: float = Query(1),
    vc_gg: float = Query(1), vc_gb: float = Query(1),
    vc_sat: float = Query(1), vc_gray: float = Query(0),
    vc_br: float = Query(1),
    vc_tint: str = Query("000000"), vc_to: float = Query(0),
    # Non-vacant treatment
    nv_sc: float = Query(0), nv_sb: float = Query(0.5),
    nv_g: float = Query(1), nv_gr: float = Query(1),
    nv_gg: float = Query(1), nv_gb: float = Query(1),
    nv_sat: float = Query(1), nv_gray: float = Query(0),
    nv_br: float = Query(1),
):
    """Live-composited tile with the treatments in the query.

    Zones: base (whole tile, vacant pixels keep this), non-vacant (mask override),
    outside boundary (mask override for pixels outside the study area).

    bm_* = base treatment, vc_* = outside boundary treatment, nv_* = non-vacant.
    """
    src = source if source in ("model", "pluto", "both") else "both"

    # Skip work if the client already disconnected (e.g. tile scrolled out of view)
    if await request.is_disconnected():
        return Response(status_code=499)

    tile_bytes = await fetch_esri_tile(z, x, y)

    if await request.is_disconnected():
        return Response(status_code=499)

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

    loop = asyncio.get_running_loop()
    tile_out = await loop.run_in_executor(
        _composite_pool,
        _composite_tile_sync,
        tile_bytes, z, x, y, t, src, base_kwargs, outside_kwargs, nv_kwargs,
    )
    return Response(content=tile_out, media_type="image/jpeg",
                    headers={"Cache-Control": "no-cache"})


# ── Presets ──────────────────────────────────────────

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


@router.get("/api/presets")
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


@router.get("/api/snapshots")
def get_snapshots():
    """Return {active, snapshots} — the full persisted playground state."""
    return _read_snapshots_file()


@router.put("/api/snapshots/active")
def put_active_snapshot(state: dict = Body(...)):
    """Overwrite the active working state (auto-saved on every control change)."""
    data = _read_snapshots_file()
    data["active"] = state
    _write_snapshots_file(data)
    return {"ok": True}


@router.post("/api/snapshots")
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


@router.delete("/api/snapshots/{name}")
def delete_snapshot_endpoint(name: str):
    """Delete a named snapshot."""
    data = _read_snapshots_file()
    data["snapshots"] = [s for s in data["snapshots"] if s["name"] != name]
    _write_snapshots_file(data)
    return {"ok": True}
