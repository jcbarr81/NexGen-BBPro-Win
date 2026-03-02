"""Dialog for league default and per-team strategy profile settings."""

from __future__ import annotations

from typing import Dict

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from services.team_strategy_profiles import (
    STRATEGY_PROFILES,
    load_team_strategy_settings,
    save_team_strategy_settings,
)
from utils.team_loader import load_teams


class TeamStrategySettingsDialog(QDialog):
    """Commissioner editor for team strategy defaults and overrides."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Team Strategy Profiles")
        self.setMinimumSize(820, 560)
        self.resize(900, 680)
        self._team_combos: Dict[str, QComboBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel(
            "Set a league strategy default and optional per-team overrides. "
            "Overrides are used when automation services need team intent."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        default_group = QGroupBox("League Default Strategy")
        default_layout = QGridLayout(default_group)
        default_layout.setContentsMargins(12, 12, 12, 12)
        default_layout.addWidget(QLabel("Default Profile"), 0, 0)
        self.default_combo = QComboBox()
        for profile_id, meta in STRATEGY_PROFILES.items():
            self.default_combo.addItem(str(meta.get("label", profile_id.title())), profile_id)
        default_layout.addWidget(self.default_combo, 0, 1)
        self.default_summary_label = QLabel("")
        self.default_summary_label.setWordWrap(True)
        default_layout.addWidget(self.default_summary_label, 1, 0, 1, 2)
        root.addWidget(default_group)

        teams_group = QGroupBox("Team Overrides")
        teams_layout = QVBoxLayout(teams_group)
        teams_layout.setContentsMargins(12, 12, 12, 12)
        teams_layout.setSpacing(8)
        teams_help = QLabel(
            "Set team-specific strategy profiles. "
            "Choose League Default for teams that should inherit the league profile."
        )
        teams_help.setWordWrap(True)
        teams_layout.addWidget(teams_help)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self._teams_grid = QGridLayout(scroll_content)
        self._teams_grid.setContentsMargins(6, 6, 6, 6)
        self._teams_grid.setHorizontalSpacing(16)
        self._teams_grid.setVerticalSpacing(8)
        scroll.setWidget(scroll_content)
        teams_layout.addWidget(scroll, stretch=1)
        root.addWidget(teams_group, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.close_button = QPushButton("Close")
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)

        self.default_combo.currentIndexChanged.connect(self._refresh_default_summary)
        self.save_button.clicked.connect(self._save)
        self.close_button.clicked.connect(self.reject)

        self._load()

    def _load(self) -> None:
        settings = load_team_strategy_settings()
        default_profile = str(settings.get("default_profile") or "balanced")
        overrides = settings.get("team_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}

        idx = self.default_combo.findData(default_profile)
        self.default_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self._build_team_rows(overrides)
        self._refresh_default_summary()

    def _build_team_rows(self, overrides: Dict[str, str]) -> None:
        while self._teams_grid.count():
            item = self._teams_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._team_combos.clear()

        self._teams_grid.addWidget(QLabel("Team"), 0, 0)
        self._teams_grid.addWidget(QLabel("Division"), 0, 1)
        self._teams_grid.addWidget(QLabel("Override"), 0, 2)

        try:
            teams = list(load_teams())
        except Exception:
            teams = []
        teams.sort(
            key=lambda team: (
                str(getattr(team, "division", "") or "").strip(),
                str(getattr(team, "team_id", "") or "").strip(),
            )
        )

        row = 1
        for team in teams:
            team_id = str(getattr(team, "team_id", "") or "").strip().upper()
            if not team_id:
                continue
            division = str(getattr(team, "division", "") or "").strip() or "--"
            label = str(getattr(team, "name", "") or team_id).strip() or team_id
            self._teams_grid.addWidget(QLabel(f"{team_id} - {label}"), row, 0)
            self._teams_grid.addWidget(QLabel(division), row, 1)
            combo = QComboBox()
            combo.addItem("League Default", "")
            for profile_id, meta in STRATEGY_PROFILES.items():
                combo.addItem(str(meta.get("label", profile_id.title())), profile_id)
            selected = str(overrides.get(team_id, "") or "")
            idx = combo.findData(selected)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._team_combos[team_id] = combo
            self._teams_grid.addWidget(combo, row, 2)
            row += 1

        if row == 1:
            self._teams_grid.addWidget(QLabel("No teams available."), row, 0, 1, 3)

    def _refresh_default_summary(self) -> None:
        profile_id = str(self.default_combo.currentData() or "balanced")
        meta = STRATEGY_PROFILES.get(profile_id, STRATEGY_PROFILES["balanced"])
        label = str(meta.get("label", "Balanced"))
        description = str(meta.get("description", ""))
        self.default_summary_label.setText(f"{label}: {description}")

    def _save(self) -> None:
        default_profile = str(self.default_combo.currentData() or "balanced")
        overrides: dict[str, str] = {}
        for team_id, combo in self._team_combos.items():
            profile = str(combo.currentData() or "").strip().lower()
            if not profile:
                continue
            overrides[team_id] = profile
        save_team_strategy_settings(
            default_profile=default_profile,
            team_overrides=overrides,
        )
        self.accept()


__all__ = ["TeamStrategySettingsDialog"]
