"""Utilities for determining pitcher roles."""

from __future__ import annotations
from typing import Any

# A pitcher with endurance ABOVE this is a starter (SP), otherwise a reliever
# (RP). This is the single source of truth for the SP/RP split — keep every
# consumer (generation, draft, client) using it so a pitcher's role is
# consistent everywhere.
ENDURANCE_THRESHOLD = 55

def _get_attr(obj: Any, attr: str, default: Any = None) -> Any:
    """Return attribute or dict key value from *obj* if present."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)

def role_from_endurance(endurance: Any) -> str:
    """Return ``"SP"``/``"RP"`` from an endurance rating (``""`` if unknown)."""
    try:
        en = int(endurance)
    except (TypeError, ValueError):
        return ""
    return "SP" if en > ENDURANCE_THRESHOLD else "RP"

def get_role(pitcher: Any) -> str:
    """Return the role for *pitcher* as ``"SP"`` or ``"RP"``.

    Endurance is the source of truth: a stored ``role`` can be stale (it never
    re-derives as endurance drifts) or mislabeled at generation (reliever
    archetypes used to force high-endurance arms to RP), which is why a team's
    highest-endurance pitcher could show as a reliever. Determination order:
    1. An explicit ``primary_position`` of ``"SP"``/``"RP"`` wins.
    2. Otherwise derive from ``endurance`` via :data:`ENDURANCE_THRESHOLD`.
    3. Only if endurance is unknown, fall back to a stored ``role``.

    If *pitcher* does not appear to be a pitcher, an empty string is returned.
    Accepts either objects with attributes or dictionaries with matching keys.
    """

    primary = str(_get_attr(pitcher, "primary_position", "")).upper()
    if primary in {"SP", "RP"}:
        return primary
    if primary and primary not in {"SP", "RP", "P"}:
        return ""

    role = role_from_endurance(_get_attr(pitcher, "endurance"))
    if role:
        return role

    stored = str(_get_attr(pitcher, "role", "")).upper()
    if stored in {"SP", "RP"}:
        return stored
    return ""


def get_display_role(pitcher: Any) -> str:
    """Return the preferred pitching role if set, falling back to ``get_role``."""

    preferred = str(_get_attr(pitcher, "preferred_pitching_role", "")).upper().strip()
    if preferred:
        return preferred
    return get_role(pitcher)
