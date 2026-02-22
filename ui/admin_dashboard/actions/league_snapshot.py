"""League snapshot export actions for the admin dashboard."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from services.league_snapshot import export_league_snapshot
from ..context import DashboardContext


class _UiDispatcher(QObject):
    """Thread-safe bridge to queue callables on the GUI thread."""

    trigger = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.trigger.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, callback: object) -> None:
        try:
            if callable(callback):
                callback()
        except Exception:
            pass


_DISPATCHER = _UiDispatcher()


def _schedule(callback) -> None:
    app = QApplication.instance()
    if app is None:
        if callable(callback):
            callback()
        return
    _DISPATCHER.trigger.emit(callback)


def export_league_snapshot_action(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Export a league snapshot zip for distribution to owners."""

    progress_dialog: Optional[QProgressDialog] = None
    if parent is not None:
        progress_dialog = QProgressDialog(
            "Exporting league snapshot...", None, 0, 0, parent
        )
        progress_dialog.setWindowTitle("Export League Snapshot")
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setValue(0)
        progress_dialog.show()

    if context.show_toast:
        context.show_toast("info", "Exporting league snapshot...")

    def worker() -> dict[str, object]:
        try:
            result = export_league_snapshot()
            return result
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
                QMessageBox.warning(parent, "Export League Snapshot", str(message))
            if context.show_toast:
                context.show_toast("error", str(message))
            return
        path = payload.get("path", "")
        message = f"Snapshot exported to:\n{path}\n\nSend this zip to your owners."
        if parent is not None:
            QMessageBox.information(parent, "Export League Snapshot", message)
        if context.show_toast:
            context.show_toast("success", "League snapshot exported.")

    future = context.run_async(worker)

    def handle_result(result_future) -> None:
        try:
            payload = result_future.result()
        except Exception as exc:
            payload = {"status": "error", "message": str(exc)}

        _schedule(lambda: finish(payload))

    if hasattr(future, "add_done_callback"):
        future.add_done_callback(handle_result)
        if context.register_cleanup and hasattr(future, "cancel"):
            context.register_cleanup(lambda fut=future: fut.cancel())
    else:
        if hasattr(future, "result"):
            handle_result(future)
        else:
            class _Immediate:
                def __init__(self, value):
                    self._value = value

                def result(self):
                    return self._value

            handle_result(_Immediate(future))


__all__ = ["export_league_snapshot_action"]
