from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List
import math
import random

from utils.position_fit import position_fielding
from utils.roster_rules import is_catcher

from .centred_ratings import (
    FIELDER_ARM_CENTER_KEYS,
    FIELDER_FA_CENTER_KEYS,
    SHIFT_DECIMALS,
    fielder_shift,
    fielders_centred,
)
from .models import BatterRatings, PitcherRatings
from .config import TuningConfig


INFIELD_POS = {"1B", "2B", "3B", "SS", "C", "P"}
OUTFIELD_POS = {"LF", "CF", "RF"}
# Release 6a: position -> its range slope and its error base (tuning keys).
_RANGE_SLOPE_KEYS = {
    "1B": "range_logit_slope_1b",
    "2B": "range_logit_slope_2b",
    "3B": "range_logit_slope_3b",
    "SS": "range_logit_slope_ss",
    "LF": "range_logit_slope_lf",
    "CF": "range_logit_slope_cf",
    "RF": "range_logit_slope_rf",
}
_ERROR_BASE_KEYS = {
    "1B": "error_base_1b",
    "2B": "error_base_2b",
    "3B": "error_base_3b",
    "SS": "error_base_ss",
    "LF": "error_base_lf",
    "CF": "error_base_cf",
    "RF": "error_base_rf",
    "P": "error_base_p",
}
_INFIELD_ERROR_POS = frozenset({"1B", "2B", "3B", "SS", "P"})
# The error chance of a position with no base of its own (a catcher on a
# batted ball: the engine never rolls one).
_ERROR_BASE_OTHER = 0.01
ERROR_PROB_MIN = 0.0005
ERROR_PROB_MAX = 0.15


@dataclass
class DefenseRatings:
    infield: float
    outfield: float
    arm: float
    infield_left: float
    infield_right: float
    outfield_left: float
    outfield_center: float
    outfield_right: float
    # Release 6a: each fielder's rating as he plays his position
    # (``adjusted_fielding_rating``, before ``range_scale``), by position.
    # ``range_model`` 1 reads the responsible fielder's from here.
    positions: Dict[str, float] = field(default_factory=dict, compare=False)


# What ``range_model`` 1 calls a neutral defence: every fielder a 50.
NEUTRAL_DEFENSE = DefenseRatings(50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0)


def _fallback_fielder(remaining: List[BatterRatings], pos: str) -> BatterRatings:
    """Best fielder in ``remaining`` for ``pos`` when nobody was assigned it.

    Release 3 (audit M16): players who list ``pos`` first. A catcher always
    takes C when one is left, and a catcher is used elsewhere only when no
    one else remains -- the old fallback took the best fielder anywhere, so
    a shortstop could end up catching while the catcher played short.
    """

    eligible = [b for b in remaining if b.primary_position == pos or pos in b.other_positions]
    if pos == "C":
        pool = [b for b in remaining if is_catcher(b)] or remaining
    else:
        pool = eligible or [b for b in remaining if not is_catcher(b)] or remaining
    return max(pool, key=lambda b: b.fielding)


def build_default_defense(batters: List[BatterRatings]) -> Dict[str, BatterRatings]:
    """Assign fielders to positions based on primary/other positions."""

    positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
    remaining = batters[:]
    defense: Dict[str, BatterRatings] = {}

    for pos in positions:
        if not remaining:
            break
        choice = _fallback_fielder(remaining, pos)
        defense[pos] = choice
        remaining.remove(choice)
    return defense


def build_defense_from_lineup(
    batters: List[BatterRatings],
    lineup_positions: Dict[str, str],
) -> Dict[str, BatterRatings]:
    """Assign fielders based on lineup positions, with a fallback fill."""

    positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
    defense: Dict[str, BatterRatings] = {}
    used_ids = set()

    for batter in batters:
        pos = (lineup_positions.get(batter.player_id) or "").upper()
        if not pos or pos == "DH":
            continue
        if pos in defense:
            continue
        defense[pos] = batter
        used_ids.add(batter.player_id)

    remaining = [b for b in batters if b.player_id not in used_ids]
    for pos in positions:
        if pos in defense:
            continue
        if not remaining:
            break
        choice = _fallback_fielder(remaining, pos)
        defense[pos] = choice
        remaining.remove(choice)
    return defense


def compute_defense_ratings(defense: Dict[str, BatterRatings], tuning: TuningConfig) -> DefenseRatings:
    def_score_in = []
    def_score_out = []
    arms = []
    pos_ratings: Dict[str, float] = {}
    centred = fielders_centred(tuning)
    for pos, player in defense.items():
        rating = adjusted_fielding_rating(player, pos, tuning)
        pos_ratings[pos] = rating
        arm = player.arm
        arms.append(arm)
        if pos in OUTFIELD_POS:
            def_score_out.append(rating)
        elif centred and pos not in FIELDER_FA_CENTER_KEYS:
            # Release 6a: the catcher's fa is not on the fielders' centred
            # scale, so it stays out of the infield average.
            continue
        else:
            def_score_in.append(rating)
    infield = sum(def_score_in) / len(def_score_in) if def_score_in else 50.0
    outfield = sum(def_score_out) / len(def_score_out) if def_score_out else 50.0
    arm_avg = sum(arms) / len(arms) if arms else 50.0

    def _avg_positions(*positions: str) -> float | None:
        values = [pos_ratings[p] for p in positions if p in pos_ratings]
        if not values:
            return None
        return sum(values) / len(values)

    infield_left = _avg_positions("3B", "SS")
    infield_right = _avg_positions("1B", "2B")
    outfield_left = pos_ratings.get("LF")
    outfield_center = pos_ratings.get("CF")
    outfield_right = pos_ratings.get("RF")

    range_scale = tuning.get("range_scale", 1.0)
    infield *= range_scale
    outfield *= range_scale
    infield_left = (infield_left if infield_left is not None else infield) * range_scale
    infield_right = (infield_right if infield_right is not None else infield) * range_scale
    outfield_left = (outfield_left if outfield_left is not None else outfield) * range_scale
    outfield_center = (outfield_center if outfield_center is not None else outfield) * range_scale
    outfield_right = (outfield_right if outfield_right is not None else outfield) * range_scale

    arm_avg *= tuning.get("arm_strength_scale", 1.0)
    return DefenseRatings(
        infield=infield,
        outfield=outfield,
        arm=arm_avg,
        infield_left=infield_left,
        infield_right=infield_right,
        outfield_left=outfield_left,
        outfield_center=outfield_center,
        outfield_right=outfield_right,
        positions=pos_ratings,
    )


def league_average_defense(tuning: TuningConfig) -> DefenseRatings:
    """The defence ``compute_defense_ratings`` gives a club of the league's
    average regulars, each at his own position.

    Release 6a, for the per-ball chance log (``fielding_chance_log``): the
    out chance behind it is what a league-average fielder would have had.
    Under ``fielder_centred_ratings`` the average regular is a 50; without
    it he is his position's centre (50 where none was delivered), read
    through the primary-position multiplier and ``range_scale`` like any
    fielder. Reads only.
    """

    if fielders_centred(tuning):
        ratings = {pos: 50.0 for pos in _RANGE_SLOPE_KEYS}
    else:
        primary = tuning.get("defense_primary_pos_scale", 1.0)
        ratings = {
            pos: tuning.get(FIELDER_FA_CENTER_KEYS[pos], 50.0) * primary
            for pos in _RANGE_SLOPE_KEYS
        }
    scale = tuning.get("range_scale", 1.0)
    infield = sum(ratings[pos] for pos in ("1B", "2B", "3B", "SS")) / 4.0
    outfield = sum(ratings[pos] for pos in ("LF", "CF", "RF")) / 3.0
    return DefenseRatings(
        infield=infield * scale,
        outfield=outfield * scale,
        arm=50.0,
        infield_left=(ratings["3B"] + ratings["SS"]) / 2.0 * scale,
        infield_right=(ratings["1B"] + ratings["2B"]) / 2.0 * scale,
        outfield_left=ratings["LF"] * scale,
        outfield_center=ratings["CF"] * scale,
        outfield_right=ratings["RF"] * scale,
        positions=ratings,
    )


def adjusted_fielding_rating(
    player: BatterRatings | PitcherRatings,
    position: str,
    tuning: TuningConfig,
) -> float:
    """``player``'s fielding rating as he plays ``position``.

    The one place the engine turns a fielder's fa into the rating a play
    reads: ``utils.position_fit.position_fielding`` (the out-of-position
    multipliers, or the points table under ``position_fit_model`` 1), then
    the shift to the league's regulars at that position under
    ``fielder_centred_ratings`` (the seven fielder positions and the
    pitcher; a catcher's terms centre him themselves). The pitcher on the
    mound has no other position to be out of.
    """
    if isinstance(player, PitcherRatings):
        rating = player.fielding
    else:
        rating = position_fielding(
            player,
            position,
            model=tuning.get("position_fit_model", 0.0),
            primary_scale=tuning.get("defense_primary_pos_scale", 1.0),
            secondary_scale=tuning.get("defense_secondary_pos_scale", 0.9),
            out_of_position_scale=tuning.get("defense_out_of_pos_scale", 0.75),
            secondary_penalty_scale=tuning.get(
                "position_secondary_penalty_scale", 0.25
            ),
            fielding=player.fielding,
        )
    if fielders_centred(tuning):
        key = FIELDER_FA_CENTER_KEYS.get(position)
        if key is not None:
            rating = round(rating + fielder_shift(tuning, key), SHIFT_DECIMALS)
    return rating


def adjusted_arm_rating(player: BatterRatings, tuning: TuningConfig) -> float:
    return player.arm * tuning.get("arm_strength_scale", 1.0)


def fielder_arm_rating(
    player: BatterRatings, position: str, tuning: TuningConfig
) -> float:
    """The arm the error and double-play terms read for a fielder.

    ``adjusted_arm_rating`` -- and, under ``fielder_centred_ratings``, that
    arm against the league's regulars at ``position`` (Release 6a). The
    Release 4 arm reads (tag-ups, extra bases) keep ``adjusted_arm_rating``:
    a throw against a runner is a race, not a rate.
    """
    arm = adjusted_arm_rating(player, tuning)
    if fielders_centred(tuning):
        key = FIELDER_ARM_CENTER_KEYS.get(position)
        if key is not None:
            arm = round(arm + fielder_shift(tuning, key), SHIFT_DECIMALS)
    return arm


def field_direction(
    spray_angle: float, batter_side: str, tuning: TuningConfig | None = None
) -> float:
    """A ball's direction for fielder credit, in degrees toward the
    left-field side (third base and left field positive).

    ``spray_direction_model`` 1 (Release 6a, plan 2.4): the stored angle is
    physical (positive = the right-field side), so this is ``-angle`` for
    both hands. 0, or no tuning: the old read, which negates only for a
    right-handed batter and so mirrors a left-handed batter's balls.
    """
    spray = float(spray_angle)
    if tuning is not None and tuning.get("spray_direction_model", 0.0) >= 0.5:
        return -spray
    if batter_side == "R":
        spray = -spray
    return spray


def infield_position(direction: float, tuning: TuningConfig | None = None) -> str:
    """The infielder a ground ball in ``direction`` (:func:`field_direction`)
    belongs to. ``infield_band_model`` 1: the band it falls in -- 3B, SS, the
    pitcher (``"P"``), 2B, else 1B, by the ``infield_band_*_min_deg`` lower
    bounds. 0, or no tuning: the old bands."""
    if tuning is not None and tuning.get("infield_band_model", 0.0) >= 0.5:
        if direction >= tuning.get("infield_band_3b_min_deg", 16.0):
            return "3B"
        if direction >= tuning.get("infield_band_ss_min_deg", 1.5):
            return "SS"
        if direction >= tuning.get("infield_band_p_min_deg", -1.5):
            return "P"
        if direction >= tuning.get("infield_band_2b_min_deg", -19.5):
            return "2B"
        return "1B"
    if direction >= 25:
        return "3B"
    if direction <= -25:
        return "1B"
    if direction >= 6:
        return "SS"
    if direction <= -6:
        return "2B"
    return "SS" if direction >= 0 else "2B"


def outfield_position(direction: float, tuning: TuningConfig) -> str:
    center_band = tuning.get("spray_center_band_deg", 8.0)
    if abs(direction) <= center_band:
        return "CF"
    return "LF" if direction > 0 else "RF"


def responsible_position(
    *, ball_type: str, spray_angle: float, tuning: TuningConfig
) -> str:
    """The one fielder whose rating moves a ball's out chance under
    ``range_model`` 1: the infield band owner on a ground ball, LF / CF / RF
    on a ball in the air. Always by the PHYSICAL side (positive stored angle
    = the right-field side), which is the side ``out_probability`` has
    always read; the engine's fielder credit agrees with it once
    ``spray_direction_model`` is on."""
    direction = -float(spray_angle)
    if ball_type == "gb":
        return infield_position(direction, tuning)
    return outfield_position(direction, tuning)


def out_probability(
    *,
    ball_type: str,
    exit_velo: float,
    launch_angle: float,
    spray_angle: float | None = None,
    batter_side: str | None = None,
    pull_tendency: float | None = None,
    defense: DefenseRatings,
    tuning: TuningConfig,
    batter_speed: float | None = None,
) -> float:
    """Chance a ball in play that stays in the park is turned into an out.

    ``range_model`` 0: the additive chance (:func:`_additive_out_probability`),
    the defence's ratings added to every ball alike. ``range_model`` 1
    (Release 6a): the neutral chance (:func:`neutral_out_probability`)
    shifted in log-odds by the one responsible fielder's rating
    (:func:`range_shifted_out_probability`).
    """
    if tuning.get("range_model", 0.0) < 0.5:
        return _additive_out_probability(
            ball_type=ball_type,
            exit_velo=exit_velo,
            launch_angle=launch_angle,
            spray_angle=spray_angle,
            batter_side=batter_side,
            pull_tendency=pull_tendency,
            defense=defense,
            tuning=tuning,
            batter_speed=batter_speed,
        )
    out0 = neutral_out_probability(
        ball_type=ball_type,
        exit_velo=exit_velo,
        launch_angle=launch_angle,
        spray_angle=spray_angle,
        batter_side=batter_side,
        pull_tendency=pull_tendency,
        tuning=tuning,
        batter_speed=batter_speed,
    )
    if spray_angle is None or not batter_side:
        return out0
    position = responsible_position(
        ball_type=ball_type, spray_angle=spray_angle, tuning=tuning
    )
    rating = defense.positions.get(position)
    if rating is None:
        return out0
    return range_shifted_out_probability(
        out0, position=position, rating=rating, ball_type=ball_type, tuning=tuning
    )


def neutral_out_probability(
    *,
    ball_type: str,
    exit_velo: float,
    launch_angle: float,
    spray_angle: float | None = None,
    batter_side: str | None = None,
    pull_tendency: float | None = None,
    tuning: TuningConfig,
    batter_speed: float | None = None,
) -> float:
    """``out0``: the out chance behind a defence of average fielders (50s),
    the ball, the shift and the batter's speed as the additive chance reads
    them."""
    return _additive_out_probability(
        ball_type=ball_type,
        exit_velo=exit_velo,
        launch_angle=launch_angle,
        spray_angle=spray_angle,
        batter_side=batter_side,
        pull_tendency=pull_tendency,
        defense=NEUTRAL_DEFENSE,
        tuning=tuning,
        batter_speed=batter_speed,
    )


def range_shifted_out_probability(
    out0: float,
    *,
    position: str,
    rating: float,
    ball_type: str,
    tuning: TuningConfig,
) -> float:
    """``out0`` moved by the responsible fielder (``range_model`` 1):

    ``logit(out) = logit(out0) + range_logit_slope_<position> * (rating - 50)
    * range_scale`` (times ``range_ld_ratio`` on a line drive), so a ball
    near a coin flip moves most and a routine play or a sure hit hardly at
    all. A position without a slope (the pitcher) leaves ``out0`` alone.
    """
    key = _RANGE_SLOPE_KEYS.get(position)
    if key is None:
        return out0
    slope = tuning.get(key, 0.0) * tuning.get("range_scale", 1.0)
    if ball_type == "ld":
        slope *= tuning.get("range_ld_ratio", 0.6)
    shift = slope * (rating - 50.0)
    if not shift:
        return out0
    odds = out0 / (1.0 - out0) * math.exp(shift)
    return max(0.02, min(0.98, odds / (1.0 + odds)))


def _additive_out_probability(
    *,
    ball_type: str,
    exit_velo: float,
    launch_angle: float,
    spray_angle: float | None = None,
    batter_side: str | None = None,
    pull_tendency: float | None = None,
    defense: DefenseRatings,
    tuning: TuningConfig,
    batter_speed: float | None = None,
) -> float:
    def _spray_dir(angle: float, side: str) -> float:
        # The angle toward the batter's pull side IF the stored angle is
        # physical (positive = the right-field side): what the side picks
        # below have always assumed, and what the shift term reads. It is
        # physical under spray_direction_model 1; with the model off a
        # right-handed batter's angle is drawn hand-blind (audit M4).
        spray = float(angle)
        side = side.upper()
        if side == "R":
            spray = -spray
        return spray

    def _infield_rating(angle: float, side: str) -> float:
        spray_dir = _spray_dir(angle, side)
        if spray_dir >= 0:
            return defense.infield_left if side == "R" else defense.infield_right
        return defense.infield_right if side == "R" else defense.infield_left

    def _outfield_rating(angle: float, side: str) -> float:
        spray_dir = _spray_dir(angle, side)
        center_band = tuning.get("spray_center_band_deg", 8.0)
        if abs(spray_dir) <= center_band:
            return defense.outfield_center
        if spray_dir >= 0:
            return defense.outfield_left if side == "R" else defense.outfield_right
        return defense.outfield_right if side == "R" else defense.outfield_left

    if ball_type == "gb":
        base = 0.78
        range_rating = defense.infield
        if spray_angle is not None and batter_side:
            range_rating = _infield_rating(spray_angle, batter_side)
        def_adj = (range_rating - 50.0) / 250.0
    elif ball_type == "ld":
        base = 0.38
        range_rating = defense.outfield
        if spray_angle is not None and batter_side:
            range_rating = _outfield_rating(spray_angle, batter_side)
        def_adj = (range_rating - 50.0) / 300.0
    else:
        base = 0.73
        range_rating = defense.outfield
        if spray_angle is not None and batter_side:
            range_rating = _outfield_rating(spray_angle, batter_side)
        def_adj = (range_rating - 50.0) / 230.0

    quality_adj = (exit_velo - 90.0) / 300.0
    out_prob = base + def_adj - quality_adj

    if (
        ball_type in {"gb", "ld"}
        and spray_angle is not None
        and batter_side
        and pull_tendency is not None
    ):
        pull_bias = (pull_tendency - 50.0) / 50.0
        threshold = (tuning.get("shift_pull_threshold", 60.0) - 50.0) / 50.0
        if abs(pull_bias) > threshold:
            intensity = (abs(pull_bias) - threshold) / max(0.01, 1.0 - threshold)
            spray_dir = _spray_dir(spray_angle, batter_side)
            spray_scale = max(1.0, tuning.get("shift_spray_scale", 25.0))
            spray_norm = max(-1.0, min(1.0, spray_dir / spray_scale))
            align = spray_norm if pull_bias >= 0 else -spray_norm
            boost = (
                tuning.get("shift_gb_boost", 0.04)
                if ball_type == "gb"
                else tuning.get("shift_ld_boost", 0.015)
            )
            out_prob += boost * intensity * align
    if ball_type == "gb" and batter_speed is not None:
        # Release 4 (M6): a fast batter beats out softer grounders. Speed is
        # read against the league's ACT-hitter mean (decision 2), so the
        # league's BABIP stays put while the fast and slow split apart. The
        # weight ramps from 1 on weak contact to 0 on hard-hit balls. Scale 0
        # (the 7.48.0 behaviour) leaves the out chance untouched.
        scale = tuning.get("infield_hit_speed_scale", 0.0)
        if scale:
            ev_lo = tuning.get("infield_hit_ev_lo", 80.0)
            ev_hi = tuning.get("infield_hit_ev_hi", 100.0)
            span = max(1e-6, ev_hi - ev_lo)
            weight = max(0.0, min(1.0, (ev_hi - exit_velo) / span))
            centre = tuning.get("hitter_speed_center", 50.0)
            out_prob -= scale * weight * (float(batter_speed) - centre) / 10.0
    return max(0.02, min(0.98, out_prob))


def double_play_probability(
    *,
    runner_speed: float,
    infield_range: float,
    turn_arm: float,
    tuning: TuningConfig,
    batter_speed: float | None = None,
) -> float:
    """Chance a ground ball with a runner on 1st becomes a double play.

    Release 4 (M6): with ``batter_speed`` the chance is multiplied by
    ``exp(-k * (sp - hitter_speed_center) / 10)`` (k =
    ``double_play_batter_speed_k``), so a burner beats the relay and a slow
    batter is doubled up more, around the league's own mean. The result is
    capped at ``double_play_max``. ``None`` or k 0 leaves the old value.
    """
    base = tuning.get("double_play_base", 0.14)
    range_adj = (infield_range - 50.0) / 230.0
    range_adj *= tuning.get("double_play_range_scale", 1.0)
    arm_adj = (turn_arm - 50.0) / 260.0
    arm_adj *= tuning.get("double_play_arm_scale", 1.0)
    speed_adj = (runner_speed - 50.0) / 220.0
    speed_adj *= tuning.get("double_play_speed_scale", 1.0)
    prob = base + range_adj + arm_adj - speed_adj
    if batter_speed is not None:
        k = tuning.get("double_play_batter_speed_k", 0.0)
        if k:
            gap = float(batter_speed) - tuning.get("hitter_speed_center", 50.0)
            prob *= math.exp(-k * gap / 10.0)
    return max(0.03, min(tuning.get("double_play_max", 0.45), prob))


def select_out_type(ball_type: str, launch_angle: float) -> tuple[str, bool]:
    if ball_type == "gb":
        return "groundout", True
    if ball_type == "fb":
        return "flyout", False
    if launch_angle >= 18.0:
        return "flyout", False
    infield_play = random.random() < 0.45
    return "lineout", infield_play


def error_probability(
    *,
    out_type: str,
    infield_play: bool,
    fielding: float,
    arm: float,
    tuning: TuningConfig,
    position: str | None = None,
) -> float:
    """Chance a ball ruled an out is booted or thrown away instead.

    ``error_model`` 0, or no ``position``: the additive chance by out type.
    ``error_model`` 1 and 2 (Release 6a), given the fielder's ``position``:

    ``error_base_<position> * exp(-error_fa_log_slope * (fielding - 50)
    - error_arm_log_slope * (arm - 50)) * error_rate_scale``

    kept within ``ERROR_PROB_MIN`` and ``ERROR_PROB_MAX``; an infielder's
    base is times ``error_infield_liner_scale`` on a ball in the air. The
    pitcher (``"P"``) has a chance only under ``error_model`` 2.
    """
    if position is not None and tuning.get("error_model", 0.0) >= 0.5:
        if position == "P" and tuning.get("error_model", 0.0) < 1.5:
            return 0.0
        key = _ERROR_BASE_KEYS.get(position)
        base = tuning.get(key, _ERROR_BASE_OTHER) if key else _ERROR_BASE_OTHER
        if position in _INFIELD_ERROR_POS and out_type != "groundout":
            base *= tuning.get("error_infield_liner_scale", 0.25)
        prob = base * rating_error_factor(fielding=fielding, arm=arm, tuning=tuning)
        return max(ERROR_PROB_MIN, min(ERROR_PROB_MAX, prob))
    if out_type == "groundout":
        base = tuning.get("error_rate_gb", 0.018)
    elif out_type == "flyout":
        base = tuning.get("error_rate_fb", 0.008)
    else:
        base = tuning.get("error_rate_ld", 0.012)
    adj = (50.0 - fielding) / 500.0
    adj += (50.0 - arm) / 900.0
    prob = (base + adj) * tuning.get("error_rate_scale", 1.0)
    return max(0.001, min(0.12, prob))


def average_error_probability(
    *,
    out_type: str,
    infield_play: bool,
    position: str | None,
    tuning: TuningConfig,
) -> float:
    """The error chance of a league-average fielder at ``position`` on the
    same play (Release 6a, for the chance log; reads only).

    Under ``error_model`` 1 and 2 that is a 50 fielder with a 50 arm. Under
    the additive chance he is his position's centres (50 where none was
    delivered), read like any fielder: through the primary-position
    multiplier and ``range_scale``, and ``arm_strength_scale``.
    """
    if position is not None and tuning.get("error_model", 0.0) >= 0.5:
        return error_probability(
            out_type=out_type, infield_play=infield_play, fielding=50.0,
            arm=50.0, tuning=tuning, position=position,
        )
    fielding = arm = 50.0
    if not fielders_centred(tuning) and position in FIELDER_ARM_CENTER_KEYS:
        fielding = tuning.get(FIELDER_FA_CENTER_KEYS[position], 50.0)
        arm = tuning.get(FIELDER_ARM_CENTER_KEYS[position], 50.0)
    fielding *= tuning.get("defense_primary_pos_scale", 1.0)
    fielding *= tuning.get("range_scale", 1.0)
    arm *= tuning.get("arm_strength_scale", 1.0)
    return error_probability(
        out_type=out_type, infield_play=infield_play, fielding=fielding,
        arm=arm, tuning=tuning,
    )


def rating_error_factor(
    *, fielding: float = 50.0, arm: float = 50.0, tuning: TuningConfig
) -> float:
    """How a fielder's ratings scale an error rate under ``error_model`` 1
    and 2: ``exp(-error_fa_log_slope * (fielding - 50) - error_arm_log_slope
    * (arm - 50)) * error_rate_scale``. 1.0 for an average fielder at the
    default scale."""
    exponent = -tuning.get("error_fa_log_slope", 0.025) * (fielding - 50.0)
    exponent -= tuning.get("error_arm_log_slope", 0.02) * (arm - 50.0)
    return math.exp(exponent) * tuning.get("error_rate_scale", 1.0)


def extra_error_probability(
    rate_key: str,
    *,
    fielding: float = 50.0,
    arm: float = 50.0,
    tuning: TuningConfig,
) -> float:
    """Chance of one of ``error_model`` 2's errors on a play that is not a
    batted-ball out: the rate in ``rate_key`` (``error_steal_throw_rate``,
    ``error_of_hit_rate``, ``error_pickoff_throw_rate``,
    ``error_relay_throw_rate``) times :func:`rating_error_factor`, at most
    ``ERROR_PROB_MAX``. 0.0 below ``error_model`` 2: the caller must not
    draw for it."""
    if tuning.get("error_model", 0.0) < 1.5:
        return 0.0
    prob = tuning.get(rate_key, 0.0) * rating_error_factor(
        fielding=fielding, arm=arm, tuning=tuning
    )
    return max(0.0, min(ERROR_PROB_MAX, prob))


def select_error_type(
    *,
    out_type: str,
    infield_play: bool,
    fielding: float,
    arm: float,
    tuning: TuningConfig,
) -> str:
    if out_type == "groundout":
        throw_share = tuning.get("throwing_error_share_gb", 0.6)
    elif out_type == "flyout":
        throw_share = tuning.get("throwing_error_share_fb", 0.2)
    else:
        throw_share = tuning.get("throwing_error_share_ld", 0.35)

    throw_share += (50.0 - arm) / 600.0
    throw_share += (fielding - 50.0) / 700.0
    throw_share = max(0.05, min(0.9, throw_share))
    return "throwing" if random.random() < throw_share else "fielding"
