"""Owner dialog to bundle and export change requests."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from services.change_requests import (
    add_request,
    create_request,
    export_cancel_request,
    export_request,
    list_requests,
    outbox_dir,
    update_request_status,
)
from utils.path_utils import get_data_dir


class ChangeRequestExportDialog(QDialog):
    def __init__(self, team_id: str, parent=None) -> None:
        super().__init__(parent)
        self.team_id = str(team_id)
        self.setWindowTitle("Submit Change Request")
        self.resize(520, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel(
            "Bundle your roster/lineup changes and export them for commissioner approval. "
            "Send the exported JSON file to your admin."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        owner_row = QHBoxLayout()
        owner_row.addWidget(QLabel("Owner Name"))
        self.owner_edit = QLineEdit(self.team_id)
        owner_row.addWidget(self.owner_edit, 1)
        layout.addLayout(owner_row)

        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("Optional note for the commissioner...")
        self.note_edit.setMaximumHeight(80)
        layout.addWidget(self.note_edit)

        self.roster_check = QCheckBox("Roster (ACT/AAA/LOW/DL/IR)")
        self.lineup_check = QCheckBox("Lineups (vs LHP/RHP)")
        self.pitching_check = QCheckBox("Pitching Staff Roles")
        self.depth_check = QCheckBox("Depth Chart")
        for box in (self.roster_check, self.lineup_check, self.pitching_check, self.depth_check):
            box.setChecked(True)
            layout.addWidget(box)

        layout.addWidget(QLabel("Previously Exported Requests"))
        self.request_list = QListWidget()
        layout.addWidget(self.request_list)

        button_row = QHBoxLayout()
        self.export_button = QPushButton("Export Request")
        self.cancel_button = QPushButton("Export Cancel")
        self.close_button = QPushButton("Close")
        self.export_button.setObjectName("Primary")
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.cancel_button)
        button_row.addStretch(1)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.export_button.clicked.connect(self._export_request)
        self.cancel_button.clicked.connect(self._export_cancel)
        self.close_button.clicked.connect(self.reject)

        self._refresh_requests()

    def _refresh_requests(self) -> None:
        self.request_list.clear()
        requests = list_requests(status="exported")
        for req in requests:
            if str(req.get("team_id")) != self.team_id:
                continue
            request_id = str(req.get("request_id") or "")
            summary = str(req.get("summary") or "")
            created = str(req.get("created_at") or "")
            label = f"{request_id} - {summary} ({created})"
            item = QListWidgetItem(label)
            item.setData(0x0100, request_id)
            self.request_list.addItem(item)

    def _export_request(self) -> None:
        files = self._collect_files()
        if not files:
            QMessageBox.warning(self, "Change Request", "No files found to export.")
            return
        owner_name = self.owner_edit.text().strip() or self.team_id
        summary = self._summary_label()
        note = self.note_edit.toPlainText().strip()
        try:
            request = create_request(
                team_id=self.team_id,
                owner_name=owner_name,
                files=files,
                summary=summary,
                note=note,
                status="exported",
            )
            add_request(request)
            export_path = export_request(request)
        except Exception as exc:
            QMessageBox.warning(self, "Change Request", f"Export failed: {exc}")
            return
        QMessageBox.information(
            self,
            "Change Request Exported",
            f"Exported to:\n{export_path}\n\nSend this file to your commissioner.",
        )
        self._refresh_requests()

    def _export_cancel(self) -> None:
        item = self.request_list.currentItem()
        if item is None:
            return
        request_id = item.data(0x0100)
        if not request_id:
            return
        owner_name = self.owner_edit.text().strip() or self.team_id
        try:
            export_path = export_cancel_request(
                request_id=str(request_id),
                team_id=self.team_id,
                owner_name=owner_name,
            )
            update_request_status(str(request_id), status="canceled", note="Owner canceled.")
        except Exception as exc:
            QMessageBox.warning(self, "Change Request", f"Cancel export failed: {exc}")
            return
        QMessageBox.information(
            self,
            "Cancel Exported",
            f"Cancel request exported to:\n{export_path}\n\nSend this file to your commissioner.",
        )
        self._refresh_requests()

    def _collect_files(self) -> list[dict]:
        data_dir = get_data_dir()
        files: list[dict] = []

        def add_file(rel_path: str) -> None:
            path = data_dir / rel_path
            if not path.exists():
                return
            files.append({"path": rel_path, "content": path.read_text(encoding="utf-8")})

        if self.roster_check.isChecked():
            add_file(f"rosters/{self.team_id}.csv")
        if self.pitching_check.isChecked():
            add_file(f"rosters/{self.team_id}_pitching.csv")
        if self.lineup_check.isChecked():
            add_file(f"lineups/{self.team_id}_vs_lhp.csv")
            add_file(f"lineups/{self.team_id}_vs_rhp.csv")
        if self.depth_check.isChecked():
            add_file(f"depth_charts/{self.team_id}.json")
        return files

    def _summary_label(self) -> str:
        parts: list[str] = []
        if self.roster_check.isChecked():
            parts.append("Roster")
        if self.lineup_check.isChecked():
            parts.append("Lineups")
        if self.pitching_check.isChecked():
            parts.append("Pitching Staff")
        if self.depth_check.isChecked():
            parts.append("Depth Chart")
        if not parts:
            return "Change Request"
        return " / ".join(parts)


__all__ = ["ChangeRequestExportDialog"]
