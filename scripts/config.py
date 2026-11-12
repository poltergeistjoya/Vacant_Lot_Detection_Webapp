"""Shared config loader for all scripts.

Uses GENERATE_MASKS_CONFIG if set, otherwise the first config.local.yaml found in
the repo root or the folder above it (shared by all worktrees of a bare repo).
"""

import os
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SEARCH = [_REPO_ROOT / "config.local.yaml", _REPO_ROOT.parent / "config.local.yaml"]


def load_config() -> dict:
    env_path = os.environ.get("GENERATE_MASKS_CONFIG")
    if env_path:
        candidates = [Path(env_path).expanduser()]
    else:
        candidates = _SEARCH

    config_path = next((p for p in candidates if p.exists()), None)
    if config_path is None:
        raise FileNotFoundError(
            "Config not found. Looked in:\n"
            + "".join(f"  {p}\n" for p in candidates)
            + "Copy config.template.yaml to config.local.yaml in one of those places\n"
            "and fill in your paths."
        )

    with config_path.open() as f:
        return yaml.safe_load(f)
