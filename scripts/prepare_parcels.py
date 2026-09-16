#!/usr/bin/env python3
"""Prepare MapPLUTO parcel GeoJSON for the browser map.

Downloads Bronx MapPLUTO from NYC Open Data, intersects parcel polygons with
the prediction raster at every configured threshold, and writes
data/parcels.geojson with per-threshold pixel coverage fractions and ownership
fields for each lot that is pluto-vacant or model-vacant at any threshold.

Output: data/parcels.geojson

Usage:
    cd scripts && uv run prepare_parcels.py
"""

import json
import sys
import urllib.request
import urllib.parse
from pathlib import Path

import click
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import calculate_default_transform, reproject
from rasterio.enums import Resampling
from shapely.geometry import shape, mapping

from config import load_config

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA = _REPO_ROOT / "data"
_CACHE = _DATA / "cache"

ARCGIS_URL = (
    "https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services"
    "/MAPPLUTO/FeatureServer/0/query"
)
ARCGIS_FIELDS = "BBL,Address,OwnerName,OwnerType,LotArea,ZoneDist1,LandUse"
ARCGIS_PAGE_SIZE = 2000

DST_CRS = "EPSG:4326"
MAX_DIM = 4000
COVERAGE_THRESHOLD = 0.20

ARCGIS_SERVICE_URL = (
    "https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services"
    "/MAPPLUTO/FeatureServer/0"
)


def _t_str(t):
    return f"t{round(t * 1000):04d}"


def _fetch_pluto_version() -> str:
    """Query the ArcGIS service metadata for the last edit date."""
    try:
        url = f"{ARCGIS_SERVICE_URL}?f=json"
        with urllib.request.urlopen(url, timeout=15) as resp:
            meta = json.loads(resp.read())
        ts = meta.get("editingInfo", {}).get("dataLastEditDate")
        if ts:
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return "unknown"


def _fetch_pluto(cache_path: Path) -> dict:
    if cache_path.exists():
        print(f"Using cached MapPLUTO: {cache_path}")
        with cache_path.open() as f:
            return json.load(f)

    print("Downloading Bronx MapPLUTO from ArcGIS FeatureServer…")
    all_features = []
    offset = 0
    while True:
        params = urllib.parse.urlencode({
            "where": "BoroCode=2",
            "outFields": ARCGIS_FIELDS,
            "f": "geojson",
            "resultRecordCount": ARCGIS_PAGE_SIZE,
            "resultOffset": offset,
        })
        url = f"{ARCGIS_URL}?{params}"
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            print(f"WARNING: MapPLUTO download failed at offset {offset} ({exc}).\n"
                  "Parcel layer will be unavailable. Check network and retry.",
                  file=sys.stderr)
            sys.exit(1)

        feats = data.get("features", [])
        all_features.extend(feats)
        print(f"  fetched {len(feats)} features (total: {len(all_features)})")
        exceeded = data.get("properties", {}).get("exceededTransferLimit", False)
        if not exceeded or len(feats) < ARCGIS_PAGE_SIZE:
            break
        offset += len(feats)

    fc = {"type": "FeatureCollection", "features": all_features}
    _CACHE.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w") as f:
        json.dump(fc, f)
    print(f"Cached {len(all_features)} features → {cache_path}")
    return fc


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

    return prob, dst_transform, dst_h, dst_w


def _compute_parcel_coverages(features, prob, dst_transform, dst_h, dst_w, thresholds):
    """For each parcel, compute pixel coverage fraction at each threshold."""
    print(f"Rasterizing {len(features)} parcel polygons onto prediction grid…")

    bbl_list = []
    burn_shapes = []
    for i, feat in enumerate(features):
        bbl = feat["properties"].get("BBL")
        geom_raw = feat.get("geometry")
        bbl_list.append(bbl)
        if geom_raw is None:
            continue
        geom = shape(geom_raw)
        if not geom.is_valid:
            geom = geom.buffer(0)
        burn_shapes.append((mapping(geom), i + 1))

    if not burn_shapes:
        return {}

    burn = rasterize(
        burn_shapes,
        out_shape=(dst_h, dst_w),
        transform=dst_transform,
        fill=0,
        dtype="int32",
    )

    total_counts = np.bincount(burn.ravel())
    parcel_ids = np.unique(burn)
    parcel_ids = parcel_ids[parcel_ids > 0]

    bbl_to_pid = {}
    for pid in parcel_ids:
        if total_counts[pid] > 0:
            bbl_to_pid[bbl_list[pid - 1]] = int(pid)

    coverage = {bbl: {} for bbl in bbl_to_pid}
    for t in thresholds:
        is_vacant = prob > t
        vacant_counts = np.bincount(burn[is_vacant].ravel(), minlength=len(total_counts))
        ts = _t_str(t)
        for bbl, pid in bbl_to_pid.items():
            frac = float(vacant_counts[pid] / total_counts[pid])
            coverage[bbl][ts] = round(frac, 4)

    n_any = sum(1 for covs in coverage.values()
                if any(v >= COVERAGE_THRESHOLD for v in covs.values()))
    print(f"  {n_any} parcels meet {COVERAGE_THRESHOLD:.0%} coverage at any threshold "
          f"(of {len(parcel_ids)} with raster overlap).")
    return coverage


@click.command()
@click.option("--force-download", is_flag=True,
              help="Re-download MapPLUTO even if cache exists.")
def main(force_download):
    """Produce data/parcels.geojson from MapPLUTO + prediction raster."""
    cfg = load_config()

    t_cfg = cfg["thresholds"]
    thresholds = t_cfg["evaluation_thresholds"]
    print(f"Using {len(thresholds)} thresholds: {thresholds[0]}–{thresholds[-1]}")

    pred_tif = Path(cfg["data"]["prediction_tif"])
    if not pred_tif.exists():
        raise FileNotFoundError(f"prediction_tif not found: {pred_tif}")

    cache_path = _CACHE / "bronx_mappluto.geojson"
    if force_download and cache_path.exists():
        cache_path.unlink()

    pluto = _fetch_pluto(cache_path)
    features = pluto.get("features", [])
    print(f"Loaded {len(features)} Bronx parcels from MapPLUTO.")

    pluto_vacant_bbls = {
        f["properties"].get("BBL")
        for f in features
        if f["properties"].get("LandUse") == "11"
    }
    print(f"  {len(pluto_vacant_bbls)} parcels recorded as vacant (LandUse=11).")

    prob, dst_transform, dst_h, dst_w = _load_prediction_grid(pred_tif)
    coverage = _compute_parcel_coverages(
        features, prob, dst_transform, dst_h, dst_w, thresholds
    )

    # t=0.0 is degenerate (everything vacant); skip for inclusion
    inclusion_thresholds = [_t_str(t) for t in thresholds if t > 0]

    out_features = []
    counts_by_threshold = {_t_str(t): 0 for t in thresholds}

    for feat in features:
        props = feat["properties"]
        bbl = props.get("BBL")
        is_pluto = bbl in pluto_vacant_bbls
        parcel_cov = coverage.get(bbl, {})
        is_model_any = any(
            parcel_cov.get(ts, 0) >= COVERAGE_THRESHOLD
            for ts in inclusion_thresholds
        )

        if not (is_pluto or is_model_any):
            continue

        geom_raw = feat.get("geometry")
        if geom_raw is None:
            continue
        geom = shape(geom_raw)
        if not geom.is_valid:
            geom = geom.buffer(0)
        geom = geom.simplify(0.00001, preserve_topology=True)

        out_props = {
            "bbl": bbl,
            "address": props.get("Address", ""),
            "owner_name": props.get("OwnerName", ""),
            "owner_type": props.get("OwnerType", ""),
            "lot_area": props.get("LotArea"),
            "zoning": props.get("ZoneDist1", ""),
            "land_use": props.get("LandUse", ""),
            "pluto_vacant": is_pluto,
        }
        for t in thresholds:
            ts = _t_str(t)
            out_props[ts] = parcel_cov.get(ts, 0)

        for t in thresholds:
            ts = _t_str(t)
            if is_pluto or parcel_cov.get(ts, 0) >= COVERAGE_THRESHOLD:
                counts_by_threshold[ts] += 1

        out_features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": out_props,
        })

    pluto_version = _fetch_pluto_version()
    print(f"  MapPLUTO data version: {pluto_version}")

    out_path = _DATA / "parcels.geojson"
    out_fc = {
        "type": "FeatureCollection",
        "metadata": {
            "pluto_version": pluto_version,
            "counts_by_threshold": counts_by_threshold,
            "coverage_threshold": COVERAGE_THRESHOLD,
        },
        "features": out_features,
    }
    out_path.write_text(json.dumps(out_fc))
    size_mb = out_path.stat().st_size / 1e6
    print(f"\nWrote {len(out_features)} parcels → {out_path} ({size_mb:.1f} MB)")

    default_ts = _t_str(t_cfg["default"])
    print(f"\nCounts by threshold (≥{COVERAGE_THRESHOLD:.0%} coverage or PLUTO-vacant):")
    for t in thresholds:
        ts = _t_str(t)
        marker = " ← default" if ts == default_ts else ""
        print(f"  {ts}: {counts_by_threshold[ts]:,}{marker}")


if __name__ == "__main__":
    main()
