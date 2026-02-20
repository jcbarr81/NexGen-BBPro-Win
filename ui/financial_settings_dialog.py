"""Dialog for configuring league-wide financial system settings."""

from __future__ import annotations

from typing import Dict

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from services.finance_settings import (
    DEFAULT_FINANCE_AI_TUNING,
    ENFORCEMENT_WARN,
    MODULE_LEVELS,
    PRESET_CUSTOM,
    PRESET_OFF,
    PRESET_PROFILES,
    apply_financial_preset,
    load_financial_settings,
    update_financial_settings,
)
from services.finance_reporting import (
    build_commissioner_projection_report,
    build_finance_alerts,
)

_PRESET_LABELS = {
    "off": "Off",
    "simple": "Simple",
    "standard": "Standard",
    "mlb_like": "MLB-Like",
    "custom": "Custom",
}

_LEVEL_LABELS = {
    "off": "Off",
    "basic": "Basic",
    "advanced": "Advanced",
    "mlb_like": "MLB-Like",
    "warn": "Warn",
    "block": "Block",
}

_MODULE_LABELS = {
    "owner_revenue": "Owner: Revenue Model",
    "owner_market_model": "Owner: Market/Fan Interest",
    "owner_budgets": "Owner: Budget Buckets",
    "owner_expenses": "Owner: Operating Expenses",
    "gm_contracts": "GM: Contracts",
    "gm_payroll_rules": "GM: Payroll Rules",
    "gm_arbitration": "GM: Arbitration",
    "gm_free_agency": "GM: Free Agency",
    "gm_roster_cost_enforcement": "GM: Roster Cost Enforcement",
    "gm_finance_ai": "GM AI: Financial Behavior",
}

_MODULE_ORDER = [
    "owner_revenue",
    "owner_market_model",
    "owner_budgets",
    "owner_expenses",
    "gm_contracts",
    "gm_payroll_rules",
    "gm_arbitration",
    "gm_free_agency",
    "gm_roster_cost_enforcement",
    "gm_finance_ai",
]

_AI_TUNING_FIELDS = (
    ("star_talent_threshold", "Star Talent Threshold"),
    ("star_performance_threshold", "Star Performance Threshold"),
    ("underperformer_threshold", "Underperformer Threshold"),
    ("high_cost_salary_share", "High-Cost Salary Share"),
    ("very_high_cost_salary_share", "Very-High-Cost Salary Share"),
    ("high_cost_salary", "High-Cost Salary ($)"),
    ("very_high_cost_salary", "Very-High-Cost Salary ($)"),
    ("max_raise_pct", "Max Arbitration Raise %"),
    ("fa_star_quality_threshold", "FA Star Quality Threshold"),
    ("fa_rebuild_avoid_salary", "FA Rebuild Avoid Salary ($)"),
    ("fa_cautious_avoid_salary", "FA Cautious Avoid Salary ($)"),
    ("fa_hard_avoid_salary", "FA Hard Avoid Salary ($)"),
    ("commitment_pressure_ratio", "Commitment Pressure Ratio"),
    ("commitment_relief_ratio", "Commitment Relief Ratio"),
    ("commitment_pressure_penalty", "Commitment Pressure Penalty ($)"),
    ("commitment_relief_bonus", "Commitment Relief Bonus ($)"),
    ("future_year_commitment_ratio_limit", "Future-Year Commitment Ratio Limit"),
    (
        "future_year_hard_commitment_ratio_limit",
        "Future-Year Hard Commitment Ratio Limit",
    ),
)


class FinancialSettingsDialog(QDialog):
    """Admin editor for global finance mode and per-module complexity levels."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Financial System Settings")
        self.resize(840, 760)
        self._updating = False
        self._module_combos: Dict[str, QComboBox] = {}
        self._ai_tuning_inputs: Dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        desc = QLabel(
            "Configure the two-layer financial system for the active league. "
            "When disabled, all finance logic is bypassed. When enabled, each module "
            "can run at Off/Basic/Advanced (or MLB-Like where applicable)."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        top = QGroupBox("Global Controls")
        top_layout = QGridLayout(top)
        top_layout.setContentsMargins(12, 12, 12, 12)
        top_layout.setHorizontalSpacing(16)
        top_layout.setVerticalSpacing(10)

        self.enabled_checkbox = QCheckBox("Enable Financial System")
        self.enabled_checkbox.toggled.connect(self._on_manual_change)
        top_layout.addWidget(self.enabled_checkbox, 0, 0, 1, 2)

        top_layout.addWidget(QLabel("Preset"), 1, 0)
        self.preset_combo = QComboBox()
        for key in ("off", "simple", "standard", "mlb_like", "custom"):
            self.preset_combo.addItem(_PRESET_LABELS[key], key)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        top_layout.addWidget(self.preset_combo, 1, 1)

        top_layout.addWidget(QLabel("Enforcement Mode"), 2, 0)
        self.enforcement_combo = QComboBox()
        for key in ("off", "warn", "block"):
            self.enforcement_combo.addItem(_LEVEL_LABELS[key], key)
        self.enforcement_combo.currentIndexChanged.connect(self._on_manual_change)
        top_layout.addWidget(self.enforcement_combo, 2, 1)

        layout.addWidget(top)

        modules_group = QGroupBox("Module Levels")
        modules_layout = QVBoxLayout(modules_group)
        modules_layout.setContentsMargins(8, 8, 8, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        module_host = QWidget()
        module_grid = QGridLayout(module_host)
        module_grid.setContentsMargins(8, 8, 8, 8)
        module_grid.setHorizontalSpacing(16)
        module_grid.setVerticalSpacing(8)

        for row, module in enumerate(_MODULE_ORDER):
            label = QLabel(_MODULE_LABELS.get(module, module))
            combo = QComboBox()
            for level in MODULE_LEVELS.get(module, ("off",)):
                combo.addItem(_LEVEL_LABELS.get(level, level), level)
            combo.currentIndexChanged.connect(self._on_manual_change)
            module_grid.addWidget(label, row, 0)
            module_grid.addWidget(combo, row, 1)
            self._module_combos[module] = combo

        scroll.setWidget(module_host)
        modules_layout.addWidget(scroll)
        layout.addWidget(modules_group, stretch=1)

        ai_group = QGroupBox("CPU Finance AI Tuning")
        ai_layout = QGridLayout(ai_group)
        ai_layout.setContentsMargins(12, 12, 12, 12)
        ai_layout.setHorizontalSpacing(16)
        ai_layout.setVerticalSpacing(8)
        for row, (key, label) in enumerate(_AI_TUNING_FIELDS):
            ai_layout.addWidget(QLabel(label), row, 0)
            field = QLineEdit()
            field.setObjectName(f"ai_tuning_{key}")
            field.textEdited.connect(self._on_manual_change)
            ai_layout.addWidget(field, row, 1)
            self._ai_tuning_inputs[key] = field
        layout.addWidget(ai_group)

        workflow_group = QGroupBox("Commissioner Workflow Guidance")
        workflow_layout = QVBoxLayout(workflow_group)
        workflow_layout.setContentsMargins(12, 12, 12, 12)
        self.workflow_label = QLabel("")
        self.workflow_label.setWordWrap(True)
        self.workflow_label.setTextInteractionFlags(
            self.workflow_label.textInteractionFlags()
        )
        workflow_layout.addWidget(self.workflow_label)
        layout.addWidget(workflow_group)

        projection_group = QGroupBox("Commissioner Projection Preview")
        projection_layout = QVBoxLayout(projection_group)
        projection_layout.setContentsMargins(12, 12, 12, 12)
        self.projection_preview_label = QLabel("")
        self.projection_preview_label.setWordWrap(True)
        self.projection_preview_label.setTextInteractionFlags(
            self.projection_preview_label.textInteractionFlags()
        )
        projection_layout.addWidget(self.projection_preview_label)
        layout.addWidget(projection_group)

        alerts_group = QGroupBox("Finance Alerts")
        alerts_layout = QVBoxLayout(alerts_group)
        alerts_layout.setContentsMargins(12, 12, 12, 12)
        self.alerts_preview_label = QLabel("")
        self.alerts_preview_label.setWordWrap(True)
        self.alerts_preview_label.setTextInteractionFlags(
            self.alerts_preview_label.textInteractionFlags()
        )
        alerts_layout.addWidget(self.alerts_preview_label)
        layout.addWidget(alerts_group)

        button_row = QHBoxLayout()
        self.refresh_preview_button = QPushButton("Refresh Preview")
        self.refresh_preview_button.clicked.connect(self._refresh_reporting_preview)
        button_row.addWidget(self.refresh_preview_button)
        button_row.addStretch(1)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.close_button = QPushButton("Close")
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.save_button.clicked.connect(self._save)
        self.close_button.clicked.connect(self.reject)

        self._load()

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _set_preset_custom(self) -> None:
        if self._preset_value() == PRESET_CUSTOM:
            return
        self._updating = True
        self._set_combo_value(self.preset_combo, PRESET_CUSTOM)
        self._updating = False

    def _preset_value(self) -> str:
        data = self.preset_combo.currentData()
        return str(data or PRESET_CUSTOM)

    def _load(self) -> None:
        settings = load_financial_settings()
        self._updating = True
        self.enabled_checkbox.setChecked(bool(settings.enabled))
        self._set_combo_value(self.preset_combo, settings.preset)
        self._set_combo_value(self.enforcement_combo, settings.enforcement_mode)
        for module, combo in self._module_combos.items():
            self._set_combo_value(combo, settings.modules.get(module, "off"))
        self._set_ai_tuning_values(settings.finance_ai_tuning)
        self._updating = False
        self._sync_enabled_state()
        self._refresh_reporting_preview()

    def _apply_preset_to_controls(self, preset: str) -> None:
        profile = PRESET_PROFILES.get(preset)
        if profile is None:
            return
        modules = profile.get("modules", {})
        self._updating = True
        self.enabled_checkbox.setChecked(bool(profile.get("enabled", False)))
        self._set_combo_value(
            self.enforcement_combo,
            str(profile.get("enforcement_mode", ENFORCEMENT_WARN)),
        )
        if isinstance(modules, dict):
            for module, combo in self._module_combos.items():
                self._set_combo_value(combo, str(modules.get(module, "off")))
        self._updating = False

    def _on_preset_changed(self, *_args) -> None:
        if self._updating:
            return
        preset = self._preset_value()
        if preset != PRESET_CUSTOM:
            self._apply_preset_to_controls(preset)
        self._sync_enabled_state()

    def _on_manual_change(self, *_args) -> None:
        if self._updating:
            return
        self._set_preset_custom()
        self._sync_enabled_state()

    def _sync_enabled_state(self) -> None:
        enabled = self.enabled_checkbox.isChecked()
        self.enforcement_combo.setEnabled(enabled)
        for combo in self._module_combos.values():
            combo.setEnabled(enabled)
        for field in self._ai_tuning_inputs.values():
            field.setEnabled(enabled)

    def _refresh_reporting_preview(self) -> None:
        try:
            report = build_commissioner_projection_report()
            alerts = build_finance_alerts(report=report, limit=8)
        except Exception:
            self.workflow_label.setText(
                "Workflow preview unavailable. Save settings and refresh to retry."
            )
            self.projection_preview_label.setText(
                "Projection preview unavailable."
            )
            self.alerts_preview_label.setText("Finance alerts unavailable.")
            return
        self.workflow_label.setText(self._format_workflow_preview(report))
        self.projection_preview_label.setText(self._format_projection_preview(report))
        self.alerts_preview_label.setText(self._format_alert_preview(alerts))

    @staticmethod
    def _format_workflow_preview(report: Dict[str, object]) -> str:
        offseason = report.get("offseason")
        data = offseason if isinstance(offseason, dict) else {}
        next_stage = str(data.get("next_stage_label") or "None")
        phase = str(data.get("phase") or "UNKNOWN")
        mode = (
            "Multi-owner"
            if bool(data.get("requires_commissioner_finance_review", False))
            else "Single-player"
        )
        return "\n".join(
            [
                "Saved Settings Workflow",
                "- Step 1: Configure modules/preset in this dialog, then Save.",
                "- Step 2: Run Offseason Finance Workflow in Season page during OFFSEASON/PRESEASON.",
                "- Step 3: Resolve GM Finance Queue decisions (multi-owner only).",
                "- Step 4: Finalize offseason checklist before owners resume transactions.",
                f"- Current phase: {phase} | Next checklist stage: {next_stage} | League mode: {mode}",
                "- Note: projection/alert preview reflects currently saved settings.",
            ]
        )

    @staticmethod
    def _format_projection_preview(report: Dict[str, object]) -> str:
        summary = report.get("summary")
        data = summary if isinstance(summary, dict) else {}
        surplus = report.get("top_surplus_teams")
        deficit = report.get("top_deficit_teams")
        surplus_rows = surplus if isinstance(surplus, list) else []
        deficit_rows = deficit if isinstance(deficit, list) else []
        lines = [
            "Projection Snapshot (Saved Config)",
            (
                f"- Teams: {int(data.get('team_count', 0) or 0)} | "
                f"Avg monthly net: ${int(data.get('average_projected_net', 0) or 0):,}"
            ),
            (
                f"- Total cash: ${int(data.get('total_cash_on_hand', 0) or 0):,} | "
                f"Total debt: ${int(data.get('total_debt', 0) or 0):,}"
            ),
            (
                f"- Negative net teams: {int(data.get('teams_negative_net', 0) or 0)} | "
                f"Cash-risk teams: {int(data.get('teams_cash_risk', 0) or 0)}"
            ),
            (
                f"- Over-threshold teams: {int(data.get('teams_over_threshold', 0) or 0)} | "
                f"Under-floor teams: {int(data.get('teams_under_floor', 0) or 0)}"
            ),
        ]
        if surplus_rows:
            top = surplus_rows[0]
            lines.append(
                (
                    "- Best projected net: "
                    f"{top.get('team_id', '--')} (${int(top.get('projected_net', 0) or 0):,})"
                )
            )
        if deficit_rows:
            bottom = deficit_rows[0]
            lines.append(
                (
                    "- Worst projected net: "
                    f"{bottom.get('team_id', '--')} (${int(bottom.get('projected_net', 0) or 0):,})"
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _format_alert_preview(alerts: list[Dict[str, str]]) -> str:
        if not alerts:
            return "No finance alerts."
        lines = ["Prioritized Alerts"]
        for alert in alerts[:6]:
            severity = str(alert.get("severity") or "info").strip().upper()
            title = str(alert.get("title") or "").strip()
            message = str(alert.get("message") or "").strip()
            next_step = str(alert.get("next_step") or "").strip()
            lines.append(f"- [{severity}] {title}: {message} Next: {next_step}")
        return "\n".join(lines)

    def _collect_modules(self) -> Dict[str, str]:
        modules: Dict[str, str] = {}
        for module, combo in self._module_combos.items():
            modules[module] = str(combo.currentData() or "off")
        return modules

    def _set_ai_tuning_values(self, values: Dict[str, object]) -> None:
        for key, field in self._ai_tuning_inputs.items():
            default_value = DEFAULT_FINANCE_AI_TUNING.get(key, "")
            value = values.get(key, default_value)
            if isinstance(default_value, int):
                text = str(int(round(float(value))))
            else:
                text = f"{float(value):.2f}"
            field.setText(text)

    def _collect_ai_tuning(self) -> Dict[str, object]:
        tuning: Dict[str, object] = {}
        for key, field in self._ai_tuning_inputs.items():
            text = field.text().strip()
            default_value = DEFAULT_FINANCE_AI_TUNING.get(key)
            if isinstance(default_value, int):
                try:
                    tuning[key] = int(round(float(text)))
                except Exception:
                    tuning[key] = int(default_value)
            else:
                try:
                    tuning[key] = float(text)
                except Exception:
                    tuning[key] = float(default_value or 0.0)
        return tuning

    def _save(self) -> None:
        preset = self._preset_value()
        if preset == PRESET_OFF:
            apply_financial_preset(PRESET_OFF)
            self.accept()
            return

        update_financial_settings(
            enabled=self.enabled_checkbox.isChecked(),
            preset=preset,
            enforcement_mode=str(self.enforcement_combo.currentData() or ENFORCEMENT_WARN),
            modules=self._collect_modules(),
            finance_ai_tuning=self._collect_ai_tuning(),
        )
        self.accept()


__all__ = ["FinancialSettingsDialog"]
