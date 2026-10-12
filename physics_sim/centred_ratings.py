"""League-relative ratings: the ``centred_ratings`` switch (Release 5).

Audit decision 2: the engine reads a rating as ``50 + (rating - league
mean)``, so one set of knobs is valid for every league. The Release 5
models did that term by term (the contact model subtracts the Contact
centre, the command model the control centre), but the batted-ball path
still read absolute ratings -- bat speed from Power, pitch velocity from
the arm, the pitch-quality factor on exit velocity -- so a league whose
ratings sit off 50 scored off the knobs' level.

With ``centred_ratings`` on, each rating that feeds a plate appearance is
shifted ONCE, where it enters the pitch kernel, by ``50 - its league
centre`` (:func:`source_shift`):

* hitters, in ``engine._batter_context``: Contact, Power and Eye, before
  the handedness, times-through-the-order, home-field and platoon shifts
  and the 1-100 clamp; their centres are the lineup regulars' means;
* pitchers, in ``engine._pitcher_context`` and the per-pitch fatigue step:
  control and movement (before the fresh-arm bonus and the fatigue
  factors), every pitch grade in the repertoire, and the arm rating that
  sets pitch velocity; their centres are the workload-weighted means, the
  ``pitcher_*_usage_center`` keys (a starter counts for more than a
  reliever: ``services.league_rating_centers``).

Everything downstream -- the formulas written against an absolute 50 and
the Release 5 models alike -- then sees league-relative numbers. A formula
that subtracts a centre from a rating shifted this way must not centre it
a second time, so every centre read in the pitch kernel goes through
:func:`rating_center`, which answers 50.0 for the centres of the ratings
the switch shifts. ``tests/test_r5_centred_ratings.py`` fails if a centre
is read any other way.

Terms that read a RAW rating against its own centre are left as they are
and keep reading the real centre: the Release 4 running-game terms
(``engine._centred_rating`` / ``_centred_speed``, which read the plain
ACT means ``pitcher_control_center``, ``pitcher_hold_center`` and
``pitcher_arm_center``) and the Contact hit edge
(``engine._contact_babip_edge``).

The switch is off (0.0) by default: the legacy engine reads its ratings
exactly as before. Generation 5's profile turns it on.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CENTRED_RATING_KEYS",
    "MODEL_CENTER_KEYS",
    "ratings_centred",
    "source_shift",
    "rating_center",
]

# The centre a pitch-kernel model names for a rating -> the centre that
# rating is shifted by at its source under the switch. The models name the
# plain ACT mean for a pitcher's rating (what they read with the switch off);
# the shift uses the workload-weighted centre of the same rating.
MODEL_CENTER_KEYS = {
    "hitter_contact_center": "hitter_contact_center",
    "hitter_power_center": "hitter_power_center",
    "hitter_eye_center": "hitter_eye_center",
    "pitcher_control_center": "pitcher_control_usage_center",
    "pitcher_movement_center": "pitcher_movement_usage_center",
    "pitcher_grade_center": "pitcher_grade_usage_center",
    "pitcher_arm_center": "pitcher_arm_usage_center",
}
# The centres the shift itself reads.
CENTRED_RATING_KEYS = frozenset(MODEL_CENTER_KEYS.values())


def ratings_centred(tuning: Any) -> bool:
    """Whether ratings are shifted to league-relative at their source."""

    return tuning is not None and tuning.get("centred_ratings", 0.0) >= 0.5


def source_shift(tuning: Any, key: str) -> float:
    """Points to add to a raw rating where it enters the pitch kernel.

    ``key`` is the centre the rating is shifted by (one of
    ``CENTRED_RATING_KEYS``): ``50 - centre`` with the switch on, so the
    league's average reads as 50; 0.0 with it off.
    """

    if key not in CENTRED_RATING_KEYS:
        raise KeyError(f"{key} is not the centre of a rating shifted at its source")
    if not ratings_centred(tuning):
        return 0.0
    return 50.0 - tuning.get(key, 50.0)


def rating_center(tuning: Any, key: str) -> float:
    """The centre a pitch-kernel formula compares a rating against.

    The league's centre named by ``key`` -- or 50.0 when the rating was
    already shifted at its source (the switch is on and ``key`` is in
    ``MODEL_CENTER_KEYS``). A centre the switch does not cover
    (``catcher_fa_center``) is always the league's.
    """

    if key in MODEL_CENTER_KEYS and ratings_centred(tuning):
        return 50.0
    return tuning.get(key, 50.0)
