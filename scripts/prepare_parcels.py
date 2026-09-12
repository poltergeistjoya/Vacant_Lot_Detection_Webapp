#!/usr/bin/env python3
"""Prepare MapPLUTO parcel GeoJSON for the browser map.

Downloads Bronx MapPLUTO from NYC Open Data, intersects parcel polygons with
the prediction raster, and writes data/parcels.geojson with vacancy category
and ownership fields for each lot that is pluto-vacant or model-vacant.

Output: data/parcels.geojson   (~5K–9K features, ~5–15 MB)

Usage:
    cd scripts && uv run prepare_parcels.py
    cd scripts && uv run prepare_parcels.py --no-model   # skip raster step
"""

import json
import sys
import urllib.request
import urllib.parse
from pathlib import Path

import click
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.warp import calculate_default_transform, reproject
from rasterio.enums import Resampling
from shapely.geometry import shape, mapping
from shapely.ops import transform as shapely_transform

from config import load_config

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA = _REPO_ROOT / "data"
_CACHE = _DATA / "cache"

PLUTO_API = "https://data.cityofnewyork.us/resource/64uk-42ks.geojson"
PLUTO_WHERE = "borocode='2'"
PLUTO_FIELDS = "bbl,address,ownername,ownertype,lotarea,zonedist1,landuse,the_geom"
PLUTO_LIMIT = 200000

DST_CRS = "EPSG:4326"
MAX_DIM = 4000
DEFAULT_THRESHOLD = 0.298


def _fetch_pluto(cache_path: Path) -> dict:
    if cache_path.exists():
        print(f"Using cached MapPLUTO: {cache_path}")
        with cache_path.open() as f:
            return json.load(f)

    print("Downloading Bronx MapPLUTO from NYC Open Data…")
    params = urllib.parse.urlencode({
        "$where": PLUTO_WHERE,
        "$select": PLUTO_FIELDS,
        "$limit": PLUTO_LIMIT,
    })
    url = f"{PLUTO_API}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"WARNING: MapPLUTO download failed ({exc}).\n"
              "Parcel layer will be unavailable. Check network and retry.", file=sys.stderr)
        sys.exit(1)

    _CACHE.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w") as f:
        json.dump(data, f)
    print(f"Cached {len(data.get('features', []))} features → {cache_path}")
    return data


def _load_prediction_grid(prediction_tif: Path):
    """Reproject probability raster to EPSG:4326, downsample to MAX_DIM."""
    print(f"Loading prediction TIF: {prediction_tif}")
    with rasterio.open(prediction_tif) as src:
        full_w, full_h = calculate_default_transform(
            src.crs, DST_CRS, src.width, src.height, *src.bounds
        )[1:]
        scale = min(1.0, MAX_DIM / max(full_w, full_h))
        dst_w = max(1, round(full_w * scale))
        dst_h = max(1, round(full_h * scale))

        dst_transform, _, _ = calculate_default_transform(
            src.crs, DST_CRS, src.width, src.height, *src.bounds,
            dst_width=dst_w, dst_height=dst_h,
        )

        print(f"Reprojecting to {DST_CRS} at {dst_w}×{dst_h}…")
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

    is_vacant = prob > DEFAULT_THRESHOLD
    return is_vacant, dst_transform, dst_h, dst_w


def _find_model_vacant_bbls(features, is_vacant, dst_transform, dst_h, dst_w):
    """Return set of BBLs whose polygons overlap at least one vacant pixel."""
    print(f"Rasterizing {len(features)} parcel polygons onto prediction grid…")

    bbl_list = []
    burn_shapes = []
    for i, feat in enumerate(features):
        bbl = feat["properties"].get("bbl")
        geom = shape(feat["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        bbl_list.append(bbl)
        burn_shapes.append((mapping(geom), i + 1))  # 1-indexed burn value

    if not burn_shapes:
        return set()

    burn = rasterize(
        burn_shapes,
        out_shape=(dst_h, dst_w),
        transform=dst_transform,
        fill=0,
        dtype="int32",
    )

    vacant_indices = np.unique(burn[is_vacant])
    vacant_indices = vacant_indices[vacant_indices > 0]
    return {bbl_list[i - 1] for i in vacant_indices}


def _classify(pluto_vacant: bool, model_vacant: bool) -> str:
    if pluto_vacant and model_vacant:
        return "both"
    if model_vacant:
        return "model_only"
    return "pluto_only"


@click.command()
@click.option("--no-model", "skip_model", is_flag=True,
              help="Skip raster intersection; only output PLUTO-recorded vacant lots.")
@click.option("--force-download", is_flag=True,
              help="Re-download MapPLUTO even if cache exists.")
def main(skip_model, force_download):
    """Produce data/parcels.geojson from MapPLUTO + prediction raster."""

    cache_path = _CACHE / "bronx_mappluto.geojson"
    if force_download and cache_path.exists():
        cache_path.unlink()

    pluto = _fetch_pluto(cache_path)
    features = pluto.get("features", [])
    print(f"Loaded {len(features)} Bronx parcels from MapPLUTO.")

    # Identify PLUTO-recorded vacant lots (LandUse == "11")
    pluto_vacant_bbls = {
        f["properties"].get("bbl")
        for f in features
        if f["properties"].get("landuse") == "11"
    }
    print(f"  {len(pluto_vacant_bbls)} parcels recorded as vacant (LandUse=11).")

    # Raster intersection
    if not skip_model:
        try:
            cfg = load_config()
            pred_tif = Path(cfg["data"]["prediction_tif"])
            if not pred_tif.exists():
                raise FileNotFoundError(pred_tif)
            is_vacant, dst_transform, dst_h, dst_w = _load_prediction_grid(pred_tif)
            model_vacant_bbls = _find_model_vacant_bbls(
                features, is_vacant, dst_transform, dst_h, dst_w
            )
            print(f"  {len(model_vacant_bbls)} parcels overlap model-predicted vacant pixels.")
        except Exception as exc:
            print(f"WARNING: Raster step skipped ({exc}). "
                  "Falling back to PLUTO-only output.", file=sys.stderr)
            model_vacant_bbls = set()
    else:
        model_vacant_bbls = set()

    # Filter to parcels that are vacant by either criterion
    out_features = []
    for feat in features:
        props = feat["properties"]
        bbl = props.get("bbl")
        is_pluto = bbl in pluto_vacant_bbls
        is_model = bbl in model_vacant_bbls
        if not (is_pluto or is_model):
            continue

        geom = shape(feat["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        geom = geom.simplify(0.00001, preserve_topology=True)

        out_features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": {
                "bbl": bbl,
                "address": props.get("address", ""),
                "owner_name": props.get("ownername", ""),
                "owner_type": props.get("ownertype", ""),
                "lot_area": props.get("lotarea"),
                "zoning": props.get("zonedist1", ""),
                "land_use": props.get("landuse", ""),
                "vacancy_category": _classify(is_pluto, is_model),
                "pluto_vacant": is_pluto,
                "model_vacant": is_model,
            },
        })

    out_path = _DATA / "parcels.geojson"
    out_fc = {"type": "FeatureCollection", "features": out_features}
    out_path.write_text(json.dumps(out_fc))
    size_mb = out_path.stat().st_size / 1e6
    print(f"\nWrote {len(out_features)} parcels → {out_path} ({size_mb:.1f} MB)")
    cats = {}
    for f in out_features:
        c = f["properties"]["vacancy_category"]
        cats[c] = cats.get(c, 0) + 1
    for cat, n in sorted(cats.items()):
        print(f"  {cat}: {n}")


if __name__ == "__main__":
    main()
