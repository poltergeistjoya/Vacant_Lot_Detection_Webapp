"""Shared config loader for all scripts.

Checks GENERATE_MASKS_CONFIG env var first, then falls back to
config.local.yaml in the repo root.
"""

import os
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    env_path = os.environ.get("GENERATE_MASKS_CONFIG")
    if env_path:
        config_path = Path(env_path).expanduser()
    else:
        config_path = _REPO_ROOT / "config.local.yaml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found: {config_path}\n"
            "Copy config.template.yaml to config.local.yaml and fill in your paths,\n"
            "or set GENERATE_MASKS_CONFIG to point to your config file."
        )

    with config_path.open() as f:
        return yaml.safe_load(f)
