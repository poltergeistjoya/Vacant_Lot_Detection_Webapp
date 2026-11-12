# Vacant Lot Detection Webapp

## Config

Scripts in `scripts/` load config via `scripts/config.py`: `GENERATE_MASKS_CONFIG` if set, otherwise the first `config.local.yaml` in the repo root or the folder above it (gitignored; template `config.template.yaml`).

The repo is a bare clone with each worktree as a sibling folder, so one `config.local.yaml` in the bare repo folder (next to `main/` and the other worktrees) serves all of them. Don't put it in the home directory.

Deployment settings (GCP project, region, Cloud Run service, bucket) live in `.env` in the repo root (gitignored; template `.env.example`). `deploy.sh` and `scripts/upload_pmtiles.sh` load it themselves. Don't hardcode them in tracked files.

## Tile compositing

All color treatment of vacancy tiles (Esri imagery + vacancy masks + `data/product_treatment.json`) is done in Python (`server/compositing.py`: `apply_color_ops_fast`, `composite_tile_u8`) when tiles are prerendered. Do **not** move color treatment to the browser: JS/WebGL/MapLibre paint properties don't reproduce the Python pipeline (LUT-based Oklch). The browser may only do **pixel selection between tiles that Python prerendered**.

Tiles are served as PMTiles from a **private** bucket: the browser's pmtiles library makes range requests to `/api/pmtiles/<archive>`, which Cloud Run forwards to `gs://$TILE_STORE_BUCKET/pmtiles/` with its service account (`server/app.py`, "PMTiles archives"). Locally too: run `uv run --env-file .env uvicorn server.dev:app --reload` (gcloud application-default credentials); archives are never served from `data/`. Don't make bucket objects public.

The deployed app (`server.app:app`) only proxies archives and serves the built frontend: it never imports `server/compositing.py` or reads `data/masks/` (guarded by `test_production_app_does_not_load_compositing`). Masks are only for prerendering and for the dev-only playground (`server/dev.py` adds `server/playground.py`). The frontend gets data files from the `WEB_DATA` list in `vite.config.js`, not all of `data/`.

Thresholds are defined once in `data/thresholds.json` (written by `scripts/extract_metrics.py`): `THRESHOLDS` in `server/compositing.py` and `CHECKPOINTS` in `src/lib/layers.js` both read it.

How each vacancy source is served (`src/lib/tiles.js`):
- **Model + PLUTO**: `pmtiles/both/{threshold}.pmtiles`, one archive per threshold.
- **PLUTO only**: `pmtiles/both/t1000.pmtiles`. Nothing is model-vacant at t1000, so it is exactly PLUTO-only (guarded by `test_pluto_only_equals_both_at_max_threshold`).
- **Model only**: the Model + PLUTO tile, with PLUTO pixels the model doesn't call vacant at the current threshold swapped for pixels from `pmtiles/pluto_nonvacant.pmtiles` (non-vacant treatment). Which pixels to swap comes from `pmtiles/model_levels.pmtiles`. See "Model-only from Model + PLUTO" in `server/compositing.py`. This relies on the threshold masks being nested (guarded by `test_threshold_masks_are_nested`).

## Tile pipeline

```bash
uv run scripts/prerender_tiles.py           # renders all loose tiles, z11–19 → data/tiles/{product/{t},pluto_nonvacant,model_levels}/ (masks + treatment + Esri)
uv run scripts/generate_pmtiles.py          # packages them only → data/pmtiles/both/{t}.pmtiles, pluto_nonvacant.pmtiles, model_levels.pmtiles (--archive to pick)
npm run test:all                            # includes archive header checks
./scripts/upload_pmtiles.sh                 # new/changed data/pmtiles/ → gs://$TILE_STORE_BUCKET/pmtiles/ (or name archives: both, both/t0298, model_levels; -n = dry run)
./deploy.sh                                 # runs tests first
```

Re-run both scripts when masks or the color treatment change (delete the stale loose tiles first: rendering is resumable and skips tiles that exist).

## Data pipeline scripts

- `scripts/prepare_mask_overlay.py` — generates raster vacancy masks at various thresholds
- `scripts/fetch_athletic_surfaces.py` — downloads athletic surface polygons from OpenStreetMap, outputs `data/athletic_surfaces.geojson`
- `scripts/prepare_athletic_surfaces.py` — enriches athletic surfaces with model coverage fractions, outputs `data/athletic_surfaces_enriched.geojson`
- `scripts/prepare_parcels.py` — downloads MapPLUTO, intersects with prediction raster, outputs `data/parcels.geojson`

Both require the config above (specifically `data.prediction_tif`).
