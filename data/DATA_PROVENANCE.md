# Data Provenance

Static geographic datasets used by the app. These are downloaded once and
committed — they change infrequently (NYC redraws CD boundaries roughly
once per decade).

## community_districts.geojson

- **Source**: NYC Open Data — "Community Districts"
- **URL**: https://data.cityofnewyork.us/City-Government/Community-Districts/jp9i-3b7y
- **Format**: GeoJSON (exported from Socrata)
- **CRS**: EPSG:4326 (WGS84)
- **Features**: 71 polygons — all five boroughs. Bronx CDs are BoroCD 201–212 plus parks (226–228).
- **Properties**: `BoroCD` (borough×100 + district number), `Shape_Leng`, `Shape_Area`
- **Downloaded**: 2026-09 (unchanged since 2024 redistricting)
- **Size**: ~3.6 MB

## bronx_boundary.geojson

- **Source**: US Census TIGER/Line — Bronx County boundary
- **CRS**: EPSG:4269 (NAD83)

## bronx_areawater.geojson

- **Source**: US Census TIGER/Line — Bronx County area water bodies
- **CRS**: EPSG:4269 (NAD83)
- **Used to**: subtract water from the county boundary to get land-only mask

## roads.geojson

- **Source**: US Census TIGER/Line — Bronx County roads
- **CRS**: EPSG:4269 (NAD83)
- **Used to**: burn road buffers out of vacant masks (8m buffer)
