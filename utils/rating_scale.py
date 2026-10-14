"""Rating scales: how a stored rating relates to the rating the engine plays.

The engine, the rating centres and every CPU decision were built on ratings
bunched around 50 (no hitter above 65 Power in any league). Owner decision 5
(``docs/audits/2026-10-06-engine-ratings-audit/DECISIONS.md``, "Release 6
owner decisions") moves STORED ratings to the full 1-99 scale without
changing how anyone plays. This module is the whole of that relationship
(``RATING_SCALE_DESIGN.md`` sections 1, 2, 4 and 6):

* **Scale 1**, the legacy scale: the stored rating is the engine rating.
  Every league is on it today, and a row with no ``rating_scale`` value is
  on it.
* **Scale 2**, the full scale: each moved rating is stored through a fixed,
  piecewise-linear map with integer slopes, ``stored = 50 + k * (engine -
  pivot)``, ``k`` chosen by segment. Integer slopes make the map exactly
  invertible: every integer engine rating whose image lies inside 1-99 comes
  back as the same number.

The scale belongs to the DATA, one row at a time (the ``rating_scale``
column of ``players.csv``), not to the engine generation and not to a
sidecar file: a stale file pushed back by an old instance, a restored backup
or an archived season then still plays correctly on its own scale.

**What holds which value.** ``models.player.Player`` /
``models.pitcher.Pitcher`` objects and every row on disk hold STORED values;
``player.rating_scale`` says which scale they are on. Code that feeds the
game or a decision never reads a moved rating off an object or a row
directly; it goes through one of:

* :func:`engine_row` -- a ``players.csv`` row as the engine reads it (the
  row boundary: ``physics_sim.models``, the rating centres, the KPI
  harness);
* :func:`engine_rating` / :func:`engine_potential` -- one rating of a player
  object or a row, on the engine scale (every consumer outside the engine:
  overall rating, salaries, trades, roster and lineup automation, the
  draft).

On a scale 1 row all three return what is stored, untouched, the same
object where there is one, so nothing changes for a league that is not on
scale 2. ``tests/test_rating_scale_reads.py`` walks the code for reads of a
moved rating that go round these.

**Potentials** are not mapped. A scale 2 potential keeps the player's GAP in
points (:func:`stretch_row`): the gap the generator rolled, in engine
points. :func:`engine_row` gives the engine the engine view of the current
rating plus that whole gap (a scale 1 row, as it was converted). The
consumer accessor :func:`engine_potential` gives what the development model
(``playbalance.development``) can still make of the player: the engine
rating plus the gap less :data:`POTENTIAL_GAP_DISCOUNT`, the generator's
optimism no player closes. So a CPU club values a young player's upside as
far as development will deliver it; on scale 1 nothing changes.

Nothing here makes a league scale 2 while the switch below is off:
:data:`GENERATED_RATING_SCALE` is 1.

**The 8.0.0 operations switch** (:data:`GENERATION6_SWITCH_ENV`, OFF unless
the service's environment sets it) is read here because it is about the
data: with it on, a new league and its draft classes are generated on scale
2 (:func:`generated_rating_scale`), engine generation 6 becomes a generation
a league season may be given (``physics_sim.engine_generation``), and a
league moves to both at the start of its next season
(``services.rating_scale_migration``). Off, nothing anywhere differs from
7.51.

**The scale 2 file format.** A ``players.csv`` holding any scale 2 row
names its height column :data:`SCALE2_HEIGHT_FIELD` (``height_in``) instead
of ``height``. Builds before 8.0.0 require ``height`` on every row
(``_required_int(row, "height")`` in their ``utils.player_loader``), so they
REFUSE such a file -- every page and game of that league fails loudly --
instead of loading stretched ratings as engine ratings and saving them back
without the ``rating_scale`` column. This build reads either name
(:func:`row_height`). A row with a blank ``height_in`` in such a file was
appended by an older build's draft (it copies the file's header and leaves
the columns it does not know blank); it is refused too
(``utils.player_loader``), because its ratings cannot be trusted.

This module imports only the standard library, so the models, the loaders,
the engine, the services and the scripts can all read it.
"""

from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
)

__all__ = [
    "FULL_RATING_SCALE",
    "GENERATED_RATING_SCALE",
    "GENERATION6_SWITCH_ENV",
    "HEIGHT_FIELD",
    "SCALE2_HEIGHT_FIELD",
    "generated_rating_scale",
    "generation6_switch_on",
    "players_fieldnames",
    "row_height",
    "KNOWN_RATING_SCALES",
    "LEGACY_RATING_SCALE",
    "MIXED_RATING_SCALES",
    "MixedRatingScaleError",
    "POTENTIAL_GAP_DISCOUNT",
    "describe_rating_scales",
    "RATING_MAX",
    "RATING_MIN",
    "RATING_SCALE_FIELD",
    "RatingClip",
    "RatingMap",
    "engine_potential",
    "engine_potential_value",
    "engine_rating",
    "engine_value",
    "engine_row",
    "engine_rows",
    "is_pitcher_flag",
    "majority_rating_scale",
    "moved_rating_keys",
    "normalize_rating_scale",
    "player_is_pitcher",
    "players_file_rating_scale",
    "players_file_rating_scales",
    "rating_map",
    "rating_scale_counts",
    "rating_scale_of",
    "stretch_row",
    "stretch_rows",
    "to_engine",
    "to_stored",
    "to_stored_exact",
]

LEGACY_RATING_SCALE = 1
FULL_RATING_SCALE = 2
KNOWN_RATING_SCALES: Tuple[int, ...] = (LEGACY_RATING_SCALE, FULL_RATING_SCALE)
# The scale a NEW league is created on while the 8.0.0 switch is off (a
# draft class takes the scale of the league it is for). With the switch on,
# :func:`generated_rating_scale` answers scale 2 instead.
GENERATED_RATING_SCALE = LEGACY_RATING_SCALE
# The 8.0.0 operations switch (module docstring). Any of these values turns
# it on; anything else, or no value, leaves it off.
GENERATION6_SWITCH_ENV = "NEXGEN_GENERATION6_SCALE2"
_SWITCH_ON_VALUES = frozenset({"1", "on", "true", "yes"})
# The operations hold on new seasons' engine
# (``services.league_rating_centers.NEW_SEASON_ENGINE_ENV``) and the
# generations it can hold a league on below generation 6 (the legacy engine
# 4 and generation 5; ``physics_sim.engine_generation``).
NEW_SEASON_ENGINE_ENV = "NEXGEN_NEW_SEASON_ENGINE"
_GENERATIONS_BELOW_6 = frozenset({4, 5})

RATING_SCALE_FIELD = "rating_scale"
# The height column of a players.csv: ``height`` in a file on scale 1 only,
# ``height_in`` in a file holding any scale 2 row (module docstring).
HEIGHT_FIELD = "height"
SCALE2_HEIGHT_FIELD = "height_in"
# What :func:`players_file_rating_scale` answers for a file whose rows are
# not all on one scale.
MIXED_RATING_SCALES = "mixed"
RATING_MIN = 1
RATING_MAX = 99
_POTENTIAL_PREFIX = "pot_"
# Engine points of every scale 2 potential gap that development never
# closes (``playbalance.development``; the generator rolls a young player's
# potential 10-30 over his talent). :func:`engine_potential` leaves them out.
POTENTIAL_GAP_DISCOUNT = 20.5


class MixedRatingScaleError(ValueError):
    """A set of player rows that is not all on one rating scale."""


def generation6_switch_on() -> bool:
    """True when the service runs with the 8.0.0 switch on
    (:data:`GENERATION6_SWITCH_ENV`). Read on every call, so a test or an
    operator can flip it without a restart of this module."""

    raw = str(os.getenv(GENERATION6_SWITCH_ENV, "") or "").strip().lower()
    return raw in _SWITCH_ON_VALUES


def generated_rating_scale() -> int:
    """The scale a NEW league is created on: 2 with the 8.0.0 switch on,
    else :data:`GENERATED_RATING_SCALE` (1).

    The operations hold (:data:`NEW_SEASON_ENGINE_ENV`, ``4`` or ``5``)
    keeps new leagues on scale 1 as well: scale 2 comes only with
    generation 6, and a held league's first season gets the held
    generation. (Read here, with the standard library, as
    ``services.league_rating_centers`` reads it: a value that names no
    generation is ignored there too.)"""

    if not generation6_switch_on():
        return GENERATED_RATING_SCALE
    raw = str(os.getenv(NEW_SEASON_ENGINE_ENV, "") or "").strip()
    try:
        held = int(raw) if raw else None
    except ValueError:
        held = None
    if held in _GENERATIONS_BELOW_6:
        return GENERATED_RATING_SCALE
    return FULL_RATING_SCALE


def players_fieldnames(fieldnames: Iterable[str], *, scale2: bool) -> List[str]:
    """A players.csv header in the format its rows need.

    ``scale2`` True (the file holds any scale 2 row): the height column is
    named :data:`SCALE2_HEIGHT_FIELD` and :data:`RATING_SCALE_FIELD` is
    there, last if it was missing. False: the names as given, ``height_in``
    turned back into ``height`` (a file with no scale 2 row left is written
    in the format every build reads). Order is kept.
    """

    out: List[str] = []
    for name in fieldnames:
        if name in (HEIGHT_FIELD, SCALE2_HEIGHT_FIELD):
            name = SCALE2_HEIGHT_FIELD if scale2 else HEIGHT_FIELD
        if name not in out:
            out.append(name)
    if scale2 and RATING_SCALE_FIELD not in out:
        out.append(RATING_SCALE_FIELD)
    return out


def row_height(row: Mapping[str, Any]) -> Any:
    """The height a players.csv row holds, whichever format its file is in.

    ``height_in`` when the row has that column (a scale 2 file), else
    ``height``; ``None`` when it has neither."""

    if SCALE2_HEIGHT_FIELD in row:
        return row.get(SCALE2_HEIGHT_FIELD)
    return row.get(HEIGHT_FIELD)


@dataclass(frozen=True)
class RatingMap:
    """One rating's map: ``stored = 50 + slope * (engine - pivot)``.

    ``slope_below`` applies under the pivot and ``slope_above`` from it; past
    ``knee`` (an engine rating, where there is one) the slope is 1, which
    keeps the long top tail of Contact, control and movement inside 99.
    """

    pivot: int
    slope_below: int
    slope_above: int
    knee: Optional[int] = None

    @property
    def stored_knee(self) -> Optional[int]:
        if self.knee is None:
            return None
        return 50 + self.slope_above * (self.knee - self.pivot)

    def stored(self, engine_value: float) -> float:
        """The mapped value, not rounded and not clipped."""

        if engine_value < self.pivot:
            return 50 + self.slope_below * (engine_value - self.pivot)
        if self.knee is None or engine_value <= self.knee:
            return 50 + self.slope_above * (engine_value - self.pivot)
        return self.stored_knee + (engine_value - self.knee)

    def engine(self, stored_value: float) -> float:
        """The exact inverse of :meth:`stored`."""

        if stored_value < 50:
            return self.pivot + (stored_value - 50) / self.slope_below
        knee = self.stored_knee
        if knee is None or stored_value <= knee:
            return self.pivot + (stored_value - 50) / self.slope_above
        return self.knee + (stored_value - knee)


# RATING_SCALE_DESIGN.md section 1. Hitters and pitchers are separate tables
# because ``arm`` and ``fa`` mean different things on the two kinds of row.
# NOT moved (already wide, or a tendency): speed, endurance, hold runner,
# every pitch grade, pitcher fielding, vs-left, ground-ball and pull
# tendency, ``sc``, durability.
_HITTER = "hitter"
_PITCHER = "pitcher"
_SCALE_MAPS: Dict[int, Dict[str, Dict[str, RatingMap]]] = {
    LEGACY_RATING_SCALE: {_HITTER: {}, _PITCHER: {}},
    FULL_RATING_SCALE: {
        _HITTER: {
            "ch": RatingMap(50, 2, 3, knee=63),
            "ph": RatingMap(50, 2, 3),
            "eye": RatingMap(50, 3, 5),
            "fa": RatingMap(52, 1, 2),
            "arm": RatingMap(52, 1, 2),
        },
        _PITCHER: {
            "control": RatingMap(52, 2, 3, knee=66),
            "movement": RatingMap(54, 2, 3, knee=68),
            "arm": RatingMap(56, 1, 2),
        },
    },
}
_MOVED_KEYS: Dict[Tuple[int, str], FrozenSet[str]] = {
    (scale, group): frozenset(table)
    for scale, groups in _SCALE_MAPS.items()
    for group, table in groups.items()
}


@dataclass(frozen=True)
class RatingClip:
    """A value :func:`stretch_row` could not store exactly.

    ``kind`` is ``"rating"`` (the map left 1-99; the engine view of the
    stored value is no longer ``engine_value``) or ``"potential"`` (the gap
    was cut at 99). ``source`` names the rating a blank one was filled from
    (``"ch"`` for Eye, ``"fb"`` for a pitcher's arm), else ``""``.
    """

    player_id: str
    key: str
    kind: str
    engine_value: float
    unclipped: float
    stored: int
    source: str = ""


# ---------------------------------------------------------------------------
# The scale of a row / a player
# ---------------------------------------------------------------------------

def normalize_rating_scale(value: object) -> int:
    """``value`` as a scale number; blank means the legacy scale.

    Anything else that is not a known scale raises ``ValueError``. A row on
    a scale this build does not know must never be played as scale 1 in
    silence (that is the 4.36 -> 4.60 runs a game of the design's "no
    un-stretch" row).
    """

    if value is None:
        return LEGACY_RATING_SCALE
    if isinstance(value, bool):
        raise ValueError(f"unknown rating scale {value!r}")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return LEGACY_RATING_SCALE
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"unknown rating scale {value!r}") from None
    if number != number or number != int(number) or int(number) not in KNOWN_RATING_SCALES:
        raise ValueError(f"unknown rating scale {value!r}")
    return int(number)


# type -> is it a row mapping. ``isinstance(x, Mapping)`` goes through the
# abstract base class machinery, several times the cost of the read itself,
# and the accessors below run on every rating a consumer reads.
_ROW_TYPES: Dict[type, bool] = {dict: True}


def _is_row(player: Any) -> bool:
    """True for a row mapping, False for a player object."""

    kind = type(player)
    try:
        return _ROW_TYPES[kind]
    except KeyError:
        known = _ROW_TYPES[kind] = isinstance(player, Mapping)
        return known


def rating_scale_of(player: Any) -> int:
    """The scale a player object or a row mapping is stored on."""

    if _is_row(player):
        raw = player.get(RATING_SCALE_FIELD)
    else:
        raw = getattr(player, RATING_SCALE_FIELD, None)
    if raw is None or raw == "" or raw == LEGACY_RATING_SCALE:
        return LEGACY_RATING_SCALE
    return normalize_rating_scale(raw)


def rating_scale_counts(players: Iterable[Any]) -> Dict[int, int]:
    """scale -> how many of ``players`` (objects or rows) are stored on it.

    A file can hold rows on two scales (half converted, or a row from
    another league appended to it). Every row still reads correctly, because
    it carries its own scale; this is for the code that has to notice.
    """

    seen: Dict[int, int] = {}
    for player in players:
        scale = rating_scale_of(player)
        seen[scale] = seen.get(scale, 0) + 1
    return seen


def describe_rating_scales(counts: Mapping[int, int]) -> str:
    """``"1490 on scale 2, 40 on scale 1"`` for a log line or an error."""

    return ", ".join(
        f"{n} on scale {s}"
        for s, n in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def majority_rating_scale(counts: Mapping[int, int]) -> int:
    """The scale most of a league's rows are on (1 for no rows at all).

    For code that must fabricate or convert rows for a league and so needs
    ONE scale (a draft class, a pick appended to players.csv): a few stray
    rows must not stop the league, and the league is what most of its rows
    are. An even split has no answer and raises
    :class:`MixedRatingScaleError`: that file is a half-done conversion.
    """

    if not counts:
        return LEGACY_RATING_SCALE
    ranked = sorted(counts.items(), key=lambda item: -item[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        raise MixedRatingScaleError(
            "players.csv is split evenly between rating scales "
            f"({describe_rating_scales(counts)}); finish or undo its "
            "conversion before generating or adding players"
        )
    return ranked[0][0]


def is_pitcher_flag(value: object) -> bool:
    """A stored ``is_pitcher`` value as a bool (the loaders' rule)."""

    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def player_is_pitcher(player: Any) -> bool:
    """Which table a player object or a row is mapped by.

    Only the ``is_pitcher`` flag decides, never the position: it is what
    makes a row a ``Pitcher`` in ``utils.player_loader`` and what
    :func:`stretch_row` keyed on when the row was written.
    """

    if _is_row(player):
        return is_pitcher_flag(player.get("is_pitcher"))
    return is_pitcher_flag(getattr(player, "is_pitcher", False))


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------

def _scale_tables(scale: object) -> Dict[str, Dict[str, RatingMap]]:
    return _SCALE_MAPS[normalize_rating_scale(scale)]


def moved_rating_keys(scale: object, *, pitcher: bool) -> FrozenSet[str]:
    """The rating keys ``scale`` stores differently from the engine."""

    return _MOVED_KEYS[(normalize_rating_scale(scale), _PITCHER if pitcher else _HITTER)]


def rating_map(rating_key: str, scale: object, *, pitcher: bool = False) -> Optional[RatingMap]:
    """The map of ``rating_key`` on ``scale``, or ``None`` when not moved."""

    return _scale_tables(scale)[_PITCHER if pitcher else _HITTER].get(rating_key)


def to_stored_exact(
    rating_key: str, engine_value: float, scale: object, *, pitcher: bool = False
) -> float:
    """``engine_value`` on ``scale``: not rounded, not clipped to 1-99."""

    spec = rating_map(rating_key, scale, pitcher=pitcher)
    if spec is None:
        return engine_value
    return spec.stored(engine_value)


def to_stored(
    rating_key: str, engine_value: float, scale: object, *, pitcher: bool = False
) -> float:
    """The value to STORE for an engine rating on ``scale``.

    A moved rating comes back as an integer inside 1-99 (rounded half up; an
    integer engine rating always maps to an integer). Clipping is the
    caller's to notice: compare with :func:`to_stored_exact`, or use
    :func:`stretch_row`, which reports every clipped value. A rating the
    scale does not move comes back as given.
    """

    spec = rating_map(rating_key, scale, pitcher=pitcher)
    if spec is None:
        return engine_value
    return _clip(_round_half_up(spec.stored(engine_value)))


def to_engine(
    rating_key: str, stored_value: float, scale: object, *, pitcher: bool = False
) -> float:
    """The engine rating of a value stored on ``scale`` (the exact inverse).

    Never rounded: the engine runs on fractional ratings already, and
    rounding would hide development until three stored points accumulate.
    """

    spec = rating_map(rating_key, scale, pitcher=pitcher)
    if spec is None:
        return stored_value
    return spec.engine(stored_value)


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _clip(value: int) -> int:
    return max(RATING_MIN, min(RATING_MAX, value))


def _set_number(value: object) -> Optional[float]:
    """A rating that is set, as a float; ``None`` for blank, text or <= 0.

    Zero and blank are "no rating" throughout the data (an unthrown pitch, a
    pitcher's hitting columns), never a rating of 0, so no map touches them.
    """

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    if number != number or number <= 0:
        return None
    return number


def _tidy(value: float) -> float:
    """An integral float as an int, so a rating stretched from an integer
    reads back as exactly what a scale 1 row holds, type included."""

    if value == int(value):
        return int(value)
    return value


def _like(sample: object, value: float) -> object:
    """``value`` in the form ``sample`` was stored in (CSV text or number)."""

    value = _tidy(value)
    if isinstance(sample, str):
        return repr(value)
    return value


# ---------------------------------------------------------------------------
# Rows: players.csv dicts, the generator's player dicts, draft pool entries
# ---------------------------------------------------------------------------

# Ratings the league loader (``utils.player_loader``) borrows from another
# one when they are missing: rating -> (the rating it borrows, which kind of
# row, whether a stored 0 also counts as missing). Each rule is a statement
# about ENGINE ratings.
_LOADER_FALLBACKS: Dict[Tuple[str, str], Tuple[str, bool]] = {
    (_HITTER, "eye"): ("ch", False),  # a blank Eye reads as Contact
    (_PITCHER, "arm"): ("fb", True),  # a missing or 0 arm reads as the fastball
}


def _fill_fallbacks(row: Dict[str, Any], group: str) -> Dict[str, str]:
    """Write the loader's fallbacks into ``row`` (engine scale, in place).

    Returns ``{rating: source}`` for every value filled. A scale 2 row must
    never leave one to the loader: it would borrow a STORED value through
    the wrong rating's map (a blank Eye from stored Contact), and the engine
    and the loader would disagree about the player.
    """

    filled: Dict[str, str] = {}
    for (kind, key), (source, zero_is_missing) in _LOADER_FALLBACKS.items():
        if kind != group:
            continue
        raw = row.get(key)
        missing = raw is None or (isinstance(raw, str) and not raw.strip())
        if not missing and zero_is_missing:
            number = _set_number(raw)
            missing = number is None and _is_zero(raw)
        if not missing:
            continue
        value = _set_number(row.get(source))
        if value is None:
            continue
        sample = row.get(source)
        row[key] = _like(sample, value)
        filled[key] = source
    return filled


def _is_zero(value: object) -> bool:
    try:
        return float(value) == 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def stretch_row(
    row: Mapping[str, Any], scale: object
) -> Tuple[Dict[str, Any], List[RatingClip]]:
    """``row`` re-expressed on ``scale``, and every value that was clipped.

    ``row`` is a ``players.csv`` row (text values) or a generated player
    dict (numbers); values keep the form they came in. A row already on
    ``scale`` is returned as an unchanged copy (conversion is idempotent per
    row); a row on any other scale than 1 is an error. ``scale`` is required:
    nothing should land on scale 2 by default.

    Fallbacks first: a rating the league loader would borrow from another
    one (a blank Eye from Contact, a missing or 0 pitcher arm from his
    fastball) is filled on the ENGINE scale, from the engine value, before
    anything is mapped, and then mapped like any other (a fill that does not
    fit 1-99 is reported, with its ``source``). So the stretched row never
    asks the loader to borrow a stored value through another rating's map,
    and the engine and the loader read the same player. On a scale 1 row the
    engine reads a blank pitcher arm as 50 where the loader reads the
    fastball; every save through ``utils.player_writer`` already writes the
    loader's value, and the conversion does the same.

    Ratings: each moved rating that is set goes through the map; a mapped
    value outside 1-99 is clipped and reported. Other blanks and zeros stay
    as they are ("no rating").

    Potentials (design section 3, item 2): for a moved rating, ``new
    potential = min(99, new current + max(0, old potential - old current))``;
    for every other rating the potential is kept, raised to the current
    rating when it was below it. This has NO exact inverse, by design: a
    potential under current and a gap cut at 99 cannot be recovered (the
    second is reported as a clip of kind ``"potential"``).
    """

    target = normalize_rating_scale(scale)
    current = rating_scale_of(row)
    out = dict(row)
    clips: List[RatingClip] = []
    if current == target:
        return out, clips
    if current != LEGACY_RATING_SCALE:
        raise ValueError(
            f"cannot stretch a row on rating scale {current} to scale {target}"
        )
    pitcher = player_is_pitcher(row)
    group = _PITCHER if pitcher else _HITTER
    table = _scale_tables(target)[group]
    player_id = str(row.get("player_id", "") or "")
    # The engine-scale row being converted, with the loader's fallbacks
    # written in.
    row = dict(row)
    filled = _fill_fallbacks(row, group)
    out = dict(row)

    for key in list(row):
        if not key.startswith(_POTENTIAL_PREFIX):
            continue
        base = key[len(_POTENTIAL_PREFIX):]
        if base in table or base not in row:
            continue
        old_current = _set_number(row.get(base))
        old_potential = _set_number(row.get(key))
        if old_current is None or old_potential is None:
            continue
        if old_potential < old_current:
            out[key] = _like(row[key], old_current)

    for key, spec in table.items():
        if key not in row:
            continue
        engine_value = _set_number(row.get(key))
        if engine_value is None:
            continue
        exact = spec.stored(engine_value)
        stored = _clip(_round_half_up(exact))
        if not RATING_MIN <= exact <= RATING_MAX:
            clips.append(
                RatingClip(
                    player_id, key, "rating", engine_value, exact, stored,
                    filled.get(key, ""),
                )
            )
        out[key] = _like(row[key], stored)
        pot_key = _POTENTIAL_PREFIX + key
        old_potential = _set_number(row.get(pot_key))
        if old_potential is None:
            continue
        wanted = stored + max(0.0, old_potential - engine_value)
        potential = _clip(_round_half_up(wanted))
        if potential < wanted:
            clips.append(
                RatingClip(player_id, pot_key, "potential", old_potential, wanted, potential)
            )
        out[pot_key] = _like(row[pot_key], potential)

    out[RATING_SCALE_FIELD] = (
        str(target) if _row_is_text(row) else target
    )
    return out, clips


def stretch_rows(
    rows: Iterable[Mapping[str, Any]], scale: object
) -> Tuple[List[Dict[str, Any]], List[RatingClip]]:
    """:func:`stretch_row` over ``rows``: the new rows and all the clips."""

    out: List[Dict[str, Any]] = []
    clips: List[RatingClip] = []
    for row in rows:
        new_row, row_clips = stretch_row(row, scale)
        out.append(new_row)
        clips.extend(row_clips)
    return out, clips


def _row_is_text(row: Mapping[str, Any]) -> bool:
    """True for a CSV row (text values), False for a generated player dict."""

    return isinstance(row.get("player_id"), str) and isinstance(
        row.get("is_pitcher"), str
    )


def engine_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """``row`` as the engine reads it: every rating on the engine scale.

    THE row boundary. A scale 1 row (every row today) is returned as it is,
    the same object, so the engine, the centres and the harness read exactly
    what they read before. A row on another scale is copied with its moved
    ratings un-stretched (never rounded), its potentials the engine rating
    plus the whole stored gap (the row as it was converted; the CPU's view,
    :func:`engine_potential`, discounts the gap) and its ``rating_scale``
    cleared, so the result is an honest scale 1 row and converting twice is
    harmless.

    A row of a file in the scale 2 format (``height_in``, module docstring)
    also gets its height back under ``height``, the name the engine reads;
    that is the only change to a scale 1 row of such a file.
    """

    scale = rating_scale_of(row)
    if scale == LEGACY_RATING_SCALE:
        if SCALE2_HEIGHT_FIELD in row and HEIGHT_FIELD not in row:
            out = dict(row)
            out[HEIGHT_FIELD] = row[SCALE2_HEIGHT_FIELD]
            return out
        return row
    table = _scale_tables(scale)[_PITCHER if player_is_pitcher(row) else _HITTER]
    out = dict(row)
    if HEIGHT_FIELD not in row and SCALE2_HEIGHT_FIELD in row:
        out[HEIGHT_FIELD] = row[SCALE2_HEIGHT_FIELD]
    for key, spec in table.items():
        if key not in row:
            continue
        stored = _set_number(row.get(key))
        if stored is None:
            continue
        engine_value = spec.engine(stored)
        out[key] = _like(row[key], engine_value)
        pot_key = _POTENTIAL_PREFIX + key
        stored_potential = _set_number(row.get(pot_key))
        if stored_potential is not None:
            out[pot_key] = _like(
                row[pot_key], engine_value + (stored_potential - stored)
            )
    out[RATING_SCALE_FIELD] = "" if isinstance(row.get(RATING_SCALE_FIELD), str) else None
    return out


def engine_rows(handle: Iterable[str]) -> Iterator[Mapping[str, Any]]:
    """``csv.DictReader`` over an open ``players.csv``, as the engine reads
    it: every row through :func:`engine_row`."""

    for row in csv.DictReader(handle):
        yield engine_row(row)


def players_file_rating_scales(path: Any) -> Dict[int, int]:
    """scale -> rows of a ``players.csv`` on it.

    A file with no ``rating_scale`` column is all scale 1, decided from the
    header alone (``{1: 0}``: the rows are not counted), so a league that
    has never been converted costs one line. ``{}`` for a missing file.
    """

    try:
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if RATING_SCALE_FIELD not in (reader.fieldnames or []):
                return {LEGACY_RATING_SCALE: 0}
            return rating_scale_counts(reader)
    except FileNotFoundError:
        return {}


def players_file_rating_scale(path: Any) -> Any:
    """The one rating scale the rows of a ``players.csv`` are on, or
    :data:`MIXED_RATING_SCALES` when they are on more than one.

    Never raises for a mixed file: each row reads correctly on its own
    scale. 1 for a file with no column, an empty file or a missing one.
    Code that needs one scale anyway uses :func:`majority_rating_scale`
    over :func:`players_file_rating_scales`.
    """

    counts = players_file_rating_scales(path)
    if len(counts) > 1:
        return MIXED_RATING_SCALES
    for scale in counts:
        return scale
    return LEGACY_RATING_SCALE


# ---------------------------------------------------------------------------
# The consumer accessor: one rating of a player, on the engine scale
# ---------------------------------------------------------------------------

_MISSING: Any = object()


def _raw(player: Any, key: str, default: Any) -> Any:
    if _is_row(player):
        return player.get(key, default)
    return getattr(player, key, default)


def engine_value(
    rating_key: str, stored_value: Any, scale: object, *, pitcher: bool = False
) -> Any:
    """One stored value as a consumer reads it: on the engine scale.

    :func:`to_engine` with the data's conventions: a rating ``scale`` does
    not move, a blank, a zero and anything that is not a number come back
    exactly as given (they are "no rating", and each consumer has its own
    fallback for that); a whole-number result is an ``int``. For a caller
    that holds a value and its row's scale but not the row;
    :func:`engine_rating` is this for a player.
    """

    if scale is None or scale == "" or scale == LEGACY_RATING_SCALE:
        return stored_value
    spec = rating_map(rating_key, scale, pitcher=pitcher)
    if spec is None:
        return stored_value
    stored = _set_number(stored_value)
    if stored is None:
        return stored_value
    return _tidy(spec.engine(stored))


def engine_rating(player: Any, key: str, default: Any = None) -> Any:
    """Rating ``key`` of ``player`` on the engine scale.

    ``player`` is a ``Player`` / ``Pitcher`` object or a row mapping, on
    whatever scale its row is on; ``default`` is returned when it has no
    such rating, exactly as ``getattr(player, key, default)`` /
    ``row.get(key, default)`` would. On a scale 1 player this IS that plain
    read, value and type untouched. On another scale a moved rating that is
    set comes back un-stretched (an int when the engine value is a whole
    number, else a float); a rating the scale does not move, a blank and a
    zero come back as stored.

    This is what every consumer that prices, ranks or picks players reads:
    the constants in the salary curve, the trade evaluator, the promotion
    bars and the lineup builder are all in engine points.
    """

    # Scale 1 first and flat: this is every read in every league today.
    if _is_row(player):
        raw_scale = player.get(RATING_SCALE_FIELD)
        if raw_scale is None or raw_scale == "" or raw_scale == LEGACY_RATING_SCALE:
            return player.get(key, default)
    else:
        raw_scale = getattr(player, RATING_SCALE_FIELD, None)
        if raw_scale is None or raw_scale == LEGACY_RATING_SCALE or raw_scale == "":
            return getattr(player, key, default)
    scale = normalize_rating_scale(raw_scale)
    if scale == LEGACY_RATING_SCALE:
        return _raw(player, key, default)
    value = _raw(player, key, _MISSING)
    if value is _MISSING:
        # The caller's fallback is its own, already an engine number.
        return default
    return engine_value(key, value, scale, pitcher=player_is_pitcher(player))


def engine_potential(player: Any, key: str, default: Any = None) -> Any:
    """The potential of rating ``key`` of ``player``, on the engine scale.

    Read from ``player.potential[key]`` on an object and from
    ``row["pot_<key>"]`` on a mapping; ``default`` when there is none. On a
    scale 1 player that stored value is returned untouched.

    On scale 2 it is the engine view of the current rating plus the part of
    the stored gap (engine points) the development model closes
    (:func:`engine_potential_value`). It is deliberately not the map's
    inverse of the stored potential: the gap is in engine points already.
    """

    if _is_row(player):
        value = player.get(_POTENTIAL_PREFIX + key, _MISSING)
    else:
        blob = getattr(player, "potential", None)
        value = blob.get(key, _MISSING) if isinstance(blob, Mapping) else _MISSING
    if value is _MISSING:
        return default  # the caller's own fallback, not a stored potential
    return engine_potential_value(player, key, value)


def engine_potential_value(player: Any, key: str, stored_potential: Any) -> Any:
    """:func:`engine_potential` for a potential the caller has already read
    (some consumers look in more than one place for it): ``stored_potential``
    of rating ``key`` of ``player``, on the engine scale. A scale 1 player
    and an unset value come back as given.

    On scale 2 this is what the player can still become under the
    development model (``playbalance.development``): his engine rating plus
    the part of his stored gap that development closes, the gap less
    :data:`POTENTIAL_GAP_DISCOUNT` engine points. For every rating, moved
    or not. A scale 2 gap is in engine points (the generator's roll, kept
    by :func:`stretch_row`), and the first 20.5 of them are the generator's
    optimism, which no player closes; reading the whole gap would show a
    CPU club 20 points of upside in every young player that never come.
    """

    scale = rating_scale_of(player)
    if scale == LEGACY_RATING_SCALE:
        return stored_potential
    spec = _scale_tables(scale)[
        _PITCHER if player_is_pitcher(player) else _HITTER
    ].get(key)
    potential = _set_number(stored_potential)
    stored = _set_number(_raw(player, key, None))
    if potential is None or stored is None:
        return stored_potential
    engine_now = stored if spec is None else spec.engine(stored)
    closable = max(0.0, potential - stored - POTENTIAL_GAP_DISCOUNT)
    return _tidy(engine_now + closable)
