#!/usr/bin/env python3
"""Enrich athletic surface polygons with model prediction coverage.

Reads data/athletic_surfaces.geojson (from fetch_athletic_surfaces.py),
intersects each polygon with the prediction raster at every configured
threshold, and writes data/athletic_surfaces_enriched.geojson with
per-threshold pixel coverage fractions.

Output: data/athletic_surfaces_enriched.geojson

Usage:
    cd scripts && uv run prepare_athletic_surfaces.py
"""

import json
from pathlib import Path

import click
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import calculate_default_transform, reproject
from rasterio.enums import Resampling
from shapely.geometry import shape, mapping

from config import load_config
from logger import get_logger

log = get_logger()

_DATA = Path(__file__).resolve().parent.parent / "data"
INPUT_PATH = _DATA / "athletic_surfaces.geojson"
OUT_PATH = _DATA / "athletic_surfaces_enriched.geojson"

DST_CRS = "EPSG:4326"
MAX_DIM = 4000
COVERAGE_THRESHOLD = 0.20


def _t_str(t):
    return f"t{round(t * 1000):04d}"


def _load_prediction_grid(prediction_tif: Path):
    log.info("Loading prediction TIF: %s", prediction_tif)
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

        log.info("Reprojecting to %s at %d×%d…", DST_CRS, dst_w, dst_h)
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


def _compute_coverages(features, prob, dst_transform, dst_h, dst_w, thresholds):
    log.info("Rasterizing %d athletic polygons onto prediction grid…", len(features))

    burn_shapes = []
    for i, feat in enumerate(features):
        geom_raw = feat.get("geometry")
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
    feature_ids = np.unique(burn)
    feature_ids = feature_ids[feature_ids > 0]

    idx_to_pid = {}
    for pid in feature_ids:
        if total_counts[pid] > 0:
            idx_to_pid[pid - 1] = int(pid)

    coverage = {idx: {} for idx in idx_to_pid}
    for t in thresholds:
        is_vacant = prob > t
        vacant_counts = np.bincount(burn[is_vacant].ravel(), minlength=len(total_counts))
        ts = _t_str(t)
        for idx, pid in idx_to_pid.items():
            frac = float(vacant_counts[pid] / total_counts[pid])
            coverage[idx][ts] = round(frac, 4)

    n_any = sum(1 for covs in coverage.values()
                if any(v >= COVERAGE_THRESHOLD for v in covs.values()))
    log.info("%d athletic surfaces meet %.0f%% coverage at any threshold.",
             n_any, COVERAGE_THRESHOLD * 100)
    return coverage


@click.command()
def main():
    """Enrich athletic surface polygons with model prediction coverage."""
    cfg = load_config()

    t_cfg = cfg["thresholds"]
    thresholds = t_cfg["evaluation_thresholds"]
    log.info("Using %d thresholds: %s–%s", len(thresholds), thresholds[0], thresholds[-1])

    pred_tif = Path(cfg["data"]["prediction_tif"])
    if not pred_tif.exists():
        raise FileNotFoundError(f"prediction_tif not found: {pred_tif}")

    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"{INPUT_PATH} not found — run fetch_athletic_surfaces.py first."
        )

    with INPUT_PATH.open() as f:
        fc = json.load(f)

    features = fc.get("features", [])
    log.info("Loaded %d athletic surface features.", len(features))

    prob, dst_transform, dst_h, dst_w = _load_prediction_grid(pred_tif)
    coverage = _compute_coverages(
        features, prob, dst_transform, dst_h, dst_w, thresholds
    )

    out_features = []
    counts_by_threshold = {_t_str(t): 0 for t in thresholds}

    for i, feat in enumerate(features):
        geom_raw = feat.get("geometry")
        if geom_raw is None:
            continue

        props = dict(feat.get("properties", {}))
        feat_cov = coverage.get(i, {})

        for t in thresholds:
            ts = _t_str(t)
            props[ts] = feat_cov.get(ts, 0)

        model_vacant = any(
            feat_cov.get(_t_str(t), 0) >= COVERAGE_THRESHOLD
            for t in thresholds if t > 0
        )
        props["model_vacant"] = model_vacant

        for t in thresholds:
            ts = _t_str(t)
            if feat_cov.get(ts, 0) >= COVERAGE_THRESHOLD:
                counts_by_threshold[ts] += 1

        out_features.append({
            "type": "Feature",
            "geometry": geom_raw,
            "properties": props,
        })

    metadata = fc.get("metadata", {})
    metadata["coverage_threshold"] = COVERAGE_THRESHOLD
    metadata["counts_by_threshold"] = counts_by_threshold

    out_fc = {
        "type": "FeatureCollection",
        "metadata": metadata,
        "features": out_features,
    }

    OUT_PATH.write_text(json.dumps(out_fc))
    size_kb = OUT_PATH.stat().st_size / 1024
    log.info("Wrote %d features → %s (%.1f KB)", len(out_features), OUT_PATH, size_kb)

    default_ts = _t_str(t_cfg["default"])
    log.info("False-positive counts (≥%.0f%% coverage):", COVERAGE_THRESHOLD * 100)
    for t in thresholds:
        ts = _t_str(t)
        marker = " ← default" if ts == default_ts else ""
        log.info("  %s: %d%s", ts, counts_by_threshold[ts], marker)


if __name__ == "__main__":
    main()
