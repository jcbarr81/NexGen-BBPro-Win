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

Release 5 (league-relative ratings, the engine's ``centred_ratings``) moves
the hitter Contact and Eye centres from every ACT hitter to the lineup
REGULARS and adds a Power centre (``hitter_power_center``) read the same
way: the hitters who bat are the regulars, and how far they sit above the
bench differs from league to league. The regulars are the hitters named in
each club's saved lineup files (``lineups/<team>_vs_lhp.csv`` and
``_vs_rhp.csv``; a hitter in both counts twice, so an everyday player
weighs more than a platoon one), and for a file that is missing or that a
game would not play as saved -- not nine different ACT hitters of the club
-- the club's nine best ACT hitters (:func:`_regular_hitter_ids`). Nothing
is written to a lineup. The speed centre, the pitcher and catcher centres,
the ``vl`` centres and the batting-side shares are unchanged: every ACT
player of the kind.

The same switch shifts a pitcher's control, movement, pitch grades and arm,
and the mean that matters there is over the pitches hitters see: a starter
throws about two and a half times a reliever's innings, and how a staff's
starters compare with its bullpen differs from league to league. Four more
centres carry that, weighted by each ACT pitcher's expected workload
(``pitcher_control_usage_center``, ``pitcher_movement_usage_center``,
``pitcher_grade_usage_center``, ``pitcher_arm_usage_center``): a club's
five-man rotation counts ``_STARTER_WORKLOAD`` and every other arm
``_RELIEVER_WORKLOAD``. The rotation is the one the games use
(``utils.rotation.staff_rotation`` on the club's ACT arms and its
``rosters/<team>_pitching.csv``: the file's SP1-SP5, holes filled by
starter-capable arms and then by endurance, which is also what a club with
no staff file gets); the stored ``role`` column is never read. The plain
ACT means above are NOT redefined: the Release 4 running-game terms and
every stored season file read ``pitcher_control_center``,
``pitcher_hold_center`` and ``pitcher_arm_center`` as they always did.

A season's league-relative centres always share one definition: the Power
centre and the four usage centres are computed only in the same step as the
Contact and Eye centres. An entry that already holds one of those two
(written before this change, on either engine) never gains them -- the
engine reads 50.0 for them, and a league's stored file keeps its bytes for
the rest of that season.

A league must never change engine in the middle of a season, in either
direction, and one file is one point of failure: a lost, truncated or stale
``rating_centers.json`` would read as "no generation", which is legacy. So
a generation that is written down is written down TWICE -- in the season's
entry here and, as ``{"season": ..., "generation": ...}`` under
``engine_generation``, in ``season_progress.json`` (the WITNESS). That file
belongs to the season being played: the rollover and a new league rebuild
it from nothing, which is what drops the witness for the next season; Reset
to Opening Day rebuilds it too and carries the witness over, because it
rewinds the same season; every other writer changes one key and keeps the
rest. The witness therefore speaks for the current season whatever key the
schedule's year gives it. Legacy stays the absence of both records for a
league that has never switched, so neither of its files changes.

How a season's generation is read (:func:`_season_verdict`):

1. What is written down for the season -- its entry, the witness. If they
   disagree, or the entry's is missing, the HIGHER generation is played,
   the fault is logged loudly and (when storing) both records are repaired.
   Higher, because the only way a season gets a generation above legacy
   written down is to have been started on it, while "legacy" is also what
   every kind of loss looks like.
2. Nothing written down and the season has an entry: legacy, as at deploy.
3. Nothing written down and no entry: a season that has not started gets
   the new generation (the rule above). One that HAS started lost its
   entry; it keeps the generation of the newest other season in the file,
   or generation 5 when the league's tuning overrides carry the marker
   that is only written while a season is fixed on generation 5
   (``services.physics_tuning_settings.SWING_SLIDER_REBASE_MARKER``).
   A generation found that way is logged loudly and written down with the
   new entry.

A ``rating_centers.json`` that exists and cannot be read decides nothing
and is never overwritten, by the generation or by the centres: the witness
(or what this process last saw) is played and the fault logged. Anything
else that goes wrong while reading a generation RAISES
(:func:`get_league_engine_generation`): a game that cannot tell which
engine its season is on must fail, not play the wrong one.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
import threading
from typing import Dict, Iterable, Mapping, NamedTuple, Optional

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
    "HITTER_POWER_CENTER_KEY",
    "PITCHER_USAGE_CENTER_KEYS",
    "HITTER_VL_CENTER_KEYS",
    "HITTER_BATS_SHARE_KEYS",
    "RATING_CENTER_KEYS",
    "ENGINE_GENERATION_KEY",
    "GENERATION_WITNESS_FILENAME",
    "GENERATION_WITNESS_KEY",
    "NEW_SEASON_ENGINE_ENV",
    "ENGINE_SWITCH_NEWS",
    "carry_generation_witness",
    "league_engine_generation",
    "get_league_engine_generation",
    "new_seasons_held_on_legacy",
    "recorded_league_engine_generation",
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
HITTER_POWER_CENTER_KEY = "hitter_power_center"
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
# The hitter centres averaged over the lineup regulars instead of every ACT
# hitter (module docstring): tuning key -> players.csv column.
_REGULARS_CENTER_SPECS: Dict[str, str] = {
    HITTER_CONTACT_CENTER_KEY: "ch",
    HITTER_EYE_CENTER_KEY: "eye",
    HITTER_POWER_CENTER_KEY: "ph",
}
# A club's saved lineups are ``lineups/<team>_vs_<hand>.csv``, nine hitters.
_LINEUP_HANDS = ("lhp", "rhp")
_LINEUP_SIZE = 9
# The pitcher centres weighted by expected workload (module docstring):
# tuning key -> players.csv column, the pitch grade being each pitcher's
# mean over the pitches he throws (``_pitch_grade``).
PITCHER_USAGE_CENTER_KEYS: Dict[str, str] = {
    "pitcher_control_usage_center": "control",
    "pitcher_movement_usage_center": "movement",
    "pitcher_grade_usage_center": "grade",
    "pitcher_arm_usage_center": "arm",
}
# Expected innings of a rotation starter against any other arm. In the
# engine's own generation 5 seasons (three leagues) a starter throws 164-168
# innings and a reliever 75-78 on average (closers about 53, long men
# 91-118). Against the innings-weighted means of those seasons any ratio
# from 2.0 to 2.5 lands within 0.36 of every rating (rms 0.14-0.17; the
# plain mean misses by up to 1.8, rms 0.67), and a weight per relief role
# does no better, so there are two weights.
_STARTER_WORKLOAD = 2.5
_RELIEVER_WORKLOAD = 1.0
# The Release 4 keys first, in their stored order; the 5a keys follow, then
# the Power centre and the usage centres.
RATING_CENTER_KEYS: tuple[str, ...] = (
    tuple(_CENTER_SPECS)
    + (PITCHER_GRADE_CENTER_KEY,)
    + tuple(HITTER_VL_CENTER_KEYS.values())
    + tuple(HITTER_BATS_SHARE_KEYS.values())
    + (HITTER_POWER_CENTER_KEY,)
    + tuple(PITCHER_USAGE_CENTER_KEYS)
)
# Centres a stored entry gains only together with its Contact and Eye
# centres (``_predates_league_relative_centers``).
_NEW_ENTRY_KEYS = frozenset((HITTER_POWER_CENTER_KEY, *PITCHER_USAGE_CENTER_KEYS))
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
# (league dir, season) whose stored entry never gains the ``_NEW_ENTRY_KEYS``
# (``_predates_league_relative_centers``), so the file is not re-read for
# them every game.
_WITHHELD: set[tuple] = set()
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
# The second record of a season's generation (module docstring): the file
# and the key in it. The value is ``{"season": <key>, "generation": <n>}``.
GENERATION_WITNESS_FILENAME = "season_progress.json"
GENERATION_WITNESS_KEY = "engine_generation"
# The generation a tuning overrides file carrying the swing-slider rebase
# marker was written under (``_sliders_rebased``).
_SLIDER_REBASE_GENERATION = 5
# (league dir, season) -> generation last read from or written to the file.
# Used only when the file cannot be read (see ``_generation_locked``).
_GENERATION_CACHE: Dict[tuple, int] = {}
# Engine-generation faults this process has already reported (``_shout``).
_SHOUTED: set[tuple] = set()
_LOGGER = logging.getLogger(__name__)


def clear_rating_center_cache() -> None:
    """Drop the process cache (tests; the file stays the source of truth)."""

    with _CENTER_LOCK:
        _CENTER_CACHE.clear()
        _WITHHELD.clear()
        _GENERATION_CACHE.clear()
        _SHOUTED.clear()


def get_league_engine_generation(*, store: bool = True) -> int:
    """The engine generation of the current league's season.

    ``store`` False is for everything that is not a season game or a saved
    setting (a page load, a lineup action, watch-a-game): it reads the
    season's generation, or works out the one the season will get, without
    fixing it.

    Nothing is caught here. The expected "nothing to read" cases -- no
    league, no schedule, no file yet, a file that cannot be parsed -- are
    answered inside :func:`league_engine_generation` without raising, so
    whatever still raises is a real fault, and answering it with "legacy"
    would put a generation-5 league's game on the wrong engine. A game
    fails instead; a page reports the error.
    """

    return league_engine_generation(store=store)


def recorded_league_engine_generation(
    data_dir: Path | str | None = None,
    season: str | int | None = None,
) -> Optional[int]:
    """The generation WRITTEN DOWN for a league's season, or ``None``.

    The season's entry or the witness (the higher, if they disagree);
    ``None`` when neither records one -- a league that has never switched,
    an offseason, a season nothing has fixed yet. Reads only. A tuning file
    is converted on disk to a generation's slider scales only while this
    says the season is fixed on that generation
    (``services.physics_tuning_settings``).
    """

    base = Path(data_dir) if data_dir is not None else get_data_dir()
    season_key = str(season) if season is not None else _engine_season_key(base)
    if season_key == _UNKNOWN_SEASON:
        return None
    with _CENTER_LOCK:
        seasons = _stored_seasons(_read_json(base / RATING_CENTERS_FILENAME))
        recorded = _recorded_generations(base, seasons.get(season_key))
    return max(recorded.values()) if recorded else None


def new_seasons_held_on_legacy() -> bool:
    """True while the operations switch holds new seasons on the legacy
    engine (:data:`NEW_SEASON_ENGINE_ENV`)."""

    return _configured_new_season_generation() <= LEGACY_ENGINE_GENERATION


def carry_generation_witness(
    previous: Mapping[str, object], rebuilt: Dict[str, object]
) -> None:
    """Copy the season's generation witness into a rebuilt progress payload.

    For a writer that builds ``season_progress.json`` from nothing for the
    SAME season (Reset to Opening Day); ``previous`` is the payload being
    replaced. A writer that starts a new season (the rollover, a new
    league) must not call this: leaving the witness out is what lets the
    next season be given its own generation.
    """

    witness = previous.get(GENERATION_WITNESS_KEY)
    if isinstance(witness, dict):
        rebuilt[GENERATION_WITNESS_KEY] = dict(witness)


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
    recomputed. A key with nothing to average is left out, and so are the
    Power and usage centres of an entry that already holds its Contact or
    Eye centre (:func:`_predates_league_relative_centers`).
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
        elif key in _NEW_ENTRY_KEYS and (root, season_key) in _WITHHELD:
            continue
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
    unreadable = not payload and path.exists()
    seasons = _stored_seasons(payload)
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
    if _predates_league_relative_centers(entry) and _NEW_ENTRY_KEYS & set(unstored):
        unstored = [key for key in unstored if key not in _NEW_ENTRY_KEYS]
        _WITHHELD.add((root, season_key))
    if unstored:
        computed = _computed(base, unstored)
        found.update(computed)
        if computed and store and unreadable:
            # The file is there but cannot be read (a disk or sync fault):
            # the season's stored centres may be in it. Writing would
            # replace them, and its generation, with what can be worked
            # out right now, so nothing is written and nothing is cached:
            # the stored values are read again as soon as the file is.
            _shout(
                (root, "centres unreadable"),
                "%s exists but cannot be read; this game uses rating centres "
                "computed from today's rosters and the file is left alone "
                "(restore it, or delete it to have it rebuilt)",
                path,
            )
        elif computed and store:
            # The season's engine generation is settled with every write of
            # its entry (module docstring): a new entry gets the season's,
            # and an entry that lost its generation gets it back.
            verdict = _season_verdict(base, season_key, seasons)
            if verdict.record:
                entry = {**entry, ENGINE_GENERATION_KEY: verdict.generation}
            if new_entry or verdict.record:
                _GENERATION_CACHE[(root, season_key)] = verdict.generation
            if new_entry and verdict.announce:
                announce.append(True)
            seasons[season_key] = {**entry, **computed}
            _write_seasons(path, seasons)
            if verdict.record:
                _write_witness(base, season_key, verdict.generation)
            for key, value in computed.items():
                _CENTER_CACHE[(root, season_key, key)] = value
    return _ordered(found, keys)


class _Verdict(NamedTuple):
    """What the evidence says about a season's engine generation."""

    generation: int
    # Write it down (the entry and the witness) when storing. False for a
    # legacy season of a league that has never recorded a generation.
    record: bool
    # The season is new and this is the league's switch to a later engine.
    announce: bool


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
        return _generation_without_the_file(base, root, season_key, path), False
    seasons = _stored_seasons(payload)
    if season_key == _UNKNOWN_SEASON:
        # No schedule, so no season to fix anything for: the generation of
        # the season under way if its schedule has gone missing (the
        # witness), else what the league's next season will get.
        witness = _read_witness(base)
        if witness is not None:
            return witness[1], False
        return _new_season_generation(base, seasons), False
    had_entry = isinstance(seasons.get(season_key), dict)
    verdict = _season_verdict(base, season_key, seasons)
    if had_entry or (store and verdict.record):
        _GENERATION_CACHE[(root, season_key)] = verdict.generation
    if not store or not verdict.record:
        # Nothing to write: a read, or a legacy season of a league that has
        # never recorded a generation -- legacy is the absence of one, so
        # that league's files stay exactly as they are today. (Its season
        # is pinned by its first game, which creates the entry.)
        return verdict.generation, False
    _record_generation(base, path, season_key, seasons, verdict.generation)
    return verdict.generation, verdict.announce and not had_entry


def _season_verdict(base: Path, season_key: str, seasons: dict) -> _Verdict:
    """A season's generation from all the evidence (module docstring).

    Reads only; ``_CENTER_LOCK`` held. ``seasons`` is the readable file's
    ``seasons`` object.
    """

    entry = seasons.get(season_key)
    recorded = _recorded_generations(base, entry)
    if recorded:
        generation = max(recorded.values())
        stored = recorded.get(RATING_CENTERS_FILENAME)
        root = str(base.resolve(strict=False))
        if min(recorded.values()) != generation:
            _shout(
                (root, season_key, "contradiction", generation),
                "season %s of %s has two engine generations on record (%s); "
                "playing %s, the higher (the lower record is corrected the "
                "next time the season's records are written)",
                season_key,
                base,
                ", ".join(f"{name}: {number}" for name, number in recorded.items()),
                generation,
            )
        elif stored is None:
            _shout(
                (root, season_key, "entry lost", generation),
                "season %s of %s has no engine generation in %s (the file or "
                "its entry was lost, or is a stale copy) but %s records "
                "generation %s; playing %s (the entry gets it back the next "
                "time the season's records are written)",
                season_key,
                base,
                RATING_CENTERS_FILENAME,
                GENERATION_WITNESS_FILENAME,
                generation,
                generation,
            )
        return _Verdict(generation, True, False)
    if isinstance(entry, dict):
        # An entry and nothing written down anywhere: written before
        # generations existed, or by a league that has never switched. The
        # season was under way on the legacy engine, and finishes on it.
        return _Verdict(LEGACY_ENGINE_GENERATION, False, False)
    started = _season_has_started(base)
    generation = _new_season_generation(base, seasons)
    return _Verdict(
        generation,
        bool(_generation_entry(generation, seasons)),
        not started and _is_engine_switch(base, seasons, generation),
    )


def _generation_without_the_file(
    base: Path, root: str, season_key: str, path: Path
) -> int:
    """A season's generation when ``rating_centers.json`` cannot be read.

    The file is there but unreadable (a disk or sync fault, a truncated
    copy). It decides nothing and nothing is written to it: the witness and
    what this process last saw answer, the higher if they differ; with
    neither, what the rules give for a season with no entry. Always logged.
    """

    known = []
    witness = _read_witness(base)
    if witness is not None:
        known.append(witness[1])
    cached = _GENERATION_CACHE.get((root, season_key))
    if cached is not None:
        known.append(cached)
    generation = max(known) if known else _new_season_generation(base)
    _shout(
        (root, season_key, "unreadable", generation),
        "%s exists but cannot be read; playing engine generation %s (%s) and "
        "leaving the file alone (restore it, or delete it to have it rebuilt)",
        path,
        generation,
        "from the season's other record" if known else "nothing else records one",
    )
    return generation


def _recorded_generations(base: Path, entry: object) -> Dict[str, int]:
    """Where a season's generation is written down -> the generation: its
    ``rating_centers.json`` entry (``entry``) and the witness."""

    recorded: Dict[str, int] = {}
    stored = _entry_generation(entry)
    if stored is not None:
        recorded[RATING_CENTERS_FILENAME] = stored
    witness = _read_witness(base)
    if witness is not None:
        recorded[GENERATION_WITNESS_FILENAME] = witness[1]
    return recorded


def _entry_generation(entry: object) -> Optional[int]:
    if not isinstance(entry, dict):
        return None
    stored = entry.get(ENGINE_GENERATION_KEY)
    return normalize_engine_generation(stored) if stored is not None else None


def _stored_seasons(payload: Mapping[str, object]) -> dict:
    seasons = payload.get("seasons")
    return seasons if isinstance(seasons, dict) else {}


def _write_seasons(path: Path, seasons: dict) -> None:
    keep = sorted(seasons)[-_KEEP_SEASONS:]
    _write_json_atomic(
        path, {"version": VERSION, "seasons": {k: seasons[k] for k in keep}}
    )


def _record_generation(
    base: Path, path: Path, season_key: str, seasons: dict, generation: int
) -> None:
    """Write a season's generation down in both places, where it is not
    already; the entry keeps everything else it holds."""

    entry = seasons.get(season_key)
    if _entry_generation(entry) != generation:
        kept = entry if isinstance(entry, dict) else {}
        seasons[season_key] = {**kept, ENGINE_GENERATION_KEY: generation}
        _write_seasons(path, seasons)
    _write_witness(base, season_key, generation)


def _read_witness(base: Path) -> Optional[tuple[str, int]]:
    """(season key, generation) from the witness, or ``None``.

    ``None`` when ``season_progress.json`` is missing or unreadable, has no
    witness, or holds one that is not a generation number.
    """

    record = _read_json(base / GENERATION_WITNESS_FILENAME).get(
        GENERATION_WITNESS_KEY
    )
    if not isinstance(record, dict):
        return None
    raw = record.get("generation")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return str(record.get("season") or ""), normalize_engine_generation(raw)


def _write_witness(base: Path, season_key: str, generation: int) -> None:
    """Record ``generation`` for the season in ``season_progress.json``.

    One key is changed and everything else in the file kept, in the file's
    own layout. A file that exists and cannot be parsed is left alone (the
    schedule cursor is in it); a write that fails is logged -- the entry in
    ``rating_centers.json`` still holds the generation.
    """

    if _read_witness(base) == (season_key, generation):
        return
    path = base / GENERATION_WITNESS_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except OSError:
        _LOGGER.exception("could not read %s to record the engine generation", path)
        return
    try:
        payload = json.loads(text) if text.strip() else {}
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        _LOGGER.error(
            "%s cannot be parsed; engine generation %s not recorded in it",
            path,
            generation,
        )
        return
    payload[GENERATION_WITNESS_KEY] = {"season": season_key, "generation": generation}
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        _LOGGER.exception("could not record the engine generation in %s", path)
        try:
            tmp.unlink()
        except OSError:
            pass


def _sliders_rebased(base: Path) -> bool:
    """True when the league's tuning overrides were written while a season
    was fixed on generation 5 (the swing-slider rebase marker)."""

    from services.physics_tuning_settings import (
        SWING_SLIDER_REBASE_MARKER,
        TUNING_OVERRIDES_FILENAME,
    )

    payload = _read_json(base / TUNING_OVERRIDES_FILENAME)
    return payload.get(SWING_SLIDER_REBASE_MARKER) is True


def _shout(key: tuple, message: str, *args: object) -> None:
    """Report an engine-generation fault where an operator will see it.

    To the log and to stdout: the API's root logger writes to a file under
    the data dir, which Cloud Run never shows (``api.working_copy._emit``).
    Once per process per fault -- a page that cannot repair what it reads
    would otherwise repeat it on every load.
    """

    if key in _SHOUTED:
        return
    _SHOUTED.add(key)
    _LOGGER.error(message, *args)
    try:
        print(f"[engine-generation] {message % args}", flush=True)
    except Exception:  # pragma: no cover - reporting must never stop a game
        pass


def _new_season_generation(base: Path, seasons: dict | None = None) -> int:
    """The generation a season with no entry yet gets.

    The new generation if none of its regular-season games has been played.
    A season already under way keeps the engine it has been playing on: the
    generation of the newest season in ``seasons`` (the file's other
    entries), which is this same season when its key moved -- a schedule
    regenerated with another year -- and legacy when the file has never
    recorded one, the case of every league at deploy. With no season in the
    file to go by, tuning overrides that were written while a season was
    fixed on generation 5 say so (:func:`_sliders_rebased`). A new
    generation whose profile cannot be loaded is not handed out (every game
    of the season would fail): the season starts on the legacy engine and
    the fault is logged.
    """

    if _season_has_started(base):
        generation = _newest_stored_generation(seasons or {})
        source = "the newest other season in the file"
        if generation <= LEGACY_ENGINE_GENERATION and _sliders_rebased(base):
            generation = _SLIDER_REBASE_GENERATION
            source = "its tuning overrides, converted for that generation"
        if generation > LEGACY_ENGINE_GENERATION:
            _shout(
                (str(base.resolve(strict=False)), "inferred", generation),
                "the season under way in %s has no engine generation on "
                "record; playing generation %s, from %s",
                base,
                generation,
                source,
            )
        return generation
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


def _predates_league_relative_centers(entry: dict) -> bool:
    """True when a season's stored entry must not gain the Power centre or
    the pitcher usage centres (``_NEW_ENTRY_KEYS``).

    The entry already holds the season's Contact or Eye centre: its centres
    were fixed before, and whichever of the new ones it lacks stay out. An
    entry written before the hitter centres were averaged over the lineup
    regulars holds ACT means for those two; they are never recomputed, and
    new centres beside them would be a second definition in one season --
    and would change the stored file of a league whose season is already
    under way. The engine reads 50.0 for a centre left out.
    """

    return any(
        _stored_value(entry, key) is not None
        for key in (HITTER_CONTACT_CENTER_KEY, HITTER_EYE_CENTER_KEY)
    )


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

    Release 5 (league-relative ratings): ``hitter_contact_center``,
    ``hitter_eye_center`` and the new ``hitter_power_center`` are the means
    over the lineup regulars (:func:`_regular_hitter_ids`), read from
    ``base / "lineups"``. The ``PITCHER_USAGE_CENTER_KEYS`` are the ACT
    pitchers' control, movement, pitch grade and arm weighted by expected
    workload (:func:`_pitcher_workloads`, from ``base / "rosters"``'s staff
    files). Every other centre is still the plain mean over every ACT
    player of its kind.
    """

    from utils.roster_rules import counts_as_pitcher

    base = Path(base)
    players = Path(players_path) if players_path is not None else base / "players.csv"
    roster_dir = base / "rosters"
    if not players.exists() or not roster_dir.is_dir():
        return {}
    active_by_team = _active_ids_by_team(roster_dir)
    active = {pid for ids in active_by_team.values() for pid in ids}
    values: Dict[str, list[float]] = {key: [] for key in _CENTER_SPECS}
    grades: list[float] = []
    vl_by_side: Dict[str, list[float]] = {side: [] for side in HITTER_VL_CENTER_KEYS}
    # ACT hitter id -> his regulars-centre ratings, and his lineup value.
    hitters: Dict[str, Dict[str, float]] = {}
    hitter_value: Dict[str, float] = {}
    # ACT pitcher id -> his players.csv row (for the usage centres).
    pitchers: Dict[str, dict] = {}
    try:
        with players.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                player_id = str(row.get("player_id") or "").strip()
                if player_id not in active:
                    continue
                if counts_as_pitcher(row):
                    groups = {"pitcher"}
                    grade = _pitch_grade(row)
                    if grade is not None:
                        grades.append(grade)
                    pitchers[player_id] = row
                else:
                    groups = {"hitter"}
                    position = str(row.get("primary_position") or "")
                    if position.strip().upper() == "C":
                        groups.add("catcher")
                    vl_by_side[_bats_side(row)].append(_rating(row, "vl"))
                    hitters[player_id] = {
                        key: _eye_rating(row)
                        if key == HITTER_EYE_CENTER_KEY
                        else _rating(row, column)
                        for key, column in _REGULARS_CENTER_SPECS.items()
                    }
                    hitter_value[player_id] = _lineup_value(row)
                for key, (group, column) in _CENTER_SPECS.items():
                    if group not in groups or key in _REGULARS_CENTER_SPECS:
                        continue
                    values[key].append(_rating(row, column))
    except OSError:
        return {}
    regulars = _regular_hitter_ids(base / "lineups", active_by_team, hitter_value)
    for key in _REGULARS_CENTER_SPECS:
        # No regular at all (no club has an ACT hitter) is no hitter at all;
        # the every-ACT-hitter mean is kept as the fallback all the same.
        values[key] = [hitters[pid][key] for pid in regulars] or [
            ratings[key] for ratings in hitters.values()
        ]
    centres = {
        key: round(sum(found) / len(found), 2)
        for key, found in values.items()
        if found
    }
    if grades:
        centres[PITCHER_GRADE_CENTER_KEY] = round(sum(grades) / len(grades), 2)
    centres.update(_batting_side_centers(vl_by_side))
    centres.update(
        _pitcher_usage_centers(
            pitchers, _pitcher_workloads(roster_dir, active_by_team, pitchers)
        )
    )
    return _ordered(centres, RATING_CENTER_KEYS)


def _pitcher_workloads(
    roster_dir: Path,
    active_by_team: Mapping[str, list[str]],
    pitchers: Mapping[str, dict],
) -> Dict[str, float]:
    """ACT pitcher id -> his expected share of his club's innings.

    ``_STARTER_WORKLOAD`` for the club's rotation, ``_RELIEVER_WORKLOAD``
    for every other ACT arm. The rotation is built exactly as a game builds
    it (``physics_sim.team_data.build_staff``): the club's ACT pitchers and
    the labels its ``<team>_pitching.csv`` gives them, through
    ``utils.rotation.staff_rotation``. A club with no staff file, or one
    that names fewer than five starters, gets the same builder's fill:
    starter-capable arms (``utils.pitcher_role.get_role``) by endurance,
    then the rest by endurance, the closer last. ``pitchers`` holds every
    ACT pitcher's players.csv row; the stored ``role`` column is read only
    as ``get_role``'s last resort.
    """
    from types import SimpleNamespace

    from utils.rotation import staff_rotation

    workloads: Dict[str, float] = {}
    for team, ids in active_by_team.items():
        arms = list(dict.fromkeys(pid for pid in ids if pid in pitchers))
        if not arms:
            continue
        labels: Dict[str, str] = {}
        for pid, label in _staff_file_labels(roster_dir / f"{team}_pitching.csv"):
            if pid in pitchers and pid in arms and pid not in labels:
                labels[pid] = "MR" if label in {"RP", "R"} else label
        rotation = staff_rotation(
            [
                SimpleNamespace(
                    player_id=pid,
                    endurance=_whole(pitchers[pid].get("endurance")),
                    primary_position=pitchers[pid].get("primary_position") or "",
                    preferred_pitching_role=pitchers[pid].get(
                        "preferred_pitching_role"
                    )
                    or "",
                    role=pitchers[pid].get("role") or "",
                )
                for pid in arms
            ],
            labels,
        )
        starters = set(rotation)
        for pid in arms:
            workloads[pid] = (
                _STARTER_WORKLOAD if pid in starters else _RELIEVER_WORKLOAD
            )
    return workloads


def _pitcher_usage_centers(
    pitchers: Mapping[str, dict], workloads: Mapping[str, float]
) -> Dict[str, float]:
    """The ``PITCHER_USAGE_CENTER_KEYS``: each rating's mean over the ACT
    pitchers, weighted by ``workloads``. The grade centre leaves out a
    pitcher with no pitch grades, as ``pitcher_grade_center`` does; ``{}``
    when there is no pitcher."""
    out: Dict[str, float] = {}
    for key, column in PITCHER_USAGE_CENTER_KEYS.items():
        total = weight_sum = 0.0
        for pid, weight in workloads.items():
            row = pitchers[pid]
            value = _pitch_grade(row) if column == "grade" else _rating(row, column)
            if value is None:
                continue
            total += value * weight
            weight_sum += weight
        if weight_sum > 0.0:
            out[key] = round(total / weight_sum, 2)
    return out


def _staff_file_labels(path: Path) -> list[tuple[str, str]]:
    """``(player_id, LABEL)`` rows of a club's pitching-staff file, as
    ``physics_sim.team_data.load_pitching_staff`` reads it; ``[]`` if the
    file is missing or unreadable."""
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return [
                (row[0].strip(), (row[1] if len(row) > 1 else "").strip().upper())
                for row in csv.reader(fh)
                if row and row[0].strip()
            ]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def _whole(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _lineup_value(row: dict) -> float:
    """A hitter's value to a lineup, for picking a club's nine best.

    The lineup auto-fill's base score (``utils.lineup_autofill``): bat 60%
    (Contact and Power evenly), speed 20%, glove and arm 20%. No platoon
    shift and no position coverage: this stands in for a lineup nobody has
    saved, it does not build one.
    """
    bat = 0.5 * _rating(row, "ch") + 0.5 * _rating(row, "ph")
    defence = 0.5 * _rating(row, "fa") + 0.5 * _rating(row, "arm")
    return 0.6 * bat + 0.2 * _rating(row, "sp") + 0.2 * defence


def _regular_hitter_ids(
    lineup_dir: Path,
    active_by_team: Mapping[str, list[str]],
    hitter_value: Mapping[str, float],
) -> list[str]:
    """The league's lineup regulars, one id per lineup spot.

    For each club and each of its two saved lineups (vs LHP, vs RHP): the
    nine hitters the file names, when a game would play it as saved -- nine
    different players, every one an ACT hitter of the club
    (``playbalance.game_runner._lineup_fits_pool``) -- else the club's nine
    best ACT hitters by :func:`_lineup_value` (all of them when it has nine
    or fewer). So an everyday player is counted twice and a platoon player
    once, and every club carries the same weight. ``hitter_value`` holds
    every ACT hitter in the league; nothing is written.
    """
    regulars: list[str] = []
    for team, ids in active_by_team.items():
        pool = list(dict.fromkeys(pid for pid in ids if pid in hitter_value))
        if not pool:
            continue
        # Best first; the id breaks a tie, so the nine never depend on the
        # roster file's order.
        best = sorted(pool, key=lambda pid: (-hitter_value[pid], pid))[:_LINEUP_SIZE]
        for hand in _LINEUP_HANDS:
            saved = _saved_lineup_ids(lineup_dir / f"{team}_vs_{hand}.csv")
            usable = (
                len(saved) == _LINEUP_SIZE
                and len(set(saved)) == _LINEUP_SIZE
                and all(pid in pool for pid in saved)
            )
            regulars.extend(saved if usable else best)
    return regulars


def _saved_lineup_ids(path: Path) -> list[str]:
    """The ``player_id`` column of a saved lineup file; ``[]`` if unreadable."""
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return [
                str(row.get("player_id") or "").strip()
                for row in csv.DictReader(fh)
            ]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


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


def _active_ids_by_team(roster_dir: Path) -> Dict[str, list[str]]:
    """Team id (the roster file's name) -> its ACT player ids, in file order."""
    active: Dict[str, list[str]] = {}
    for roster_file in sorted(roster_dir.glob("*.csv")):
        if roster_file.stem.endswith(_ROSTER_SIDE_SUFFIXES):
            continue  # <team>_pitching.csv and other side files
        try:
            with roster_file.open(newline="", encoding="utf-8") as fh:
                active[roster_file.stem] = [
                    row[0].strip()
                    for row in csv.reader(fh)
                    if len(row) >= 2 and row[1].strip().upper() == "ACT"
                ]
        except OSError:
            continue
    return active
