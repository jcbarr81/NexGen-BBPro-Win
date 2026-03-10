"""Almanac export actions for the admin dashboard."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from services.almanac_exporter import export_almanac
from ui.export_dialogs import show_export_success_dialog
from ..context import DashboardContext


def export_almanac_action(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Export the league Almanac HTML bundle in the background."""

    progress_dialog: Optional[QProgressDialog] = None
    if parent is not None:
        progress_dialog = QProgressDialog(
            "Exporting league almanac...", None, 0, 0, parent
        )
        progress_dialog.setWindowTitle("Export Almanac")
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setValue(0)
        progress_dialog.show()

    if context.show_toast:
        context.show_toast("info", "Exporting league almanac in background...")

    def worker() -> dict[str, object]:
        try:
            result = export_almanac()
            return {
                "status": "success",
                "output_dir": str(result.output_dir),
                "index_html": str(result.index_html),
                "season_count": len(result.season_ids),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def finish(payload: dict[str, object]) -> None:
        if progress_dialog is not None:
            try:
                progress_dialog.close()
            except Exception:
                pass
        if payload.get("status") != "success":
            message = str(payload.get("message") or "Almanac export failed.")
            if parent is not None:
                QMessageBox.warning(parent, "Export Almanac", message)
            if context.show_toast:
                context.show_toast("error", message)
            return

        output_dir = str(payload.get("output_dir") or "")
        index_html = str(payload.get("index_html") or "")
        season_count = int(payload.get("season_count") or 0)
        if index_html:
            try:
                webbrowser.open(Path(index_html).resolve().as_uri())
            except Exception:
                pass
        message = (
            f"League almanac exported to:\n{output_dir}\n\n"
            f"Landing page:\n{index_html or '(not generated)'}\n\n"
            f"Seasons indexed: {season_count}"
        )
        if parent is not None:
            show_export_success_dialog(
                parent=parent,
                title="Export Almanac",
                message=message,
                export_path=output_dir,
            )
        if context.show_toast:
            context.show_toast("success", "League almanac exported.")

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


__all__ = ["export_almanac_action"]
