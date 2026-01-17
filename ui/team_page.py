from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from .components import Card, section_title


class TeamPage(QWidget):
    """Page for viewing team-specific information."""

    def __init__(self, dashboard):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        card = Card()
        card.layout().addWidget(section_title("Team"))

        btn_sched = QPushButton("Team Schedule", objectName="Primary")
        btn_sched.clicked.connect(dashboard.open_team_schedule_window)
        card.layout().addWidget(btn_sched)

        btn_stats = QPushButton("Team Stats", objectName="Primary")
        btn_stats.clicked.connect(dashboard.open_team_stats_window)
        card.layout().addWidget(btn_stats)

        btn_settings = QPushButton("Team Settings", objectName="Primary")
        btn_settings.clicked.connect(dashboard.open_team_settings_dialog)
        card.layout().addWidget(btn_settings)

        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()
