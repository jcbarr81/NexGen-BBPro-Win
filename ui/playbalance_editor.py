from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

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
from .components import ActionButtonPanel

from physics_sim.config import DEFAULT_TUNING
from services.physics_tuning_settings import (
    load_physics_tuning_overrides,
    load_physics_tuning_values,
    reset_physics_tuning_overrides,
    save_physics_tuning_overrides,
)
from services.physics_tuning_spec import TuningSliderSpec, _TUNING_SECTIONS


@dataclass
class SliderControl:
    slider: QSlider
    value_label: QLabel
    scale: int
    precision: int
    fmt: str




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

        button_row = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )
        self.reset_button = QPushButton("Reset to Defaults")
        self.close_button = QPushButton("Close")
        self.reset_button.setObjectName("Secondary")
        self.close_button.setObjectName("Primary")
        button_row.add_buttons([self.reset_button, self.close_button])
        layout.addWidget(button_row)

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
