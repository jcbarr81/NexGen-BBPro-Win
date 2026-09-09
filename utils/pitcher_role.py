"""Utilities for determining pitcher roles."""

from __future__ import annotations
from typing import Any

# A pitcher with endurance ABOVE this is a starter (SP), otherwise a reliever
# (RP). This is the FALLBACK for the SP/RP split — keep every consumer
# (generation, draft, client) using this module so a pitcher's role is
# consistent everywhere.
#
# Endurance alone cannot staff a league. On the healthy calibration seed
# (endurance 25-75) only 83 of 390 pitchers clear this bar, while a 20-team
# league needs 100 starters. On a league carrying the older compressed seed it
# is worse than useless: alpha-test's pitchers run 48-54, so NOT ONE of its 460
# arms classifies as a starter, and every consumer — the rotation builder,
# auto-assign, pitching auto-fill, the draft AI, the stats split — silently
# behaved as though the league had no starting pitchers at all.
ENDURANCE_THRESHOLD = 55

# What a declared role means for the SP/RP split. ``preferred_pitching_role``
# is set at generation from the pitcher's archetype and is editable by the
# owner in the pitching-staff editor, so it is a statement of intent rather
# than a guess derived from one rating.
_STARTER_TOKENS = {"SP", "SP1", "SP2", "SP3", "SP4", "SP5", "STARTER"}
_RELIEF_TOKENS = {
    "RP", "CL", "SU", "LR", "MR", "MR1", "MR2", "MR3",
    "CLOSER", "SETUP", "RELIEVER", "LONG",
}

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

def role_from_preferred(value: Any) -> str:
    """Map a declared pitching role onto the ``"SP"``/``"RP"`` split.

    Returns ``""`` for an unrecognised or missing value so callers fall through
    to the next signal rather than guessing.
    """

    token = str(value or "").upper().strip()
    if not token:
        return ""
    if token in _STARTER_TOKENS:
        return "SP"
    if token in _RELIEF_TOKENS:
        return "RP"
    return ""


def get_role(pitcher: Any) -> str:
    """Return the role for *pitcher* as ``"SP"`` or ``"RP"``.

    Determination order, most explicit first:
    1. An explicit ``primary_position`` of ``"SP"``/``"RP"``.
    2. A declared ``preferred_pitching_role`` (SP1-5 / RP / CL / SU / LR / MR).
    3. Otherwise derive from ``endurance`` via :data:`ENDURANCE_THRESHOLD`.
    4. Only if none of those answer, a stored ``role``.

    Step 2 used to be absent, which made endurance the source of truth. That
    was chosen because a stored ``role`` could be stale or mislabeled at
    generation — but it over-corrected onto a DIFFERENT field. A declared
    preference is a statement of intent; endurance is one rating, and deriving
    from it alone under-produces starters even on healthy data and produces
    none at all on a league with compressed ratings. Endurance remains the
    fallback for a pitcher who has never had a role declared.

    If *pitcher* does not appear to be a pitcher, an empty string is returned.
    Accepts either objects with attributes or dictionaries with matching keys.
    """

    primary = str(_get_attr(pitcher, "primary_position", "")).upper()
    if primary in {"SP", "RP"}:
        return primary
    if primary and primary not in {"SP", "RP", "P"}:
        return ""

    preferred = role_from_preferred(_get_attr(pitcher, "preferred_pitching_role"))
    if preferred:
        return preferred

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
