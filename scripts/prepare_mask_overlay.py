#!/usr/bin/env python3
"""Prepare the vacant-lot mask for the browser playground.

Reads the (already-thresholded) binary mask TIF from config, reprojects +
downsamples it to Web Mercator, burns out road rights-of-way (from the
repo's data/roads.geojson) so roads never render as vacant, and writes a
single RGBA PNG whose alpha channel is the mask (opaque where predicted
vacant, transparent elsewhere) plus a JSON sidecar with its WGS84 bounds
for use as a Leaflet ImageOverlay.

Source pixel semantics (per the model pipeline, not re-derived here):
  0         -> not vacant   -> transparent
  1         -> vacant       -> opaque (unless it falls on a road)
  255 / NoData -> transparent

This script only reads the source TIF; it never modifies it.
"""

import json
from pathlib import Path

import numpy as np
import rasterio
import yaml
from PIL import Image
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.enums import Resampling
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.local.yaml"
if not _CONFIG_PATH.exists():
    raise FileNotFoundError(
        f"Config not found: {_CONFIG_PATH}\n"
        "Copy config.template.yaml to config.local.yaml and fill in your paths."
    )
with _CONFIG_PATH.open() as _f:
    _cfg = yaml.safe_load(_f)

SRC_TIF = Path(_cfg["data"]["vacant_mask_tif"])
OUT_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_PNG = OUT_DIR / "mask_overlay.png"
OUT_JSON = OUT_DIR / "mask_overlay.json"

# Project-local asset (checked into data/), not a machine-specific path,
# so it's referenced directly rather than through config.local.yaml.
ROADS_GEOJSON = Path(__file__).resolve().parent.parent / "data" / "roads.geojson"
ROADS_SRC_CRS = "EPSG:4269"  # roads.geojson's declared CRS (NAD83)
ROAD_BUFFER_M = 8  # half-width, meters; approximates ROW for a typical local street

DST_CRS = "EPSG:3857"
MAX_DIM = 6000  # longest output side, in pixels


def load_road_mask(dst_shape, dst_transform, dst_bounds_3857):
    """Rasterize buffered road centerlines into a boolean mask on the dst grid."""
    if not ROADS_GEOJSON.exists():
        print(f"No roads file at {ROADS_GEOJSON}, skipping road mask-out.")
        return np.zeros(dst_shape, dtype=bool)

    with ROADS_GEOJSON.open() as f:
        fc = json.load(f)

    transformer = Transformer.from_crs(ROADS_SRC_CRS, DST_CRS, always_xy=True)
    minx, miny, maxx, maxy = dst_bounds_3857

    shapes = []
    for feat in fc["features"]:
        proj_geom = shapely_transform(transformer.transform, shape(feat["geometry"]))
        gminx, gminy, gmaxx, gmaxy = proj_geom.bounds
        if gmaxx < minx or gminx > maxx or gmaxy < miny or gminy > maxy:
            continue  # outside the mask extent
        shapes.append(proj_geom.buffer(ROAD_BUFFER_M))

    print(f"Rasterizing {len(shapes)} road buffers intersecting the mask extent...")
    if not shapes:
        return np.zeros(dst_shape, dtype=bool)

    road_mask = rasterize(
        shapes, out_shape=dst_shape, transform=dst_transform,
        fill=0, default_value=1, dtype="uint8",
    )
    return road_mask.astype(bool)


def main():
    if not SRC_TIF.exists():
        raise FileNotFoundError(f"vacant_mask_tif not found: {SRC_TIF}")

    with rasterio.open(SRC_TIF) as src:
        print(f"Source: {src.width}x{src.height}, crs={src.crs}")

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
        dst = np.zeros((dst_h, dst_w), dtype=np.uint8)
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=DST_CRS,
            resampling=Resampling.max,  # keep small vacant lots from vanishing when downsampled
        )

        dst_bounds_3857 = rasterio.transform.array_bounds(dst_h, dst_w, dst_transform)
        west, south, east, north = transform_bounds(DST_CRS, "EPSG:4326", *dst_bounds_3857)

    vacant = dst == 1  # only exact value 1 is vacant; 0/255/anything else -> transparent

    road_mask = load_road_mask((dst_h, dst_w), dst_transform, dst_bounds_3857)
    on_road = vacant & road_mask
    print(f"Vacant pixels on a road (masked out): {int(on_road.sum())}")
    vacant &= ~road_mask

    rgba = np.zeros((dst_h, dst_w, 4), dtype=np.uint8)
    rgba[vacant] = [255, 255, 255, 255]  # white; the playground tints this client-side

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(OUT_PNG)
    OUT_JSON.write_text(json.dumps({
        "west": west, "south": south, "east": east, "north": north,
    }, indent=2) + "\n")

    print(f"Vacant pixels: {int(vacant.sum())} / {vacant.size}")
    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
