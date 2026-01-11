import logging
import os
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QGraphicsOpacityEffect,
)
from PyQt6.QtGui import QPixmap, QFont, QKeySequence, QShortcut
from PyQt6.QtCore import Qt, QEvent, QPropertyAnimation, QEasingCurve, QTimer, QUrl
try:  # Multimedia may not be available on all platforms
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
except Exception as exc:  # pragma: no cover - optional dependency
    logging.getLogger(__name__).debug("Qt multimedia unavailable: %s", exc)
    QMediaPlayer = None  # type: ignore[assignment]
    QAudioOutput = None  # type: ignore[assignment]

try:  # Optional pygame fallback for environments without Qt multimedia
    import pygame  # type: ignore
except Exception as exc:  # pragma: no cover - optional dependency
    logging.getLogger(__name__).debug("pygame unavailable for splash music: %s", exc)
    pygame = None  # type: ignore[assignment]

from ui.login_window import LoginWindow
from utils.path_utils import get_base_dir
from ui.window_utils import show_on_top, set_all_on_top
from ui.version_badge import enable_version_badge

logger = logging.getLogger(__name__)

class SplashScreen(QWidget):
    """Initial splash screen displaying the NexGen logo and start button."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NexGen BBPro")

        layout = QVBoxLayout()
        layout.addStretch()

        logo_label = QLabel()
        logo_path = get_base_dir() / "logo" / "NexGen.png"
        logo_label.setPixmap(QPixmap(str(logo_path)))
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_label)

        layout.addStretch()

        # Prominent primary button
        self.login_button = QPushButton("Start Game", objectName="Primary")
        font = self.login_button.font()
        font.setPointSize(22)
        font.setBold(True)
        self.login_button.setFont(font)
        self.login_button.setMinimumWidth(260)
        self.login_button.setMinimumHeight(48)
        self.login_button.clicked.connect(self.open_login)
        # Place near lower-right corner for stronger visual affordance
        button_row = QVBoxLayout()
        button_row.setContentsMargins(0, 0, 24, 24)
        button_row.setSpacing(0)
        container = QWidget()
        cr = QVBoxLayout(container)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(0)
        cr.addWidget(self.login_button, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(container)

        # Sponsor/tech logos (bottom-left). Scales images to fit nicely.
        sponsors = QWidget()
        sp = QVBoxLayout(sponsors)
        sp.setContentsMargins(24, 0, 0, 24)
        sp.setSpacing(6)
        caption = QLabel("Powered by")
        cf = caption.font()
        cf.setPointSize(10)
        cf.setBold(True)
        caption.setFont(cf)
        caption.setStyleSheet("color: #d2ba8f;")
        caption.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        sp.addWidget(caption)
        self.sponsor_bar = self._build_sponsor_bar()
        sp.addWidget(self.sponsor_bar, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(sponsors, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

        # Add a larger stretch below the button to push it upward for a
        # more balanced appearance on the splash screen.
        layout.addStretch(2)

        self.setLayout(layout)
        enable_version_badge(self)
        self.login_window = None

        # Keyboard shortcut: Enter/Return triggers Start Game
        try:
            QShortcut(QKeySequence(Qt.Key.Key_Return), self, activated=self.open_login)
            QShortcut(QKeySequence(Qt.Key.Key_Enter), self, activated=self.open_login)
            QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)
        except Exception:
            pass

        # Subtle fade-in animations for logo, sponsors and start button
        self._anims = []  # hold refs
        self._apply_fade_in(logo_label, duration=800, delay=0)
        self._apply_fade_in(self.login_button, duration=700, delay=300)
        self._apply_fade_in(sponsors, duration=700, delay=500)

        # Start background music if available
        self._music_player = None
        self._audio_output = None
        self._music_backend: str | None = None
        self._music_started = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._music_started:
            self._music_started = True
            QTimer.singleShot(0, self._setup_music)

    def _build_sponsor_bar(self) -> QWidget:
        from PyQt6.QtWidgets import QHBoxLayout
        bar = QWidget()
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(10)
        base = get_base_dir()
        # Slightly smaller footprint for better fit
        candidates = [
            (base / "assets" / "iron8.png", 160),
            # MindWeaver image removed per request
        ]
        max_h = 56
        for path, width in candidates:
            if not path.exists():
                # Try common alternatives
                alt1 = base / "assets" / path.name.capitalize()
                alt2 = base / "assets" / path.name.upper()
                if alt1.exists():
                    path = alt1
                elif alt2.exists():
                    path = alt2
                else:
                    continue
            lbl = QLabel()
            pm = QPixmap(str(path))
            if not pm.isNull():
                scaled = pm.scaled(width, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                lbl.setPixmap(scaled)
            hb.addWidget(lbl)
        hb.addStretch(1)
        return bar

    def _apply_fade_in(self, widget: QWidget, *, duration: int = 600, delay: int = 0) -> None:
        try:
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            effect.setOpacity(0.0)
            anim = QPropertyAnimation(effect, b"opacity", self)
            anim.setDuration(duration)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            if delay > 0:
                QTimer.singleShot(delay, anim.start)
            else:
                anim.start()
            self._anims.append(anim)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Music helpers
    def _setup_music(self) -> None:
        disable_music = os.environ.get("NEXGEN_SPLASH_MUSIC", "").strip().lower()
        if disable_music in {"0", "false", "no", "off"}:
            logger.info("Splash music disabled via NEXGEN_SPLASH_MUSIC.")
            return

        base = get_base_dir()
        candidates = [
            base / "assets" / "splash_music.ogg",
            base / "assets" / "splash_music.mp3",
            base / "assets" / "splash.ogg",
            base / "assets" / "splash.mp3",
            base / "assets" / "music" / "splash.mp3",
        ]
        audio = next((p for p in candidates if p.exists()), None)
        if audio is None:
            logger.debug("No splash music asset found at expected locations.")
            return

        last_error: Optional[Exception] = None
        backend = os.environ.get("NEXGEN_AUDIO_BACKEND", "").strip().lower()
        prefer_pygame = backend == "pygame"

        def _try_qt() -> bool:
            nonlocal last_error
            if QMediaPlayer is None or QAudioOutput is None:
                return False
            try:
                player = QMediaPlayer(self)
                audio_output = QAudioOutput(self)
                player.setAudioOutput(audio_output)
                try:
                    audio_output.setVolume(1.0)
                except Exception:
                    pass
                player.setSource(QUrl.fromLocalFile(str(audio)))

                try:
                    def _seek_to_24(status):  # pragma: no cover - depends on Qt version
                        try:
                            from PyQt6.QtMultimedia import QMediaPlayer as _MP
                            if status == _MP.MediaStatus.LoadedMedia:
                                player.setPosition(24000)
                                try:
                                    player.mediaStatusChanged.disconnect(_seek_to_24)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                    player.mediaStatusChanged.connect(_seek_to_24)
                except Exception:
                    try:
                        QTimer.singleShot(300, lambda: player.setPosition(24000))
                    except Exception:
                        pass

                if hasattr(player, "setLoops"):
                    try:
                        player.setLoops(-1)  # type: ignore[arg-type]
                    except Exception:
                        pass
                else:
                    def _restart_if_needed(state):  # pragma: no cover - depends on Qt version
                        try:
                            from PyQt6.QtMultimedia import QMediaPlayer as _MP
                            if state == _MP.PlaybackState.StoppedState:
                                player.play()
                        except Exception:
                            pass
                    try:
                        player.playbackStateChanged.connect(_restart_if_needed)
                    except Exception:
                        pass

                player.play()
                self._music_player = player
                self._audio_output = audio_output
                self._music_backend = "qt"
                return True
            except Exception as exc:  # pragma: no cover - environment dependent
                last_error = exc
                logger.warning("Failed to start splash music via Qt multimedia: %s", exc)
                self._music_player = None
                self._audio_output = None
                self._music_backend = None
                return False

        def _try_pygame() -> bool:
            nonlocal last_error
            if pygame is None:
                return False
            try:
                self._init_pygame_mixer()
                pygame.mixer.music.load(str(audio))  # type: ignore[attr-defined]
                pygame.mixer.music.set_volume(1.0)  # type: ignore[attr-defined]
                pygame.mixer.music.play(-1)  # type: ignore[attr-defined]
                try:
                    pygame.mixer.music.set_pos(24.0)  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._music_player = "pygame"
                self._audio_output = None
                self._music_backend = "pygame"
                return True
            except Exception as exc:  # pragma: no cover - environment dependent
                last_error = exc
                logger.warning("Failed to start splash music via pygame: %s", exc)
                try:
                    pygame.mixer.music.stop()  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._music_player = None
                self._music_backend = None
                return False

        if prefer_pygame:
            if _try_pygame() or _try_qt():
                return
        else:
            if _try_qt():
                return

        if last_error is not None:
            logger.info(
                "Splash music disabled; no working audio backend (%s). "
                "Install Qt multimedia dependencies or set NEXGEN_AUDIO_BACKEND=pygame.",
                last_error,
            )
        else:
            logger.info(
                "Splash music disabled; no audio backend available. "
                "Install Qt multimedia dependencies or set NEXGEN_AUDIO_BACKEND=pygame."
            )

    def _stop_music(self) -> None:
        try:
            if self._music_backend == "qt" and self._music_player is not None:
                self._music_player.stop()
            elif self._music_backend == "pygame" and pygame is not None:
                pygame.mixer.music.stop()  # type: ignore[attr-defined]
        except Exception:
            pass
        self._music_player = None
        self._audio_output = None
        self._music_backend = None

    def _init_pygame_mixer(self) -> None:
        if pygame is None:
            return
        try:
            if not pygame.get_init():
                pygame.init()  # type: ignore[attr-defined]
            if pygame.mixer.get_init():
                return  # Mixer already initialised
            self._initialise_pygame_with_preferred_driver()
        except Exception as exc:  # pragma: no cover - environment dependent
            message = str(exc).lower()
            if "audio device" not in message and "audio driver" not in message:
                raise
            try:
                pygame.mixer.quit()  # type: ignore[attr-defined]
            except Exception:
                pass
            os.environ["SDL_AUDIODRIVER"] = "dummy"
            pygame.mixer.init()  # type: ignore[attr-defined]

    def _initialise_pygame_with_preferred_driver(self) -> None:
        """Try several SDL audio drivers before falling back to dummy."""
        if pygame is None:
            return
        original_driver = os.environ.get("SDL_AUDIODRIVER")
        drivers_to_try: list[str | None] = [original_driver]
        if self._running_in_wsl():
            drivers_to_try.extend(["pipewire", "pulse", "alsa"])
        drivers_to_try.append("dummy")

        # Deduplicate while preserving order
        seen: set[str | None] = set()
        unique_drivers = [d for d in drivers_to_try if not (d in seen or seen.add(d))]

        last_error: Exception | None = None
        for driver in unique_drivers:
            try:
                if driver is None:
                    if original_driver is None:
                        os.environ.pop("SDL_AUDIODRIVER", None)
                    else:
                        os.environ["SDL_AUDIODRIVER"] = original_driver
                else:
                    os.environ["SDL_AUDIODRIVER"] = driver
                pygame.mixer.init()  # type: ignore[attr-defined]
                if driver == "dummy":
                    logger.info(
                        "Splash music muted: SDL dummy audio driver active. "
                        "Configure audio backend for playback."
                    )
                elif driver is not None and driver != original_driver:
                    logger.info("Splash music using SDL audio driver '%s'.", driver)
                return
            except Exception as exc:  # pragma: no cover - environment dependent
                last_error = exc
                try:
                    pygame.mixer.quit()  # type: ignore[attr-defined]
                except Exception:
                    pass
                continue

        # Restore environment variable on complete failure
        if original_driver is None:
            os.environ.pop("SDL_AUDIODRIVER", None)
        else:
            os.environ["SDL_AUDIODRIVER"] = original_driver
        if last_error is not None:
            raise last_error

    @staticmethod
    def _running_in_wsl() -> bool:
        """Detect whether the application is running under Windows Subsystem for Linux."""
        try:
            with open("/proc/sys/kernel/osrelease", encoding="utf-8") as handle:
                contents = handle.read().lower()
        except OSError:
            return False
        return "microsoft" in contents or "wsl" in contents

    def open_login(self):
        """Show the login window while keeping the splash visible."""
        # Disable the button to prevent spawning multiple login windows
        self.login_button.setEnabled(False)
        # Stop splash music when transitioning
        self._stop_music()

        self.login_window = LoginWindow(self)
        show_on_top(self.login_window)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            set_all_on_top(not self.isMinimized())
        super().changeEvent(event)
