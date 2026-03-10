"""Report export actions for the admin dashboard."""
from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QMessageBox, QWidget, QProgressDialog

from services.report_exporter import export_reports
from ui.export_dialogs import show_export_success_dialog
from ..context import DashboardContext


def export_reports_action(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
    *,
    export_format: str = "html",
) -> None:
    """Export league history + analytics reports in the background."""

    progress_dialog: Optional[QProgressDialog] = None
    if parent is not None:
        progress_dialog = QProgressDialog(
            "Exporting league reports...", None, 0, 0, parent
        )
        progress_dialog.setWindowTitle("Export Reports")
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setValue(0)
        progress_dialog.show()

    if context.show_toast:
        context.show_toast("info", "Exporting league reports in background...")

    def worker() -> dict[str, object]:
        try:
            normalized = str(export_format or "html").strip().lower()
            if normalized not in {"html", "csv"}:
                normalized = "html"
            result = export_reports(
                report_format=normalized,
                include_csv=(normalized == "csv"),
                include_pdf=(normalized == "csv"),
            )
            return {
                "status": "success",
                "output_dir": str(result.output_dir),
                "pdf_written": result.pdf_written,
                "reports_index_html": str(result.files.get("reports_index_html", "") or ""),
                "format": normalized,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def finish(payload: dict[str, object]) -> None:
        if progress_dialog is not None:
            try:
                progress_dialog.close()
            except Exception:
                pass
        status = payload.get("status")
        if status != "success":
            message = payload.get("message", "Export failed.")
            if parent is not None:
                QMessageBox.warning(parent, "Export Reports", str(message))
            if context.show_toast:
                context.show_toast("error", str(message))
            return
        output_dir = payload.get("output_dir", "")
        pdf_written = bool(payload.get("pdf_written"))
        reports_index_html = str(payload.get("reports_index_html", "") or "")
        normalized = str(payload.get("format", "html") or "html")
        note = "PDF summary generated." if pdf_written else "PDF summary skipped."
        if normalized == "html":
            message = (
                f"HTML reports exported to:\n{output_dir}\n\n"
                f"Landing page:\n{reports_index_html or '(not generated)'}"
            )
        else:
            message = f"CSV reports exported to:\n{output_dir}\n\n{note}"
        if normalized == "html" and reports_index_html:
            try:
                webbrowser.open(Path(reports_index_html).resolve().as_uri())
            except Exception:
                pass
        if parent is not None:
            show_export_success_dialog(
                parent=parent,
                title="Export Reports",
                message=message,
                export_path=str(output_dir),
            )
        if context.show_toast:
            if normalized == "html":
                context.show_toast("success", "HTML reports exported.")
            else:
                context.show_toast("success", "CSV reports exported.")

    future = context.run_async(worker)

    def handle_result(result_future) -> None:
        try:
            payload = result_future.result()
        except Exception as exc:
            payload = {"status": "error", "message": str(exc)}

        QTimer.singleShot(0, lambda: finish(payload))

    if hasattr(future, "add_done_callback"):
        future.add_done_callback(handle_result)
        if context.register_cleanup and hasattr(future, "cancel"):
            context.register_cleanup(lambda fut=future: fut.cancel())
    else:
        handle_result(future)


__all__ = ["export_reports_action"]
