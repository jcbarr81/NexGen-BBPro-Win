"""Dialog for configuring Hall of Fame eligibility and scoring."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from services.hall_of_fame import (
    DEFAULT_MIN_YEARS_RETIRED,
    DEFAULT_SCORE_THRESHOLD,
    load_hall_of_fame,
    save_hall_of_fame,
    update_hall_of_fame,
)


class HallOfFameSettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hall of Fame Settings")
        self.resize(440, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        desc = QLabel(
            "Adjust Hall of Fame eligibility and scoring. "
            "Changes apply to future inductions; existing inductees remain."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        years_row = QHBoxLayout()
        years_row.addWidget(QLabel("Minimum Years Retired"))
        self.years_spin = QSpinBox()
        self.years_spin.setMinimum(0)
        self.years_spin.setMaximum(50)
        self.years_spin.setSingleStep(1)
        years_row.addWidget(self.years_spin, 1)
        layout.addLayout(years_row)

        score_row = QHBoxLayout()
        score_row.addWidget(QLabel("Score Threshold"))
        self.score_spin = QDoubleSpinBox()
        self.score_spin.setMinimum(0.0)
        self.score_spin.setMaximum(10000.0)
        self.score_spin.setDecimals(1)
        self.score_spin.setSingleStep(5.0)
        score_row.addWidget(self.score_spin, 1)
        layout.addLayout(score_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.reset_button = QPushButton("Reset to Defaults")
        self.save_button = QPushButton("Save")
        self.close_button = QPushButton("Close")
        self.save_button.setObjectName("Primary")
        button_row.addWidget(self.reset_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.reset_button.clicked.connect(self._reset_defaults)
        self.save_button.clicked.connect(self._save)
        self.close_button.clicked.connect(self.reject)

        self._load_settings()

    def _load_settings(self) -> None:
        payload = load_hall_of_fame()
        settings = payload.get("settings", {}) if isinstance(payload, dict) else {}
        min_years = settings.get("min_years_retired", DEFAULT_MIN_YEARS_RETIRED)
        threshold = settings.get("score_threshold", DEFAULT_SCORE_THRESHOLD)
        try:
            self.years_spin.setValue(int(min_years))
        except Exception:
            self.years_spin.setValue(DEFAULT_MIN_YEARS_RETIRED)
        try:
            self.score_spin.setValue(float(threshold))
        except Exception:
            self.score_spin.setValue(float(DEFAULT_SCORE_THRESHOLD))

    def _save(self) -> None:
        payload = load_hall_of_fame()
        settings = payload.get("settings", {}) if isinstance(payload, dict) else {}
        settings["min_years_retired"] = int(self.years_spin.value())
        settings["score_threshold"] = float(self.score_spin.value())
        payload["settings"] = settings
        save_hall_of_fame(payload)
        try:
            update_hall_of_fame()
        except Exception:
            pass
        self.accept()

    def _reset_defaults(self) -> None:
        self.years_spin.setValue(DEFAULT_MIN_YEARS_RETIRED)
        self.score_spin.setValue(float(DEFAULT_SCORE_THRESHOLD))


__all__ = ["HallOfFameSettingsDialog"]
