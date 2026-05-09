"""Shared rating/overall/star formatting for the list-view routers.

Mirrors the transforms the PyQt UI applied in ``position_players_dialog``,
``pitchers_dialog``, ``free_agency_window``, and ``draft_console`` so the
React client sees the same scaled/bucketed numbers regardless of which
endpoint produced them. The profile view-model (``ui/player_profile_v2_view
model.py``) owns its own transform; this helper exists for list views.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from utils.star_rating import star_text
from utils.path_utils import get_base_dir
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


_DEFAULT_HITTER_WEIGHTS: Dict[str, float] = {
    "ch": 2.0, "ph": 2.0, "eye": 1.5, "sp": 1.5,
    "fa": 1.5, "arm": 1.0,
    "pl": 0.5, "vl": 0.5, "sc": 0.5, "gf": 0.5,
}


_DEFAULT_TOP_N = 4
_DEFAULT_TOP_N_BLEND = 0.65


@lru_cache(maxsize=1)
def _load_hitter_weight_table() -> Tuple[
    Dict[str, float], Dict[str, Dict[str, float]], int, float
]:
    """Read ``config/rating_weights.json`` once and cache it. Returns a
    tuple of ``(default_weights, position_weights, top_n, top_n_blend)``.
    Falls back to the in-code defaults if the file is missing or
    malformed — that way a bad edit can't 500 the whole roster API.
    """

    path = get_base_dir() / "config" / "rating_weights.json"
    if not path.exists():
        return (
            dict(_DEFAULT_HITTER_WEIGHTS),
            {},
            _DEFAULT_TOP_N,
            _DEFAULT_TOP_N_BLEND,
        )
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return (
            dict(_DEFAULT_HITTER_WEIGHTS),
            {},
            _DEFAULT_TOP_N,
            _DEFAULT_TOP_N_BLEND,
        )

    raw_default = data.get("default") if isinstance(data, Mapping) else None
    if isinstance(raw_default, Mapping):
        default = {
            str(k): float(v)
            for k, v in raw_default.items()
            if isinstance(v, (int, float))
        }
    else:
        default = dict(_DEFAULT_HITTER_WEIGHTS)

    raw_positions = data.get("positions") if isinstance(data, Mapping) else None
    positions: Dict[str, Dict[str, float]] = {}
    if isinstance(raw_positions, Mapping):
        for pos, weights in raw_positions.items():
            if isinstance(weights, Mapping):
                positions[str(pos).upper()] = {
                    str(k): float(v)
                    for k, v in weights.items()
                    if isinstance(v, (int, float))
                }

    raw_top_n = data.get("top_n") if isinstance(data, Mapping) else None
    try:
        top_n = max(1, int(raw_top_n)) if raw_top_n is not None else _DEFAULT_TOP_N
    except (TypeError, ValueError):
        top_n = _DEFAULT_TOP_N

    raw_blend = data.get("top_n_blend") if isinstance(data, Mapping) else None
    try:
        top_n_blend = (
            max(0.0, min(1.0, float(raw_blend)))
            if raw_blend is not None
            else _DEFAULT_TOP_N_BLEND
        )
    except (TypeError, ValueError):
        top_n_blend = _DEFAULT_TOP_N_BLEND

    return default, positions, top_n, top_n_blend


def _hitter_weights_for(position: Optional[str]) -> Dict[str, float]:
    default, positions, _top_n, _blend = _load_hitter_weight_table()
    pos = (position or "").strip().upper()
    return positions.get(pos, default)


def _compute_hitter_overall(
    get_raw: Callable[[str], Any],
    position: Optional[str],
) -> Tuple[Optional[int], Optional[int]]:
    """Compute hitter OVR by blending two views of the player's
    *displayed* (already percentile-scaled) ratings:

    1. **Top-N average** — the average of the player's N best displayed
       ratings. Rewards specialists with elite skills (a slugger gets
       credit for elite contact + power even if his glove is a 35).
    2. **Position-weighted average** — keeps positional context so a
       glove-only SS isn't reduced to "what's your top-4 average"
       alone.

    The blend ratio is configurable in ``config/rating_weights.json``
    via ``top_n_blend`` (default 0.65 = 65% top-N, 35% position-
    weighted). Both legs use displayed values, so the headline OVR
    can never disagree with the per-rating cards rendered next to it.
    """

    weights = _hitter_weights_for(position)
    _default_w, _position_w, top_n, top_n_blend = _load_hitter_weight_table()

    raw_values: list[float] = []
    display_values: list[float] = []
    weighted_sum = 0.0
    weight_sum = 0.0

    for key in _HITTER_OVERALL_KEYS:
        try:
            raw_numeric = float(get_raw(key) or 0)
        except (TypeError, ValueError):
            continue
        raw_values.append(raw_numeric)

        # Use the *displayed* value (percentile-scaled per stat) so the
        # OVR is always comparable to the per-stat numbers the UI shows.
        try:
            scaled = rating_display_value(
                raw_numeric,
                key=key.upper(),
                position=position,
                is_pitcher=False,
                mode="scale_99",
            )
            display_numeric = float(scaled)
        except (TypeError, ValueError):
            display_numeric = raw_numeric
        display_values.append(display_numeric)

        weight = float(weights.get(key, 0.0))
        if weight > 0:
            weighted_sum += display_numeric * weight
            weight_sum += weight

    if not raw_values:
        return None, None

    raw_overall = max(0, min(99, int(round(sum(raw_values) / len(raw_values)))))

    # Position-weighted leg.
    if weight_sum > 0:
        weighted_avg = weighted_sum / weight_sum
    elif display_values:
        weighted_avg = sum(display_values) / len(display_values)
    else:
        weighted_avg = float(raw_overall)

    # Top-N leg — rewards elite specialists.
    if display_values:
        sorted_display = sorted(display_values, reverse=True)
        n = max(1, min(top_n, len(sorted_display)))
        top_avg = sum(sorted_display[:n]) / n
    else:
        top_avg = weighted_avg

    blended = top_n_blend * top_avg + (1.0 - top_n_blend) * weighted_avg
    display_overall = max(0, min(99, int(round(blended))))
    return raw_overall, display_overall


def _compute_pitcher_overall(
    get_raw: Callable[[str], Any],
    position: Optional[str],
) -> Tuple[Optional[int], Optional[int]]:
    """Pitcher OVR keeps the existing pitch-mix-aware logic — a pitcher
    who throws four pitches isn't averaged down by zeros for the pitches
    he doesn't use. The display value still goes through the percentile
    rescale because the pitcher distribution doesn't have the same
    cluster-around-50 problem the hitter side does.
    """

    values: list[float] = []
    for key in _PITCHER_OVERALL_KEYS:
        try:
            numeric = float(get_raw(key) or 0)
        except (TypeError, ValueError):
            continue
        if key in _PITCH_KEYS and numeric <= 0:
            continue
        values.append(numeric)
    if not values:
        return None, None
    raw_overall = max(0, min(99, int(round(sum(values) / len(values)))))
    try:
        scaled = rating_display_value(
            raw_overall,
            key="OVR",
            position=position,
            is_pitcher=True,
            mode="scale_99",
        )
        display_overall = int(round(float(scaled)))
    except (TypeError, ValueError):
        display_overall = raw_overall
    return raw_overall, display_overall


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

    Hitters use a position-weighted average of the *displayed* (scaled)
    ratings — the weights live in ``config/rating_weights.json`` so
    commissioners can tune them without a rebuild. Pitchers continue to
    use the legacy pitch-mix-aware percentile rescale.
    """

    if is_pitcher:
        raw_overall, display_overall = _compute_pitcher_overall(get_raw, position)
    else:
        raw_overall, display_overall = _compute_hitter_overall(get_raw, position)

    if raw_overall is None:
        return {
            "overall_raw": None,
            "overall_display": None,
            "overall_stars_text": None,
        }
    star_source = display_overall if display_overall is not None else raw_overall
    stars = star_text(star_source, min_rating=35.0, max_rating=99.0)
    return {
        "overall_raw": raw_overall,
        "overall_display": display_overall,
        "overall_stars_text": stars,
    }


__all__ = ["scale_rating", "rating_context", "compute_overall"]
