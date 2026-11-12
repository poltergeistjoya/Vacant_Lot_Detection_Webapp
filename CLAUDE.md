# Vacant Lot Detection Webapp

## Config

Scripts in `scripts/` load config via `scripts/config.py`, which reads from the `GENERATE_MASKS_CONFIG` env var or falls back to `config.local.yaml` in the repo root.

The stable config lives at `~/.config/generate_masks/config.local.yaml`. In worktrees (which lack `config.local.yaml`), set the env var before running scripts:

```bash
export GENERATE_MASKS_CONFIG=~/.config/generate_masks/config.local.yaml
```

This is **not** in `.zshrc` — set it manually per session, or add it to your shell profile.

Deployment settings (GCP project, region, Cloud Run service, bucket) live in `.env` in the repo root (gitignored; template `.env.example`). `deploy.sh` and `scripts/*.sh` load it via `scripts/env.sh`. Don't hardcode them in tracked files.

## Tile compositing

All color treatment of vacancy tiles (Esri imagery + vacancy masks + `data/product_treatment.json`) is done in Python (`server/app.py`: `apply_color_ops_fast`, `composite_tile_u8`). Do **not** move color treatment to the browser: JS/WebGL/MapLibre paint properties don't reproduce the Python pipeline (LUT-based Oklch). The browser may only do **pixel selection between tiles that Python prerendered**.

Tiles are served browser → GCS as PMTiles (no Cloud Run in the path). Live compositing on Cloud Run (`/api/tile/product`) is only a fallback for local dev without PMTiles and for the playground.

How each vacancy source is served (`src/lib/tiles.js`):
- **Model + PLUTO**: `pmtiles/both/{threshold}.pmtiles`, one archive per threshold.
- **PLUTO only**: `pmtiles/both/t1000.pmtiles`. Nothing is model-vacant at t1000, so it is exactly PLUTO-only (guarded by `test_pluto_only_equals_both_at_max_threshold`).
- **Model only**: the Model + PLUTO tile, with PLUTO pixels the model doesn't call vacant at the current threshold swapped for pixels from `pmtiles/pluto_nonvacant.pmtiles` (non-vacant treatment). Which pixels to swap comes from `pmtiles/model_levels.pmtiles`. See "Model-only from Model + PLUTO" in `server/app.py`. This relies on the threshold masks being nested (guarded by `test_threshold_masks_are_nested`).

## Tile pipeline

```bash
uv run scripts/prerender_tiles.py           # Model + PLUTO loose tiles, z11–19, all thresholds → data/tiles/product/
uv run scripts/generate_pmtiles.py          # → data/pmtiles/both/{t}.pmtiles, pluto_nonvacant.pmtiles, model_levels.pmtiles (--archive to pick)
npm run test:all                            # includes archive header checks
./scripts/upload_pmtiles.sh                 # new/changed data/pmtiles/ → gs://$TILE_STORE_BUCKET/pmtiles/ (or name archives: both, both/t0298, model_levels; -n = dry run)
./deploy.sh                                 # runs tests + scripts/check_pmtiles_gcs.sh first
```

Re-run both scripts when masks or the color treatment change. Rendering is resumable: existing loose tiles are skipped.

## Data pipeline scripts

- `scripts/prepare_mask_overlay.py` — generates raster vacancy masks at various thresholds
- `scripts/fetch_athletic_surfaces.py` — downloads athletic surface polygons from OpenStreetMap, outputs `data/athletic_surfaces.geojson`
- `scripts/prepare_athletic_surfaces.py` — enriches athletic surfaces with model coverage fractions, outputs `data/athletic_surfaces_enriched.geojson`
- `scripts/prepare_parcels.py` — downloads MapPLUTO, intersects with prediction raster, outputs `data/parcels.geojson`

Both require the config above (specifically `data.prediction_tif`).
