"""Dialogs for selecting league presets and setup flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QDialogButtonBox,
)
from .components import ActionButtonPanel

from services.league_presets import (
    load_rule_presets,
    load_schedule_templates,
    load_quickstart_presets,
)


@dataclass(frozen=True)
class PresetOption:
    option_id: str
    name: str
    description: str
    details: str = ""


class LeagueSetupChoiceDialog(QDialog):
    """Prompt user to choose Quick-Start vs Custom league setup."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("League Setup")
        self.choice: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("How would you like to set up the new league-"))

        button_row = ActionButtonPanel(
            min_columns=1,
            max_columns=3,
            target_button_width=190,
            min_button_width=140,
            max_button_width=220,
        )
        quick_btn = QPushButton("Quick-Start")
        custom_btn = QPushButton("Custom Setup")
        cancel_btn = QPushButton("Cancel")
        button_row.add_buttons([quick_btn, custom_btn, cancel_btn])
        layout.addWidget(button_row)

        quick_btn.clicked.connect(self._choose_quickstart)
        custom_btn.clicked.connect(self._choose_custom)
        cancel_btn.clicked.connect(self.reject)

    def _choose_quickstart(self) -> None:
        self.choice = "quickstart"
        self.accept()

    def _choose_custom(self) -> None:
        self.choice = "custom"
        self.accept()


class PresetListDialog(QDialog):
    """Generic list dialog for selecting a preset option."""

    def __init__(
        self,
        title: str,
        options: Iterable[PresetOption],
        parent=None,
        *,
        default_id: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._options = list(options)
        self.selected_id: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        self.desc_label = QLabel("")
        self.desc_label.setWordWrap(True)
        layout.addWidget(self.desc_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            ok_button.setEnabled(False)

        for option in self._options:
            item = QListWidgetItem(option.name)
            item.setData(Qt.ItemDataRole.UserRole, option.option_id)
            self.list_widget.addItem(item)

        self.list_widget.currentItemChanged.connect(self._on_selection_changed)

        if default_id:
            self._select_default(default_id)

    def _select_default(self, default_id: str) -> None:
        for idx in range(self.list_widget.count()):
            item = self.list_widget.item(idx)
            if item and item.data(Qt.ItemDataRole.UserRole) == default_id:
                self.list_widget.setCurrentItem(item)
                break

    def _on_selection_changed(self, current, _previous) -> None:
        if current is None:
            return
        option_id = current.data(Qt.ItemDataRole.UserRole)
        self.selected_id = option_id
        for option in self._options:
            if option.option_id == option_id:
                details = option.description
                if option.details:
                    details = f"{details}\n{option.details}"
                self.desc_label.setText(details)
                break
        buttons = self.findChild(QDialogButtonBox)
        if buttons:
            ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
            if ok_button:
                ok_button.setEnabled(True)


def _rule_options(include_none: bool) -> list[PresetOption]:
    options = []
    if include_none:
        options.append(
            PresetOption(
                option_id="__none__",
                name="Keep Current Defaults",
                description="Do not apply a rule preset right now.",
            )
        )
    for preset in load_rule_presets():
        options.append(
            PresetOption(
                option_id=preset.preset_id,
                name=preset.name,
                description=preset.description,
            )
        )
    return options


def select_rule_preset(
    parent=None,
    *,
    include_none: bool = False,
    default_id: Optional[str] = None,
) -> Optional[str]:
    dialog = PresetListDialog(
        "Select Rule Preset",
        _rule_options(include_none),
        parent=parent,
        default_id=default_id,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.selected_id


def select_schedule_template(
    parent=None,
    *,
    default_id: Optional[str] = None,
) -> Optional[str]:
    options: list[PresetOption] = []
    for template in load_schedule_templates():
        detail = f"Games per team: {template.games_per_team}"
        if not template.include_all_star_break:
            detail += " - No All-Star break"
        options.append(
            PresetOption(
                option_id=template.template_id,
                name=template.name,
                description=template.description,
                details=detail,
            )
        )
    dialog = PresetListDialog(
        "Select Schedule Template",
        options,
        parent=parent,
        default_id=default_id,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.selected_id


def select_quickstart_preset(parent=None) -> Optional[str]:
    options: list[PresetOption] = []
    for preset in load_quickstart_presets():
        team_total = len(preset.divisions) * preset.teams_per_division
        detail = f"{team_total} teams - {len(preset.divisions)} divisions"
        options.append(
            PresetOption(
                option_id=preset.preset_id,
                name=preset.name,
                description=preset.description,
                details=detail,
            )
        )
    dialog = PresetListDialog(
        "Select Quick-Start Preset",
        options,
        parent=parent,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.selected_id


__all__ = [
    "LeagueSetupChoiceDialog",
    "select_rule_preset",
    "select_schedule_template",
    "select_quickstart_preset",
]
