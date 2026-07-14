from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any
import math
import random

from .config import TuningConfig
from .park import Park


@dataclass
class PitchResult:
    pitch_type: str
    pitch_quality: float
    velocity: float
    location: tuple[float, float]
    in_zone: bool
    swing: bool
    contact: bool
    foul: bool
    in_play: bool
    outcome: str
    called_in_zone: bool | None = None
    objective: str | None = None
    intent: str | None = None
    exit_velo: float | None = None
    launch_angle: float | None = None
    spray_angle: float | None = None
    distance: float | None = None
    ball_type: str | None = None
    hit_type: str | None = None
    out_type: str | None = None
    reached_on_error: bool = False


FASTBALL_PITCHES = {"fb", "si"}
BREAKING_PITCHES = {"sl", "cb", "kn", "scb"}
OFFSPEED_PITCHES = {"cu"}


def _weighted_choice(weights: Dict[str, float]) -> str:
    total = sum(max(0.0, w) for w in weights.values())
    if total <= 0.0:
        return next(iter(weights))
    roll = random.random() * total
    for key, weight in weights.items():
        roll -= max(0.0, weight)
        if roll <= 0:
            return key
    return next(iter(weights))


def _effective_batter_side(batter_hand: str, pitcher_hand: str) -> str:
    if batter_hand == "S":
        return "L" if pitcher_hand == "R" else "R"
    if batter_hand in {"L", "R"}:
        return batter_hand
    return "R"


def strike_zone_bounds(
    *,
    height_in: float | None,
    zone_bottom: float | None,
    zone_top: float | None,
    tuning: TuningConfig,
) -> tuple[float, float]:
    if (
        zone_bottom is not None
        and zone_top is not None
        and zone_top > zone_bottom
    ):
        return zone_bottom, zone_top
    height = height_in or tuning.get("default_height_in", 72.0)
    base_bottom = tuning.get("zone_bottom_base", 1.5)
    base_top = tuning.get("zone_top_base", 3.5)
    bottom = base_bottom + (height - 72.0) * tuning.get("zone_bottom_height_scale", 0.01)
    top = base_top + (height - 72.0) * tuning.get("zone_top_height_scale", 0.015)
    bottom = max(tuning.get("zone_bottom_min", 1.2), bottom)
    top = min(tuning.get("zone_top_max", 4.3), top)
    min_height = tuning.get("zone_min_height", 1.8)
    if top - bottom < min_height:
        top = bottom + min_height
    return bottom, top


def _plate_half_width(tuning: TuningConfig) -> float:
    return tuning.get("plate_half_width", 0.708)


def _pitch_break(
    *,
    pitch_type: str,
    movement: float,
    pitch_quality: float,
    pitcher_hand: str,
    tuning: TuningConfig,
) -> tuple[float, float]:
    base_breaks = tuning.values.get("pitch_break_base")
    base_x = base_z = 0.0
    if isinstance(base_breaks, dict):
        entry = base_breaks.get(pitch_type)
        if isinstance(entry, dict):
            try:
                base_x = float(entry.get("x", 0.0))
                base_z = float(entry.get("z", 0.0))
            except (TypeError, ValueError):
                base_x = base_z = 0.0
    arm_side = pitch_type in {"fb", "si", "cu"}
    glove_side = pitch_type in {"sl", "cb", "scb"}
    if glove_side:
        base_x = -abs(base_x)
    elif arm_side:
        base_x = abs(base_x)
    else:
        base_x = abs(base_x) * (1.0 if random.random() < 0.5 else -1.0)
    hand_dir = 1.0 if pitcher_hand == "R" else -1.0
    base_x *= hand_dir

    movement_factor = 1.0 + (movement - 50.0) / 100.0 * tuning.get(
        "break_movement_scale", 0.6
    )
    quality_factor = 1.0 + (pitch_quality - 50.0) / 100.0 * tuning.get(
        "break_quality_scale", 0.4
    )
    scale = tuning.get("break_scale", 1.0) * movement_factor * quality_factor
    sd = tuning.get("pitch_break_sd", 0.04)
    return (
        base_x * scale + random.gauss(0.0, sd),
        base_z * scale + random.gauss(0.0, sd),
    )

def _weight_map(value: Any) -> Dict[str, float]:
    if not isinstance(value, dict):
        return {}
    weights: Dict[str, float] = {}
    for key, raw in value.items():
        try:
            weights[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return weights


def _merge_weight_map(
    base: Dict[str, float], overrides: Dict[str, float]
) -> Dict[str, float]:
    merged = dict(base)
    merged.update(overrides)
    return merged


def _apply_weight_mods(
    weights: Dict[str, float], mods: Dict[str, float]
) -> Dict[str, float]:
    if not mods:
        return weights
    for key, value in mods.items():
        if key in weights:
            weights[key] *= value
    return weights


def _objective_weights_for_count(
    balls: int, strikes: int, tuning: TuningConfig
) -> Dict[str, float]:
    default = _weight_map(tuning.values.get("pitch_objective_default"))
    if not default:
        default = {
            "attack": 1.0,
            "edge": 0.7,
            "chase": 0.4,
            "waste": 0.2,
            "putaway": 0.35,
        }
    count_table = tuning.values.get("pitch_objective_count_weights")
    count_weights: Dict[str, float] = {}
    if isinstance(count_table, dict):
        count_weights = _weight_map(count_table.get(f"{balls}-{strikes}"))
    return _merge_weight_map(default, count_weights)


def choose_pitch_objective(
    *,
    balls: int,
    strikes: int,
    tuning: TuningConfig,
    context: Dict[str, Any] | None = None,
) -> str:
    weights = _objective_weights_for_count(balls, strikes, tuning)
    if strikes >= 2:
        weights = _apply_weight_mods(
            weights, _weight_map(tuning.values.get("pitch_objective_two_strike_mod"))
        )
    if balls >= 3:
        weights = _apply_weight_mods(
            weights, _weight_map(tuning.values.get("pitch_objective_three_ball_mod"))
        )
    if context:
        bases = context.get("bases") or {}
        risp = bool(bases.get("second") or bases.get("third"))
        if risp:
            weights = _apply_weight_mods(
                weights, _weight_map(tuning.values.get("pitch_objective_risp_mod"))
            )
        if not bases.get("first"):
            weights = _apply_weight_mods(
                weights,
                _weight_map(tuning.values.get("pitch_objective_first_base_open_mod")),
            )
        inning = int(context.get("inning", 1) or 1)
        score_diff = int(context.get("score_diff", 0) or 0)
        close_diff = int(tuning.get("close_game_run_diff", 2.0))
        late_inning = int(tuning.get("pitch_objective_late_inning", 7.0))
        if inning >= late_inning and abs(score_diff) <= close_diff:
            weights = _apply_weight_mods(
                weights, _weight_map(tuning.values.get("pitch_objective_late_close_mod"))
            )
        pitches_seen = int(context.get("batter_pitches_seen", 0) or 0)
        min_pitches = int(tuning.get("batter_aggression_min_pitches", 6.0))
        swing_rate = context.get("batter_swing_rate")
        chase_rate = context.get("batter_chase_rate")
        if pitches_seen >= min_pitches and swing_rate is not None:
            if swing_rate >= tuning.get("batter_aggression_high", 0.52):
                weights = _apply_weight_mods(
                    weights, _weight_map(tuning.values.get("pitch_objective_aggressive_mod"))
                )
            elif swing_rate <= tuning.get("batter_aggression_low", 0.42):
                weights = _apply_weight_mods(
                    weights, _weight_map(tuning.values.get("pitch_objective_passive_mod"))
                )
        if pitches_seen >= min_pitches and chase_rate is not None:
            if chase_rate >= tuning.get("batter_chase_high", 0.38):
                weights = _apply_weight_mods(
                    weights, _weight_map(tuning.values.get("pitch_objective_chase_mod"))
                )
    return _weighted_choice(weights)


def _objective_intent(objective: str, tuning: TuningConfig) -> str:
    intent_map = tuning.values.get("pitch_objective_intent_map")
    if isinstance(intent_map, dict):
        intent = intent_map.get(objective)
        if isinstance(intent, str):
            return intent
    return "zone"


def choose_pitch_type(
    *,
    repertoire: Dict[str, float],
    batter: Dict[str, float],
    count: tuple[int, int],
    objective: str,
    tuning: TuningConfig,
    context: Dict[str, Any] | None = None,
) -> str:
    balls, strikes = count
    weights: Dict[str, float] = {}
    batter_power = batter.get("power", 50.0)
    batter_eye = batter.get("eye", 50.0)
    objective_bias = tuning.values.get("pitch_objective_group_bias")
    bias_map = {}
    if isinstance(objective_bias, dict):
        bias_map = objective_bias.get(objective, {})

    for pitch_type, rating in repertoire.items():
        weight = max(1.0, float(rating))
        if pitch_type in FASTBALL_PITCHES:
            weight *= tuning.get("pitch_seq_fastball_bias", 1.0)
            if balls == 0 and strikes == 0:
                weight *= tuning.get("pitch_seq_first_pitch_fastball", 1.1)
            if balls > strikes:
                weight *= tuning.get("pitch_seq_behind_fastball", 1.15)
            if strikes > balls:
                weight *= tuning.get("pitch_seq_ahead_fastball", 0.9)
            if batter_power >= 60.0:
                weight *= tuning.get("pitch_seq_power_avoid_fastball", 0.92)
            if isinstance(bias_map, dict):
                weight *= float(bias_map.get("fastball", 1.0))
        elif pitch_type in BREAKING_PITCHES:
            weight *= tuning.get("pitch_seq_breaking_bias", 1.0)
            if strikes >= 2:
                weight *= tuning.get("pitch_seq_two_strike_breaking", 1.25)
            if strikes > balls:
                weight *= tuning.get("pitch_seq_ahead_breaking", 1.1)
            if batter_eye >= 60.0:
                weight *= tuning.get("pitch_seq_eye_avoid_breaking", 0.95)
            if isinstance(bias_map, dict):
                weight *= float(bias_map.get("breaking", 1.0))
        else:
            weight *= tuning.get("pitch_seq_offspeed_bias", 1.0)
            if balls > strikes:
                weight *= tuning.get("pitch_seq_behind_offspeed", 0.95)
            if isinstance(bias_map, dict):
                weight *= float(bias_map.get("offspeed", 1.0))
        weights[pitch_type] = weight
    if context:
        last_pitch = context.get("last_pitch_type")
        if isinstance(last_pitch, str) and last_pitch in weights:
            repeat_count = int(context.get("last_pitch_repeat", 0) or 0)
            repeat_scale = tuning.get("pitch_seq_repeat_scale", 0.85)
            repeat_floor = tuning.get("pitch_seq_repeat_floor", 0.4)
            if repeat_count <= 0:
                repeat_count = 1
            multiplier = repeat_scale ** repeat_count
            multiplier = max(repeat_floor, multiplier)
            weights[last_pitch] *= multiplier
    return _weighted_choice(weights)


def _sample_edge_location(
    *,
    plate_half_width: float,
    zone_center: float,
    zone_half_height: float,
    inner: float,
    outer: float,
    zone_inner: float,
) -> tuple[float, float]:
    axis = "x" if random.random() < 0.5 else "y"
    sign = -1.0 if random.random() < 0.5 else 1.0
    if axis == "x":
        x = sign * random.uniform(plate_half_width * inner, plate_half_width * outer)
        y = zone_center + random.uniform(
            -zone_half_height * zone_inner, zone_half_height * zone_inner
        )
        return x, y
    x = random.uniform(-plate_half_width * zone_inner, plate_half_width * zone_inner)
    y = zone_center + sign * random.uniform(zone_half_height * inner, zone_half_height * outer)
    return x, y


def sample_pitch_location(
    *,
    intent: str,
    in_zone_target: bool,
    zone_bottom: float,
    zone_top: float,
    tuning: TuningConfig,
) -> tuple[float, float]:
    plate_half = _plate_half_width(tuning)
    zone_center = (zone_bottom + zone_top) / 2.0
    zone_half_height = max(0.4, (zone_top - zone_bottom) / 2.0)
    zone_inner = tuning.get("intent_zone_inner", 0.75)

    effective_intent = intent
    if intent == "zone" and not in_zone_target:
        effective_intent = "edge"
    elif intent == "edge" and not in_zone_target:
        effective_intent = "chase"

    if effective_intent == "zone":
        return (
            random.uniform(-plate_half * zone_inner, plate_half * zone_inner),
            zone_center
            + random.uniform(-zone_half_height * zone_inner, zone_half_height * zone_inner),
        )
    if effective_intent == "edge":
        return _sample_edge_location(
            plate_half_width=plate_half,
            zone_center=zone_center,
            zone_half_height=zone_half_height,
            inner=tuning.get("intent_edge_inner", 0.85),
            outer=tuning.get("intent_edge_outer", 1.05),
            zone_inner=zone_inner,
        )
    if effective_intent == "chase":
        return _sample_edge_location(
            plate_half_width=plate_half,
            zone_center=zone_center,
            zone_half_height=zone_half_height,
            inner=tuning.get("intent_chase_inner", 1.05),
            outer=tuning.get("intent_chase_outer", 1.5),
            zone_inner=zone_inner,
        )
    if effective_intent == "waste":
        return _sample_edge_location(
            plate_half_width=plate_half,
            zone_center=zone_center,
            zone_half_height=zone_half_height,
            inner=tuning.get("intent_waste_inner", 1.3),
            outer=tuning.get("intent_waste_outer", 2.2),
            zone_inner=zone_inner,
        )
    return (
        random.uniform(-plate_half * zone_inner, plate_half * zone_inner),
        zone_center
        + random.uniform(-zone_half_height * zone_inner, zone_half_height * zone_inner),
    )


def sample_pitch_velocity(base_velo: float, fatigue: float, tuning: TuningConfig) -> float:
    scale = tuning.get("velocity_scale", 1.0)
    return base_velo * scale * fatigue


def _command_error(
    *, control: float, movement: float, tuning: TuningConfig
) -> tuple[float, float]:
    miss = max(0.0, (100.0 - control) / 100.0)
    base_x = tuning.get("command_error_base_x", 0.08)
    base_y = tuning.get("command_error_base_y", 0.1)
    scale = tuning.get("command_error_scale", 2.2)
    movement_adj = max(0.0, (movement - 50.0) / 50.0)
    movement_penalty = tuning.get("movement_command_penalty", 0.4)
    multiplier = 1.0 + miss * scale + movement_adj * movement_penalty
    multiplier *= tuning.get("command_variance_scale", 1.0)
    return base_x * multiplier, base_y * multiplier


def miss_distance(
    *,
    location: tuple[float, float],
    zone_bottom: float,
    zone_top: float,
    tuning: TuningConfig,
) -> float:
    x, y = location
    plate_half = _plate_half_width(tuning)
    zone_height = max(0.5, zone_top - zone_bottom)
    x_over = max(0.0, abs(x) - plate_half) / plate_half
    if y < zone_bottom:
        y_over = (zone_bottom - y) / zone_height
    elif y > zone_top:
        y_over = (y - zone_top) / zone_height
    else:
        y_over = 0.0
    return (x_over + y_over) / 2.0


def _edge_distance(
    *,
    location: tuple[float, float],
    zone_bottom: float,
    zone_top: float,
    tuning: TuningConfig,
    plate_half_width: float | None = None,
) -> float:
    x, y = location
    plate_half = plate_half_width if plate_half_width is not None else _plate_half_width(tuning)
    x_over = max(0.0, abs(x) - plate_half)
    if y < zone_bottom:
        y_over = zone_bottom - y
    elif y > zone_top:
        y_over = y - zone_top
    else:
        y_over = 0.0
    return max(x_over, y_over)


def _called_strike(
    *,
    location: tuple[float, float],
    zone_bottom: float,
    zone_top: float,
    catcher_fielding: float,
    intent: str | None,
    tuning: TuningConfig,
    plate_half_width: float | None = None,
) -> bool:
    margin = tuning.get("umpire_margin_ft", 0.06)
    margin += (catcher_fielding - 50.0) / 100.0 * tuning.get(
        "framing_margin_scale", 0.04
    )
    if margin <= 0:
        return False
    edge_dist = _edge_distance(
        location=location,
        zone_bottom=zone_bottom,
        zone_top=zone_top,
        tuning=tuning,
        plate_half_width=plate_half_width,
    )
    if edge_dist > margin:
        return False
    prob = tuning.get("framing_strike_chance", 0.55)
    prob += (catcher_fielding - 50.0) / 100.0 * tuning.get(
        "framing_prob_scale", 0.2
    )
    intent_mods = tuning.values.get("called_strike_intent_mod")
    if intent and isinstance(intent_mods, dict):
        try:
            prob *= float(intent_mods.get(intent, 1.0))
        except (TypeError, ValueError):
            pass
    prob = max(0.05, min(0.95, prob))
    return random.random() < prob


def _count_modifier(
    mapping: Any,
    *,
    count_key: str,
    default: float,
    field: str | None = None,
) -> float:
    if not isinstance(mapping, dict):
        return default
    entry = mapping.get(count_key)
    if entry is None:
        return default
    if field is not None:
        if isinstance(entry, dict):
            try:
                return float(entry.get(field, default))
            except (TypeError, ValueError):
                return default
        return default
    try:
        return float(entry)
    except (TypeError, ValueError):
        return default


def simulate_pitch(
    *,
    batter: Dict[str, Any],
    pitcher: Dict[str, Any],
    tuning: TuningConfig,
    count: tuple[int, int],
    context: Dict[str, Any] | None = None,
) -> PitchResult:
    """Placeholder pitch simulation; will be replaced with full physics model."""

    repertoire = pitcher.get("repertoire", {"fb": 50})
    objective = choose_pitch_objective(
        balls=count[0], strikes=count[1], tuning=tuning, context=context
    )
    pitch_type = choose_pitch_type(
        repertoire=repertoire,
        batter=batter,
        count=count,
        objective=objective,
        tuning=tuning,
        context=context,
    )
    pitch_quality = float(repertoire.get(pitch_type, 50.0))
    fatigue = pitcher.get("fatigue_factor", 1.0)
    velocity = sample_pitch_velocity(pitcher.get("velocity", 90.0), fatigue, tuning)
    # Per-type velocity: offspeed/breaking pitches arrive slower than the
    # fastball (previously all types shared one speed, so the whiff/EV
    # velocity terms couldn't tell a curveball from a heater).
    _type_offsets = tuning.values.get("pitch_type_velocity_offset") or {}
    try:
        velocity += float(_type_offsets.get(pitch_type, 0.0))
    except (TypeError, ValueError):
        pass
    control = pitcher.get("control", 50.0)
    movement = pitcher.get("movement", 50.0)
    pitcher_hand = (pitcher.get("hand") or "R").upper()
    batter_hand = (batter.get("bats") or "R").upper()
    batter_side = batter.get("batter_side") or _effective_batter_side(
        batter_hand, pitcher_hand
    )
    if batter_side == "L":
        pitch_quality += (
            (pitcher.get("vs_left", 50.0) - 50.0)
            * tuning.get("platoon_pitcher_scale", 0.25)
        )
    pitch_quality = max(1.0, min(100.0, pitch_quality))
    zone_bottom, zone_top = strike_zone_bounds(
        height_in=batter.get("height"),
        zone_bottom=batter.get("zone_bottom"),
        zone_top=batter.get("zone_top"),
        tuning=tuning,
    )
    zone_center = (zone_bottom + zone_top) / 2.0
    zone_half_height = max(0.5, (zone_top - zone_bottom) / 2.0)
    plate_half = _plate_half_width(tuning)
    ball_radius = tuning.get("ball_radius_ft", 0.12)
    balls, strikes = count
    zone_target = tuning.get("zone_target_base", 0.50)
    zone_target += (control - 50.0) * tuning.get("zone_target_control_scale", 0.0025)
    zone_target += (strikes - balls) * tuning.get("zone_target_count_scale", 0.03)
    zone_adjust = _weight_map(tuning.values.get("pitch_objective_zone_adjust"))
    if objective in zone_adjust:
        zone_target += zone_adjust[objective]
    zone_target = max(0.15, min(0.85, zone_target))
    in_zone_target = random.random() < zone_target
    intent = _objective_intent(objective, tuning)
    target_x, target_y = sample_pitch_location(
        intent=intent,
        in_zone_target=in_zone_target,
        zone_bottom=zone_bottom,
        zone_top=zone_top,
        tuning=tuning,
    )
    cmd_x_sd, cmd_y_sd = _command_error(
        control=control, movement=movement, tuning=tuning
    )
    aim_x = target_x + random.gauss(0.0, cmd_x_sd)
    aim_y = target_y + random.gauss(0.0, cmd_y_sd)
    break_x, break_z = _pitch_break(
        pitch_type=pitch_type,
        movement=movement,
        pitch_quality=pitch_quality,
        pitcher_hand=pitcher_hand,
        tuning=tuning,
    )
    loc = (aim_x + break_x, aim_y + break_z)
    break_mag = math.hypot(break_x, break_z)

    # Simple swing decision: zone vs chase.
    zone_scale = tuning.get("zone_swing_scale", 1.0)
    chase_scale = tuning.get("chase_scale", 1.0)
    eye = batter.get("eye", batter.get("contact", 50.0)) * tuning.get("eye_scale", 1.0)
    in_zone = (
        abs(loc[0]) <= plate_half + ball_radius
        and zone_bottom - ball_radius <= loc[1] <= zone_top + ball_radius
    )
    called_shrink = max(0.0, tuning.get("called_zone_shrink_ft", 0.0))
    zone_height = max(0.5, zone_top - zone_bottom)
    max_shrink = min(plate_half + ball_radius - 0.05, zone_height / 2.0 - 0.05)
    if max_shrink < 0.0:
        max_shrink = 0.0
    if called_shrink > max_shrink:
        called_shrink = max_shrink
    called_half = plate_half + ball_radius - called_shrink
    called_bottom = zone_bottom - ball_radius + called_shrink
    called_top = zone_top + ball_radius - called_shrink
    if called_top <= called_bottom:
        called_bottom = zone_bottom - ball_radius
        called_top = zone_top + ball_radius
        called_half = plate_half + ball_radius
    called_in_zone = (
        abs(loc[0]) <= called_half and called_bottom <= loc[1] <= called_top
    )
    loc_miss = miss_distance(
        location=loc, zone_bottom=zone_bottom, zone_top=zone_top, tuning=tuning
    )
    hbp_rate = tuning.get("hbp_rate", 0.003)
    hbp_rate *= 1.0 + (50.0 - control) / 120.0
    hbp_rate *= 1.0 + loc_miss
    if random.random() < hbp_rate:
        return PitchResult(
            pitch_type=pitch_type,
            pitch_quality=pitch_quality,
            velocity=velocity,
            location=loc,
            in_zone=in_zone,
            called_in_zone=called_in_zone,
            swing=False,
            contact=False,
            foul=False,
            in_play=False,
            outcome="hbp",
            objective=objective,
            intent=intent,
        )
    zone_base = 0.62 + (eye - 50.0) / 220.0
    chase_base = 0.28 - (eye - 50.0) / 260.0
    chase_base += batter.get("platoon_chase", 0.0)
    base_swing = zone_base if in_zone else chase_base
    base_swing *= zone_scale if in_zone else chase_scale
    if strikes >= 2:
        aggression = tuning.get("two_strike_aggression_scale", 1.0)
        base_swing += 0.10 * aggression if in_zone else 0.08 * aggression
    count_key = f"{balls}-{strikes}"
    swing_bonus = _count_modifier(
        tuning.values.get("count_swing_bonus"),
        count_key=count_key,
        default=0.0,
        field="zone" if in_zone else "chase",
    )
    base_swing += swing_bonus
    if balls == 3:
        take_scale = (
            tuning.get("take_on_3_0_scale", 0.35)
            if strikes == 0
            else tuning.get("take_on_3_1_scale", 0.65)
        )
        base_swing *= take_scale
    walk_scale = tuning.get("walk_scale", 1.0)
    if walk_scale > 0:
        base_swing = base_swing / walk_scale if not in_zone else base_swing
    base_swing = max(0.02, min(0.98, base_swing))
    swing = random.random() < base_swing
    if not swing and strikes >= 2:
        protect = (
            tuning.get("two_strike_zone_protect", 0.0)
            if in_zone
            else tuning.get("two_strike_chase_protect", 0.0)
        )
        if protect > 0 and random.random() < protect:
            swing = True

    contact = False
    foul = False
    in_play = False
    outcome = "ball"
    exit_velo = None
    launch_angle = None
    spray_angle = None
    distance = None
    ball_type = None
    hit_type = None

    if swing:
        ci_rate = tuning.get("catcher_interference_rate", 0.0005)
        if random.random() < ci_rate:
            return PitchResult(
                pitch_type=pitch_type,
                pitch_quality=pitch_quality,
                velocity=velocity,
                location=loc,
                in_zone=in_zone,
                called_in_zone=called_in_zone,
                swing=True,
                contact=False,
                foul=False,
                in_play=False,
                outcome="interference",
                objective=objective,
                intent=intent,
            )
        pitch_quality = control * 0.4 + movement * 0.4 + pitch_quality * 0.2
        pitch_quality *= tuning.get("pitching_dom_scale", 1.0)
        whiff_prob = tuning.get("whiff_base", 0.05)
        whiff_prob += max(0.0, (pitch_quality - 50.0) / 100.0) * tuning.get(
            "whiff_quality_scale", 0.25
        )
        whiff_prob += max(0.0, (velocity - 90.0) / 20.0) * tuning.get(
            "whiff_velocity_scale", 0.15
        )
        whiff_prob += min(1.0, break_mag / 0.4) * tuning.get(
            "whiff_break_scale", 0.2
        )
        whiff_prob += min(1.0, loc_miss) * tuning.get("whiff_location_scale", 0.12)
        if not in_zone:
            whiff_prob *= tuning.get("whiff_chase_scale", 1.05)
        whiff_prob = max(0.0, min(0.6, whiff_prob))
        contact_base = batter.get("contact", 50.0) - (pitch_quality - 50.0) * 0.4
        contact_base -= break_mag * tuning.get("break_contact_penalty", 5.0)
        contact_prob_scale = tuning.get("contact_prob_scale", 1.0)
        contact_prob = min(
            0.95,
            max(0.05, (contact_base / 100.0) * contact_prob_scale),
        )
        if not in_zone:
            contact_prob *= tuning.get("chase_contact_scale", 1.0)
        contact_prob *= _count_modifier(
            tuning.values.get("count_contact_scale"),
            count_key=count_key,
            default=1.0,
        )
        contact_prob /= max(0.1, tuning.get("k_scale", 1.0))
        contact_prob = max(0.0, min(contact_prob, 1.0 - whiff_prob))
        if random.random() < whiff_prob:
            contact = False
        else:
            no_whiff = max(1e-6, 1.0 - whiff_prob)
            contact = random.random() < (contact_prob / no_whiff)
        if contact:
            batter_contact = batter.get("contact", 50.0)
            difficulty = 0.0
            difficulty += max(0.0, (pitch_quality - 50.0) / 100.0)
            difficulty += max(0.0, (velocity - 90.0) / 20.0)
            difficulty += min(1.0, break_mag / 0.4) * 0.5
            skill_factor = 0.8 + (1.0 - batter_contact / 100.0) * 0.6
            timing_sd = tuning.get("timing_error_base", 0.22)
            timing_sd *= 1.0 + difficulty * tuning.get("timing_error_scale", 0.6)
            timing_sd *= skill_factor
            barrel_sd = tuning.get("barrel_error_base", 0.24)
            barrel_sd *= 1.0 + difficulty * tuning.get("barrel_error_scale", 0.6)
            barrel_sd *= skill_factor
            timing_error = random.gauss(0.0, timing_sd)
            barrel_error = random.gauss(0.0, barrel_sd)
            timing_quality = max(0.0, 1.0 - abs(timing_error))
            barrel_quality = max(0.0, 1.0 - abs(barrel_error))
            timing_weight = tuning.get("timing_quality_weight", 0.6)
            barrel_weight = tuning.get("barrel_quality_weight", 0.4)
            weight_sum = timing_weight + barrel_weight
            if weight_sum <= 0:
                weight_sum = 1.0
            contact_quality = (
                timing_quality * timing_weight + barrel_quality * barrel_weight
            ) / weight_sum
            bat_speed = tuning.get("bat_speed_base", 62.0)
            bat_speed += (batter.get("power", 50.0) - 50.0) * tuning.get(
                "bat_speed_power_scale", 0.55
            )
            bat_speed += (batter.get("contact", 50.0) - 50.0) * tuning.get(
                "bat_speed_contact_scale", 0.2
            )
            bat_speed = max(35.0, bat_speed)
            ev_base = (
                velocity * tuning.get("ev_pitch_weight", 0.48)
                + bat_speed * tuning.get("ev_bat_weight", 0.7)
            )
            ev_base += random.gauss(0.0, tuning.get("exit_velo_sd", 5.0))
            quality = 0.85 + (contact_base - 50.0) / 250.0
            quality *= max(0.75, 1.0 - (pitch_quality - 50.0) / 250.0)
            quality *= 0.7 + 0.6 * contact_quality
            quality *= max(
                0.65,
                1.0 - abs(timing_error) * tuning.get("timing_ev_penalty", 0.18),
            )
            quality *= max(
                0.65,
                1.0 - abs(barrel_error) * tuning.get("barrel_ev_penalty", 0.22),
            )
            quality = max(0.5, min(1.2, quality))
            exit_velo = max(50.0, ev_base * quality)
            exit_velo *= tuning.get("contact_quality_scale", 1.0)
            exit_velo *= tuning.get("offense_scale", 1.0)
            softcap = tuning.get("exit_velo_softcap", 0.0)
            if softcap and exit_velo > softcap:
                high_scale = tuning.get("exit_velo_softcap_scale", 0.5)
                exit_velo = softcap + (exit_velo - softcap) * high_scale
            gb_bias = (batter.get("gb_tendency", 50.0) - 50.0) / 10.0
            launch_angle_base = tuning.get("launch_angle_base", 10.0)
            launch_angle = random.gauss(
                launch_angle_base - gb_bias, tuning.get("launch_angle_sd", 11.0)
            )
            vertical_loc = 0.0
            if zone_half_height > 0:
                vertical_loc = (loc[1] - zone_center) / zone_half_height
                vertical_loc = max(-1.5, min(1.5, vertical_loc))
            launch_angle += vertical_loc * tuning.get("location_launch_scale", 10.0)
            launch_angle += timing_error * tuning.get("timing_launch_scale", 8.0)
            launch_angle += random.gauss(
                0.0, abs(barrel_error) * tuning.get("barrel_launch_sd_scale", 4.0)
            )
            launch_angle *= tuning.get("gb_fb_tilt", 1.0)
            launch_angle = max(-20.0, min(60.0, launch_angle))
            pull_bias = (batter.get("pull_tendency", 50.0) - 50.0) / 2.0
            spray_angle = random.gauss(
                pull_bias + timing_error * tuning.get("timing_spray_scale", 12.0),
                18.0,
            )
            foul_rate = tuning.get("foul_rate", 0.26)
            quality_penalty = 1.0 - contact_quality
            foul_rate *= 1.0 + quality_penalty * tuning.get("foul_quality_scale", 0.5)
            pitch_quality_factor = max(0.0, (pitch_quality - 50.0) / 50.0)
            foul_rate *= 1.0 + pitch_quality_factor * tuning.get(
                "foul_pitch_quality_scale", 0.25
            )
            x_norm = abs(loc[0]) / max(0.01, plate_half + ball_radius)
            y_norm = 0.0
            if zone_half_height > 0:
                y_norm = abs((loc[1] - zone_center) / zone_half_height)
            edge_factor = min(1.0, max(x_norm, y_norm))
            foul_rate *= 1.0 + edge_factor * tuning.get("foul_location_scale", 0.35)
            if not in_zone:
                foul_rate *= tuning.get("foul_chase_scale", 1.05)
            if strikes >= 2:
                foul_rate *= tuning.get("two_strike_foul_scale", 1.0)
            foul_territory = 1.0
            if context:
                try:
                    foul_territory = float(context.get("foul_territory_scale", 1.0))
                except (TypeError, ValueError):
                    foul_territory = 1.0
            foul_rate *= 1.0 + (foul_territory - 1.0) * tuning.get(
                "foul_territory_scale", 1.0
            )
            foul_rate *= _count_modifier(
                tuning.values.get("count_foul_scale"),
                count_key=count_key,
                default=1.0,
            )
            foul_rate = max(0.05, min(0.9, foul_rate))
            foul = random.random() < foul_rate
            in_play = not foul
            outcome = "in_play" if in_play else "foul"
        else:
            outcome = "swinging_strike"

    if not swing and not in_zone:
        catcher_fielding = 50.0
        if context:
            try:
                catcher_fielding = float(context.get("catcher_fielding", 50.0))
            except (TypeError, ValueError):
                catcher_fielding = 50.0
        if _called_strike(
            location=loc,
            zone_bottom=called_bottom,
            zone_top=called_top,
            catcher_fielding=catcher_fielding,
            intent=intent,
            tuning=tuning,
            plate_half_width=called_half,
        ):
            outcome = "strike"
    if not swing and called_in_zone:
        outcome = "strike"

    return PitchResult(
        pitch_type=pitch_type,
        pitch_quality=pitch_quality,
        velocity=velocity,
        location=loc,
        in_zone=in_zone,
        called_in_zone=called_in_zone,
        swing=swing,
        contact=contact,
        foul=foul,
        in_play=in_play,
        outcome=outcome,
        objective=objective,
        intent=intent,
        exit_velo=exit_velo,
        launch_angle=launch_angle,
        spray_angle=spray_angle,
        distance=distance,
        ball_type=ball_type,
        hit_type=hit_type,
        out_type=None,
        reached_on_error=False,
    )


def classify_ball_type(launch_angle: float, tuning: TuningConfig) -> str:
    gb_cutoff = tuning.get("bip_gb_cutoff", 6.0)
    ld_cutoff = tuning.get("bip_ld_cutoff", 13.0)
    if launch_angle < gb_cutoff:
        return "gb"
    if launch_angle < ld_cutoff:
        return "ld"
    return "fb"


def spray_to_field_angle(spray_deg: float) -> float:
    """Convert spray angle to stadium angle in radians (0=RF line, pi/2=LF line)."""

    return max(0.0, min(math.pi / 2, math.radians(45.0 - spray_deg)))


def estimate_carry_distance(
    exit_velo: float,
    launch_angle: float,
    tuning: TuningConfig,
    park: Park,
) -> float:
    ev_ft_s = exit_velo * 1.467
    theta = math.radians(max(1.0, min(60.0, launch_angle)))
    g = 32.17
    carry_scale = 0.75 * tuning.get("hr_scale", 1.0) * tuning.get("offense_scale", 1.0)
    altitude_ft = 0.0
    try:
        altitude_ft = float(getattr(park, "altitude_ft", 0.0) or 0.0)
    except (TypeError, ValueError):
        altitude_ft = 0.0
    altitude_factor = 1.0 + altitude_ft * tuning.get("altitude_ft_scale", 0.0)
    altitude_factor = max(0.9, min(1.25, altitude_factor))
    park_factor_scale = tuning.get("park_factor_scale", 1.0)
    park_factor = 1.0 + (park.park_factor - 1.0) * park_factor_scale
    carry_scale *= tuning.get("altitude_scale", 1.0) * park_factor * altitude_factor
    return (ev_ft_s**2 / g) * math.sin(2 * theta) * carry_scale


def resolve_batted_ball(
    *,
    exit_velo: float,
    launch_angle: float,
    spray_angle: float,
    park: Park,
    tuning: TuningConfig,
    batter_speed: float | None = None,
    batter_contact: float | None = None,
    batter_power: float | None = None,
) -> tuple[float, bool, str, str | None]:
    """Return (distance, is_hr, ball_type, hit_type)."""

    ball_type = classify_ball_type(launch_angle, tuning)
    dist = estimate_carry_distance(exit_velo, launch_angle, tuning, park)
    angle = spray_to_field_angle(spray_angle)
    park_scale = tuning.get("park_size_scale", 1.0)
    wall = park.stadium.wall_distance(angle) * park_scale
    if dist > wall:
        return dist, True, ball_type, "hr"
    # Non-HR hit type determined by wall-relative distance.
    speed_norm = 0.0
    if batter_speed is not None:
        try:
            speed_norm = (float(batter_speed) - 50.0) / 50.0
        except (TypeError, ValueError):
            speed_norm = 0.0
        speed_norm = max(-1.0, min(1.0, speed_norm))
    gap_norm = 0.0
    if batter_contact is not None or batter_power is not None:
        try:
            contact = float(batter_contact) if batter_contact is not None else 50.0
            power = float(batter_power) if batter_power is not None else 50.0
        except (TypeError, ValueError):
            contact = 50.0
            power = 50.0
        gap_norm = ((contact + power) / 2.0 - 50.0) / 50.0
        gap_norm = max(-1.0, min(1.0, gap_norm))
    double_scale = tuning.get("double_distance_scale", 1.0)
    triple_scale = tuning.get("triple_distance_scale", 1.0)
    double_speed = 1.0 - speed_norm * tuning.get("double_speed_scale", 0.0)
    triple_speed = 1.0 - speed_norm * tuning.get("triple_speed_scale", 0.0)
    double_gap = 1.0 - gap_norm * tuning.get("double_gap_scale", 0.0)
    double_threshold = (
        park.stadium.double_distance(angle)
        * park_scale
        * double_scale
        * double_speed
        * double_gap
    )
    triple_threshold = (
        park.stadium.triple_distance(angle) * park_scale * triple_scale * triple_speed
    )
    if triple_threshold <= double_threshold:
        triple_threshold = double_threshold + 1.0
    if dist >= triple_threshold:
        hit_type = "triple"
    elif dist >= double_threshold:
        hit_type = "double"
    else:
        hit_type = "single"
    return dist, False, ball_type, hit_type
