"""Render every loose tile the PMTiles archives are built from.

Fetches each Esri basemap tile once, composites it with the vacancy masks using the
production color treatments (server/compositing.py), and writes (under --out):
    product/{threshold}/{z}/{x}/{y}.jpg  Model + PLUTO, per threshold
    pluto_nonvacant/{z}/{x}/{y}.jpg      Esri + non-vacant treatment, tiles with PLUTO lots only
    model_levels/{z}/{x}/{y}.png         per PLUTO pixel, how many thresholds the model calls it
                                         vacant (255 = not PLUTO); PNG so values stay exact
generate_pmtiles.py packages them. Resumable: tiles already written are skipped.

Usage:
    uv run scripts/prerender_tiles.py                # all thresholds, zooms 11-19
    uv run scripts/prerender_tiles.py -t t0298       # Model + PLUTO for one threshold only
    uv run scripts/prerender_tiles.py --zoom 14 18   # zoom range
    uv run scripts/prerender_tiles.py --dry-run      # count tiles without fetching
"""

import argparse
import asyncio
import io
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.compositing import (
    PRODUCT_BASE, PRODUCT_NV, PRODUCT_OUTSIDE, THRESHOLDS, _load_model_levels, _load_product_masks,
    apply_color_ops_fast, composite_tile_u8, get_model_level_tile, tile_bytes_to_uint8, uint8_to_jpeg,
)
from logger import get_logger

log = get_logger()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MASKS_DIR = DATA_DIR / "masks"

ESRI_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

BOUNDS = json.loads((MASKS_DIR / "bounds.json").read_text())

# Loose tile directories under --out (generate_pmtiles.py reads the same names)
PRODUCT_DIR = "product"
NONVACANT_DIR = "pluto_nonvacant"
LEVELS_DIR = "model_levels"


def lon_to_tile_x(lon, z):
    return int((lon + 180) / 360 * (2 ** z))


def lat_to_tile_y(lat, z):
    lat_rad = math.radians(lat)
    return int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * (2 ** z))


def tiles_for_zoom(z):
    """Return all (z, x, y) tiles covering the Bronx at zoom level z."""
    x_min = lon_to_tile_x(BOUNDS["west"], z)
    x_max = lon_to_tile_x(BOUNDS["east"], z)
    y_min = lat_to_tile_y(BOUNDS["north"], z)
    y_max = lat_to_tile_y(BOUNDS["south"], z)
    tiles = []
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            tiles.append((z, x, y))
    return tiles


async def fetch_esri_tile(client, z, x, y, retries=3):
    url = ESRI_URL.format(z=z, y=y, x=x)
    for attempt in range(retries):
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)


def composite_tile(tile_bytes, z, x, y, threshold):
    """Model + PLUTO tile as JPEG."""
    tile_u8 = tile_bytes_to_uint8(tile_bytes)
    return uint8_to_jpeg(composite_tile_u8(
        tile_u8, z, x, y, threshold, "both", PRODUCT_BASE, PRODUCT_OUTSIDE, PRODUCT_NV))


def nonvacant_tile(tile_bytes):
    """Esri tile with the non-vacant treatment as JPEG."""
    return uint8_to_jpeg(apply_color_ops_fast(tile_bytes_to_uint8(tile_bytes), **PRODUCT_NV))


def level_png(level_tile):
    buf = io.BytesIO()
    Image.fromarray(level_tile, mode="L").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


async def prerender(out_dir, thresholds, zoom_min, zoom_max, concurrency, workers, dry_run):
    all_tiles = []
    for z in range(zoom_min, zoom_max + 1):
        all_tiles.extend(tiles_for_zoom(z))

    total = len(all_tiles) * len(thresholds)
    log.info("Thresholds: %d, Zoom: %d-%d", len(thresholds), zoom_min, zoom_max)
    log.info("Tiles per threshold: %d, Total tiles: %d", len(all_tiles), total)

    if dry_run:
        for z in range(zoom_min, zoom_max + 1):
            zt = tiles_for_zoom(z)
            log.info("z%d: %d tiles", z, len(zt))
        return

    out_path = Path(out_dir) / PRODUCT_DIR
    nonvacant_root = Path(out_dir) / NONVACANT_DIR
    levels_root = Path(out_dir) / LEVELS_DIR
    sem = asyncio.Semaphore(concurrency)
    done = 0
    skipped = 0
    errors = 0
    pluto_rendered = 0
    start = time.time()

    # Compositing is numpy/PIL work that releases the GIL, so threads parallelize it
    pool = ThreadPoolExecutor(max_workers=workers)
    loop = asyncio.get_running_loop()

    # Masks are LRU-cached (server/compositing.py); compositing more thresholds per tile than the
    # cache holds would re-decode a full mask PNG on almost every tile.
    batch_size = _load_product_masks.cache_info().maxsize or len(thresholds)
    batches = [thresholds[i:i + batch_size] for i in range(0, len(thresholds), batch_size)]
    log.info("Loading masks...")
    _load_model_levels()  # load once up front, not concurrently from worker threads

    async with httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
    ) as client:

        async def process_tile(z, x, y, batch, with_pluto):
            """Fetch the Esri tile once and write every tile still missing for it: each
            threshold in the batch, plus (with_pluto) the threshold-independent PLUTO tiles."""
            nonlocal done, skipped, errors, pluto_rendered
            paths = {t: out_path / t / str(z) / str(x) / f"{y}.jpg" for t in batch}
            missing = [t for t, p in paths.items() if not p.exists()]
            skipped += len(batch) - len(missing)
            done += len(batch) - len(missing)

            nv_path = nonvacant_root / str(z) / str(x) / f"{y}.jpg"
            lvl_path = levels_root / str(z) / str(x) / f"{y}.png"
            level_tile = None
            if with_pluto and not (nv_path.exists() and lvl_path.exists()):
                # None when the tile has no PLUTO pixels: nothing to write
                level_tile = await loop.run_in_executor(pool, get_model_level_tile, z, x, y)

            if not missing and level_tile is None:
                return

            async with sem:
                try:
                    tile_bytes = await fetch_esri_tile(client, z, x, y)
                except Exception as e:
                    errors += len(missing) + (level_tile is not None)
                    done += len(missing)
                    log.error("Fetch %d/%d/%d failed: %s", z, x, y, e)
                    return

            if level_tile is not None:
                try:
                    jpg = await loop.run_in_executor(pool, nonvacant_tile, tile_bytes)
                    png = await loop.run_in_executor(pool, level_png, level_tile)
                    nv_path.parent.mkdir(parents=True, exist_ok=True)
                    lvl_path.parent.mkdir(parents=True, exist_ok=True)
                    nv_path.write_bytes(jpg)
                    # Level last: a tile counts as done only once both files exist
                    lvl_path.write_bytes(png)
                    pluto_rendered += 1
                except Exception as e:
                    errors += 1
                    log.error("PLUTO tiles %d/%d/%d failed: %s", z, x, y, e)

            for threshold in missing:
                try:
                    jpg = await loop.run_in_executor(
                        pool, composite_tile, tile_bytes, z, x, y, threshold)
                    paths[threshold].parent.mkdir(parents=True, exist_ok=True)
                    paths[threshold].write_bytes(jpg)
                except Exception as e:
                    errors += 1
                    log.error("Composite %d/%d/%d (%s) failed: %s", z, x, y, threshold, e)
                done += 1

                if done % 1000 == 0:
                    elapsed = time.time() - start
                    rate = (done - skipped) / elapsed if elapsed > 0 else 0
                    eta = (total - done) / rate if rate > 0 else 0
                    log.info("%d/%d (%d cached, %d errors) — %.1f tiles/s, ETA %.0fm",
                             done, total, skipped, errors, rate, eta / 60)

        for i, batch in enumerate(batches):
            log.info("Batch: %s", ", ".join(batch))
            for threshold in batch:
                _load_product_masks(threshold)
            # PLUTO tiles don't depend on the threshold: write them with the first batch
            await asyncio.gather(*(process_tile(z, x, y, batch, i == 0) for z, x, y in all_tiles))

    pool.shutdown()

    elapsed = time.time() - start
    log.info("Done in %.0fs: %d Model + PLUTO tiles (%d cached), %d new PLUTO tile pairs, %d errors",
             elapsed, done, skipped, pluto_rendered, errors)
    log.info("Output: %s, %s, %s", out_path, nonvacant_root, levels_root)
    if errors:
        log.error("%d tiles failed; re-run to retry before packaging.", errors)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Render the loose tiles the PMTiles archives are built from")
    parser.add_argument("-o", "--out", default=str(DATA_DIR / "tiles"),
                        help="Output directory (default: data/tiles)")
    parser.add_argument("-t", "--threshold", action="append",
                        help="Model + PLUTO threshold to render (repeatable; default: all)")
    parser.add_argument("--zoom", nargs=2, type=int, default=[11, 19],
                        metavar=("MIN", "MAX"), help="Zoom range (default: 11 19)")
    parser.add_argument("-c", "--concurrency", type=int, default=10,
                        help="Max concurrent Esri fetches (default: 10)")
    parser.add_argument("-w", "--workers", type=int, default=os.cpu_count(),
                        help="Compositing threads (default: CPU count)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count tiles without fetching")
    args = parser.parse_args()

    thresholds = args.threshold or THRESHOLDS

    invalid = [t for t in thresholds if t not in THRESHOLDS]
    if invalid:
        log.error("Unknown thresholds: %s. Available: %s", invalid, THRESHOLDS)
        sys.exit(1)

    asyncio.run(prerender(
        args.out, thresholds, args.zoom[0], args.zoom[1],
        args.concurrency, args.workers, args.dry_run,
    ))


if __name__ == "__main__":
    main()
