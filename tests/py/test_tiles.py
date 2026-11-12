"""Regression tests for product tile serving (prerendered store, vacancy sources, PMTiles)."""

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import server.app as app_mod
from server.app import app, prerendered_tile_path, _get_tile_masks, _tile_to_mercator_bounds

REPO = Path(__file__).resolve().parents[2]
PMTILES_DIR = REPO / "data" / "pmtiles"
SOURCES = ("both", "model", "pluto")


# ── Prerendered tile layout ───────────────────────────

def test_prerendered_paths_are_distinct_per_source():
    paths = {prerendered_tile_path(18, 1, 2, "t0298", s) for s in SOURCES}
    assert len(paths) == len(SOURCES)


def test_both_keeps_original_layout():
    # Existing GCS bucket / data/tiles use this layout; changing it orphans 5GB of tiles
    assert prerendered_tile_path(18, 1, 2, "t0298", "both") == "product/t0298/18/1/2.jpg"


# ── Product tile route ────────────────────────────────

@pytest.fixture
def tile_store(tmp_path, monkeypatch):
    """Local prerendered store with a combined ('both') tile, live compositing stubbed out."""
    both = tmp_path / prerendered_tile_path(18, 1, 2, "t0298", "both")
    both.parent.mkdir(parents=True)
    both.write_bytes(b"PRERENDERED_BOTH")

    monkeypatch.setattr(app_mod, "_gcs_bucket", None)
    monkeypatch.setattr(app_mod, "_tile_store_path", tmp_path)
    monkeypatch.setattr(app_mod, "_product_cache", type(app_mod._product_cache)())

    async def fake_esri(z, x, y):
        return b"esri"

    def fake_composite(tile_bytes, z, x, y, t, src, *args):
        return f"LIVE:{src}:{t}:{z}".encode()

    monkeypatch.setattr(app_mod, "fetch_esri_tile", fake_esri)
    monkeypatch.setattr(app_mod, "_composite_tile_sync", fake_composite)
    return tmp_path


def test_both_served_from_prerendered_store(tile_store):
    r = TestClient(app).get("/api/tile/product/18/1/2.jpg?t=t0298&source=both")
    assert r.status_code == 200
    assert r.content == b"PRERENDERED_BOTH"


@pytest.mark.parametrize("source", ["model", "pluto"])
def test_single_source_never_served_combined_tiles(tile_store, source):
    r = TestClient(app).get(f"/api/tile/product/18/1/2.jpg?t=t0298&source={source}")
    assert r.status_code == 200
    assert r.content == f"LIVE:{source}:t0298:18".encode()


def test_single_source_uses_its_own_prerendered_tiles(tile_store):
    p = tile_store / prerendered_tile_path(18, 1, 2, "t0298", "model")
    p.parent.mkdir(parents=True)
    p.write_bytes(b"PRERENDERED_MODEL")
    r = TestClient(app).get("/api/tile/product/18/1/2.jpg?t=t0298&source=model")
    assert r.content == b"PRERENDERED_MODEL"


def test_z19_composited_live_when_not_prerendered(tile_store):
    # Sources without archives rely on the server for full-resolution z19
    r = TestClient(app).get("/api/tile/product/19/2/4.jpg?t=t0298&source=both")
    assert r.status_code == 200
    assert r.content == b"LIVE:both:t0298:19"


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

    monkeypatch.setattr(app_mod, "_load_product_masks", lambda t: {
        "vacant": vacant, "nonvacant": nonvacant, "bounds": bounds, "shape": (4, 4)})
    monkeypatch.setattr(app_mod, "_load_shared_masks", lambda: {"pluto_vacant": pluto})
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
    shared = app_mod._load_shared_masks()
    assert not app_mod._load_product_masks("t1000")["vacant"].any()
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
        assert meta["thresholds"] == app_mod.mask_thresholds()


# ── Model-only from both + pluto_nonvacant + model_levels ─

_HAS_MASKS = (MASKS_DIR / "t1000" / "vacant.png").exists()
_CIRC = 40075016.686


def _tiles_with_pluto(zooms=(13, 16, 19), per_zoom=4):
    """A few real tiles containing PLUTO pixels, plus their east neighbors (mixed)."""
    shared = app_mod._load_shared_masks()
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
    for t in app_mod.mask_thresholds():
        v = app_mod._load_product_masks(t)["vacant"]
        if prev is not None:
            assert not (v & ~prev).any(), f"{t} has pixels not vacant at the previous threshold"
        prev = v


@pytest.mark.skipif(not _HAS_MASKS, reason="masks not generated")
def test_model_only_selection_reproduces_model_only_exactly():
    rng = np.random.default_rng(0)
    thresholds = app_mod.mask_thresholds()
    kw = (app_mod.PRODUCT_BASE, app_mod.PRODUCT_OUTSIDE, app_mod.PRODUCT_NV)
    # Threshold-outer: the server's mask cache holds 8 thresholds
    cases = []
    for z, x, y in _tiles_with_pluto():
        esri = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
        level = app_mod.get_model_level_tile(z, x, y)
        nonvacant = app_mod.apply_color_ops_fast(esri, **app_mod.PRODUCT_NV)
        cases.append(((z, x, y), esri, level, nonvacant))
    for i, t in enumerate(thresholds):
        for (z, x, y), esri, level, nonvacant in cases:
            both = app_mod.composite_tile_u8(esri, z, x, y, t, "both", *kw)
            model = app_mod.composite_tile_u8(esri, z, x, y, t, "model", *kw)
            if level is None:
                assert np.array_equal(both, model), f"{z}/{x}/{y} {t}: no PLUTO but tiles differ"
            else:
                got = app_mod.select_model_only(both, nonvacant, level, i)
                assert np.array_equal(got, model), f"{z}/{x}/{y} {t}: selected tile != model-only"
    assert any(level is not None for _, _, level, _ in cases)
    assert any(level is None for _, _, level, _ in cases)
