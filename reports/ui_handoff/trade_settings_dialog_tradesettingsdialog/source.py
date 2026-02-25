"""Dialog for configuring league-wide trade settings."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from services.trade_settings import (
    MAX_ALLOWED_PICK_TRADE_YEARS,
    MIN_ALLOWED_PICK_TRADE_YEARS,
    load_trade_settings,
    update_trade_settings,
)


class TradeSettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trade Settings")
        self.resize(460, 240)

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

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.close_button = QPushButton("Close")
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.enable_trading_checkbox.toggled.connect(self._sync_enabled_state)
        self.enable_pick_trading_checkbox.toggled.connect(self._sync_enabled_state)
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
        self.max_years_spin.setValue(settings.max_pick_trade_years)
        self._sync_enabled_state()

    def _sync_enabled_state(self) -> None:
        trading_on = self.enable_trading_checkbox.isChecked()
        picks_on = self.enable_pick_trading_checkbox.isChecked()
        self.enable_pick_trading_checkbox.setEnabled(trading_on)
        self.require_commissioner_checkbox.setEnabled(trading_on)
        self.max_years_spin.setEnabled(trading_on and picks_on)

    def _save(self) -> None:
        update_trade_settings(
            trades_enabled=self.enable_trading_checkbox.isChecked(),
            draft_pick_trading_enabled=self.enable_pick_trading_checkbox.isChecked(),
            require_commissioner_approval=self.require_commissioner_checkbox.isChecked(),
            max_pick_trade_years=int(self.max_years_spin.value()),
        )
        self.accept()


__all__ = ["TradeSettingsDialog"]
