"""Shared helpers for export completion dialogs."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QMessageBox, QWidget

from utils.desktop_utils import open_containing_folder


def show_export_success_dialog(
    *,
    parent: Optional[QWidget],
    title: str,
    message: str,
    export_path: Path | str,
) -> None:
    """Show success dialog with an optional Open Folder action."""

    try:
        box = QMessageBox(parent)
        box.setWindowTitle(title)
        icon_enum = getattr(QMessageBox, "Icon", None)
        info_icon = getattr(icon_enum, "Information", None) if icon_enum else None
        if info_icon is not None:
            box.setIcon(info_icon)
        box.setText(message)

        role_enum = getattr(QMessageBox, "ButtonRole", None)
        action_role = getattr(role_enum, "ActionRole", None) if role_enum else None
        accept_role = getattr(role_enum, "AcceptRole", None) if role_enum else None
        open_button = box.addButton(
            "Open Folder",
            action_role if action_role is not None else 0,
        )
        close_button = box.addButton(
            "Close",
            accept_role if accept_role is not None else 0,
        )
        try:
            box.setDefaultButton(close_button)
        except Exception:
            pass
        box.exec()
    except Exception:
        QMessageBox.information(parent, title, message)
        return

    if box.clickedButton() != open_button:
        return
    try:
        open_containing_folder(Path(export_path))
    except Exception as exc:
        QMessageBox.warning(
            parent,
            title,
            f"Unable to open export folder:\n{exc}",
        )


__all__ = ["show_export_success_dialog"]
