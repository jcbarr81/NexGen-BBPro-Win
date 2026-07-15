from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import json


DEFAULT_TUNING: Dict[str, Any] = {
    # Global run environment
    "offense_scale": 1.015,
    "pitching_dom_scale": 1.0,
    # Plate discipline / swing behaviour
    "zone_swing_scale": 0.91,
    "chase_scale": 0.69,
    "two_strike_aggression_scale": 1.05,
    "two_strike_zone_protect": 0.63,
    "two_strike_chase_protect": 0.19,
    "eye_scale": 1.0,
    "zone_half_width": 0.45,
    "zone_half_height": 0.40,
    "plate_half_width": 0.708,
    "ball_radius_ft": 0.12,
    "called_zone_shrink_ft": 0.025,
    "zone_bottom_base": 1.5,
    "zone_top_base": 3.5,
    "zone_bottom_height_scale": 0.01,
    "zone_top_height_scale": 0.015,
    "zone_bottom_min": 1.2,
    "zone_top_max": 4.3,
    "zone_min_height": 1.8,
    "default_height_in": 72.0,
    "intent_zone_inner": 0.75,
    "command_error_base_x": 0.09,
    "command_error_base_y": 0.12,
    "command_error_scale": 3.1,
    "movement_command_penalty": 0.4,
    "break_scale": 1.0,
    "break_movement_scale": 0.6,
    "break_quality_scale": 0.4,
    "pitch_break_base": {
        "fb": {"x": 0.04, "z": 0.06},
        "si": {"x": 0.12, "z": -0.06},
        "sl": {"x": 0.25, "z": -0.12},
        "cb": {"x": 0.18, "z": -0.28},
        "cu": {"x": 0.14, "z": -0.22},
        "scb": {"x": 0.18, "z": -0.2},
        "kn": {"x": 0.08, "z": 0.04},
    },
    # Velocity delta (mph) vs the pitcher's fastball, per pitch type —
    # MLB-typical gaps (QW-12/13, deep_review_plan.md). Previously every
    # pitch type left the hand at the same speed.
    "pitch_type_velocity_offset": {
        "fb": 0.0,
        "si": -1.0,
        "sl": -6.0,
        "cu": -8.0,
        "cb": -11.0,
        "scb": -10.0,
        "kn": -18.0,
    },
    "pitch_break_sd": 0.04,
    "break_contact_penalty": 5.0,
    "timing_error_base": 0.22,
    "timing_error_scale": 0.6,
    "barrel_error_base": 0.24,
    "barrel_error_scale": 0.6,
    "timing_quality_weight": 0.6,
    "barrel_quality_weight": 0.4,
    "timing_ev_penalty": 0.19,
    "barrel_ev_penalty": 0.215,
    "timing_launch_scale": 7.0,
    "location_launch_scale": 8.0,
    "launch_angle_sd": 10.5,
    "launch_angle_base": 12.1,
    "barrel_launch_sd_scale": 3.5,
    "timing_spray_scale": 12.0,
    "zone_target_base": 0.36,
    "zone_target_control_scale": 0.0009,
    "zone_target_count_scale": -0.02,
    "take_on_3_0_scale": 0.5,
    "take_on_3_1_scale": 0.8,
    "whiff_base": 0.0095,
    "whiff_quality_scale": 0.072,
    "whiff_velocity_scale": 0.062,
    "whiff_break_scale": 0.068,
    "whiff_location_scale": 0.042,
    "whiff_chase_scale": 1.04,
    "foul_quality_scale": 0.35,
    "foul_pitch_quality_scale": 0.2,
    "foul_location_scale": 0.25,
    "foul_chase_scale": 1.02,
    "hbp_rate": 0.003,
    "umpire_margin_ft": 0.025,
    "framing_margin_scale": 0.01,
    "framing_strike_chance": 0.18,
    "framing_prob_scale": 0.1,
    "called_strike_intent_mod": {
        "attack": 1.0,
        "edge": 1.0,
        "chase": 0.85,
        "waste": 0.6,
        "putaway": 0.9,
    },
    "count_swing_bonus": {
        "0-2": {"zone": 0.1, "chase": 0.02},
        "1-2": {"zone": 0.08, "chase": 0.01},
        "2-2": {"zone": 0.04, "chase": 0.01},
        "3-2": {"zone": 0.1, "chase": 0.04},
    },
    "count_foul_scale": {
        "0-2": 1.2,
        "1-2": 1.15,
        "2-2": 1.05,
        "3-2": 1.05,
    },
    "count_contact_scale": {
        "0-2": 1.10,
        "1-2": 1.10,
        "2-2": 1.08,
        "3-2": 1.08,
    },
    # Pitch objectives / intent
    "pitch_objective_default": {
        "attack": 1.0,
        "edge": 0.7,
        "chase": 0.4,
        "waste": 0.2,
        "putaway": 0.35,
    },
    "pitch_objective_count_weights": {
        "0-2": {
            "attack": 0.45,
            "edge": 0.9,
            "chase": 1.1,
            "waste": 1.4,
            "putaway": 1.2,
        },
        "1-2": {
            "attack": 0.55,
            "edge": 0.85,
            "chase": 1.0,
            "waste": 1.2,
            "putaway": 1.15,
        },
        "3-0": {
            "attack": 1.8,
            "edge": 0.4,
            "chase": 0.15,
            "waste": 0.05,
            "putaway": 0.0,
        },
        "3-1": {
            "attack": 1.4,
            "edge": 0.6,
            "chase": 0.2,
            "waste": 0.1,
        },
    },
    "pitch_objective_two_strike_mod": {
        "attack": 0.95,
        "edge": 1.0,
        "chase": 1.05,
        "waste": 1.1,
        "putaway": 1.15,
    },
    "pitch_objective_three_ball_mod": {
        "attack": 1.15,
        "edge": 0.8,
        "chase": 0.6,
        "waste": 0.4,
        "putaway": 0.7,
    },
    "pitch_objective_risp_mod": {
        "attack": 0.95,
        "edge": 1.1,
        "chase": 1.05,
        "waste": 1.0,
        "putaway": 1.05,
    },
    "pitch_objective_first_base_open_mod": {
        "attack": 0.98,
        "edge": 1.05,
        "chase": 1.1,
        "waste": 1.1,
        "putaway": 1.0,
    },
    "pitch_objective_late_close_mod": {
        "attack": 0.95,
        "edge": 1.1,
        "chase": 1.05,
        "waste": 1.0,
        "putaway": 1.1,
    },
    "pitch_objective_late_inning": 7.0,
    "batter_aggression_min_pitches": 6.0,
    "batter_aggression_high": 0.52,
    "batter_aggression_low": 0.42,
    "batter_chase_high": 0.38,
    "pitch_objective_aggressive_mod": {
        "attack": 0.95,
        "edge": 1.05,
        "chase": 1.15,
        "waste": 1.1,
        "putaway": 1.1,
    },
    "pitch_objective_passive_mod": {
        "attack": 1.15,
        "edge": 0.95,
        "chase": 0.8,
        "waste": 0.75,
        "putaway": 0.9,
    },
    "pitch_objective_chase_mod": {
        "attack": 0.9,
        "edge": 1.0,
        "chase": 1.2,
        "waste": 1.1,
        "putaway": 1.05,
    },
    "pitch_seq_repeat_scale": 0.85,
    "pitch_seq_repeat_floor": 0.4,
    "pitch_objective_zone_adjust": {
        "attack": 0.08,
        "edge": 0.02,
        "chase": -0.08,
        "waste": -0.16,
        "putaway": -0.02,
    },
    "pitch_objective_intent_map": {
        "attack": "zone",
        "edge": "edge",
        "chase": "chase",
        "waste": "waste",
        "putaway": "edge",
    },
    "pitch_objective_group_bias": {
        "attack": {"fastball": 1.05, "breaking": 0.95, "offspeed": 0.95},
        "edge": {"fastball": 1.0, "breaking": 1.05, "offspeed": 1.0},
        "chase": {"fastball": 0.9, "breaking": 1.15, "offspeed": 1.05},
        "waste": {"fastball": 0.95, "breaking": 1.05, "offspeed": 1.0},
        "putaway": {"fastball": 0.85, "breaking": 1.2, "offspeed": 1.1},
    },
    "intent_edge_inner": 0.85,
    "intent_edge_outer": 1.05,
    "intent_chase_inner": 1.05,
    "intent_chase_outer": 1.5,
    "intent_waste_inner": 1.3,
    "intent_waste_outer": 2.2,
    "error_rate_gb": 0.018,
    "error_rate_ld": 0.012,
    "error_rate_fb": 0.008,
    "throwing_error_share_gb": 0.6,
    "throwing_error_share_ld": 0.35,
    "throwing_error_share_fb": 0.2,
    "throw_error_base": 0.015,
    "throw_error_scale": 1.0,
    "throw_error_arm_scale": 1.0,
    "throw_error_extra_base_chance": 0.35,
    "shift_pull_threshold": 60.0,
    "shift_spray_scale": 25.0,
    "shift_gb_boost": 0.04,
    "shift_ld_boost": 0.015,
    "spray_center_band_deg": 8.0,
    "tag_up_third_extra": 0.25,
    "tag_up_second_extra": 0.05,
    "ground_rbi_prob": 0.25,
    "fielder_choice_force_prob": 0.55,
    "steal_attempt_rate_first": 0.045,
    "steal_attempt_rate_second": 0.015,
    "steal_attempt_rate_home": 0.002,
    "double_steal_rate": 0.003,
    "steal_success_base": 0.80,
    "steal_home_success_scale": 0.6,
    "steal_count_favorable": 1.25,
    "steal_count_unfavorable": 0.75,
    "steal_two_strike_scale": 0.85,
    "steal_three_ball_scale": 1.1,
    "steal_two_out_scale": 1.05,
    "steal_early_inning_scale": 0.9,
    "steal_close_late_scale": 1.2,
    "steal_ahead_big_scale": 0.7,
    "steal_behind_big_scale": 0.85,
    "steal_pitcher_arm_deterrent": 1.0,
    "steal_pitcher_arm_success": 1.0,
    "steal_catcher_fielding_deterrent": 1.0,
    "steal_catcher_fielding_success": 1.0,
    "lead_speed_threshold": 70.0,
    "lead_speed_aggressive": 85.0,
    "lead_hold_threshold": 70.0,
    "lead_ball_bonus": 1.0,
    "lead_two_strike_penalty": 1.0,
    "lead_two_out_penalty": 1.0,
    "wild_pitch_rate": 0.0035,
    "passed_ball_rate": 0.0025,
    "missed_pitch_loc_scale": 0.6,
    "k_in_dirt_rate": 0.02,
    "extra_innings_runner": 0.0,
    "extra_innings_runner_start": 10.0,
    "max_innings": 18.0,
    # Outcomes
    "hr_scale": 0.925,
    "double_distance_scale": 0.70,
    "triple_distance_scale": 0.96,
    "double_speed_scale": 0.18,
    "triple_speed_scale": 0.28,
    "double_gap_scale": 0.45,
    "stretch_double_base": 0.02,
    "stretch_double_speed_scale": 0.18,
    "stretch_double_arm_scale": 0.7,
    "stretch_triple_base": 0.006,
    "stretch_triple_speed_scale": 0.12,
    "stretch_triple_arm_scale": 0.9,
    "babip_scale": 0.917,
    "walk_scale": 0.83,
    "k_scale": 0.51,
    "contact_prob_scale": 0.885,
    "chase_contact_scale": 0.73,
    "contact_quality_scale": 1.075,
    "foul_rate": 0.41,
    "two_strike_foul_scale": 1.02,
    "bat_speed_base": 69.3,
    "bat_speed_power_scale": 0.09,
    "bat_speed_contact_scale": 0.15,
    "ev_pitch_weight": 0.48,
    "ev_bat_weight": 0.7,
    "exit_velo_sd": 5.0,
    # S2-08 de-compression: raise the EV soft cap so the power tail (40-HR
    # seasons, HR/FB dispersion) survives instead of being flattened.
    "exit_velo_softcap": 107.0,
    "exit_velo_softcap_scale": 0.44,
    # Pitch/command
    "velocity_scale": 1.0,
    "movement_scale": 1.0,
    "command_variance_scale": 1.0,
    "fatigue_decay_scale": 1.4,
    "fatigue_start_base": 60.0,
    "fatigue_start_endurance_scale": 0.4,
    "fatigue_limit_base": 14.0,
    "fatigue_limit_endurance_scale": 0.05,
    "fatigue_debt_scale": 0.35,
    "fatigue_debt_penalty_scale": 0.3,
    "fatigue_debt_start_reduction": 0.2,
    "fatigue_debt_limit_reduction": 0.25,
    "daily_recovery_base": 40.0,
    "daily_recovery_durability_scale": 0.8,
    "starter_rest_days": 4.0,
    # S2-03: reliever rest is pitch-count-conditional (canonical table in
    # physics_sim/usage.reliever_rest_days) rather than a flat role-based wait.
    "reliever_rest_b2b_max_pitches": 12.0,
    "reliever_rest_one_day_max_pitches": 25.0,
    "reliever_rest_two_day_max_pitches": 40.0,
    "closer_availability_ratio": 1.3,
    "short_rest_penalty": 0.35,
    "reliever_fatigue_start_scale": 0.25,
    "reliever_fatigue_limit_scale": 0.2,
    "long_reliever_fatigue_start_scale": 0.5,
    "long_reliever_fatigue_limit_scale": 0.45,
    "closer_max_outs": 3.0,
    # S2-03: applies to ALL bullpen roles now (3rd consecutive day blocked).
    "reliever_max_consecutive_days": 2.0,
    "closer_max_appearances_ratio": 0.45,
    "setup_max_outs": 3.0,
    "middle_reliever_max_outs": 4.0,
    "long_reliever_max_outs": 6.0,
    "batter_daily_recovery_base": 6.0,
    "batter_daily_recovery_durability_scale": 0.05,
    "batter_fatigue_game_cost": 6.0,
    "batter_fatigue_durability_scale": 0.02,
    "batter_fatigue_threshold_base": 35.0,
    "batter_fatigue_threshold_scale": 0.45,
    "batter_fatigue_penalty_scale": 0.5,
    "batter_fatigue_penalty_cap": 0.35,
    "batter_fatigue_offense_scale": 0.8,
    "batter_fatigue_eye_scale": 0.7,
    "batter_fatigue_speed_scale": 0.5,
    "batter_fatigue_defense_scale": 0.4,
    "consecutive_usage_penalty": 3.0,
    # Park/environment
    "park_size_scale": 1.0,
    "park_factor_scale": 0.0,
    "foul_territory_scale": 1.0,
    "wind_speed": 0.0,
    "wind_angle_deg": 0.0,
    "altitude_scale": 1.0,
    "altitude_ft_scale": 0.00002,
    # Fielding / baserunning
    "range_scale": 1.0,
    "arm_strength_scale": 1.0,
    "error_rate_scale": 1.0,
    "speed_scale": 1.0,
    "steal_freq_scale": 3.0,
    "advancement_aggression_scale": 1.6,
    "extra_base_out_base": 0.06,
    "extra_base_out_scale": 1.0,
    "double_play_base": 0.32,
    "double_play_range_scale": 1.2,
    "double_play_arm_scale": 1.2,
    "double_play_speed_scale": 1.0,
    "pickoff_attempt_rate_first": 0.004,
    "pickoff_attempt_rate_second": 0.0015,
    "pickoff_attempt_rate_third": 0.0003,
    "pickoff_success_base": 0.045,
    "pickoff_freq_scale": 1.0,
    "pickoff_success_scale": 1.0,
    "pickoff_arm_scale": 1.0,
    "defense_primary_pos_scale": 1.0,
    "defense_secondary_pos_scale": 0.9,
    "defense_out_of_pos_scale": 0.75,
    "defensive_sub_inning": 7.0,
    "defensive_sub_close_run_diff": 2.0,
    "defensive_sub_fielding_diff": 8.0,
    "pinch_hit_inning": 7.0,
    "pinch_hit_close_run_diff": 2.0,
    "pinch_hit_advantage_min": 6.0,
    "pinch_run_inning": 7.0,
    "pinch_run_close_run_diff": 2.0,
    "pinch_run_speed_min": 55.0,
    "pinch_run_speed_diff": 8.0,
    "bunt_attempt_rate": 0.03,
    "bunt_inning_max": 8.0,
    "bunt_close_run_diff": 2.0,
    "bunt_squeeze_rate": 0.15,
    "bunt_success_base": 0.68,
    "bunt_hit_base": 0.03,
    "bunt_double_play_base": 0.08,
    "triple_play_base": 0.0008,
    "ibb_inning": 7.0,
    "ibb_close_run_diff": 2.0,
    "ibb_batter_threshold": 65.0,
    "ibb_chance": 0.35,
    "balk_rate": 0.0004,
    "catcher_interference_rate": 0.0005,
    "injuries_enabled": 1.0,
    "injury_rate_scale": 0.1,
    "injury_overuse_pitch_min": 80.0,
    "injury_overuse_penalty_threshold": 0.6,
    # S2-01: sized so the league platoon-split KPI lands in its 20-32 wOBA-point
    # band (2.0 produced ~46 pts). Tune these three together.
    "handedness_contact_bonus": 1.2,
    "handedness_power_bonus": 1.2,
    "handedness_eye_bonus": 1.2,
    "handedness_switch_bonus": 0.5,
    # S2-07: batter familiarity bonus per times-through-order pass beyond the
    # first (rating points; MLB TTO penalty ~20-30 OPS pts per pass).
    "tto_contact_bonus": 0.32,
    "tto_eye_bonus": 0.32,
    "tto_power_bonus": 0.2,
    "tto_max_passes": 3.0,
    "platoon_contact_scale": 0.25,
    "platoon_power_scale": 0.2,
    "platoon_eye_scale": 0.3,
    "platoon_chase_scale": 0.0015,
    "platoon_pitcher_scale": 0.25,
    "bullpen_platoon_weight": 2.0,
    "pitch_seq_fastball_bias": 1.0,
    "pitch_seq_breaking_bias": 1.0,
    "pitch_seq_offspeed_bias": 1.0,
    "pitch_seq_first_pitch_fastball": 1.1,
    "pitch_seq_behind_fastball": 1.15,
    "pitch_seq_ahead_fastball": 0.9,
    "pitch_seq_ahead_breaking": 1.1,
    "pitch_seq_two_strike_breaking": 1.25,
    "pitch_seq_behind_offspeed": 0.95,
    "pitch_seq_power_avoid_fastball": 0.92,
    "pitch_seq_eye_avoid_breaking": 0.95,
    # Batted-ball shape
    "gb_fb_tilt": 0.97,
    "bip_gb_cutoff": 9.0,
    "bip_ld_cutoff": 15.7,
    # Pitching hooks/usage
    "hook_threshold": 1.9,
    "hook_aggression_scale": 1.3,
    "postseason_hook_scale": 1.2,
    "close_game_hook_scale": 1.1,
    "close_game_run_diff": 2.0,
    "save_opportunity_run_diff": 3.0,
    "save_opportunity_inning": 1.0,
    "save_long_innings": 3.0,
    "closer_inning_min": 9.0,
    # S2-04: tied road games hold the closer through the 9th (a later lead can
    # still hand him a save); from the 10th both sides may use the CL when tied.
    "closer_tied_road_inning_min": 10.0,
    "hook_runs_allowed": 5.0,
    "hook_hits_allowed": 7.0,
    "hook_walks_allowed": 3.5,
    "hook_consecutive_hits": 3.0,
    "hook_runs_in_inning": 2.8,
    "hook_walks_in_inning": 2.6,
    "hook_baserunners_in_inning": 4.0,
    "hook_fatigue_penalty": 0.8,
    "hook_fatigue_soft_penalty": 0.55,
    "hook_tto_penalty": 0.7,
    "achievement_inning_threshold": 7.0,
    "nohit_pitch_limit": 160.0,
    "perfect_pitch_limit": 170.0,
    "shutout_pitch_bonus": 10.0,
    "one_hit_pitch_bonus": 8.0,
    "leash_shutout_bonus": 0.4,
    "leash_one_hit_bonus": 0.3,
    "leash_nohit_bonus": 0.6,
    "leash_perfect_bonus": 0.8,
}


@dataclass
class TuningConfig:
    """Container for all user-adjustable tuning knobs."""

    values: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_TUNING))

    @classmethod
    def from_overrides(
        cls,
        *,
        overrides: Optional[Dict[str, Any]] = None,
        overrides_path: Optional[Path] = None,
    ) -> "TuningConfig":
        base = dict(DEFAULT_TUNING)
        data: Dict[str, Any] = {}
        if overrides_path:
            try:
                with Path(overrides_path).open("r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                    if isinstance(loaded, dict):
                        data.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass
        if overrides:
            data.update(overrides)
        for k, v in data.items():
            if k in base:
                base_value = base.get(k)
                if isinstance(base_value, (int, float)):
                    try:
                        base[k] = float(v)
                    except (TypeError, ValueError):
                        continue
                else:
                    base[k] = v
        return cls(values=base)

    def get(self, key: str, default: Optional[float] = None) -> float:
        """Numeric knob lookup, memoized per (key, default) (S1-09).

        The pitch kernel calls this ~60-80× per pitch (~50M float()
        conversions per season). Values never change after construction in
        production (overrides build a NEW TuningConfig), so cache the
        converted floats. Anything that mutates ``values`` in place (tests)
        should call :meth:`invalidate_cache` afterwards.
        """
        cache = self.__dict__.get("_num_cache")
        if cache is None:
            cache = {}
            self.__dict__["_num_cache"] = cache
        cache_key = (key, default)
        try:
            return cache[cache_key]
        except KeyError:
            value = float(self.values.get(key, default if default is not None else 0.0))
            cache[cache_key] = value
            return value

    def invalidate_cache(self) -> None:
        """Drop memoized lookups after an in-place ``values`` mutation."""
        self.__dict__.pop("_num_cache", None)
        self.__dict__.pop("_objective_table", None)


def load_tuning(
    overrides: Optional[Dict[str, Any]] = None, overrides_path: Optional[Path] = None
) -> TuningConfig:
    """Load a :class:`TuningConfig` merging optional overrides."""

    return TuningConfig.from_overrides(overrides=overrides, overrides_path=overrides_path)
