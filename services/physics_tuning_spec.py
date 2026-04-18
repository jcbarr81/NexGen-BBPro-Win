"""Physics tuning slider catalog — single source of truth.

Extracted from ``ui/playbalance_editor.py`` so the FastAPI sidecar can
reuse the exact same slider definitions without pulling in PyQt6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


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
                description="Steal attempt frequency scaling.",
                min_value=1.0,
                max_value=5.0,
                step=0.1,
                fmt="{:.1f}",
            ),
        ],
    ),
]


__all__ = ["TuningSliderSpec", "_TUNING_SECTIONS"]
