from __future__ import annotations

from bisect import bisect_left
import csv
from functools import lru_cache
import math
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models.pitcher import Pitcher
from models.player import Player
from utils.path_utils import get_data_dir
from utils.pitcher_role import get_role
from utils.player_overall import (
    hitter_overall_score,
    pitcher_overall_score,
    player_overall_score,
)

DISPLAY_ENV = "PB_RATING_DISPLAY"
RAW_BLEND_ENV = "PB_RATING_DISPLAY_RAW_BLEND"
# Fraction of the displayed value contributed by the *raw* underlying
# rating (vs. the percentile-rescaled one). Default 0.5 means a player
# with raw 63 in a stat ends up displayed as ``0.5 * 63 + 0.5 * scaled``,
# which keeps the league percentile signal visible but stops the display
# from inflating raw 63 all the way to 99 when the league distribution
# is tightly clustered around 50. Override via PB_RATING_DISPLAY_RAW_BLEND
# at sidecar launch (no rebuild needed). Set to 0.0 for the legacy
# pure-percentile behavior; 1.0 effectively disables the rescale.
#
# Note: this only affects what users see on the UI. The simulator reads
# raw player attrs directly, so changes here have zero impact on stat
# output, BABIP, ERA, or anything the engine produces.
_DEFAULT_RAW_BLEND = 0.5

# Below this league SD the overall is shown raw instead of percentile-scaled
# (audit H8): stretching a ~1-point spread manufactures 30-point gaps.
OVERALL_MIN_SPREAD = 3.0


def _get_raw_blend() -> float:
    raw = os.getenv(RAW_BLEND_ENV)
    if raw is None:
        return _DEFAULT_RAW_BLEND
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_RAW_BLEND
    return max(0.0, min(1.0, value))

_ABBREV_MAP = {
    "as": "arm",
    "en": "endurance",
    "co": "control",
    "mo": "movement",
    "mv": "movement",
    "ovr": "overall",
}

_PITCH_KEYS = {"fb", "sl", "cu", "cb", "si", "scb", "kn"}
_HITTER_KEYS = {key for key in Player._rating_fields if not key.startswith("pot_")}
_PITCHER_KEYS = {key for key in Pitcher._rating_fields if not key.startswith("pot_")}
_EXTRA_KEYS = {"overall"}
_ALL_KEYS = _HITTER_KEYS | _PITCHER_KEYS | _EXTRA_KEYS

# These lists now only select the hitter vs pitcher formula in
# ``_overall_from_row``; the weights live in ``utils.player_overall``.
_HITTER_OVERALL_KEYS = (
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
_PITCHER_OVERALL_KEYS = (
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

POSITION_BUCKETS = ("C", "1B", "2B", "3B", "SS", "OF")

_POSITION_MAP = {
    "LF": "OF",
    "CF": "OF",
    "RF": "OF",
}


def _rating_source_path() -> Path:
    base_dir = get_data_dir()
    normalized = base_dir / "players_normalized.csv"
    if normalized.exists():
        return normalized
    return base_dir / "players.csv"


def _distribution_source_key() -> tuple[str, int | None, int | None]:
    path = _rating_source_path()
    resolved = path.resolve(strict=False)
    try:
        stat_result = resolved.stat()
    except OSError:
        return str(resolved), None, None
    mtime_ns = getattr(stat_result, "st_mtime_ns", None)
    if mtime_ns is None:
        mtime_ns = int(stat_result.st_mtime * 1_000_000_000)
    return str(resolved), mtime_ns, stat_result.st_size


def overall_rating(player: object) -> int:
    """The shared production-weighted overall, rounded (audit H8/M14).

    Feeds the depth-chart autofill sort and roster-fill comparisons, so it
    must rank players the same way the displayed OVR and CPU logic do.
    """

    score = player_overall_score(player)
    if score is None:
        return 0
    return max(0, min(99, int(round(score))))


def _overall_from_row(row: Dict[str, object], keys: Tuple[str, ...]) -> Optional[float]:
    """Shared overall for one players.csv row, for the league distribution.

    ``keys`` picks the hitter or pitcher formula (callers pass
    ``_PITCHER_OVERALL_KEYS`` or ``_HITTER_OVERALL_KEYS``). The score stays
    continuous so the percentile scale is built from the same numbers the
    per-player display looks up -- percentile-stretching a rounded integer
    put pitchers one raw point apart 10-15 display points apart (H8).
    """

    if keys == _PITCHER_OVERALL_KEYS:
        score = pitcher_overall_score(row.get, get_role(row))
    else:
        score = hitter_overall_score(row.get, row.get("primary_position"))
    if score is None:
        return None
    return round(score, 2)


@lru_cache(maxsize=8)
def _load_distributions(
    source_key: tuple[str, int | None, int | None],
) -> Dict[str, Dict[str, Dict[str, List[int]]]]:
    distributions = {
        "hitters": {key: [] for key in _HITTER_KEYS | _EXTRA_KEYS},
        "pitchers": {key: [] for key in _PITCHER_KEYS | _EXTRA_KEYS},
        "all": {key: [] for key in _ALL_KEYS},
        "hitters_by_bucket": {
            bucket: {key: [] for key in _HITTER_KEYS | _EXTRA_KEYS}
            for bucket in POSITION_BUCKETS
        },
    }
    path = Path(source_key[0])
    if not path.exists():
        return distributions

    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            is_pitcher = str(row.get("is_pitcher", "0")).strip().lower() in {
                "1",
                "true",
                "yes",
            }
            keys = _PITCHER_KEYS if is_pitcher else _HITTER_KEYS
            pos_bucket = None
            if not is_pitcher:
                pos_bucket = _normalize_position_bucket(
                    row.get("primary_position")
                )
            for key in keys:
                raw = row.get(key)
                if raw in (None, ""):
                    continue
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if key in _PITCH_KEYS and value <= 0:
                    continue
                rating = int(round(value))
                distributions["all"][key].append(rating)
                if is_pitcher:
                    distributions["pitchers"][key].append(rating)
                else:
                    distributions["hitters"][key].append(rating)
                    if pos_bucket:
                        distributions["hitters_by_bucket"][pos_bucket][key].append(
                            rating
                        )
            overall_keys = _PITCHER_OVERALL_KEYS if is_pitcher else _HITTER_OVERALL_KEYS
            overall_val = _overall_from_row(row, overall_keys)
            if overall_val is not None:
                distributions["all"]["overall"].append(overall_val)
                if is_pitcher:
                    distributions["pitchers"]["overall"].append(overall_val)
                else:
                    distributions["hitters"]["overall"].append(overall_val)
                    if pos_bucket:
                        distributions["hitters_by_bucket"][pos_bucket]["overall"].append(
                            overall_val
                        )

    for group in distributions.values():
        if group:
            for values in group.values():
                if isinstance(values, dict):
                    for inner in values.values():
                        inner.sort()
                else:
                    values.sort()
    return distributions


def _normalize_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    token = key.strip().lower()
    token = token.replace("/", " ").replace("-", " ").replace(":", " ")
    token = " ".join(token.split())
    token = token.replace(" ", "_")
    if token.startswith("pot_"):
        token = token[4:]
    return _ABBREV_MAP.get(token, token)


def _percentile(values: List[int], value: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return 1.0
    idx = bisect_left(values, value)
    if idx <= 0:
        return 0.0
    if idx >= len(values) - 1:
        return 1.0
    return idx / (len(values) - 1)


def _normalize_position_bucket(position: Optional[str]) -> Optional[str]:
    if not position:
        return None
    token = str(position).strip().upper()
    token = _POSITION_MAP.get(token, token)
    if token in POSITION_BUCKETS:
        return token
    return None


def _average(values: List[int]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _spread(values: List[float]) -> float:
    """Population SD (plain arithmetic: ``statistics`` is slow per row)."""

    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _logistic_curve(pct: float, k: float) -> float:
    pct = max(0.0, min(1.0, pct))
    raw = 1.0 / (1.0 + math.exp(-k * (pct - 0.5)))
    min_val = 1.0 / (1.0 + math.exp(k * 0.5))
    max_val = 1.0 / (1.0 + math.exp(-k * 0.5))
    if max_val == min_val:
        return pct
    return (raw - min_val) / (max_val - min_val)


def _select_distribution(
    key: str,
    is_pitcher: Optional[bool],
    *,
    position_bucket: Optional[str] = None,
    use_position_bucket: bool = False,
) -> List[int]:
    distributions = _load_distributions(_distribution_source_key())
    if is_pitcher is False and position_bucket and use_position_bucket:
        values = distributions["hitters_by_bucket"].get(position_bucket, {}).get(key, [])
        if values:
            return values
    if is_pitcher is True:
        values = distributions["pitchers"].get(key, [])
    elif is_pitcher is False:
        values = distributions["hitters"].get(key, [])
    else:
        values = distributions["all"].get(key, [])
    if values:
        return values
    if is_pitcher is not None:
        return distributions["all"].get(key, [])
    return (
        distributions["pitchers"].get(key, [])
        or distributions["hitters"].get(key, [])
        or []
    )


def _normalize_mode(raw: str) -> str:
    token = (raw or "").strip().lower()
    if not token:
        return "scale_99"
    if token in {"raw", "backend", "normalized"}:
        return "raw"
    if token in {
        "99",
        "0-99",
        "scale_99",
        "display_99",
        "percentile",
        "percentile_99",
    }:
        return "scale_99"
    if token in {"stars", "star", "asterisks", "asterisk"}:
        return "stars"
    return "scale_99"


def get_display_mode(override: Optional[str] = None) -> str:
    if override is not None:
        return _normalize_mode(override)
    return _normalize_mode(os.getenv(DISPLAY_ENV, "scale_99"))


def rating_display_details(
    value: object,
    *,
    key: Optional[str] = None,
    position: Optional[str] = None,
    is_pitcher: Optional[bool] = None,
    mode: Optional[str] = None,
    curve: Optional[str] = "logistic",
    curve_k: float = 6.0,
    display_min: int = 35,
    display_max: int = 99,
    use_position_bucket: bool = False,
) -> Tuple[object, Optional[int], Optional[float], Optional[str]]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ("" if value is None else str(value)), None, None, None

    display_mode = get_display_mode(mode)
    normalized_key = _normalize_key(key)
    if display_mode == "raw" or not normalized_key:
        return int(round(numeric)), None, None, None

    if normalized_key in _PITCH_KEYS and numeric <= 0:
        return 0, None, None, None

    bucket = _normalize_position_bucket(position) if is_pitcher is False else None
    values = _select_distribution(
        normalized_key,
        is_pitcher,
        position_bucket=bucket,
        use_position_bucket=use_position_bucket,
    )
    pct = _percentile(values, numeric)
    avg = _average(values)
    if pct is None:
        return int(round(numeric)), None, avg, bucket

    adj_pct = pct
    if curve == "logistic":
        adj_pct = _logistic_curve(pct, curve_k)

    if display_mode == "stars":
        stars = min(5, max(1, int(pct * 5) + 1))
        top_pct = int(round((1.0 - pct) * 100))
        top_pct = max(1, min(99, top_pct))
        return "*" * stars, top_pct, avg, bucket

    if normalized_key == "overall" and _spread(values) < OVERALL_MIN_SPREAD:
        # A league whose overalls barely differ (alpha's compressed pitchers:
        # raw 52-56 shown as 44-77, H8) is shown raw rather than stretched,
        # so players who perform alike are displayed alike.
        top_pct = max(1, min(99, int(round((1.0 - pct) * 100))))
        shown = max(display_min, min(display_max, int(round(numeric))))
        return shown, top_pct, avg, bucket

    scale_span = max(1, display_max - display_min)
    scaled_pct = display_min + adj_pct * scale_span
    # Hybrid: blend the raw rating with the percentile-rescaled value so
    # the display reflects what the player actually has (raw signal)
    # while still surfacing where they sit in the league (percentile
    # signal). Pure percentile inflated mediocre raws to 99 because the
    # league distribution clusters tightly around 50; pure raw lost the
    # comparative reading entirely. The 70/30 default (raw / percentile)
    # gives both. ``PB_RATING_DISPLAY_RAW_BLEND=0`` reverts to legacy.
    raw_blend = _get_raw_blend()
    blended = raw_blend * numeric + (1.0 - raw_blend) * scaled_pct
    scaled = int(round(blended))
    top_pct = int(round((1.0 - pct) * 100))
    top_pct = max(1, min(99, top_pct))
    return (
        max(display_min, min(display_max, scaled)),
        top_pct,
        avg,
        bucket,
    )


def rating_display_value(
    value: object,
    *,
    key: Optional[str] = None,
    position: Optional[str] = None,
    is_pitcher: Optional[bool] = None,
    mode: Optional[str] = None,
    curve: Optional[str] = "logistic",
    curve_k: float = 6.0,
    display_min: int = 35,
    display_max: int = 99,
    use_position_bucket: bool = False,
) -> object:
    display_value, _top_pct, _avg, _bucket = rating_display_details(
        value,
        key=key,
        position=position,
        is_pitcher=is_pitcher,
        mode=mode,
        curve=curve,
        curve_k=curve_k,
        display_min=display_min,
        display_max=display_max,
        use_position_bucket=use_position_bucket,
    )
    return display_value


def rating_display_text(
    value: object,
    *,
    key: Optional[str] = None,
    position: Optional[str] = None,
    is_pitcher: Optional[bool] = None,
    mode: Optional[str] = None,
    curve: Optional[str] = "logistic",
    curve_k: float = 6.0,
    display_min: int = 35,
    display_max: int = 99,
    use_position_bucket: bool = False,
) -> str:
    return str(
        rating_display_value(
            value,
            key=key,
            position=position,
            is_pitcher=is_pitcher,
            mode=mode,
            curve=curve,
            curve_k=curve_k,
            display_min=display_min,
            display_max=display_max,
            use_position_bucket=use_position_bucket,
        )
    )
