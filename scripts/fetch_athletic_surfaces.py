#!/usr/bin/env python3
"""Fetch athletic surface polygons from OpenStreetMap for the Bronx.

Queries the Overpass API for leisure=pitch and leisure=track features,
converts them to GeoJSON, and writes data/athletic_surfaces.geojson.

Usage:
    cd scripts && uv run fetch_athletic_surfaces.py
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import click
from shapely.geometry import Polygon, MultiPolygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

from logger import get_logger

log = get_logger()

_DATA = Path(__file__).resolve().parent.parent / "data"
OUT_PATH = _DATA / "athletic_surfaces.geojson"
BRONX_BOUNDARY_GEOJSON = _DATA / "bronx_boundary.geojson"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
BBOX = (40.785, -73.933, 40.917, -73.748)  # south, west, north, east

OVERPASS_QUERY = """
[out:json][timeout:60];
(
  way["leisure"="pitch"]({s},{w},{n},{e});
  relation["leisure"="pitch"]({s},{w},{n},{e});
  way["leisure"="track"]({s},{w},{n},{e});
  relation["leisure"="track"]({s},{w},{n},{e});
);
out geom;
""".strip()

KEEP_TAGS = ("sport", "leisure", "name", "surface")
MAX_RETRIES = 2
RETRY_DELAY_S = 30


def _query_overpass() -> dict:
    query = OVERPASS_QUERY.format(s=BBOX[0], w=BBOX[1], n=BBOX[2], e=BBOX[3])
    data = urllib.parse.urlencode({"data": query}).encode()
    headers = {"User-Agent": "VacantLotDetection/1.0"}
    req = urllib.request.Request(OVERPASS_URL, data=data, headers=headers)

    for attempt in range(MAX_RETRIES):
        try:
            log.info("Querying Overpass API (attempt %d)…", attempt + 1)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            if attempt < MAX_RETRIES - 1:
                log.warning("Overpass request failed (%s), retrying in %ds…", exc, RETRY_DELAY_S)
                time.sleep(RETRY_DELAY_S)
            else:
                raise


def _way_to_polygon(element: dict):
    """Convert a way element (with `out geom` coordinates) to a Shapely Polygon."""
    coords = [(pt["lon"], pt["lat"]) for pt in element.get("geometry", [])]
    if len(coords) < 4:
        return None
    if coords[0] != coords[-1]:
        return None
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = make_valid(poly)
    if poly.is_empty or poly.geom_type not in ("Polygon", "MultiPolygon"):
        return None
    return poly


def _relation_to_polygon(element: dict):
    """Convert a relation element (with `out geom` members) to a Shapely polygon."""
    outers = []
    inners = []
    for member in element.get("members", []):
        if member.get("type") != "way" or "geometry" not in member:
            continue
        coords = [(pt["lon"], pt["lat"]) for pt in member["geometry"]]
        if len(coords) < 4 or coords[0] != coords[-1]:
            continue
        role = member.get("role", "outer")
        if role == "inner":
            inners.append(coords)
        else:
            outers.append(coords)

    if not outers:
        return None

    polys = []
    for ring in outers:
        polys.append(Polygon(ring, [h for h in inners]))

    geom = polys[0] if len(polys) == 1 else MultiPolygon(polys)
    if not geom.is_valid:
        geom = make_valid(geom)
    if geom.is_empty:
        return None
    return geom


def _extract_properties(element: dict) -> dict:
    tags = element.get("tags", {})
    props = {"osm_id": element["id"]}
    for key in KEEP_TAGS:
        if key in tags:
            props[key] = tags[key]
    return props


def _load_bronx_boundary():
    with BRONX_BOUNDARY_GEOJSON.open() as f:
        return shape(json.load(f)["features"][0]["geometry"])


def _build_geojson(overpass_data: dict) -> dict:
    bronx = _load_bronx_boundary()
    log.info("Loaded Bronx boundary for spatial filtering.")

    features = []
    skipped = 0
    outside = 0

    for el in overpass_data.get("elements", []):
        if el["type"] == "way":
            geom = _way_to_polygon(el)
        elif el["type"] == "relation":
            geom = _relation_to_polygon(el)
        else:
            continue

        if geom is None:
            skipped += 1
            continue

        if not geom.intersects(bronx):
            outside += 1
            continue

        features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": _extract_properties(el),
        })

    if skipped:
        log.info("Skipped %d elements (non-polygon or invalid geometry).", skipped)
    if outside:
        log.info("Filtered out %d features outside Bronx boundary.", outside)

    sports = {}
    for f in features:
        sport = f["properties"].get("sport", "unknown")
        sports[sport] = sports.get(sport, 0) + 1

    log.info("Sport breakdown: %s", json.dumps(sports, indent=2))

    return {
        "type": "FeatureCollection",
        "metadata": {
            "source": "OpenStreetMap via Overpass API",
            "query_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "bbox": list(BBOX),
            "license": "ODbL — (c) OpenStreetMap contributors",
        },
        "features": features,
    }


@click.command()
@click.option("--force", is_flag=True, help="Overwrite existing file.")
def main(force):
    """Fetch athletic surface polygons from OpenStreetMap."""
    if OUT_PATH.exists() and not force:
        raise click.ClickException(
            f"{OUT_PATH} already exists. Use --force to overwrite."
        )

    data = _query_overpass()
    log.info("Received %d elements from Overpass.", len(data.get("elements", [])))

    fc = _build_geojson(data)
    log.info("Built %d polygon features.", len(fc["features"]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        json.dump(fc, f)

    size_kb = OUT_PATH.stat().st_size / 1024
    log.info("Wrote %s (%.1f KB, %d features).", OUT_PATH, size_kb, len(fc["features"]))


if __name__ == "__main__":
    main()
