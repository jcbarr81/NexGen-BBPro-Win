from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QScrollArea,
    QWidget,
)

from playbalance.team_name_generator import random_team
from ui.window_utils import untrack_on_top


class TeamEntryDialog(QDialog):
    """Dialog for entering team cities and nicknames."""

    def __init__(self, divisions, teams_per_div, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Teams")
        self.resize(1080, 700)
        self._inputs = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        instructions = QLabel(
            "Enter team city and nickname for each division. "
            "Large leagues can scroll horizontally across division columns."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, stretch=1)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        for div in divisions:
            group = QGroupBox(f"{div} Division")
            group_layout = QGridLayout(group)
            group_layout.setContentsMargins(10, 10, 10, 10)
            group_layout.setHorizontalSpacing(8)
            group_layout.setVerticalSpacing(6)
            group.setMinimumWidth(420)
            group_layout.setColumnStretch(1, 1)
            group_layout.setColumnStretch(2, 1)

            self._inputs[div] = []
            for i in range(teams_per_div):
                row_label = QLabel(f"Team {i + 1}")
                city_edit = QLineEdit()
                city_edit.setPlaceholderText("City")
                city_edit.setMinimumWidth(120)
                name_edit = QLineEdit()
                name_edit.setPlaceholderText("Nickname")
                name_edit.setMinimumWidth(140)
                random_btn = QPushButton("Randomize")
                random_btn.setMinimumWidth(96)

                group_layout.addWidget(row_label, i, 0)
                group_layout.addWidget(city_edit, i, 1)
                group_layout.addWidget(name_edit, i, 2)
                group_layout.addWidget(random_btn, i, 3)

                self._inputs[div].append((city_edit, name_edit))
                random_btn.clicked.connect(
                    lambda _, c=city_edit, n=name_edit: self._random_fill(c, n)
                )

            content_layout.addWidget(group)

        content_layout.addStretch(1)
        scroll.setWidget(content)

        btn_row = QHBoxLayout()
        random_all_btn = QPushButton("Randomize All")
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(random_all_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        random_all_btn.clicked.connect(self._random_fill_all)
        save_btn.clicked.connect(self._handle_save)
        cancel_btn.clicked.connect(self.reject)

    def _random_fill(self, city_edit: QLineEdit, name_edit: QLineEdit) -> None:
        """Populate the provided fields with a random team name."""
        try:
            city, nickname = random_team()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Names Exhausted", str(exc))
            return
        city_edit.setText(city)
        name_edit.setText(nickname)

    def _random_fill_all(self) -> None:
        """Populate all team fields with random names."""
        for fields in self._inputs.values():
            for city_edit, name_edit in fields:
                try:
                    city, nickname = random_team()
                except RuntimeError as exc:
                    QMessageBox.warning(self, "Names Exhausted", str(exc))
                    return
                city_edit.setText(city)
                name_edit.setText(nickname)

    def _handle_save(self):
        for fields in self._inputs.values():
            for city, name in fields:
                if not city.text().strip() or not name.text().strip():
                    QMessageBox.warning(self, "Error", "All fields must be filled.")
                    return
        self.accept()
        self.deleteLater()

    def accept(self) -> None:  # type: ignore[override]
        untrack_on_top(self)
        super().accept()

    def reject(self) -> None:  # type: ignore[override]
        untrack_on_top(self)
        super().reject()

    def get_structure(self):
        structure = {}
        for div, fields in self._inputs.items():
            teams = []
            for city, name in fields:
                teams.append((city.text().strip(), name.text().strip()))
            structure[div] = teams
        return structure
