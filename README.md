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
cp config.template.yaml config.local.yaml   # then fill in vacant_mask_tif
uv run scripts/prepare_mask_overlay.py      # generates data/mask_overlay.{png,json}
npm run dev                          # start Vite dev server
```

Open http://localhost:5173 in your browser.

## Generating the overlay

`scripts/prepare_mask_overlay.py` reads `data.vacant_mask_tif` from
`config.local.yaml`, reprojects it to Web Mercator, and writes:

- `data/mask_overlay.png` — RGBA image; alpha channel is the mask (opaque
  where the source pixel value is exactly `1`, transparent for `0`, `255`,
  and any NoData). Downsampled to a max side of 6000px for browser
  performance (`Resampling.max` keeps small vacant lots from vanishing).
- `data/mask_overlay.json` — WGS84 bounds for the overlay.

It only *reads* the source TIF — never modifies it. Both output files are
gitignored; re-run the script whenever the source mask changes.

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
