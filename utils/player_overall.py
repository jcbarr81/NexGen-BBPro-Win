"""One production-weighted overall for every consumer (audit H8 + M14).

The displayed OVR, the profile OVR, the depth-chart autofill sort, CPU roster
auto-assign and the CPU trade evaluator all score players with
:func:`overall_score`. Before this they each averaged a flat key list that the
engine does not reward (sc is never loaded, pl has no effect, vl is
season-neutral, gf lowers offense; pitcher arm/fa/hold_runner do nothing) and
counted every unthrown pitch as a 0, so r(OVR, OPS+) was ~0.3 and the CPU
pitcher score tracked pitches thrown (r 0.985) instead of FIP (r -0.03).

The score stays on the rating scale: a player whose ratings are all 50 scores
50, so hitters and pitchers are directly comparable (the old pitcher average
sat ~12 points below hitters and the trade evaluator undervalued arms).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from utils.pitcher_role import get_role

PITCH_KEYS = ("fb", "cu", "cb", "sl", "si", "scb", "kn")

# Offense weights follow what the engine rewards (H8): contact and power carry
# production, eye a little, speed a little.
_OFFENSE_WEIGHTS = {"ch": 0.45, "ph": 0.45, "eye": 0.07, "sp": 0.03}

# PROVISIONAL defense weights per point of (rating - 50), DECISIONS.md #12:
# the MLB spectrum (SS/CF premium, then 2B/3B, then LF/RF, 1B least), kept
# modest -- roughly a quarter of an offensive SD per defensive SD at SS/CF.
# Deliberately NOT derived from today's measured fielding run values, which
# are wrong (M22: 10 fa is worth more in RF than at SS) until Release 6
# re-derives these from total runs. C is not on the decision's spectrum; it
# sits on the 2B/3B tier, arm-heavy for the running game. DH has no glove.
_DEFENSE_WEIGHTS = {
    "SS": (0.15, 0.06),
    "CF": (0.16, 0.05),
    "2B": (0.11, 0.03),
    "3B": (0.09, 0.05),
    "C": (0.06, 0.08),
    "LF": (0.07, 0.02),
    "RF": (0.06, 0.04),
    "1B": (0.04, 0.00),
    "DH": (0.00, 0.00),
}
_DEFAULT_DEFENSE_WEIGHTS = (0.07, 0.03)

# Pitchers: command and movement drive results; the pitch grades the pitcher
# actually throws add the rest. arm (wrong-signed today), fa and hold_runner
# have no measurable effect and stay out (H8).
_CONTROL_WEIGHT = 0.47
_MOVEMENT_WEIGHT = 0.38
_PITCH_GRADE_WEIGHT = 0.15

# Endurance is a role adjustment only (H8): it decides how many innings a
# starter can cover, so it moves a starter's score a little and a reliever's
# not at all.
_STARTER_ENDURANCE_SLOPE = 0.06
_STARTER_ENDURANCE_CAP = 3.0

_NEUTRAL = 50.0


def _rating(get_raw: Callable[[str], Any], key: str) -> Optional[float]:
    """A usable rating, or None when blank/zero (an unset field, not a 0)."""

    try:
        value = float(get_raw(key))
    except (TypeError, ValueError):
        return None
    if value != value or value <= 0:  # NaN or unset
        return None
    return min(99.0, value)


def _clamp(score: float) -> float:
    return max(0.0, min(99.0, score))


def hitter_overall_score(
    get_raw: Callable[[str], Any],
    position: Optional[str] = None,
) -> Optional[float]:
    """Continuous hitter overall on the rating scale (None without ch/ph)."""

    ch = _rating(get_raw, "ch")
    ph = _rating(get_raw, "ph")
    if ch is None and ph is None:
        return None
    offense = 0.0
    for key, weight in _OFFENSE_WEIGHTS.items():
        value = _rating(get_raw, key)
        offense += weight * (_NEUTRAL if value is None else value)

    fa_weight, arm_weight = _DEFENSE_WEIGHTS.get(
        str(position or "").strip().upper(), _DEFAULT_DEFENSE_WEIGHTS
    )
    fa = _rating(get_raw, "fa")
    arm = _rating(get_raw, "arm")
    defense = fa_weight * ((fa if fa is not None else _NEUTRAL) - _NEUTRAL)
    defense += arm_weight * ((arm if arm is not None else _NEUTRAL) - _NEUTRAL)
    return _clamp(offense + defense)


def pitcher_overall_score(
    get_raw: Callable[[str], Any],
    role: Optional[str] = None,
) -> Optional[float]:
    """Continuous pitcher overall on the rating scale (None without co/mo).

    Only thrown pitches (grade > 0) enter the pitch-grade mean, so a pitcher
    with two pitches and one with five of the same grade score the same
    (M14). With no graded pitch the weight falls back onto control/movement.
    """

    control = _rating(get_raw, "control")
    movement = _rating(get_raw, "movement")
    if control is None and movement is None:
        return None
    control = _NEUTRAL if control is None else control
    movement = _NEUTRAL if movement is None else movement
    grades = [g for g in (_rating(get_raw, key) for key in PITCH_KEYS) if g]
    if grades:
        score = (
            _CONTROL_WEIGHT * control
            + _MOVEMENT_WEIGHT * movement
            + _PITCH_GRADE_WEIGHT * (sum(grades) / len(grades))
        )
    else:
        score = (_CONTROL_WEIGHT * control + _MOVEMENT_WEIGHT * movement) / (
            _CONTROL_WEIGHT + _MOVEMENT_WEIGHT
        )

    if str(role or "").strip().upper() == "SP":
        endurance = _rating(get_raw, "endurance")
        if endurance is not None:
            adjust = _STARTER_ENDURANCE_SLOPE * (endurance - _NEUTRAL)
            score += max(-_STARTER_ENDURANCE_CAP, min(_STARTER_ENDURANCE_CAP, adjust))
    return _clamp(score)


def _getter(player: Any) -> Callable[[str], Any]:
    if isinstance(player, Mapping):
        return player.get
    return lambda key: getattr(player, key, None)


def is_pitcher_like(player: Any) -> bool:
    get = _getter(player)
    flag = get("is_pitcher")
    if isinstance(flag, str):
        flag = flag.strip().lower() in {"1", "true", "yes"}
    if flag:
        return True
    return str(get("primary_position") or "").strip().upper() in {"P", "SP", "RP"}


def overall_score(
    get_raw: Callable[[str], Any],
    *,
    is_pitcher: bool,
    position: Optional[str] = None,
    role: Optional[str] = None,
) -> Optional[float]:
    """The shared overall: ``get_raw(key)`` reads one rating by key."""

    if is_pitcher:
        return pitcher_overall_score(get_raw, role)
    return hitter_overall_score(get_raw, position)


def player_overall_score(
    player: Any,
    *,
    get_raw: Optional[Callable[[str], Any]] = None,
) -> Optional[float]:
    """:func:`overall_score` for a player object or CSV row dict.

    ``get_raw`` overrides where ratings are read from (the trade evaluator
    passes one that reads potential ratings); position and role still come
    from ``player``.
    """

    if player is None:
        return None
    reader = get_raw or _getter(player)
    if is_pitcher_like(player):
        return pitcher_overall_score(reader, get_role(player))
    return hitter_overall_score(reader, _getter(player)("primary_position"))


__all__ = [
    "PITCH_KEYS",
    "hitter_overall_score",
    "is_pitcher_like",
    "overall_score",
    "pitcher_overall_score",
    "player_overall_score",
]
