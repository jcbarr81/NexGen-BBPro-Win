from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QApplication, QStatusBar

from utils.path_utils import get_base_dir
from .theme_enhanced import ENHANCED_DARK_QSS, ENHANCED_LIGHT_QSS

THEME_FAMILY_CLASSIC = "classic"
THEME_FAMILY_ENHANCED_WARM = "enhanced_warm"

THEME_MODE_DARK = "dark"
THEME_MODE_LIGHT = "light"

DEFAULT_THEME_FAMILY = THEME_FAMILY_CLASSIC
DEFAULT_THEME_MODE = THEME_MODE_DARK

_THEME_PREFS_FILE = "theme_preferences.json"
_THEME_FAMILY_PROP = "nexgen_theme_family"
_THEME_MODE_PROP = "nexgen_theme_mode"


CLASSIC_LIGHT_QSS = """
/* App */
QWidget {
    background: #fffdf0;
    color: #462d0d;
    font-family: 'Segoe UI', 'Noto Sans', Arial;
    font-size: 14px;
    font-weight: 500;
}

/* Sidebar (dugout) */
#Sidebar {
    background: #462d0d;
    border: none;
}
#Sidebar QLabel {
    color: #fffdf0;
    font-weight: 600;
    padding: 8px 10px;
    letter-spacing: .5px;
}
#NavButton {
    color: #fffdf0;
    background: transparent;
    padding: 10px 14px;
    margin: 4px 8px;
    border-radius: 10px;
    text-align: left;
}
#NavButton:hover { background: #604d33; }
#NavButton:checked {
    background: #604d33;
    border: 1px solid #968d7d;
    color: #fffdf0;
}

/* Header (scoreboard strip) */
#Header {
    background: #fffdf0;
    border-bottom: 1px solid #968d7d;
}
#Title {
    font-size: 20px;
    font-weight: 800;
    letter-spacing: .5px;
    color: #462d0d;
}
#Scoreboard {
    background: #604d33;
    color: #fffdf0;
    border-radius: 10px;
    padding: 6px 12px;
    font-weight: 700;
}

/* Cards and content */
QFrame#Card {
    background: #fffdf0;
    border: 1px solid #968d7d;
    border-radius: 14px;
}
QLabel#SectionTitle {
    font-size: 16px;
    font-weight: 700;
    color: #462d0d;
}
QLabel#MetricLabel {
    font-size: 12px;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: #6f5c42;
}
QLabel#MetricLabel[variant="leader"] {
    font-size: 11px;
    letter-spacing: 0.6px;
}
QLabel#MetricValue {
    font-size: 24px;
    font-weight: 800;
    color: #462d0d;
}
QLabel#MetricValue[interactive="true"] {
    color: #b36b18;
}
QLabel#MetricValue[interactive="true"][highlight="true"] { color: #c3521f; }
QLabel#MetricValue[variant="leader"] {
    font-size: 18px;
    font-weight: 700;
}
QLabel#MetricValue[highlight="true"] { color: #c3521f; }

QListWidget#DepthChartList {
    background: #fff7dc;
    border: 1px solid #d6c4a3;
    border-radius: 10px;
    padding: 6px;
}
QListWidget#DepthChartList::item {
    padding: 4px 6px;
    color: #3a2508;
}
QListWidget#DepthChartList::item:selected {
    background: #604d33;
    color: #fffdf0;
    border-radius: 6px;
}

/* Buttons */
QPushButton {
    background: #968d7d;
    color: #fffdf0;
    border: 1px solid #604d33;
    padding: 8px 14px;
    border-radius: 8px;
    font-weight: 600;
}
QPushButton:hover { background: #a59c8c; }
QPushButton:pressed { background: #857d6f; }

QPushButton#Primary,
QPushButton#ActionButton {
    background: #604d33;
    color: #fffdf0;
    border: none;
    padding: 10px 16px;
    border-radius: 10px;
    font-weight: 600;
}
QPushButton#Primary:hover,
QPushButton#ActionButton:hover { background: #6f5c42; }
QPushButton#Primary:pressed,
QPushButton#ActionButton:pressed { background: #513e24; }

QPushButton#Success {
    background: #2f9e44;
    color: white;
    border: none;
    padding: 12px 18px;
    border-radius: 14px;
    font-size: 16px;
    font-weight: 700;
}
QPushButton#Success:hover { background: #27903c; }
QPushButton#Success:pressed { background: #237f35; }

/* Destructive actions */
QPushButton#Danger {
    background: #a61e1e;
    color: white;
    border: none;
    padding: 10px 16px;
    border-radius: 10px;
    font-weight: 700;
}
QPushButton#Danger:hover { background: #b32d2d; }
QPushButton#Danger:pressed { background: #8f1a1a; }

QStatusBar { background: #fffdf0; border-top: 1px solid #968d7d; }
#VersionBadge {
    color: #462d0d;
    background: rgba(255, 253, 240, 0.75);
    border: 1px solid #968d7d;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
"""

CLASSIC_DARK_QSS = """
QWidget {
    background: #1e1207;
    color: #fffdf0;
    font-family: 'Segoe UI', 'Noto Sans', Arial;
    font-size: 14px;
    font-weight: 500;
}
#Sidebar {
    background: #160e04;
}
#Sidebar QLabel { color: #fffdf0; }
#NavButton {
    color: #fffdf0;
    background: transparent;
    padding: 10px 14px;
    margin: 4px 8px;
    border-radius: 10px;
}
#NavButton:hover { background: #2c1b0a; }
#NavButton:checked {
    background: #3b2810;
    border: 1px solid #604d33;
    color: #fffdf0;
}
#Header {
    background: #221508;
    border-bottom: 1px solid #3b2810;
}
#Title { color: #fffdf0; }
#Scoreboard {
    background: #160e04;
    color: #fffdf0;
    border: 1px solid #3b2810;
    border-radius: 10px;
    padding: 6px 12px;
    font-weight: 700;
}
QFrame#Card {
    background: #221508;
    border: 1px solid #3b2810;
    border-radius: 14px;
}
QLabel#SectionTitle {
    font-size: 16px;
    font-weight: 700;
    color: #fffdf0;
}
QLabel#MetricLabel {
    font-size: 12px;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: #a59c8c;
}
QLabel#MetricLabel[variant="leader"] {
    font-size: 11px;
    letter-spacing: 0.6px;
    color: #d4c5a5;
}
QLabel#MetricValue {
    font-size: 24px;
    font-weight: 800;
    color: #fffdf0;
}
QLabel#MetricValue[interactive="true"] {
    color: #f1c27d;
}
QLabel#MetricValue[interactive="true"][highlight="true"] { color: #e67700; }
QLabel#MetricValue[variant="leader"] {
    font-size: 18px;
    font-weight: 700;
}

QListWidget#DepthChartList {
    background: #1a0f05;
    border: 1px solid #3b2810;
    border-radius: 10px;
    padding: 6px;
}
QListWidget#DepthChartList::item {
    padding: 4px 6px;
    color: #fffdf0;
}
QListWidget#DepthChartList::item:selected {
    background: #8d6a36;
    color: #fffdf0;
    border-radius: 6px;
}
QLabel#MetricValue[highlight="true"] { color: #e67700; }
QPushButton {
    background: #3b2810;
    color: #fffdf0;
    border: 1px solid #604d33;
    padding: 8px 14px;
    border-radius: 8px;
    font-weight: 600;
}
QPushButton:hover { background: #4f3c29; }
QPushButton:pressed { background: #2c1b0a; }
QPushButton#Primary,
QPushButton#ActionButton {
    background: #604d33;
    color: #fffdf0;
    border: none;
    padding: 10px 16px;
    border-radius: 10px;
    font-weight: 600;
}
QPushButton#Primary:hover,
QPushButton#ActionButton:hover { background: #6f5c42; }
QPushButton#Primary:pressed,
QPushButton#ActionButton:pressed { background: #513e24; }
QPushButton#Success {
    background: #2f9e44;
    color: white;
    border: none;
    padding: 12px 18px;
    border-radius: 14px;
    font-size: 16px;
    font-weight: 700;
}
QPushButton#Success:hover { background: #27903c; }
QPushButton#Success:pressed { background: #237f35; }
/* Destructive actions */
QPushButton#Danger {
    background: #8f1a1a;
    color: white;
    border: 1px solid #b32d2d;
    padding: 10px 16px;
    border-radius: 10px;
    font-weight: 700;
}
QPushButton#Danger:hover { background: #a61e1e; }
QPushButton#Danger:pressed { background: #701313; }
QStatusBar { background: #1e1207; border-top: 1px solid #3b2810; }
#VersionBadge {
    color: #d2ba8f;
    background: rgba(22, 14, 4, 0.7);
    border: 1px solid rgba(150, 141, 125, 0.5);
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
"""


LIGHT_QSS = CLASSIC_LIGHT_QSS
DARK_QSS = CLASSIC_DARK_QSS

_THEME_DISPLAY_NAMES = {
    THEME_FAMILY_CLASSIC: "Classic",
    THEME_FAMILY_ENHANCED_WARM: "Enhanced Warm",
}

_THEME_STYLES = {
    THEME_FAMILY_CLASSIC: {
        THEME_MODE_LIGHT: CLASSIC_LIGHT_QSS,
        THEME_MODE_DARK: CLASSIC_DARK_QSS,
    },
    THEME_FAMILY_ENHANCED_WARM: {
        THEME_MODE_LIGHT: ENHANCED_LIGHT_QSS,
        THEME_MODE_DARK: ENHANCED_DARK_QSS,
    },
}


def _preferences_path() -> Path:
    return get_base_dir() / "config" / _THEME_PREFS_FILE


def available_theme_families() -> tuple[str, ...]:
    return tuple(_THEME_STYLES.keys())


def normalize_theme_family(value: str | None) -> str:
    token = str(value or "").strip().lower()
    if token in _THEME_STYLES:
        return token
    return DEFAULT_THEME_FAMILY


def normalize_theme_mode(value: str | None) -> str:
    token = str(value or "").strip().lower()
    if token in {THEME_MODE_DARK, THEME_MODE_LIGHT}:
        return token
    return DEFAULT_THEME_MODE


def theme_display_name(family: str) -> str:
    normalized = normalize_theme_family(family)
    return _THEME_DISPLAY_NAMES.get(normalized, "Classic")


def load_theme_preferences() -> dict[str, str]:
    path = _preferences_path()
    if not path.exists():
        return {
            "theme_family": DEFAULT_THEME_FAMILY,
            "theme_mode": DEFAULT_THEME_MODE,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    family = normalize_theme_family(str(payload.get("theme_family", "")))
    mode = normalize_theme_mode(str(payload.get("theme_mode", "")))
    return {
        "theme_family": family,
        "theme_mode": mode,
    }


def save_theme_preferences(family: str, mode: str) -> None:
    normalized_family = normalize_theme_family(family)
    normalized_mode = normalize_theme_mode(mode)
    path = _preferences_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "theme_family": normalized_family,
                    "theme_mode": normalized_mode,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def _qss_for_theme(family: str, mode: str) -> str:
    resolved_family = normalize_theme_family(family)
    resolved_mode = normalize_theme_mode(mode)
    return _THEME_STYLES[resolved_family][resolved_mode]


def get_active_theme_state(app: QApplication | None = None) -> tuple[str, str]:
    target_app = app or QApplication.instance()
    if target_app is not None:
        family_prop = target_app.property(_THEME_FAMILY_PROP)
        mode_prop = target_app.property(_THEME_MODE_PROP)
        family = normalize_theme_family(str(family_prop or ""))
        mode = normalize_theme_mode(str(mode_prop or ""))
        if family_prop is not None and mode_prop is not None:
            return family, mode
    prefs = load_theme_preferences()
    return prefs["theme_family"], prefs["theme_mode"]


def apply_theme(
    *,
    family: str | None = None,
    mode: str | None = None,
    persist: bool = True,
    status_bar: Optional[QStatusBar] = None,
) -> tuple[str, str]:
    app = QApplication.instance()
    if app is None:
        return (
            normalize_theme_family(family),
            normalize_theme_mode(mode),
        )

    current_family, current_mode = get_active_theme_state(app)
    resolved_family = normalize_theme_family(family or current_family)
    resolved_mode = normalize_theme_mode(mode or current_mode)
    app.setStyleSheet(_qss_for_theme(resolved_family, resolved_mode))
    app.setProperty(_THEME_FAMILY_PROP, resolved_family)
    app.setProperty(_THEME_MODE_PROP, resolved_mode)

    if persist:
        save_theme_preferences(resolved_family, resolved_mode)

    if status_bar is not None:
        mode_label = "Dark" if resolved_mode == THEME_MODE_DARK else "Light"
        status_bar.showMessage(f"{theme_display_name(resolved_family)} {mode_label}")

    return resolved_family, resolved_mode


def apply_saved_theme(status_bar: Optional[QStatusBar] = None) -> tuple[str, str]:
    prefs = load_theme_preferences()
    return apply_theme(
        family=prefs["theme_family"],
        mode=prefs["theme_mode"],
        persist=False,
        status_bar=status_bar,
    )


def set_theme_family(
    family: str,
    *,
    persist: bool = True,
    status_bar: Optional[QStatusBar] = None,
) -> tuple[str, str]:
    _, current_mode = get_active_theme_state()
    return apply_theme(
        family=family,
        mode=current_mode,
        persist=persist,
        status_bar=status_bar,
    )


def set_theme_mode(
    mode: str,
    *,
    persist: bool = True,
    status_bar: Optional[QStatusBar] = None,
) -> tuple[str, str]:
    current_family, _ = get_active_theme_state()
    return apply_theme(
        family=current_family,
        mode=mode,
        persist=persist,
        status_bar=status_bar,
    )


def toggle_theme_mode(
    *,
    persist: bool = True,
    status_bar: Optional[QStatusBar] = None,
) -> tuple[str, str]:
    current_family, current_mode = get_active_theme_state()
    next_mode = (
        THEME_MODE_LIGHT
        if current_mode == THEME_MODE_DARK
        else THEME_MODE_DARK
    )
    return apply_theme(
        family=current_family,
        mode=next_mode,
        persist=persist,
        status_bar=status_bar,
    )


def _toggle_theme(status_bar: Optional[QStatusBar] = None) -> None:
    """Backward-compatible mode toggle helper."""
    toggle_theme_mode(status_bar=status_bar)


__all__ = [
    "CLASSIC_DARK_QSS",
    "CLASSIC_LIGHT_QSS",
    "DARK_QSS",
    "DEFAULT_THEME_FAMILY",
    "DEFAULT_THEME_MODE",
    "LIGHT_QSS",
    "THEME_FAMILY_CLASSIC",
    "THEME_FAMILY_ENHANCED_WARM",
    "THEME_MODE_DARK",
    "THEME_MODE_LIGHT",
    "_toggle_theme",
    "apply_saved_theme",
    "apply_theme",
    "available_theme_families",
    "get_active_theme_state",
    "load_theme_preferences",
    "save_theme_preferences",
    "set_theme_family",
    "set_theme_mode",
    "theme_display_name",
    "toggle_theme_mode",
]
