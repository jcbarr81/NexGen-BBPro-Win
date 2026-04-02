"""Finance setup step used by league creation flow."""

from __future__ import annotations

from typing import Any, Dict

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)
from .components import ActionButtonPanel

from services.finance_settings import (
    ENFORCEMENT_BLOCK,
    ENFORCEMENT_OFF,
    ENFORCEMENT_WARN,
    MODULE_LEVELS,
    PRESET_CUSTOM,
    PRESET_MLB_LIKE,
    PRESET_OFF,
    PRESET_PROFILES,
    PRESET_SIMPLE,
    PRESET_STANDARD,
    build_finance_enforcement_tooltip,
    build_finance_module_tooltip,
)

_PRESET_LABELS = {
    PRESET_OFF: "Off",
    PRESET_SIMPLE: "Simple",
    PRESET_STANDARD: "Standard (Recommended)",
    PRESET_MLB_LIKE: "MLB-Like",
    PRESET_CUSTOM: "Custom",
}

_LEVEL_LABELS = {
    "off": "Off",
    "basic": "Basic",
    "advanced": "Advanced",
    "mlb_like": "MLB-Like",
    "warn": "Warn",
    "block": "Block",
}

_KEY_MODULES = (
    ("owner_budgets", "Owner Budgets"),
    ("gm_contracts", "GM Contracts"),
    ("gm_payroll_rules", "Payroll Rules"),
    ("gm_arbitration", "Arbitration"),
    ("gm_free_agency", "Free Agency"),
    ("gm_roster_cost_enforcement", "Roster Cost Enforcement"),
)


def _combo_current_data(combo: QComboBox, fallback: str = "") -> str:
    getter = getattr(combo, "currentData", None)
    if callable(getter):
        try:
            token = str(getter() or "").strip()
            if token:
                return token
        except Exception:
            pass
    return fallback


def _set_combo_data(combo: QComboBox, value: str) -> None:
    token = str(value or "").strip().lower()
    find_data = getattr(combo, "findData", None)
    set_current_index = getattr(combo, "setCurrentIndex", None)
    if callable(find_data) and callable(set_current_index):
        try:
            index = int(find_data(token))
            if index >= 0:
                set_current_index(index)
                return
        except Exception:
            pass
    # Fallback for lightweight test stubs.
    items = getattr(combo, "_items", None)
    if isinstance(items, list) and callable(set_current_index):
        for idx, (_label, data) in enumerate(items):
            if str(data or "").strip().lower() == token:
                try:
                    set_current_index(idx)
                except Exception:
                    pass
                return


class LeagueCreationFinanceDialog(QDialog):
    """Wizard step for selecting initial finance configuration."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("League Creation - Finance Setup")
        self.resize(700, 520)
        self._updating = False
        self._module_combos: Dict[str, QComboBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel(
            "Choose initial finance rules for this league. "
            "You can use a preset or pick Custom and adjust key modules before league creation finishes."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        top_group = QGroupBox("Finance Mode")
        top_layout = QGridLayout(top_group)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setHorizontalSpacing(12)
        top_layout.setVerticalSpacing(8)

        top_layout.addWidget(QLabel("Preset"), 0, 0)
        self.preset_combo = QComboBox()
        for preset in (
            PRESET_STANDARD,
            PRESET_SIMPLE,
            PRESET_MLB_LIKE,
            PRESET_OFF,
            PRESET_CUSTOM,
        ):
            self.preset_combo.addItem(_PRESET_LABELS[preset], preset)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        top_layout.addWidget(self.preset_combo, 0, 1)

        self.enabled_checkbox = QCheckBox("Enable Financial System")
        self.enabled_checkbox.toggled.connect(self._on_manual_change)
        top_layout.addWidget(self.enabled_checkbox, 1, 0, 1, 2)

        top_layout.addWidget(QLabel("Enforcement Mode"), 2, 0)
        self.enforcement_combo = QComboBox()
        self.enforcement_combo.addItem(_LEVEL_LABELS[ENFORCEMENT_OFF], ENFORCEMENT_OFF)
        self.enforcement_combo.addItem(_LEVEL_LABELS[ENFORCEMENT_WARN], ENFORCEMENT_WARN)
        self.enforcement_combo.addItem(_LEVEL_LABELS[ENFORCEMENT_BLOCK], ENFORCEMENT_BLOCK)
        self.enforcement_combo.currentIndexChanged.connect(self._on_manual_change)
        self.enforcement_combo.setToolTip(build_finance_enforcement_tooltip())
        top_layout.addWidget(self.enforcement_combo, 2, 1)
        root.addWidget(top_group)

        modules_group = QGroupBox("Custom Key Modules")
        modules_layout = QGridLayout(modules_group)
        modules_layout.setContentsMargins(10, 10, 10, 10)
        modules_layout.setHorizontalSpacing(12)
        modules_layout.setVerticalSpacing(8)

        module_help_note = QLabel(
            "Hover a module name or level selector to see what each level changes."
        )
        module_help_note.setWordWrap(True)
        modules_layout.addWidget(module_help_note, 0, 0, 1, 2)

        for row, (module, label) in enumerate(_KEY_MODULES):
            tooltip = build_finance_module_tooltip(module)
            module_label = QLabel(label)
            module_label.setToolTip(tooltip)
            modules_layout.addWidget(module_label, row + 1, 0)
            combo = QComboBox()
            for level in MODULE_LEVELS.get(module, ()):
                combo.addItem(_LEVEL_LABELS.get(level, level.title()), level)
            combo.currentIndexChanged.connect(self._on_manual_change)
            combo.setToolTip(tooltip)
            self._module_combos[module] = combo
            modules_layout.addWidget(combo, row + 1, 1)

        root.addWidget(modules_group)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        button_row = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=200,
            min_button_width=150,
            max_button_width=230,
        )
        cancel_btn = QPushButton("Cancel")
        continue_btn = QPushButton("Continue")
        continue_btn.setObjectName("Primary")
        button_row.add_buttons([cancel_btn, continue_btn])
        root.addWidget(button_row)

        cancel_btn.clicked.connect(self.reject)
        continue_btn.clicked.connect(self.accept)

        _set_combo_data(self.preset_combo, PRESET_STANDARD)
        self._apply_preset(PRESET_STANDARD)

    def _on_preset_changed(self) -> None:
        if self._updating:
            return
        preset = _combo_current_data(self.preset_combo, PRESET_STANDARD)
        self._apply_preset(preset)

    def _on_manual_change(self) -> None:
        if self._updating:
            return
        preset = _combo_current_data(self.preset_combo, PRESET_STANDARD)
        if preset != PRESET_CUSTOM:
            _set_combo_data(self.preset_combo, PRESET_CUSTOM)
            preset = PRESET_CUSTOM
        self._sync_manual_state(preset)
        self._refresh_summary()

    def _apply_preset(self, preset: str) -> None:
        token = str(preset or PRESET_STANDARD).strip().lower()
        profile = PRESET_PROFILES.get(token, PRESET_PROFILES[PRESET_OFF])
        modules = profile.get("modules") if isinstance(profile, dict) else {}
        modules_map = modules if isinstance(modules, dict) else {}

        self._updating = True
        try:
            self.enabled_checkbox.setChecked(bool(profile.get("enabled", False)))
            _set_combo_data(
                self.enforcement_combo,
                str(profile.get("enforcement_mode") or ENFORCEMENT_WARN),
            )
            for module, combo in self._module_combos.items():
                _set_combo_data(combo, str(modules_map.get(module, "off")))
            self._sync_manual_state(token)
            self._refresh_summary()
        finally:
            self._updating = False

    def _sync_manual_state(self, preset: str) -> None:
        custom_mode = str(preset or "").strip().lower() == PRESET_CUSTOM
        self.enabled_checkbox.setEnabled(custom_mode)
        self.enforcement_combo.setEnabled(custom_mode)
        for combo in self._module_combos.values():
            combo.setEnabled(custom_mode)

    def _refresh_summary(self) -> None:
        summary = self.summarize_selection(self.get_selection())
        self.summary_label.setText(summary)

    @staticmethod
    def summarize_selection(selection: Dict[str, Any]) -> str:
        preset = str(selection.get("preset") or PRESET_OFF).strip().lower()
        enabled = bool(selection.get("enabled", False))
        enforcement = str(selection.get("enforcement_mode") or ENFORCEMENT_WARN).strip().lower()
        modules = selection.get("modules") if isinstance(selection.get("modules"), dict) else {}
        labels = []
        labels.append(f"Preset: {_PRESET_LABELS.get(preset, preset.title())}")
        labels.append(f"Enabled: {'Yes' if enabled else 'No'}")
        labels.append(
            f"Enforcement: {_LEVEL_LABELS.get(enforcement, enforcement.title())}"
        )
        if preset == PRESET_CUSTOM and modules:
            for key, label in _KEY_MODULES:
                token = str(modules.get(key, "off")).strip().lower()
                labels.append(f"{label}: {_LEVEL_LABELS.get(token, token.title())}")
        return "Finance Setup Summary: " + " | ".join(labels)

    def get_selection(self) -> Dict[str, Any]:
        preset = _combo_current_data(self.preset_combo, PRESET_STANDARD)
        modules = {
            module: _combo_current_data(combo, "off")
            for module, combo in self._module_combos.items()
        }
        return {
            "preset": preset,
            "enabled": bool(getattr(self.enabled_checkbox, "isChecked", lambda: False)()),
            "enforcement_mode": _combo_current_data(
                self.enforcement_combo, ENFORCEMENT_WARN
            ),
            "modules": modules,
        }


__all__ = ["LeagueCreationFinanceDialog"]
