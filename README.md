# Bronx Vacant Lot Detection

Interactive web map showing predicted vacant lots across the Bronx, built on
U-Net (ResNet-34) segmentation of NAIP aerial imagery. Esri World Imagery
basemap tiles are composited server-side with per-zone color treatments
(basemap / vacant / non-vacant) so the real aerial photography stays visible
under every effect.

Live at **[app.joya.dev](https://app.joya.dev)**

## Quick Start

```bash
uv sync                              # install Python dependencies
npm install                          # install JS dependencies

# Config: copy template and fill in paths, or set the env var
cp config.template.yaml config.local.yaml
# OR: export GENERATE_MASKS_CONFIG=~/.config/generate_masks/config.local.yaml

# Generate masks for all thresholds (or use -t 0.298 for just one)
cd scripts && uv run prepare_mask_overlay.py --all && cd ..

# Start the backend + frontend
uv run uvicorn server.app:app --reload &  # FastAPI backend on :8000
npm run dev                               # Vite dev server on :5173
```

Open http://localhost:5173 in your browser.

## Playground (local dev only)

The color-tuning playground (`src/playground.html`) is available only during
local development via `npm run dev`. It is **not** included in production
Docker builds or deployed to Cloud Run.

## Docker

```bash
docker build -t vacant-lot-app .
docker run -p 8000:8000 vacant-lot-app
```

Open http://localhost:8000 — serves both the API and the built frontend.

## Deploy (Google Cloud Run)

One-time setup:

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
gcloud artifacts repositories create vacant-lot --repository-format=docker --location=us-east4
```

Deploy:

```bash
./deploy.sh
```

Custom domain: add a CNAME record at your registrar pointing to
`ghs.googlehosted.com`, then create a Cloud Run domain mapping.

## Generating masks

`scripts/prepare_mask_overlay.py` reads the raw prediction probability TIF
(`data.prediction_tif` in config), reprojects it to Web Mercator, and
produces masks at each requested threshold:

```
data/masks/
  boundary.png          # shared Bronx land mask (water subtracted)
  bounds.json           # WGS84 geo bounds
  t0298/vacant.png      # per-threshold vacant mask
  t0400/vacant.png
  ...
```

Usage:
- `--all` generates all 18 checkpoints from config
- `-t 0.298` generates a single threshold (repeatable)
- No args generates only the default threshold

The script only *reads* the source TIF — never modifies it. Outputs are
gitignored; re-run whenever the source prediction changes.
