"""Platoon and handedness: the batter's edge by pitcher hand, in one place.

Release 5 (audit H7; decisions 6 and 7; Release 5 owner decision 5). Two
numbers describe a batter against a pitcher's hand:

- ``h``, the handedness advantage: positive with the platoon edge (opposite
  hands), negative without it. The engine multiplies it by the three
  ``handedness_*_bonus`` knobs.
- ``d_hand``, the hitter's own split from his ``vl`` rating: ``vl`` against
  its centre when the pitcher is left-handed, and the smaller, opposite
  counter-shift (``platoon_rhp_counter_scale``) against a right-hander.

Every reader -- the per-PA batter context, the pinch-hit / intentional-walk /
rest-day offence score, the bullpen matchup score and the lineup auto-fill --
gets them from :func:`platoon_shift` (or :func:`platoon_shift_values` when it
holds a ``players.csv`` row object rather than a ``BatterRatings``), so they
can not drift apart.

At the default knobs the pair is exactly what those five places hard-coded
before Release 5: ``h`` is +1 / -1 (0.5 for a switch hitter) and ``d_hand``
is ``vl - 50`` or ``-0.35 * (vl - 50)``. That holds for malformed rows as
well (a batting side that is not L, R or S, a blank or zero ``vl``): they
are only read strictly once the centred ``vl`` is switched on (see
:func:`platoon_shift_values`).

This module must not import the engine: ``utils.lineup_autofill`` reads it,
and the engine imports that.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from .config import DEFAULT_TUNING
from .models import known_vl

__all__ = [
    "handedness_scales",
    "platoon_shift",
    "platoon_shift_row",
    "platoon_shift_values",
    "platoon_needs_centers",
    "platoon_vl_centred",
]

# Batting side -> the league's mean ``vl`` on that side (a rating centre,
# ``services.league_rating_centers``). Any other side reads as right-handed
# (``_batting_side``).
_VL_CENTER_KEYS = {
    "L": "hitter_vl_center_l",
    "R": "hitter_vl_center_r",
    "S": "hitter_vl_center_s",
}


def _knob(tuning: Any, key: str) -> float:
    default = float(DEFAULT_TUNING[key])
    if tuning is None:
        return default
    return tuning.get(key, default)


def _balance_ratio(tuning: Any) -> Optional[float]:
    """The RHB / LHB bonus ratio at which LHP and RHP come out equal.

    With batting-side shares l / r / s and a switch hitter taking the bonus
    of the side he bats from times ``handedness_switch_bonus`` (b), the mean
    advantage against a LHP is ``-l*aL + (r + b*s)*aR`` and against a RHP
    ``(l + b*s)*aL - r*aR``; they are equal at
    ``aR / aL = (2l + b*s) / (2r + b*s)``, which is ``(2l + s) / (2r + s)``
    at the full switch bonus. ``None`` when the shares are unknown (0 / 0 /
    0, the tuning default) or there is nobody to bat right-handed.
    """

    left = _knob(tuning, "hitter_bats_share_l")
    right = _knob(tuning, "hitter_bats_share_r")
    switch = _knob(tuning, "hitter_bats_share_s")
    if left + right + switch <= 0.0:
        return None
    switch *= max(0.0, _knob(tuning, "handedness_switch_bonus"))
    if 2.0 * right + switch <= 0.0:
        return None
    return (2.0 * left + switch) / (2.0 * right + switch)


def handedness_scales(tuning: Any = None) -> Tuple[float, float]:
    """``(a_L, a_R)``: the handedness bonus of a left- and a right-handed
    batter, as multiples of the ``handedness_*_bonus`` knobs.

    ``a_L`` is ``handedness_lhb_scale``. ``a_R`` is ``a_L`` times
    ``(1 - w) * handedness_rhb_scale + w * rho + handedness_balance_bias``
    clamped to ``handedness_balance_min`` .. ``_max``: ``w``
    (``handedness_balance_strength``) slides the right-handed split from a
    fixed size (0) to the size that balances this league's own mix of
    batting sides (1; ``rho``, :func:`_balance_ratio`). Unknown shares read
    as ``w`` 0.
    """

    a_left = _knob(tuning, "handedness_lhb_scale")
    ratio = _knob(tuning, "handedness_rhb_scale")
    strength = _knob(tuning, "handedness_balance_strength")
    if strength != 0.0:
        rho = _balance_ratio(tuning)
        if rho is not None:
            ratio = (1.0 - strength) * ratio + strength * rho
    ratio += _knob(tuning, "handedness_balance_bias")
    ratio = max(
        _knob(tuning, "handedness_balance_min"),
        min(_knob(tuning, "handedness_balance_max"), ratio),
    )
    return a_left, a_left * ratio


def platoon_vl_centred(tuning: Any = None) -> bool:
    """Whether ``vl`` is read against the league's mean for the hitter's
    batting side (``platoon_vl_center_enabled``) rather than against 50."""

    return _knob(tuning, "platoon_vl_center_enabled") >= 0.5


def _batting_side(bats: Any) -> str:
    """L, R or S; a blank or unknown side bats right, as
    ``services.league_rating_centers`` counts it for the centres."""

    side = str(bats or "").strip().upper()
    return side if side in _VL_CENTER_KEYS else "R"


def platoon_shift_values(
    bats: Any, vs_left: Any, pitcher_hand: Any, tuning: Any = None
) -> Tuple[float, float]:
    """``(h, d_hand)`` for a batting side and ``vl`` against a pitcher hand.

    ``tuning`` None reads every knob at its default. See the module
    docstring for the two numbers.

    With the centred ``vl`` on, the row is read strictly: the batting side
    is normalised first (:func:`_batting_side`; " l" is left-handed, "B" or
    anything else unknown is right-handed, so nobody holds the platoon edge
    against both hands), and a ``vl`` that is blank, not a number or zero
    is no personal split (``d_hand`` 0), whichever side he bats from. With
    it off both are read as they always were -- an unrecognised side as
    "neither hand" and ``vl`` as the number passed in against 50 -- so the
    default path is unchanged for malformed rows too.
    """

    hand = str(pitcher_hand or "R").upper()
    centred = platoon_vl_centred(tuning)
    side = _batting_side(bats) if centred else str(bats or "R").upper()
    a_left, a_right = handedness_scales(tuning)
    if side == "S":
        # A switch hitter always bats from the platoon side: left-handed
        # against a right-hander.
        h = _knob(tuning, "handedness_switch_bonus") * (
            a_left if hand == "R" else a_right
        )
    else:
        h = a_left if side == "L" else a_right
        if side == hand:
            h = -h
    if centred:
        rating = known_vl(vs_left)
        if rating is None:
            d_hand = 0.0
        else:
            d_hand = rating - _knob(tuning, _VL_CENTER_KEYS[side])
    else:
        d_hand = float(vs_left) - 50.0
    if hand != "L":
        d_hand = -_knob(tuning, "platoon_rhp_counter_scale") * d_hand
    return h, d_hand


def platoon_shift(batter: Any, pitcher_hand: Any, tuning: Any = None) -> Tuple[float, float]:
    """``(h, d_hand)`` for an engine ``BatterRatings`` against a pitcher hand.

    ``BatterRatings.from_row`` stores a blank ``vl`` as 50.0 and remembers
    that it did (``vs_left_known``); the centred read gets that as "no
    rating", the default read gets the 50.0 it always got.
    """

    vs_left: Any = batter.vs_left
    if not getattr(batter, "vs_left_known", True) and platoon_vl_centred(tuning):
        vs_left = None
    return platoon_shift_values(batter.bats, vs_left, pitcher_hand, tuning)


def platoon_shift_row(
    player: Any, pitcher_hand: Any, tuning: Any = None
) -> Tuple[float, float]:
    """``(h, d_hand)`` for a ``players.csv`` player object (``bats`` and a
    raw ``vl``; the lineup auto-fill's entry).

    With the centred ``vl`` on, a blank or zero ``vl`` is no personal
    split, exactly as :func:`platoon_shift` reads it for the engine. With
    it off a blank or zero ``vl`` reads as 50, as the auto-fill always had
    it (the engine reads a stored 0 as 0 there; the two differ only for
    that malformed value, and only on the default path).
    """

    vs_left: Any = getattr(player, "vl", None)
    if not platoon_vl_centred(tuning):
        vs_left = float(vs_left or 50)
    return platoon_shift_values(
        getattr(player, "bats", ""), vs_left, pitcher_hand, tuning
    )


def platoon_needs_centers(tuning: Any = None) -> bool:
    """Whether a switched-on platoon term reads the league's rating centres
    (the by-bats ``vl`` means or the batting-side shares)."""

    return (
        platoon_vl_centred(tuning)
        or _knob(tuning, "handedness_balance_strength") != 0.0
    )
