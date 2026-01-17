from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from physics_sim.config import DEFAULT_TUNING
from services.physics_tuning_settings import (
    load_physics_tuning_overrides,
    load_physics_tuning_values,
    reset_physics_tuning_overrides,
    save_physics_tuning_overrides,
)


@dataclass(frozen=True)
class TuningSliderSpec:
    key: str
    label: str
    description: str
    min_value: float
    max_value: float
    step: float
    fmt: str


@dataclass
class SliderControl:
    slider: QSlider
    value_label: QLabel
    scale: int
    precision: int
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


def _precision_for_step(step: float) -> int:
    text = f"{step:.10f}".rstrip("0").rstrip(".")
    if "." in text:
        return len(text.split(".")[1])
    return 0


def _scale_for_step(step: float) -> int:
    if step <= 0:
        return 1
    return max(1, int(round(1 / step)))


class PhysicsTuningEditor(QDialog):
    """Dialog to configure physics engine tuning sliders."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Physics Tuning")
        self.resize(760, 680)
        self._controls: Dict[str, SliderControl] = {}
        self._overrides = load_physics_tuning_overrides()
        self._values = load_physics_tuning_values()
        self._suppress_updates = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        desc = QLabel(
            "Adjust core physics sliders. Changes apply immediately. "
            "Values not shown here remain at defaults."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        for title, specs in _TUNING_SECTIONS:
            group = QGroupBox(title)
            group_layout = QVBoxLayout(group)
            group_layout.setSpacing(10)
            for spec in specs:
                row = self._build_slider(spec)
                group_layout.addWidget(row)
            content_layout.addWidget(group)

        content_layout.addStretch(1)
        scroll.setWidget(content)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.reset_button = QPushButton("Reset to Defaults")
        self.close_button = QPushButton("Close")
        self.reset_button.setObjectName("Secondary")
        self.close_button.setObjectName("Primary")
        button_row.addWidget(self.reset_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.reset_button.clicked.connect(self._reset_defaults)
        self.close_button.clicked.connect(self.reject)

    def _build_slider(self, spec: TuningSliderSpec) -> QWidget:
        current_value = float(self._values.get(spec.key, 0.0))
        scale = _scale_for_step(spec.step)
        precision = _precision_for_step(spec.step)

        slider_min = int(round(spec.min_value * scale))
        slider_max = int(round(spec.max_value * scale))
        slider_value = int(round(current_value * scale))
        slider_value = max(slider_min, min(slider_max, slider_value))

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(slider_min)
        slider.setMaximum(slider_max)
        slider.setSingleStep(1)
        slider.setPageStep(5)
        slider.setValue(slider_value)

        value_label = QLabel(spec.fmt.format(slider_value / scale))

        header = QHBoxLayout()
        header.addWidget(QLabel(spec.label))
        header.addStretch(1)
        header.addWidget(value_label)

        description = QLabel(spec.description)
        description.setWordWrap(True)

        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(6, 6, 6, 6)
        row_layout.setSpacing(6)
        row_layout.addLayout(header)
        row_layout.addWidget(slider)
        row_layout.addWidget(description)

        control = SliderControl(
            slider=slider,
            value_label=value_label,
            scale=scale,
            precision=precision,
            fmt=spec.fmt,
        )
        self._controls[spec.key] = control

        slider.valueChanged.connect(
            lambda raw, key=spec.key, ctl=control: self._on_slider_change(
                key, raw, ctl
            )
        )
        return row

    def _on_slider_change(self, key: str, raw: int, control: SliderControl) -> None:
        value = raw / control.scale
        control.value_label.setText(control.fmt.format(value))
        if self._suppress_updates:
            return
        self._persist_override(key, value, control.precision)

    def _persist_override(self, key: str, value: float, precision: int) -> None:
        default_value = DEFAULT_TUNING.get(key)
        if not isinstance(default_value, (int, float)):
            return
        rounded = round(value, precision)
        if rounded == round(float(default_value), precision):
            self._overrides.pop(key, None)
        else:
            self._overrides[key] = rounded
        save_physics_tuning_overrides(self._overrides)

    def _reset_defaults(self) -> None:
        reset_physics_tuning_overrides()
        self._overrides = {}
        self._suppress_updates = True
        try:
            for key, control in self._controls.items():
                default_value = DEFAULT_TUNING.get(key, 0.0)
                if not isinstance(default_value, (int, float)):
                    continue
                raw = int(round(float(default_value) * control.scale))
                raw = max(control.slider.minimum(), min(control.slider.maximum(), raw))
                control.slider.setValue(raw)
        finally:
            self._suppress_updates = False


PlayBalanceEditor = PhysicsTuningEditor


__all__ = ["PhysicsTuningEditor", "PlayBalanceEditor"]
