# Data Sources

## community_districts.geojson

- **Description:** NYC Community District boundaries for all five boroughs (71 features including joint interest areas)
- **Source:** NYC Department of City Planning, via [dwillis/nyc-maps](https://github.com/dwillis/nyc-maps) GitHub mirror
- **Original dataset:** NYC Open Data — "Community Districts" (dataset ID `jp9i-3b7y`)
- **Coordinate system:** WGS 84 (CRS:84)
- **Properties:** `BoroCD` (3-digit code: first digit = borough, remaining = district number), `Shape_Leng`, `Shape_Area`
- **Borough codes:** 1 = Manhattan, 2 = Bronx, 3 = Brooklyn, 4 = Queens, 5 = Staten Island
- **Retrieved:** 2026-09-10

## bronx_boundary.geojson

- **Description:** Bronx borough boundary polygon
- **Source:** NYC Open Data

## bronx_areawater.geojson

- **Description:** Bronx area water features
- **Source:** US Census Bureau TIGER/Line

## roads.geojson

- **Description:** Road network for the Bronx study area
- **Source:** OpenStreetMap

## thresholds.json

- **Description:** Model threshold metrics (precision, recall, F1) at each checkpoint
- **Source:** Generated from U-Net model evaluation

## product_treatment.json

- **Description:** Default product visual treatment settings
- **Source:** Internal configuration
