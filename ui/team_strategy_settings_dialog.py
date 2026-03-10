"""Dialog for league default and per-team strategy profile settings."""

from __future__ import annotations

from typing import Dict

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from .components import ActionButtonPanel

from services.team_strategy_profiles import (
    STRATEGY_PROFILES,
    load_team_strategy_settings,
    save_team_strategy_settings,
)
from services.team_auto_reassign_settings import (
    DEFAULT_ENABLED as AUTO_REASSIGN_DEFAULT_ENABLED,
    load_team_auto_reassign_settings,
    save_team_auto_reassign_settings,
)
from utils.team_loader import load_teams


class TeamStrategySettingsDialog(QDialog):
    """Commissioner editor for team strategy and auto-reassign defaults."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Team Strategy & Auto-Reassign")
        self.setMinimumSize(820, 560)
        self.resize(900, 680)
        self._team_strategy_combos: Dict[str, QComboBox] = {}
        self._team_auto_reassign_combos: Dict[str, QComboBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel(
            "Set league defaults and per-team overrides for strategy and "
            "optional roster auto-reassign automation."
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

        default_layout.addWidget(QLabel("Default Auto-Reassign"), 2, 0)
        self.default_auto_reassign_combo = QComboBox()
        self.default_auto_reassign_combo.addItem("Enabled", "enabled")
        self.default_auto_reassign_combo.addItem("Disabled", "disabled")
        default_layout.addWidget(self.default_auto_reassign_combo, 2, 1)
        self.default_auto_reassign_summary_label = QLabel("")
        self.default_auto_reassign_summary_label.setWordWrap(True)
        default_layout.addWidget(self.default_auto_reassign_summary_label, 3, 0, 1, 2)
        root.addWidget(default_group)

        teams_group = QGroupBox("Team Overrides")
        teams_layout = QVBoxLayout(teams_group)
        teams_layout.setContentsMargins(12, 12, 12, 12)
        teams_layout.setSpacing(8)
        teams_help = QLabel(
            "Set team-specific strategy and auto-reassign behavior. "
            "Choose League Default to inherit each league-level setting."
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

        buttons = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=200,
            min_button_width=150,
            max_button_width=230,
        )
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.close_button = QPushButton("Close")
        buttons.add_buttons([self.save_button, self.close_button])
        root.addWidget(buttons)

        self.default_combo.currentIndexChanged.connect(self._refresh_default_summary)
        self.default_auto_reassign_combo.currentIndexChanged.connect(
            self._refresh_auto_default_summary
        )
        self.save_button.clicked.connect(self._save)
        self.close_button.clicked.connect(self.reject)

        self._load()

    def _load(self) -> None:
        strategy_settings = load_team_strategy_settings()
        default_profile = str(strategy_settings.get("default_profile") or "balanced")
        strategy_overrides = strategy_settings.get("team_overrides", {})
        if not isinstance(strategy_overrides, dict):
            strategy_overrides = {}

        auto_reassign_settings = load_team_auto_reassign_settings()
        default_auto_enabled = bool(
            auto_reassign_settings.get("default_enabled", AUTO_REASSIGN_DEFAULT_ENABLED)
        )
        auto_reassign_overrides = auto_reassign_settings.get("team_overrides", {})
        if not isinstance(auto_reassign_overrides, dict):
            auto_reassign_overrides = {}

        idx = self.default_combo.findData(default_profile)
        self.default_combo.setCurrentIndex(idx if idx >= 0 else 0)
        auto_idx = self.default_auto_reassign_combo.findData(
            "enabled" if default_auto_enabled else "disabled"
        )
        self.default_auto_reassign_combo.setCurrentIndex(auto_idx if auto_idx >= 0 else 0)

        self._build_team_rows(strategy_overrides, auto_reassign_overrides)
        self._refresh_default_summary()
        self._refresh_auto_default_summary()

    def _build_team_rows(
        self,
        strategy_overrides: Dict[str, str],
        auto_reassign_overrides: Dict[str, bool],
    ) -> None:
        while self._teams_grid.count():
            item = self._teams_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._team_strategy_combos.clear()
        self._team_auto_reassign_combos.clear()

        self._teams_grid.addWidget(QLabel("Team"), 0, 0)
        self._teams_grid.addWidget(QLabel("Division"), 0, 1)
        self._teams_grid.addWidget(QLabel("Strategy Override"), 0, 2)
        self._teams_grid.addWidget(QLabel("Auto-Reassign Override"), 0, 3)

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
            selected = str(strategy_overrides.get(team_id, "") or "")
            strategy_idx = combo.findData(selected)
            combo.setCurrentIndex(strategy_idx if strategy_idx >= 0 else 0)
            self._team_strategy_combos[team_id] = combo
            self._teams_grid.addWidget(combo, row, 2)

            auto_combo = QComboBox()
            auto_combo.addItem("League Default", "")
            auto_combo.addItem("Enabled", "enabled")
            auto_combo.addItem("Disabled", "disabled")
            auto_selected = auto_reassign_overrides.get(team_id, None)
            if auto_selected is True:
                auto_data = "enabled"
            elif auto_selected is False:
                auto_data = "disabled"
            else:
                auto_data = ""
            auto_selected_idx = auto_combo.findData(auto_data)
            auto_combo.setCurrentIndex(auto_selected_idx if auto_selected_idx >= 0 else 0)
            self._team_auto_reassign_combos[team_id] = auto_combo
            self._teams_grid.addWidget(auto_combo, row, 3)
            row += 1

        if row == 1:
            self._teams_grid.addWidget(QLabel("No teams available."), row, 0, 1, 4)

    def _refresh_default_summary(self) -> None:
        profile_id = str(self.default_combo.currentData() or "balanced")
        meta = STRATEGY_PROFILES.get(profile_id, STRATEGY_PROFILES["balanced"])
        label = str(meta.get("label", "Balanced"))
        description = str(meta.get("description", ""))
        self.default_summary_label.setText(f"{label}: {description}")

    def _refresh_auto_default_summary(self) -> None:
        selected = str(self.default_auto_reassign_combo.currentData() or "disabled")
        if selected == "enabled":
            self.default_auto_reassign_summary_label.setText(
                "Enabled: roster updates can trigger automatic ACT/AAA/LOW rebalancing."
            )
        else:
            self.default_auto_reassign_summary_label.setText(
                "Disabled: owners keep manual roster level control unless they opt in."
            )

    def _save(self) -> None:
        default_profile = str(self.default_combo.currentData() or "balanced")
        strategy_overrides: dict[str, str] = {}
        for team_id, combo in self._team_strategy_combos.items():
            profile = str(combo.currentData() or "").strip().lower()
            if not profile:
                continue
            strategy_overrides[team_id] = profile

        default_auto_enabled = (
            str(self.default_auto_reassign_combo.currentData() or "disabled") == "enabled"
        )
        auto_reassign_overrides: dict[str, bool] = {}
        for team_id, combo in self._team_auto_reassign_combos.items():
            value = str(combo.currentData() or "").strip().lower()
            if value == "enabled":
                auto_reassign_overrides[team_id] = True
            elif value == "disabled":
                auto_reassign_overrides[team_id] = False
        save_team_strategy_settings(
            default_profile=default_profile,
            team_overrides=strategy_overrides,
        )
        save_team_auto_reassign_settings(
            default_enabled=default_auto_enabled,
            team_overrides=auto_reassign_overrides,
        )
        self.accept()


__all__ = ["TeamStrategySettingsDialog"]
