"""Persistence helpers for physics engine tuning overrides."""

from __future__ import annotations

import json
from typing import Any, Dict

from physics_sim.config import DEFAULT_TUNING
from utils.path_utils import get_base_dir

__all__ = [
    "TUNING_OVERRIDES_PATH",
    "get_physics_tuning_overrides",
    "load_physics_tuning_overrides",
    "load_physics_tuning_values",
    "reset_physics_tuning_overrides",
    "save_physics_tuning_overrides",
]

TUNING_OVERRIDES_PATH = get_base_dir() / "data" / "physics_tuning_overrides.json"
_NUMERIC_TYPES = (int, float)


def get_physics_tuning_overrides() -> Dict[str, float]:
    """Return the current physics tuning overrides."""

    return load_physics_tuning_overrides()


def load_physics_tuning_overrides() -> Dict[str, float]:
    """Load tuning overrides from disk."""

    if not TUNING_OVERRIDES_PATH.exists():
        return {}
    try:
        payload = json.loads(TUNING_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return _sanitize_overrides(payload)


def load_physics_tuning_values() -> Dict[str, float]:
    """Return defaults merged with any stored overrides."""

    values = {
        key: float(value)
        for key, value in DEFAULT_TUNING.items()
        if isinstance(value, _NUMERIC_TYPES)
    }
    values.update(load_physics_tuning_overrides())
    return values


def save_physics_tuning_overrides(overrides: Dict[str, float]) -> None:
    """Persist tuning overrides to disk."""

    cleaned = _sanitize_overrides(overrides)
    if not cleaned:
        reset_physics_tuning_overrides()
        return
    TUNING_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TUNING_OVERRIDES_PATH.write_text(
        json.dumps(cleaned, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def reset_physics_tuning_overrides() -> None:
    """Remove any saved overrides and fall back to defaults."""

    try:
        TUNING_OVERRIDES_PATH.unlink()
    except FileNotFoundError:
        pass


def _sanitize_overrides(data: Dict[str, Any]) -> Dict[str, float]:
    cleaned: Dict[str, float] = {}
    for key, value in data.items():
        if key not in DEFAULT_TUNING:
            continue
        default_value = DEFAULT_TUNING.get(key)
        if not isinstance(default_value, _NUMERIC_TYPES):
            continue
        try:
            cleaned[key] = float(value)
        except (TypeError, ValueError):
            continue
    return cleaned
