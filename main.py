import os
import sys

from PyQt6.QtCore import Qt, QTimer, qInstallMessageHandler
from PyQt6.QtGui import QGuiApplication, QFont, QIcon
from PyQt6.QtWidgets import QApplication

from ui.splash_screen import SplashScreen
from ui.theme import DARK_QSS
from ui.version_badge import install_version_badge
from utils.path_utils import get_base_dir

_PREV_QT_HANDLER = None


def _show_splash_window(window: SplashScreen, app: QApplication) -> None:
    """Present the splash window maximized while keeping Wayland stability."""
    platform = (QGuiApplication.platformName() or "").lower()
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()

    if "wayland" in (platform, session_type):
        # Avoid an initial maximized show that can crash under fractional scaling
        screen = window.screen() or app.primaryScreen()
        if screen:
            window.setGeometry(screen.availableGeometry())
        window.show()

        def _maximize_after_show():
            window.setWindowState(window.windowState() | Qt.WindowState.WindowMaximized)
            window.raise_()
            window.activateWindow()

        QTimer.singleShot(0, _maximize_after_show)
        return

    window.showMaximized()
    window.raise_()
    window.activateWindow()


def _normalize_app_font(app: QApplication) -> None:
    """Ensure the app has a valid point-size font to avoid Qt warnings."""
    try:
        font = app.font()
    except Exception:
        return
    try:
        point_size = float(font.pointSizeF())
    except Exception:
        point_size = -1.0
    if point_size > 0:
        return

    try:
        pixel_size = int(font.pixelSize())
    except Exception:
        pixel_size = -1

    if pixel_size > 0:
        screen = app.primaryScreen()
        try:
            dpi = float(screen.logicalDotsPerInch()) if screen else 96.0
        except Exception:
            dpi = 96.0
        if dpi <= 0:
            dpi = 96.0
        point_size = max(1.0, (pixel_size * 72.0 / dpi))
    else:
        point_size = 12.0

    font.setPointSizeF(point_size)
    app.setFont(font)


def _apply_app_icon(app: QApplication) -> None:
    icon_path = get_base_dir() / "logo" / "NexGen.png"
    if not icon_path.exists():
        return
    try:
        app.setWindowIcon(QIcon(str(icon_path)))
    except Exception:
        pass


def _install_qt_warning_filter() -> None:
    """Suppress noisy Qt font warnings while preserving other log output."""
    global _PREV_QT_HANDLER

    def _handler(mode, context, message):
        if "QFont::setPointSize" in message:
            return
        if _PREV_QT_HANDLER is not None:
            _PREV_QT_HANDLER(mode, context, message)
            return
        sys.stderr.write(f"{message}\n")

    _PREV_QT_HANDLER = qInstallMessageHandler(_handler)


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes  # type: ignore

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "NexGen.BBPro"
        )
    except Exception:
        pass


def main():
    _install_qt_warning_filter()
    _set_windows_app_id()
    app = QApplication(sys.argv)
    _apply_app_icon(app)
    _normalize_app_font(app)
    app.setStyleSheet(DARK_QSS)
    install_version_badge(app)
    splash = SplashScreen()
    _show_splash_window(splash, app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
