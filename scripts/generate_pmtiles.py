#!/usr/bin/env python3
"""Build the PMTiles archives the frontend serves (see "Tile compositing" in CLAUDE.md).

Archives (in --output, default data/pmtiles):
    both/{t}.pmtiles         Model + PLUTO per threshold, packaged from the loose tiles
                             prerender_tiles.py wrote to {input}/product/{t}/
    pluto_nonvacant.pmtiles  Esri + non-vacant treatment, tiles containing PLUTO lots only
    model_levels.pmtiles     per PLUTO pixel, how many thresholds the model calls it vacant
                             (255 = not PLUTO); metadata.thresholds = index order

Model-only = both/{t} with PLUTO pixels where level <= index(t) taken from
pluto_nonvacant (src/lib/tiles.js). PLUTO-only = both/t1000.

pluto_nonvacant and model_levels are threshold-independent and rendered here (resumable
loose tiles in {input}/pluto_nonvacant/ and {input}/model_levels/), then packaged.

Usage:
    uv run scripts/generate_pmtiles.py                          # everything
    uv run scripts/generate_pmtiles.py --archive both -t t0298  # one threshold
    uv run scripts/generate_pmtiles.py --archive pluto_nonvacant --archive model_levels
    uv run scripts/generate_pmtiles.py --package-only           # don't render, just package
"""

import argparse
import asyncio
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pmtiles.tile import TileType, Compression, zxy_to_tileid
from pmtiles.writer import Writer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.compositing import THRESHOLDS
from logger import get_logger
from prerender_tiles import PRODUCT_DIR, fetch_esri_tile, tiles_for_zoom

log = get_logger()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MASKS_DIR = DATA_DIR / "masks"
BOUNDS = json.loads((MASKS_DIR / "bounds.json").read_text())

ARCHIVES = ("both", "pluto_nonvacant", "model_levels")


def collect_tiles(tile_dir, ext=".jpg"):
    """Walk a z/x/y{ext} directory and return (tile_id, path) sorted by tile ID."""
    entries = []
    for z_dir in tile_dir.iterdir():
        if not z_dir.is_dir():
            continue
        z = int(z_dir.name)
        for x_dir in z_dir.iterdir():
            if not x_dir.is_dir():
                continue
            x = int(x_dir.name)
            for tile_file in x_dir.iterdir():
                if tile_file.suffix != ext:
                    continue
                y = int(tile_file.stem)
                tid = zxy_to_tileid(z, x, y)
                entries.append((tid, tile_file))

    entries.sort(key=lambda e: e[0])
    return entries


def build_archive(tile_dir, output_path, tile_type=TileType.JPEG, ext=".jpg",
                  metadata=None):
    """Create a PMTiles archive from a directory of z/x/y{ext} tiles."""
    entries = collect_tiles(tile_dir, ext) if tile_dir.exists() else []
    if not entries:
        log.warning("No tiles found in %s", tile_dir)
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        writer = Writer(f)

        for tid, tile_file in entries:
            writer.write_tile(tid, tile_file.read_bytes())

        header = {
            "tile_type": tile_type,
            "tile_compression": Compression.NONE,
            "min_lon_e7": int(BOUNDS["west"] * 1e7),
            "min_lat_e7": int(BOUNDS["south"] * 1e7),
            "max_lon_e7": int(BOUNDS["east"] * 1e7),
            "max_lat_e7": int(BOUNDS["north"] * 1e7),
            "center_lon_e7": int((BOUNDS["west"] + BOUNDS["east"]) / 2 * 1e7),
            "center_lat_e7": int((BOUNDS["south"] + BOUNDS["north"]) / 2 * 1e7),
            "center_zoom": 14,
        }
        writer.finalize(header, metadata or {
            "name": "Bronx Vacancy Product Tiles",
            "description": "Prerendered satellite + vacancy mask composites",
        })

    size_mb = output_path.stat().st_size / (1024 * 1024)
    log.info("%d tiles → %s (%.1f MB)", len(entries), output_path, size_mb)
    return len(entries)


# ── both/{t}.pmtiles ────────────────────────────────

def package_both(input_dir, output_dir, thresholds=None):
    product_dir = input_dir / PRODUCT_DIR
    thresholds = thresholds or THRESHOLDS
    invalid = [t for t in thresholds if t not in THRESHOLDS]
    if invalid:
        log.error("Unknown thresholds: %s. Available: %s", invalid, THRESHOLDS)
        sys.exit(1)
    missing = [t for t in thresholds if not (product_dir / t).is_dir()]
    if missing:
        log.error("No loose tiles in %s for %s. Run prerender_tiles.py first.", product_dir, missing)
        sys.exit(1)

    log.info("both: %s → %s (%d thresholds)", product_dir, output_dir / "both", len(thresholds))
    for threshold in thresholds:
        log.info("both/%s", threshold)
        build_archive(product_dir / threshold, output_dir / "both" / f"{threshold}.pmtiles")


# ── pluto_nonvacant.pmtiles + model_levels.pmtiles ──

async def render_pluto_layers(input_dir, zoom_min, zoom_max, concurrency, workers):
    """Write loose pluto_nonvacant (.jpg) and model_levels (.png) tiles for every tile
    containing PLUTO pixels. Skips tiles already written."""
    import httpx
    from PIL import Image
    from server.compositing import (
        PRODUCT_NV, apply_color_ops_fast, _load_model_levels, get_model_level_tile,
        tile_bytes_to_uint8, uint8_to_jpeg,
    )

    def level_png(level_tile):
        buf = io.BytesIO()
        Image.fromarray(level_tile, mode="L").save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def nonvacant_jpg(tile_bytes):
        return uint8_to_jpeg(apply_color_ops_fast(tile_bytes_to_uint8(tile_bytes), **PRODUCT_NV))

    nonvacant_root = input_dir / "pluto_nonvacant"
    levels_root = input_dir / "model_levels"
    pool = ThreadPoolExecutor(max_workers=workers)
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(concurrency)
    stats = {"rendered": 0, "no_pluto": 0, "cached": 0, "errors": 0}
    log.info("Loading masks...")
    _load_model_levels()  # load once up front, not concurrently from worker threads
    start = time.time()

    async with httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
    ) as client:

        async def process_tile(z, x, y):
            nv_path = nonvacant_root / str(z) / str(x) / f"{y}.jpg"
            lvl_path = levels_root / str(z) / str(x) / f"{y}.png"
            if nv_path.exists() and lvl_path.exists():
                stats["cached"] += 1
                return

            level_tile = await loop.run_in_executor(pool, get_model_level_tile, z, x, y)
            if level_tile is None:
                stats["no_pluto"] += 1
                return

            async with sem:
                try:
                    tile_bytes = await fetch_esri_tile(client, z, x, y)
                except Exception as e:
                    stats["errors"] += 1
                    log.error("Fetch %d/%d/%d failed: %s", z, x, y, e)
                    return

            jpg = await loop.run_in_executor(pool, nonvacant_jpg, tile_bytes)
            png = await loop.run_in_executor(pool, level_png, level_tile)
            nv_path.parent.mkdir(parents=True, exist_ok=True)
            lvl_path.parent.mkdir(parents=True, exist_ok=True)
            nv_path.write_bytes(jpg)
            # Level last: a tile counts as done only once both files exist
            lvl_path.write_bytes(png)
            stats["rendered"] += 1

            if stats["rendered"] % 500 == 0:
                rate = stats["rendered"] / (time.time() - start)
                log.info("%s — %.1f tiles/s", stats, rate)

        for z in range(zoom_min, zoom_max + 1):
            tiles = tiles_for_zoom(z)
            log.info("z%d: %d candidate tiles", z, len(tiles))
            await asyncio.gather(*(process_tile(z, x, y) for _, x, y in tiles))

    pool.shutdown()
    log.info("Rendered in %.0fs: %s", time.time() - start, stats)
    return stats


def package_pluto_nonvacant(input_dir, output_dir):
    log.info("pluto_nonvacant")
    build_archive(input_dir / "pluto_nonvacant", output_dir / "pluto_nonvacant.pmtiles", metadata={
        "name": "Bronx PLUTO lots, non-vacant treatment",
        "description": "Esri + non-vacant treatment, tiles containing PLUTO lots only",
    })


def package_model_levels(input_dir, output_dir):
    '''
    model levels are PNG for lossless compression. 
    '''
    log.info("model_levels")
    build_archive(input_dir / "model_levels", output_dir / "model_levels.pmtiles",
                  tile_type=TileType.PNG, ext=".png", metadata={
        "name": "Bronx model vacancy levels on PLUTO lots",
        "description": "Per PLUTO pixel: number of thresholds the model calls it vacant; 255 = not PLUTO",
        "thresholds": THRESHOLDS,
    })


def main():
    parser = argparse.ArgumentParser(description="Build the PMTiles archives the frontend serves")
    parser.add_argument("-a", "--archive", action="append", choices=ARCHIVES,
                        help="Archive to build (repeatable; default: all)")
    parser.add_argument("-i", "--input", type=Path, default=DATA_DIR / "tiles",
                        help="Loose tile directory (default: data/tiles)")
    parser.add_argument("-o", "--output", type=Path, default=DATA_DIR / "pmtiles",
                        help="Output directory (default: data/pmtiles)")
    parser.add_argument("-t", "--threshold", action="append",
                        help="both: threshold to package (repeatable; default: all)")
    parser.add_argument("--package-only", action="store_true",
                        help="pluto_nonvacant/model_levels: package existing loose tiles, don't render")
    parser.add_argument("--render-only", action="store_true",
                        help="pluto_nonvacant/model_levels: render loose tiles, don't package")
    parser.add_argument("--zoom", nargs=2, type=int, default=[11, 19], metavar=("MIN", "MAX"),
                        help="Render zoom range (default: 11 19, must match both/)")
    parser.add_argument("-c", "--concurrency", type=int, default=10,
                        help="Max concurrent Esri fetches (default: 10)")
    parser.add_argument("-w", "--workers", type=int, default=8,
                        help="Compositing threads (default: 8)")
    args = parser.parse_args()
    archives = args.archive or list(ARCHIVES)
    start = time.time()

    if "both" in archives and not args.render_only:
        package_both(args.input, args.output, args.threshold)

    pluto = [a for a in archives if a != "both"]
    if pluto:
        if not args.package_only:
            # Both loose sets come from one pass (same tiles, same Esri fetch)
            stats = asyncio.run(render_pluto_layers(args.input, args.zoom[0], args.zoom[1],
                                                    args.concurrency, args.workers))
            if stats["errors"]:
                log.error("%d tiles failed; re-run to retry before packaging.", stats["errors"])
                sys.exit(1)
        if not args.render_only:
            if "pluto_nonvacant" in pluto:
                package_pluto_nonvacant(args.input, args.output)
            if "model_levels" in pluto:
                package_model_levels(args.input, args.output)

    log.info("Done in %.0fs", time.time() - start)


if __name__ == "__main__":
    main()
