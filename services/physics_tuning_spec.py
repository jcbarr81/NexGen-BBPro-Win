"""Physics tuning slider catalog — single source of truth.

Extracted from ``ui/playbalance_editor.py`` so the FastAPI sidecar can
reuse the exact same slider definitions without pulling in PyQt6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class TuningSliderSpec:
    key: str
    label: str
    description: str
    min_value: float
    max_value: float
    step: float
    fmt: str


_TUNING_SECTIONS: List[Tuple[str, List[TuningSliderSpec]]] = [
    (
        "Run Environment",
        [
            TuningSliderSpec(
                key="offense_scale",
                label="Offense Scale",
                description="Global run environment multiplier.",
                min_value=0.85,
                max_value=1.15,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="pitching_dom_scale",
                label="Pitching Dominance",
                description="Pitching dominance scaling. Higher suppresses offense.",
                min_value=0.85,
                max_value=1.15,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="hr_scale",
                label="Home Run Rate",
                description="Home run outcome scaling.",
                min_value=0.75,
                max_value=1.25,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="babip_scale",
                label="BABIP Rate",
                description="In-play hit rate scaling.",
                min_value=0.75,
                max_value=1.25,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="walk_scale",
                label="Walk Rate",
                description="Walk frequency scaling.",
                min_value=0.6,
                max_value=1.2,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="k_scale",
                label="Strikeout Rate",
                description="Strikeout frequency scaling.",
                min_value=0.4,
                max_value=1.2,
                step=0.01,
                fmt="{:.2f}",
            ),
        ],
    ),
    (
        "Plate Discipline",
        [
            TuningSliderSpec(
                key="zone_swing_scale",
                label="Zone Swing",
                description="Swings at strikes.",
                min_value=0.6,
                max_value=1.2,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="chase_scale",
                label="Chase",
                description="Swings at balls out of the zone.",
                min_value=0.4,
                max_value=1.0,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="two_strike_aggression_scale",
                label="Two-Strike Aggression",
                description="Swing aggression with two strikes.",
                min_value=0.8,
                max_value=1.4,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="two_strike_zone_protect",
                label="Two-Strike Protect",
                description="Protect the zone with two strikes.",
                min_value=0.4,
                max_value=0.9,
                step=0.01,
                fmt="{:.2f}",
            ),
        ],
    ),
    (
        "Contact & Batted Ball",
        [
            TuningSliderSpec(
                key="contact_prob_scale",
                label="Contact Rate",
                description="Overall contact probability scaling.",
                min_value=0.85,
                max_value=1.15,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="contact_quality_scale",
                label="Contact Quality",
                description="Quality of contact scaling.",
                min_value=0.85,
                max_value=1.15,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="foul_rate",
                label="Foul Rate",
                description="Frequency of foul balls on contact.",
                min_value=0.25,
                max_value=0.55,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="launch_angle_base",
                label="Launch Angle Base",
                description="Baseline launch angle in degrees.",
                min_value=6.0,
                max_value=18.0,
                step=0.1,
                fmt="{:.1f}",
            ),
        ],
    ),
    (
        "Pitching & Fatigue",
        [
            TuningSliderSpec(
                key="velocity_scale",
                label="Velocity Scale",
                description="Pitch velocity scaling.",
                min_value=0.9,
                max_value=1.1,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="movement_scale",
                label="Movement Scale",
                description="Pitch movement scaling.",
                min_value=0.9,
                max_value=1.1,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="command_variance_scale",
                label="Command Variance",
                description="Pitch command variance. Higher is wilder.",
                min_value=0.7,
                max_value=1.3,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="fatigue_decay_scale",
                label="Fatigue Decay",
                description="How quickly fatigue penalties grow.",
                min_value=0.8,
                max_value=2.0,
                step=0.05,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="fatigue_start_base",
                label="Fatigue Start",
                description="Pitch count before fatigue begins.",
                min_value=45.0,
                max_value=75.0,
                step=1.0,
                fmt="{:.0f}",
            ),
            TuningSliderSpec(
                key="fatigue_limit_base",
                label="Fatigue Limit",
                description="Extra pitches after fatigue starts.",
                min_value=8.0,
                max_value=25.0,
                step=1.0,
                fmt="{:.0f}",
            ),
        ],
    ),
    (
        "Defense & Running",
        [
            TuningSliderSpec(
                key="range_scale",
                label="Range Scale",
                description="Fielding range impact.",
                min_value=0.85,
                max_value=1.15,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="arm_strength_scale",
                label="Arm Strength",
                description="Throwing arm impact.",
                min_value=0.85,
                max_value=1.15,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="error_rate_scale",
                label="Error Rate",
                description="Fielding error frequency scaling.",
                min_value=0.7,
                max_value=1.3,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="speed_scale",
                label="Speed Scale",
                description="Runner speed impact.",
                min_value=0.85,
                max_value=1.15,
                step=0.01,
                fmt="{:.2f}",
            ),
            TuningSliderSpec(
                key="steal_freq_scale",
                label="Steal Frequency",
                description=(
                    "Steal attempt frequency. 1.0 = MLB volume (about 0.73 "
                    "steals per team per game); 0.5 halves it, 2.0 doubles "
                    "it. Fast runners always try far more often than slow "
                    "ones. (Earlier versions ran 1-5 with 3.0 as normal; "
                    "a saved setting was converted.)"
                ),
                min_value=0.25,
                max_value=3.0,
                step=0.05,
                fmt="{:.2f}",
            ),
        ],
    ),
]


# Release 5 (owner decision 9): the plate-discipline sliders of the new swing
# model. A league running ``swing_model`` 1 does not read walk_scale,
# zone_swing_scale, chase_scale or the two-strike knobs, so its Walk Rate,
# Zone Swing and Chase sliders move the keys below instead: odds multipliers
# on the engine's per-count swing table, 1.0 = MLB. Two-Strike Aggression and
# Two-Strike Protect become ONE slider. ``tuning_sections`` swaps them in,
# slot for slot; while a league runs ``swing_model`` 0 it gets
# ``_TUNING_SECTIONS`` untouched. A stored legacy value is converted once
# when the league first loads its overrides under the new model
# (services/physics_tuning_settings.convert_swing_slider_overrides).
#
# SWITCH-ON TEXT: the labels and descriptions below are what commissioners
# see from the Release 5 switch-on. Review them with the help page and the
# news post at the flip; nothing shows them before a league runs model 1.
_SWING_MODEL_SLIDERS: Dict[str, Optional[TuningSliderSpec]] = {
    "walk_scale": TuningSliderSpec(
        key="swing_walk_scale",
        label="Walk Rate",
        description=(
            "Walk frequency. 1.0 = MLB; 1.10 is about 10% more walks, 0.90 "
            "about 10% fewer. Works by making hitters chase less (or more). "
            "(Earlier versions ran 0.6-1.2 with 0.83 as normal; a saved "
            "setting was converted.)"
        ),
        min_value=0.7,
        max_value=1.4,
        step=0.01,
        fmt="{:.2f}",
    ),
    "zone_swing_scale": TuningSliderSpec(
        key="swing_zone_scale",
        label="Zone Swing",
        description=(
            "Swings at strikes. 1.0 = MLB swing rates in every count; "
            "higher is more aggressive, lower takes more strikes. (Earlier "
            "versions ran 0.6-1.2 with 0.91 as normal; a saved setting was "
            "converted.)"
        ),
        min_value=0.5,
        max_value=2.0,
        step=0.01,
        fmt="{:.2f}",
    ),
    "chase_scale": TuningSliderSpec(
        key="swing_chase_scale",
        label="Chase",
        description=(
            "Swings at balls out of the zone. 1.0 = MLB chase rates in "
            "every count; higher chases more. (Earlier versions ran "
            "0.4-1.0 with 0.69 as normal; a saved setting was converted.)"
        ),
        min_value=0.5,
        max_value=2.0,
        step=0.01,
        fmt="{:.2f}",
    ),
    "two_strike_aggression_scale": TuningSliderSpec(
        key="swing_two_strike_scale",
        label="Two-Strike Approach",
        description=(
            "How much hitters expand and protect with two strikes. 1.0 = "
            "MLB; higher swings more with two strikes (fewer called third "
            "strikes, more chases), lower takes more. Replaces Two-Strike "
            "Aggression and Two-Strike Protect; saved settings were "
            "combined."
        ),
        min_value=0.5,
        max_value=2.0,
        step=0.01,
        fmt="{:.2f}",
    ),
    # Merged into Two-Strike Approach: no slider of its own.
    "two_strike_zone_protect": None,
}


def tuning_sections(
    swing_model: float = 0.0,
) -> List[Tuple[str, List[TuningSliderSpec]]]:
    """The slider catalog for a league running ``swing_model``.

    Below 1 it is ``_TUNING_SECTIONS`` itself. From 1 the five legacy
    plate-discipline sliders are replaced by the four in
    ``_SWING_MODEL_SLIDERS`` (same sections, same order).
    """
    if swing_model < 1.0:
        return _TUNING_SECTIONS
    sections: List[Tuple[str, List[TuningSliderSpec]]] = []
    for label, specs in _TUNING_SECTIONS:
        swapped: List[TuningSliderSpec] = []
        for spec in specs:
            if spec.key not in _SWING_MODEL_SLIDERS:
                swapped.append(spec)
            elif _SWING_MODEL_SLIDERS[spec.key] is not None:
                swapped.append(_SWING_MODEL_SLIDERS[spec.key])
        sections.append((label, swapped))
    return sections


__all__ = [
    "TuningSliderSpec",
    "_SWING_MODEL_SLIDERS",
    "_TUNING_SECTIONS",
    "tuning_sections",
]
