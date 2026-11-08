"""Pre-render product tiles for all thresholds and zoom levels.

Fetches Esri basemap tiles, composites them with vacancy masks using the
production color treatments, and writes JPEG tiles to an output directory
structured as: {out}/product/{threshold}/{z}/{x}/{y}.jpg (source=both)
or {out}/product-{source}/{threshold}/{z}/{x}/{y}.jpg (source=model|pluto)

Usage:
    uv run scripts/prerender_tiles.py                # all thresholds, zooms 11-19
    uv run scripts/prerender_tiles.py -t t0298       # single threshold
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
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.app import (
    _get_tile_masks,
    prerendered_tile_dir,
    prerendered_tile_path,
    _load_product_masks,
    _load_shared_masks,
    apply_color_ops_fast,
    tile_bytes_to_uint8,
    uint8_to_jpeg,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MASKS_DIR = DATA_DIR / "masks"

ESRI_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

BOUNDS = json.loads((MASKS_DIR / "bounds.json").read_text())
TREATMENT = json.loads((DATA_DIR / "product_treatment.json").read_text())
BASE_KWARGS = TREATMENT["base"]
OUTSIDE_KWARGS = TREATMENT.get("outside", {})
NV_KWARGS = TREATMENT["nonvacant"]


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


def composite_tile(tile_bytes, z, x, y, threshold, source="both"):
    """Composite a single tile — same logic as server product_tile endpoint."""
    tile_u8 = tile_bytes_to_uint8(tile_bytes)
    vacant_mask, nonvacant_mask = _get_tile_masks(z, x, y, threshold, source=source)

    if vacant_mask is None:
        return uint8_to_jpeg(apply_color_ops_fast(tile_u8, **OUTSIDE_KWARGS))

    base_out = apply_color_ops_fast(tile_u8, **BASE_KWARGS)
    nv_out = apply_color_ops_fast(tile_u8, **NV_KWARGS)

    result = base_out
    result[nonvacant_mask] = nv_out[nonvacant_mask]

    boundary = vacant_mask | nonvacant_mask
    outside_pixels = ~boundary
    if outside_pixels.any():
        outside_out = apply_color_ops_fast(tile_u8, **OUTSIDE_KWARGS)
        result[outside_pixels] = outside_out[outside_pixels]

    return uint8_to_jpeg(result)


async def prerender(out_dir, thresholds, zoom_min, zoom_max, concurrency, workers, source, dry_run):
    all_tiles = []
    for z in range(zoom_min, zoom_max + 1):
        all_tiles.extend(tiles_for_zoom(z))

    total = len(all_tiles) * len(thresholds)
    print(f"Thresholds: {len(thresholds)}, Zoom: {zoom_min}-{zoom_max}")
    print(f"Tiles per threshold: {len(all_tiles)}, Total tiles: {total}")

    if dry_run:
        for z in range(zoom_min, zoom_max + 1):
            zt = tiles_for_zoom(z)
            print(f"  z{z}: {len(zt)} tiles")
        return

    out_path = Path(out_dir)
    sem = asyncio.Semaphore(concurrency)
    done = 0
    skipped = 0
    errors = 0
    start = time.time()

    # Compositing is numpy/PIL work that releases the GIL, so threads parallelize it
    pool = ThreadPoolExecutor(max_workers=workers)
    loop = asyncio.get_running_loop()

    # Masks are LRU-cached server-side; compositing more thresholds per tile than the
    # cache holds would re-decode a full mask PNG on almost every tile.
    batch_size = _load_product_masks.cache_info().maxsize or len(thresholds)
    batches = [thresholds[i:i + batch_size] for i in range(0, len(thresholds), batch_size)]

    async with httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
    ) as client:

        async def process_tile(z, x, y, batch):
            """Fetch the Esri tile once and composite every threshold in the batch still missing."""
            nonlocal done, skipped, errors
            paths = {t: out_path / prerendered_tile_path(z, x, y, t, source) for t in batch}
            missing = [t for t, p in paths.items() if not p.exists()]
            skipped += len(batch) - len(missing)
            done += len(batch) - len(missing)
            if not missing:
                return

            async with sem:
                try:
                    tile_bytes = await fetch_esri_tile(client, z, x, y)
                except Exception as e:
                    errors += len(missing)
                    done += len(missing)
                    print(f"  ERROR fetch {z}/{x}/{y}: {e}")
                    return

            for threshold in missing:
                try:
                    jpg = await loop.run_in_executor(
                        pool, composite_tile, tile_bytes, z, x, y, threshold, source)
                    paths[threshold].parent.mkdir(parents=True, exist_ok=True)
                    paths[threshold].write_bytes(jpg)
                except Exception as e:
                    errors += 1
                    print(f"  ERROR {z}/{x}/{y} ({threshold}): {e}")
                done += 1

                if done % 1000 == 0:
                    elapsed = time.time() - start
                    rate = (done - skipped) / elapsed if elapsed > 0 else 0
                    eta = (total - done) / rate if rate > 0 else 0
                    print(f"  {done}/{total} ({skipped} cached, {errors} errors) "
                          f"— {rate:.1f} tiles/s, ETA {eta/60:.0f}m", flush=True)

        for batch in batches:
            print(f"Batch: {', '.join(batch)}", flush=True)
            for threshold in batch:
                _load_product_masks(threshold)
            await asyncio.gather(*(process_tile(z, x, y, batch) for z, x, y in all_tiles))

    pool.shutdown()

    elapsed = time.time() - start
    print(f"\nDone: {done} tiles in {elapsed:.0f}s ({skipped} cached, {errors} errors)")
    print(f"Output: {out_path / prerendered_tile_dir('*', source)}")


def main():
    parser = argparse.ArgumentParser(description="Pre-render product tiles")
    parser.add_argument("-o", "--out", default=str(DATA_DIR / "tiles"),
                        help="Output directory (default: data/tiles)")
    parser.add_argument("-t", "--threshold", action="append",
                        help="Threshold to render (repeatable; default: all)")
    parser.add_argument("--zoom", nargs=2, type=int, default=[11, 19],
                        metavar=("MIN", "MAX"), help="Zoom range (default: 11 19)")
    parser.add_argument("-c", "--concurrency", type=int, default=10,
                        help="Max concurrent Esri fetches (default: 10)")
    parser.add_argument("-w", "--workers", type=int, default=os.cpu_count(),
                        help="Compositing threads (default: CPU count)")
    parser.add_argument("--source", default="both", choices=["model", "pluto", "both"],
                        help="Vacancy source (default: both)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count tiles without fetching")
    args = parser.parse_args()

    all_thresholds = sorted(
        d.name for d in MASKS_DIR.iterdir()
        if d.is_dir() and d.name.startswith("t")
    )
    thresholds = args.threshold or all_thresholds

    invalid = [t for t in thresholds if t not in all_thresholds]
    if invalid:
        print(f"Unknown thresholds: {invalid}")
        print(f"Available: {all_thresholds}")
        sys.exit(1)

    asyncio.run(prerender(
        args.out, thresholds, args.zoom[0], args.zoom[1],
        args.concurrency, args.workers, args.source, args.dry_run,
    ))


if __name__ == "__main__":
    main()
