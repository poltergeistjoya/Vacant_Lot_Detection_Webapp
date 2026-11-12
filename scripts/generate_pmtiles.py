#!/usr/bin/env python3
"""Package the loose tiles prerender_tiles.py rendered into the PMTiles archives the
frontend serves (see "Tile compositing" in CLAUDE.md). No rendering happens here.

Archives (in --output, default data/pmtiles), from loose tiles in --input:
    both/{t}.pmtiles         Model + PLUTO per threshold      ← product/{t}/
    pluto_nonvacant.pmtiles  non-vacant treatment, PLUTO only ← pluto_nonvacant/
    model_levels.pmtiles     model vacancy levels (PNG)       ← model_levels/;
                             metadata.thresholds = level index order

Model-only = both/{t} with PLUTO pixels where level <= index(t) taken from
pluto_nonvacant (src/lib/tiles.js). PLUTO-only = both/t1000.

Usage:
    uv run scripts/generate_pmtiles.py                          # everything
    uv run scripts/generate_pmtiles.py --archive both -t t0298  # one threshold
    uv run scripts/generate_pmtiles.py --archive pluto_nonvacant --archive model_levels
"""

import argparse
import json
import sys
import time
from pathlib import Path

from pmtiles.tile import TileType, Compression, zxy_to_tileid
from pmtiles.writer import Writer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.compositing import THRESHOLDS
from logger import get_logger
from prerender_tiles import LEVELS_DIR, NONVACANT_DIR, PRODUCT_DIR

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

def _require_loose(tile_dir):
    if not tile_dir.is_dir():
        log.error("No loose tiles in %s. Run prerender_tiles.py first.", tile_dir)
        sys.exit(1)


def package_pluto_nonvacant(input_dir, output_dir):
    log.info("pluto_nonvacant")
    _require_loose(input_dir / NONVACANT_DIR)
    build_archive(input_dir / NONVACANT_DIR, output_dir / "pluto_nonvacant.pmtiles", metadata={
        "name": "Bronx PLUTO lots, non-vacant treatment",
        "description": "Esri + non-vacant treatment, tiles containing PLUTO lots only",
    })


def package_model_levels(input_dir, output_dir):
    '''
    model levels are PNG for lossless compression. 
    '''
    log.info("model_levels")
    _require_loose(input_dir / LEVELS_DIR)
    build_archive(input_dir / LEVELS_DIR, output_dir / "model_levels.pmtiles",
                  tile_type=TileType.PNG, ext=".png", metadata={
        "name": "Bronx model vacancy levels on PLUTO lots",
        "description": "Per PLUTO pixel: number of thresholds the model calls it vacant; 255 = not PLUTO",
        "thresholds": THRESHOLDS,
    })


def main():
    parser = argparse.ArgumentParser(description="Package loose tiles into the PMTiles archives the frontend serves")
    parser.add_argument("-a", "--archive", action="append", choices=ARCHIVES,
                        help="Archive to build (repeatable; default: all)")
    parser.add_argument("-i", "--input", type=Path, default=DATA_DIR / "tiles",
                        help="Loose tile directory (default: data/tiles)")
    parser.add_argument("-o", "--output", type=Path, default=DATA_DIR / "pmtiles",
                        help="Output directory (default: data/pmtiles)")
    parser.add_argument("-t", "--threshold", action="append",
                        help="both: threshold to package (repeatable; default: all)")
    args = parser.parse_args()
    archives = args.archive or list(ARCHIVES)
    start = time.time()

    if "both" in archives:
        package_both(args.input, args.output, args.threshold)
    if "pluto_nonvacant" in archives:
        package_pluto_nonvacant(args.input, args.output)
    if "model_levels" in archives:
        package_model_levels(args.input, args.output)

    log.info("Done in %.0fs", time.time() - start)


if __name__ == "__main__":
    main()
