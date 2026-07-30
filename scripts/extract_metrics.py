#!/usr/bin/env python3
"""Extract precision/recall/F1/F2 at checkpoint thresholds from pr_curves.npz."""

import json
from pathlib import Path

import numpy as np
import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.local.yaml"
if not _CONFIG_PATH.exists():
    raise FileNotFoundError(
        f"Config not found: {_CONFIG_PATH}\n"
        "Copy config.template.yaml to config.local.yaml and fill in your paths."
    )
with _CONFIG_PATH.open() as _f:
    _cfg = yaml.safe_load(_f)

NPZ_PATH = Path(_cfg["data"]["pr_curves"])
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "thresholds.json"


def compute_metrics(precision, recall, thresholds, checkpoints):
    idx = np.clip(np.searchsorted(thresholds, checkpoints, side="right") - 1, 0, len(thresholds) - 1)
    p, r = precision[idx], recall[idx]
    f1 = 2 * p * r / (p + r + 1e-12)
    f2 = 5 * p * r / (4 * p + r + 1e-12)
    return [
        {"precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4),
         "f1": round(float(f1[i]), 4), "f2": round(float(f2[i]), 4)}
        for i in range(len(checkpoints))
    ]


def main():
    t_cfg = _cfg["thresholds"]
    checkpoints = np.array(t_cfg["evaluation_thresholds"])

    data = np.load(NPZ_PATH)
    splits = {
        prefix: (data[f"{prefix}_pr_precision"], data[f"{prefix}_pr_recall"], data[f"{prefix}_pr_thresholds"])
        for prefix in ("val", "test")
    }

    split_metrics = {
        name: compute_metrics(prec, rec, thresh, checkpoints)
        for name, (prec, rec, thresh) in splits.items()
    }

    entries = [
        {"t": float(t), "tStr": f"t{round(t * 1000):04d}", **{name: split_metrics[name][i] for name in splits}}
        for i, t in enumerate(checkpoints)
    ]

    result = {
        "default_threshold": t_cfg["default"],
        "good_zone": t_cfg["good_zone"],
        "checkpoints": entries,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {OUT_PATH} ({len(entries)} checkpoints)")


if __name__ == "__main__":
    main()
