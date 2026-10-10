"""Persistence helpers for physics engine tuning overrides."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

from physics_sim.config import DEFAULT_TUNING
from utils.path_utils import ActivePath, get_data_dir

__all__ = [
    "STEAL_FREQ_REBASE_MARKER",
    "TUNING_OVERRIDES_PATH",
    "get_physics_tuning_overrides",
    "load_physics_tuning_overrides",
    "load_physics_tuning_values",
    "reset_physics_tuning_overrides",
    "save_physics_tuning_overrides",
]

TUNING_OVERRIDES_PATH = ActivePath(lambda: get_data_dir() / "physics_tuning_overrides.json")
_NUMERIC_TYPES = (int, float)

# Release 4 (audit H2, owner decision): the Steal Frequency slider was rebased
# so 1.0 = MLB volume (the old default 3.0 is the new 1.0). A file saved
# before the rebase holds steal_freq_scale on the old scale; it is divided by
# 3 once. Every file written from now on carries this marker, so a stored
# value is never divided twice. The marker is not a tuning knob.
STEAL_FREQ_REBASE_MARKER = "_steal_freq_scale_rebased_r4"
_STEAL_FREQ_REBASE_DIVISOR = 3.0


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
    cleaned = _sanitize_overrides(payload)
    if not payload.get(STEAL_FREQ_REBASE_MARKER):
        cleaned = _rebase_steal_freq(cleaned)
    return cleaned


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
    """Persist tuning overrides to disk (on the current slider scales)."""

    cleaned = _sanitize_overrides(overrides)
    if not cleaned:
        reset_physics_tuning_overrides()
        return
    payload: Dict[str, Any] = dict(cleaned)
    payload[STEAL_FREQ_REBASE_MARKER] = True
    _write_atomic(Path(TUNING_OVERRIDES_PATH), payload)


def reset_physics_tuning_overrides() -> None:
    """Remove any saved overrides and fall back to defaults."""

    try:
        TUNING_OVERRIDES_PATH.unlink()
    except FileNotFoundError:
        pass


def _rebase_steal_freq(cleaned: Dict[str, float]) -> Dict[str, float]:
    """One-time Release 4 migration of a pre-rebase file (see the marker).

    The divided value is written back with the marker so the file itself is
    migrated; if the write fails (a read-only copy) the division still
    applies in memory, from the unchanged file, on every load.
    """
    if "steal_freq_scale" not in cleaned:
        return cleaned
    migrated = dict(cleaned)
    migrated["steal_freq_scale"] = (
        cleaned["steal_freq_scale"] / _STEAL_FREQ_REBASE_DIVISOR
    )
    try:
        save_physics_tuning_overrides(migrated)
    except OSError:
        pass
    return migrated


def _write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    # Replace, never rewrite in place: games read this file on every run,
    # and the one-time migration below may write it from inside a sim.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        # Never leave a partial temp file for the working-copy sync to push.
        tmp.unlink(missing_ok=True)
        raise


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
