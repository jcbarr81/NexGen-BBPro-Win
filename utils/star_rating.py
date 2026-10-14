"""Pure-Python star-rating helpers shared by the FastAPI sidecar and the
PyQt UI.

The Qt-dependent rendering helpers (``star_pixmap``, ``star_label``) still
live in ``ui/star_rating.py`` and re-export ``star_rating_value`` and
``star_text`` from this module so there is a single source of truth.
"""

from __future__ import annotations

import math
from typing import Optional


def _quantize_stars(value: float) -> float:
    return math.floor(value * 2 + 0.5) / 2.0


def star_rating_value(
    value: object,
    *,
    min_rating: float = 0.0,
    max_rating: float = 99.0,
) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if max_rating <= min_rating:
        return 1.0
    clamped = max(min_rating, min(max_rating, numeric))
    normalized = (clamped - min_rating) / (max_rating - min_rating)
    stars = 1.0 + normalized * 4.0
    stars = _quantize_stars(stars)
    return max(1.0, min(5.0, stars))


def star_text(
    value: object,
    *,
    min_rating: float = 0.0,
    max_rating: float = 99.0,
) -> Optional[str]:
    stars = star_rating_value(value, min_rating=min_rating, max_rating=max_rating)
    return _stars_as_text(stars)


def _stars_as_text(stars: Optional[float]) -> Optional[str]:
    if stars is None:
        return None
    if stars.is_integer():
        return str(int(stars))
    return f"{stars:.1f}"


# Stars for the overall a rating scale 2 page shows
# (``utils.rating_display.full_scale_overall``): the lowest shown overall
# that earns each star count. Re-anchored so a scale 2 league hands out
# stars about as a scale 1 league does today (measured 2026-10-14 on the
# calibration and league fixtures and stats-clean, pooled: today's linear
# 35-99 stars over the percentile-blended overall give 1 / 1.5 / 2 / 2.5 /
# 3 / 3.5 / 4 stars to 2 / 23 / 17 / 14 / 16 / 25 / 2.5 percent of
# players and nobody 4.5 or 5; these cut-offs give 2 / 24 / 17 / 13 / 16 /
# 24 / 2.4). 4.5 and 5 stay out of reach of every league measured, as today,
# and are kept for the rare overall above the 88-92 a league's best reads.
FULL_SCALE_STAR_CUTOFFS = (
    (97, 5.0),
    (92, 4.5),
    (77, 4.0),
    (59, 3.5),
    (52, 3.0),
    (48, 2.5),
    (43, 2.0),
    (26, 1.5),
)


def full_scale_star_value(value: object) -> Optional[float]:
    """Stars for a scale 2 shown overall (1 to 5 in halves)."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    for cutoff, stars in FULL_SCALE_STAR_CUTOFFS:
        if numeric >= cutoff:
            return stars
    return 1.0


def full_scale_star_text(value: object) -> Optional[str]:
    """:func:`full_scale_star_value` as the text the payloads carry."""

    return _stars_as_text(full_scale_star_value(value))


def overall_star_text(value: object, *, scale: Optional[int] = None) -> Optional[str]:
    """Stars for a shown overall on a page of rating ``scale``: the linear
    35-99 stars on scale 1 (``None``), the cut-offs above on scale 2."""

    if scale is None or scale == 1:
        return star_text(value, min_rating=35.0, max_rating=99.0)
    return full_scale_star_text(value)


__all__ = [
    "FULL_SCALE_STAR_CUTOFFS",
    "full_scale_star_text",
    "full_scale_star_value",
    "overall_star_text",
    "star_rating_value",
    "star_text",
]
