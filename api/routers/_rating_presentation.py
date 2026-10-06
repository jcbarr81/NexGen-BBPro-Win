"""Shared rating/overall/star formatting for the list-view routers.

Mirrors the transforms the PyQt UI applied in ``position_players_dialog``,
``pitchers_dialog``, ``free_agency_window``, and ``draft_console`` so the
React client sees the same scaled/bucketed numbers regardless of which
endpoint produced them. The profile view-model (``ui/player_profile_v2_view
model.py``) owns its own transform; this helper exists for list views.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from utils.pitcher_role import get_role
from utils.player_overall import overall_score
from utils.star_rating import star_text
from utils.rating_display import rating_display_details, rating_display_value


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


def _display_overall(
    score: float,
    *,
    is_pitcher: bool,
    position: Optional[str],
) -> int:
    """Percentile-scale the continuous shared overall against the league's
    distribution of the same score (``utils.rating_display`` shows it raw
    when that distribution's SD is under ~3, audit H8)."""

    try:
        scaled = rating_display_value(
            score,
            key="OVR",
            position=position,
            is_pitcher=is_pitcher,
            mode="scale_99",
        )
        return int(round(float(scaled)))
    except (TypeError, ValueError):
        return max(0, min(99, int(round(score))))


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

    Both sides use the shared production-weighted score from
    ``utils.player_overall`` (audit H8/M14) -- the same number CPU
    auto-assign and trade evaluation rank by. ``overall_raw`` is that score
    rounded; ``overall_display`` is it percentile-scaled. The old top-4
    leg (65% of hitter OVR) and the flat pitcher average are gone. Pitcher
    role (for the starter endurance adjustment) is read through ``get_raw``
    as well.
    """

    role = None
    if is_pitcher:
        role = get_role(
            {
                "primary_position": position,
                "preferred_pitching_role": get_raw("preferred_pitching_role"),
                "endurance": get_raw("endurance"),
                "role": get_raw("role"),
            }
        )
    score = overall_score(
        get_raw, is_pitcher=is_pitcher, position=position, role=role
    )

    if score is None:
        return {
            "overall_raw": None,
            "overall_display": None,
            "overall_stars_text": None,
        }
    raw_overall = max(0, min(99, int(round(score))))
    display_overall = _display_overall(
        score, is_pitcher=is_pitcher, position=position
    )
    star_source = display_overall
    stars = star_text(star_source, min_rating=35.0, max_rating=99.0)
    return {
        "overall_raw": raw_overall,
        "overall_display": display_overall,
        "overall_stars_text": stars,
    }


__all__ = ["scale_rating", "rating_context", "compute_overall"]
