from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton

from .components import ActionButtonPanel, Card, section_title


class TransactionsPage(QWidget):
    """Page allowing users to manage team transactions."""

    def __init__(self, dashboard):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        card = Card()
        card.layout().addWidget(section_title("Transactions"))
        action_panel = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        btn_view = QPushButton("View Transactions", objectName="Primary")
        btn_view.clicked.connect(dashboard.open_transactions_page)
        action_panel.add_button(btn_view)

        btn_trade = QPushButton("Trade Players", objectName="Primary")
        btn_trade.clicked.connect(dashboard.open_trade_dialog)
        action_panel.add_button(btn_trade)

        btn_free = QPushButton("Sign Free Agent", objectName="Primary")
        btn_free.clicked.connect(dashboard.sign_free_agent)
        action_panel.add_button(btn_free)

        card.layout().addWidget(action_panel)
        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()
