# Vacant Lot Overlay Playground

Local visual experimentation playground for the Bronx vacant-lot prediction mask.
Esri World Imagery basemap with the vacancy mask used as a *clipping mask*,
not a color fill: every effect is scoped to pixels where the mask == 1, and
the real aerial imagery stays visible underneath, just locally adjusted. No
thresholding happens here — the mask is treated as fixed, already-thresholded
input.

## Quick Start

```bash
uv sync                              # install Python dependencies
npm install                          # install JS dependencies

# Config: copy template and fill in paths, or set the env var for worktree persistence
cp config.template.yaml config.local.yaml
# OR: export GENERATE_MASKS_CONFIG=~/.config/generate_masks/config.local.yaml

# Generate masks for all thresholds (or use -t 0.298 for just one)
cd scripts && uv run prepare_mask_overlay.py --all && cd ..

# Start the backend + frontend
uv run uvicorn server.app:app --reload &  # FastAPI backend on :8000
npm run dev                               # Vite dev server on :5173
```

Open http://localhost:5173 in your browser.

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

## Controls

**Inside-area effects** — brightness, contrast, saturation, hue, blur —
adjust the actual Esri imagery only where the mask is 1. This is done with
a *second* copy of the Esri tile layer, filtered with CSS, and clipped with
a CSS `mask-image` sized/positioned to the mask's geographic bounds. Outside
the mask that layer is fully transparent, so the unfiltered base imagery
underneath shows through untouched — nowhere does a flat color get painted
over the imagery.

**Boundary effects** — Outline, Glow, Shadow — are derived from the mask's
edge and rendered as separate canvas layers:
- *Outline*: a ring grown outward from the boundary by the given width, tinted
  and shown at the given opacity.
- *Glow* / *Shadow*: the full mask shape tinted (glow: chosen color; shadow:
  black) at `strength` alpha, then CSS-blurred by `radius`. Because these
  layers sit *underneath* the clipped inside-effects layer in z-order, the
  portion of the blur that bleeds inward is hidden by it — only the outward
  bleed past the boundary remains visible, which is what gives the "extends
  slightly outside the prediction boundary" look without extra math.

**Show Original** temporarily hides every effect (for comparison) without
touching any control's value; toggling back restores exactly what was set.
Reset restores all defaults. Every control updates the map immediately and
is independently adjustable — combine as many effects as you like.
