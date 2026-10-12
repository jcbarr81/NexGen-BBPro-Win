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

Release 4 (F4) adds the battery centres the running-game terms read (the
steal attempt deterrents and success logit, the wild-pitch / passed-ball
rates and the dropped third strike): the mean ``control``, ``hold_runner``
and ``arm`` of the ACT pitchers and the mean ``arm`` and ``fa`` of the ACT
catchers (primary position C). The calibration fixtures' batteries sit well
above 50 while a real league's sit at 50, so terms calibrated on raw
``r - 50`` ran a live league far hotter than the fixtures. The battery
centres share the file, the season key and the cache; a file written before
F4 (speed only) gets the missing centres computed and added for the same
season without touching its stored speed centre. A league with no ACT
catcher (or pitcher) leaves those keys out and the engine keeps the 50.0
default for them.

Release 5a adds the centres the Release 5 plate-discipline, contact and
platoon terms will read, with nothing reading them yet: the ACT hitters'
mean Contact (``ch``) and Eye, the ACT pitchers' mean ``movement`` and mean
pitch grade (each pitcher's average over the pitches he throws), the ACT
hitters' mean ``vl`` by batting side (L / R / S) and the share of ACT
hitters batting from each side. They ride in the same file, season key and
cache, so a file written before 5a gains them for the same season without
any stored value changing. The three shares are not centres -- their
tuning default is 0.0, "unknown" -- but are fixed, stored and delivered the
same way.

Release 5b adds the season's ENGINE GENERATION to the same entry
(``engine_generation``): which engine the season is played on
(``physics_sim.engine_generation``). It lives here, not in a file of its
own, because it has the centres' lifetime exactly -- fixed when the season
starts, read by every process, carried by a league copy, a backup and the
working-copy push -- and because "this season already has an entry" is the
fact that keeps a season on the engine it started on:

* an entry with a generation plays that generation for the whole season;
* an entry WITHOUT one is a legacy season: it was written before
  generations existed, when the season was already under way on today's
  engine, or it belongs to a season that started legacy. Legacy is never
  written down, so a legacy league's file is byte for byte what it is today;
* a season with no entry yet gets the new generation only if none of its
  regular-season games has been played (:func:`_season_has_started`), else
  the engine it has been playing on. A new generation is written with the
  entry, whoever creates the entry (this module is the file's only writer).

So nothing changes for a league at deploy; it moves to the new engine when
its next season starts, and a league created after the deploy starts on it.
"""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
import threading
from typing import Dict, Iterable, Optional

from physics_sim.engine_generation import (
    CURRENT_ENGINE_GENERATION,
    LEGACY_ENGINE_GENERATION,
    engine_profile,
    known_engine_generations,
    normalize_engine_generation,
)

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
    "PITCHER_CONTROL_CENTER_KEY",
    "PITCHER_HOLD_CENTER_KEY",
    "PITCHER_ARM_CENTER_KEY",
    "CATCHER_ARM_CENTER_KEY",
    "CATCHER_FA_CENTER_KEY",
    "HITTER_CONTACT_CENTER_KEY",
    "HITTER_EYE_CENTER_KEY",
    "PITCHER_MOVEMENT_CENTER_KEY",
    "PITCHER_GRADE_CENTER_KEY",
    "HITTER_VL_CENTER_KEYS",
    "HITTER_BATS_SHARE_KEYS",
    "RATING_CENTER_KEYS",
    "ENGINE_GENERATION_KEY",
    "NEW_SEASON_ENGINE_ENV",
    "ENGINE_SWITCH_NEWS",
    "league_engine_generation",
    "get_league_engine_generation",
    "active_hitter_mean_speed",
    "active_rating_centers",
    "league_hitter_speed_center",
    "league_rating_centers",
    "get_rating_center_overrides",
    "clear_rating_center_cache",
]

VERSION = 1
RATING_CENTERS_FILENAME = "rating_centers.json"
HITTER_SPEED_CENTER_KEY = "hitter_speed_center"
PITCHER_CONTROL_CENTER_KEY = "pitcher_control_center"
PITCHER_HOLD_CENTER_KEY = "pitcher_hold_center"
PITCHER_ARM_CENTER_KEY = "pitcher_arm_center"
CATCHER_ARM_CENTER_KEY = "catcher_arm_center"
CATCHER_FA_CENTER_KEY = "catcher_fa_center"
HITTER_CONTACT_CENTER_KEY = "hitter_contact_center"
HITTER_EYE_CENTER_KEY = "hitter_eye_center"
PITCHER_MOVEMENT_CENTER_KEY = "pitcher_movement_center"
PITCHER_GRADE_CENTER_KEY = "pitcher_grade_center"
# Batting side -> tuning key: the ACT hitters' mean ``vl`` on that side, and
# the share of ACT hitters who bat from it (the three shares sum to 1).
HITTER_VL_CENTER_KEYS: Dict[str, str] = {
    "L": "hitter_vl_center_l",
    "R": "hitter_vl_center_r",
    "S": "hitter_vl_center_s",
}
HITTER_BATS_SHARE_KEYS: Dict[str, str] = {
    "L": "hitter_bats_share_l",
    "R": "hitter_bats_share_r",
    "S": "hitter_bats_share_s",
}
# A side with fewer ACT hitters than this reads the all-hitter ``vl`` mean:
# a handful of switch hitters is not a centre.
_VL_SIDE_MIN_HITTERS = 10
# tuning key -> (ACT group, players.csv column). "hitter" is every ACT
# non-pitcher, "pitcher" every ACT ``counts_as_pitcher`` row and "catcher"
# the ACT non-pitchers whose primary position is C.
_CENTER_SPECS: Dict[str, tuple[str, str]] = {
    HITTER_SPEED_CENTER_KEY: ("hitter", "sp"),
    PITCHER_CONTROL_CENTER_KEY: ("pitcher", "control"),
    PITCHER_HOLD_CENTER_KEY: ("pitcher", "hold_runner"),
    PITCHER_ARM_CENTER_KEY: ("pitcher", "arm"),
    CATCHER_ARM_CENTER_KEY: ("catcher", "arm"),
    CATCHER_FA_CENTER_KEY: ("catcher", "fa"),
    HITTER_CONTACT_CENTER_KEY: ("hitter", "ch"),
    # A blank Eye reads as the hitter's Contact (``_eye_rating``).
    HITTER_EYE_CENTER_KEY: ("hitter", "eye"),
    PITCHER_MOVEMENT_CENTER_KEY: ("pitcher", "movement"),
}
# The Release 4 keys first, in their stored order; the 5a keys follow.
RATING_CENTER_KEYS: tuple[str, ...] = (
    tuple(_CENTER_SPECS)
    + (PITCHER_GRADE_CENTER_KEY,)
    + tuple(HITTER_VL_CENTER_KEYS.values())
    + tuple(HITTER_BATS_SHARE_KEYS.values())
)
# Seasons kept in the file for reference; the current one rules.
_KEEP_SEASONS = 5
# The season key ``_season_key`` returns when the league has no schedule
# (between a rollover and the next schedule, or a directory that is not the
# active league). Such a value is kept in the process cache only -- so serial
# and parallel games in one run see the same number even if an injury
# reshuffles an ACT roster mid-day -- and never written to the file, so it
# can not pin a stale centre onto a later season that also lacks a date.
_UNKNOWN_SEASON = "default"

# (league dir, season, key) -> centre; the file is the source of truth.
_CENTER_CACHE: Dict[tuple, float] = {}
_CENTER_LOCK = threading.Lock()

# The season entry's engine generation (see the module docstring).
ENGINE_GENERATION_KEY = "engine_generation"
# Operations switch: the generation a season that has not started is given
# (default: the current one). Set to the legacy generation to hold every
# league on today's engine without a code change; a season that already has
# a generation is never moved by it.
NEW_SEASON_ENGINE_ENV = "NEXGEN_NEW_SEASON_ENGINE"
# The league news item logged once, when a league that has played a season
# before starts one on generation 5.
ENGINE_SWITCH_NEWS = (
    "The league now plays on the updated game engine, starting this season. "
    "Strikeouts, walks and contact are sharper skills, home teams have a "
    "small edge, and managers now issue intentional walks."
)
# (league dir, season) -> generation last read from or written to the file.
# Used only when the file cannot be read (see ``_generation_locked``).
_GENERATION_CACHE: Dict[tuple, int] = {}
_LOGGER = logging.getLogger(__name__)


def clear_rating_center_cache() -> None:
    """Drop the process cache (tests; the file stays the source of truth)."""

    with _CENTER_LOCK:
        _CENTER_CACHE.clear()
        _GENERATION_CACHE.clear()


def get_league_engine_generation(*, store: bool = True) -> int:
    """The engine generation of the current league's season; never raises.

    ``store`` False is for everything that is not a season game or a saved
    setting (a page load, a lineup action, watch-a-game): it reads the
    season's generation, or works out the one the season will get, without
    fixing it.
    """

    try:
        return league_engine_generation(store=store)
    except Exception:  # pragma: no cover - defensive; a game must still run
        _LOGGER.exception("engine generation lookup failed; using legacy")
        return LEGACY_ENGINE_GENERATION


def league_engine_generation(
    data_dir: Path | str | None = None,
    season: str | int | None = None,
    *,
    store: bool = True,
) -> int:
    """The engine generation of a league's season, fixed for the season.

    The rules are in the module docstring. A league with no schedule has no
    season to fix anything for: the active league (an offseason, a league
    being created) reads the generation its next season will get, nothing
    stored; any other directory (a fixture, a tools folder) is legacy.
    ``data_dir`` other than the active league is read by its own schedule.
    With ``store`` False nothing is written.
    """

    base = Path(data_dir) if data_dir is not None else get_data_dir()
    season_key = str(season) if season is not None else _engine_season_key(base)
    with _CENTER_LOCK:
        generation, announce = _generation_locked(base, season_key, store=store)
    if announce:
        _announce_engine_switch(base)
    return generation


def get_rating_center_overrides(*, store: bool = True) -> Dict[str, float]:
    """Tuning overrides carrying the current league's rating centres.

    Every centre the league can average (and, since Release 5a, its
    batting-side shares), keyed as ``RATING_CENTER_KEYS``
    (``{"hitter_speed_center": x, "pitcher_control_center": y, ...}``). A
    centre with nothing to average (no ACT hitters, pitchers or catchers) is
    left out, and the engine keeps its 50.0 default; ``{}`` when there is
    nothing at all. ``store`` False is for games that are not part of the
    season (watch-a-game): they read stored centres but never fix one, so a
    preseason replay cannot pin the season's centres from training-camp
    rosters.
    """

    try:
        return league_rating_centers(store=store)
    except Exception:  # pragma: no cover - defensive; a game must still run
        return {}


def league_rating_centers(
    data_dir: Path | str | None = None,
    season: str | int | None = None,
    *,
    store: bool = True,
) -> Dict[str, float]:
    """Every rating centre the league can average, fixed per season.

    The rules of :func:`league_hitter_speed_center`, key by key: a centre
    already stored for the season is read and never recomputed, and only the
    missing ones are computed from the current ACT rosters and added (so a
    file written before the battery centres existed keeps its speed centre).
    """

    return _league_centers(data_dir, season, RATING_CENTER_KEYS, store=store)


def league_hitter_speed_center(
    data_dir: Path | str | None = None,
    season: str | int | None = None,
    *,
    store: bool = True,
) -> Optional[float]:
    """Mean speed of the league's ACT hitters, fixed per season.

    Computed the first time a season asks for it and stored in
    ``<league>/rating_centers.json`` (decision 2: "computed once per
    season"). ``None`` when the league has no ACT hitters to average. With
    ``store`` False a stored or cached value is returned as usual, but a
    missing one is computed live and neither cached nor written.
    """

    centres = _league_centers(
        data_dir, season, (HITTER_SPEED_CENTER_KEY,), store=store
    )
    return centres.get(HITTER_SPEED_CENTER_KEY)


def _league_centers(
    data_dir: Path | str | None,
    season: str | int | None,
    keys: Iterable[str],
    *,
    store: bool,
) -> Dict[str, float]:
    """The centres in ``keys``: cache, then the season's file, then computed.

    Only keys missing from both are computed, and (``store``, known season)
    merged into the season's stored entry; a stored centre is never
    recomputed. A key with nothing to average is left out.
    """

    base = Path(data_dir) if data_dir is not None else get_data_dir()
    season_key = str(season) if season is not None else _season_key(base)
    announce: list[bool] = []
    with _CENTER_LOCK:
        centres = _league_centers_locked(
            base, season_key, tuple(keys), store=store, announce=announce
        )
    if announce:
        _announce_engine_switch(base)
    return centres


def _league_centers_locked(
    base: Path,
    season_key: str,
    keys: tuple[str, ...],
    *,
    store: bool,
    announce: list[bool],
) -> Dict[str, float]:
    """:func:`_league_centers` with ``_CENTER_LOCK`` held.

    ``announce`` gets one item when this call created the season's entry on
    a new engine generation and the league should be told (the caller logs
    the news after releasing the lock).
    """

    root = str(base.resolve(strict=False))
    found: Dict[str, float] = {}
    missing = []
    for key in keys:
        cached = _CENTER_CACHE.get((root, season_key, key))
        if cached is not None:
            found[key] = cached
        else:
            missing.append(key)
    if not missing:
        return _ordered(found, keys)
    if season_key == _UNKNOWN_SEASON:
        computed = _computed(base, missing)
        found.update(computed)
        if store:
            for key, value in computed.items():
                _CENTER_CACHE[(root, season_key, key)] = value
        return _ordered(found, keys)
    path = base / RATING_CENTERS_FILENAME
    payload = _read_json(path)
    seasons = payload.get("seasons")
    if not isinstance(seasons, dict):
        seasons = {}
    entry = seasons.get(season_key)
    new_entry = not isinstance(entry, dict)
    if new_entry:
        entry = {}
    unstored = []
    for key in missing:
        value = _stored_value(entry, key)
        if value is None:
            unstored.append(key)
            continue
        found[key] = value
        _CENTER_CACHE[(root, season_key, key)] = value
    if unstored:
        computed = _computed(base, unstored)
        found.update(computed)
        if computed and store:
            if new_entry:
                # The season's entry is being created here: its engine
                # generation is fixed with it (module docstring).
                generation = _new_season_generation(base, seasons)
                entry = _generation_entry(generation, seasons)
                _GENERATION_CACHE[(root, season_key)] = generation
                if _is_engine_switch(base, seasons, generation):
                    announce.append(True)
            seasons[season_key] = {**entry, **computed}
            keep = sorted(seasons)[-_KEEP_SEASONS:]
            _write_json_atomic(
                path,
                {"version": VERSION, "seasons": {k: seasons[k] for k in keep}},
            )
            for key, value in computed.items():
                _CENTER_CACHE[(root, season_key, key)] = value
    return _ordered(found, keys)


def _generation_locked(
    base: Path, season_key: str, *, store: bool
) -> tuple[int, bool]:
    """(generation, announce the switch) for a season; ``_CENTER_LOCK`` held."""

    if season_key == _UNKNOWN_SEASON and not _is_active_league(base):
        return LEGACY_ENGINE_GENERATION, False
    root = str(base.resolve(strict=False))
    path = base / RATING_CENTERS_FILENAME
    payload = _read_json(path)
    if not payload and path.exists():
        # The file is there but cannot be read (a disk or sync fault). Do
        # not decide a season's engine from that, and write nothing: use
        # what this process last saw, else what the rules give right now.
        cached = _GENERATION_CACHE.get((root, season_key))
        if cached is not None:
            return cached, False
        return _new_season_generation(base), False
    seasons = payload.get("seasons")
    if not isinstance(seasons, dict):
        seasons = {}
    if season_key == _UNKNOWN_SEASON:
        # No schedule, so no season to fix anything for: what the league's
        # next season will get (or, if results exist, what it plays now).
        return _new_season_generation(base, seasons), False
    entry = seasons.get(season_key)
    if isinstance(entry, dict):
        stored = entry.get(ENGINE_GENERATION_KEY)
        generation = (
            normalize_engine_generation(stored)
            if stored is not None
            # Written before generations existed: the season was already
            # under way on the legacy engine, and finishes on it.
            else LEGACY_ENGINE_GENERATION
        )
        _GENERATION_CACHE[(root, season_key)] = generation
        return generation, False
    generation = _new_season_generation(base, seasons)
    entry = _generation_entry(generation, seasons)
    if not store or not entry:
        # Legacy is the absence of a generation, so there is nothing to
        # write: a legacy league's file stays exactly as it is today. (Its
        # season is pinned by its first game, which creates the entry.)
        return generation, False
    announce = _is_engine_switch(base, seasons, generation)
    seasons[season_key] = entry
    keep = sorted(seasons)[-_KEEP_SEASONS:]
    _write_json_atomic(
        path, {"version": VERSION, "seasons": {k: seasons[k] for k in keep}}
    )
    _GENERATION_CACHE[(root, season_key)] = generation
    return generation, announce


def _new_season_generation(base: Path, seasons: dict | None = None) -> int:
    """The generation a season with no entry yet gets.

    The new generation if none of its regular-season games has been played.
    A season already under way keeps the engine it has been playing on: the
    generation of the newest season in ``seasons`` (the file's other
    entries), which is this same season when its key moved -- a schedule
    regenerated with another year -- and legacy when the file has never
    recorded one, the case of every league at deploy. A new generation whose
    profile cannot be loaded is not handed out (every game of the season
    would fail): the season starts on the legacy engine and the fault is
    logged.
    """

    if _season_has_started(base):
        return _newest_stored_generation(seasons or {})
    wanted = _configured_new_season_generation()
    if wanted <= LEGACY_ENGINE_GENERATION:
        return LEGACY_ENGINE_GENERATION
    try:
        engine_profile(wanted)
    except ValueError:
        _LOGGER.exception(
            "engine generation %s has no usable profile; season starts legacy",
            wanted,
        )
        return LEGACY_ENGINE_GENERATION
    return wanted


def _generation_entry(generation: int, seasons: dict) -> Dict[str, int]:
    """What a new season entry records of its generation.

    The number -- or nothing at all for the legacy engine in a file that
    has never recorded a generation (an entry without one IS legacy, and
    such a file stays as it is today). Once a league has a season on a
    later generation, a legacy season is written out too, so it can not
    inherit that generation (:func:`_newest_stored_generation`).
    """

    if generation <= LEGACY_ENGINE_GENERATION and not _records_generations(seasons):
        return {}
    return {ENGINE_GENERATION_KEY: generation}


def _records_generations(seasons: dict) -> bool:
    return any(
        isinstance(entry, dict) and entry.get(ENGINE_GENERATION_KEY) is not None
        for entry in seasons.values()
    )


def _newest_stored_generation(seasons: dict) -> int:
    """The generation of the highest season key in the file; legacy if the
    file has no season or that season has no generation."""

    known = [key for key, entry in seasons.items() if isinstance(entry, dict)]
    if not known:
        return LEGACY_ENGINE_GENERATION
    stored = seasons[max(known)].get(ENGINE_GENERATION_KEY)
    if stored is None:
        return LEGACY_ENGINE_GENERATION
    generation = normalize_engine_generation(stored)
    if generation not in known_engine_generations():
        return LEGACY_ENGINE_GENERATION
    return generation


def _configured_new_season_generation() -> int:
    raw = str(os.getenv(NEW_SEASON_ENGINE_ENV, "") or "").strip()
    if raw:
        try:
            wanted = int(raw)
        except ValueError:
            wanted = None
        if wanted in known_engine_generations():
            return wanted
        _LOGGER.warning(
            "%s=%r is not an engine generation", NEW_SEASON_ENGINE_ENV, raw
        )
    return CURRENT_ENGINE_GENERATION


def _season_has_started(base: Path) -> bool:
    """True when the league's current season has a regular-season result.

    Any one of: a schedule row marked played or carrying a result; a
    schedule cursor (``season_progress.json`` ``sim_index``) past the first
    day; a club with a win or a loss in ``standings.json``. Three sources
    because each can be wiped on its own mid-season -- a regenerated
    schedule has no played rows but leaves the cursor and the standings, a
    results reset leaves both -- while a rollover, a reset to Opening Day
    and a new league clear all three. Cached on the files' mtimes: a lineup
    action asks this for every club.
    """

    from utils.file_cache import cached_read

    schedule = base / "schedule.csv"
    progress = base / "season_progress.json"
    standings = base / "standings.json"
    return bool(
        cached_read(
            f"engine_generation_started|{base.resolve(strict=False)}",
            (schedule, progress, standings),
            lambda: _read_season_started(schedule, progress, standings),
        )
    )


def _read_season_started(schedule: Path, progress: Path, standings: Path) -> bool:
    try:
        with schedule.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if str(row.get("played") or "").strip() == "1":
                    return True
                if str(row.get("result") or "").strip():
                    return True
    except OSError:
        pass
    try:
        if int(_read_json(progress).get("sim_index") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    for record in _read_json(standings).values():
        if not isinstance(record, dict):
            continue
        for key in ("wins", "losses", "w", "l"):
            try:
                if float(record.get(key) or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _is_engine_switch(base: Path, seasons: dict, generation: int) -> bool:
    """True when a season starting on ``generation`` is the league's switch.

    The league has finished a season before (``career_index.json`` lists an
    archived one) and no season in the file was played on this generation
    or a later one. A league created on the new engine has nothing to be
    told.
    """

    if generation <= LEGACY_ENGINE_GENERATION:
        return False
    for entry in seasons.values():
        if not isinstance(entry, dict):
            continue
        stored = entry.get(ENGINE_GENERATION_KEY)
        if stored is not None and normalize_engine_generation(stored) >= generation:
            return False
    archived = _read_json(base / "career_index.json").get("seasons")
    return isinstance(archived, list) and bool(archived)


def _announce_engine_switch(base: Path) -> None:
    """Log :data:`ENGINE_SWITCH_NEWS` to the league's news feed (best effort)."""

    try:
        from utils.news_logger import log_news_event

        log_news_event(ENGINE_SWITCH_NEWS, file_path=base / "news_feed.txt")
    except Exception:  # pragma: no cover - news must never stop a game
        _LOGGER.exception("could not log the engine switch news item")


def _is_active_league(base: Path) -> bool:
    try:
        return base.resolve(strict=False) == get_data_dir().resolve(strict=False)
    except Exception:  # pragma: no cover - defensive
        return False


def _engine_season_key(base: Path) -> str:
    """The season a generation is asked for: ``_season_key``, and for a
    league directory that is not the active one, the year of its own
    schedule's current date."""

    key = _season_key(base)
    if key != _UNKNOWN_SEASON or _is_active_league(base):
        return key
    try:
        from utils.sim_date import _compute_sim_date

        token = str(
            _compute_sim_date(base / "schedule.csv", base / "season_progress.json")
            or ""
        ).strip()
    except Exception:  # pragma: no cover - defensive
        return _UNKNOWN_SEASON
    if len(token) >= 4 and token[:4].isdigit():
        return token[:4]
    return _UNKNOWN_SEASON


def _stored_value(entry: dict, key: str) -> Optional[float]:
    try:
        stored = entry.get(key)
        return float(stored) if stored is not None else None
    except (TypeError, ValueError):
        return None


def _computed(base: Path, keys: Iterable[str]) -> Dict[str, float]:
    wanted = set(keys)
    return {k: v for k, v in active_rating_centers(base).items() if k in wanted}


def _ordered(values: Dict[str, float], keys: tuple[str, ...]) -> Dict[str, float]:
    return {key: values[key] for key in keys if key in values}


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

    centres = active_rating_centers(base, players_path=players_path)
    return centres.get(HITTER_SPEED_CENTER_KEY)


def active_rating_centers(
    base: Path | str,
    *,
    players_path: Path | str | None = None,
) -> Dict[str, float]:
    """Every rating centre over the clubs' ACT rosters, to 2 decimals.

    ``base`` and ``players_path`` as in :func:`active_hitter_mean_speed`.
    Hitters are the ACT non-pitchers, pitchers the ACT rows
    ``utils.roster_rules.counts_as_pitcher`` accepts and catchers the ACT
    non-pitchers whose primary position is C. A missing or blank rating
    counts as 50, as the engine's rating loaders read it. A centre whose
    group is empty is left out; ``{}`` when the files are missing.

    Release 5a: ``pitcher_grade_center`` is the mean over the ACT pitchers
    of each one's average pitch grade across the pitches he throws (a blank
    or 0 grade is a pitch he does not throw; a pitcher with none is left
    out). The ``hitter_vl_center_*`` keys are the ACT hitters' mean ``vl``
    by batting side, a side with fewer than ``_VL_SIDE_MIN_HITTERS`` hitters
    reading the all-hitter mean; the ``hitter_bats_share_*`` keys are the
    share of ACT hitters on each side, to 4 decimals, summing to 1.
    """

    from utils.roster_rules import counts_as_pitcher

    base = Path(base)
    players = Path(players_path) if players_path is not None else base / "players.csv"
    roster_dir = base / "rosters"
    if not players.exists() or not roster_dir.is_dir():
        return {}
    active = _active_player_ids(roster_dir)
    values: Dict[str, list[float]] = {key: [] for key in _CENTER_SPECS}
    grades: list[float] = []
    vl_by_side: Dict[str, list[float]] = {side: [] for side in HITTER_VL_CENTER_KEYS}
    try:
        with players.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if str(row.get("player_id") or "").strip() not in active:
                    continue
                if counts_as_pitcher(row):
                    groups = {"pitcher"}
                    grade = _pitch_grade(row)
                    if grade is not None:
                        grades.append(grade)
                else:
                    groups = {"hitter"}
                    position = str(row.get("primary_position") or "")
                    if position.strip().upper() == "C":
                        groups.add("catcher")
                    vl_by_side[_bats_side(row)].append(_rating(row, "vl"))
                for key, (group, column) in _CENTER_SPECS.items():
                    if group not in groups:
                        continue
                    if key == HITTER_EYE_CENTER_KEY:
                        values[key].append(_eye_rating(row))
                    else:
                        values[key].append(_rating(row, column))
    except OSError:
        return {}
    centres = {
        key: round(sum(found) / len(found), 2)
        for key, found in values.items()
        if found
    }
    if grades:
        centres[PITCHER_GRADE_CENTER_KEY] = round(sum(grades) / len(grades), 2)
    centres.update(_batting_side_centers(vl_by_side))
    return _ordered(centres, RATING_CENTER_KEYS)


def _rating(row: dict, column: str) -> float:
    try:
        return float(row.get(column) or 50.0)
    except (TypeError, ValueError):
        return 50.0


def _eye_rating(row: dict) -> float:
    """Eye as ``BatterRatings.from_row`` reads it: a blank Eye is the
    hitter's Contact."""
    try:
        return float(row.get("eye") or "")
    except (TypeError, ValueError):
        return _rating(row, "ch")


def _bats_side(row: dict) -> str:
    """L, R or S; a blank or unknown side bats right, as the engine has it."""
    side = str(row.get("bats") or "").strip().upper()
    return side if side in HITTER_VL_CENTER_KEYS else "R"


def _pitch_grade(row: dict) -> Optional[float]:
    """A pitcher's mean grade over the pitches he throws, or ``None``.

    The grades are the per-pitch columns the engine's pitch quality reads
    (``PitcherRatings.repertoire``, ``physics_sim.models.PITCH_KEYS``); a
    blank or 0 grade means he does not throw that pitch.
    """
    from physics_sim.models import PITCH_KEYS

    thrown = []
    for key in PITCH_KEYS:
        try:
            grade = float(row.get(key) or 0.0)
        except (TypeError, ValueError):
            continue
        if grade > 0.0:
            thrown.append(grade)
    return (sum(thrown) / len(thrown)) if thrown else None


def _batting_side_centers(vl_by_side: Dict[str, list[float]]) -> Dict[str, float]:
    """The ``hitter_vl_center_*`` and ``hitter_bats_share_*`` keys.

    ``vl_by_side`` holds every ACT hitter's ``vl`` under his batting side.
    ``{}`` when there are no hitters.
    """
    everyone = [vl for found in vl_by_side.values() for vl in found]
    if not everyone:
        return {}
    overall = sum(everyone) / len(everyone)
    out: Dict[str, float] = {}
    for side, key in HITTER_VL_CENTER_KEYS.items():
        found = vl_by_side[side]
        enough = len(found) >= _VL_SIDE_MIN_HITTERS
        out[key] = round(sum(found) / len(found) if enough else overall, 2)
    left = round(len(vl_by_side["L"]) / len(everyone), 4)
    right = round(len(vl_by_side["R"]) / len(everyone), 4)
    out[HITTER_BATS_SHARE_KEYS["L"]] = left
    out[HITTER_BATS_SHARE_KEYS["R"]] = right
    # The remainder, so the three sum to 1 whatever the rounding did.
    out[HITTER_BATS_SHARE_KEYS["S"]] = max(0.0, round(1.0 - left - right, 4))
    return out


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
