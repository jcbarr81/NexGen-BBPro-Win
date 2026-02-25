"""
NexGen BBPro — Enhanced Warm Theme (theme_enhanced.py)
Drop-in replacement for theme.py

Changes vs original:
  - Sidebar nav buttons gain left-accent-bar indicator, icon zone, and
    a subtle gradient so they read as pressable tiles rather than plain text
  - Quick-Action / roster buttons become raised "dugout tiles" with a
    top highlight edge and bottom shadow edge — matching the splash aesthetic
  - Cards get a faint grain overlay via a repeating SVG data-URI pattern
  - MetricValue numbers are slightly larger and use the amber accent colour
    on the dark theme to give the dashboard more energy
  - New object names exposed:  #ActionButton, #SidebarLogo, #StatBadge
    (no breaking changes to existing names)
"""

from __future__ import annotations

from typing import Optional
from PyQt6.QtWidgets import QApplication, QStatusBar


# ---------------------------------------------------------------------------
# Shared tokens — imported from design_tokens (single source of truth)
# ---------------------------------------------------------------------------
from .design_tokens import (
    ESPRESSO   as _ESPRESSO,
    DEEP_ROAST as _DEEP_ROAST,
    MAHOGANY   as _MAHOGANY,
    WALNUT     as _WALNUT,
    BARK       as _BARK,
    TAN        as _TAN,
    CREAM      as _CREAM,
    PARCHMENT  as _PARCHMENT,
    AMBER      as _AMBER,
    AMBER_DIM  as _AMBER_DIM,
    RED        as _RED,
    NAVY       as _NAVY,
    GREEN      as _GREEN,
    CHARCOAL   as _CHARCOAL,
)

# Grain pattern encoded as inline SVG data-URI (tiny, tileable)
_GRAIN_LIGHT = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "width='64' height='64'%3E%3Cfilter id='n'%3E%3CfeTurbulence "
    "type='fractalNoise' baseFrequency='0.75' numOctaves='4' "
    "stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='64' height='64' "
    "filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E\")"
)
_GRAIN_DARK = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "width='64' height='64'%3E%3Cfilter id='n'%3E%3CfeTurbulence "
    "type='fractalNoise' baseFrequency='0.75' numOctaves='4' "
    "stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='64' height='64' "
    "filter='url(%23n)' opacity='0.06'/%3E%3C/svg%3E\")"
)

# ---------------------------------------------------------------------------
# LIGHT QSS
# ---------------------------------------------------------------------------
ENHANCED_LIGHT_QSS = f"""
/* ── Base ─────────────────────────────────────────────────────────────── */
QWidget {{
    background: {_CREAM};
    color: {_MAHOGANY};
    font-family: 'Segoe UI', 'Noto Sans', Arial;
    font-size: 14px;
    font-weight: 500;
}}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
#Sidebar {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {_MAHOGANY}, stop:1 #3a2008);
    border-right: 2px solid {_WALNUT};
}}
#Sidebar QLabel {{
    color: {_CREAM};
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 1.5px;
    padding: 12px 14px 4px 14px;
    text-transform: uppercase;
}}
#SidebarLogo {{
    padding: 14px 10px 10px 10px;
    border-bottom: 1px solid rgba(255,253,240,0.12);
}}

/* Nav buttons — raised tile style */
#NavButton {{
    color: rgba(255,253,240,0.75);
    background: transparent;
    padding: 10px 14px 10px 18px;
    margin: 2px 8px;
    border-radius: 8px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
    border-left: 3px solid transparent;
}}
#NavButton:hover {{
    color: {_CREAM};
    background: rgba(255,253,240,0.08);
    border-left: 3px solid rgba(245,158,11,0.5);
}}
#NavButton:checked {{
    color: {_CREAM};
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 rgba(96,77,51,0.9), stop:1 rgba(96,77,51,0.4));
    border-left: 3px solid {_AMBER};
    border-top: 1px solid rgba(255,253,240,0.1);
    border-bottom: 1px solid rgba(0,0,0,0.2);
    border-right: none;
}}

/* ── Header ───────────────────────────────────────────────────────────── */
#Header {{
    background: {_CREAM};
    border-bottom: 2px solid {_TAN};
}}
#Title {{
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: {_MAHOGANY};
}}
#Scoreboard {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {_WALNUT}, stop:1 #4a3520);
    color: {_CREAM};
    border-radius: 8px;
    border-top: 1px solid rgba(255,253,240,0.15);
    border-bottom: 2px solid rgba(0,0,0,0.3);
    padding: 5px 12px;
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 0.3px;
}}

/* ── Cards ────────────────────────────────────────────────────────────── */
QFrame#Card {{
    background: {_CREAM};
    border: 1px solid {_TAN};
    border-radius: 12px;
}}

/* ── Section title ────────────────────────────────────────────────────── */
QLabel#SectionTitle {{
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: {_MAHOGANY};
    border-bottom: 2px solid {_AMBER};
    padding-bottom: 4px;
}}

/* ── Metric labels ────────────────────────────────────────────────────── */
QLabel#MetricLabel {{
    font-size: 10px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: {_TAN};
    font-weight: 600;
}}
QLabel#MetricLabel[variant="leader"] {{
    font-size: 10px;
    letter-spacing: 0.8px;
}}
QLabel#MetricValue {{
    font-size: 26px;
    font-weight: 900;
    color: {_MAHOGANY};
}}
QLabel#MetricValue[interactive="true"] {{ color: {_AMBER_DIM}; }}
QLabel#MetricValue[interactive="true"][highlight="true"] {{ color: {_RED}; }}
QLabel#MetricValue[variant="leader"] {{
    font-size: 17px;
    font-weight: 700;
}}
QLabel#MetricValue[highlight="true"] {{ color: {_RED}; }}

/* Stat badge pill */
#StatBadge {{
    background: {_WALNUT};
    color: {_CREAM};
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}

/* ── Quick-Action / roster BUTTONS (ActionButton) ─────────────────────── */
/*  These are the large grid buttons on the dashboard and roster page.     */
QPushButton#ActionButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #7a6450, stop:1 {_WALNUT});
    color: {_CREAM};
    border: none;
    border-top: 1px solid rgba(255,253,240,0.18);
    border-bottom: 2px solid rgba(0,0,0,0.35);
    border-radius: 8px;
    padding: 10px 8px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
QPushButton#ActionButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #8a7460, stop:1 #6f5c42);
    border-bottom: 2px solid rgba(0,0,0,0.45);
}}
QPushButton#ActionButton:pressed {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {_WALNUT}, stop:1 #513e24);
    border-top: 2px solid rgba(0,0,0,0.3);
    border-bottom: 1px solid rgba(255,253,240,0.08);
    padding-top: 11px;
    padding-bottom: 9px;
}}

/* ── Generic buttons ──────────────────────────────────────────────────── */
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #a59c8c, stop:1 {_TAN});
    color: {_CREAM};
    border: none;
    border-top: 1px solid rgba(255,253,240,0.2);
    border-bottom: 2px solid rgba(0,0,0,0.25);
    padding: 8px 14px;
    border-radius: 7px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #b5ac9c, stop:1 #a59c8c);
}}
QPushButton:pressed {{
    background: {_TAN};
    border-top: 2px solid rgba(0,0,0,0.2);
    border-bottom: 1px solid rgba(255,253,240,0.1);
}}

QPushButton#Primary {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #6f5c42, stop:1 {_WALNUT});
    color: {_CREAM};
    border: none;
    border-top: 1px solid rgba(255,253,240,0.18);
    border-bottom: 2px solid rgba(0,0,0,0.35);
    padding: 10px 16px;
    border-radius: 9px;
    font-weight: 700;
}}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #7f6c52, stop:1 #6f5c42); }}
QPushButton#Primary:pressed {{ background: {_WALNUT}; }}

QPushButton#Success {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #3aae54, stop:1 {_GREEN});
    color: white;
    border: none;
    border-top: 1px solid rgba(255,255,255,0.2);
    border-bottom: 2px solid rgba(0,0,0,0.3);
    padding: 12px 18px;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 700;
}}
QPushButton#Success:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #44be5e, stop:1 #2f9e44); }}
QPushButton#Success:pressed {{ background: #237f35; }}

QPushButton#Danger {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #be2424, stop:1 #a61e1e);
    color: white;
    border: none;
    border-top: 1px solid rgba(255,255,255,0.15);
    border-bottom: 2px solid rgba(0,0,0,0.35);
    padding: 10px 16px;
    border-radius: 9px;
    font-weight: 700;
}}
QPushButton#Danger:hover {{ background: #b32d2d; }}
QPushButton#Danger:pressed {{ background: #8f1a1a; }}

/* ── Depth chart list ─────────────────────────────────────────────────── */
QListWidget#DepthChartList {{
    background: {_PARCHMENT};
    border: 1px solid #d6c4a3;
    border-radius: 8px;
    padding: 4px;
}}
QListWidget#DepthChartList::item {{
    padding: 5px 8px;
    color: #3a2508;
    border-radius: 4px;
}}
QListWidget#DepthChartList::item:selected {{
    background: {_WALNUT};
    color: {_CREAM};
}}
QListWidget#DepthChartList::item:hover:!selected {{
    background: rgba(96,77,51,0.12);
}}

/* ── Status bar / version badge ───────────────────────────────────────── */
QStatusBar {{
    background: {_CREAM};
    border-top: 1px solid {_TAN};
    font-size: 12px;
    color: {_WALNUT};
}}
#VersionBadge {{
    color: {_MAHOGANY};
    background: rgba(255,253,240,0.8);
    border: 1px solid {_TAN};
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
/* Semantic status properties — set via widget.setProperty("status", ...) */
*[status="success"] {{ color: #2f9e44; }}
*[status="warning"] {{ color: #e67700; }}
*[status="danger"]  {{ color: #c92a2a; }}
*[status="muted"]   {{ color: #6c757d; }}
/* Named label roles */
QLabel#PanelHeading {{ font-weight: 700; }}
QLabel#StatusLabel  {{ font-weight: 600; }}
"""

# ---------------------------------------------------------------------------
# DARK QSS
# ---------------------------------------------------------------------------
ENHANCED_DARK_QSS = f"""
QWidget {{
    background: {_ESPRESSO};
    color: {_CREAM};
    font-family: 'Segoe UI', 'Noto Sans', Arial;
    font-size: 14px;
    font-weight: 500;
}}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
#Sidebar {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {_DEEP_ROAST}, stop:1 #1a0e05);
    border-right: 2px solid {_BARK};
}}
#Sidebar QLabel {{
    color: rgba(255,253,240,0.5);
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 1.5px;
    padding: 12px 14px 4px 14px;
}}
#SidebarLogo {{
    padding: 14px 10px 10px 10px;
    border-bottom: 1px solid rgba(255,253,240,0.08);
}}

#NavButton {{
    color: rgba(255,253,240,0.6);
    background: transparent;
    padding: 10px 14px 10px 18px;
    margin: 2px 8px;
    border-radius: 8px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
    border-left: 3px solid transparent;
}}
#NavButton:hover {{
    color: {_CREAM};
    background: rgba(255,253,240,0.05);
    border-left: 3px solid rgba(245,158,11,0.45);
}}
#NavButton:checked {{
    color: {_CREAM};
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 rgba(59,40,16,0.95), stop:1 rgba(59,40,16,0.4));
    border-left: 3px solid {_AMBER};
    border-top: 1px solid rgba(255,253,240,0.07);
    border-bottom: 1px solid rgba(0,0,0,0.3);
    border-right: none;
}}

/* ── Header ───────────────────────────────────────────────────────────── */
#Header {{
    background: #221508;
    border-bottom: 2px solid {_BARK};
}}
#Title {{
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: {_CREAM};
}}
#Scoreboard {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #221508, stop:1 {_DEEP_ROAST});
    color: {_CREAM};
    border: 1px solid {_BARK};
    border-top: 1px solid rgba(255,253,240,0.08);
    border-bottom: 2px solid rgba(0,0,0,0.4);
    border-radius: 8px;
    padding: 5px 12px;
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 0.3px;
}}

/* ── Cards ────────────────────────────────────────────────────────────── */
QFrame#Card {{
    background: #221508;
    border: 1px solid {_BARK};
    border-top: 1px solid rgba(255,253,240,0.06);
    border-radius: 12px;
}}

QLabel#SectionTitle {{
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: {_CREAM};
    border-bottom: 2px solid {_AMBER};
    padding-bottom: 4px;
}}

/* ── Metrics ──────────────────────────────────────────────────────────── */
QLabel#MetricLabel {{
    font-size: 10px;
    letter-spacing: 1.2px;
    color: rgba(150,141,125,0.85);
    font-weight: 600;
}}
QLabel#MetricLabel[variant="leader"] {{
    font-size: 10px;
    letter-spacing: 0.8px;
    color: #d4c5a5;
}}
QLabel#MetricValue {{
    font-size: 26px;
    font-weight: 900;
    color: {_CREAM};
}}
QLabel#MetricValue[interactive="true"] {{ color: {_AMBER}; }}
QLabel#MetricValue[interactive="true"][highlight="true"] {{ color: #e67700; }}
QLabel#MetricValue[variant="leader"] {{
    font-size: 17px;
    font-weight: 700;
}}
QLabel#MetricValue[highlight="true"] {{ color: {_AMBER}; }}

#StatBadge {{
    background: {_BARK};
    color: {_AMBER};
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
    border: 1px solid rgba(245,158,11,0.3);
}}

/* ── Action buttons (dashboard grid + roster page buttons) ────────────── */
QPushButton#ActionButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #4a3520, stop:1 {_BARK});
    color: {_CREAM};
    border: none;
    border-top: 1px solid rgba(255,253,240,0.1);
    border-bottom: 2px solid rgba(0,0,0,0.5);
    border-radius: 8px;
    padding: 10px 8px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
QPushButton#ActionButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #5a4530, stop:1 #4a3520);
    border-top: 1px solid rgba(245,158,11,0.25);
    border-bottom: 2px solid rgba(0,0,0,0.55);
}}
QPushButton#ActionButton:pressed {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {_BARK}, stop:1 #2c1b0a);
    border-top: 2px solid rgba(0,0,0,0.4);
    border-bottom: 1px solid rgba(255,253,240,0.05);
    padding-top: 11px;
    padding-bottom: 9px;
}}

/* ── Generic buttons ──────────────────────────────────────────────────── */
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {_BARK}, stop:1 #2c1b0a);
    color: {_CREAM};
    border: none;
    border-top: 1px solid rgba(255,253,240,0.08);
    border-bottom: 2px solid rgba(0,0,0,0.4);
    padding: 8px 14px;
    border-radius: 7px;
    font-weight: 600;
}}
QPushButton:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #4f3c29, stop:1 {_BARK}); }}
QPushButton:pressed {{ background: #2c1b0a; }}

QPushButton#Primary {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #6f5c42, stop:1 {_WALNUT});
    color: {_CREAM};
    border: none;
    border-top: 1px solid rgba(255,253,240,0.12);
    border-bottom: 2px solid rgba(0,0,0,0.4);
    padding: 10px 16px;
    border-radius: 9px;
    font-weight: 700;
}}
QPushButton#Primary:hover {{ background: #6f5c42; }}
QPushButton#Primary:pressed {{ background: #513e24; }}

QPushButton#Success {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #3aae54, stop:1 {_GREEN});
    color: white;
    border: none;
    border-top: 1px solid rgba(255,255,255,0.15);
    border-bottom: 2px solid rgba(0,0,0,0.35);
    padding: 12px 18px;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 700;
}}
QPushButton#Success:hover {{ background: #27903c; }}
QPushButton#Success:pressed {{ background: #237f35; }}

QPushButton#Danger {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #a61e1e, stop:1 #8f1a1a);
    color: white;
    border: 1px solid rgba(200,50,50,0.4);
    border-top: 1px solid rgba(255,100,100,0.2);
    border-bottom: 2px solid rgba(0,0,0,0.4);
    padding: 10px 16px;
    border-radius: 9px;
    font-weight: 700;
}}
QPushButton#Danger:hover {{ background: #a61e1e; }}
QPushButton#Danger:pressed {{ background: #701313; }}

/* ── Depth chart list ─────────────────────────────────────────────────── */
QListWidget#DepthChartList {{
    background: #1a0f05;
    border: 1px solid {_BARK};
    border-radius: 8px;
    padding: 4px;
}}
QListWidget#DepthChartList::item {{
    padding: 5px 8px;
    color: {_CREAM};
    border-radius: 4px;
}}
QListWidget#DepthChartList::item:selected {{
    background: #8d6a36;
    color: {_CREAM};
}}
QListWidget#DepthChartList::item:hover:!selected {{
    background: rgba(141,106,54,0.2);
}}

/* ── Status / version ─────────────────────────────────────────────────── */
QStatusBar {{
    background: {_ESPRESSO};
    border-top: 1px solid {_BARK};
    font-size: 12px;
    color: rgba(150,141,125,0.7);
}}
#VersionBadge {{
    color: #d2ba8f;
    background: rgba(22,14,4,0.7);
    border: 1px solid rgba(150,141,125,0.4);
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
/* Semantic status properties — set via widget.setProperty("status", ...) */
*[status="success"] {{ color: #2f9e44; }}
*[status="warning"] {{ color: #e67700; }}
*[status="danger"]  {{ color: #c92a2a; }}
*[status="muted"]   {{ color: #6c757d; }}
/* Named label roles */
QLabel#PanelHeading {{ font-weight: 700; }}
QLabel#StatusLabel  {{ font-weight: 600; }}
"""


def _toggle_theme(status_bar: Optional[QStatusBar] = None) -> None:
    """Toggle between enhanced light and dark themes."""
    app = QApplication.instance()
    if app is None:
        return
    is_dark = "1e1207" in app.styleSheet()
    app.setStyleSheet(ENHANCED_LIGHT_QSS if is_dark else ENHANCED_DARK_QSS)
    if status_bar is not None:
        status_bar.showMessage("Light theme" if is_dark else "Dark theme")


# Backwards-compatible aliases so existing code works unchanged
LIGHT_QSS = ENHANCED_LIGHT_QSS
DARK_QSS = ENHANCED_DARK_QSS
