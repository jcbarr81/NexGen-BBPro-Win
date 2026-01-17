from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
)

from data.ballparks import BALLPARKS
from .park_selector_dialog import ParkSelectorDialog


class TeamSettingsDialog(QDialog):
    """Dialog allowing an owner to configure basic team properties."""

    def __init__(self, team, parent=None):
        super().__init__(parent)
        self.team = team
        self.setWindowTitle("Team Settings")

        layout = QVBoxLayout()

        # Colors
        color_row = QHBoxLayout()
        from PyQt6.QtCore import QRegularExpression
        from PyQt6.QtGui import QRegularExpressionValidator

        hex_regex = QRegularExpression(r"#[0-9A-Fa-f]{6}")
        validator = QRegularExpressionValidator(hex_regex, self)

        color_row.addWidget(QLabel("Primary Color:"))
        self.primary_edit = QLineEdit(team.primary_color)
        self.primary_edit.setValidator(validator)
        color_row.addWidget(self.primary_edit)
        primary_btn = QPushButton("Choose")
        primary_btn.clicked.connect(lambda: self.choose_color(self.primary_edit))
        color_row.addWidget(primary_btn)

        color_row.addWidget(QLabel("Secondary Color:"))
        self.secondary_edit = QLineEdit(team.secondary_color)
        self.secondary_edit.setValidator(validator)
        color_row.addWidget(self.secondary_edit)
        secondary_btn = QPushButton("Choose")
        secondary_btn.clicked.connect(lambda: self.choose_color(self.secondary_edit))
        color_row.addWidget(secondary_btn)

        layout.addLayout(color_row)

        # Stadium selection
        stadium_row = QHBoxLayout()
        stadium_row.addWidget(QLabel("Stadium:"))
        self.stadium_combo = QComboBox()
        self.stadium_combo.setEditable(True)
        self.stadium_combo.addItems(sorted(BALLPARKS))
        if team.stadium:
            self.stadium_combo.setCurrentText(team.stadium)
        stadium_row.addWidget(self.stadium_combo)

        browse_btn = QPushButton("Browse MLB Parks...")
        browse_btn.clicked.connect(self._open_park_selector)
        stadium_row.addWidget(browse_btn)
        layout.addLayout(stadium_row)

        self.stadium_label = QLabel()
        self._update_stadium_label(self.stadium_combo.currentText())
        self.stadium_combo.currentTextChanged.connect(self._update_stadium_label)
        layout.addWidget(self.stadium_label)

        # Action buttons
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)

    def choose_color(self, edit):
        """Open a color dialog and set the selected color on the given line edit."""
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor

        current = edit.text() or "#ffffff"
        color = QColorDialog.getColor(QColor(current), self, "Select Color")
        if color.isValid():
            edit.setText(color.name())

    def get_settings(self):
        primary = self.primary_edit.text().strip()
        secondary = self.secondary_edit.text().strip()
        return {
            "primary_color": primary if self.primary_edit.hasAcceptableInput() else "",
            "secondary_color": secondary if self.secondary_edit.hasAcceptableInput() else "",
            "stadium": self.stadium_combo.currentText(),
        }

    def _open_park_selector(self):
        dlg = ParkSelectorDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.selected_name:
            # Set the chosen park NAME as the stadium string
            self.stadium_combo.setCurrentText(dlg.selected_name)

    def _update_stadium_label(self, text: str) -> None:
        name = (text or "").strip()
        if name:
            self.stadium_label.setText(f"Current MLB park: {name}")
        else:
            self.stadium_label.setText("Current MLB park: Not set")

