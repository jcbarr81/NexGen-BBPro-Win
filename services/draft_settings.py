"""Per-league draft configuration.

Stores the number of rounds and the pool size the commissioner wants for
the amateur draft. Read at league creation, overridable season-to-season
from the Draft admin tab. Persisted to
``<data_dir>/draft_settings.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from utils.path_utils import get_data_dir

DEFAULT_ROUNDS = 10
DEFAULT_POOL_SIZE = 200
MIN_ROUNDS = 1
MAX_ROUNDS = 50
MIN_POOL_SIZE = 20
MAX_POOL_SIZE = 2000

# How long a human owner has once his team goes on the clock. One duration for
# the whole draft rather than a per-pick deadline, so there is nothing for the
# commissioner to re-set between picks. 0 turns the clock off entirely and the
# draft waits indefinitely, which is the old behaviour.
DEFAULT_PICK_CLOCK_HOURS = 0
MIN_PICK_CLOCK_HOURS = 0
MAX_PICK_CLOCK_HOURS = 336  # two weeks


@dataclass
class DraftSettings:
    rounds: int = DEFAULT_ROUNDS
    pool_size: int = DEFAULT_POOL_SIZE
    pick_clock_hours: int = DEFAULT_PICK_CLOCK_HOURS

    def to_dict(self) -> Dict[str, int]:
        return {
            "rounds": int(self.rounds),
            "pool_size": int(self.pool_size),
            "pick_clock_hours": int(self.pick_clock_hours),
        }


def _settings_path(data_dir: Path | None = None) -> Path:
    root = Path(data_dir) if data_dir is not None else get_data_dir()
    return root / "draft_settings.json"


def load_draft_settings(data_dir: Path | None = None) -> DraftSettings:
    path = _settings_path(data_dir)
    if not path.exists():
        return DraftSettings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return DraftSettings()
    rounds = _clamp(
        payload.get("rounds", DEFAULT_ROUNDS), MIN_ROUNDS, MAX_ROUNDS, DEFAULT_ROUNDS
    )
    pool = _clamp(
        payload.get("pool_size", DEFAULT_POOL_SIZE),
        MIN_POOL_SIZE,
        MAX_POOL_SIZE,
        DEFAULT_POOL_SIZE,
    )
    clock = _clamp(
        payload.get("pick_clock_hours", DEFAULT_PICK_CLOCK_HOURS),
        MIN_PICK_CLOCK_HOURS,
        MAX_PICK_CLOCK_HOURS,
        DEFAULT_PICK_CLOCK_HOURS,
    )
    return DraftSettings(rounds=rounds, pool_size=pool, pick_clock_hours=clock)


def save_draft_settings(
    settings: DraftSettings, *, data_dir: Path | None = None
) -> DraftSettings:
    rounds = _clamp(settings.rounds, MIN_ROUNDS, MAX_ROUNDS, DEFAULT_ROUNDS)
    pool = _clamp(settings.pool_size, MIN_POOL_SIZE, MAX_POOL_SIZE, DEFAULT_POOL_SIZE)
    clock = _clamp(
        settings.pick_clock_hours,
        MIN_PICK_CLOCK_HOURS,
        MAX_PICK_CLOCK_HOURS,
        DEFAULT_PICK_CLOCK_HOURS,
    )
    normalized = DraftSettings(rounds=rounds, pool_size=pool, pick_clock_hours=clock)
    path = _settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized.to_dict(), indent=2), encoding="utf-8")
    return normalized


def _clamp(value: Any, lo: int, hi: int, fallback: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(lo, min(hi, n))


__all__ = [
    "DraftSettings",
    "DEFAULT_ROUNDS",
    "DEFAULT_POOL_SIZE",
    "MIN_ROUNDS",
    "MAX_ROUNDS",
    "MIN_POOL_SIZE",
    "MAX_POOL_SIZE",
    "DEFAULT_PICK_CLOCK_HOURS",
    "MIN_PICK_CLOCK_HOURS",
    "MAX_PICK_CLOCK_HOURS",
    "load_draft_settings",
    "save_draft_settings",
]
