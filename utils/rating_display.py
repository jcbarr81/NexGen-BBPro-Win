"""What an owner is shown for a rating and for the overall.

Two ways, chosen by the rating scale the league's pages are on
(:func:`league_display_scale`):

* **Scale 1** (every league today): the percentile blend below,
  ``0.5 * stored + 0.5 * (35 + percentile * 64)``, clamped 35-99, and the
  overall percentile-scaled the same way. Unchanged, to the byte.
* **Scale 2** (owner decision 13, ``DECISIONS.md`` "Release 6 owner
  decisions"): the STORED rating as it is, no blend, on every page; the
  overall through :func:`full_scale_overall`, a fixed stretch of the
  engine-scale overall so an average regular reads about 50 and the best
  player in a league about 88-92. The overall every CPU decision reads is
  untouched; this is display only.
"""

from __future__ import annotations

from bisect import bisect_left
import csv
from functools import lru_cache
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from models.pitcher import Pitcher
from models.player import Player
from utils.path_utils import get_data_dir
from utils.pitcher_role import get_role
from utils.player_overall import (
    hitter_overall_score,
    pitcher_overall_score,
    player_overall_score,
)
from utils.rating_scale import (
    FULL_RATING_SCALE,
    KNOWN_RATING_SCALES,
    LEGACY_RATING_SCALE,
    MixedRatingScaleError,
    engine_potential_value,
    engine_row,
    engine_value,
    majority_rating_scale,
    player_is_pitcher,
    players_file_rating_scales,
    rating_map,
    rating_scale_of,
    stretch_row,
    to_stored,
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


# ---------------------------------------------------------------------------
# Scale 2: the overall an owner sees
# ---------------------------------------------------------------------------

class OverallDisplayMap:
    """``shown = 50 + slope * (overall - pivot)``, slope chosen by segment.

    ``overall`` is the shared engine-scale overall
    (``utils.player_overall``). Under the pivot the slope is
    ``slope_below``; from the pivot to ``knee`` it is ``slope_above``; past
    the knee it is ``slope_top``. Rounded half up and kept inside 1-99.
    """

    __slots__ = ("pivot", "slope_below", "slope_above", "knee", "slope_top")

    def __init__(
        self,
        pivot: float,
        slope_below: float,
        slope_above: float,
        knee: float,
        slope_top: float,
    ) -> None:
        self.pivot = pivot
        self.slope_below = slope_below
        self.slope_above = slope_above
        self.knee = knee
        self.slope_top = slope_top

    def exact(self, overall: float) -> float:
        if overall < self.pivot:
            return 50.0 + self.slope_below * (overall - self.pivot)
        if overall <= self.knee:
            return 50.0 + self.slope_above * (overall - self.pivot)
        at_knee = 50.0 + self.slope_above * (self.knee - self.pivot)
        return at_knee + self.slope_top * (overall - self.knee)

    def shown(self, overall: float) -> int:
        return max(1, min(99, int(math.floor(self.exact(overall) + 0.5))))


# Derived from the three KPI fixtures and the stats-clean and alpha-test
# copies (arithmetic on the shared overall, 2026-10-14; the numbers are in
# the r8-display report). The pivots are where the pooled average active
# (ACT) player sits: hitters 50.6, pitchers 53.5. Above the pivot 4 shown
# points per overall point, so the best player of a league with a normal
# spread reads 88-92 (stats-clean: hitter 61.0 -> 90, pitcher 64.1 -> 90;
# alpha-test hitter 61.6 -> 91); past pivot + 9 (shown 86) 2 per point, so a
# league whose best is a point or two higher does not run to 99. Under the
# pivot 2.5 per point, so the weakest one percent of a league (overall
# 38-40) reads 20-25 and nothing but alpha-test's one 29-overall draft pick
# reaches 1. The design's "about x2.5 / x2.65" cannot put any league's best
# above about 80 and was not used.
FULL_SCALE_OVERALL_MAPS: Dict[bool, OverallDisplayMap] = {
    False: OverallDisplayMap(50.0, 2.5, 4.0, 59.0, 2.0),  # hitters
    True: OverallDisplayMap(53.0, 2.5, 4.0, 62.0, 2.0),  # pitchers
}


def full_scale_overall(overall: object, *, is_pitcher: bool) -> Optional[int]:
    """The overall a scale 2 page shows for an engine-scale ``overall``."""

    try:
        numeric = float(overall)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return FULL_SCALE_OVERALL_MAPS[bool(is_pitcher)].shown(numeric)


# ---------------------------------------------------------------------------
# Which scale a league's pages are on, and a player's ratings on it
# ---------------------------------------------------------------------------

def _players_file() -> Path:
    return get_data_dir() / "players.csv"


@lru_cache(maxsize=16)
def _file_display_scale(source_key: tuple[str, int | None, int | None]) -> Optional[int]:
    counts = players_file_rating_scales(source_key[0])
    if not counts:
        return None
    try:
        return majority_rating_scale(counts)
    except MixedRatingScaleError:
        return None


def league_display_scale(path: Optional[Path] = None) -> Optional[int]:
    """The rating scale the league's pages show ratings on.

    The scale most rows of the league's ``players.csv`` are on: after a
    conversion every row is on scale 2, before it every row is on scale 1
    (a file without the ``rating_scale`` column is decided from its header
    alone). A file holding rows on two scales (a stray row appended from an
    old draft class, a restore mid-conversion) still shows ONE scale on
    every page, the one most of its rows are on, and the stray rows are
    re-expressed on it (:func:`display_rating`); an owner never sees two
    scales side by side. ``None`` when there is no file or it is split
    exactly in half: each row is then shown on its own scale.
    """

    target = Path(path) if path is not None else _players_file()
    resolved = target.resolve(strict=False)
    try:
        stat_result = resolved.stat()
    except OSError:
        return None
    mtime_ns = getattr(stat_result, "st_mtime_ns", None)
    if mtime_ns is None:
        mtime_ns = int(stat_result.st_mtime * 1_000_000_000)
    return _file_display_scale((str(resolved), mtime_ns, stat_result.st_size))


def display_scale_for(player: Any, league_scale: Optional[int]) -> int:
    """The scale ``player`` is shown on: the league's, else his row's own."""

    if league_scale in KNOWN_RATING_SCALES:
        return int(league_scale)  # type: ignore[arg-type]
    return rating_scale_of(player)


def _stored(player: Any, key: str, default: Any) -> Any:
    if isinstance(player, dict):
        return player.get(key, default)
    return getattr(player, key, default)


def _is_set(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number > 0


def display_rating(player: Any, key: str, scale: int, default: Any = None) -> Any:
    """Rating ``key`` of ``player`` (an object or a row) as stored on ``scale``.

    A player stored on ``scale`` (every player, outside a mixed file) gets
    exactly ``getattr(player, key, default)`` / ``row.get(key, default)``.
    Otherwise a moved rating is re-expressed: on scale 1 as its engine value,
    on scale 2 as :func:`utils.rating_scale.to_stored` of it; a potential
    keeps its gap above the current rating, as the conversion stores it. A
    rating the scales do not move, a blank and a zero come back as stored.
    """

    value = _stored(player, key, default)
    own = rating_scale_of(player)
    if own == scale or not _is_set(value):
        return value
    pitcher = player_is_pitcher(player)
    base = key[4:] if key.startswith("pot_") else key
    if rating_map(base, FULL_RATING_SCALE, pitcher=pitcher) is None:
        return value
    if key.startswith("pot_"):
        engine_pot = engine_potential_value(player, base, value)
        if scale == LEGACY_RATING_SCALE:
            return engine_pot
        current = _stored(player, base, None)
        if not _is_set(current):
            return value
        engine_cur = float(engine_value(base, current, own, pitcher=pitcher))
        shown = display_rating(player, base, scale)
        gap = max(0.0, float(engine_pot) - engine_cur)
        return max(1, min(99, int(math.floor(float(shown) + gap + 0.5))))
    engine = engine_value(key, value, own, pitcher=pitcher)
    if scale == LEGACY_RATING_SCALE:
        return engine
    return to_stored(key, float(engine), scale, pitcher=pitcher)


def display_reader(player: Any, scale: int):
    """``key -> display_rating(player, key, scale)``; the plain reader when
    the player is stored on ``scale``."""

    if rating_scale_of(player) == scale:
        if isinstance(player, dict):
            return player.get
        return lambda key: getattr(player, key, None)
    return lambda key: display_rating(player, key, scale)


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


def _row_on_scale(row: Dict[str, object], scale: int) -> Dict[str, object]:
    """A source row as a page on ``scale`` reads it (the same row when it is
    already on that scale, which is every row of a one-scale file)."""

    if rating_scale_of(row) == scale:
        return row
    if scale == LEGACY_RATING_SCALE:
        return engine_row(row)  # type: ignore[return-value]
    return stretch_row(engine_row(row), scale)[0]


@lru_cache(maxsize=8)
def _load_distributions(
    source_key: tuple[str, int | None, int | None],
    scale: int = LEGACY_RATING_SCALE,
) -> Dict[str, Dict[str, Dict[str, List[int]]]]:
    """Each rating's league distribution, as stored on ``scale``.

    The overall's distribution is the engine-scale overall on either scale
    (the scale 2 overall is a fixed map of it, see :func:`full_scale_overall`).
    """

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
            # rating-scale: the row is put on the page's scale first
            row = _row_on_scale(row, scale)
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
    scale: int = LEGACY_RATING_SCALE,
) -> List[int]:
    if scale == LEGACY_RATING_SCALE:
        distributions = _load_distributions(_distribution_source_key())
    else:
        distributions = _load_distributions(_distribution_source_key(), scale)
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
    scale: Optional[int] = None,
) -> Tuple[object, Optional[int], Optional[float], Optional[str]]:
    """``(shown, top percent, league average, position bucket)`` for one
    value.

    ``scale`` is the scale of the page (:func:`league_display_scale`) and
    ``value`` must already be on it (:func:`display_rating`); ``None`` or 1
    is the scale 1 percentile blend. On scale 2 a rating is shown as stored
    (rounded, inside 1-99) and the overall, whose ``value`` is always the
    engine-scale overall, through :func:`full_scale_overall`; the top
    percent and the average are still worked out, against the league's
    ratings as stored on scale 2.
    """

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

    full_scale = scale is not None and scale != LEGACY_RATING_SCALE
    bucket = _normalize_position_bucket(position) if is_pitcher is False else None
    values = _select_distribution(
        normalized_key,
        is_pitcher,
        position_bucket=bucket,
        use_position_bucket=use_position_bucket,
        scale=FULL_RATING_SCALE if full_scale else LEGACY_RATING_SCALE,
    )
    pct = _percentile(values, numeric)
    avg = _average(values)
    if full_scale and display_mode != "stars":
        if normalized_key == "overall":
            shown = full_scale_overall(numeric, is_pitcher=bool(is_pitcher))
        else:
            shown = max(1, min(99, int(math.floor(numeric + 0.5))))
        if pct is None:
            return shown, None, avg, bucket
        return shown, max(1, min(99, int(round((1.0 - pct) * 100)))), avg, bucket
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
    scale: Optional[int] = None,
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
        scale=scale,
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
    scale: Optional[int] = None,
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
            scale=scale,
        )
    )
