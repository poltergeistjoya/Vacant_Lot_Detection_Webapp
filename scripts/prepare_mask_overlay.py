#!/usr/bin/env python3
"""Prepare vacant masks for the browser map at one or more thresholds.

Reads the raw prediction probability TIF, reprojects + downsamples to
Web Mercator, computes a shared boundary mask (Bronx land minus water),
and for each requested threshold produces a vacant mask PNG with roads
burned out.

Output structure:
  data/masks/
    boundary.png        — shared Bronx-land mask (RGBA, alpha=255 inside)
    bounds.json         — WGS84 geo bounds for all masks
    t0298/vacant.png    — per-threshold vacant mask
    ...

The server derives non-vacant at load time as boundary & ~vacant.
"""

import json
import sys
from pathlib import Path

import click
import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.enums import Resampling
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform, unary_union

from config import load_config

_cfg = load_config()

PREDICTION_TIF = Path(_cfg["data"]["prediction_tif"])

_REPO_DATA = Path(__file__).resolve().parent.parent / "data"
OUT_DIR = _REPO_DATA / "masks"

ROADS_GEOJSON = _REPO_DATA / "roads.geojson"
ROADS_SRC_CRS = "EPSG:4269"
ROAD_BUFFER_M = 8

BRONX_BOUNDARY_GEOJSON = _REPO_DATA / "bronx_boundary.geojson"
BRONX_BOUNDARY_SRC_CRS = "EPSG:4269"

BRONX_AREAWATER_GEOJSON = _REPO_DATA / "bronx_areawater.geojson"

DST_CRS = "EPSG:3857"
MAX_DIM = 6000


def t_str(t):
    return f"t{round(t * 1000):04d}"


def load_land_boundary():
    """Load the Bronx county boundary with water bodies subtracted."""
    with BRONX_BOUNDARY_GEOJSON.open() as f:
        boundary_geom = shape(json.load(f)["features"][0]["geometry"])

    if not BRONX_AREAWATER_GEOJSON.exists():
        print("No areawater file found, using raw county boundary (includes water).")
        return boundary_geom

    with BRONX_AREAWATER_GEOJSON.open() as f:
        water_fc = json.load(f)
    water_geoms = [shape(feat["geometry"]) for feat in water_fc["features"]]
    water_union = unary_union(water_geoms)

    land = boundary_geom.difference(water_union)
    pct = (boundary_geom.area - land.area) / boundary_geom.area * 100
    print(f"Subtracted water from boundary ({pct:.1f}% of county area).")
    return land


def rasterize_geojson(path, src_crs, dst_shape, dst_transform, dst_bounds_3857,
                       buffer_m=0, label="features"):
    """Rasterize a GeoJSON file onto the destination grid as a boolean mask."""
    if not path.exists():
        print(f"No {label} file at {path}, skipping.")
        return np.zeros(dst_shape, dtype=bool)

    with path.open() as f:
        fc = json.load(f)

    transformer = Transformer.from_crs(src_crs, DST_CRS, always_xy=True)
    minx, miny, maxx, maxy = dst_bounds_3857

    shapes = []
    for feat in fc["features"]:
        proj_geom = shapely_transform(transformer.transform, shape(feat["geometry"]))
        gminx, gminy, gmaxx, gmaxy = proj_geom.bounds
        if gmaxx < minx or gminx > maxx or gmaxy < miny or gminy > maxy:
            continue
        shapes.append(proj_geom.buffer(buffer_m) if buffer_m else proj_geom)

    print(f"Rasterizing {len(shapes)} {label} intersecting the mask extent...")
    if not shapes:
        return np.zeros(dst_shape, dtype=bool)

    mask = rasterize(
        shapes, out_shape=dst_shape, transform=dst_transform,
        fill=0, default_value=1, dtype="uint8",
    )
    return mask.astype(bool)


def save_mask_png(mask_bool, path):
    """Save a boolean mask as an RGBA PNG (white, alpha from mask)."""
    h, w = mask_bool.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[mask_bool] = [255, 255, 255, 255]
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path)


@click.command()
@click.option("--all", "all_thresholds", is_flag=True,
              help="Generate masks for all checkpoints in config.")
@click.option("--threshold", "-t", type=float, multiple=True,
              help="Generate mask for a specific threshold (repeatable).")
def main(all_thresholds, threshold):
    """Generate vacant masks from the prediction probability TIF."""
    t_cfg = _cfg["thresholds"]

    if all_thresholds:
        thresholds = t_cfg["evaluation_thresholds"]
    elif threshold:
        thresholds = list(threshold)
    else:
        thresholds = [t_cfg["default"]]

    if not PREDICTION_TIF.exists():
        raise FileNotFoundError(f"prediction_tif not found: {PREDICTION_TIF}")

    # --- Reproject probability raster once ---
    with rasterio.open(PREDICTION_TIF) as src:
        print(f"Source: {src.width}x{src.height}, crs={src.crs}, dtype={src.dtypes[0]}")

        full_w, full_h = calculate_default_transform(
            src.crs, DST_CRS, src.width, src.height, *src.bounds
        )[1:]
        scale = min(1.0, MAX_DIM / max(full_w, full_h))
        dst_w, dst_h = max(1, round(full_w * scale)), max(1, round(full_h * scale))

        dst_transform, _, _ = calculate_default_transform(
            src.crs, DST_CRS, src.width, src.height, *src.bounds,
            dst_width=dst_w, dst_height=dst_h,
        )

        print(f"Reprojecting to {DST_CRS} at {dst_w}x{dst_h}...")
        prob = np.zeros((dst_h, dst_w), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=prob,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=DST_CRS,
            resampling=Resampling.bilinear,
        )

        dst_bounds_3857 = rasterio.transform.array_bounds(dst_h, dst_w, dst_transform)
        west, south, east, north = transform_bounds(DST_CRS, "EPSG:4326", *dst_bounds_3857)

    # --- Shared masks (computed once) ---
    land_geom = load_land_boundary()
    transformer = Transformer.from_crs(BRONX_BOUNDARY_SRC_CRS, DST_CRS, always_xy=True)
    land_3857 = shapely_transform(transformer.transform, land_geom)
    boundary_mask = rasterize(
        [land_3857], out_shape=(dst_h, dst_w), transform=dst_transform,
        fill=0, default_value=1, dtype="uint8",
    ).astype(bool)

    road_mask = rasterize_geojson(
        ROADS_GEOJSON, ROADS_SRC_CRS, (dst_h, dst_w), dst_transform, dst_bounds_3857,
        buffer_m=ROAD_BUFFER_M, label="road buffers",
    )

    # --- Write shared outputs ---
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    save_mask_png(boundary_mask, OUT_DIR / "boundary.png")
    print(f"Wrote {OUT_DIR / 'boundary.png'} ({int(boundary_mask.sum())} land pixels)")

    bounds_path = OUT_DIR / "bounds.json"
    bounds_path.write_text(json.dumps({
        "west": west, "south": south, "east": east, "north": north,
    }, indent=2) + "\n")
    print(f"Wrote {bounds_path}")

    # --- Per-threshold vacant masks ---
    for t in thresholds:
        ts = t_str(t)
        vacant = (prob > t) & boundary_mask & ~road_mask
        out_path = OUT_DIR / ts / "vacant.png"
        save_mask_png(vacant, out_path)
        print(f"  {ts}: {int(vacant.sum())} vacant pixels → {out_path}")

    print(f"\nDone — {len(thresholds)} threshold(s) written to {OUT_DIR}")


if __name__ == "__main__":
    main()
