"""Regression tests for tile serving (PMTiles proxy) and prerendering (vacancy masks)."""

import subprocess
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

import server.app as app_mod
import server.compositing as comp
from server.app import create_app
from server.compositing import THRESHOLDS, _get_tile_masks, _tile_to_mercator_bounds

REPO = Path(__file__).resolve().parents[2]
PMTILES_DIR = REPO / "data" / "pmtiles"
SOURCES = ("both", "model", "pluto")


# ── Production app ────────────────────────────────────

def test_production_app_does_not_load_compositing():
    """The deployed app only proxies archives: no masks, no color treatment."""
    code = "import sys, server.app; sys.exit('server.compositing' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], cwd=REPO).returncode == 0


def test_playground_routes_only_in_dev_app():
    url = "/api/presets"
    assert TestClient(create_app()).get(url).status_code == 404
    assert TestClient(create_app(playground=True)).get(url).status_code == 200


# ── Thresholds ────────────────────────────────────────

def test_thresholds_are_ascending():
    assert THRESHOLDS == sorted(THRESHOLDS) and len(set(THRESHOLDS)) == len(THRESHOLDS)


def test_every_threshold_has_a_mask():
    """model_levels counts one mask per threshold, in THRESHOLDS order: a missing or extra
    mask would shift every level index and Model-only would swap the wrong pixels."""
    masks = sorted(d.name for d in comp.MASKS_DIR.iterdir() if (d / "vacant.png").exists())
    assert masks == THRESHOLDS


# ── Vacancy source mask semantics ─────────────────────

@pytest.fixture
def fake_masks(monkeypatch):
    """4x4 masks covering exactly one z18 tile.

    Columns: 0 = model vacant, 1 = model non-vacant, 2 = model vacant + PLUTO, 3 = no data (street).
    """
    z, x, y = 18, 77000, 98000
    bounds = _tile_to_mercator_bounds(z, x, y)
    vacant = np.zeros((4, 4), bool); vacant[:, 0] = vacant[:, 2] = True
    nonvacant = np.zeros((4, 4), bool); nonvacant[:, 1] = True
    pluto = np.zeros((4, 4), bool); pluto[:, 1] = pluto[:, 2] = True

    monkeypatch.setattr(comp, "_load_product_masks", lambda t: {
        "vacant": vacant, "nonvacant": nonvacant, "bounds": bounds, "shape": (4, 4)})
    monkeypatch.setattr(comp, "_load_shared_masks", lambda: {"pluto_vacant": pluto})
    return z, x, y


def _cols(mask):
    """Which of the 4 mask columns are set (sampled at the center of each 64px band)."""
    return [bool(mask[128, c * 64 + 32]) for c in range(4)]


def test_model_source_ignores_pluto(fake_masks):
    v, nv = _get_tile_masks(*fake_masks, "t0298", source="model")
    assert _cols(v) == [True, False, True, False]
    assert _cols(nv) == [False, True, False, False]


def test_pluto_source_ignores_model_vacancy(fake_masks):
    v, nv = _get_tile_masks(*fake_masks, "t0298", source="pluto")
    assert _cols(v) == [False, True, True, False]
    assert _cols(nv) == [True, False, False, False]


def test_both_is_union(fake_masks):
    v, nv = _get_tile_masks(*fake_masks, "t0298", source="both")
    assert _cols(v) == [True, True, True, False]
    assert _cols(nv) == [False, False, False, False]


def test_no_data_pixels_are_outside_boundary(fake_masks):
    for src in SOURCES:
        v, nv = _get_tile_masks(*fake_masks, "t0298", source=src)
        assert _cols(v | nv)[3] is False


# ── PLUTO-only reuses the Model + PLUTO t1000 archive ─

MASKS_DIR = REPO / "data" / "masks"


@pytest.mark.skipif(not (MASKS_DIR / "t1000" / "vacant.png").exists(), reason="masks not generated")
def test_pluto_only_equals_both_at_max_threshold():
    """The frontend serves PLUTO-only from both/t1000.pmtiles (src/lib/tiles.js).

    That's only valid while nothing is model-vacant at t1000 and PLUTO lies inside the
    boundary. If the model or masks change, this fails and PLUTO-only needs its own archive.
    """
    shared = comp._load_shared_masks()
    assert not comp._load_product_masks("t1000")["vacant"].any()
    assert not (shared["pluto_vacant"] & ~shared["boundary"]).any()


# ── Local PMTiles archives (skipped if not generated) ─

def _archives():
    return sorted(PMTILES_DIR.rglob("*.pmtiles")) if PMTILES_DIR.exists() else []


@pytest.mark.skipif(not _archives(), reason="no local PMTiles archives")
@pytest.mark.parametrize("path", _archives(), ids=lambda p: str(p.relative_to(PMTILES_DIR)))
def test_pmtiles_archive_header(path):
    from pmtiles.reader import Reader, MmapSource
    from pmtiles.tile import TileType

    is_levels = path.name == "model_levels.pmtiles"
    with open(path, "rb") as f:
        reader = Reader(MmapSource(f))
        h = reader.header()
        meta = reader.metadata()
    assert h["tile_type"] == (TileType.PNG if is_levels else TileType.JPEG)
    # Must match PMTILES_MAX_ZOOM in src/lib/tiles.js (regenerate archives if this fails)
    assert h["max_zoom"] == 19
    assert h["min_zoom"] <= 11
    if is_levels:
        # The browser maps thresholds to level indexes with this list
        assert meta["thresholds"] == THRESHOLDS


# ── Model-only from both + pluto_nonvacant + model_levels ─

_HAS_MASKS = (MASKS_DIR / "t1000" / "vacant.png").exists()
_CIRC = 40075016.686


def _tiles_with_pluto(zooms=(13, 16, 19), per_zoom=4):
    """A few real tiles containing PLUTO pixels, plus their east neighbors (mixed)."""
    shared = comp._load_shared_masks()
    ml, mb, mr, mt = shared["bounds"]
    h, w = shared["shape"]
    rows, cols = np.nonzero(shared["pluto_vacant"])
    picks = np.linspace(0, len(rows) - 1, per_zoom).astype(int)
    tiles = []
    for z in zooms:
        size = _CIRC / 2 ** z
        for i in picks:
            mx = ml + (cols[i] + 0.5) * (mr - ml) / w
            my = mt - (rows[i] + 0.5) * (mt - mb) / h
            x, y = int((mx + _CIRC / 2) // size), int((_CIRC / 2 - my) // size)
            tiles += [(z, x, y), (z, x + 3, y)]
    return tiles


@pytest.mark.skipif(not _HAS_MASKS, reason="masks not generated")
def test_threshold_masks_are_nested():
    """Level tiles assume vacant at a higher threshold implies vacant at every lower one."""
    prev = None
    for t in THRESHOLDS:
        v = comp._load_product_masks(t)["vacant"]
        if prev is not None:
            assert not (v & ~prev).any(), f"{t} has pixels not vacant at the previous threshold"
        prev = v


@pytest.mark.skipif(not _HAS_MASKS, reason="masks not generated")
def test_model_only_selection_reproduces_model_only_exactly():
    rng = np.random.default_rng(0)
    thresholds = THRESHOLDS
    kw = (comp.PRODUCT_BASE, comp.PRODUCT_OUTSIDE, comp.PRODUCT_NV)
    # Threshold-outer: the server's mask cache holds 8 thresholds
    cases = []
    for z, x, y in _tiles_with_pluto():
        esri = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
        level = comp.get_model_level_tile(z, x, y)
        nonvacant = comp.apply_color_ops_fast(esri, **comp.PRODUCT_NV)
        cases.append(((z, x, y), esri, level, nonvacant))
    for i, t in enumerate(thresholds):
        for (z, x, y), esri, level, nonvacant in cases:
            both = comp.composite_tile_u8(esri, z, x, y, t, "both", *kw)
            model = comp.composite_tile_u8(esri, z, x, y, t, "model", *kw)
            if level is None:
                assert np.array_equal(both, model), f"{z}/{x}/{y} {t}: no PLUTO but tiles differ"
            else:
                got = comp.select_model_only(both, nonvacant, level, i)
                assert np.array_equal(got, model), f"{z}/{x}/{y} {t}: selected tile != model-only"
    assert any(level is not None for _, _, level, _ in cases)
    assert any(level is None for _, _, level, _ in cases)


# ── PMTiles archive route (/api/pmtiles) ──────────────

@pytest.fixture
def bucket(monkeypatch):
    """Fake private bucket holding pmtiles/both/t0298.pmtiles (bytes 0..255 repeated)."""
    archive = bytes(range(256)) * 4
    seen = []

    async def fake_get(url, headers):
        seen.append((url, headers))
        if not url.endswith("/pmtiles/both/t0298.pmtiles"):
            return httpx.Response(404)
        start, end = map(int, headers["Range"].removeprefix("bytes=").split("-"))
        end = min(end, len(archive) - 1)
        return httpx.Response(206, content=archive[start:end + 1], headers={
            "content-range": f"bytes {start}-{end}/{len(archive)}", "etag": '"e"'})

    async def fake_token():
        return "tok"

    monkeypatch.setattr(app_mod, "TILE_STORE_BUCKET", "bucket")
    monkeypatch.setattr(app_mod._gcs_http, "get", fake_get)
    monkeypatch.setattr(app_mod, "_gcs_token", fake_token)
    client = TestClient(create_app())
    client.seen = seen
    return client


def test_pmtiles_forwards_range_to_private_bucket(bucket):
    r = bucket.get("/api/pmtiles/both/t0298.pmtiles", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206
    assert r.content == bytes(range(10, 20))
    assert r.headers["content-range"] == "bytes 10-19/1024"
    assert r.headers["etag"] == '"e"'
    assert bucket.seen == [("https://storage.googleapis.com/bucket/pmtiles/both/t0298.pmtiles",
                            {"Authorization": "Bearer tok", "Range": "bytes=10-19"})]


@pytest.mark.parametrize("range_header", [None, "bytes=0-", "bytes=5-1", f"bytes=0-{16 * 1024 * 1024}"])
def test_pmtiles_requires_bounded_range(bucket, range_header):
    headers = {"Range": range_header} if range_header else {}
    r = bucket.get("/api/pmtiles/both/t0298.pmtiles", headers=headers)
    assert r.status_code == 416
    assert bucket.seen == []


@pytest.mark.parametrize("name", ["both/missing.pmtiles", "both/..%2Fboth%2Ft0298.pmtiles", "both/t0298.jpg", "..%2F.env"])
def test_pmtiles_only_serves_archives(bucket, name):
    r = bucket.get(f"/api/pmtiles/{name}", headers={"Range": "bytes=0-9"})
    assert r.status_code == 404


def test_pmtiles_needs_bucket(monkeypatch):
    monkeypatch.setattr(app_mod, "TILE_STORE_BUCKET", "")
    r = TestClient(create_app()).get("/api/pmtiles/both/t0298.pmtiles", headers={"Range": "bytes=0-9"})
    assert r.status_code == 503
