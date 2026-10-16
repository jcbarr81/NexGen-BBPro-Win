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
(``engine._contact_babip_edge``). Under the switch the pickoff joins them
(``engine._pickoff_rating``): its attempt rate and its success chance read
the pitcher's hold and arm through the same Release 4 reader, against
those plain means, like the steal terms beside them. With the switch off
the pickoff reads both raw against 50, as it always has.

A rating is only ever treated as league-relative if its centre was
DELIVERED. Every centre defaults to 50.0, which cannot be told from "nobody
supplied this league's centre", and a game that shifts its hitters but not
its pitchers -- or shifts nothing while the models compare against 50 --
plays a different sport. So :func:`source_shift` raises
:class:`RatingCenterMissing` when the switch is on and the centre it is
asked for is not among the keys the tuning's overrides supplied
(``TuningConfig.delivered``), and ``engine.simulate_game`` checks the ones
every game needs before anything is played
(:func:`require_rating_centers`). Every shifted input reaches the pitch
through :func:`source_shift`, so a model's "compare against 50" never
applies to a rating that was not shifted.

The shifted rating is rounded to ``SHIFT_DECIMALS`` places
(:func:`league_relative`). ``rating + (50 - centre)`` is not exact in
binary for a two-decimal centre, so two leagues that differ by a constant
would otherwise read the same player a last bit apart, and that bit can
decide a near-tie between two relievers or the side of a threshold a
rating falls on. Rounded, they read the identical number.

The switch is off (0.0) by default: the legacy engine reads its ratings
exactly as before. Generation 5's profile turns it on.

Release 6a adds a second, independent switch, ``fielder_centred_ratings``,
for the ratings a batted ball is FIELDED with (owner decision 7): a
fielder's fa and arm read against the league's lineup regulars at the same
position (``FIELDER_FA_CENTER_KEYS`` / ``FIELDER_ARM_CENTER_KEYS``, seven
positions each, and the pitchers' fa). They are shifted where they enter
the range, error and double-play terms
(``fielding.adjusted_fielding_rating`` / ``fielding.fielder_arm_rating``),
through :func:`fielder_shift`, under the same rule: a centre that was not
delivered raises :class:`RatingCenterMissing`, and ``engine.simulate_game``
checks all of them before anything is played
(:func:`require_fielder_centers`). The Release 4 arm reads (tag-ups, extra
bases) and the catcher's terms are not part of it.

Release 6a (power and doubles): the line-drive credit on doubles
(``double_line_drive_scale``, ``physics.resolve_batted_ball``) reads the
hitter's raw ground-ball rating against the league regulars' mean,
``hitter_gf_center`` (``BATTED_BALL_CENTER_KEY``; gf is never shifted at
its source, so that centre is always the league's). Under the same rule a
game with the credit on is not played unless the centre was delivered
(:func:`require_batted_ball_centers`); with the credit off nothing is
checked.
"""

from __future__ import annotations

from typing import Any, Iterable

__all__ = [
    "CENTRED_RATING_KEYS",
    "MODEL_CENTER_KEYS",
    "REQUIRED_CENTER_KEYS",
    "SHIFT_DECIMALS",
    "RatingCenterMissing",
    "league_relative",
    "ratings_centred",
    "require_rating_centers",
    "source_shift",
    "rating_center",
    "FIELDER_FA_CENTER_KEYS",
    "FIELDER_ARM_CENTER_KEYS",
    "FIELDER_CENTER_KEYS",
    "fielders_centred",
    "fielder_shift",
    "require_fielder_centers",
    "BATTED_BALL_CENTER_KEY",
    "require_batted_ball_centers",
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
# The ones no game can be played without under the switch. The pitch-grade
# centre is asked for only when a pitcher has a repertoire to shift: a
# league whose pitchers carry no pitch grades has no such centre, and every
# pitch there is the stand-in 50.
REQUIRED_CENTER_KEYS = CENTRED_RATING_KEYS - {"pitcher_grade_usage_center"}
# Decimal places a shifted rating is rounded to (module docstring).
SHIFT_DECIMALS = 9
# Release 6a (fielder_centred_ratings): position -> the centre a fielder's
# fa, and his arm, are read against there. The pitcher has a fa centre only
# (his arm rating is his velocity).
FIELDER_FA_CENTER_KEYS = {
    "1B": "fielder_fa_center_1b",
    "2B": "fielder_fa_center_2b",
    "3B": "fielder_fa_center_3b",
    "SS": "fielder_fa_center_ss",
    "LF": "fielder_fa_center_lf",
    "CF": "fielder_fa_center_cf",
    "RF": "fielder_fa_center_rf",
    "P": "fielder_fa_center_p",
}
FIELDER_ARM_CENTER_KEYS = {
    "1B": "fielder_arm_center_1b",
    "2B": "fielder_arm_center_2b",
    "3B": "fielder_arm_center_3b",
    "SS": "fielder_arm_center_ss",
    "LF": "fielder_arm_center_lf",
    "CF": "fielder_arm_center_cf",
    "RF": "fielder_arm_center_rf",
}
# Every one of them: no game is played without them under the switch.
FIELDER_CENTER_KEYS = frozenset(FIELDER_FA_CENTER_KEYS.values()) | frozenset(
    FIELDER_ARM_CENTER_KEYS.values()
)


class RatingCenterMissing(RuntimeError):
    """``centred_ratings`` is on and a league centre it needs was not
    delivered with the tuning."""


def ratings_centred(tuning: Any) -> bool:
    """Whether ratings are shifted to league-relative at their source."""

    return tuning is not None and tuning.get("centred_ratings", 0.0) >= 0.5


def require_rating_centers(tuning: Any) -> None:
    """Raise :class:`RatingCenterMissing` unless every centre a game needs
    was delivered. Nothing to check with the switch off."""

    if not ratings_centred(tuning):
        return
    delivered = getattr(tuning, "delivered", ())
    missing = sorted(key for key in REQUIRED_CENTER_KEYS if key not in delivered)
    if missing:
        raise RatingCenterMissing(_missing_message(missing))


def _missing_message(missing: Iterable[str]) -> str:
    return (
        "centred_ratings is on but the league's rating centres were not "
        f"delivered with the tuning ({', '.join(missing)}); the game would be "
        "played on ratings that are not league-relative. The centres come "
        "from services.league_rating_centers (KPI harness: "
        "with_rating_centers)."
    )


def source_shift(tuning: Any, key: str) -> float:
    """Points to add to a raw rating where it enters the pitch kernel.

    ``key`` is the centre the rating is shifted by (one of
    ``CENTRED_RATING_KEYS``): ``50 - centre`` with the switch on, so the
    league's average reads as 50; 0.0 with it off. With the switch on and
    the centre not delivered this raises :class:`RatingCenterMissing`: the
    50.0 default is never taken for a league's centre.
    """

    if key not in CENTRED_RATING_KEYS:
        raise KeyError(f"{key} is not the centre of a rating shifted at its source")
    if not ratings_centred(tuning):
        return 0.0
    if key not in getattr(tuning, "delivered", ()):
        raise RatingCenterMissing(_missing_message([key]))
    return 50.0 - tuning.get(key, 50.0)


def league_relative(value: float, key: str, tuning: Any) -> float:
    """A raw rating as the plate appearance reads it.

    ``value`` itself with the switch off. With it on, ``value`` plus
    :func:`source_shift`, rounded to ``SHIFT_DECIMALS`` places so that two
    leagues a constant apart read the identical number.
    """

    if not ratings_centred(tuning):
        return value
    return round(value + source_shift(tuning, key), SHIFT_DECIMALS)


def rating_center(tuning: Any, key: str) -> float:
    """The centre a pitch-kernel formula compares a rating against.

    The league's centre named by ``key`` -- or 50.0 when the rating was
    already shifted at its source (the switch is on and ``key`` is in
    ``MODEL_CENTER_KEYS``). A centre the switch does not cover
    (``catcher_fa_center``) is always the league's. A usage centre is the
    shift's, never a model's: asking for one here is an error.
    """

    if key in MODEL_CENTER_KEYS:
        if ratings_centred(tuning):
            return 50.0
    elif key in CENTRED_RATING_KEYS:
        raise KeyError(f"{key} is a shift centre; a model names the plain centre")
    return tuning.get(key, 50.0)


def fielders_centred(tuning: Any) -> bool:
    """Whether fielding ratings are read against the league's regulars at
    the same position (Release 6a, ``fielder_centred_ratings``)."""

    return tuning is not None and tuning.get("fielder_centred_ratings", 0.0) >= 0.5


def _fielder_missing_message(missing: Iterable[str]) -> str:
    return (
        "fielder_centred_ratings is on but the league's fielder centres were "
        f"not delivered with the tuning ({', '.join(missing)}); the game "
        "would be played on fielding ratings that are not league-relative. "
        "The centres come from services.league_rating_centers (KPI harness: "
        "with_rating_centers)."
    )


def require_fielder_centers(tuning: Any) -> None:
    """Raise :class:`RatingCenterMissing` unless every fielder centre was
    delivered. Nothing to check with ``fielder_centred_ratings`` off."""

    if not fielders_centred(tuning):
        return
    delivered = getattr(tuning, "delivered", ())
    missing = sorted(key for key in FIELDER_CENTER_KEYS if key not in delivered)
    if missing:
        raise RatingCenterMissing(_fielder_missing_message(missing))


BATTED_BALL_CENTER_KEY = "hitter_gf_center"


PULL_CENTER_KEY = "hitter_pull_center"
PITCHER_GF_CENTER_KEY = "pitcher_gf_usage_center"


def batted_ball_center_needs(tuning: Any) -> dict[str, str]:
    """The batted-ball centres a game on ``tuning`` reads -> the switch that
    reads it: ``hitter_gf_center`` under the line-drive credit on doubles
    (``double_line_drive_scale``) or the Release 6b kernel
    (``batted_ball_model``); under the kernel also ``hitter_pull_center``
    with ``spray_model`` and ``pitcher_gf_usage_center`` with the pitcher's
    ground-ball term (``pitcher_gb_launch_scale``)."""

    needs: dict[str, str] = {}
    if tuning is None:
        return needs
    if tuning.get("double_line_drive_scale", 0.0):
        needs[BATTED_BALL_CENTER_KEY] = "double_line_drive_scale"
    if tuning.get("batted_ball_model", 0.0) >= 0.5:
        needs.setdefault(BATTED_BALL_CENTER_KEY, "batted_ball_model")
        if tuning.get("spray_model", 0.0) >= 0.5:
            needs[PULL_CENTER_KEY] = "spray_model"
        if tuning.get("pitcher_gb_launch_scale", 0.0):
            needs[PITCHER_GF_CENTER_KEY] = "pitcher_gb_launch_scale"
    return needs


def require_batted_ball_centers(tuning: Any) -> None:
    """Raise :class:`RatingCenterMissing` when a switch that reads a
    batted-ball centre is on (:func:`batted_ball_center_needs`) and the
    league's centre was not delivered. Nothing to check with them off."""

    delivered = getattr(tuning, "delivered", ())
    for key, switch in batted_ball_center_needs(tuning).items():
        if key not in delivered:
            raise RatingCenterMissing(
                f"{switch} is on but the league's {key} was not delivered "
                "with the tuning; the game would read every player against "
                "50. The centre comes from services.league_rating_centers "
                "(KPI harness: with_rating_centers)."
            )


def fielder_shift(tuning: Any, key: str) -> float:
    """Points to add to a fielder's raw fa or arm at a position.

    ``key`` is one of ``FIELDER_CENTER_KEYS``: ``50 - centre`` with
    ``fielder_centred_ratings`` on, so the league's average regular there
    reads as 50; 0.0 with it off. With the switch on and the centre not
    delivered this raises :class:`RatingCenterMissing`.
    """

    if key not in FIELDER_CENTER_KEYS:
        raise KeyError(f"{key} is not a fielder centre")
    if not fielders_centred(tuning):
        return 0.0
    if key not in getattr(tuning, "delivered", ()):
        raise RatingCenterMissing(_fielder_missing_message([key]))
    return 50.0 - tuning.get(key, 50.0)
