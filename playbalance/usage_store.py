"""Per-league, persisted physics rest state (audit M18, Release 3).

The physics engine's pitcher and batter rest state (``UsageState``: fatigue
debt, last day used, consecutive days, appearances) used to live only in
``playbalance.game_runner`` module globals. A new process -- a cold Cloud Run
instance, the "Sim day" button, a scheduled one-day run, a sim right after
another league's -- started it empty, so a league simmed one day per process
had no reliever rest gating at all.

This module keeps one state per league data dir, in memory and on disk:

* File ``<league data dir>/physics_usage.json``::

      {"version": 1, "season_year": 2026, "season_start": "2026-04-01",
       "last_date": "2026-05-12", "last_day": 37, "usage": {...}}

  written atomically (tmp file + ``os.replace``).
* :func:`context` returns ``(state, day)`` for a game date. ``day`` is the
  rest clock handed to the engine: the 0-based index of the game date in the
  season (each new date the league plays is one more day). Opening Day is
  day 0. A date in a new year, or a date before the last one simmed (a reset
  or a re-sim), starts a fresh season state; the backwards case is logged.
* Saves follow the pitcher tracker: :func:`mark_dirty` after each game saves
  at once, unless a :func:`deferred_saves` block is open, which saves once at
  exit. ``SeasonSimulator.simulate_next_day`` opens one per sim day.
* With no file yet (a league that simmed before this release), the first
  context replays this season's recent appearances from
  ``pitcher_recovery.json`` so relievers who pitched in the last two weeks are
  not all fresh. Batters start fresh. It is approximate: appearance counts
  only cover those two weeks.

Parallel-day workers never touch the store: they get the state in their
payload and the parent merges the results into the cached state, then marks
it dirty.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

from physics_sim.usage import (
    UsageState,
    usage_state_from_dict,
    usage_state_to_dict,
)

logger = logging.getLogger(__name__)

FILENAME = "physics_usage.json"
FILE_VERSION = 1
TRACKER_FILENAME = "pitcher_recovery.json"

_LOCK = threading.RLock()


class _LeagueUsage:
    """One league's cached rest state."""

    __slots__ = (
        "path",
        "loaded",
        "state",
        "season_year",
        "season_start",
        "last_date",
        "last_day",
        "dirty",
        "defer_depth",
    )

    def __init__(self, path: Path) -> None:
        self.path = path
        self.loaded = False
        self.state: Optional[UsageState] = None
        self.season_year: Optional[int] = None
        self.season_start: Optional[date] = None
        self.last_date: Optional[date] = None
        self.last_day: Optional[int] = None
        self.dirty = False
        self.defer_depth = 0


_CACHE: Dict[str, _LeagueUsage] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _data_dir(data_dir: str | Path | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    from utils.path_utils import get_data_dir

    return get_data_dir()


def usage_path(data_dir: str | Path | None = None) -> Path:
    """Return the league's ``physics_usage.json`` path."""

    return _data_dir(data_dir) / FILENAME


def _parse_date(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    token = str(value).strip()[:10]
    if not token:
        return None
    try:
        return date.fromisoformat(token)
    except ValueError:
        return None


def _entry(data_dir: str | Path | None = None) -> _LeagueUsage:
    """Return (creating, not loading) the cache entry for a league dir."""

    path = usage_path(data_dir)
    key = str(path.resolve(strict=False))
    entry = _CACHE.get(key)
    if entry is None:
        entry = _LeagueUsage(path)
        _CACHE[key] = entry
    return entry


def _day_for(entry: _LeagueUsage, when: date) -> int:
    """Rest-clock day for *when* (the game-date clock: one day per new date)."""

    if entry.last_date is None or entry.last_day is None:
        return 0
    if when == entry.last_date:
        return entry.last_day
    return entry.last_day + 1


def _start_season(entry: _LeagueUsage, when: date) -> None:
    entry.state = UsageState()
    entry.season_year = when.year
    entry.season_start = when
    entry.last_date = None
    entry.last_day = None


# ---------------------------------------------------------------------------
# Load / bootstrap / save
# ---------------------------------------------------------------------------
def _load(entry: _LeagueUsage, when: date) -> None:
    """Fill *entry* from disk, or bootstrap it from the pitcher tracker."""

    entry.loaded = True
    try:
        raw = json.loads(entry.path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _bootstrap_from_tracker(entry, when)
        return
    except (OSError, ValueError) as exc:
        logger.warning("physics usage: unreadable %s (%s); starting fresh", entry.path, exc)
        return
    if not isinstance(raw, dict) or raw.get("version") != FILE_VERSION:
        logger.warning("physics usage: unknown format in %s; starting fresh", entry.path)
        return
    season_start = _parse_date(raw.get("season_start"))
    last_date = _parse_date(raw.get("last_date"))
    try:
        season_year = int(raw.get("season_year"))
    except (TypeError, ValueError):
        season_year = season_start.year if season_start else None
    last_day = raw.get("last_day")
    if season_start is None or season_year is None:
        return
    entry.state = usage_state_from_dict(raw.get("usage"))
    entry.season_year = season_year
    entry.season_start = season_start
    entry.last_date = last_date
    entry.last_day = int(last_day) if isinstance(last_day, int) else None


def _bootstrap_from_tracker(entry: _LeagueUsage, when: date) -> None:
    """Rebuild pitcher rest from this season's ``pitcher_recovery.json``.

    Replays every recorded appearance from this year that is before *when*
    (the tracker keeps about two weeks) through ``advance_day`` and
    ``record_outing``, so relievers who pitched yesterday are not fresh on the
    first sim after this release. Batters start fresh.
    """

    tracker_path = entry.path.parent / TRACKER_FILENAME
    try:
        raw = json.loads(tracker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    teams = raw.get("teams") if isinstance(raw, dict) else None
    if not isinstance(teams, dict):
        return
    outings: list[tuple[date, str, int]] = []
    for team in teams.values():
        pitchers = team.get("pitchers") if isinstance(team, dict) else None
        if not isinstance(pitchers, dict):
            continue
        for pid, status in pitchers.items():
            recent = status.get("recent") if isinstance(status, dict) else None
            for item in recent or []:
                if not isinstance(item, dict) or not item.get("appeared"):
                    continue
                if item.get("warmed_only"):
                    continue
                played = _parse_date(item.get("date"))
                if played is None or played >= when or played.year != when.year:
                    continue
                try:
                    pitches = int(item.get("pitches") or 0)
                except (TypeError, ValueError):
                    continue
                if pitches > 0:
                    outings.append((played, str(pid), pitches))
    if not outings:
        return

    from physics_sim.config import load_tuning

    overrides = None
    try:
        from services.physics_tuning_settings import get_physics_tuning_overrides

        overrides = get_physics_tuning_overrides()
    except Exception:
        overrides = None
    tuning = load_tuning(overrides=overrides or None)
    durability = _pitcher_durability(entry.path.parent)

    class _Arm:
        __slots__ = ("player_id", "durability")

        def __init__(self, player_id: str) -> None:
            self.player_id = player_id
            self.durability = durability.get(player_id, 50.0)

    outings.sort()
    dates = sorted({played for played, _, _ in outings})
    _start_season(entry, dates[0])
    state = entry.state
    assert state is not None
    for played in dates:
        day = _day_for(entry, played)
        todays = [(pid, pitches) for d, pid, pitches in outings if d == played]
        state.advance_day(
            day=day, pitchers=[_Arm(pid) for pid, _ in todays], tuning=tuning
        )
        for pid, pitches in todays:
            state.record_outing(
                pitcher_id=pid, pitches=pitches, day=day, multiplier=1.0, tuning=tuning
            )
        entry.last_date = played
        entry.last_day = day
    logger.info(
        "physics usage: bootstrapped %d outings over %d dates from %s",
        len(outings),
        len(dates),
        tracker_path,
    )


def _pitcher_durability(data_dir: Path) -> Dict[str, float]:
    try:
        from physics_sim.data_loader import load_players_by_id

        _, pitchers = load_players_by_id(data_dir / "players.csv")
    except Exception:
        return {}
    out: Dict[str, float] = {}
    for pid, ratings in pitchers.items():
        try:
            out[str(pid)] = float(getattr(ratings, "durability", 50.0) or 50.0)
        except (TypeError, ValueError):
            out[str(pid)] = 50.0
    return out


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows: a reader (or a sync client) briefly holds the target.
            if attempt == 4:
                break
            time.sleep(0.05 * (attempt + 1))
    try:
        path.write_text(text, encoding="utf-8")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _save(entry: _LeagueUsage) -> None:
    entry.dirty = False
    if entry.state is None or entry.season_start is None:
        return
    payload = {
        "version": FILE_VERSION,
        "season_year": entry.season_year,
        "season_start": entry.season_start.isoformat(),
        "last_date": entry.last_date.isoformat() if entry.last_date else None,
        "last_day": entry.last_day,
        "usage": usage_state_to_dict(entry.state),
    }
    try:
        _write_atomic(entry.path, json.dumps(payload, separators=(",", ":")))
    except OSError as exc:  # pragma: no cover - persistence is best effort
        logger.warning("physics usage: could not save %s (%s)", entry.path, exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def context(
    date_token: object, *, data_dir: str | Path | None = None
) -> Tuple[Optional[UsageState], Optional[int]]:
    """Return ``(state, day)`` for a game on *date_token* in the active league.

    ``(None, None)`` for an undated game (or a token that is not a date), which
    turns the engine's rest gating off for it, as before.
    """

    if not date_token:
        return None, None
    when = _parse_date(date_token)
    if when is None:
        logger.debug("physics usage: ignoring non-date token %r", date_token)
        return None, None
    with _LOCK:
        entry = _entry(data_dir)
        if not entry.loaded:
            _load(entry, when)
        if entry.state is None:
            _start_season(entry, when)
        elif entry.season_year != when.year:
            _start_season(entry, when)
        elif entry.last_date is not None and when < entry.last_date:
            logger.warning(
                "physics usage: %s is before the last simmed date %s in %s; "
                "rest state reset",
                when.isoformat(),
                entry.last_date.isoformat(),
                entry.path.parent,
            )
            _start_season(entry, when)
        day = _day_for(entry, when)
        entry.last_date = when
        entry.last_day = day
        return entry.state, day


def mark_dirty(*, data_dir: str | Path | None = None) -> None:
    """Note that the league's state changed: save now, or at the end of the
    open :func:`deferred_saves` block."""

    with _LOCK:
        entry = _entry(data_dir)
        if entry.state is None:
            return
        entry.dirty = True
        if entry.defer_depth == 0:
            _save(entry)


def save_if_dirty(*, data_dir: str | Path | None = None) -> bool:
    """Save the league's state if it changed since the last save."""

    with _LOCK:
        entry = _entry(data_dir)
        if not entry.dirty:
            return False
        _save(entry)
        return True


@contextmanager
def deferred_saves(*, data_dir: str | Path | None = None) -> Iterator[None]:
    """Batch saves for the league: one write when the outermost block exits.

    Re-entrant; inner blocks are no-ops. The save runs in ``finally`` so a sim
    day that fails part-way keeps the games it did play.
    """

    with _LOCK:
        entry = _entry(data_dir)
        entry.defer_depth += 1
    try:
        yield
    finally:
        with _LOCK:
            entry.defer_depth -= 1
            if entry.defer_depth == 0 and entry.dirty:
                _save(entry)


def reset(*, data_dir: str | Path | None = None) -> None:
    """Forget the league's rest state and delete its file (league reset)."""

    with _LOCK:
        entry = _entry(data_dir)
        entry.loaded = True
        entry.state = None
        entry.season_year = None
        entry.season_start = None
        entry.last_date = None
        entry.last_day = None
        entry.dirty = False
        try:
            entry.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:  # pragma: no cover - best effort
            logger.warning("physics usage: could not delete %s (%s)", entry.path, exc)


def clear_cache() -> None:
    """Drop every in-memory state without saving (what a new process sees)."""

    with _LOCK:
        _CACHE.clear()


__all__ = [
    "FILENAME",
    "clear_cache",
    "context",
    "deferred_saves",
    "mark_dirty",
    "reset",
    "save_if_dirty",
    "usage_path",
]
