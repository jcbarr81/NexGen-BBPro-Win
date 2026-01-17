"""Dialog for configuring league-wide injury settings."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from services.injury_settings import (
    DEFAULT_LEVEL,
    LEVEL_OPTIONS,
    load_injury_settings,
    set_injury_level,
)


class InjurySettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Injury Settings")
        self.resize(420, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        desc = QLabel(
            "Configure league-wide injury frequency. Changes apply immediately."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        row = QHBoxLayout()
        row.addWidget(QLabel("Frequency"))
        self.level_combo = QComboBox()
        for key, label in (
            ("off", "Off"),
            ("low", "Low"),
            ("normal", "Normal"),
        ):
            self.level_combo.addItem(label, key)
        row.addWidget(self.level_combo, 1)
        layout.addLayout(row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.save_button = QPushButton("Save")
        self.close_button = QPushButton("Close")
        self.save_button.setObjectName("Primary")
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.save_button.clicked.connect(self._save)
        self.close_button.clicked.connect(self.reject)

        self._load_settings()

    def _load_settings(self) -> None:
        settings = load_injury_settings()
        level = settings.level or DEFAULT_LEVEL
        if level not in LEVEL_OPTIONS:
            level = DEFAULT_LEVEL
        idx = self.level_combo.findData(level)
        if idx >= 0:
            self.level_combo.setCurrentIndex(idx)

    def _save(self) -> None:
        level = self.level_combo.currentData() or DEFAULT_LEVEL
        set_injury_level(str(level))
        self.accept()


__all__ = ["InjurySettingsDialog"]
