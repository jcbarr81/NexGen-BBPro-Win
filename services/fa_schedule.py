"""Per-day deadline for the free-agency bidding window.

The FA window (:mod:`services.fa_window`) is a 14-day offseason auction that the
commissioner advances one day at a time. Before this, it had no real-world
clock: owners had no idea when their bids were due, and nothing advanced the
day if the commissioner went quiet — one inactive person stalled the league.
This module adds that clock.

It is deliberately SEPARATE from ``fa_window``. That service mutates real league
data (negotiations, contracts, payroll, rosters), so the deadline layer never
reaches into it — it keeps its own small config file, reads the window's public
status, and calls the existing public ``advance_day``. A league with no
``fa_window_schedule.json`` reads as "no deadline, auto-advance off" and behaves
exactly as it did before, so this cannot disturb leagues already in flight.

Config (all optional, per league):
    deadline       ISO-8601 UTC instant the CURRENT window day is due
    auto_advance   fire without a commissioner click once the deadline passes
    advance_hours  how long each window day gets (default 24)

Unlike the season progression schedule, a passed FA deadline does NOT CPU-fill
or block: choosing not to bid is a legitimate move, and there is no sensible way
to invent a bid for someone. The day simply advances and ``waiting`` is surfaced
to the commissioner as information.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from utils.path_utils import get_data_dir

FILENAME = "fa_window_schedule.json"

# A window day must be at least an hour (so a typo can't spin the window shut)
# and at most a fortnight.
MIN_ADVANCE_HOURS = 1
MAX_ADVANCE_HOURS = 24 * 14
DEFAULT_ADVANCE_HOURS = 24


def _path(data_dir: Path | str | None = None) -> Path:
    base = get_data_dir() if data_dir is None else Path(data_dir)
    return Path(base) / FILENAME


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_utc(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 string to an aware UTC datetime, else ``None``."""
    s = str(value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coerce_hours(value: Any) -> int:
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return DEFAULT_ADVANCE_HOURS
    return max(MIN_ADVANCE_HOURS, min(MAX_ADVANCE_HOURS, hours))


def read_schedule(*, data_dir: Path | str | None = None) -> Dict[str, Any]:
    """The stored config, normalized. Missing/corrupt file → safe defaults with
    ``auto_advance`` OFF, so an un-configured league never fires."""
    path = _path(data_dir)
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "deadline": str(data.get("deadline") or "").strip() or None,
        "auto_advance": bool(data.get("auto_advance", False)),
        "advance_hours": _coerce_hours(data.get("advance_hours")),
    }


def write_schedule(sched: Dict[str, Any], *, data_dir: Path | str | None = None) -> None:
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "deadline": sched.get("deadline") or None,
                "auto_advance": bool(sched.get("auto_advance", False)),
                "advance_hours": _coerce_hours(sched.get("advance_hours")),
            }
        ),
        encoding="utf-8",
    )


def set_schedule(
    *,
    deadline: Any = None,
    auto_advance: Any = None,
    advance_hours: Any = None,
    data_dir: Path | str | None = None,
) -> Dict[str, Any]:
    """Merge a partial update into the stored config. ``deadline=""`` clears it."""
    sched = read_schedule(data_dir=data_dir)
    if deadline is not None:
        text = str(deadline or "").strip()
        if not text:
            sched["deadline"] = None
        else:
            dt = parse_iso_utc(text)
            if dt is None:
                raise ValueError("deadline must be an ISO-8601 date/time.")
            sched["deadline"] = dt.isoformat()
    if auto_advance is not None:
        sched["auto_advance"] = bool(auto_advance)
    if advance_hours is not None:
        sched["advance_hours"] = _coerce_hours(advance_hours)
    write_schedule(sched, data_dir=data_dir)
    return sched


def clear(*, data_dir: Path | str | None = None) -> Dict[str, Any]:
    """Drop the deadline but keep the cadence/toggle (the window closed)."""
    sched = read_schedule(data_dir=data_dir)
    sched["deadline"] = None
    write_schedule(sched, data_dir=data_dir)
    return sched


def next_deadline_from_now(
    advance_hours: int, *, reference: Optional[datetime] = None
) -> str:
    """The next due time, measured from NOW rather than from the old deadline.

    Measuring from now is the safety property that matters: if a deadline sat
    unfired for a week, rolling it forward one cadence at a time would leave it
    still in the past and the window would burn through every remaining day in
    consecutive ticks. From now, each advance buys a full cadence no matter how
    stale the clock was.
    """
    ref = reference or now_utc()
    return (ref + timedelta(hours=_coerce_hours(advance_hours))).isoformat()


def roll_after_advance(
    *, closed: bool = False, data_dir: Path | str | None = None
) -> Optional[str]:
    """Re-arm the clock after a day was advanced. Returns the new deadline.

    A closed window clears the deadline (nothing left to be due). A league that
    never set a deadline stays un-armed — advancing manually must not silently
    opt someone into a schedule they never configured.
    """
    sched = read_schedule(data_dir=data_dir)
    if closed:
        sched["deadline"] = None
    elif sched["deadline"]:
        sched["deadline"] = next_deadline_from_now(sched["advance_hours"])
    else:
        return None
    write_schedule(sched, data_dir=data_dir)
    return sched["deadline"]


def schedule_view(
    *, window_open: bool = False, data_dir: Path | str | None = None
) -> Dict[str, Any]:
    """UI-facing status: the config plus a computed countdown."""
    sched = read_schedule(data_dir=data_dir)
    dt = parse_iso_utc(sched["deadline"])
    now = now_utc()
    past_due = bool(dt and now >= dt)
    return {
        **sched,
        "deadline_utc": dt.isoformat() if dt else None,
        "is_scheduled": dt is not None,
        "past_due": past_due,
        "seconds_remaining": int((dt - now).total_seconds()) if dt else None,
        # Only an OPEN window can actually fire; a closed one is inert.
        "will_auto_advance": bool(sched["auto_advance"] and dt is not None and window_open),
    }


def is_due(*, data_dir: Path | str | None = None) -> bool:
    """Should an auto-advance fire right now (config-wise)? Callers must also
    confirm the window is open and that no sim holds the global lock."""
    sched = read_schedule(data_dir=data_dir)
    if not sched["auto_advance"]:
        return False
    dt = parse_iso_utc(sched["deadline"])
    return bool(dt and now_utc() >= dt)
