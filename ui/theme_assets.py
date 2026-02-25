from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from utils.path_utils import get_base_dir
import ui.theme as app_theme

try:  # pragma: no cover - exercised via UI runtime
    from PyQt6.QtCore import QByteArray, Qt
    from PyQt6.QtGui import QIcon, QPainter, QPixmap
    from PyQt6.QtSvg import QSvgRenderer
except Exception:  # pragma: no cover - headless test fallback
    QByteArray = None  # type: ignore[assignment]
    Qt = None  # type: ignore[assignment]
    QIcon = None  # type: ignore[assignment]
    QPainter = None  # type: ignore[assignment]
    QPixmap = None  # type: ignore[assignment]
    QSvgRenderer = None  # type: ignore[assignment]


SVG_NAMESPACE = "http://www.w3.org/2000/svg"
ICONS_PATH = get_base_dir() / "assets" / "graphics" / "icons.svg"

ENHANCED_NAV_ICON_IDS: dict[str, str] = {
    "dashboard": "icon-dashboard",
    "home": "icon-dashboard",
    "roster": "icon-roster",
    "team": "icon-team",
    "teams": "icon-team",
    "records": "icon-records",
    "transactions": "icon-trades",
    "league": "icon-league",
    "season": "icon-league",
    "draft": "icon-admin",
    "users": "icon-admin",
    "settings": "icon-admin",
    "finance": "icon-records",
    "utils": "icon-league",
}

ENHANCED_OWNER_ACTION_ICON_IDS: dict[str, str] = {
    "Lineups": "btn-lineups",
    "Depth Chart": "btn-depth",
    "Training Focus": "btn-settings",
    "Pitching Staff": "btn-settings",
    "Reassign Players": "btn-transactions",
    "Recent Transactions": "btn-transactions",
    "Team Settings": "btn-settings",
    "Full Roster": "btn-stats",
    "Team Injuries": "btn-injuries",
    "Team Stats": "btn-stats",
    "League Leaders": "btn-leaders",
    "League Standings": "btn-standings",
    "Team Schedule": "btn-schedule",
    "Draft Console": "btn-draft",
    "Playoffs Viewer": "btn-playoffs",
}

ENHANCED_ADMIN_ACTION_ICON_IDS: dict[str, str] = {
    "Review Trades": "btn-transactions",
    "Review Change Requests": "btn-settings",
    "Review GM Finance Queue": "btn-stats",
    "Open Season Hub": "btn-schedule",
    "Open Draft Hub": "btn-draft",
}


class _NullIcon:
    def isNull(self) -> bool:
        return True


def _empty_icon() -> Any:
    if QIcon is None:
        return _NullIcon()
    return QIcon()


def _theme_family_enhanced() -> str:
    return str(
        getattr(app_theme, "THEME_FAMILY_ENHANCED_WARM", "enhanced_warm")
    )


def _theme_mode_dark() -> str:
    return str(getattr(app_theme, "THEME_MODE_DARK", "dark"))


def _current_theme_state() -> tuple[str, str]:
    getter = getattr(app_theme, "get_active_theme_state", None)
    if callable(getter):
        try:
            family, mode = getter()
            return str(family), str(mode)
        except Exception:
            pass
    return ("classic", "dark")


def is_enhanced_theme_active() -> bool:
    family, _mode = _current_theme_state()
    return family == _theme_family_enhanced()


def _icon_color_for_mode() -> str:
    _family, mode = _current_theme_state()
    if mode == _theme_mode_dark():
        return "#fffdf0"
    return "#462d0d"


@lru_cache(maxsize=1)
def _icons_xml() -> str:
    if not ICONS_PATH.exists():
        return ""
    try:
        return ICONS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def _iter_svg_roots() -> list[ET.Element]:
    xml_text = _icons_xml()
    if not xml_text:
        return []
    wrapped = f"<root>{xml_text}</root>"
    try:
        root = ET.fromstring(wrapped)
    except ET.ParseError:
        return []
    return list(root)


def _extract_symbol_svg(symbol_id: str) -> str:
    for svg_root in _iter_svg_roots():
        for symbol in svg_root.findall(f".//{{{SVG_NAMESPACE}}}symbol"):
            if symbol.attrib.get("id") != symbol_id:
                continue
            view_box = symbol.attrib.get("viewBox", "0 0 24 24")
            inner = "".join(
                ET.tostring(child, encoding="unicode")
                for child in list(symbol)
            )
            return (
                '<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="{view_box}" fill="none" stroke="currentColor" '
                'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                f"{inner}</svg>"
            )
    return ""


def _extract_standalone_svg(icon_id: str) -> str:
    for svg_root in _iter_svg_roots():
        if svg_root.attrib.get("id") != icon_id:
            continue
        svg_root.attrib.pop("id", None)
        return ET.tostring(svg_root, encoding="unicode")
    return ""


def _render_svg_icon(svg_text: str, *, size: int, color: str) -> Any:
    if not svg_text:
        return _empty_icon()
    if (
        QIcon is None
        or QPixmap is None
        or QPainter is None
        or QSvgRenderer is None
        or QByteArray is None
        or Qt is None
    ):
        return _empty_icon()

    try:
        rendered = (
            svg_text.replace("currentColor", color)
            .replace("#fffdf0", color)
            .replace("#462d0d", color)
        )
        renderer = QSvgRenderer(QByteArray(rendered.encode("utf-8")))
        if not renderer.isValid():
            return _empty_icon()
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception:
        return _empty_icon()


@lru_cache(maxsize=256)
def _cached_nav_icon(key: str, size: int, color: str) -> Any:
    symbol_id = ENHANCED_NAV_ICON_IDS.get(key, "")
    if not symbol_id:
        return _empty_icon()
    svg_text = _extract_symbol_svg(symbol_id)
    return _render_svg_icon(svg_text, size=size, color=color)


@lru_cache(maxsize=256)
def _cached_action_icon(icon_id: str, size: int, color: str) -> Any:
    svg_text = _extract_standalone_svg(icon_id)
    return _render_svg_icon(svg_text, size=size, color=color)


def load_enhanced_nav_icon(key: str, size: int = 24) -> Any:
    if not is_enhanced_theme_active():
        return _empty_icon()
    safe_size = max(8, int(size))
    color = _icon_color_for_mode()
    return _cached_nav_icon(str(key).strip().lower(), safe_size, color)


def load_enhanced_owner_action_icon(label: str, size: int = 18) -> Any:
    if not is_enhanced_theme_active():
        return _empty_icon()
    icon_id = ENHANCED_OWNER_ACTION_ICON_IDS.get(str(label).strip(), "")
    if not icon_id:
        return _empty_icon()
    color = _icon_color_for_mode()
    return _cached_action_icon(icon_id, max(8, int(size)), color)


def load_enhanced_admin_action_icon(label: str, size: int = 18) -> Any:
    if not is_enhanced_theme_active():
        return _empty_icon()
    icon_id = ENHANCED_ADMIN_ACTION_ICON_IDS.get(str(label).strip(), "")
    if not icon_id:
        return _empty_icon()
    color = _icon_color_for_mode()
    return _cached_action_icon(icon_id, max(8, int(size)), color)
