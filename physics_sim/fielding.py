from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import math
import random

from utils.roster_rules import is_catcher

from .models import BatterRatings
from .config import TuningConfig


INFIELD_POS = {"1B", "2B", "3B", "SS", "C", "P"}
OUTFIELD_POS = {"LF", "CF", "RF"}


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
    for pos, player in defense.items():
        rating = adjusted_fielding_rating(player, pos, tuning)
        pos_ratings[pos] = rating
        arm = player.arm
        arms.append(arm)
        if pos in OUTFIELD_POS:
            def_score_out.append(rating)
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
    )


def adjusted_fielding_rating(
    player: BatterRatings,
    position: str,
    tuning: TuningConfig,
) -> float:
    rating = player.fielding
    if position == player.primary_position:
        rating *= tuning.get("defense_primary_pos_scale", 1.0)
    elif position in player.other_positions:
        rating *= tuning.get("defense_secondary_pos_scale", 0.9)
    else:
        rating *= tuning.get("defense_out_of_pos_scale", 0.75)
    return rating


def adjusted_arm_rating(player: BatterRatings, tuning: TuningConfig) -> float:
    return player.arm * tuning.get("arm_strength_scale", 1.0)


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
) -> float:
    def _spray_dir(angle: float, side: str) -> float:
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
    return max(0.02, min(0.98, out_prob))


def double_play_probability(
    *,
    runner_speed: float,
    infield_range: float,
    turn_arm: float,
    tuning: TuningConfig,
) -> float:
    base = tuning.get("double_play_base", 0.14)
    range_adj = (infield_range - 50.0) / 230.0
    range_adj *= tuning.get("double_play_range_scale", 1.0)
    arm_adj = (turn_arm - 50.0) / 260.0
    arm_adj *= tuning.get("double_play_arm_scale", 1.0)
    speed_adj = (runner_speed - 50.0) / 220.0
    speed_adj *= tuning.get("double_play_speed_scale", 1.0)
    prob = base + range_adj + arm_adj - speed_adj
    return max(0.03, min(0.45, prob))


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
) -> float:
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
