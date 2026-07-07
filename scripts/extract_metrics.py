#!/usr/bin/env python3
"""Extract precision/recall/F1/F2 at checkpoint thresholds from pr_curves.npz."""

import json
from pathlib import Path

import numpy as np

NPZ_PATH = Path("/Users/joyadebi/repos/Vacant_Lot_Detection/outputs/models/deeplabv3plus/kahan_027/pr_curves.npz")
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "thresholds.json"

CHECKPOINTS = [0.0, 0.1, 0.2, 0.298, 0.32, 0.34, 0.36, 0.38, 0.40,
               0.42, 0.44, 0.45, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def metrics_at(precision, recall, thresholds, t):
    """Interpolate precision/recall at threshold t using sklearn convention."""
    if t <= 0.0:
        idx = 0
    elif t >= thresholds[-1]:
        idx = len(thresholds) - 1
    else:
        idx = int(np.searchsorted(thresholds, t, side="right")) - 1
        idx = max(0, min(idx, len(thresholds) - 1))
    p, r = float(precision[idx]), float(recall[idx])
    f1 = 2 * p * r / (p + r + 1e-12)
    f2 = 5 * p * r / (4 * p + r + 1e-12)
    return {"precision": round(p, 4), "recall": round(r, 4),
            "f1": round(f1, 4), "f2": round(f2, 4)}


def main():
    data = np.load(NPZ_PATH)
    splits = {}
    for prefix in ("val", "test"):
        splits[prefix] = (
            data[f"{prefix}_pr_precision"],
            data[f"{prefix}_pr_recall"],
            data[f"{prefix}_pr_thresholds"],
        )

    entries = []
    for t in CHECKPOINTS:
        t_str = f"t{round(t * 1000):04d}"
        entry = {"t": t, "tStr": t_str}
        for split_name, (prec, rec, thresh) in splits.items():
            entry[split_name] = metrics_at(prec, rec, thresh, t)
        entries.append(entry)

    result = {
        "default_threshold": 0.298,
        "good_zone": [0.298, 0.450],
        "checkpoints": entries,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {OUT_PATH} ({len(entries)} checkpoints)")


if __name__ == "__main__":
    main()
