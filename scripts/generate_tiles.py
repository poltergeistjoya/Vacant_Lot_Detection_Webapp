#!/usr/bin/env python3
"""Generate map tiles from prediction TIF, ground truth mask, and NAIP imagery.

Stages:
  A) COG conversion (once) — fast random reads
  B) Load prediction + GT arrays into RAM
  C) Per-threshold outline + error tiles (z12–17)
  D) NAIP RGB tiles (z12–16)

Tiles are written to --output-dir (default: ../tiles/) in {z}/{x}/{y}.png layout
under prefixed subdirectories (outline_t0298/, error_t0298/, naip/).
"""

import subprocess
import sys
from pathlib import Path

import click
import mercantile
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds
from PIL import Image
from scipy.ndimage import gaussian_filter
from tqdm import tqdm

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.local.yaml"
if not _CONFIG_PATH.exists():
    raise FileNotFoundError(
        f"Config not found: {_CONFIG_PATH}\n"
        "Copy config.template.yaml to config.local.yaml and fill in your paths."
    )
with _CONFIG_PATH.open() as _f:
    _cfg = yaml.safe_load(_f)

# --- Paths ---
PRED_STRIPPED = Path(_cfg["data"]["prediction_tif"])
PRED_COG = PRED_STRIPPED.with_name("test_pred_s512_cog.tif")
GT_MASK = Path(_cfg["data"]["gt_mask"])
NAIP_VRT = Path(_cfg["data"]["naip_vrt"])
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "tiles"

CHECKPOINTS = _cfg["thresholds"]["evaluation_thresholds"]

# NYC-specific constants
BOUNDS_4326 = (-73.9409, 40.7857, -73.7577, 40.9248)
OVERLAY_ZOOMS = list(range(12, 18))  # z12–17 for outline + error
NAIP_ZOOMS = list(range(12, 17))     # z12–16


def t_str(t):
    return f"t{round(t * 1000):04d}"


def ensure_cog(skip_cog):
    """Convert stripped TIF to COG if not already done."""
    if PRED_COG.exists():
        click.echo(f"COG already exists: {PRED_COG}")
        return
    if skip_cog:
        click.echo("--skip-cog set but COG doesn't exist. Cannot continue.", err=True)
        sys.exit(1)
    click.echo(f"Converting to COG (this takes ~10-15 min)...")
    subprocess.run([
        "gdal_translate", "-of", "COG",
        "-co", "COMPRESS=DEFLATE", "-co", "BLOCKSIZE=512",
        str(PRED_STRIPPED), str(PRED_COG),
    ], check=True)
    click.echo(f"COG written: {PRED_COG}")


def load_arrays():
    """Load prediction probabilities and aligned ground truth into RAM."""
    click.echo("Loading prediction COG into RAM...")
    with rasterio.open(PRED_COG) as src:
        prob = src.read(1)
        pred_profile = src.profile.copy()
        pred_bounds = src.bounds
        pred_transform = src.transform
        pred_crs = src.crs

    click.echo(f"  pred shape: {prob.shape}, dtype: {prob.dtype}")

    click.echo("Loading ground truth (aligned window)...")
    with rasterio.open(GT_MASK) as gt_src:
        gt_win = from_bounds(*pred_bounds, transform=gt_src.transform)
        gt_win = gt_win.round_offsets().round_lengths()
        gt = gt_src.read(1, window=gt_win, out_shape=prob.shape,
                         resampling=Resampling.nearest)

    click.echo(f"  gt shape: {gt.shape}, dtype: {gt.dtype}")
    assert gt.shape == prob.shape, f"Shape mismatch: gt {gt.shape} vs pred {prob.shape}"

    return prob, gt, pred_profile, pred_transform, pred_crs, pred_bounds


def write_tiles_from_array(rgba, profile, layer_dir, zooms, desc=""):
    """Write an RGBA numpy array as map tiles via rio-tiler."""
    from rio_tiler.io import Reader as TilerReader
    import tempfile

    tmp_path = Path(tempfile.mktemp(suffix=".tif"))
    tile_profile = profile.copy()
    tile_profile.update(driver="GTiff", count=4, dtype="uint8", nodata=None,
                        compress="deflate")
    with rasterio.open(tmp_path, "w", **tile_profile) as dst:
        dst.write(rgba)

    tile_list = list(mercantile.tiles(*BOUNDS_4326, zooms=zooms))
    written = 0

    try:
        with TilerReader(str(tmp_path)) as tiler:
            for tile in tqdm(tile_list, desc=desc, unit="tile"):
                try:
                    img = tiler.tile(tile.x, tile.y, tile.z, tilesize=256)
                except Exception:
                    continue
                if img.mask.all():
                    continue
                out = layer_dir / f"{tile.z}/{tile.x}/{tile.y}.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(img.render(img_format="PNG", add_mask=True))
                written += 1
    finally:
        tmp_path.unlink(missing_ok=True)

    click.echo(f"  {desc}: {written} tiles written")


def generate_overlay(prob, t):
    """Dark semi-transparent overlay on non-vacant predictions with smooth boundary."""
    smoothed = gaussian_filter(prob, sigma=3)
    H, W = prob.shape
    rgba = np.zeros((4, H, W), dtype=np.uint8)
    non_vacant = smoothed <= t
    rgba[0][non_vacant] = 20
    rgba[1][non_vacant] = 20
    rgba[2][non_vacant] = 20
    rgba[3][non_vacant] = 140
    return rgba


def generate_error(prob, gt, t):
    """TP/FP/FN error map at threshold t. TN = transparent."""
    H, W = prob.shape
    pred_bin = prob > t

    valid = gt != 255
    mask = valid & ~np.isnan(prob)
    tp = mask & pred_bin & (gt == 1)
    fp = mask & pred_bin & (gt == 0)
    fn = mask & ~pred_bin & (gt == 1)

    rgba = np.zeros((4, H, W), dtype=np.uint8)
    # TP = green
    rgba[0][tp] = 0;   rgba[1][tp] = 200; rgba[2][tp] = 0;   rgba[3][tp] = 180
    # FP = red
    rgba[0][fp] = 220; rgba[1][fp] = 0;   rgba[2][fp] = 0;   rgba[3][fp] = 180
    # FN = blue
    rgba[0][fn] = 0;   rgba[1][fn] = 100; rgba[2][fn] = 255; rgba[3][fn] = 180
    return rgba


def generate_naip_tiles(output_dir):
    """Tile NAIP imagery at z12–16."""
    from rio_tiler.io import Reader as TilerReader

    naip_dir = output_dir / "naip"
    tile_list = list(mercantile.tiles(*BOUNDS_4326, zooms=NAIP_ZOOMS))
    written = 0

    with TilerReader(str(NAIP_VRT)) as tiler:
        for tile in tqdm(tile_list, desc="naip", unit="tile"):
            try:
                img = tiler.tile(tile.x, tile.y, tile.z, tilesize=256,
                                 indexes=[1, 2, 3])
            except Exception:
                continue
            out = naip_dir / f"{tile.z}/{tile.x}/{tile.y}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(img.render(img_format="PNG"))
            written += 1

    click.echo(f"NAIP: {written} tiles written")


@click.command()
@click.option("--skip-cog", is_flag=True, help="Skip COG conversion (must already exist)")
@click.option("--only-threshold", type=float, default=None,
              help="Generate tiles for a single threshold only")
@click.option("--skip-naip", is_flag=True, help="Skip NAIP tile generation")
@click.option("--output-dir", type=click.Path(), default=str(DEFAULT_OUT),
              help="Output directory for tiles")
@click.option("--skip-overlay", is_flag=True, help="Skip non-vacant overlay tiles")
@click.option("--skip-error", is_flag=True, help="Skip error map tiles")
def main(skip_cog, only_threshold, skip_naip, output_dir, skip_overlay, skip_error):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Stage A: COG
    ensure_cog(skip_cog)

    # Stage B: Load arrays
    prob, gt, profile, transform, crs, bounds = load_arrays()

    # Stage C: Per-threshold tiles
    thresholds = [only_threshold] if only_threshold is not None else CHECKPOINTS
    for t in thresholds:
        ts = t_str(t)
        click.echo(f"\n--- Threshold {t} ({ts}) ---")

        if not skip_overlay:
            rgba_overlay = generate_overlay(prob, t)
            write_tiles_from_array(
                rgba_overlay, profile,
                output_dir / ts / "overlay", OVERLAY_ZOOMS,
                desc=f"overlay_{ts}")
            del rgba_overlay

        if not skip_error:
            rgba_error = generate_error(prob, gt, t)
            write_tiles_from_array(
                rgba_error, profile,
                output_dir / ts / "error", OVERLAY_ZOOMS,
                desc=f"error_{ts}")
            del rgba_error

    # Stage D: NAIP
    if not skip_naip:
        click.echo("\n--- NAIP tiles ---")
        generate_naip_tiles(output_dir)

    click.echo("\nDone!")


if __name__ == "__main__":
    main()
