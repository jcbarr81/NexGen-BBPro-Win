"""Asset generation actions for the admin dashboard."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget, QProgressDialog

from utils.avatar_generator import generate_player_avatars
from utils.logo_generator import generate_team_logos
from utils.openai_client import (
    CLIENT_STATUS_INIT_FAILED,
    CLIENT_STATUS_MISSING_DEPENDENCY,
    get_client_status,
    get_client_status_message,
)

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
            # Swallow exceptions to avoid crashing the GUI thread.
            pass


_DISPATCHER = _UiDispatcher()


def _schedule(callback) -> None:
    app = QApplication.instance()
    if app is None:
        if callable(callback):
            callback()
        return
    _DISPATCHER.trigger.emit(callback)


def generate_team_logos_action(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Generate team logos on a background worker."""

    status_code = get_client_status()
    status_message = get_client_status_message()

    if status_code in (
        CLIENT_STATUS_MISSING_DEPENDENCY,
        CLIENT_STATUS_INIT_FAILED,
    ):
        message = status_message or (
            "OpenAI image generation is unavailable because the OpenAI "
            "Python package is not installed."
            if status_code == CLIENT_STATUS_MISSING_DEPENDENCY
            else "OpenAI client could not be initialised. Check your API key "
            "and network connection."
        )
        if context.show_toast:
            context.show_toast("error", message)
        target_parent = parent or QApplication.activeWindow()
        if target_parent is not None:
            QMessageBox.warning(
                target_parent,
                "OpenAI Not Available",
                message,
            )
        return

    if context.show_toast:
        context.show_toast("info", "Generating team logos in background...")

    progress_state: dict[str, object] = {
        "dialog": None,
        "done": 0,
        "total": 0,
        "status": "openai",
        "completed": False,
        "status_message": None,
    }

    if parent is not None:
        dialog = QProgressDialog(
            "Generating team logos...", None, 0, 1, parent
        )
        dialog.setWindowTitle("Generating Team Logos")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.show()
        progress_state["dialog"] = dialog

    def update_label() -> None:
        dialog = progress_state.get("dialog")
        if dialog is None:
            return
        done = int(progress_state.get("done", 0) or 0)
        total = int(progress_state.get("total", 0) or 0)
        completed = bool(progress_state.get("completed"))
        status = progress_state.get("status", "openai")
        label = "Generating team logos..."
        clamped_done = done
        if total > 0:
            clamped_done = max(0, min(done, total))
            percent = int(round(clamped_done / total * 100))
            if completed:
                percent = 100
            status_text = (
                "Team logos generated!"
                if completed
                else "Generating team logos..."
            )
            label = f"{status_text} ({clamped_done}/{total} - {percent}%)"
        if total:
            label = label.strip()
        elif completed:
            label = "Team logos generated!"
        if status == "auto_logo":
            status_message = progress_state.get("status_message")
            detail = (
                str(status_message).strip()
                if isinstance(status_message, str)
                else None
            )
            if detail:
                label = f"{label}\n{detail}"
            else:
                label = f"{label}\nLegacy auto-logo generator in use"
        dialog.setLabelText(label)

    def close_progress() -> None:
        dialog = progress_state.get("dialog")
        if dialog is not None:
            dialog.reset()
            dialog.close()
        progress_state["dialog"] = None
        progress_state["completed"] = False
        progress_state["status_message"] = None

    def progress_cb(done: int, total: int) -> None:
        progress_state["done"] = done
        progress_state["total"] = total
        progress_state["completed"] = total > 0 and done >= total

        def update() -> None:
            dialog = progress_state.get("dialog")
            if dialog is not None:
                if total > 0:
                    clamped_total = max(1, total)
                    clamped_done = max(0, min(done, clamped_total))
                    if (
                        dialog.minimum() != 0
                        or dialog.maximum() != clamped_total
                    ):
                        dialog.setRange(0, clamped_total)
                    dialog.setValue(clamped_done)
                else:
                    if dialog.minimum() != 0 or dialog.maximum() != 0:
                        dialog.setRange(0, 0)
                    dialog.setValue(0)
            update_label()

        _schedule(update)

    def status_cb(mode: str) -> None:
        progress_state["status"] = mode
        if mode == "auto_logo":
            progress_state["status_message"] = get_client_status_message()
        else:
            progress_state["status_message"] = None

        def update() -> None:
            update_label()

        _schedule(update)

    def worker() -> None:
        try:
            out_dir = generate_team_logos(
                progress_callback=progress_cb,
                status_callback=status_cb,
            )
        except Exception as exc:
            def fail() -> None:
                close_progress()
                if parent is not None:
                    QMessageBox.warning(
                        parent,
                        "Logo Generation Failed",
                        str(exc),
                    )
                if context.show_toast:
                    context.show_toast(
                        "error",
                        f"Logo generation failed: {exc}",
                    )

            _schedule(fail)
        else:
            def success() -> None:
                progress_state["completed"] = True
                dialog = progress_state.get("dialog")
                if dialog is not None:
                    total = int(
                        progress_state.get("total", dialog.maximum()) or 0
                    )
                    progress_state["done"] = max(
                        total, int(progress_state.get("done", total) or 0)
                    )
                    if total > 0:
                        dialog.setRange(0, max(1, total))
                        dialog.setValue(max(1, total))
                    else:
                        dialog.setRange(0, 0)
                        dialog.setValue(0)
                    update_label()
                    QTimer.singleShot(1200, close_progress)
                else:
                    close_progress()
                fallback_reason = None
                if progress_state.get("status") == "auto_logo":
                    raw_reason = progress_state.get("status_message")
                    if isinstance(raw_reason, str) and raw_reason.strip():
                        fallback_reason = raw_reason.strip()
                    else:
                        message_hint = get_client_status_message()
                        if message_hint:
                            fallback_reason = message_hint
                        else:
                            fallback_reason = (
                                "OpenAI client is not configured, "
                                "so the legacy auto-logo "
                                "generator was used for these logos."
                            )
                lines = [f"Team logos saved to {out_dir}"]
                if fallback_reason:
                    lines.append(fallback_reason)
                message = "\n\n".join(lines)
                target_parent = parent or QApplication.activeWindow()
                if target_parent is not None:
                    QMessageBox.information(
                        target_parent,
                        "Logos Generated",
                        message,
                    )
                if context.show_toast:
                    toast_msg = "Team logos generated."
                    if fallback_reason:
                        toast_msg = (
                            "Team logos generated via fallback: "
                            f"{fallback_reason}"
                        )
                    context.show_toast("success", toast_msg)

            _schedule(success)

    context.run_async(worker)


def generate_player_avatars_action(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Generate player avatars asynchronously."""

    initial = False
    if parent is not None:
        initial = (
            QMessageBox.question(
                parent,
                "Initial Creation",
                "Is this the initial creation of player avatars?\n"
                "Yes will remove existing avatars (except Template).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    if context.show_toast:
        context.show_toast(
            "info",
            "Generating player avatars in background...",
        )

    progress_state: dict[str, object] = {
        "dialog": None,
        "done": 0,
        "total": 0,
        "completed": False,
    }

    if parent is not None:
        dialog = QProgressDialog(
            "Generating player avatars...", None, 0, 1, parent
        )
        dialog.setWindowTitle("Generating Player Avatars")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.show()
        progress_state["dialog"] = dialog

    def update_label() -> None:
        dialog = progress_state.get("dialog")
        if dialog is None:
            return
        done = int(progress_state.get("done", 0) or 0)
        total = int(progress_state.get("total", 0) or 0)
        completed = bool(progress_state.get("completed"))
        label = "Generating player avatars..."
        if total > 0:
            clamped_done = max(0, min(done, total))
            percent = int(round(clamped_done / total * 100))
            if completed:
                percent = 100
            status_text = (
                "Player avatars generated!"
                if completed
                else "Generating player avatars..."
            )
            label = f"{status_text} ({clamped_done}/{total} - {percent}%)"
        elif completed:
            label = "Player avatars generated!"
        dialog.setLabelText(label)

    def close_progress() -> None:
        dialog = progress_state.get("dialog")
        if dialog is not None:
            dialog.reset()
            dialog.close()
        progress_state["dialog"] = None
        progress_state["completed"] = False
        progress_state["done"] = 0
        progress_state["total"] = 0

    def progress_cb(done: int, total: int) -> None:
        progress_state["done"] = done
        progress_state["total"] = total
        progress_state["completed"] = total > 0 and done >= total

        def update() -> None:
            dialog = progress_state.get("dialog")
            if dialog is not None:
                if total > 0:
                    clamped_total = max(1, total)
                    clamped_done = max(0, min(done, clamped_total))
                    if (
                        dialog.minimum() != 0
                        or dialog.maximum() != clamped_total
                    ):
                        dialog.setRange(0, clamped_total)
                    dialog.setValue(clamped_done)
                else:
                    if dialog.minimum() != 0 or dialog.maximum() != 0:
                        dialog.setRange(0, 0)
                    dialog.setValue(0)
            update_label()

        _schedule(update)

    def worker() -> None:
        try:
            out_dir = generate_player_avatars(
                progress_callback=progress_cb,
                initial_creation=initial,
            )
        except Exception as exc:
            def fail() -> None:
                close_progress()
                if parent is not None:
                    QMessageBox.warning(
                        parent,
                        "Avatar Generation Failed",
                        str(exc),
                    )
                if context.show_toast:
                    context.show_toast(
                        "error",
                        f"Avatar generation failed: {exc}",
                    )

            _schedule(fail)
        else:
            def success() -> None:
                progress_state["completed"] = True
                dialog = progress_state.get("dialog")
                if dialog is not None:
                    total = int(
                        progress_state.get("total", dialog.maximum()) or 0
                    )
                    progress_state["done"] = max(
                        total, int(progress_state.get("done", total) or 0)
                    )
                    if total > 0:
                        dialog.setRange(0, max(1, total))
                        dialog.setValue(max(1, total))
                    else:
                        dialog.setRange(0, 0)
                        dialog.setValue(0)
                    update_label()
                    QTimer.singleShot(1200, close_progress)
                else:
                    close_progress()
                if parent is not None:
                    QMessageBox.information(
                        parent,
                        "Avatars Generated",
                        f"Player avatars saved to {out_dir}",
                    )
                if context.show_toast:
                    context.show_toast("success", "Player avatars generated.")

            _schedule(success)

    context.run_async(worker)


__all__ = [
    "generate_player_avatars_action",
    "generate_team_logos_action",
]
