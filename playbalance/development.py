"""Player development on the full rating scale (rating scale 2).

Replaces, for players stored on rating scale 2 only, both the yearly aging
table (paused since 7.51.2) and the rating gains of spring training
(``RATING_SCALE_DESIGN.md`` section 3; Release 6 owner decisions 12 and 14).
Players on scale 1 never reach this module: their aging stays paused and
their training camp runs exactly as in 7.51.2.

Once a year, at the season rollover, every scale 2 player:

* **grows** in each rating while he is younger than that rating's peak age
  (about 30): he closes a share of his gap to potential, a share that rises
  with age, with a little seeded noise.
* **declines** from the peak age on, a few stored points a year and more
  each year, and his potential follows his rating down. A potential is never
  below the current rating, and every rating stays inside 1-99.
* **trains**: the year's growth is shared out between his ratings by his
  team's training focus, and so is the year's decline. Training adds no
  points of its own: a focus on Contact moves growth from his other ratings
  into Contact and the total is unchanged.
* **is helped by his club's budgets**: the development and training budgets
  speed his growth, and the development budget slows his decline. Growth
  never passes what his potential allows, so no budget makes a 99.

**What a scale 2 potential means.** The potential column keeps the gap the
player generator rolled, in ENGINE points (``utils.rating_scale.stretch_row``
keeps the gap "in points"; the generator rolls it on the engine scale, 10 to
30 points over a young player's talent). So a player's ceiling, on the engine
scale, is his engine rating plus his stored gap, and that is what
``utils.rating_scale.engine_potential`` returns. Growth is therefore worked
out on the engine scale and stored through the rating's map: a year's gain
of 1 engine point is about 3 stored points of Contact or 5 of Eye above
average, 1 of speed. Measured in stored points the same rule would leave
Eye unable to hold its level (draft potentials average 48 stored against
regulars at 57), whatever the growth rate.

**Not every point of a potential is real.** The generator's potentials are
optimistic by construction (10-30 over talent for every young player), and
a young player in a league today is already as good as a veteran. A player
closes his gap only beyond ``gap_discount`` engine points, and only
``realization`` of that: a draft pick (rated well under his talent, gap
about 30) grows back to about his talent by his late twenties, while a
21-year-old who is already a regular grows little. This is what keeps the
league's average and spread where the scale put them (the stationarity gate
of the design, ``scripts/development_population_sim.py``) without any
league-wide correction.

Decline is in stored points: the scale gives each moved rating about the
same spread in stored points, so the same loss means the same to every
rating.

Randomness is seeded per player and season (``random.Random`` on a string),
so the same rollover always gives the same result, whatever order the rows
are in and whatever ``PYTHONHASHSEED`` is.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple

from utils.rating_scale import (
    FULL_RATING_SCALE,
    RATING_MAX,
    RATING_MIN,
    player_is_pitcher,
    rating_map,
    rating_scale_of,
)

__all__ = [
    "DEFAULT_PARAMS",
    "DevelopmentParams",
    "DevelopmentResult",
    "PITCH_KEYS",
    "RatingCurve",
    "decline_points",
    "develop_player",
    "develop_row",
    "developed_keys",
    "focus_factors",
    "growth_share",
    "is_developed",
    "params_with",
    "summarize",
]

PITCH_KEYS: Tuple[str, ...] = ("fb", "cu", "cb", "sl", "si", "scb", "kn")
_POT = "pot_"


@dataclass(frozen=True)
class RatingCurve:
    """How one rating grows and declines.

    ``peak`` is the first age at which the rating no longer grows: from it
    on the rating loses ``decline + decline_step * (age - peak)`` stored
    points a year (before noise and budget). ``growth`` scales the share of
    the gap closed each year (:func:`growth_share`).
    """

    peak: int = 30
    growth: float = 1.0
    decline: float = 0.6
    decline_step: float = 0.45
    # This rating's own diminishing returns (``DevelopmentParams.level_power``
    # when None).
    level_power: Optional[float] = None


@dataclass(frozen=True)
class DevelopmentParams:
    """The model's sizes (module docstring). One set for every league."""

    # Engine points of every gap that are never closed, and the share of
    # the rest a player closes by his peak if he develops at an average rate.
    gap_discount: float = 12.0
    # The share of the remaining closable gap closed in a year:
    # ``share_base`` at ``share_age``, rising ``share_step`` a year, never
    # above ``share_max``; scaled by the rating's ``growth``.
    share_base: float = 0.12
    share_age: int = 18
    share_step: float = 0.015
    share_max: float = 0.30
    # Diminishing returns: above ``level_base`` stored points the year's
    # gain is scaled by ((level_top - rating) / (level_top - level_base))
    # ** level_power: the better a player already is, the harder each point.
    level_base: float = 45.0
    level_top: float = 105.0
    level_power: float = 0.0
    # Noise: one "good or bad year" draw shared by every rating of a player,
    # and one per rating, both as a relative sd on the year's change.
    year_noise: float = 0.20
    rating_noise: float = 0.30
    # Training focus: a rating's share of the growth moves with its track's
    # allocation relative to the default allocation, to this power.
    focus_power: float = 0.5
    # Budget multipliers are clamped here (the finance module's own range).
    budget_min: float = 0.85
    budget_max: float = 1.15
    hitter: Mapping[str, RatingCurve] = field(
        default_factory=lambda: {
            "ch": RatingCurve(peak=30, decline=0.7, decline_step=0.45),
            "ph": RatingCurve(peak=30, decline=0.7, decline_step=0.45),
            "eye": RatingCurve(peak=31, decline=0.5, decline_step=0.35),
            "fa": RatingCurve(peak=29, decline=0.7, decline_step=0.40),
            "arm": RatingCurve(peak=29, decline=0.7, decline_step=0.40),
            "sp": RatingCurve(peak=27, decline=0.6, decline_step=0.30),
        }
    )
    pitcher: Mapping[str, RatingCurve] = field(
        default_factory=lambda: {
            "control": RatingCurve(peak=31, decline=0.6, decline_step=0.40),
            "movement": RatingCurve(peak=30, decline=0.7, decline_step=0.45),
            "arm": RatingCurve(peak=29, decline=0.7, decline_step=0.45),
            "endurance": RatingCurve(peak=30, decline=0.5, decline_step=0.30),
            "hold_runner": RatingCurve(peak=31, decline=0.4, decline_step=0.25),
        }
    )
    # Every pitch the pitcher throws (a grade above 0) develops on this.
    pitch: RatingCurve = field(
        default_factory=lambda: RatingCurve(peak=30, decline=0.6, decline_step=0.40)
    )


DEFAULT_PARAMS = DevelopmentParams()


def params_with(base: DevelopmentParams = DEFAULT_PARAMS, **overrides: Any) -> DevelopmentParams:
    """``base`` with fields replaced; ``hitter`` / ``pitcher`` take a dict of
    rating -> dict of :class:`RatingCurve` fields (merged into the base
    curve), ``pitch`` a dict of fields. For tuning runs and tests."""

    values: Dict[str, Any] = {}
    for name, value in overrides.items():
        if name in ("hitter", "pitcher"):
            table = dict(getattr(base, name))
            for key, fields in value.items():
                table[key] = replace(table.get(key, RatingCurve()), **fields)
            values[name] = table
        elif name == "pitch":
            values[name] = replace(base.pitch, **value)
        else:
            values[name] = value
    return replace(base, **values)


# Training tracks (``services.training_settings``) -> the ratings they steer.
_HITTER_TRACK_OF = {
    "ch": "contact",
    "ph": "power",
    "sp": "speed",
    "eye": "discipline",
    "fa": "defense",
    "arm": "defense",
}
_PITCHER_TRACK_OF = {
    "control": "command",
    "movement": "movement",
    "endurance": "stamina",
    "arm": "velocity",
    "hold_runner": "hold",
    **{pitch: "pitch_lab" for pitch in PITCH_KEYS},
}


@dataclass
class DevelopmentResult:
    """One player's year: ``changes`` (rating -> stored points, non-zero
    only), the new stored ``potentials`` and ``focus``, the training track
    that received the most growth ("" when he did not grow)."""

    player_id: str
    age: int
    changes: Dict[str, int]
    potentials: Dict[str, int]
    focus: str = ""


# ---------------------------------------------------------------------------
# Who and what develops
# ---------------------------------------------------------------------------

def is_developed(player: Any) -> bool:
    """True for a player object or a row stored on rating scale 2."""

    return rating_scale_of(player) == FULL_RATING_SCALE


def developed_keys(
    pitcher: bool, params: DevelopmentParams = DEFAULT_PARAMS
) -> Tuple[str, ...]:
    """The ratings the model moves for a hitter or a pitcher (of the pitch
    grades, only the pitches he throws)."""

    if pitcher:
        return tuple(params.pitcher) + PITCH_KEYS
    return tuple(params.hitter)


def track_of(key: str, pitcher: bool) -> str:
    """The training track that steers rating ``key``."""

    return (_PITCHER_TRACK_OF if pitcher else _HITTER_TRACK_OF).get(key, "")


def _curve(key: str, pitcher: bool, params: DevelopmentParams) -> RatingCurve:
    if pitcher:
        if key in PITCH_KEYS:
            return params.pitch
        return params.pitcher[key]
    return params.hitter[key]


def growth_share(
    age: int, curve: RatingCurve, params: DevelopmentParams = DEFAULT_PARAMS
) -> float:
    """The share of the closable gap a player of ``age`` closes in a year
    (before noise and budget); 0 from the rating's peak age on."""

    if age >= curve.peak:
        return 0.0
    share = params.share_base + params.share_step * max(0, age - params.share_age)
    return max(0.0, min(params.share_max, share)) * curve.growth


def level_factor(
    stored: float,
    params: DevelopmentParams = DEFAULT_PARAMS,
    curve: Optional[RatingCurve] = None,
) -> float:
    """How much of a year's gain a player rated ``stored`` still finds."""

    power = params.level_power
    if curve is not None and curve.level_power is not None:
        power = curve.level_power
    if power <= 0 or stored <= params.level_base:
        return 1.0
    room = (params.level_top - stored) / (params.level_top - params.level_base)
    return max(0.0, min(1.0, room)) ** power


def decline_points(age: int, curve: RatingCurve) -> float:
    """Stored points the rating loses at ``age`` (before noise and budget)."""

    if age < curve.peak:
        return 0.0
    return curve.decline + curve.decline_step * (age - curve.peak)


# ---------------------------------------------------------------------------
# Training focus
# ---------------------------------------------------------------------------

def _default_allocations(pitcher: bool) -> Mapping[str, float]:
    from services.training_settings import (
        DEFAULT_HITTER_ALLOCATIONS,
        DEFAULT_PITCHER_ALLOCATIONS,
    )

    return DEFAULT_PITCHER_ALLOCATIONS if pitcher else DEFAULT_HITTER_ALLOCATIONS


def focus_factors(
    weights: Any,
    keys: Tuple[str, ...],
    *,
    pitcher: bool,
    params: DevelopmentParams = DEFAULT_PARAMS,
) -> Dict[str, float]:
    """rating -> how strongly training steers growth into it.

    1 for every rating under the default allocation, or with no weights. A
    track given twice its default share weighs ``2 ** focus_power``.
    ``weights`` is a ``TrainingWeights`` (``hitter_weight`` /
    ``pitcher_weight``) or ``None``.
    """

    if weights is None:
        return {key: 1.0 for key in keys}
    defaults = _default_allocations(pitcher)
    getter = weights.pitcher_weight if pitcher else weights.hitter_weight
    out: Dict[str, float] = {}
    for key in keys:
        track = track_of(key, pitcher)
        default = float(defaults.get(track, 0) or 0) if track else 0.0
        if default <= 0:
            out[key] = 1.0
            continue
        try:
            share = float(getter(track))
        except Exception:
            share = default
        if share <= 0:
            share = default
        out[key] = (share / default) ** params.focus_power
    return out


def _redistribute(
    amounts: Dict[str, float],
    factors: Mapping[str, float],
    caps: Optional[Mapping[str, float]] = None,
) -> Dict[str, float]:
    """``sum(amounts)`` shared out again in proportion to amount * factor.

    The total is kept. With ``caps`` no rating receives more than its cap;
    what it cannot take goes to the others in the same proportions, as far
    as they have room (what nobody has room for is lost).
    """

    total = sum(amounts.values())
    out = {k: 0.0 for k in amounts}
    if total <= 0:
        return out
    weighted = {k: v * factors.get(k, 1.0) for k, v in amounts.items() if v > 0}
    remaining = total
    open_keys = set(weighted)
    while open_keys and remaining > 1e-9:
        weight_sum = sum(weighted[k] for k in open_keys)
        if weight_sum <= 0:
            break
        spill = 0.0
        filled = set()
        for k in sorted(open_keys):
            share = remaining * weighted[k] / weight_sum
            room = (caps[k] - out[k]) if caps is not None else math.inf
            if share >= room:
                out[k] += max(0.0, room)
                spill += share - max(0.0, room)
                filled.add(k)
            else:
                out[k] += share
        if not filled:
            break
        open_keys -= filled
        remaining = spill
    return out


# ---------------------------------------------------------------------------
# Reading and writing a player's stored values
# ---------------------------------------------------------------------------

class _ObjectView:
    """A ``Player`` / ``Pitcher`` object's stored values."""

    def __init__(self, player: Any) -> None:
        self.player = player
        blob = getattr(player, "potential", None)
        if not isinstance(blob, MutableMapping):
            blob = {}
            try:
                player.potential = blob
            except Exception:
                pass
        self.blob = blob

    def current(self, key: str) -> Optional[float]:
        return _number(getattr(self.player, key, None))

    def potential(self, key: str) -> Optional[float]:
        value = _number(self.blob.get(key))
        if value is None:
            value = _number(getattr(self.player, _POT + key, None))
        return value

    def set(self, key: str, current: int, potential: int) -> None:
        setattr(self.player, key, int(current))
        self.blob[key] = int(potential)
        if _number(getattr(self.player, _POT + key, None)) is not None:
            setattr(self.player, _POT + key, int(potential))


class _RowView:
    """A ``players.csv`` row's stored values (text), changed in place."""

    def __init__(self, row: MutableMapping[str, Any]) -> None:
        self.row = row

    def current(self, key: str) -> Optional[float]:
        return _number(self.row.get(key))

    def potential(self, key: str) -> Optional[float]:
        return _number(self.row.get(_POT + key))

    def set(self, key: str, current: int, potential: int) -> None:
        self.row[key] = _like(self.row.get(key), current)
        if _POT + key in self.row:
            self.row[_POT + key] = _like(self.row.get(_POT + key), potential)


def _number(value: Any) -> Optional[float]:
    """A set rating as a float; ``None`` for blank, text, 0 ("no rating")."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:
        return None
    return number


def _like(sample: Any, value: int) -> Any:
    return str(int(value)) if isinstance(sample, str) or sample is None else int(value)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_stochastic(value: float, rng: random.Random) -> int:
    """``value`` to a whole number, up with probability equal to its
    fraction, so a year's expected change is not lost to rounding."""

    low = math.floor(value)
    return int(low + (1 if rng.random() < value - low else 0))


def _player_rng(player_id: str, season: Any) -> random.Random:
    return random.Random(f"development:{season}:{player_id}")


class _Scale:
    """One rating's map between stored points and engine points."""

    def __init__(self, key: str, pitcher: bool) -> None:
        self.spec = rating_map(key, FULL_RATING_SCALE, pitcher=pitcher)

    def engine(self, stored: float) -> float:
        return stored if self.spec is None else self.spec.engine(stored)

    def stored(self, engine: float) -> float:
        return engine if self.spec is None else self.spec.stored(engine)


# ---------------------------------------------------------------------------
# One player's year
# ---------------------------------------------------------------------------

def _develop(
    view: Any,
    *,
    player_id: str,
    pitcher: bool,
    age: int,
    season: Any,
    development: float,
    intensity: float,
    weights: Any,
    params: DevelopmentParams,
) -> DevelopmentResult:
    rng = _player_rng(player_id, season)
    keys = tuple(
        key for key in developed_keys(pitcher, params) if view.current(key) is not None
    )
    development = _clamp(float(development or 1.0), params.budget_min, params.budget_max)
    intensity = _clamp(float(intensity or 1.0), params.budget_min, params.budget_max)
    growth_budget = (development + intensity) / 2.0
    year = 1.0 + rng.gauss(0.0, params.year_noise)

    current: Dict[str, float] = {}
    gap: Dict[str, float] = {}
    scales: Dict[str, _Scale] = {}
    growth: Dict[str, float] = {}  # stored points
    room: Dict[str, float] = {}  # stored points
    decline: Dict[str, float] = {}  # stored points
    for key in keys:
        cur = float(view.current(key))
        pot = view.potential(key)
        current[key] = cur
        gap[key] = 0.0 if pot is None else max(0.0, float(pot) - cur)
        scale = scales[key] = _Scale(key, pitcher)
        curve = _curve(key, pitcher, params)
        noise = max(0.0, year + rng.gauss(0.0, params.rating_noise))
        if age < curve.peak:
            closable = max(0.0, gap[key] - params.gap_discount)
            engine_now = scale.engine(cur)
            engine_gain = (
                closable
                * growth_share(age, curve, params)
                * level_factor(cur, params, curve)
                * growth_budget
                * noise
            )
            top = min(float(RATING_MAX), scale.stored(engine_now + closable))
            room[key] = max(0.0, top - cur)
            growth[key] = min(room[key], max(0.0, scale.stored(engine_now + engine_gain) - cur))
        else:
            # A bad year (noise under 1) is a bigger drop: mirrored.
            decline[key] = decline_points(age, curve) * max(0.0, 2.0 - noise) / development

    factors = focus_factors(weights, keys, pitcher=pitcher, params=params)
    growth = _redistribute(growth, factors, room)
    inverse = {key: 1.0 / max(1e-6, factors.get(key, 1.0)) for key in decline}
    decline = _redistribute(decline, inverse)

    changes: Dict[str, int] = {}
    potentials: Dict[str, int] = {}
    received: Dict[str, float] = {}
    for key in keys:
        cur = current[key]
        scale = scales[key]
        if key in growth:
            new = _clamp(cur + _round_stochastic(growth[key], rng), RATING_MIN, RATING_MAX)
            # The gap is in engine points: what he closed comes off it.
            closed = max(0.0, scale.engine(new) - scale.engine(cur))
            new_gap = max(0.0, gap[key] - closed)
            new_pot = _clamp(new + math.floor(new_gap + 0.5), new, RATING_MAX)
            if growth[key] > 0:
                received[track_of(key, pitcher)] = (
                    received.get(track_of(key, pitcher), 0.0) + growth[key]
                )
        else:
            loss = _round_stochastic(decline.get(key, 0.0), rng)
            new = _clamp(cur - loss, RATING_MIN, RATING_MAX)
            new_pot = new  # past his peak: the potential follows him down
        new, new_pot = int(new), int(new_pot)
        view.set(key, new, new_pot)
        potentials[key] = new_pot
        if new != int(cur):
            changes[key] = new - int(cur)

    focus = max(sorted(received), key=lambda t: received[t]) if received else ""
    return DevelopmentResult(
        player_id=player_id, age=age, changes=changes, potentials=potentials, focus=focus
    )


def develop_player(
    player: Any,
    *,
    age: int,
    season: Any,
    development: float = 1.0,
    intensity: float = 1.0,
    weights: Any = None,
    params: DevelopmentParams = DEFAULT_PARAMS,
) -> DevelopmentResult:
    """One offseason for a ``Player`` / ``Pitcher`` object, in place.

    ``age`` is his age at the rollover, ``season`` the coming season (it
    seeds the noise), ``development`` / ``intensity`` his club's budget
    multipliers (``services.finance_budget_effects``; 1.0 is neutral) and
    ``weights`` his ``TrainingWeights`` (``None``: the default focus).
    Refuses a player not on rating scale 2.
    """

    _require_scale_2(player)
    return _develop(
        _ObjectView(player),
        player_id=str(getattr(player, "player_id", "") or ""),
        pitcher=player_is_pitcher(player),
        age=int(age),
        season=season,
        development=development,
        intensity=intensity,
        weights=weights,
        params=params,
    )


def develop_row(
    row: MutableMapping[str, Any],
    *,
    age: int,
    season: Any,
    development: float = 1.0,
    intensity: float = 1.0,
    weights: Any = None,
    params: DevelopmentParams = DEFAULT_PARAMS,
) -> DevelopmentResult:
    """:func:`develop_player` for a ``players.csv`` row, changed in place.
    Only rating and potential cells change; every other column, and the
    form of each value, is left as it was."""

    _require_scale_2(row)
    return _develop(
        _RowView(row),
        player_id=str(row.get("player_id", "") or ""),
        pitcher=player_is_pitcher(row),
        age=int(age),
        season=season,
        development=development,
        intensity=intensity,
        weights=weights,
        params=params,
    )


def _require_scale_2(player: Any) -> None:
    scale = rating_scale_of(player)
    if scale != FULL_RATING_SCALE:
        if isinstance(player, Mapping):
            pid = player.get("player_id")
        else:
            pid = getattr(player, "player_id", "?")
        raise ValueError(
            f"player {pid!r} is stored on rating scale {scale}; the development "
            "model is built for scale 2 (scale 1 aging stays paused)"
        )


def summarize(results: List[DevelopmentResult]) -> Dict[str, Any]:
    """Counts for a log line or the rollover artifacts."""

    grew = sum(1 for r in results if any(v > 0 for v in r.changes.values()))
    fell = sum(1 for r in results if any(v < 0 for v in r.changes.values()))
    return {"players": len(results), "improved": grew, "declined": fell}
