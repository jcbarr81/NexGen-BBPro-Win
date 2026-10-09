"""League rating centres: where a league's "average" sits on a rating scale.

Audit 2026-10-06 decision 2: a frequency term the engine adds to a
league-calibrated rate (the steal attempt factor, the infield-hit term, the
batter-speed double-play term) reads a rating against the league's own mean,
not against an absolute 50, so the league's overall rate does not move with
how its ratings happen to be distributed.

Release 4 (W0) adds the first of these centres, the mean speed (``sp``) of
the league's active-roster (ACT) hitters. It is the single source of the
``hitter_speed_center`` tuning key (default 50.0): every path that builds a
live game's tuning -- ``playbalance.game_runner`` (and through it the
parallel-day workers, the playoffs and the exhibition), the watch-a-game
socket and the KPI harness -- layers :func:`get_rating_center_overrides`
into its overrides.

The value is computed once per season and stored in
``<league data dir>/rating_centers.json`` plus a process cache, following
the pitcher durability centre in ``services.injury_settings``: it never moves
mid-season, and serial runs, parallel workers and a fresh Cloud Run instance
all read the same number. The working-copy push carries the file to the
durable mount like any other league file. A new season is a new key, so the
first game of the next season recomputes it from that season's ACT rosters;
nothing needs resetting at rollover.
"""

from __future__ import annotations

import csv
from pathlib import Path
import threading
from typing import Dict, Optional

# Shared with the durability centre so both resolve the season, and read and
# write their per-season files, the same way.
from services.injury_settings import (
    _ROSTER_SIDE_SUFFIXES,
    _read_json,
    _season_key,
    _write_json_atomic,
)
from utils.path_utils import get_data_dir

__all__ = [
    "RATING_CENTERS_FILENAME",
    "HITTER_SPEED_CENTER_KEY",
    "active_hitter_mean_speed",
    "league_hitter_speed_center",
    "get_rating_center_overrides",
    "clear_rating_center_cache",
]

VERSION = 1
RATING_CENTERS_FILENAME = "rating_centers.json"
HITTER_SPEED_CENTER_KEY = "hitter_speed_center"
# Seasons kept in the file for reference; the current one rules.
_KEEP_SEASONS = 5
# The season key ``_season_key`` returns when the league has no schedule
# (between a rollover and the next schedule, or a directory that is not the
# active league). Such a value is computed fresh and never stored, so it can
# not pin a stale centre onto a later season that also lacks a date.
_UNKNOWN_SEASON = "default"

# (league dir, season, key) -> centre; the file is the source of truth.
_CENTER_CACHE: Dict[tuple, float] = {}
_CENTER_LOCK = threading.Lock()


def clear_rating_center_cache() -> None:
    """Drop the process cache (tests; the file stays the source of truth)."""

    with _CENTER_LOCK:
        _CENTER_CACHE.clear()


def get_rating_center_overrides() -> Dict[str, float]:
    """Tuning overrides carrying the current league's rating centres.

    ``{"hitter_speed_center": x}``, or ``{}`` when the league has no ACT
    hitters to average (the engine then keeps the 50.0 default).
    """

    try:
        center = league_hitter_speed_center()
    except Exception:  # pragma: no cover - defensive; a game must still run
        center = None
    if center is None:
        return {}
    return {HITTER_SPEED_CENTER_KEY: center}


def league_hitter_speed_center(
    data_dir: Path | str | None = None,
    season: str | int | None = None,
) -> Optional[float]:
    """Mean speed of the league's ACT hitters, fixed per season.

    Computed the first time a season asks for it and stored in
    ``<league>/rating_centers.json`` (decision 2: "computed once per
    season"). ``None`` when the league has no ACT hitters to average.
    """

    base = Path(data_dir) if data_dir is not None else get_data_dir()
    season_key = str(season) if season is not None else _season_key(base)
    if season_key == _UNKNOWN_SEASON:
        return active_hitter_mean_speed(base)
    cache_key = (str(base.resolve(strict=False)), season_key, HITTER_SPEED_CENTER_KEY)
    with _CENTER_LOCK:
        cached = _CENTER_CACHE.get(cache_key)
        if cached is not None:
            return cached
        path = base / RATING_CENTERS_FILENAME
        payload = _read_json(path)
        seasons = payload.get("seasons")
        if not isinstance(seasons, dict):
            seasons = {}
        entry = seasons.get(season_key)
        if not isinstance(entry, dict):
            entry = {}
        try:
            stored = entry.get(HITTER_SPEED_CENTER_KEY)
            value = float(stored) if stored is not None else None
        except (TypeError, ValueError):
            value = None
        if value is None:
            value = active_hitter_mean_speed(base)
            if value is None:
                return None
            seasons[season_key] = {**entry, HITTER_SPEED_CENTER_KEY: value}
            keep = sorted(seasons)[-_KEEP_SEASONS:]
            _write_json_atomic(
                path,
                {"version": VERSION, "seasons": {k: seasons[k] for k in keep}},
            )
        _CENTER_CACHE[cache_key] = value
        return value


def active_hitter_mean_speed(
    base: Path | str,
    *,
    players_path: Path | str | None = None,
) -> Optional[float]:
    """Average ``sp`` over every club's ACT non-pitchers, to 2 decimals.

    ``base`` holds ``rosters/`` (``<team>.csv`` rows of ``player_id,level``)
    and, unless ``players_path`` names another file, ``players.csv``.
    Pitchers (``utils.roster_rules.counts_as_pitcher``) and every non-ACT
    level are left out. A missing or blank ``sp`` counts as 50.
    """

    from utils.roster_rules import counts_as_pitcher

    base = Path(base)
    players = Path(players_path) if players_path is not None else base / "players.csv"
    roster_dir = base / "rosters"
    if not players.exists() or not roster_dir.is_dir():
        return None
    active = _active_player_ids(roster_dir)
    values: list[float] = []
    try:
        with players.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if str(row.get("player_id") or "").strip() not in active:
                    continue
                if counts_as_pitcher(row):
                    continue
                try:
                    values.append(float(row.get("sp") or 50.0))
                except (TypeError, ValueError):
                    values.append(50.0)
    except OSError:
        return None
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _active_player_ids(roster_dir: Path) -> set[str]:
    active: set[str] = set()
    for roster_file in sorted(roster_dir.glob("*.csv")):
        if roster_file.stem.endswith(_ROSTER_SIDE_SUFFIXES):
            continue  # <team>_pitching.csv and other side files
        try:
            with roster_file.open(newline="", encoding="utf-8") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 2 and row[1].strip().upper() == "ACT":
                        active.add(row[0].strip())
        except OSError:
            continue
    return active
