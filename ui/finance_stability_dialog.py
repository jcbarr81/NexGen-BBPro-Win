"""Dialog for running finance stability simulations and reviewing results."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from services.finance_stability import (
    CORE_COMPARISON_PRESETS,
    DEFAULT_STABILITY_GUARDRAILS,
    run_finance_stability_preset_comparison,
)
from ui.export_dialogs import show_export_success_dialog
from .components import ActionButtonPanel
from utils.path_utils import get_data_dir


class FinanceStabilityDialog(QDialog):
    """Admin tool to run and export multi-season finance stability reports."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Finance Stability Simulation")
        self.resize(820, 640)
        self._last_result: Dict[str, Any] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        description = QLabel(
            "Run a multi-season CPU finance simulation and evaluate stability guardrails "
            "(debt, cash, unsigned free agents, payroll spread, star retention)."
        )
        description.setWordWrap(True)
        root.addWidget(description)

        controls = QGroupBox("Simulation Settings")
        grid = QGridLayout(controls)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("Seasons"), 0, 0)
        self.seasons_input = QSpinBox()
        self.seasons_input.setRange(1, 50)
        self.seasons_input.setValue(10)
        grid.addWidget(self.seasons_input, 0, 1)

        grid.addWidget(QLabel("Preset"), 0, 2)
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Current League Preset (Recommended)", "__current__")
        self.preset_combo.addItem("Simple", "simple")
        self.preset_combo.addItem("Standard", "standard")
        self.preset_combo.addItem("MLB-Like", "mlb_like")
        self.preset_combo.setCurrentIndex(0)
        grid.addWidget(self.preset_combo, 0, 3)

        grid.addWidget(QLabel("Seed"), 1, 0)
        self.seed_input = QSpinBox()
        self.seed_input.setRange(0, 2_000_000_000)
        self.seed_input.setValue(42)
        grid.addWidget(self.seed_input, 1, 1)

        grid.addWidget(QLabel("Max FA Rounds (0 = Auto)"), 1, 2)
        self.max_fa_rounds_input = QSpinBox()
        self.max_fa_rounds_input.setRange(0, 20)
        self.max_fa_rounds_input.setValue(0)
        grid.addWidget(self.max_fa_rounds_input, 1, 3)

        self.strict_checkbox = QCheckBox("Strict Mode (consider guardrail failures as errors)")
        grid.addWidget(self.strict_checkbox, 2, 0, 1, 4)
        self.include_current_compare_checkbox = QCheckBox("Include current league preset in comparison")
        self.include_current_compare_checkbox.setChecked(True)
        grid.addWidget(self.include_current_compare_checkbox, 3, 0, 1, 4)

        root.addWidget(controls)

        guardrails = QGroupBox("Guardrail Thresholds")
        threshold_grid = QGridLayout(guardrails)
        threshold_grid.setContentsMargins(12, 12, 12, 12)
        threshold_grid.setHorizontalSpacing(14)
        threshold_grid.setVerticalSpacing(8)

        self._threshold_inputs: Dict[str, QSpinBox] = {}
        threshold_fields = [
            ("max_distressed_debt_ratio", "Max Distressed Debt %"),
            ("max_negative_cash_ratio", "Max Negative Cash %"),
            ("max_unsigned_ratio", "Max Unsigned Player %"),
            ("max_payroll_spread_ratio", "Max Payroll Spread x100"),
            ("min_star_retention_rate", "Min Star Retention %"),
        ]
        for row, (key, label) in enumerate(threshold_fields):
            threshold_grid.addWidget(QLabel(label), row, 0)
            spin = QSpinBox()
            if key == "max_payroll_spread_ratio":
                spin.setRange(100, 5000)
                spin.setValue(int(round(DEFAULT_STABILITY_GUARDRAILS[key] * 100)))
            else:
                spin.setRange(0, 100)
                spin.setValue(int(round(DEFAULT_STABILITY_GUARDRAILS[key] * 100)))
            self._threshold_inputs[key] = spin
            threshold_grid.addWidget(spin, row, 1)

        root.addWidget(guardrails)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Run a simulation to view summary metrics and guardrail checks.")
        root.addWidget(self.output, stretch=1)

        button_row = ActionButtonPanel(
            min_columns=1,
            max_columns=3,
            target_button_width=200,
            min_button_width=145,
            max_button_width=235,
        )
        self.run_button = QPushButton("Run Simulation")
        self.run_button.setObjectName("Primary")
        self.compare_button = QPushButton("Compare Core Presets")
        self.export_json_button = QPushButton("Export JSON")
        self.export_csv_button = QPushButton("Export CSV")
        self.close_button = QPushButton("Close")
        button_row.add_button(self.run_button)
        button_row.add_button(self.compare_button)
        button_row.add_button(self.export_json_button)
        button_row.add_button(self.export_csv_button)
        button_row.add_button(self.close_button)
        root.addWidget(button_row)

        self.run_button.clicked.connect(self._run_simulation)
        self.compare_button.clicked.connect(self._run_comparison)
        self.export_json_button.clicked.connect(self._export_json)
        self.export_csv_button.clicked.connect(self._export_csv)
        self.close_button.clicked.connect(self.reject)
        self._set_export_enabled(False)

    def _thresholds(self) -> Dict[str, float]:
        return {
            "max_distressed_debt_ratio": self._threshold_inputs["max_distressed_debt_ratio"].value() / 100.0,
            "max_negative_cash_ratio": self._threshold_inputs["max_negative_cash_ratio"].value() / 100.0,
            "max_unsigned_ratio": self._threshold_inputs["max_unsigned_ratio"].value() / 100.0,
            "max_payroll_spread_ratio": self._threshold_inputs["max_payroll_spread_ratio"].value() / 100.0,
            "min_star_retention_rate": self._threshold_inputs["min_star_retention_rate"].value() / 100.0,
        }

    def _run_simulation(self) -> None:
        self._set_run_buttons_enabled(False)
        self.output.setPlainText("Running simulation...")
        try:
            preset_token = str(self.preset_combo.currentData() or "__current__")
            comparison = run_finance_stability_preset_comparison(
                seasons=int(self.seasons_input.value()),
                data_dir=get_data_dir(),
                presets=[preset_token],
                seed=int(self.seed_input.value()),
                max_fa_rounds=(
                    int(self.max_fa_rounds_input.value())
                    if int(self.max_fa_rounds_input.value()) > 0
                    else None
                ),
                guardrails=self._thresholds(),
            )
            result = self._extract_single_result(comparison)
            self._last_result = result
            self._set_export_enabled(True)
            self._render_result(result)
            guardrails = result.get("guardrails")
            passed = bool(guardrails.get("passed", False)) if isinstance(guardrails, dict) else False
            if self.strict_checkbox.isChecked() and not passed:
                QMessageBox.warning(
                    self,
                    "Guardrails Failed",
                    "Finance stability guardrails failed in strict mode. Review report details.",
                )
        except Exception as exc:
            self._last_result = None
            self._set_export_enabled(False)
            self.output.setPlainText(f"Simulation failed: {exc}")
        finally:
            self._set_run_buttons_enabled(True)

    def _run_comparison(self) -> None:
        self._set_run_buttons_enabled(False)
        self.output.setPlainText("Running preset comparison...")
        try:
            presets = list(CORE_COMPARISON_PRESETS)
            if self.include_current_compare_checkbox.isChecked():
                presets.insert(0, "__current__")
            result = run_finance_stability_preset_comparison(
                seasons=int(self.seasons_input.value()),
                data_dir=get_data_dir(),
                presets=presets,
                seed=int(self.seed_input.value()),
                max_fa_rounds=(
                    int(self.max_fa_rounds_input.value())
                    if int(self.max_fa_rounds_input.value()) > 0
                    else None
                ),
                guardrails=self._thresholds(),
            )
            self._last_result = result
            self._set_export_enabled(True)
            self._render_result(result)
            passed = bool(result.get("all_passed", False))
            if self.strict_checkbox.isChecked() and not passed:
                QMessageBox.warning(
                    self,
                    "Guardrails Failed",
                    "One or more preset profiles failed guardrails in strict mode.",
                )
        except Exception as exc:
            self._last_result = None
            self._set_export_enabled(False)
            self.output.setPlainText(f"Comparison failed: {exc}")
        finally:
            self._set_run_buttons_enabled(True)

    def _render_result(self, result: Dict[str, Any]) -> None:
        if str(result.get("mode") or "").strip().lower() == "preset_comparison":
            self._render_comparison_result(result)
            return
        lines: list[str] = []
        lines.append("Finance Stability Simulation")
        lines.append(f"League: {result.get('league_id')}")
        lines.append(f"Seasons Run: {result.get('seasons_run')}")
        lines.append(f"Preset: {result.get('preset')}")
        lines.append("")
        guardrails = result.get("guardrails")
        if isinstance(guardrails, dict):
            checks = guardrails.get("checks")
            if isinstance(checks, list):
                for raw in checks:
                    check = raw if isinstance(raw, dict) else {}
                    state = "PASS" if bool(check.get("passed")) else "FAIL"
                    lines.append(
                        f"[{state}] {check.get('name')}: {check.get('value')} "
                        f"{check.get('comparator')} {check.get('threshold')}"
                    )
            lines.append("")
            lines.append(f"Guardrails: {'PASS' if bool(guardrails.get('passed')) else 'FAIL'}")
        self.output.setPlainText("\n".join(lines))

    def _render_comparison_result(self, result: Dict[str, Any]) -> None:
        lines: list[str] = []
        lines.append("Finance Stability Preset Comparison")
        lines.append(f"Seasons Requested: {result.get('seasons_requested')}")
        lines.append("")
        rows = result.get("results")
        entries = rows if isinstance(rows, list) else []
        for raw in entries:
            entry = raw if isinstance(raw, dict) else {}
            summary = entry.get("result")
            simulation = summary if isinstance(summary, dict) else {}
            guardrails = simulation.get("guardrails")
            guardrail_payload = guardrails if isinstance(guardrails, dict) else {}
            state = "PASS" if bool(entry.get("guardrails_passed", False)) else "FAIL"
            lines.append(
                f"[{state}] preset={entry.get('effective_preset')} "
                f"(requested={entry.get('preset')}) seasons={entry.get('seasons_run')}"
            )
            checks = guardrail_payload.get("checks")
            check_rows = checks if isinstance(checks, list) else []
            for raw_check in check_rows:
                check = raw_check if isinstance(raw_check, dict) else {}
                lines.append(
                    f"  - {check.get('name')}: {check.get('value')} "
                    f"{check.get('comparator')} {check.get('threshold')}"
                )
            lines.append("")
        lines.append(f"Overall: {'PASS' if bool(result.get('all_passed', False)) else 'FAIL'}")
        self.output.setPlainText("\n".join(lines))

    def _set_export_enabled(self, enabled: bool) -> None:
        self.export_json_button.setEnabled(enabled)
        self.export_csv_button.setEnabled(enabled)

    def _set_run_buttons_enabled(self, enabled: bool) -> None:
        self.run_button.setEnabled(enabled)
        self.compare_button.setEnabled(enabled)

    def _default_reports_dir(self) -> Path:
        return get_data_dir() / "reports"

    def _export_json(self) -> None:
        if not isinstance(self._last_result, dict):
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Finance Stability JSON",
            str(self._default_reports_dir() / "finance_stability.json"),
            "JSON Files (*.json)",
        )
        if not out_path:
            return
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._last_result, indent=2), encoding="utf-8")
        show_export_success_dialog(
            parent=self,
            title="Finance Stability Export",
            message=f"JSON report exported to:\n{path}",
            export_path=path,
        )

    def _export_csv(self) -> None:
        if not isinstance(self._last_result, dict):
            return
        season_metrics = self._flatten_season_rows(self._last_result)
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Finance Stability CSV",
            str(self._default_reports_dir() / "finance_stability.csv"),
            "CSV Files (*.csv)",
        )
        if not out_path:
            return
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        headers = sorted({key for row in season_metrics if isinstance(row, dict) for key in row.keys()})
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for raw in season_metrics:
                row = raw if isinstance(raw, dict) else {}
                writer.writerow({key: row.get(key, "") for key in headers})
        show_export_success_dialog(
            parent=self,
            title="Finance Stability Export",
            message=f"CSV report exported to:\n{path}",
            export_path=path,
        )

    def _flatten_season_rows(self, result: Dict[str, Any]) -> list[Dict[str, Any]]:
        mode = str(result.get("mode") or "").strip().lower()
        if mode != "preset_comparison":
            rows = result.get("season_metrics")
            return [row for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict)]
        flattened: list[Dict[str, Any]] = []
        profiles = result.get("results")
        entries = profiles if isinstance(profiles, list) else []
        for raw in entries:
            entry = raw if isinstance(raw, dict) else {}
            summary = entry.get("result")
            simulation = summary if isinstance(summary, dict) else {}
            season_rows = simulation.get("season_metrics")
            for season in (season_rows if isinstance(season_rows, list) else []):
                if not isinstance(season, dict):
                    continue
                row = dict(season)
                row["requested_preset"] = entry.get("preset")
                row["effective_preset"] = entry.get("effective_preset")
                row["guardrails_passed"] = entry.get("guardrails_passed")
                flattened.append(row)
        return flattened

    def _extract_single_result(self, comparison: Dict[str, Any]) -> Dict[str, Any]:
        rows = comparison.get("results")
        entries = rows if isinstance(rows, list) else []
        if not entries:
            return {"guardrails": {"passed": False, "checks": []}}
        first = entries[0]
        entry = first if isinstance(first, dict) else {}
        result = entry.get("result")
        simulation = result if isinstance(result, dict) else {}
        if simulation and str(entry.get("preset")) == "__current__":
            simulation = dict(simulation)
            simulation["preset"] = f"current:{entry.get('effective_preset')}"
        return simulation


__all__ = ["FinanceStabilityDialog"]
