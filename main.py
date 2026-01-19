import os
import sys
import logging
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, qInstallMessageHandler
from PyQt6.QtGui import QGuiApplication, QFont, QIcon
from PyQt6.QtWidgets import QApplication

from ui.splash_screen import SplashScreen
from ui.theme import DARK_QSS
from ui.version_badge import install_version_badge
from utils.path_utils import get_base_dir

_PREV_QT_HANDLER = None
_LOG_FILE_HANDLE = None


def _startup_log_dir() -> Path:
    base_dir = get_base_dir()
    candidates = [
        base_dir / "data" / "logs",
        base_dir / "logs",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        fallback = Path(local_app) / "NexGen-BBPro" / "logs"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except OSError:
            pass
    return Path.cwd()


def _configure_startup_logging() -> None:
    global _LOG_FILE_HANDLE

    log_dir = _startup_log_dir()
    log_path = log_dir / "startup.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    try:
        import faulthandler

        _LOG_FILE_HANDLE = open(log_path, "a", encoding="utf-8")
        faulthandler.enable(_LOG_FILE_HANDLE)
    except Exception:
        _LOG_FILE_HANDLE = None

    logging.info("Startup log initialized at %s", log_path)
    logging.info("CWD=%s", Path.cwd())
    logging.info("EXE=%s", sys.executable)
    logging.info("ARGV=%s", sys.argv)
    logging.info("MEIPASS=%s", getattr(sys, "_MEIPASS", None))
    logging.info("BASE_DIR=%s", get_base_dir())

    try:
        os.chdir(get_base_dir())
        logging.info("CWD set to %s", Path.cwd())
    except OSError:
        logging.warning("Unable to set CWD to base dir", exc_info=True)

    def _excepthook(exc_type, exc, tb):
        if exc_type is SystemExit:
            return
        logging.error("Unhandled exception: %s", exc, exc_info=(exc_type, exc, tb))
        traceback.print_exception(exc_type, exc, tb)

    sys.excepthook = _excepthook

    try:
        import threading

        def _thread_hook(args):
            logging.error(
                "Unhandled thread exception: %s",
                args.exc_value,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        threading.excepthook = _thread_hook  # type: ignore[attr-defined]
    except Exception:
        pass


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
        try:
            logging.info("Qt: %s", message)
        except Exception:
            pass
        if _PREV_QT_HANDLER is not None:
            _PREV_QT_HANDLER(mode, context, message)
            return
        stream = sys.stderr
        if stream is not None and hasattr(stream, "write"):
            try:
                stream.write(f"{message}\n")
            except Exception:
                pass

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
    _configure_startup_logging()
    _install_qt_warning_filter()
    _set_windows_app_id()
    try:
        app = QApplication(sys.argv)
        _apply_app_icon(app)
        _normalize_app_font(app)
        app.setStyleSheet(DARK_QSS)
        install_version_badge(app)
        splash = SplashScreen()
        _show_splash_window(splash, app)
        sys.exit(app.exec())
    except Exception:
        logging.exception("Fatal startup failure")
        raise


if __name__ == "__main__":
    main()
