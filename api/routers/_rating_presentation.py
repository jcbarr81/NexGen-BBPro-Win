"""Shared rating/overall/star formatting for the list-view routers.

Mirrors the transforms the PyQt UI applied in ``position_players_dialog``,
``pitchers_dialog``, ``free_agency_window``, and ``draft_console`` so the
React client sees the same scaled/bucketed numbers regardless of which
endpoint produced them. The profile view-model (``ui/player_profile_v2_view
model.py``) owns its own transform; this helper exists for list views.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from ui.star_rating import star_text
from utils.rating_display import rating_display_details, rating_display_value


_HITTER_OVERALL_KEYS: Tuple[str, ...] = (
    "ch",
    "ph",
    "sp",
    "pl",
    "vl",
    "sc",
    "fa",
    "arm",
    "gf",
)
_PITCHER_OVERALL_KEYS: Tuple[str, ...] = (
    "endurance",
    "control",
    "movement",
    "hold_runner",
    "arm",
    "fa",
    "fb",
    "cu",
    "cb",
    "sl",
    "si",
    "scb",
    "kn",
)
_PITCH_KEYS = {"fb", "cu", "cb", "sl", "si", "scb", "kn"}


def scale_rating(
    raw: Any,
    *,
    key: str,
    position: Optional[str],
    is_pitcher: bool,
) -> Any:
    """Run a single raw rating through position-aware 35-99 scaling."""

    if raw in (None, "", 0):
        return raw
    try:
        scaled = rating_display_value(
            raw,
            key=key.upper(),
            position=position,
            is_pitcher=is_pitcher,
            mode="scale_99",
        )
        return int(round(float(scaled)))
    except (TypeError, ValueError):
        return raw


def rating_context(
    raw: Any,
    *,
    key: str,
    position: Optional[str],
    is_pitcher: bool,
) -> Optional[Dict[str, Any]]:
    """Position-bucket percentile info for a hitter rating (None for
    pitchers or missing values). Mirrors the ``use_position_context=True``
    branch in PyQt's position_players_dialog."""

    if is_pitcher or raw in (None, "", 0):
        return None
    try:
        _display_val, top_pct, avg, bucket = rating_display_details(
            raw,
            key=key.upper(),
            position=position,
            is_pitcher=False,
            mode="scale_99",
            curve=None,
            use_position_bucket=True,
        )
    except (TypeError, ValueError):
        return None
    if top_pct is None:
        return None
    return {
        "top_pct": int(top_pct),
        "bucket": bucket or (position or "").upper() or None,
        "avg": None if avg is None else int(round(float(avg))),
    }


def compute_overall(
    get_raw: Callable[[str], Any],
    *,
    is_pitcher: bool,
    position: Optional[str],
) -> Dict[str, Any]:
    """Compute the raw + display overall + star-text for a player.

    ``get_raw`` abstracts over player objects (``getattr``) and CSV row
    dicts (``row.get``) so every list-view router can share one code path.
    Returns a dict with ``overall_raw``, ``overall_display``, and
    ``overall_stars_text`` (all nullable when ratings are absent).
    """

    keys = _PITCHER_OVERALL_KEYS if is_pitcher else _HITTER_OVERALL_KEYS
    values: list[float] = []
    for key in keys:
        raw = get_raw(key)
        try:
            numeric = float(raw or 0)
        except (TypeError, ValueError):
            continue
        if key in _PITCH_KEYS and numeric <= 0:
            continue
        values.append(numeric)
    if not values:
        return {
            "overall_raw": None,
            "overall_display": None,
            "overall_stars_text": None,
        }
    raw_overall = max(0, min(99, int(round(sum(values) / len(values)))))
    try:
        scaled = rating_display_value(
            raw_overall,
            key="OVR",
            position=position,
            is_pitcher=is_pitcher,
            mode="scale_99",
        )
        display_overall = int(round(float(scaled)))
    except (TypeError, ValueError):
        display_overall = raw_overall
    star_source = display_overall if display_overall is not None else raw_overall
    stars = star_text(star_source, min_rating=35.0, max_rating=99.0)
    return {
        "overall_raw": raw_overall,
        "overall_display": display_overall,
        "overall_stars_text": stars,
    }


__all__ = ["scale_rating", "rating_context", "compute_overall"]
