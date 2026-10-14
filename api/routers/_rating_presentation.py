"""Shared rating/overall/star formatting for the list-view routers.

Mirrors the transforms the PyQt UI applied in ``position_players_dialog``,
``pitchers_dialog``, ``free_agency_window``, and ``draft_console`` so the
React client sees the same scaled/bucketed numbers regardless of which
endpoint produced them. The profile view-model (``ui/player_profile_v2_view
model.py``) owns its own transform; this helper exists for list views.

Every helper takes the page's rating ``scale`` (:func:`page_scale`, once per
request): ``None`` or 1 is today's percentile blend, unchanged; 2 shows the
stored rating and the stretched overall (``utils.rating_display``). The
value a helper is handed must already be on that scale
(:func:`page_reader`).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from utils.pitcher_role import get_role
from utils.player_overall import overall_score
from utils.rating_display import (
    display_reader,
    display_scale_for,
    league_display_scale,
    rating_display_details,
    rating_display_value,
)
from utils.rating_scale import LEGACY_RATING_SCALE
from utils.star_rating import overall_star_text, star_text


def page_scale() -> Optional[int]:
    """The rating scale this league's pages are shown on (``None`` for a
    league with no players file, or one split evenly between scales: each
    player is then shown on his own row's scale)."""

    return league_display_scale()


def page_reader(player: Any, league_scale: Optional[int]) -> tuple[int, Callable[[str], Any]]:
    """``(scale, reader)`` for showing ``player`` on the page: the scale he
    is shown on and a reader of his ratings on it (the plain attribute or
    row reader for a player stored on that scale, which is every player
    outside a mixed file)."""

    scale = display_scale_for(player, league_scale)
    return scale, display_reader(player, scale)


def _full(scale: Optional[int]) -> bool:
    return scale is not None and scale != LEGACY_RATING_SCALE


def scale_rating(
    raw: Any,
    *,
    key: str,
    position: Optional[str],
    is_pitcher: bool,
    scale: Optional[int] = None,
) -> Any:
    """Run a single raw rating through position-aware 35-99 scaling (scale
    1), or show it as stored (scale 2)."""

    if raw in (None, "", 0):
        return raw
    try:
        scaled = rating_display_value(
            raw,
            key=key.upper(),
            position=position,
            is_pitcher=is_pitcher,
            mode="scale_99",
            scale=scale if _full(scale) else None,
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
    scale: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Position-bucket percentile info for a hitter rating (None for
    pitchers or missing values). Mirrors the ``use_position_context=True``
    branch in PyQt's position_players_dialog. On scale 2 the average is the
    bucket's average stored rating."""

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
            scale=scale if _full(scale) else None,
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
    scale: Optional[int] = None,
) -> int:
    """Percentile-scale the continuous shared overall against the league's
    distribution of the same score (``utils.rating_display`` shows it raw
    when that distribution's SD is under ~3, audit H8). On scale 2, the
    fixed stretch ``utils.rating_display.full_scale_overall``."""

    try:
        scaled = rating_display_value(
            score,
            key="OVR",
            position=position,
            is_pitcher=is_pitcher,
            mode="scale_99",
            scale=scale if _full(scale) else None,
        )
        return int(round(float(scaled)))
    except (TypeError, ValueError):
        return max(0, min(99, int(round(score))))


def compute_overall(
    get_raw: Callable[[str], Any],
    *,
    is_pitcher: bool,
    position: Optional[str],
    scale: Optional[int] = None,
) -> Dict[str, Any]:
    """Compute the raw + display overall + star-text for a player.

    ``get_raw`` abstracts over player objects (``getattr``) and CSV row
    dicts (``row.get``) so every list-view router can share one code path.
    Returns a dict with ``overall_raw``, ``overall_display``, and
    ``overall_stars_text`` (all nullable when ratings are absent).

    Both sides use the shared production-weighted score from
    ``utils.player_overall`` (audit H8/M14) -- the same number CPU
    auto-assign and trade evaluation rank by. ``overall_raw`` is that score
    rounded, on the engine scale whatever the page's ``scale``;
    ``overall_display`` is it percentile-scaled (scale 1) or stretched
    (scale 2), and the stars follow the shown value. The old top-4 leg (65%
    of hitter OVR) and the flat pitcher average are gone. Pitcher role (for
    the starter endurance adjustment) is read through ``get_raw`` as well.
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
        score, is_pitcher=is_pitcher, position=position, scale=scale
    )
    star_source = display_overall
    if _full(scale):
        stars = overall_star_text(star_source, scale=scale)
    else:
        stars = star_text(star_source, min_rating=35.0, max_rating=99.0)
    return {
        "overall_raw": raw_overall,
        "overall_display": display_overall,
        "overall_stars_text": stars,
    }


__all__ = [
    "compute_overall",
    "page_reader",
    "page_scale",
    "rating_context",
    "scale_rating",
]
