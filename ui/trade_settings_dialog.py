"""Dialog for configuring league-wide trade settings."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from .components import ActionButtonPanel

from services.trade_settings import (
    CPU_PROPOSAL_CADENCE_VALUES,
    MAX_ALLOWED_PICK_TRADE_YEARS,
    MIN_ALLOWED_PICK_TRADE_YEARS,
    load_trade_settings,
    update_trade_settings,
)


class TradeSettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trade Settings")
        self.resize(500, 280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        desc = QLabel(
            "Configure league-wide trade permissions. "
            "Changes apply to all owners immediately."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.enable_trading_checkbox = QCheckBox("Enable player trading")
        layout.addWidget(self.enable_trading_checkbox)

        self.enable_pick_trading_checkbox = QCheckBox("Allow trading draft picks")
        layout.addWidget(self.enable_pick_trading_checkbox)

        self.require_commissioner_checkbox = QCheckBox(
            "Require commissioner approval before executing accepted trades"
        )
        layout.addWidget(self.require_commissioner_checkbox)

        self.cpu_initiated_checkbox = QCheckBox(
            "Allow CPU-initiated trade offers (counters/proactive)"
        )
        layout.addWidget(self.cpu_initiated_checkbox)

        cadence_row = QHBoxLayout()
        cadence_row.addWidget(QLabel("CPU proactive proposal cadence:"))
        self.cpu_proposal_cadence_combo = QComboBox()
        self.cpu_proposal_cadence_combo.addItem("Off", "off")
        self.cpu_proposal_cadence_combo.addItem("Low", "low")
        self.cpu_proposal_cadence_combo.addItem("Normal", "normal")
        self.cpu_proposal_cadence_combo.addItem("High", "high")
        cadence_row.addWidget(self.cpu_proposal_cadence_combo)
        cadence_row.addStretch(1)
        layout.addLayout(cadence_row)

        years_row = QHBoxLayout()
        years_row.addWidget(QLabel("Maximum pick trade years out:"))
        self.max_years_spin = QSpinBox()
        self.max_years_spin.setRange(
            MIN_ALLOWED_PICK_TRADE_YEARS,
            MAX_ALLOWED_PICK_TRADE_YEARS,
        )
        years_row.addWidget(self.max_years_spin)
        years_row.addStretch(1)
        layout.addLayout(years_row)

        button_row = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=200,
            min_button_width=150,
            max_button_width=230,
        )
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.close_button = QPushButton("Close")
        button_row.add_buttons([self.save_button, self.close_button])
        layout.addWidget(button_row)

        self.enable_trading_checkbox.toggled.connect(self._sync_enabled_state)
        self.enable_pick_trading_checkbox.toggled.connect(self._sync_enabled_state)
        self.cpu_initiated_checkbox.toggled.connect(self._sync_enabled_state)
        self.save_button.clicked.connect(self._save)
        self.close_button.clicked.connect(self.reject)

        self._load()

    def _load(self) -> None:
        settings = load_trade_settings()
        self.enable_trading_checkbox.setChecked(settings.trades_enabled)
        self.enable_pick_trading_checkbox.setChecked(
            settings.draft_pick_trading_enabled
        )
        self.require_commissioner_checkbox.setChecked(
            settings.require_commissioner_approval
        )
        self.cpu_initiated_checkbox.setChecked(
            settings.cpu_initiated_trades_enabled
        )
        cadence = str(settings.cpu_proposal_cadence or "").strip().lower()
        if cadence not in CPU_PROPOSAL_CADENCE_VALUES:
            cadence = "normal"
        self.cpu_proposal_cadence_combo.setCurrentIndex(
            max(
                0,
                self.cpu_proposal_cadence_combo.findData(cadence),
            )
        )
        self.max_years_spin.setValue(settings.max_pick_trade_years)
        self._sync_enabled_state()

    def _sync_enabled_state(self) -> None:
        trading_on = self.enable_trading_checkbox.isChecked()
        picks_on = self.enable_pick_trading_checkbox.isChecked()
        cpu_on = self.cpu_initiated_checkbox.isChecked()
        self.enable_pick_trading_checkbox.setEnabled(trading_on)
        self.require_commissioner_checkbox.setEnabled(trading_on)
        self.cpu_initiated_checkbox.setEnabled(trading_on)
        self.cpu_proposal_cadence_combo.setEnabled(trading_on and cpu_on)
        self.max_years_spin.setEnabled(trading_on and picks_on)

    def _save(self) -> None:
        update_trade_settings(
            trades_enabled=self.enable_trading_checkbox.isChecked(),
            draft_pick_trading_enabled=self.enable_pick_trading_checkbox.isChecked(),
            require_commissioner_approval=self.require_commissioner_checkbox.isChecked(),
            cpu_initiated_trades_enabled=self.cpu_initiated_checkbox.isChecked(),
            cpu_proposal_cadence=str(
                self.cpu_proposal_cadence_combo.currentData() or "normal"
            ),
            max_pick_trade_years=int(self.max_years_spin.value()),
        )
        self.accept()


__all__ = ["TradeSettingsDialog"]
