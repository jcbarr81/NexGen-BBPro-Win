"""Shared design tokens for NexGen-BBPro UI — single source of truth.

Import colour constants and apply_status() from here instead of
hard-coding hex values or calling setStyleSheet() with inline colours.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Core palette  (keep in sync with theme QSS f-strings)
# ---------------------------------------------------------------------------
ESPRESSO   = "#1e1207"
DEEP_ROAST = "#160e04"
MAHOGANY   = "#462d0d"
WALNUT     = "#604d33"
BARK       = "#3b2810"
TAN        = "#968d7d"
CREAM      = "#fffdf0"
PARCHMENT  = "#fff7dc"
AMBER      = "#F59E0B"
AMBER_DIM  = "#b36b18"
AMBER_TEXT = "#d4a76a"  # lighter amber for text on dark backgrounds
RED        = "#C8102E"
NAVY       = "#0A3161"
GREEN      = "#2f9e44"
CHARCOAL   = "#1F2937"

# ---------------------------------------------------------------------------
# Semantic status colours
# Use these via apply_status() rather than setStyleSheet("color: …")
# ---------------------------------------------------------------------------
STATUS_SUCCESS = GREEN       # "#2f9e44"
STATUS_WARNING = "#e67700"
STATUS_DANGER  = "#c92a2a"
STATUS_MUTED   = "#6c757d"
TEXT_SUBTLE    = "#888888"
TEXT_DIM       = "#b8b8b8"


# ---------------------------------------------------------------------------
# Status utility
# ---------------------------------------------------------------------------
def apply_status(widget: Any, status: str) -> None:
    """Apply a semantic status colour to *widget* via QSS dynamic property.

    Recognised values: ``"success"``, ``"warning"``, ``"danger"``,
    ``"muted"``, ``""`` (clears any active status).

    This avoids inline setStyleSheet colour strings and keeps colour
    definitions inside the theme QSS where they respond to theme changes.
    Widgets that should also carry a fixed font-weight should be given the
    ``"StatusLabel"`` object name so the corresponding QSS rule applies.
    """
    widget.setProperty("status", status)
    try:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
    except Exception:
        pass
