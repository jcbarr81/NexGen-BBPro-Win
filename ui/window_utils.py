from __future__ import annotations

"""Utilities for managing top-most behaviour of Qt windows."""

import weakref

from PyQt6.QtCore import Qt

# Track windows that should follow the splash screen's top-most state
_tracked_windows: "weakref.WeakSet" = weakref.WeakSet()


def _apply_flag(window, enable: bool) -> None:
    """Apply or remove the WindowStaysOnTopHint flag for *window*."""
    try:
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enable)
    except AttributeError:  # pragma: no cover - legacy fallback
        flags = window.windowFlags()
        if enable:
            window.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            window.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)

    window.show()


def ensure_on_top(window) -> None:
    """Ensure *window* stays on top and register it for global toggling."""
    _tracked_windows.add(window)
    _apply_flag(window, True)


def remove_on_top(window) -> None:
    """Remove the on-top hint for *window* and stop tracking it."""
    _apply_flag(window, False)
    try:
        _tracked_windows.remove(window)
    except KeyError:
        pass


def untrack_on_top(window) -> None:
    """Stop tracking *window* without changing flags or visibility."""
    try:
        _tracked_windows.remove(window)
    except KeyError:
        pass


def set_all_on_top(enable: bool) -> None:
    """Toggle the on-top flag for all tracked windows."""
    for win in list(_tracked_windows):
        _apply_flag(win, enable)


def show_on_top(window):
    """Show a window while ensuring it stays on top.

    If the window has an ``exec`` method (e.g. dialogs), it will be invoked and
    the result returned. Otherwise ``show`` is called.
    """
    ensure_on_top(window)
    if hasattr(window, "exec"):
        return window.exec()
    window.show()
    window.raise_()
    window.activateWindow()
    return None
