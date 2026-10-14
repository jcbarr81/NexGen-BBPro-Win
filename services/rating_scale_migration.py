"""The 8.0.0 move: a league's ratings to scale 2, with engine generation 6.

Owner decisions 5 and 15 (``docs/audits/2026-10-06-engine-ratings-audit/
DECISIONS.md``, "Release 6 owner decisions"); the design is
``RATING_SCALE_DESIGN.md`` section 6. Everything here is behind the 8.0.0
operations switch (``utils.rating_scale.GENERATION6_SWITCH_ENV``): with it
off nothing calls in, and no league converts.

**When.** A league moves when its next season is given its engine
generation (``services.league_rating_centers``: the first season game, or
the first saved setting, of a season with no game played). With the switch
on, that season is given generation 6 and THIS module converts the league's
players first, in the same locked step; only then are the season's
generation and rating centres written down. A league that cannot convert
(:func:`move_blocker`) is given generation 5 and stays on scale 1, and its
commissioner is told why. A season already under way never moves. A league
created with the switch on is generated on scale 2 and starts on
generation 6 without a conversion.

**What one conversion does** (:func:`convert_league`), under a league lock
and the working copy's background-writer guard:

1. Read ``players.csv`` raw (never through the models).
2. With the league's re-spread flag on (:func:`respread_requested`), map
   each bunched rating by rank onto a normal league's spread, in ENGINE
   points (:func:`respread_rows`). alpha-test only (decision 15).
3. ``stretch_row`` every scale 1 row to scale 2 (a scale 2 row is left as
   it is: idempotent per row).
4. Check the row count and the id set are unchanged.
5. Copy the original to ``players.scale1.<season>.csv`` (and an open draft
   pool's files to ``draft_pool_<year>.scale1.<season>.<ext>``).
6. Write the whole file atomically in the scale 2 format (``height_in``;
   ``utils.rating_scale``), which a build before 8.0.0 refuses to load.
7. Convert every open draft pool the same way (a year from the season's
   own on).
8. Log it in ``rating_scale.json`` and post the news items.

Never converted: history, stats, records, archives, rating centres (engine
scale by construction), ``players_normalized.csv``.

**Why it cannot half-happen.** Each step leaves a league that plays
correctly, because every row carries its own scale and reads correctly on
it, and each step is redone or finished by the next attempt:

* a crash before the players file is replaced leaves a scale 1 league with
  no generation recorded: the next attempt converts it;
* a crash after it, before the season's generation is written down, leaves
  a scale 2 league with none: a league whose players are on scale 2 is
  given generation 6 (``league_rating_centers``), so the next attempt
  records 6 and finds nothing left to convert;
* a players file that LOSES its conversion afterwards (a stale copy pushed
  back, a restore, a per-file sync that carried the generation but not the
  players) is a league recorded on generation 6 with scale 1 rows: the next
  season game converts them again (:func:`repair_league`). The game itself
  was never wrong: scale is play-neutral.

**Rollback** (:func:`rollback_league`, ``scripts/rating_scale_rollback.py``,
``docs/rating_scale_switch_runbook.md``): the backup, or the exact inverse.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import statistics
import threading
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

from utils.rating_scale import (
    FULL_RATING_SCALE,
    HEIGHT_FIELD,
    LEGACY_RATING_SCALE,
    RATING_SCALE_FIELD,
    SCALE2_HEIGHT_FIELD,
    MixedRatingScaleError,
    RatingClip,
    describe_rating_scales,
    engine_row,
    is_pitcher_flag,
    majority_rating_scale,
    players_fieldnames,
    rating_map,
    rating_scale_counts,
    rating_scale_of,
    stretch_row,
)

__all__ = [
    "BACKUP_TEMPLATE",
    "RATING_SCALE_LOG_FILENAME",
    "RESPREAD_LEAGUES_ENV",
    "RESPREAD_REFERENCE_PATH",
    "MovePlan",
    "MoveRefused",
    "MoveResult",
    "RespreadResult",
    "build_respread_reference",
    "convert_league",
    "engine_and_scale_news",
    "format_respread_reference",
    "league_id_of",
    "league_on_scale2",
    "load_respread_reference",
    "move_blocker",
    "plan_move",
    "read_scale_log",
    "refusal_news",
    "repair_league",
    "respread_news",
    "respread_requested",
    "respread_rows",
    "rollback_league",
]

_LOGGER = logging.getLogger(__name__)

RATING_SCALE_LOG_FILENAME = "rating_scale.json"
BACKUP_TEMPLATE = "players.scale1.{season}.csv"
# Comma-separated league ids whose ratings are re-spread when they move
# (decision 15: alpha-test). Read when the league converts.
RESPREAD_LEAGUES_ENV = "NEXGEN_RESPREAD_LEAGUES"
RESPREAD_REFERENCE_PATH = Path(__file__).resolve().with_name(
    "rating_respread_reference.json"
)
_LOCK_NAME = ".rating_scale_move.lock"
# A move lock older than this is a dead process's: broken, and logged.
_STALE_LOCK_SECONDS = 600.0
_PLAYERS = "players.csv"
_POOL_RE = re.compile(r"^draft_pool_(\d{4})\.(json|csv)$")
_NEWS_FILE = "news_feed.txt"
# How many players a refusal names.
_NAMED = 8

# ---------------------------------------------------------------------------
# The re-spread (decision 15)
# ---------------------------------------------------------------------------

# Ratings a re-spread may move, by kind of row. Not ``vl`` (a split the
# engine reads against each batting side's own mean; mapping it across
# sides would scramble that structure) and not ``sc`` or durability.
RESPREAD_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    "hitter": ("ch", "ph", "eye", "sp", "fa", "arm", "gf", "pl"),
    "pitcher": (
        "control", "movement", "arm", "endurance", "hold_runner", "fa", "gf",
        "fb", "cu", "cb", "sl", "si", "scb", "kn",
    ),
}
# The measured rule: a rating is BUNCHED in a league when the standard
# deviation over its ACT players is below this share of the reference
# league's (``data/calibration_league``, a league as the product creates
# one). On alpha-test it picks Eye (.57), fielding (.22), arm (.17),
# ground-ball (.53) and pull (.31) of the hitters and control (.35),
# movement (0), arm (.24), endurance (.11), hold (.16), fielding (.36) and
# ground-ball (.44) of the pitchers; it leaves Contact (1.32), Power (.90),
# speed (.77) and every pitch grade (.68 and up). The flat fixture
# (``data/calibration_flat``, bunched the same way) gives the same twelve;
# stats-clean (lowest ratio .64), the calibration fixture and the league
# fixture give none.
BUNCHED_SD_RATIO = 0.6
# The fixed seed of the last tie-break (a hash, so no random stream and no
# PYTHONHASHSEED is involved).
RESPREAD_SEED = "8.0.0-respread"
_PITCH_KEYS = ("fb", "cu", "cb", "sl", "si", "scb", "kn")
_QUANTILES = 100
_REFERENCE_CACHE: Dict[str, Any] = {}


@dataclass
class RespreadRating:
    """What the re-spread did to one rating of one kind of row."""

    group: str
    key: str
    league_sd: float
    reference_sd: float
    bunched: bool
    players: int = 0
    act_mean_before: float = 0.0
    act_mean_after: float = 0.0
    act_sd_after: float = 0.0
    act_min_before: float = 0.0
    act_max_before: float = 0.0
    act_min_after: float = 0.0
    act_max_after: float = 0.0
    changed: int = 0
    # On the scale owners see (scale 2), filled when the move is logged.
    stored_range_unspread: Optional[List[int]] = None
    stored_range: Optional[List[int]] = None

    def as_log(self) -> Dict[str, Any]:
        return {
            "group": self.group,
            "key": self.key,
            "act_sd_before": round(self.league_sd, 2),
            "reference_act_sd": round(self.reference_sd, 2),
            "players": self.players,
            "changed": self.changed,
            "act_mean_before": round(self.act_mean_before, 2),
            "act_mean_after": round(self.act_mean_after, 2),
            "act_sd_after": round(self.act_sd_after, 2),
            "act_range_before": [self.act_min_before, self.act_max_before],
            "act_range_after": [self.act_min_after, self.act_max_after],
            "stored_range_unspread": self.stored_range_unspread,
            "stored_range": self.stored_range,
        }


@dataclass
class RespreadResult:
    rows: List[Dict[str, Any]]
    ratings: List[RespreadRating]

    @property
    def moved(self) -> List[RespreadRating]:
        return [r for r in self.ratings if r.bunched]


def build_respread_reference(
    league_dir: Path | str, source: str = "data/calibration_league"
) -> Dict[str, Any]:
    """The reference spread of a league directory (players.csv + rosters).

    For each candidate rating of each kind of row: the ACT players' mean and
    standard deviation (the bunched rule) and the percentiles 0-100 over
    EVERY player of the kind with the rating set (the target of the rank
    map: a league's whole population, ACT and minor leaguers alike, is
    mapped onto a whole population). Engine scale. The stored reference
    (:data:`RESPREAD_REFERENCE_PATH`) is this for ``data/calibration_league``
    (tests/test_r8_switch_respread.py rebuilds it).
    """

    base = Path(league_dir)
    rows = [engine_row(r) for r in _read_rows(base / _PLAYERS)[1]]
    active = _active_ids(base) or set()
    out: Dict[str, Any] = {"source": source, "ratings": {}}
    for group, keys in RESPREAD_CANDIDATES.items():
        out["ratings"][group] = {}
        members = [r for r in rows if _group(r) == group]
        for key in keys:
            values = sorted(v for v in (_value(r, key) for r in members) if v is not None)
            act = [
                v for v in (_value(r, key) for r in members if r.get("player_id") in active)
                if v is not None
            ]
            if len(values) < 2 or len(act) < 2:
                continue
            out["ratings"][group][key] = {
                "act_mean": round(statistics.fmean(act), 3),
                "act_sd": round(statistics.pstdev(act), 3),
                "quantiles": [
                    round(_percentile(values, q / _QUANTILES), 3)
                    for q in range(_QUANTILES + 1)
                ],
            }
    return out


def format_respread_reference(reference: Mapping[str, Any]) -> str:
    """The reference as stored: one line per rating, for readable diffs.
    Rebuild with ``python -c "from services.rating_scale_migration import *;
    RESPREAD_REFERENCE_PATH.write_bytes(format_respread_reference(
    build_respread_reference('data/calibration_league')).encode())"``."""

    lines = ["{", f'  "source": {json.dumps(reference.get("source"))},', '  "ratings": {']
    groups = list(reference.get("ratings", {}).items())
    for g_index, (group, ratings) in enumerate(groups):
        lines.append(f"    {json.dumps(group)}: {{")
        items = list(ratings.items())
        for r_index, (key, spec) in enumerate(items):
            comma = "," if r_index < len(items) - 1 else ""
            lines.append(f"      {json.dumps(key)}: {json.dumps(spec, sort_keys=True)}{comma}")
        lines.append("    }" + ("," if g_index < len(groups) - 1 else ""))
    lines += ["  }", "}", ""]
    return "\n".join(lines)


def load_respread_reference(path: Path | str | None = None) -> Dict[str, Any]:
    target = str(path or RESPREAD_REFERENCE_PATH)
    cached = _REFERENCE_CACHE.get(target)
    if cached is None:
        cached = json.loads(Path(target).read_text(encoding="utf-8"))
        _REFERENCE_CACHE[target] = cached
    return cached


def respread_rows(
    rows: List[Mapping[str, Any]],
    *,
    active_ids: Optional[Iterable[str]],
    rotation_ids: Iterable[str] = (),
    reference: Optional[Mapping[str, Any]] = None,
) -> RespreadResult:
    """Each bunched rating mapped by rank onto the reference spread.

    ``rows`` are scale 1 ``players.csv`` rows (engine scale); the result's
    rows are new dicts, in the same order, with integer values in the form
    the row held them (text stays text). Per kind of row (hitter /
    pitcher) and rating:

    * BUNCHED when the ACT players' standard deviation is below
      :data:`BUNCHED_SD_RATIO` of the reference's. Anything else is left
      exactly as it is.
    * Every player of the kind with the rating set is ranked: by the
      rating, then (pitchers) by the mean of the pitch grades he throws,
      then by a fixed seeded draw. Endurance ranks a club's rotation
      starters (``rotation_ids``) above every other arm first: a bunched
      endurance holds no information on who starts, the staff file does.
    * The player at rank ``i`` of ``n`` takes the reference percentile
      ``(i + 0.5) / n``; the whole rating is then shifted so its ACT mean
      is what it was (the league's run level does not move), rounded to a
      whole number and kept inside 1-99.
    * Potentials keep their gap in points (never below the new rating).

    Order is preserved: a player above another before is not below him
    after (rounding can tie two; endurance is ordered within starters and
    within everyone else).
    """

    reference = reference or load_respread_reference()
    active = set(active_ids or ())
    rotation = set(rotation_ids)
    out = [dict(r) for r in rows]
    report: List[RespreadRating] = []
    grades = {
        id(r): _pitch_grade_mean(r) for r in rows if _group(r) == "pitcher"
    }
    for group, keys in RESPREAD_CANDIDATES.items():
        ref_group = reference.get("ratings", {}).get(group, {})
        members = [
            (i, r) for i, r in enumerate(rows) if _group(r) == group
        ]
        for key in keys:
            ref = ref_group.get(key)
            if ref is None:
                continue
            population = [
                (i, r, v) for i, r in members
                if (v := _value(r, key)) is not None
            ]
            act_values = [
                v for _, r, v in population if str(r.get("player_id")) in active
            ]
            if len(act_values) < 2:
                continue
            league_sd = statistics.pstdev(act_values)
            entry = RespreadRating(
                group, key, league_sd, float(ref["act_sd"]),
                league_sd < BUNCHED_SD_RATIO * float(ref["act_sd"]),
            )
            entry.act_mean_before = statistics.fmean(act_values)
            entry.act_min_before = min(act_values)
            entry.act_max_before = max(act_values)
            report.append(entry)
            if not entry.bunched:
                continue

            def rank_key(item):
                _, row, value = item
                pid = str(row.get("player_id") or "")
                starter = 1 if key == "endurance" and pid in rotation else 0
                grade = grades.get(id(row), 0.0) or 0.0
                return (starter, value, grade, _draw(pid, key))

            ordered = sorted(population, key=rank_key)
            n = len(ordered)
            targets = [
                _quantile(ref["quantiles"], (rank + 0.5) / n) for rank in range(n)
            ]
            act_targets = [
                t for t, (_, r, _) in zip(targets, ordered)
                if str(r.get("player_id")) in active
            ]
            shift = entry.act_mean_before - statistics.fmean(act_targets)
            after_act: List[int] = []
            for target, (index, row, old) in zip(targets, ordered):
                new = max(1, min(99, int(round(target + shift))))
                if new != old:
                    entry.changed += 1
                target_row = out[index]
                target_row[key] = _like(row.get(key), new)
                pot_key = f"pot_{key}"
                pot = _value(row, pot_key)
                if pot is not None:
                    gap = max(0.0, pot - old)
                    target_row[pot_key] = _like(row.get(pot_key), min(99, int(round(new + gap))))
                if str(row.get("player_id")) in active:
                    after_act.append(new)
            entry.players = n
            entry.act_mean_after = statistics.fmean(after_act)
            entry.act_sd_after = statistics.pstdev(after_act)
            entry.act_min_after = min(after_act)
            entry.act_max_after = max(after_act)
    return RespreadResult(out, report)


def respread_requested(base: Path | str) -> bool:
    """True when the league is listed in :data:`RESPREAD_LEAGUES_ENV`."""

    raw = str(os.getenv(RESPREAD_LEAGUES_ENV, "") or "")
    wanted = {item.strip() for item in raw.split(",") if item.strip()}
    return league_id_of(base) in wanted


def _group(row: Mapping[str, Any]) -> str:
    return "pitcher" if is_pitcher_flag(row.get("is_pitcher")) else "hitter"


def _value(row: Mapping[str, Any], key: str) -> Optional[float]:
    raw = row.get(key)
    if raw is None or raw == "":
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _pitch_grade_mean(row: Mapping[str, Any]) -> float:
    grades = [v for v in (_value(row, k) for k in _PITCH_KEYS) if v is not None]
    return statistics.fmean(grades) if grades else 0.0


def _draw(player_id: str, key: str) -> str:
    return hashlib.sha256(f"{RESPREAD_SEED}|{key}|{player_id}".encode()).hexdigest()


def _percentile(values: List[float], p: float) -> float:
    if len(values) == 1:
        return values[0]
    pos = p * (len(values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def _quantile(quantiles: List[float], p: float) -> float:
    return _percentile(list(quantiles), min(1.0, max(0.0, p)))


def _like(sample: Any, value: int) -> Any:
    return str(value) if isinstance(sample, str) else value


# ---------------------------------------------------------------------------
# The plan (read-only) and the blocker
# ---------------------------------------------------------------------------

class MoveRefused(RuntimeError):
    """The league cannot be converted; ``reason`` says why in plain words."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class MovePlan:
    path: Path
    fieldnames: List[str]
    rows: List[Dict[str, Any]]
    counts: Dict[int, int]
    active_ids: Optional[set]
    converted: List[Dict[str, Any]] = field(default_factory=list)
    clips: List[RatingClip] = field(default_factory=list)
    respread: Optional[RespreadResult] = None
    blocker: Optional[str] = None
    # The rows the stretch was given: ``rows``, or the re-spread rows.
    sources: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def to_convert(self) -> int:
        return sum(1 for r in self.rows if rating_scale_of(r) == LEGACY_RATING_SCALE)

    @property
    def active_clips(self) -> List[RatingClip]:
        return [
            c for c in self.clips
            if c.kind == "rating" and _counts_as_active(c.player_id, self.active_ids)
        ]

    @property
    def other_clips(self) -> List[RatingClip]:
        active = set(id(c) for c in self.active_clips)
        return [c for c in self.clips if id(c) not in active]

    @property
    def in_scale2_format(self) -> bool:
        return SCALE2_HEIGHT_FIELD in self.fieldnames or HEIGHT_FIELD not in self.fieldnames


def _counts_as_active(player_id: str, active_ids: Optional[set]) -> bool:
    # A league with no rosters cannot say who plays: everyone counts.
    return active_ids is None or player_id in active_ids


def plan_move(base: Path | str, *, respread: Optional[bool] = None) -> MovePlan:
    """What converting ``base`` would do, without writing anything.

    ``respread`` None asks :func:`respread_requested`. The plan's
    ``blocker`` is ``None`` when the league can convert, else the reason it
    cannot: no readable players file, rows on no known scale, a file split
    evenly between scales, or an ACT player (every player, in a league with
    no rosters) with a rating that would not fit 1-99 on scale 2 -- a
    clipped rating no longer plays as it did. Clips on players off the
    active rosters, and potentials cut at 99, are allowed and reported.
    """

    base = Path(base)
    path = base / _PLAYERS
    try:
        fieldnames, rows = _read_rows(path)
    except OSError as exc:
        return MovePlan(path, [], [], {}, None, blocker=f"players.csv cannot be read ({exc})")
    plan = MovePlan(path, fieldnames, rows, {}, _active_ids(base))
    hold = read_scale_log(base).get("hold")
    if hold:
        # Set by a rollback (the runbook): the league stays on scale 1 --
        # neither moved again at its next season nor repaired -- until an
        # operator removes the key.
        detail = hold if isinstance(hold, str) else hold.get("reason", "held")
        plan.blocker = (
            f"an operator holds this league on the current scale ({detail}); "
            f'remove "hold" from {RATING_SCALE_LOG_FILENAME} to let it move'
        )
        return plan
    if not rows:
        plan.blocker = "players.csv has no players"
        return plan
    try:
        plan.counts = rating_scale_counts(rows)
        majority_rating_scale(plan.counts)
    except MixedRatingScaleError as exc:
        plan.blocker = str(exc)
        return plan
    except ValueError as exc:
        plan.blocker = f"players.csv holds a row on no known rating scale ({exc})"
        return plan
    legacy = [r for r in rows if rating_scale_of(r) == LEGACY_RATING_SCALE]
    if respread is None:
        respread = respread_requested(base)
    source = rows
    if respread and legacy:
        # Only rows still on scale 1 are re-spread (a repair never is).
        result = respread_rows(
            legacy,
            active_ids=plan.active_ids or (),
            rotation_ids=_rotation_ids(base),
        )
        plan.respread = result
        by_id = {id(r): new for r, new in zip(legacy, result.rows)}
        source = [by_id.get(id(r), r) for r in rows]
    converted: List[Dict[str, Any]] = []
    for row in source:
        new_row, clips = stretch_row(row, FULL_RATING_SCALE)
        converted.append(new_row)
        plan.clips.extend(clips)
    plan.converted = converted
    plan.sources = source
    if plan.active_clips:
        named = ", ".join(
            f"{c.player_id} {c.key} {c.engine_value:g}"
            for c in plan.active_clips[:_NAMED]
        )
        more = len(plan.active_clips) - _NAMED
        who = (
            "players on active rosters"
            if plan.active_ids is not None
            else "players (the league has no rosters, so every player counts)"
        )
        plan.blocker = (
            f"{len(plan.active_clips)} rating(s) of {who} "
            f"would not fit the full 1-99 scale ({named}"
            f"{f' and {more} more' if more > 0 else ''}); they would no longer "
            "play as they do"
        )
    return plan


# path signature -> blocker (None: can convert)
_BLOCKER_CACHE: Dict[Tuple[str, int, int, bool], Optional[str]] = {}
_CACHE_LOCK = threading.Lock()


def move_blocker(base: Path | str) -> Optional[str]:
    """Why ``base`` cannot convert, or ``None``; read-only, cached on the
    players file (and rosters) as they are. For the generation a season
    with no entry WILL get (``league_rating_centers``)."""

    base = Path(base)
    key = _signature_key(base) + (respread_requested(base),)
    with _CACHE_LOCK:
        if key in _BLOCKER_CACHE:
            return _BLOCKER_CACHE[key]
    blocker = plan_move(base).blocker
    with _CACHE_LOCK:
        _BLOCKER_CACHE[key] = blocker
    return blocker


def league_on_scale2(base: Path | str) -> bool:
    """True when most of the league's player rows are on scale 2 (an even
    split is not: that file is refused by :func:`move_blocker`)."""

    from utils.rating_scale import players_file_rating_scales

    counts = players_file_rating_scales(Path(base) / _PLAYERS)
    try:
        return majority_rating_scale(counts) == FULL_RATING_SCALE
    except MixedRatingScaleError:
        return False


def _signature_key(base: Path) -> Tuple[str, int, int]:
    path = base / _PLAYERS
    try:
        stat = path.stat()
        sig = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        sig = (0, 0)
    roster_sig = 0
    roster_dir = base / "rosters"
    try:
        for entry in roster_dir.glob("*.csv"):
            roster_sig ^= hash((entry.name, entry.stat().st_mtime_ns))
    except OSError:
        pass
    try:
        roster_sig ^= hash(("log", (base / RATING_SCALE_LOG_FILENAME).stat().st_mtime_ns))
    except OSError:
        pass
    return (str(path.resolve(strict=False)), sig[0] ^ roster_sig, sig[1])


def clear_caches() -> None:
    with _CACHE_LOCK:
        _BLOCKER_CACHE.clear()
    _REFERENCE_CACHE.clear()


# ---------------------------------------------------------------------------
# The conversion
# ---------------------------------------------------------------------------

@dataclass
class MoveResult:
    status: str  # "converted", "already", "repaired"
    season: str
    players: int = 0
    converted: int = 0
    backup: Optional[str] = None
    pools: List[str] = field(default_factory=list)
    respread: Optional[RespreadResult] = None
    news: List[str] = field(default_factory=list)
    record: Dict[str, Any] = field(default_factory=dict)


def convert_league(
    base: Path | str,
    season: str,
    *,
    generation: int = 6,
    previous_generation: Optional[int] = None,
    respread: Optional[bool] = None,
    announce: bool = True,
    event_name: str = "converted",
) -> MoveResult:
    """Convert ``base`` to scale 2 for ``season`` (module docstring, steps
    1-8). Idempotent: a league already on scale 2 is left alone (an open
    draft pool still on scale 1 is converted, and a missing log record is
    written). Raises :class:`MoveRefused` before anything is written when
    the league cannot convert.

    ``previous_generation`` is the engine the league played its last
    season on (for the news item); ``announce`` False posts no news.
    """

    base = Path(base)
    season = str(season)
    with _move_guard(base):
        plan = plan_move(base, respread=respread)
        if plan.blocker:
            raise MoveRefused(plan.blocker)
        if plan.to_convert == 0 and plan.in_scale2_format:
            # Nothing left of the players to convert (a retry after a crash,
            # or a league created on scale 2): finish what may be missing.
            pools = _convert_pools(base, season)
            result = MoveResult("already", season, players=len(plan.rows), pools=pools)
            if _season_record(base, season) is None and _scale_log_needed(base):
                result.record = _log_conversion(
                    base, season, plan, generation, None, pools, event_name
                )
            return result
        before_ids = [str(r.get("player_id") or "") for r in plan.rows]
        after_ids = [str(r.get("player_id") or "") for r in plan.converted]
        if len(before_ids) != len(after_ids) or set(before_ids) != set(after_ids):
            raise MoveRefused("the converted file would not hold the same players")
        backup: Optional[Path] = None
        if all(rating_scale_of(r) == LEGACY_RATING_SCALE for r in plan.rows):
            backup = base / BACKUP_TEMPLATE.format(season=season)
            if not backup.exists():
                # Never replaced: it is the file as it was at the first
                # attempt, which a retry after a crash leaves unchanged.
                _write_bytes_atomic(backup, plan.path.read_bytes())
        _write_players(plan.path, plan.fieldnames, plan.converted)
        _verify_written(plan.path, after_ids)
        if plan.to_convert == 0:
            # Every row was on scale 2 already; only the file's format was
            # behind (a scale 2 file written before the format existed).
            pools = _convert_pools(base, season)
            _append_log(base, {"event": "reformatted", "season": season, "at": _now()})
            _clear_player_caches()
            return MoveResult("already", season, players=len(plan.rows), pools=pools)
        # Pools after the players: a scale 1 pick drafted into a scale 2
        # league is stretched on the way in (services.draft_assignment), the
        # other way round is refused.
        pools = _convert_pools(base, season)
        record = _log_conversion(base, season, plan, generation, backup, pools, event_name)
        result = MoveResult(
            "converted", season, players=len(plan.rows), converted=plan.to_convert,
            backup=backup.name if backup else None, pools=pools,
            respread=plan.respread, record=record,
        )
        _clear_player_caches()
        if announce:
            result.news = _post_move_news(base, plan, record, previous_generation)
        _print(
            f"{base}: {plan.to_convert} players converted to rating scale 2 for "
            f"season {season} (generation {generation})"
            + (f"; backup {backup.name}" if backup else "")
            + (f"; re-spread {len(plan.respread.moved)} ratings" if plan.respread else "")
        )
        return result


def repair_league(base: Path | str, season: str) -> Optional[MoveResult]:
    """Convert the scale 1 rows of a league already recorded on generation 6
    (module docstring); ``None`` when there are none. Never re-spreads and
    posts no news. A row that would clip is left as it is (logged): it
    still plays correctly on its own scale."""

    base = Path(base)
    from utils.rating_scale import players_file_rating_scales

    path = base / _PLAYERS
    counts = players_file_rating_scales(path)
    if not counts:
        return None
    needed = LEGACY_RATING_SCALE in counts or _header_needs_scale2_format(path)
    if not needed:
        return None
    try:
        result = convert_league(
            base, season, respread=False, announce=False, event_name="repaired"
        )
    except MoveRefused as exc:
        _print(f"{base}: scale 1 rows found in a generation 6 league and left as "
               f"they are ({exc.reason}); each still plays on its own scale")
        return None
    if result.status == "converted":
        result.status = "repaired"
        _print(f"{base}: repaired {result.converted} scale 1 rows of a generation 6 league")
    return result


def _header_needs_scale2_format(path: Path) -> bool:
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            header = next(csv.reader(fh), [])
    except OSError:
        return False
    return HEIGHT_FIELD in header and SCALE2_HEIGHT_FIELD not in header


def _write_players(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    from utils.atomic_write import atomic_text_writer

    added = []
    for row in rows:
        for key in row:
            if key not in fieldnames and key not in added and key not in (
                RATING_SCALE_FIELD, HEIGHT_FIELD, SCALE2_HEIGHT_FIELD
            ):
                added.append(key)  # an Eye the stretch filled into a file without one
    header = players_fieldnames(list(fieldnames) + added, scale2=True)
    with atomic_text_writer(path, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            if HEIGHT_FIELD in out:
                out[SCALE2_HEIGHT_FIELD] = out.pop(HEIGHT_FIELD)
            writer.writerow({k: out.get(k, "") for k in header})


def _verify_written(path: Path, ids: List[str]) -> None:
    fieldnames, rows = _read_rows(path)
    got = [str(r.get("player_id") or "") for r in rows]
    if got != ids or any(rating_scale_of(r) != FULL_RATING_SCALE for r in rows):
        raise RuntimeError(f"{path} did not read back as written")
    if SCALE2_HEIGHT_FIELD not in fieldnames:
        raise RuntimeError(f"{path} was not written in the scale 2 format")


def _convert_pools(base: Path, season: str) -> List[str]:
    """Convert every open draft pool (a year from ``season`` on) still on
    scale 1; the files converted. Backups beside them."""

    try:
        first_year = int(season)
    except ValueError:
        first_year = 0
    done: List[str] = []
    for path in sorted(base.glob("draft_pool_*")):
        match = _POOL_RE.match(path.name)
        if not match or int(match.group(1)) < first_year:
            continue
        ext = match.group(2)
        backup = base / f"draft_pool_{match.group(1)}.scale1.{season}.{ext}"
        if ext == "json":
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(records, list) or not any(
                isinstance(r, dict) and rating_scale_of(r) == LEGACY_RATING_SCALE
                for r in records
            ):
                continue
            converted = []
            for record in records:
                if isinstance(record, dict):
                    record = stretch_row(record, FULL_RATING_SCALE)[0]
                converted.append(record)
            if not backup.exists():
                _write_bytes_atomic(backup, path.read_bytes())
            _write_bytes_atomic(path, json.dumps(converted, indent=2).encode("utf-8"))
        else:
            fieldnames, rows = _read_rows(path)
            if not rows or all(rating_scale_of(r) != LEGACY_RATING_SCALE for r in rows):
                continue
            converted = [stretch_row(r, FULL_RATING_SCALE)[0] for r in rows]
            header = list(fieldnames)
            if RATING_SCALE_FIELD not in header:
                header.append(RATING_SCALE_FIELD)
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=header)
            writer.writeheader()
            for row in converted:
                writer.writerow({k: row.get(k, "") for k in header})
            if not backup.exists():
                _write_bytes_atomic(backup, path.read_bytes())
            _write_bytes_atomic(path, buffer.getvalue().replace("\r\n", "\n").encode("utf-8"))
        done.append(path.name)
    return done


# ---------------------------------------------------------------------------
# The log: rating_scale.json
# ---------------------------------------------------------------------------

def read_scale_log(base: Path | str) -> Dict[str, Any]:
    try:
        payload = json.loads((Path(base) / RATING_SCALE_LOG_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "events": []}
    if not isinstance(payload, dict):
        return {"version": 1, "events": []}
    payload.setdefault("events", [])
    return payload


def _season_record(base: Path, season: str) -> Optional[Dict[str, Any]]:
    for event in read_scale_log(base).get("events", []):
        if event.get("event") == "converted" and str(event.get("season")) == season:
            return event
    return None


def _append_log(base: Path, event: Dict[str, Any]) -> Dict[str, Any]:
    payload = read_scale_log(base)
    payload["version"] = 1
    payload["events"].append(event)
    payload["scale"] = FULL_RATING_SCALE if event.get("event") in {"converted", "repaired"} else payload.get("scale")
    _write_bytes_atomic(
        Path(base) / RATING_SCALE_LOG_FILENAME,
        json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
    )
    return event


def _scale_log_needed(base: Path) -> bool:
    """A scale 2 league with no conversion on record: one created on scale
    2 needs none (its log stays absent); one whose record was lost does."""

    return (base / RATING_SCALE_LOG_FILENAME).exists() or any(
        base.glob(BACKUP_TEMPLATE.format(season="*"))
    )


def _log_conversion(
    base: Path,
    season: str,
    plan: MovePlan,
    generation: int,
    backup: Optional[Path],
    pools: List[str],
    event_name: str = "converted",
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "event": event_name,
        "season": season,
        "at": _now(),
        "scale": FULL_RATING_SCALE,
        "engine_generation": generation,
        "players": len(plan.rows),
        "players_converted": plan.to_convert,
        "backup": backup.name if backup else None,
        "draft_pools": pools,
        "clips": [
            {"player_id": c.player_id, "key": c.key, "kind": c.kind,
             "engine": c.engine_value, "unclipped": round(c.unclipped, 2), "stored": c.stored}
            for c in plan.clips
        ],
        "summary": _scale_summary(plan),
    }
    if plan.respread is not None:
        _add_stored_ranges(plan)
        event["respread"] = {
            "seed": RESPREAD_SEED,
            "rule": f"ACT sd below {BUNCHED_SD_RATIO} of the reference league's",
            "reference": load_respread_reference().get("source"),
            "ratings": [r.as_log() for r in plan.respread.moved],
            "left_alone": [
                {"group": r.group, "key": r.key, "act_sd": round(r.league_sd, 2),
                 "reference_act_sd": round(r.reference_sd, 2)}
                for r in plan.respread.ratings if not r.bunched
            ],
        }
    return _append_log(base, event)


def _add_stored_ranges(plan: MovePlan) -> None:
    """For each re-spread rating, the ACT range on the scale owners see:
    the stretch of the original value against the stretch of the
    re-spread one (``stored_range_unspread`` / ``stored_range``)."""

    if plan.respread is None:
        return
    by_id = {str(r.get("player_id")): r for r in plan.rows}
    spread = {str(r.get("player_id")): r for r in plan.respread.rows}
    for entry in plan.respread.moved:
        pitcher = entry.group == "pitcher"
        spec = rating_map(entry.key, FULL_RATING_SCALE, pitcher=pitcher)
        before, after = [], []
        for pid, row in spread.items():
            if _group(row) != entry.group or not _counts_as_active(pid, plan.active_ids):
                continue
            old, new = _value(by_id[pid], entry.key), _value(row, entry.key)
            if old is None or new is None:
                continue
            if spec is not None:
                old, new = spec.stored(old), spec.stored(new)
            before.append(max(1, min(99, int(math.floor(old + 0.5)))))
            after.append(max(1, min(99, int(math.floor(new + 0.5)))))
        if before:
            entry.stored_range_unspread = [min(before), max(before)]
            entry.stored_range = [min(after), max(after)]


def log_refusal(base: Path | str, season: str, reason: str, generation: int) -> Dict[str, Any]:
    """Record that ``season`` could not move and was given ``generation``."""

    return _append_log(Path(base), {
        "event": "refused", "season": str(season), "at": _now(),
        "reason": reason, "engine_generation": generation,
    })


def _scale_summary(plan: MovePlan) -> Dict[str, Any]:
    """Top and average of the headline ratings, before and after, over the
    ACT players (every player when there are no rosters): the numbers the
    news item quotes."""

    out: Dict[str, Any] = {}
    # Before = the engine values the stretch was given (after a re-spread,
    # where there was one: the scale change is the stretch alone).
    pairs = list(zip(plan.sources or plan.rows, plan.converted))
    for group, key, label in _HEADLINES:
        before, after = [], []
        for old, new in pairs:
            if _group(old) != group or not _counts_as_active(
                str(old.get("player_id") or ""), plan.active_ids
            ):
                continue
            o, n = _value(old, key), _value(new, key)
            if o is None or n is None:
                continue
            before.append(o)
            after.append(n)
        if before:
            out[label] = {
                "before_max": max(before), "after_max": max(after),
                "before_mean": round(statistics.fmean(before), 1),
                "after_mean": round(statistics.fmean(after), 1),
            }
    return out


_HEADLINES = (
    ("hitter", "ch", "Contact"),
    ("hitter", "ph", "Power"),
    ("hitter", "eye", "Eye"),
    ("hitter", "fa", "Fielding"),
    ("pitcher", "control", "Control"),
    ("pitcher", "movement", "Movement"),
    ("pitcher", "arm", "Arm"),
)


# ---------------------------------------------------------------------------
# News (drafted here; posted only by a move, which needs the switch on)
# ---------------------------------------------------------------------------

def engine_and_scale_news(
    summary: Mapping[str, Any],
    *,
    players: int,
    season: str,
    backup: Optional[str],
    previous_generation: Optional[int],
) -> str:
    """The news item every league gets when it moves (numbers from its
    own log record)."""

    def pair(label: str) -> str:
        item = summary.get(label)
        if not item:
            return ""
        return f"{label} {_n(item['before_max'])} to {_n(item['after_max'])}"

    tops = [p for p in (pair(l) for _, _, l in _HEADLINES[:2] + _HEADLINES[4:5]) if p]
    from_legacy = previous_generation is not None and previous_generation < 5
    engine = (
        "Pitch grades now drive a pitcher's stuff and velocity, tired pitchers "
        "lose velocity and command, Power pays off at the top of the scale, "
        "doubles come from contact and line drives, and fielding is judged "
        "against the regulars at each position, with errors at a big-league "
        "rate."
    )
    if from_legacy:
        engine = (
            "Strikeouts, walks and contact are sharper skills, home teams have a "
            "small edge and managers issue intentional walks. " + engine
        )
    text = (
        f"Season {season}: the league now plays on the updated game engine, and "
        "every rating is shown on the full 1-99 scale. Nobody got better or "
        "worse: each player keeps his place, and a rating plays exactly as "
        "before, it is just spread out so the best players read in the 80s and "
        "90s and an average regular about 50. "
    )
    if tops:
        text += "The league's best ratings went from " + ", ".join(tops) + ". "
    text += f"{players} players were converted. {engine}"
    return text


def respread_news(record: Mapping[str, Any], *, league: str, season: str) -> str:
    """The separate news item for a league whose bunched ratings were
    re-spread (decision 15: it changes how that league plays)."""

    moved = record.get("respread", {}).get("ratings", [])
    names = {
        ("hitter", "eye"): "hitters' Eye", ("hitter", "fa"): "fielding",
        ("hitter", "arm"): "throwing arms", ("hitter", "gf"): "hitters' ground-ball tendency",
        ("hitter", "pl"): "pull tendency", ("hitter", "ch"): "Contact",
        ("hitter", "ph"): "Power", ("hitter", "sp"): "speed",
        ("pitcher", "control"): "pitchers' Control", ("pitcher", "movement"): "Movement",
        ("pitcher", "arm"): "pitchers' Arm", ("pitcher", "endurance"): "stamina",
        ("pitcher", "hold_runner"): "holding runners", ("pitcher", "fa"): "pitchers' fielding",
        ("pitcher", "gf"): "pitchers' ground-ball tendency",
    }
    parts = []
    for item in moved:
        name = names.get((item["group"], item["key"]), item["key"])
        lo, hi = item.get("stored_range") or item["act_range_after"]
        olo, ohi = item.get("stored_range_unspread") or item["act_range_before"]
        parts.append(f"{name} {_n(lo)}-{_n(hi)} (would have been {_n(olo)}-{_n(ohi)})")
    listing = "; ".join(parts) if parts else "none"
    stamina = any(i["group"] == "pitcher" and i["key"] == "endurance" for i in moved)
    return (
        f"Season {season}: {league}'s ratings were spread out. When this league "
        "was created, several ratings came out almost the same for every "
        "player, so they made little difference on the field. They have been "
        "spread to match a normal league, keeping every player's order and the "
        "league's averages, so the run level stays where it was but the best "
        "and worst players now stand apart. On the new scale, across the "
        f"active rosters: {listing}."
        + (
            " Stamina now follows each staff's rotation: starters can go "
            "deeper, relievers tire sooner."
            if stamina
            else ""
        )
        + " This changes how this league plays, on top of the engine and "
        "rating-scale update everyone gets."
    )


def refusal_news(reason: str, *, season: str) -> str:
    return (
        f"Season {season} starts on the current game engine and the current "
        "rating scale: the league's ratings could not be moved to the full "
        f"1-99 scale ({reason}). The commissioner can contact support; the "
        "league will be offered the update again at the start of next season."
    )


def _post_move_news(
    base: Path, plan: MovePlan, record: Mapping[str, Any], previous_generation: Optional[int]
) -> List[str]:
    items = [
        engine_and_scale_news(
            record.get("summary", {}), players=len(plan.rows), season=str(record.get("season")),
            backup=record.get("backup"), previous_generation=previous_generation,
        )
    ]
    if plan.respread is not None and plan.respread.moved:
        items.append(respread_news(record, league=league_id_of(base), season=str(record.get("season"))))
    for item in items:
        _post_news(base, item)
    return items


def _post_news(base: Path, text: str, category: str = "league") -> None:
    try:
        from utils.news_logger import log_news_event

        log_news_event(text, category=category, file_path=base / _NEWS_FILE)
    except Exception:  # pragma: no cover - news must never stop a game
        _LOGGER.exception("could not post a rating-scale news item")


def post_refusal(base: Path | str, season: str, reason: str, generation: int) -> str:
    """Tell the commissioner (news, the log, the operator's stdout)."""

    base = Path(base)
    log_refusal(base, season, reason, generation)
    text = refusal_news(reason, season=str(season))
    _post_news(base, text, category="commissioner")
    _print(f"{base}: season {season} NOT moved to generation 6 / scale 2: {reason}")
    return text


def _n(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number == int(number) else f"{number:.1f}"


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def rollback_league(
    base: Path | str,
    *,
    mode: str = "backup",
    season: Optional[str] = None,
) -> Dict[str, Any]:
    """Put a converted league's players back on scale 1.

    ``mode`` "backup": restore ``players.scale1.<season>.csv`` (the file as
    it was at the conversion; anything that happened to players since --
    injuries, trades, signings, draft picks -- is lost). "inverse": un-stretch
    today's file in place with the exact inverse map (``engine_row``):
    every change since is kept; a value developed since the conversion
    comes back fractional and is rounded half up (at most half an engine
    point), a potential keeps its gap; a re-spread is NOT undone (use the
    backup). Open draft pools are put back the same way. The league is
    put on HOLD (``"hold"`` in ``rating_scale.json``): it is neither
    repaired nor moved again at its next season until an operator removes
    the key, so a league left on generation 6 stays on scale 1 (and plays
    correctly: scale is play-neutral). The engine generation is NOT changed
    here (a season in play must never change engine):
    :func:`set_recorded_generation` and the runbook.
    """

    base = Path(base)
    path = base / _PLAYERS
    log = read_scale_log(base)
    if season is None:
        conversions = [e for e in log.get("events", []) if e.get("event") == "converted"]
        if not conversions:
            raise MoveRefused("rating_scale.json records no conversion")
        season = str(conversions[-1].get("season"))
    with _move_guard(base):
        if mode == "backup":
            backup = base / BACKUP_TEMPLATE.format(season=season)
            if not backup.exists():
                raise MoveRefused(f"{backup.name} is missing; use mode 'inverse'")
            _write_bytes_atomic(path, backup.read_bytes())
            pools = []
            for pool_backup in sorted(base.glob(f"draft_pool_*.scale1.{season}.*")):
                year, ext = pool_backup.name.split(".")[0], pool_backup.suffix
                target = base / f"{year}{ext}"
                _write_bytes_atomic(target, pool_backup.read_bytes())
                pools.append(target.name)
            rows = len(_read_rows(path)[1])
        elif mode == "inverse":
            fieldnames, rows_in = _read_rows(path)
            out = [_unstretch(r) for r in rows_in]
            header = [f for f in players_fieldnames(fieldnames, scale2=False) if f != RATING_SCALE_FIELD]
            from utils.atomic_write import atomic_text_writer

            with atomic_text_writer(path, newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=header)
                writer.writeheader()
                for row in out:
                    writer.writerow({k: row.get(k, "") for k in header})
            pools = []
            for pool in sorted(base.glob("draft_pool_*")):
                if not _POOL_RE.match(pool.name):
                    continue
                if pool.suffix == ".json":
                    records = json.loads(pool.read_text(encoding="utf-8"))
                    if not any(isinstance(r, dict) and rating_scale_of(r) != 1 for r in records):
                        continue
                    back = [_unstretch(r) if isinstance(r, dict) else r for r in records]
                    for r in back:
                        if isinstance(r, dict):
                            r.pop(RATING_SCALE_FIELD, None)
                    _write_bytes_atomic(pool, json.dumps(back, indent=2).encode("utf-8"))
                else:
                    fn, prow = _read_rows(pool)
                    if not any(rating_scale_of(r) != 1 for r in prow):
                        continue
                    hdr = [f for f in fn if f != RATING_SCALE_FIELD]
                    buffer = io.StringIO()
                    writer = csv.DictWriter(buffer, fieldnames=hdr)
                    writer.writeheader()
                    for r in prow:
                        r = _unstretch(r)
                        writer.writerow({k: r.get(k, "") for k in hdr})
                    _write_bytes_atomic(pool, buffer.getvalue().replace("\r\n", "\n").encode("utf-8"))
                pools.append(pool.name)
            rows = len(out)
        else:
            raise ValueError(f"unknown rollback mode {mode!r}")
        event = _append_log(base, {
            "event": "rolled_back", "season": season, "at": _now(), "mode": mode,
            "players": rows, "draft_pools": pools,
        })
        payload = read_scale_log(base)
        payload["scale"] = LEGACY_RATING_SCALE
        # The league stays on scale 1 until an operator removes this
        # (plan_move): no repair, and no move at its next season.
        payload["hold"] = {"since": event["at"], "reason": f"rolled back ({mode})"}
        _write_bytes_atomic(
            base / RATING_SCALE_LOG_FILENAME,
            json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
        )
        _clear_player_caches()
        return event


def set_recorded_generation(base: Path | str, season: str, generation: int) -> Dict[str, Any]:
    """Rewrite the engine generation written down for ``season`` -- the
    season's ``rating_centers.json`` entry AND the witness in
    ``season_progress.json`` -- to ``generation``. An OPERATOR step only
    (``scripts/rating_scale_rollback.py --generation``): the product never
    changes a season's engine once it is recorded, and the working copy
    refuses to push a lower generation over a higher one, so this is run on
    the durable copy with every instance stopped (the runbook). The
    season's centres are kept; a generation 6 season's extra centres stay
    in the entry, unread below generation 6."""

    base = Path(base)
    season = str(season)
    centres_path = base / "rating_centers.json"
    payload = json.loads(centres_path.read_text(encoding="utf-8"))
    entry = payload.setdefault("seasons", {}).setdefault(season, {})
    before = {"rating_centers.json": entry.get("engine_generation")}
    entry["engine_generation"] = int(generation)
    _write_bytes_atomic(
        centres_path, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    )
    progress_path = base / "season_progress.json"
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        progress = {}
    witness = progress.get("engine_generation")
    before["season_progress.json"] = witness
    progress["engine_generation"] = {"season": season, "generation": int(generation)}
    _write_bytes_atomic(progress_path, json.dumps(progress, indent=2).encode("utf-8"))
    return _append_log(base, {
        "event": "generation_set", "season": season, "at": _now(),
        "engine_generation": int(generation), "before": before,
    })


def _unstretch(row: Mapping[str, Any]) -> Dict[str, Any]:
    """A scale 2 row as a scale 1 row: ``engine_row``, then each moved value
    rounded half up to a whole engine point (scale 1 stores integers)."""

    scale = rating_scale_of(row)
    flat = dict(engine_row(row))
    if scale != LEGACY_RATING_SCALE:
        pitcher = is_pitcher_flag(row.get("is_pitcher"))
        for key in list(flat):
            base_key = key[4:] if key.startswith("pot_") else key
            if rating_map(base_key, FULL_RATING_SCALE, pitcher=pitcher) is None:
                continue
            value = _value(flat, key)
            if value is None:
                continue
            whole = int(value + 0.5)
            flat[key] = str(whole) if isinstance(row.get(key), str) else whole
    if SCALE2_HEIGHT_FIELD in flat:
        flat[HEIGHT_FIELD] = flat.pop(SCALE2_HEIGHT_FIELD)
    flat.pop(RATING_SCALE_FIELD, None)
    return flat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def league_id_of(base: Path | str) -> str:
    """The league id of a league data directory (``.../leagues/<id>/data``),
    or the directory's own name for any other layout."""

    base = Path(base)
    if base.name == "data" and base.parent.parent.name == "leagues":
        return base.parent.name
    return base.name


def _read_rows(path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def _active_ids(base: Path) -> Optional[set]:
    """Every ACT player id of the league; ``None`` with no rosters."""

    roster_dir = Path(base) / "rosters"
    if not roster_dir.is_dir():
        return None
    from services.league_rating_centers import _active_ids_by_team

    return {pid for ids in _active_ids_by_team(roster_dir).values() for pid in ids}


def _rotation_ids(base: Path) -> set:
    """The clubs' five-man rotations, as a game builds them."""

    from services.league_rating_centers import (
        _STARTER_WORKLOAD,
        active_pitcher_workloads,
    )

    return {
        str(row.get("player_id"))
        for row, weight in active_pitcher_workloads(base)
        if weight >= _STARTER_WORKLOAD
    }


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _clear_player_caches() -> None:
    try:
        from utils.player_loader import load_players_from_csv

        load_players_from_csv.cache_clear()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive
        pass
    clear_caches()


@contextmanager
def _move_guard(base: Path) -> Iterator[None]:
    """The league's move lock (one conversion at a time, across processes)
    inside the working copy's background-writer guard (a shutdown flush
    never pushes half a move)."""

    try:
        from api.working_copy import background_writer

        guard = background_writer("rating-scale move")
    except Exception:  # pragma: no cover - no API package (tools)
        guard = nullcontext()
    lock = Path(base) / _LOCK_NAME
    with guard:
        _acquire(lock)
        try:
            yield
        finally:
            try:
                lock.unlink()
            except OSError:
                pass


def _acquire(lock: Path) -> None:
    deadline = time.monotonic() + 30.0
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {_now()}".encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                continue
            if age > _STALE_LOCK_SECONDS:
                _print(f"breaking a stale rating-scale move lock {lock} ({age:.0f}s old)")
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() > deadline:
                raise MoveRefused(f"another conversion of this league holds {lock.name}")
            time.sleep(0.05)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _print(message: str) -> None:
    """To the log and stdout (Cloud Run shows stdout, not the app log)."""

    _LOGGER.warning(message)
    try:
        print(f"[rating-scale] {message}", flush=True)
    except Exception:  # pragma: no cover
        pass


def describe_counts(base: Path | str) -> str:
    from utils.rating_scale import players_file_rating_scales

    return describe_rating_scales(players_file_rating_scales(Path(base) / _PLAYERS))


__all__ += [
    "clear_caches", "describe_counts", "log_refusal", "post_refusal",
    "set_recorded_generation",
]
