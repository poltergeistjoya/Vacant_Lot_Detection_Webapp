# Vacant Lot Detection Webapp

## Config

Scripts in `scripts/` load config via `scripts/config.py`, which reads from the `GENERATE_MASKS_CONFIG` env var or falls back to `config.local.yaml` in the repo root.

The stable config lives at `~/.config/generate_masks/config.local.yaml`. In worktrees (which lack `config.local.yaml`), set the env var before running scripts:

```bash
export GENERATE_MASKS_CONFIG=~/.config/generate_masks/config.local.yaml
```

This is **not** in `.zshrc` — set it manually per session, or add it to your shell profile.

## Data pipeline scripts

- `scripts/prepare_mask_overlay.py` — generates raster vacancy masks at various thresholds
- `scripts/fetch_athletic_surfaces.py` — downloads athletic surface polygons from OpenStreetMap, outputs `data/athletic_surfaces.geojson`
- `scripts/prepare_athletic_surfaces.py` — enriches athletic surfaces with model coverage fractions, outputs `data/athletic_surfaces_enriched.geojson`
- `scripts/prepare_parcels.py` — downloads MapPLUTO, intersects with prediction raster, outputs `data/parcels.geojson`

Both require the config above (specifically `data.prediction_tif`).
