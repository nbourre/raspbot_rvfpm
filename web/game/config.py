# -*- coding: utf-8 -*-
"""
web/game/config.py
------------------
Game configuration: gameplay parameters + per-color HSV calibration ranges.
Persisted to color_config.json at the project root on the Pi.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# File path
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parents[2] / "color_config.json"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    # Gameplay
    "num_stops": 5,
    "hold_duration": 1.0,       # seconds the robot must stay in position
    "overlay_min_ratio": 0.20,  # min overlay circle radius as fraction of image width
    "overlay_max_ratio": 0.35,  # max overlay circle radius as fraction of image width
    "center_tolerance": 0.10,   # allowed offset from image center (fraction of width)
    "radius_tolerance": 0.10,   # allowed radius mismatch (fraction of overlay radius)

    # HSV calibration per color.
    # Each entry: [H_min, H_max, S_min, S_max, V_min, V_max]
    # OpenCV HSV: H in [0,179], S and V in [0,255]
    "colors": {
        "red": {
            "ranges": [
                [0, 10, 100, 255, 80, 255],
                [160, 179, 100, 255, 80, 255]
            ]
        },
        "green": {
            "ranges": [
                [40, 85, 60, 255, 60, 255]
            ]
        },
        "blue": {
            "ranges": [
                [100, 130, 80, 255, 60, 255]
            ]
        },
        "black": {
            # Black: low saturation AND low value (avoids dark-but-coloured shadows)
            "ranges": [
                [0, 179, 0, 60, 0, 60]
            ]
        }
    }
}

# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

_config: dict[str, Any] | None = None


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively, returning a new dict."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load() -> dict[str, Any]:
    """Load config from disk, merged with defaults. Cached in memory."""
    global _config
    if _config is not None:
        return _config
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                on_disk = json.load(fh)
            _config = _deep_merge(DEFAULT_CONFIG, on_disk)
        except Exception:
            _config = dict(DEFAULT_CONFIG)
    else:
        _config = dict(DEFAULT_CONFIG)
    return _config


def save(new_config: dict[str, Any]) -> None:
    """Persist config to disk and update the in-memory cache."""
    global _config
    _config = _deep_merge(DEFAULT_CONFIG, new_config)
    CONFIG_PATH.write_text(
        json.dumps(_config, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def reload() -> dict[str, Any]:
    """Force reload from disk."""
    global _config
    _config = None
    return load()
