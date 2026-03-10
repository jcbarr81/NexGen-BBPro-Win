from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton

from .components import ActionButtonPanel, Card, section_title


class TeamPage(QWidget):
    """Page for viewing team-specific information."""

    def __init__(self, dashboard):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        card = Card()
        card.layout().addWidget(section_title("Team"))
        action_panel = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        btn_sched = QPushButton("Team Schedule", objectName="Primary")
        btn_sched.clicked.connect(dashboard.open_team_schedule_window)
        action_panel.add_button(btn_sched)

        btn_stats = QPushButton("Team Stats", objectName="Primary")
        btn_stats.clicked.connect(dashboard.open_team_stats_window)
        action_panel.add_button(btn_stats)

        btn_settings = QPushButton("Team Settings", objectName="Primary")
        btn_settings.clicked.connect(dashboard.open_team_settings_dialog)
        action_panel.add_button(btn_settings)

        card.layout().addWidget(action_panel)
        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()
