"""Admin window for reviewing owner change requests."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)
from .components import ActionButtonPanel

from services.change_requests import (
    approve_request,
    import_requests_from_inbox,
    inbox_dir,
    list_requests,
    reject_request,
)


class ChangeRequestsWindow(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Requests")
        self.resize(920, 560)
        self._requests: dict[str, dict] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        intro = QLabel(
            "Owners export change request ZIP bundles. Place those files in the inbox "
            "folder below, then click Import Inbox to load them into the approval queue."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        inbox_path = str(inbox_dir())
        inbox_label = QLabel(f"Inbox Folder: {inbox_path}")
        inbox_label.setWordWrap(True)
        layout.addWidget(inbox_label)

        controls = QHBoxLayout()
        self.import_button = QPushButton("Import Inbox")
        self.refresh_button = QPushButton("Refresh")
        controls.addWidget(self.import_button)
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)

        controls.addWidget(QLabel("Show"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(
            [
                "Pending",
                "All",
                "Approved",
                "Applied",
                "Rejected",
                "Canceled",
                "Failed",
                "Exported",
            ]
        )
        controls.addWidget(self.filter_combo)
        layout.addLayout(controls)

        admin_row = QHBoxLayout()
        admin_row.addWidget(QLabel("Admin Name"))
        self.admin_name_edit = QLineEdit("Commissioner")
        admin_row.addWidget(self.admin_name_edit, 1)
        layout.addLayout(admin_row)

        main = QHBoxLayout()
        layout.addLayout(main, 1)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Team", "Owner", "Status", "Summary", "Created"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(5, 140)
        main.addWidget(self.table, 3)

        side = QVBoxLayout()
        main.addLayout(side, 2)
        side.addWidget(QLabel("Request Details"))
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        side.addWidget(self.details, 2)
        side.addWidget(QLabel("Admin Note (used when rejecting)"))
        self.note_edit = QTextEdit()
        self.note_edit.setMaximumHeight(90)
        side.addWidget(self.note_edit)

        action_row = ActionButtonPanel(
            min_columns=1,
            max_columns=3,
            target_button_width=210,
            min_button_width=150,
            max_button_width=240,
        )
        self.approve_button = QPushButton("Approve + Apply", objectName="Primary")
        self.reject_button = QPushButton("Reject")
        self.close_button = QPushButton("Close")
        action_row.add_buttons(
            [
                self.approve_button,
                self.reject_button,
                self.close_button,
            ]
        )
        layout.addWidget(action_row)

        self.import_button.clicked.connect(self._import_inbox)
        self.refresh_button.clicked.connect(self._refresh_requests)
        self.filter_combo.currentIndexChanged.connect(self._refresh_requests)
        self.table.itemSelectionChanged.connect(self._update_details)
        self.approve_button.clicked.connect(self._approve_selected)
        self.reject_button.clicked.connect(self._reject_selected)
        self.close_button.clicked.connect(self.reject)

        self._refresh_requests()

    def _selected_request_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _import_inbox(self) -> None:
        result = import_requests_from_inbox()
        errors = result.get("errors") or []
        message = (
            f"Imported: {result.get('imported', 0)}\n"
            f"Canceled: {result.get('canceled', 0)}\n"
            f"Failed: {result.get('failed', 0)}"
        )
        if errors:
            message += "\n\nErrors:\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "Import Complete", message)
        self._refresh_requests()

    def _refresh_requests(self) -> None:
        status = self.filter_combo.currentText().lower()
        status_filter = None if status == "all" else status
        rows = list_requests(status=status_filter)
        self._requests = {
            str(row.get("request_id")): row
            for row in rows
            if isinstance(row, dict)
        }
        self.table.setRowCount(0)
        for row in rows:
            req_id = str(row.get("request_id") or "")
            team_id = str(row.get("team_id") or "")
            owner_name = str(row.get("owner_name") or "")
            status_label = str(row.get("status") or "")
            summary = str(row.get("summary") or "")
            created = str(row.get("created_at") or "")
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            self._set_cell(row_idx, 0, req_id, req_id)
            self._set_cell(row_idx, 1, team_id)
            self._set_cell(row_idx, 2, owner_name)
            self._set_cell(row_idx, 3, status_label)
            self._set_cell(row_idx, 4, summary)
            self._set_cell(row_idx, 5, created)
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
        else:
            self._update_details()

    def _set_cell(self, row: int, col: int, text: str, req_id: str | None = None) -> None:
        item = QTableWidgetItem(text)
        if req_id and col == 0:
            item.setData(Qt.ItemDataRole.UserRole, req_id)
        self.table.setItem(row, col, item)

    def _update_details(self) -> None:
        req_id = self._selected_request_id()
        if not req_id:
            self.details.setPlainText("")
            return
        request = self._requests.get(req_id)
        if not request:
            self.details.setPlainText("")
            return
        lines = [
            f"Request ID: {req_id}",
            f"Team: {request.get('team_id', '')}",
            f"Owner: {request.get('owner_name', '')}",
            f"Status: {request.get('status', '')}",
            f"Created: {request.get('created_at', '')}",
            f"Updated: {request.get('updated_at', '')}",
            f"Summary: {request.get('summary', '')}",
        ]
        note = str(request.get("note") or "")
        if note:
            lines.append(f"Owner Note: {note}")
        admin_note = str(request.get("admin_note") or "")
        if admin_note:
            lines.append(f"Admin Note: {admin_note}")
        files = request.get("files") or []
        if files:
            lines.append("Files:")
            for entry in files:
                if not isinstance(entry, dict):
                    continue
                lines.append(f" - {entry.get('path', '')}")
        self.details.setPlainText("\n".join(lines))

    def _approve_selected(self) -> None:
        req_id = self._selected_request_id()
        if not req_id:
            return
        request = self._requests.get(req_id, {})
        if str(request.get("status")) not in {"pending", "approved"}:
            QMessageBox.information(
                self,
                "Change Request",
                "Only pending requests can be approved.",
            )
            return
        admin_name = self.admin_name_edit.text().strip() or "Commissioner"
        result = approve_request(req_id, applied_by=admin_name, auto_apply=True)
        if result.get("status") == "applied":
            QMessageBox.information(
                self,
                "Change Request",
                "Request approved and applied.",
            )
        else:
            QMessageBox.warning(
                self,
                "Change Request",
                f"Unable to apply request: {result}",
            )
        self._refresh_requests()

    def _reject_selected(self) -> None:
        req_id = self._selected_request_id()
        if not req_id:
            return
        request = self._requests.get(req_id, {})
        if str(request.get("status")) not in {"pending", "approved"}:
            QMessageBox.information(
                self,
                "Change Request",
                "Only pending requests can be rejected.",
            )
            return
        admin_name = self.admin_name_edit.text().strip() or "Commissioner"
        note = self.note_edit.toPlainText().strip()
        result = reject_request(req_id, note=note, applied_by=admin_name)
        if result.get("status") == "updated":
            QMessageBox.information(
                self,
                "Change Request",
                "Request rejected.",
            )
        else:
            QMessageBox.warning(
                self,
                "Change Request",
                f"Unable to reject request: {result}",
            )
        self._refresh_requests()


__all__ = ["ChangeRequestsWindow"]
