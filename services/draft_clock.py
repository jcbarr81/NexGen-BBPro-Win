"""The pick clock: how long an owner has before the CPU picks for him.

A draft with real owners in it stalls the moment one of them is unavailable,
and the rest of the league cannot do anything about it. So a team that goes on
the clock has a deadline; when it passes, the CPU makes the pick and the draft
moves on.

One duration covers the whole draft rather than a deadline set per pick, so
there is nothing for the commissioner to re-set between picks. ``0`` hours
turns the clock off and the draft waits indefinitely, which is how it behaved
before any of this existed.

CPU teams are never put on a clock: nobody is waiting on them, so they pick as
soon as anything advances the draft.

The clock lives in the draft state as ``{"team_id": ..., "since": <iso>}`` —
the team is stored alongside the timestamp so a stale clock from the previous
pick can never be read as the current one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

CLOCK_KEY = "clock"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def start(
    state: Dict[str, Any],
    team_id: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Put *team_id* on the clock as of now. Returns the mutated state."""

    token = str(team_id or "").strip().upper()
    if not token:
        state.pop(CLOCK_KEY, None)
        return state
    state[CLOCK_KEY] = {
        "team_id": token,
        "since": (now or _now()).isoformat(),
    }
    return state


def started_at(state: Dict[str, Any], team_id: Optional[str]) -> Optional[datetime]:
    """When *team_id* went on the clock, or ``None`` if the record is stale.

    A clock naming a different team belongs to a pick that has already been
    made, and must never be read as this team's.
    """

    clock = state.get(CLOCK_KEY)
    if not isinstance(clock, dict):
        return None
    token = str(team_id or "").strip().upper()
    if not token or str(clock.get("team_id", "")).strip().upper() != token:
        return None
    return _parse(clock.get("since"))


def ensure_started(
    state: Dict[str, Any],
    team_id: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    """Start the clock for *team_id* if it is not already running.

    Called on read as well as after a pick, so a draft that was mid-pick when
    this shipped still gets a clock rather than waiting forever.
    """

    existing = started_at(state, team_id)
    if existing is not None:
        return existing
    token = str(team_id or "").strip().upper()
    if not token:
        return None
    moment = now or _now()
    start(state, token, now=moment)
    return moment


def deadline(
    state: Dict[str, Any],
    team_id: Optional[str],
    pick_clock_hours: int,
) -> Optional[datetime]:
    """When *team_id* runs out of time, or ``None`` when no clock applies."""

    try:
        hours = int(pick_clock_hours or 0)
    except (TypeError, ValueError):
        hours = 0
    if hours <= 0:
        return None
    began = started_at(state, team_id)
    if began is None:
        return None
    return began + timedelta(hours=hours)


def is_expired(
    state: Dict[str, Any],
    team_id: Optional[str],
    pick_clock_hours: int,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """True when *team_id* has had its time and still has not picked."""

    due = deadline(state, team_id, pick_clock_hours)
    if due is None:
        return False
    return (now or _now()) >= due


def seconds_remaining(
    state: Dict[str, Any],
    team_id: Optional[str],
    pick_clock_hours: int,
    *,
    now: Optional[datetime] = None,
) -> Optional[int]:
    """Seconds left, floored at zero, or ``None`` when no clock applies."""

    due = deadline(state, team_id, pick_clock_hours)
    if due is None:
        return None
    return max(0, int((due - (now or _now())).total_seconds()))


def clear(state: Dict[str, Any]) -> Dict[str, Any]:
    state.pop(CLOCK_KEY, None)
    return state


__all__ = [
    "CLOCK_KEY",
    "clear",
    "deadline",
    "ensure_started",
    "is_expired",
    "seconds_remaining",
    "start",
    "started_at",
]
