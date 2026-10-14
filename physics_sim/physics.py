from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any
import math
import random

from .centred_ratings import rating_center
from .config import DEFAULT_TUNING, TuningConfig
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



def _power_bat_speed(power: float, tuning: TuningConfig) -> float:
    """Bat speed added by the Power rating, relative to an average hitter.

    Linear below the knee; above it each point adds ``bat_speed_power_knee_scale``
    more. Home runs are a distance-vs-fence threshold, so a steep LINEAR slope
    turned an ordinary power spread into dozens of 30-homer seasons -- which is
    why S2-08 flattened power to 0.09 and handed home runs to the Contact rating.
    A knee lets average hitters stay average while genuine sluggers separate.

    The defaults (knee 100, no extra slope) reproduce the old linear formula.
    """

    scale = tuning.get("bat_speed_power_scale", 0.55)
    knee = tuning.get("bat_speed_power_knee", 100.0)
    knee_scale = tuning.get("bat_speed_power_knee_scale", 0.0)
    delta = (float(power) - 50.0) * scale
    if power > knee:
        delta += (float(power) - knee) * knee_scale
    return delta


def _batter_power_bat_speed(batter: Dict[str, Any], tuning: TuningConfig) -> float:
    """Bat speed from the batter's Power in this plate appearance.

    ``batter["power"]`` is his Power rating plus the situational bonuses
    (handedness, his vl split, times through the order). Run through the
    curve above, a bonus point is worth ``bat_speed_power_scale`` mph below
    the knee and that plus ``bat_speed_power_knee_scale`` above it, so the
    same platoon edge was a far bigger home-run edge for a hitter a point
    above the knee than for one a point below (audit H7).

    With ``platoon_power_after_knee`` on, the curve reads his own Power
    (``power_base``) and every bonus point adds a flat
    ``platoon_bat_speed_per_point`` mph, whatever his Power.
    """

    power = batter.get("power", 50.0)
    if tuning.get("platoon_power_after_knee", 0.0) >= 0.5:
        base = batter.get("power_base", power)
        return _power_bat_speed(base, tuning) + (power - base) * tuning.get(
            "platoon_bat_speed_per_point", 0.35
        )
    return _power_bat_speed(power, tuning)


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


def _objective_weight_table(
    tuning: TuningConfig,
) -> Dict[tuple[int, int], Dict[str, float]]:
    """Per-count objective weights with the 2-strike / 3-ball mods folded in,
    computed once per TuningConfig (S1-09). Built with the exact same helper
    sequence the per-pitch path used, so key insertion order — which drives
    ``_weighted_choice`` iteration and therefore RNG parity — is unchanged.
    """
    table = tuning.__dict__.get("_objective_table")
    if table is not None:
        return table
    table = {}
    for balls in range(4):
        for strikes in range(3):
            weights = _objective_weights_for_count(balls, strikes, tuning)
            if strikes >= 2:
                weights = _apply_weight_mods(
                    weights,
                    _weight_map(tuning.values.get("pitch_objective_two_strike_mod")),
                )
            if balls >= 3:
                weights = _apply_weight_mods(
                    weights,
                    _weight_map(tuning.values.get("pitch_objective_three_ball_mod")),
                )
            table[(balls, strikes)] = weights
    tuning.__dict__["_objective_table"] = table
    return table


def choose_pitch_objective(
    *,
    balls: int,
    strikes: int,
    tuning: TuningConfig,
    context: Dict[str, Any] | None = None,
) -> str:
    # Copy the cached count table entry: the context mods below mutate in
    # place, and the cache must stay pristine.
    weights = dict(
        _objective_weight_table(tuning)[(min(balls, 3), min(strikes, 2))]
    )
    if context:
        bases = context.get("bases") or {}
        risp = bool(bases.get("second") or bases.get("third"))
        if risp:
            weights = _apply_weight_mods(
                weights, _weight_map(tuning.values.get("pitch_objective_risp_mod"))
            )
        # Release 5: with the switch on, an open first base matters only with
        # a runner in scoring position (not with the bases empty).
        if not bases.get("first") and (
            risp or tuning.get("pitch_objective_fbo_requires_risp", 0.0) <= 0.5
        ):
            weights = _apply_weight_mods(
                weights,
                _weight_map(tuning.values.get("pitch_objective_first_base_open_mod")),
            )
        inning = int(context.get("inning", 1) or 1)
        score_diff = int(context.get("score_diff", 0) or 0)
        close_diff = int(tuning.get("close_game_run_diff", 2.0))
        late_inning = int(tuning.get("pitch_objective_late_inning", 7.0))
        if inning >= late_inning and abs(score_diff) <= close_diff:
            late_mods = _weight_map(tuning.values.get("pitch_objective_late_close_mod"))
            # Release 5: the strength scales each entry's distance from 1.0.
            # At exactly 1.0 the table is used untouched, because
            # 1 + (m - 1) * 1.0 is not bit-equal to m.
            late_strength = tuning.get("pitch_objective_late_close_strength", 1.0)
            if late_strength != 1.0:
                late_mods = {
                    key: 1.0 + (value - 1.0) * late_strength
                    for key, value in late_mods.items()
                }
            weights = _apply_weight_mods(weights, late_mods)
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
    if tuning.get("platoon_power_after_knee", 0.0) >= 0.5:
        # The pitcher sequences against the hitter's own Power, not against
        # his platoon edge.
        batter_power = batter.get("power_base", batter_power)
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


# Release 6a (fatigue_model 1): the most a tired pitcher's fastball can lose,
# as a share of his fresh speed -- the old model's own floor (x 0.85). The
# generation 6 coefficients take 2.25 mph at the fatigue cap, so it binds
# only on a mistuned knob.
FATIGUE_VELOCITY_FLOOR = 0.85
# The lowest pitch quality a tired pitcher's stuff loss can leave, the bottom
# of the scale a pitch grade is clamped to.
PITCH_QUALITY_FLOOR = 1.0


def pitching_group_on(tuning: TuningConfig) -> bool:
    """Release 6a: the stuff / velocity / exit-velocity / fatigue group is on.

    The group has no switch of its own; it is on when both of its model
    switches are (``ev_velocity_model`` and ``fatigue_model``), as in the
    generation 6 profile. Terms of the group that have no switch of their
    own (the chase term) act only then, so no earlier generation can turn
    one on by itself.
    """
    return (
        tuning.get("ev_velocity_model", 0.0) >= 1.0
        and tuning.get("fatigue_model", 0.0) >= 1.0
    )


def sample_pitch_velocity(
    base_velo: float, fatigue: float, tuning: TuningConfig, loss_mph: float = 0.0
) -> float:
    """Fastball speed: the pitcher's base speed, the commissioner's scale
    and the legacy fatigue factor. ``loss_mph`` is what a tired pitcher has
    lost under ``fatigue_model`` 1 (Release 6a), where the factor is 1.0; it
    never takes him below ``FATIGUE_VELOCITY_FLOOR`` of his fresh speed."""
    scale = tuning.get("velocity_scale", 1.0)
    velocity = base_velo * scale * fatigue
    if loss_mph > 0.0:
        velocity = max(velocity - loss_mph, velocity * FATIGUE_VELOCITY_FLOOR)
    return velocity


def _velocity_reference(pitch_type: str, tuning: TuningConfig) -> float:
    """The reference speed of ``pitch_type``: a 50-arm fastball
    (``contact_velo_ref``) plus the type's ``pitch_type_velocity_offset``."""
    reference = tuning.get("contact_velo_ref", 93.0)
    offsets = tuning.values.get("pitch_type_velocity_offset") or {}
    try:
        reference += float(offsets.get(pitch_type, 0.0))
    except (TypeError, ValueError):
        pass
    return reference


def _pitch_quality_center(tuning: TuningConfig) -> float:
    """The league's average pitch quality: the pitch-quality mix
    (``pq_weight_*``) of the three rating centres."""
    return (
        rating_center(tuning, "pitcher_control_center")
        * tuning.get("pq_weight_control", 0.4)
        + rating_center(tuning, "pitcher_movement_center")
        * tuning.get("pq_weight_movement", 0.4)
        + rating_center(tuning, "pitcher_grade_center")
        * tuning.get("pq_weight_grade", 0.2)
    )


def _command_error(
    *, control: float, movement: float, tuning: TuningConfig
) -> tuple[float, float]:
    base_x = tuning.get("command_error_base_x", 0.08)
    base_y = tuning.get("command_error_base_y", 0.1)
    movement_adj = max(0.0, (movement - 50.0) / 50.0)
    movement_penalty = tuning.get("movement_command_penalty", 0.4)
    if tuning.get("command_model", 0.0) >= 1.0:
        # Release 5: the miss shrinks by a fixed share per control point
        # (log-linear) instead of a fixed amount, read against the league's
        # mean control. ``control`` is the fatigued rating, so a tiring
        # pitcher's misses grow the same way.
        centred = control - rating_center(tuning, "pitcher_control_center")
        multiplier = tuning.get("command_error_ref_mult", 2.55) * math.exp(
            -centred * tuning.get("command_error_control_log_slope", 0.02)
        )
        multiplier += movement_adj * movement_penalty
    else:
        miss = max(0.0, (100.0 - control) / 100.0)
        scale = tuning.get("command_error_scale", 2.2)
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


def _signed_edge_distance(
    *,
    location: tuple[float, float],
    zone_bottom: float,
    zone_top: float,
    plate_half_width: float,
) -> float:
    """Feet from the zone edge: positive outside, negative inside.

    Outside it is ``_edge_distance`` (the larger of the horizontal and the
    vertical miss); inside it is minus the distance to the nearest edge.
    The bounds are the caller's, ball radius included.
    """
    x, y = location
    x_in = plate_half_width - abs(x)
    y_in = min(y - zone_bottom, zone_top - y)
    if x_in >= 0.0 and y_in >= 0.0:
        return -min(x_in, y_in)
    return max(-x_in, -y_in)


def _logit(prob: float) -> float:
    prob = min(max(prob, 1e-6), 1.0 - 1e-6)
    return math.log(prob / (1.0 - prob))


def _sigmoid(x: float) -> float:
    if x < -40.0:
        return 0.0
    if x > 40.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


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


def _swing_logit_table(
    tuning: TuningConfig,
) -> tuple[Dict[tuple[int, int], tuple[float, float]], float]:
    """``swing_model`` 1: per-count (zone, chase) swing logits and the eye
    centre, computed once per TuningConfig like ``_objective_weight_table``.

    The logits are ``swing_count_table`` with the commissioner sliders
    folded in as odds multipliers (all 1.0 = the table): the zone and chase
    scales on their own column, the two-strike scale on both columns with
    two strikes, and the walk scale dividing the chase odds, to the power
    ``swing_walk_logit_gain``. A count or column the table lacks reads the
    default table's.

    The eye centre is the league mean of what ``simulate_pitch`` calls
    ``eye``: ``hitter_eye_center``, pulled toward the pitchers' mean control
    by ``eye_control_blend`` exactly as ``engine._batter_context`` blends
    the rating itself, and scaled by ``eye_scale``. With ``centred_ratings``
    on both ratings reach ``simulate_pitch`` already league-relative and
    both centres read 50 (``centred_ratings.rating_center``).
    """
    cached = tuning.__dict__.get("_swing_table")
    if cached is not None:
        return cached

    def odds_logit(key: str) -> float:
        return math.log(max(1e-6, tuning.get(key, 1.0)))

    zone_shift = odds_logit("swing_zone_scale")
    chase_shift = odds_logit("swing_chase_scale") - odds_logit(
        "swing_walk_scale"
    ) * tuning.get("swing_walk_logit_gain", 1.33)
    two_strike_shift = odds_logit("swing_two_strike_scale")
    raw = tuning.values.get("swing_count_table")
    default = DEFAULT_TUNING["swing_count_table"]
    table: Dict[tuple[int, int], tuple[float, float]] = {}
    for balls in range(4):
        for strikes in range(3):
            key = f"{balls}-{strikes}"
            zone, chase = (
                _logit(
                    _count_modifier(
                        raw, count_key=key, default=default[key][field], field=field
                    )
                )
                for field in ("zone", "chase")
            )
            zone += zone_shift
            chase += chase_shift
            if strikes >= 2:
                zone += two_strike_shift
                chase += two_strike_shift
            table[(balls, strikes)] = (zone, chase)
    blend = tuning.get("eye_control_blend", 0.2)
    eye_center = rating_center(tuning, "hitter_eye_center") * (1.0 - blend)
    eye_center += (
        100.0 - rating_center(tuning, "pitcher_control_center")
    ) * blend
    eye_center *= tuning.get("eye_scale", 1.0)
    cached = (table, eye_center)
    tuning.__dict__["_swing_table"] = cached
    return cached


def _swing_probability(
    *,
    eye: float,
    contact: float,
    platoon_chase: float,
    in_zone: bool,
    balls: int,
    strikes: int,
    tuning: TuningConfig,
    pitch_quality: float | None = None,
) -> float:
    """``swing_model`` 1: the chance the batter swings at this pitch.

    Log-odds from the per-count table (``_swing_logit_table``). The count is
    in the table, so there is no take-on-3-0 scale and no count bonus. The
    eye moves the chase rate (and barely the zone rate) around the league's
    average hitter; ``platoon_chase`` is the old model's chase shift, in
    chance units, converted to log-odds. With two strikes a zone pitch also
    takes the contact-model hook (plan 2.2): the better contact hitter takes
    fewer called third strikes; it is off at 0.0.

    Release 6a: ``pitch_quality`` is the composite the contact roll reads.
    A pitch out of the zone is chased more the better it is
    (``swing_pq_chase_logit`` per point above the league's average pitch);
    off at 0.0, with no ``pitch_quality`` given, and unless the generation
    6 pitching group is on (:func:`pitching_group_on`).
    """
    swing_logits, eye_center = _swing_logit_table(tuning)
    zone_logit, chase_logit = swing_logits[(min(balls, 3), min(strikes, 2))]
    eye_edge = eye - eye_center
    if in_zone:
        swing_logit = zone_logit + eye_edge * tuning.get(
            "swing_eye_zone_logit", -0.005
        )
        if strikes >= 2:
            swing_logit += (
                contact - rating_center(tuning, "hitter_contact_center")
            ) * tuning.get("swing_two_strike_contact_logit", 0.0)
    else:
        swing_logit = chase_logit - eye_edge * tuning.get(
            "swing_eye_chase_logit", 0.035
        )
        swing_logit += platoon_chase * tuning.get("swing_platoon_chase_logit", 5.0)
        chase_slope = tuning.get("swing_pq_chase_logit", 0.0)
        if (
            chase_slope
            and pitch_quality is not None
            and pitching_group_on(tuning)
        ):
            swing_logit += (
                pitch_quality - _pitch_quality_center(tuning)
            ) * chase_slope
    return max(
        tuning.get("swing_prob_floor", 0.01),
        min(tuning.get("swing_prob_cap", 0.99), _sigmoid(swing_logit)),
    )


def _two_strike_zone_protect(
    protect: float, *, contact: float, eye: float, tuning: TuningConfig
) -> float:
    """``swing_model`` 0: the chance a two-strike take of a zone pitch turns
    into a "protect" swing, by hitter (plan 2.2).

    ``protect`` is ``two_strike_zone_protect``; the hitter moves it in
    log-odds, his contact (and, off by design, his eye) read against the
    league's average hitter, so the better contact hitter takes fewer called
    third strikes. Both slopes are 0.0 by default and ``protect`` comes back
    untouched. Under ``swing_model`` 1 there is no protect roll and the same
    term is ``swing_two_strike_contact_logit``.
    """
    shift = (
        contact - rating_center(tuning, "hitter_contact_center")
    ) * tuning.get("two_strike_protect_contact", 0.0)
    eye_slope = tuning.get("two_strike_protect_eye", 0.0)
    if eye_slope:
        shift += (eye - _swing_logit_table(tuning)[1]) * eye_slope
    if not shift:
        return protect
    return _sigmoid(_logit(protect) + shift)


def _contact_probability(
    *,
    contact: float,
    pitch_quality: float,
    break_mag: float,
    velocity: float,
    pitch_type: str,
    in_zone: bool,
    strikes: int,
    tuning: TuningConfig,
) -> float:
    """``contact_model`` 1: the chance a swing meets the ball (plan 2.2).

    One log-odds sum, so the hitter and the pitcher each move the odds by
    the same factor whoever the other is (log5): there is no ceiling, no
    separate whiff roll and no ``k_scale`` division. ``contact`` is the
    batter's contact in context (handedness, platoon and times through the
    order included) and ``pitch_quality`` the control / movement / pitch
    grade composite the old roll used (the ``pq_weight_*`` mix); both are
    read against the league's averages. Break is in feet. The velocity term
    compares the pitch with the reference speed of its own type, both ways
    (a slower pitch than the reference is easier to hit), and is off (0.0)
    before generation 6; ``contact_velo_ref`` is the fastball of a 50 arm,
    which is the league's average arm once ``centred_ratings`` shifts the
    arm rating.
    """
    logit = (
        tuning.get("contact_logit_zone", 1.74)
        if in_zone
        else tuning.get("contact_logit_chase", 0.48)
    )
    logit += (
        contact - rating_center(tuning, "hitter_contact_center")
    ) * tuning.get("contact_logit_ch", 0.09)
    quality_center = _pitch_quality_center(tuning)
    logit -= (pitch_quality - quality_center) * tuning.get("contact_logit_pq", 0.04)
    logit -= break_mag * tuning.get("contact_logit_break", 0.4)
    velocity_slope = tuning.get("contact_logit_velo", 0.0)
    if velocity_slope:
        reference = _velocity_reference(pitch_type, tuning)
        logit -= (velocity - reference) * velocity_slope
    if strikes >= 2:
        logit += tuning.get("contact_logit_two_strike", 0.22)
    # The commissioner's Strikeout Rate slider (1.0 = MLB, no term): it
    # divides the contact odds, to the power contact_strikeout_logit_gain.
    strikeout_scale = tuning.get("contact_strikeout_scale", 1.0)
    if strikeout_scale != 1.0:
        logit -= math.log(max(1e-6, strikeout_scale)) * tuning.get(
            "contact_strikeout_logit_gain", 1.8
        )
    return _sigmoid(logit)


def _umpire_even_distance(
    *, catcher_fielding: float, balls: int, strikes: int, tuning: TuningConfig
) -> float:
    """``umpire_model`` 1: feet outside the zone edge where a take is 50/50.

    The base offset is negative (the called zone is a little smaller than
    the rulebook's). A good receiver moves it out, read against the league's
    mean catcher fielding; so does a hitter's count, and a pitcher's count
    moves it in.
    """
    even = tuning.get("umpire_edge_offset_ft", -0.055)
    even += (
        (catcher_fielding - rating_center(tuning, "catcher_fa_center"))
        / 100.0
        * tuning.get("umpire_framing_offset_ft", 0.045)
    )
    even += (balls - strikes) * tuning.get("umpire_count_offset_ft", 0.012)
    return even


def _umpire_strike_probability(
    edge_signed: float, edge_even: float, tuning: TuningConfig
) -> float:
    """``umpire_model`` 1: the chance a take ``edge_signed`` feet outside the
    zone edge (negative inside) is called a strike."""
    width = max(0.005, tuning.get("umpire_edge_width_ft", 0.07))
    return _sigmoid((edge_even - edge_signed) / width)


def _hbp_inside_chance(
    *,
    x: float,
    batter_side: str,
    zone_half_width: float,
    tuning: TuningConfig,
    pitcher_hand: str | None = None,
) -> float:
    """``hbp_model`` 1: the chance this pitch hits the batter.

    +x is the right-handed batter's side of the plate: ``_pitch_break`` runs
    a right-hander's arm-side pitches (fb, si, cu) toward +x, and those run
    in on a right-handed batter. So "inside" is +x for a batter hitting
    right and -x for one hitting left. Zero until the pitch is
    ``hbp_inside_min_ft`` inside the zone edge on his side, then a ramp to
    ``hbp_inside_rate`` over ``hbp_inside_span_ft``.

    The chance is then scaled by matchup hand: ``hbp_same_hand_scale`` when
    the batter stands on the pitcher's arm side, ``hbp_opposite_hand_scale``
    when he does not. Pitch targets are the same on both sides of the plate
    and the break is added to the aim point, so on location alone the
    far-inside pitches are mostly glove-side ones and the opposite-hand
    batter is hit more often; in MLB it is the same-hand batter, about twice
    as often. The two scales carry that and leave where pitches go alone.
    With no ``pitcher_hand`` the chance is not scaled.
    """
    inside_ft = (x if batter_side == "R" else -x) - zone_half_width
    inside_ft -= tuning.get("hbp_inside_min_ft", 0.35)
    if inside_ft <= 0.0:
        return 0.0
    span = max(0.01, tuning.get("hbp_inside_span_ft", 0.6))
    chance = tuning.get("hbp_inside_rate", 0.2) * min(1.0, inside_ft / span)
    if pitcher_hand is not None:
        if batter_side == pitcher_hand:
            chance *= tuning.get("hbp_same_hand_scale", 1.0)
        else:
            chance *= tuning.get("hbp_opposite_hand_scale", 1.0)
    return max(0.0, min(1.0, chance))


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
    velocity = sample_pitch_velocity(
        pitcher.get("velocity", 90.0),
        fatigue,
        tuning,
        pitcher.get("velocity_loss", 0.0),
    )
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
    # Release 5 (command_model 1): control is read against the league mean
    # here too; the stronger slope is zone_target_control_scale's value.
    control_ref = 50.0
    if tuning.get("command_model", 0.0) >= 1.0:
        control_ref = rating_center(tuning, "pitcher_control_center")
    zone_target += (control - control_ref) * tuning.get(
        "zone_target_control_scale", 0.0025
    )
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
    # Release 5 (umpire_model 1): the edge is a probability, not a line. A
    # take is called a strike with a chance that falls from near 1 well
    # inside the zone to near 0 well outside, 50/50 at ``edge_even`` feet
    # outside the edge. ``called_in_zone`` then means "more likely a strike
    # than a ball".
    umpire_model = tuning.get("umpire_model", 0.0) >= 1.0
    edge_signed = edge_even = 0.0
    if umpire_model:
        # No catcher in the context reads as the league's average receiver:
        # no framing, whatever the league's centre is.
        catcher_center = rating_center(tuning, "catcher_fa_center")
        catcher_fielding = catcher_center
        if context:
            try:
                catcher_fielding = float(
                    context.get("catcher_fielding", catcher_center)
                )
            except (TypeError, ValueError):
                catcher_fielding = catcher_center
        edge_signed = _signed_edge_distance(
            location=loc,
            zone_bottom=zone_bottom - ball_radius,
            zone_top=zone_top + ball_radius,
            plate_half_width=plate_half + ball_radius,
        )
        edge_even = _umpire_even_distance(
            catcher_fielding=catcher_fielding,
            balls=balls,
            strikes=strikes,
            tuning=tuning,
        )
        called_in_zone = edge_signed <= edge_even
    loc_miss = miss_distance(
        location=loc, zone_bottom=zone_bottom, zone_top=zone_top, tuning=tuning
    )
    if tuning.get("hbp_model", 0.0) >= 1.0:
        # Release 5: only a pitch well inside can hit the batter, and no
        # roll is made for one that cannot reach him.
        hbp_rate = _hbp_inside_chance(
            x=loc[0],
            batter_side=batter_side,
            zone_half_width=plate_half + ball_radius,
            tuning=tuning,
            pitcher_hand=pitcher_hand,
        )
        hit_batter = hbp_rate > 0.0 and random.random() < hbp_rate
    else:
        hbp_rate = tuning.get("hbp_rate", 0.003)
        hbp_rate *= 1.0 + (50.0 - control) / 120.0
        hbp_rate *= 1.0 + loc_miss
        hit_batter = random.random() < hbp_rate
    if hit_batter:
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
    count_key = f"{balls}-{strikes}"
    # Release 6a: the control / movement / pitch grade composite, worked out
    # before the swing decision (the chase term reads it) with no random
    # number. ``pitch_quality`` stays the pitch's own grade until a swing,
    # as it was, so a take's result still reports the grade.
    composite_quality = (
        control * tuning.get("pq_weight_control", 0.4)
        + movement * tuning.get("pq_weight_movement", 0.4)
        + pitch_quality * tuning.get("pq_weight_grade", 0.2)
    )
    stuff_loss = pitcher.get("stuff_loss", 0.0)
    if stuff_loss > 0.0:
        # fatigue_model 1: a tired pitcher's stuff, in pitch-quality points,
        # never below the bottom of the scale.
        composite_quality = max(
            composite_quality - stuff_loss,
            min(composite_quality, PITCH_QUALITY_FLOOR),
        )
    composite_quality *= tuning.get("pitching_dom_scale", 1.0)
    if tuning.get("swing_model", 0.0) >= 1.0:
        # Release 5: one roll, and no second "protect" roll.
        base_swing = _swing_probability(
            eye=eye,
            contact=batter.get("contact", 50.0),
            platoon_chase=batter.get("platoon_chase", 0.0),
            in_zone=in_zone,
            balls=balls,
            strikes=strikes,
            tuning=tuning,
            pitch_quality=composite_quality,
        )
        swing = random.random() < base_swing
    else:
        # S2-08 de-compression: widen the eye slopes so plate-discipline
        # dispersion (qualified OBP/AVG SD, walk-rate spread) matches MLB
        # instead of collapsing.
        zone_base = 0.62 + (eye - 50.0) / 200.0
        chase_base = 0.28 - (eye - 50.0) / 230.0
        chase_base += batter.get("platoon_chase", 0.0)
        base_swing = zone_base if in_zone else chase_base
        base_swing *= zone_scale if in_zone else chase_scale
        if strikes >= 2:
            aggression = tuning.get("two_strike_aggression_scale", 1.0)
            base_swing += 0.10 * aggression if in_zone else 0.08 * aggression
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
            if in_zone and protect > 0:
                # Release 5: the called third strike depends on Contact.
                protect = _two_strike_zone_protect(
                    protect,
                    contact=batter.get("contact", 50.0),
                    eye=eye,
                    tuning=tuning,
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
        pitch_quality = composite_quality
        # The legacy contact roll (contact_model 0) reads contact_base, with
        # its own 0.4 of pitch quality. Exit velocity reads a copy whose
        # pitch-quality share is a knob (Release 6a, the single
        # pitch-quality path); at 0.4 the copy is contact_base.
        contact_base = batter.get("contact", 50.0) - (pitch_quality - 50.0) * 0.4
        contact_base -= break_mag * tuning.get("break_contact_penalty", 5.0)
        ev_contact_base = batter.get("contact", 50.0) - (
            pitch_quality - 50.0
        ) * tuning.get("ev_pq_contact_base_weight", 0.4)
        ev_contact_base -= break_mag * tuning.get("break_contact_penalty", 5.0)
        if tuning.get("contact_model", 0.0) >= 1.0:
            # Release 5: one log-odds roll, no ceiling and no whiff roll.
            contact = random.random() < _contact_probability(
                contact=batter.get("contact", 50.0),
                pitch_quality=pitch_quality,
                break_mag=break_mag,
                velocity=velocity,
                pitch_type=pitch_type,
                in_zone=in_zone,
                strikes=strikes,
                tuning=tuning,
            )
        else:
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
            whiff_prob += min(1.0, loc_miss) * tuning.get(
                "whiff_location_scale", 0.12
            )
            if not in_zone:
                whiff_prob *= tuning.get("whiff_chase_scale", 1.05)
            whiff_prob = max(0.0, min(0.6, whiff_prob))
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
            # Release 6a: pitch quality's and velocity's shares are knobs
            # (1.0 = as they were); break's is the batted-ball model's.
            difficulty += max(0.0, (pitch_quality - 50.0) / 100.0) * tuning.get(
                "difficulty_pq_scale", 1.0
            )
            difficulty += max(0.0, (velocity - 90.0) / 20.0) * tuning.get(
                "difficulty_velocity_scale", 1.0
            )
            difficulty += min(1.0, break_mag / 0.4) * 0.5
            # Timing (when the bat arrives) is a contact skill. Barrelling the
            # ball -- the sweet spot, which is what makes it go far -- is much
            # more what separates power hitters, so barrel accuracy can draw on
            # Power via barrel_power_weight. At 0.0 both use contact alone, the
            # original single skill_factor.
            skill_scale = tuning.get("skill_contact_scale", 0.6)
            timing_skill = 0.8 + (1.0 - batter_contact / 100.0) * skill_scale
            barrel_power_weight = tuning.get("barrel_power_weight", 0.0)
            barrel_rating = (
                batter_contact * (1.0 - barrel_power_weight)
                + batter.get("power", 50.0) * barrel_power_weight
            )
            barrel_skill = 0.8 + (1.0 - barrel_rating / 100.0) * skill_scale
            timing_sd = tuning.get("timing_error_base", 0.22)
            timing_sd *= 1.0 + difficulty * tuning.get("timing_error_scale", 0.6)
            timing_sd *= timing_skill
            barrel_sd = tuning.get("barrel_error_base", 0.24)
            barrel_sd *= 1.0 + difficulty * tuning.get("barrel_error_scale", 0.6)
            barrel_sd *= barrel_skill
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
            bat_speed += _batter_power_bat_speed(batter, tuning)
            bat_speed += (batter.get("contact", 50.0) - 50.0) * tuning.get(
                "bat_speed_contact_scale", 0.2
            )
            bat_speed = max(35.0, bat_speed)
            ev_pitch = velocity * tuning.get("ev_pitch_weight", 0.48)
            if tuning.get("ev_velocity_model", 0.0) >= 1.0:
                # Release 6a: the type's reference speed carries the pitch
                # weight; this pitch's distance from it has its own, small
                # one, so velocity mostly decides whether the ball is hit.
                reference = _velocity_reference(pitch_type, tuning)
                ev_pitch = (
                    reference * tuning.get("ev_pitch_weight", 0.48)
                    + (velocity - reference) * tuning.get("ev_velo_dev_weight", 0.1)
                    + tuning.get("ev_base_offset_mph", 20.0)
                )
            ev_base = ev_pitch + bat_speed * tuning.get("ev_bat_weight", 0.7)
            ev_base += random.gauss(0.0, tuning.get("exit_velo_sd", 5.0))
            # Contact's share of how HARD the ball is hit. contact_base mixes the
            # hitter's contact with the pitch's quality; this weight scales only
            # the hitter's part, so the pitcher's effect is untouched. At 1.0 it
            # is the original formula. Contact still decides whether and how
            # squarely the ball is met (contact_prob, timing and barrel error);
            # this is the term that also let it decide how far the ball goes.
            contact_ev_weight = tuning.get("ev_contact_quality_weight", 1.0)
            quality = 0.85 + (
                ev_contact_base
                - 50.0
                + (batter_contact - 50.0) * (contact_ev_weight - 1.0)
            ) / 250.0
            # The pitcher's one path into exit velocity from generation 6.
            # 0.004 is the old hard-coded 1 / 250 and keeps its division.
            ev_pq_slope = tuning.get("ev_pq_slope", 0.004)
            if ev_pq_slope == 0.004:
                quality *= max(0.75, 1.0 - (pitch_quality - 50.0) / 250.0)
            else:
                quality *= max(0.75, 1.0 - (pitch_quality - 50.0) * ev_pq_slope)
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

    if umpire_model:
        if not swing and random.random() < _umpire_strike_probability(
            edge_signed, edge_even, tuning
        ):
            outcome = "strike"
    else:
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
    # Release 4 (T3): the triple slope has a slow and a fast side. A fast
    # scale below 0 inherits the slow one (the old symmetric line).
    triple_speed_scale = tuning.get("triple_speed_scale", 0.0)
    if speed_norm > 0.0:
        fast_scale = tuning.get("triple_speed_scale_fast", -1.0)
        if fast_scale >= 0.0:
            triple_speed_scale = fast_scale
    triple_speed = 1.0 - speed_norm * triple_speed_scale
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
