"""Per-league draft configuration.

Stores the number of rounds and the pool size the commissioner wants for
the amateur draft, the pick clock, and when in the year the draft runs.
Read at league creation, overridable season-to-season from the Draft admin
tab. Persisted to ``<data_dir>/draft_settings.json``.
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

# When the amateur draft runs (backlog #63, owner decisions 2026-10-11).
# "midseason": the third Tuesday in July; the regular season pauses for it.
# "preseason": after the offseason and BEFORE spring training, so the draft
# class gets a training camp and no regular-season sim ever waits on a draft.
# A change applies to the next draft that has not been held yet; a league's
# first draft always follows its first completed season.
DRAFT_TIMING_MIDSEASON = "midseason"
DRAFT_TIMING_PRESEASON = "preseason"
DRAFT_TIMINGS = (DRAFT_TIMING_MIDSEASON, DRAFT_TIMING_PRESEASON)
DEFAULT_DRAFT_TIMING = DRAFT_TIMING_MIDSEASON

# How long the automatic scheduled run waits after the last pick of a draft
# before it may fill unready owner rosters and sim (owner decision
# 2026-10-11). Owners get this long with their draft class. 0 = no wait. The
# commissioner's own "Run now" is not held.
DEFAULT_POST_DRAFT_WAIT_HOURS = 24
MIN_POST_DRAFT_WAIT_HOURS = 0
MAX_POST_DRAFT_WAIT_HOURS = 336  # two weeks


@dataclass
class DraftSettings:
    rounds: int = DEFAULT_ROUNDS
    pool_size: int = DEFAULT_POOL_SIZE
    pick_clock_hours: int = DEFAULT_PICK_CLOCK_HOURS
    timing: str = DEFAULT_DRAFT_TIMING
    post_draft_wait_hours: int = DEFAULT_POST_DRAFT_WAIT_HOURS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rounds": int(self.rounds),
            "pool_size": int(self.pool_size),
            "pick_clock_hours": int(self.pick_clock_hours),
            "timing": normalize_timing(self.timing),
            "post_draft_wait_hours": int(self.post_draft_wait_hours),
        }


def normalize_timing(value: Any) -> str:
    """A stored or submitted timing as one of DRAFT_TIMINGS (default on junk)."""

    text = str(value or "").strip().lower().replace("-", "").replace("_", "")
    for timing in DRAFT_TIMINGS:
        if text == timing:
            return timing
    return DEFAULT_DRAFT_TIMING


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
    if not isinstance(payload, dict):
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
    wait = _clamp(
        payload.get("post_draft_wait_hours", DEFAULT_POST_DRAFT_WAIT_HOURS),
        MIN_POST_DRAFT_WAIT_HOURS,
        MAX_POST_DRAFT_WAIT_HOURS,
        DEFAULT_POST_DRAFT_WAIT_HOURS,
    )
    return DraftSettings(
        rounds=rounds,
        pool_size=pool,
        pick_clock_hours=clock,
        timing=normalize_timing(payload.get("timing")),
        post_draft_wait_hours=wait,
    )


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
    wait = _clamp(
        settings.post_draft_wait_hours,
        MIN_POST_DRAFT_WAIT_HOURS,
        MAX_POST_DRAFT_WAIT_HOURS,
        DEFAULT_POST_DRAFT_WAIT_HOURS,
    )
    normalized = DraftSettings(
        rounds=rounds,
        pool_size=pool,
        pick_clock_hours=clock,
        timing=normalize_timing(settings.timing),
        post_draft_wait_hours=wait,
    )
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
    "DEFAULT_POST_DRAFT_WAIT_HOURS",
    "MIN_POST_DRAFT_WAIT_HOURS",
    "MAX_POST_DRAFT_WAIT_HOURS",
    "DRAFT_TIMING_MIDSEASON",
    "DRAFT_TIMING_PRESEASON",
    "DRAFT_TIMINGS",
    "DEFAULT_DRAFT_TIMING",
    "normalize_timing",
    "load_draft_settings",
    "save_draft_settings",
]
