from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from .components import ActionButtonPanel

from services.gm_finance_queue import (
    apply_approved_queue_decisions,
    list_pending_queue_decisions,
    set_queue_review_status,
)


class GmFinanceQueueDialog(QDialog):
    """Commissioner review UI for pending owner GM-finance queue decisions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("GM Finance Queue Review")
        self.resize(980, 560)
        self._rows: list[dict[str, object]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.summary_label = QLabel(
            "Review pending owner finance queue decisions (arbitration + free agency)."
        )
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                "Team",
                "Queue",
                "Item ID",
                "Action",
                "Updated",
                "Notes",
                "Status",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, stretch=1)

        buttons = ActionButtonPanel(
            min_columns=1,
            max_columns=3,
            target_button_width=220,
            min_button_width=150,
            max_button_width=250,
        )
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.approve_button = QPushButton("Approve Selected")
        self.approve_button.clicked.connect(self._approve_selected)
        self.reject_button = QPushButton("Reject Selected")
        self.reject_button.setObjectName("Danger")
        self.reject_button.clicked.connect(self._reject_selected)
        self.apply_button = QPushButton("Apply Approved Decisions")
        self.apply_button.clicked.connect(self._apply_approved)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons.add_button(self.refresh_button)
        buttons.add_button(self.approve_button)
        buttons.add_button(self.reject_button)
        buttons.add_button(self.apply_button)
        buttons.add_button(self.close_button)
        root.addWidget(buttons)

        self.refresh()

    def _apply_approved(self) -> None:
        summary = apply_approved_queue_decisions()
        applied = int(summary.get("applied", 0) or 0)
        skipped = int(summary.get("skipped", 0) or 0)
        QMessageBox.information(
            self,
            "GM Finance Queue",
            f"Applied approved decisions: {applied}\nSkipped: {skipped}",
        )
        self.refresh()

    def refresh(self) -> None:
        self._rows = list_pending_queue_decisions()
        self.table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            self.table.setItem(
                row_index, 0, QTableWidgetItem(str(row.get("team_id") or ""))
            )
            self.table.setItem(
                row_index, 1, QTableWidgetItem(str(row.get("queue_type") or ""))
            )
            self.table.setItem(
                row_index, 2, QTableWidgetItem(str(row.get("item_id") or ""))
            )
            self.table.setItem(
                row_index, 3, QTableWidgetItem(str(row.get("action") or ""))
            )
            self.table.setItem(
                row_index, 4, QTableWidgetItem(str(row.get("updated_at") or ""))
            )
            self.table.setItem(
                row_index, 5, QTableWidgetItem(str(row.get("notes") or ""))
            )
            self.table.setItem(
                row_index, 6, QTableWidgetItem(str(row.get("review_status") or ""))
            )

        if self._rows:
            self.summary_label.setText(
                f"Pending GM finance decisions: {len(self._rows)}"
            )
        else:
            self.summary_label.setText("No pending GM finance decisions.")

    def _selected_decision(self) -> dict[str, object] | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def _approve_selected(self) -> None:
        decision = self._selected_decision()
        if decision is None:
            QMessageBox.information(
                self,
                "GM Finance Queue",
                "Select a pending decision to approve.",
            )
            return
        updated = set_queue_review_status(
            str(decision.get("team_id") or ""),
            queue_type=str(decision.get("queue_type") or ""),
            item_id=str(decision.get("item_id") or ""),
            review_status="approved_commissioner",
            notes="Approved by commissioner",
        )
        if updated is None:
            QMessageBox.warning(
                self,
                "GM Finance Queue",
                "Unable to update selected decision.",
            )
            return
        self.refresh()

    def _reject_selected(self) -> None:
        decision = self._selected_decision()
        if decision is None:
            QMessageBox.information(
                self,
                "GM Finance Queue",
                "Select a pending decision to reject.",
            )
            return
        updated = set_queue_review_status(
            str(decision.get("team_id") or ""),
            queue_type=str(decision.get("queue_type") or ""),
            item_id=str(decision.get("item_id") or ""),
            review_status="rejected_commissioner",
            notes="Rejected by commissioner",
        )
        if updated is None:
            QMessageBox.warning(
                self,
                "GM Finance Queue",
                "Unable to update selected decision.",
            )
            return
        self.refresh()


__all__ = ["GmFinanceQueueDialog"]
