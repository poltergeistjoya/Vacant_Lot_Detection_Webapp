# Bronx Vacant Lot Detection Webapp

Interactive map displaying DeepLabV3+ vacant lot predictions for the Bronx. City planners can explore predictions at adjustable confidence thresholds, compare against ground truth error maps, and toggle reference layers (NAIP imagery, parks).

## Quick Start

```bash
uv sync         # install Python dependencies
npm install     # install JS dependencies
npm run dev     # start Vite dev server
```

Open http://localhost:5173 in your browser.

## Generating Data

### 1. Extract metrics

Produces `data/thresholds.json` from the PR curves:

```bash
uv run scripts/extract_metrics.py
```

### 2. Generate map tiles

Requires the prediction TIF, ground truth mask, and NAIP VRT from the research repo.

Full run (~2.5 hours, generates all 18 thresholds + NAIP):

```bash
uv run scripts/generate_tiles.py
```

Test with a single threshold:

```bash
uv run scripts/generate_tiles.py --only-threshold 0.298
```

Other flags: `--skip-cog`, `--skip-naip`, `--skip-outline`, `--skip-error`, `--output-dir PATH`.

### 3. Serve tiles locally during development

The dev frontend expects tiles at `http://localhost:8080/tiles`. Use any static file server:

```bash
cd tiles && python3 -m http.server 8080 --bind 127.0.0.1
```

### 4. Parks GeoJSON

Download Bronx parks from NYC Open Data:

```bash
ogr2ogr -f GeoJSON data/parks.geojson \
  "https://data.cityofnewyork.us/api/geospatial/enfh-gkve?method=export&type=GeoJSON" \
  -where "borough='X'"
```

## Deployment

Pushes to `main` trigger GitHub Actions to build and deploy to GitHub Pages. Tiles live on the `gh-pages` branch (not `main`) and are preserved across deploys via `keep_files: true`.

To push tiles:

```bash
git clone --branch gh-pages <repo-url> gh-pages-staging
cp -r tiles/ gh-pages-staging/tiles/
cd gh-pages-staging && git add tiles/ && git commit -m "Add tiles" && git push
```

## Layers

| Layer | Description |
|---|---|
| NAIP Imagery | 2022 NAIP aerial photos (z12–16) |
| Predicted Outlines | Yellow outlines of predicted vacant lots at current threshold (z12–17) |
| Error Map | TP (green), FP (red), FN (blue) against ground truth (z12–17) |
| Parks | NYC DPR parks and open spaces |

## Threshold Slider

18 checkpoints from 0.0 to 1.0. The highlighted "good zone" (0.298–0.450) marks thresholds with the best F2 scores. Default: 0.298 (best F2 on test split).
