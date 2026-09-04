#!/usr/bin/env python3
"""Prepare the vacant/non-vacant masks for the browser playground.

Reads the (already-thresholded) binary mask TIF from config, reprojects +
downsamples it to Web Mercator, burns out road rights-of-way (from the
repo's data/roads.geojson) so roads never render as vacant, and writes two
RGBA PNGs whose alpha channels are the vacant and non-vacant masks (opaque
where they apply, transparent elsewhere), plus a shared JSON sidecar with
their WGS84 bounds for use as Leaflet ImageOverlays.

Source pixel semantics (per the model pipeline, not re-derived here):
  0 -> not vacant   -> non-vacant candidate
  1 -> vacant       -> vacant candidate

The source raster has no NoData — it's a plain rectangle of 0/1 values
covering the whole model grid, including water and slivers of neighboring
boroughs (the model was never geographically restricted to the Bronx).
So neither pixel value alone tells you whether a pixel is real Bronx land;
both masks are further restricted to data/bronx_boundary.geojson (Bronx
County, from Census TIGERweb — see that file's provenance note) the same
way roads are punched out of the vacant mask: rasterize the boundary onto
the same grid and require pixels to fall inside it.

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
from shapely.geometry import shape, mapping
from shapely.ops import transform as shapely_transform, unary_union

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
OUT_NONVACANT_PNG = OUT_DIR / "nonvacant_mask_overlay.png"
OUT_JSON = OUT_DIR / "mask_overlay.json"

# Project-local assets (checked into data/), not machine-specific paths,
# so they're referenced directly rather than through config.local.yaml.
ROADS_GEOJSON = Path(__file__).resolve().parent.parent / "data" / "roads.geojson"
ROADS_SRC_CRS = "EPSG:4269"  # roads.geojson's declared CRS (NAD83)
ROAD_BUFFER_M = 8  # half-width, meters; approximates ROW for a typical local street

BRONX_BOUNDARY_GEOJSON = Path(__file__).resolve().parent.parent / "data" / "bronx_boundary.geojson"
BRONX_BOUNDARY_SRC_CRS = "EPSG:4269"  # TIGERweb's declared CRS (NAD83)

BRONX_AREAWATER_GEOJSON = Path(__file__).resolve().parent.parent / "data" / "bronx_areawater.geojson"

DST_CRS = "EPSG:3857"
MAX_DIM = 6000  # longest output side, in pixels


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
    """Rasterize a GeoJSON file's features (reprojected + optionally
    buffered) into a boolean mask on the dst grid."""
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
            continue  # outside the mask extent
        shapes.append(proj_geom.buffer(buffer_m) if buffer_m else proj_geom)

    print(f"Rasterizing {len(shapes)} {label} intersecting the mask extent...")
    if not shapes:
        return np.zeros(dst_shape, dtype=bool)

    mask = rasterize(
        shapes, out_shape=dst_shape, transform=dst_transform,
        fill=0, default_value=1, dtype="uint8",
    )
    return mask.astype(bool)


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

    non_vacant = dst == 0  # candidate non-vacant pixels
    vacant = dst == 1  # candidate vacant pixels

    # The source raster has no NoData: the model predicted 0/1 across the
    # full rectangular grid, including water and slivers of neighboring
    # boroughs — there's nothing in the pixel values themselves that marks
    # "outside the Bronx". Both masks need the boundary punch-out, not
    # just non-vacant.
    land_geom = load_land_boundary()
    transformer = Transformer.from_crs(BRONX_BOUNDARY_SRC_CRS, DST_CRS, always_xy=True)
    land_3857 = shapely_transform(transformer.transform, land_geom)
    roi_mask = rasterize(
        [land_3857], out_shape=(dst_h, dst_w), transform=dst_transform,
        fill=0, default_value=1, dtype="uint8",
    ).astype(bool)
    print(f"Vacant pixels outside the Bronx boundary (excluded): "
          f"{int((vacant & ~roi_mask).sum())}")
    print(f"Non-vacant pixels outside the Bronx boundary (excluded): "
          f"{int((non_vacant & ~roi_mask).sum())}")
    vacant &= roi_mask
    non_vacant &= roi_mask

    road_mask = rasterize_geojson(
        ROADS_GEOJSON, ROADS_SRC_CRS, (dst_h, dst_w), dst_transform, dst_bounds_3857,
        buffer_m=ROAD_BUFFER_M, label="road buffers",
    )
    on_road = vacant & road_mask
    print(f"Vacant pixels on a road (masked out): {int(on_road.sum())}")
    vacant &= ~road_mask

    rgba = np.zeros((dst_h, dst_w, 4), dtype=np.uint8)
    rgba[vacant] = [255, 255, 255, 255]  # white; the playground tints this client-side

    nonvacant_rgba = np.zeros((dst_h, dst_w, 4), dtype=np.uint8)
    nonvacant_rgba[non_vacant] = [255, 255, 255, 255]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(OUT_PNG)
    Image.fromarray(nonvacant_rgba, mode="RGBA").save(OUT_NONVACANT_PNG)
    OUT_JSON.write_text(json.dumps({
        "west": west, "south": south, "east": east, "north": north,
    }, indent=2) + "\n")

    print(f"Vacant pixels: {int(vacant.sum())} / {vacant.size}")
    print(f"Non-vacant pixels: {int(non_vacant.sum())} / {non_vacant.size}")
    print(f"Wrote {OUT_PNG}")
    print(f"Wrote {OUT_NONVACANT_PNG}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
