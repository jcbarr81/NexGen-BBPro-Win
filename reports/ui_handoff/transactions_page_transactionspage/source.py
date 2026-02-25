from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from .components import Card, section_title


class TransactionsPage(QWidget):
    """Page allowing users to manage team transactions."""

    def __init__(self, dashboard):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        card = Card()
        card.layout().addWidget(section_title("Transactions"))

        btn_view = QPushButton("View Transactions", objectName="Primary")
        btn_view.clicked.connect(dashboard.open_transactions_page)
        card.layout().addWidget(btn_view)

        btn_trade = QPushButton("Trade Players", objectName="Primary")
        btn_trade.clicked.connect(dashboard.open_trade_dialog)
        card.layout().addWidget(btn_trade)

        btn_free = QPushButton("Sign Free Agent", objectName="Primary")
        btn_free.clicked.connect(dashboard.sign_free_agent)
        card.layout().addWidget(btn_free)

        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()
