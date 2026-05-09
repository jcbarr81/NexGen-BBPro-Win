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
    if stars is None:
        return None
    if stars.is_integer():
        return str(int(stars))
    return f"{stars:.1f}"


__all__ = ["star_rating_value", "star_text"]
