"""
NexGen BBPro — Newspaper / Print Editorial Theme  (theme_newspaper.py)

Aesthetic direction:
  - Black ink on newsprint white — like a 1950s sports section front page
  - High-contrast serif-influenced typography via Georgia / Times New Roman
  - Ruled lines instead of filled backgrounds for dividers
  - Red accent (#C8102E) used sparingly — like a headline ink stamp
  - Button style: bordered black outlines, no fill, ink-stamp press effect
  - Sidebar: black with reversed-out white type, thick left border per item

Usage:
    from theme_newspaper import NEWSPAPER_DARK_QSS, NEWSPAPER_LIGHT_QSS
    app.setStyleSheet(NEWSPAPER_DARK_QSS)

Object names honoured (same as theme_enhanced.py plus new ones):
    #Sidebar, #NavButton, #Header, #Title, #Scoreboard, #Card,
    #SectionTitle, #MetricLabel, #MetricValue, #ActionButton,
    #StatBadge, #VersionBadge
"""

from __future__ import annotations

from typing import Optional
from PyQt6.QtWidgets import QApplication, QStatusBar

# ── Palette ───────────────────────────────────────────────────────────────
_INK        = "#0a0a0a"      # near-black for text / borders
_PRESS      = "#1a1a1a"      # sidebar / pressed state
_RULE       = "#2e2e2e"      # dividing rules in dark mode
_NEWSPRINT  = "#f4f0e6"      # warm off-white page colour
_PAPER      = "#ede8dc"      # slightly darker parchment
_BYLINE     = "#5a5040"      # subdued label colour (light mode)
_STAMP_RED  = "#C8102E"      # headline red
_SCORE_RED  = "#a00020"      # darker red for scores
_AMBER      = "#b36b18"      # interactive amber (light mode only)
_WHITE      = "#f8f6f0"      # reversed text on black

# ── LIGHT (Newsprint) ─────────────────────────────────────────────────────
NEWSPAPER_LIGHT_QSS = f"""
/* ── Base ─────────────────────────────────────────────────────────────── */
QWidget {{
    background: {_NEWSPRINT};
    color: {_INK};
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 14px;
    font-weight: 400;
}}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
#Sidebar {{
    background: {_INK};
    border-right: 3px solid {_STAMP_RED};
}}
#Sidebar QLabel {{
    color: rgba(248,246,240,0.45);
    font-family: 'Georgia', serif;
    font-weight: 700;
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 14px 14px 4px 16px;
    border-bottom: 1px solid rgba(248,246,240,0.12);
}}

#NavButton {{
    color: rgba(248,246,240,0.65);
    background: transparent;
    padding: 9px 14px 9px 18px;
    margin: 1px 6px;
    border-radius: 0px;
    text-align: left;
    font-family: 'Georgia', serif;
    font-size: 13px;
    font-weight: 400;
    border-left: 3px solid transparent;
    border-bottom: 1px solid rgba(248,246,240,0.07);
}}
#NavButton:hover {{
    color: {_WHITE};
    background: rgba(248,246,240,0.06);
    border-left: 3px solid {_STAMP_RED};
}}
#NavButton:checked {{
    color: {_WHITE};
    background: rgba(200,16,46,0.15);
    border-left: 3px solid {_STAMP_RED};
    font-weight: 700;
}}

/* ── Header ───────────────────────────────────────────────────────────── */
#Header {{
    background: {_NEWSPRINT};
    border-bottom: 3px solid {_INK};
}}
#Title {{
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 1px;
    color: {_INK};
    text-transform: uppercase;
}}
#Scoreboard {{
    background: {_INK};
    color: {_WHITE};
    border-radius: 2px;
    padding: 5px 14px;
    font-family: 'Courier New', monospace;
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 0.5px;
}}

/* ── Cards ────────────────────────────────────────────────────────────── */
QFrame#Card {{
    background: {_NEWSPRINT};
    border: 2px solid {_INK};
    border-radius: 0px;
}}

/* ── Section titles ───────────────────────────────────────────────────── */
QLabel#SectionTitle {{
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: {_INK};
    border-bottom: 3px double {_INK};
    padding-bottom: 4px;
}}

/* ── Metric labels ────────────────────────────────────────────────────── */
QLabel#MetricLabel {{
    font-family: 'Courier New', monospace;
    font-size: 10px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: {_BYLINE};
    font-weight: 400;
}}
QLabel#MetricLabel[variant="leader"] {{
    font-size: 9px;
    letter-spacing: 1px;
}}
QLabel#MetricValue {{
    font-family: 'Georgia', serif;
    font-size: 28px;
    font-weight: 700;
    color: {_INK};
}}
QLabel#MetricValue[interactive="true"] {{ color: {_AMBER}; }}
QLabel#MetricValue[interactive="true"][highlight="true"] {{ color: {_STAMP_RED}; }}
QLabel#MetricValue[variant="leader"] {{
    font-size: 17px;
    font-weight: 700;
}}
QLabel#MetricValue[highlight="true"] {{ color: {_STAMP_RED}; }}

#StatBadge {{
    background: {_INK};
    color: {_WHITE};
    border-radius: 0px;
    padding: 2px 8px;
    font-family: 'Courier New', monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}

/* ── Action buttons ───────────────────────────────────────────────────── */
QPushButton#ActionButton {{
    background: {_NEWSPRINT};
    color: {_INK};
    border: 2px solid {_INK};
    border-radius: 0px;
    padding: 9px 8px;
    font-family: 'Georgia', serif;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}}
QPushButton#ActionButton:hover {{
    background: {_INK};
    color: {_WHITE};
}}
QPushButton#ActionButton:pressed {{
    background: {_PRESS};
    color: {_WHITE};
    border-color: {_PRESS};
    padding-top: 11px;
    padding-bottom: 7px;
}}

/* ── Generic buttons ──────────────────────────────────────────────────── */
QPushButton {{
    background: {_NEWSPRINT};
    color: {_INK};
    border: 2px solid {_INK};
    border-radius: 0px;
    padding: 7px 14px;
    font-family: 'Georgia', serif;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
QPushButton:hover {{ background: {_PAPER}; border-color: {_STAMP_RED}; color: {_STAMP_RED}; }}
QPushButton:pressed {{ background: {_INK}; color: {_WHITE}; }}

QPushButton#Primary {{
    background: {_INK};
    color: {_WHITE};
    border: 2px solid {_INK};
    border-radius: 0px;
    padding: 10px 16px;
    font-weight: 700;
    font-family: 'Georgia', serif;
}}
QPushButton#Primary:hover {{ background: {_PRESS}; border-color: {_PRESS}; }}
QPushButton#Primary:pressed {{ background: #000; }}

QPushButton#Success {{
    background: {_NEWSPRINT};
    color: #1a6e2a;
    border: 2px solid #1a6e2a;
    border-radius: 0px;
    padding: 12px 18px;
    font-size: 14px;
    font-weight: 700;
    font-family: 'Georgia', serif;
}}
QPushButton#Success:hover {{ background: #1a6e2a; color: {_WHITE}; }}
QPushButton#Success:pressed {{ background: #0f4e1e; color: {_WHITE}; }}

QPushButton#Danger {{
    background: {_NEWSPRINT};
    color: {_STAMP_RED};
    border: 2px solid {_STAMP_RED};
    border-radius: 0px;
    padding: 10px 16px;
    font-weight: 700;
    font-family: 'Georgia', serif;
}}
QPushButton#Danger:hover {{ background: {_STAMP_RED}; color: {_WHITE}; }}
QPushButton#Danger:pressed {{ background: {_SCORE_RED}; color: {_WHITE}; }}

/* ── Depth chart list ─────────────────────────────────────────────────── */
QListWidget#DepthChartList {{
    background: {_NEWSPRINT};
    border: 2px solid {_INK};
    border-radius: 0px;
    padding: 4px;
    font-family: 'Courier New', monospace;
}}
QListWidget#DepthChartList::item {{
    padding: 5px 8px;
    color: {_INK};
    border-bottom: 1px solid rgba(10,10,10,0.15);
}}
QListWidget#DepthChartList::item:selected {{
    background: {_INK};
    color: {_WHITE};
}}
QListWidget#DepthChartList::item:hover:!selected {{
    background: {_PAPER};
}}

/* ── Status / version ─────────────────────────────────────────────────── */
QStatusBar {{
    background: {_NEWSPRINT};
    border-top: 2px solid {_INK};
    font-family: 'Courier New', monospace;
    font-size: 11px;
    color: {_BYLINE};
}}
#VersionBadge {{
    color: {_INK};
    background: transparent;
    border: 1px solid {_INK};
    border-radius: 0px;
    padding: 2px 10px;
    font-family: 'Courier New', monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
"""

# ── DARK (Printing Press) ─────────────────────────────────────────────────
NEWSPAPER_DARK_QSS = f"""
QWidget {{
    background: {_INK};
    color: {_WHITE};
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 14px;
    font-weight: 400;
}}

#Sidebar {{
    background: #050505;
    border-right: 3px solid {_STAMP_RED};
}}
#Sidebar QLabel {{
    color: rgba(248,246,240,0.35);
    font-family: 'Georgia', serif;
    font-weight: 700;
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 14px 14px 4px 16px;
    border-bottom: 1px solid rgba(248,246,240,0.08);
}}

#NavButton {{
    color: rgba(248,246,240,0.55);
    background: transparent;
    padding: 9px 14px 9px 18px;
    margin: 1px 6px;
    border-radius: 0px;
    text-align: left;
    font-family: 'Georgia', serif;
    font-size: 13px;
    font-weight: 400;
    border-left: 3px solid transparent;
    border-bottom: 1px solid rgba(248,246,240,0.05);
}}
#NavButton:hover {{
    color: {_WHITE};
    background: rgba(248,246,240,0.04);
    border-left: 3px solid {_STAMP_RED};
}}
#NavButton:checked {{
    color: {_WHITE};
    background: rgba(200,16,46,0.12);
    border-left: 3px solid {_STAMP_RED};
    font-weight: 700;
}}

#Header {{
    background: #050505;
    border-bottom: 3px solid {_STAMP_RED};
}}
#Title {{
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 1px;
    color: {_WHITE};
    text-transform: uppercase;
}}
#Scoreboard {{
    background: transparent;
    color: {_WHITE};
    border: 1px solid rgba(248,246,240,0.25);
    border-radius: 0px;
    padding: 5px 14px;
    font-family: 'Courier New', monospace;
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 0.5px;
}}

QFrame#Card {{
    background: #111111;
    border: 1px solid rgba(248,246,240,0.12);
    border-top: 1px solid rgba(248,246,240,0.06);
    border-radius: 0px;
}}

QLabel#SectionTitle {{
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: {_WHITE};
    border-bottom: 1px solid {_STAMP_RED};
    padding-bottom: 4px;
}}

QLabel#MetricLabel {{
    font-family: 'Courier New', monospace;
    font-size: 10px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: rgba(248,246,240,0.4);
    font-weight: 400;
}}
QLabel#MetricLabel[variant="leader"] {{
    font-size: 9px;
    letter-spacing: 1px;
    color: rgba(248,246,240,0.5);
}}
QLabel#MetricValue {{
    font-family: 'Georgia', serif;
    font-size: 28px;
    font-weight: 700;
    color: {_WHITE};
}}
QLabel#MetricValue[interactive="true"] {{ color: #f1c27d; }}
QLabel#MetricValue[interactive="true"][highlight="true"] {{ color: {_STAMP_RED}; }}
QLabel#MetricValue[variant="leader"] {{
    font-size: 17px;
    font-weight: 700;
}}
QLabel#MetricValue[highlight="true"] {{ color: {_STAMP_RED}; }}

#StatBadge {{
    background: transparent;
    color: {_WHITE};
    border: 1px solid rgba(248,246,240,0.35);
    border-radius: 0px;
    padding: 2px 8px;
    font-family: 'Courier New', monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}

QPushButton#ActionButton {{
    background: transparent;
    color: {_WHITE};
    border: 1px solid rgba(248,246,240,0.25);
    border-radius: 0px;
    padding: 9px 8px;
    font-family: 'Georgia', serif;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}}
QPushButton#ActionButton:hover {{
    background: rgba(248,246,240,0.07);
    border-color: {_STAMP_RED};
    color: {_WHITE};
}}
QPushButton#ActionButton:pressed {{
    background: rgba(200,16,46,0.15);
    border-color: {_STAMP_RED};
    color: {_STAMP_RED};
}}

QPushButton {{
    background: transparent;
    color: {_WHITE};
    border: 1px solid rgba(248,246,240,0.25);
    border-radius: 0px;
    padding: 7px 14px;
    font-family: 'Georgia', serif;
    font-weight: 400;
}}
QPushButton:hover {{ border-color: {_STAMP_RED}; color: {_STAMP_RED}; }}
QPushButton:pressed {{ background: rgba(200,16,46,0.1); }}

QPushButton#Primary {{
    background: {_WHITE};
    color: {_INK};
    border: none;
    border-radius: 0px;
    padding: 10px 16px;
    font-weight: 700;
    font-family: 'Georgia', serif;
}}
QPushButton#Primary:hover {{ background: #e0ddd5; }}
QPushButton#Primary:pressed {{ background: #c0bdb5; }}

QPushButton#Success {{
    background: transparent;
    color: #4ec46a;
    border: 1px solid #4ec46a;
    border-radius: 0px;
    padding: 12px 18px;
    font-size: 14px;
    font-weight: 700;
    font-family: 'Georgia', serif;
}}
QPushButton#Success:hover {{ background: #4ec46a; color: {_INK}; }}
QPushButton#Success:pressed {{ background: #2f9e44; color: {_WHITE}; }}

QPushButton#Danger {{
    background: transparent;
    color: {_STAMP_RED};
    border: 1px solid {_STAMP_RED};
    border-radius: 0px;
    padding: 10px 16px;
    font-weight: 700;
    font-family: 'Georgia', serif;
}}
QPushButton#Danger:hover {{ background: {_STAMP_RED}; color: {_WHITE}; }}
QPushButton#Danger:pressed {{ background: {_SCORE_RED}; color: {_WHITE}; }}

QListWidget#DepthChartList {{
    background: #111111;
    border: 1px solid rgba(248,246,240,0.15);
    border-radius: 0px;
    padding: 4px;
    font-family: 'Courier New', monospace;
}}
QListWidget#DepthChartList::item {{
    padding: 5px 8px;
    color: {_WHITE};
    border-bottom: 1px solid rgba(248,246,240,0.07);
}}
QListWidget#DepthChartList::item:selected {{
    background: {_STAMP_RED};
    color: {_WHITE};
}}
QListWidget#DepthChartList::item:hover:!selected {{
    background: rgba(248,246,240,0.05);
}}

QStatusBar {{
    background: #050505;
    border-top: 1px solid {_STAMP_RED};
    font-family: 'Courier New', monospace;
    font-size: 11px;
    color: rgba(248,246,240,0.4);
}}
#VersionBadge {{
    color: rgba(248,246,240,0.5);
    background: transparent;
    border: 1px solid rgba(248,246,240,0.2);
    border-radius: 0px;
    padding: 2px 10px;
    font-family: 'Courier New', monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
"""


def _toggle_newspaper_theme(status_bar: Optional[QStatusBar] = None) -> None:
    """Toggle between newspaper light and dark themes."""
    app = QApplication.instance()
    if app is None:
        return
    is_dark = "0a0a0a" in app.styleSheet() and "background: #0a0a0a" in app.styleSheet()
    new_sheet = NEWSPAPER_LIGHT_QSS if is_dark else NEWSPAPER_DARK_QSS
    app.setStyleSheet(new_sheet)
    if status_bar is not None:
        status_bar.showMessage("Newsprint (light)" if is_dark else "Press (dark)")
