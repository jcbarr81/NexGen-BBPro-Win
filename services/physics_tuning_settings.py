"""Persistence helpers for physics engine tuning overrides."""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import math
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

from physics_sim.config import DEFAULT_TUNING
from physics_sim.engine_generation import (
    LEGACY_ENGINE_GENERATION,
    engine_defaults,
    normalize_engine_generation,
)
from services.physics_tuning_spec import (
    _CONTACT_MODEL_SLIDERS,
    _SWING_MODEL_SLIDERS,
)
from utils.path_utils import ActivePath, get_data_dir

__all__ = [
    "GENERATION_OWNED_KEYS",
    "LEGACY_SLIDER_KEYS",
    "LEGACY_SLIDERS_MARKER",
    "STEAL_FREQ_REBASE_MARKER",
    "SWING_SLIDER_REBASE_MARKER",
    "TUNING_OVERRIDES_FILENAME",
    "TUNING_OVERRIDES_PATH",
    "convert_slider_overrides",
    "convert_strikeout_slider_overrides",
    "convert_swing_slider_overrides",
    "effective_contact_model",
    "effective_swing_model",
    "get_physics_tuning_overrides",
    "load_physics_tuning_defaults",
    "load_physics_tuning_overrides",
    "load_physics_tuning_values",
    "reset_physics_tuning_overrides",
    "rule_preset_overrides",
    "save_physics_tuning_overrides",
]

TUNING_OVERRIDES_FILENAME = "physics_tuning_overrides.json"
TUNING_OVERRIDES_PATH = ActivePath(lambda: get_data_dir() / TUNING_OVERRIDES_FILENAME)
_NUMERIC_TYPES = (int, float)
_LOGGER = logging.getLogger(__name__)

# Release 4 (audit H2, owner decision): the Steal Frequency slider was rebased
# so 1.0 = MLB volume (the old default 3.0 is the new 1.0). A file saved
# before the rebase holds steal_freq_scale on the old scale; it is divided by
# 3 once. Every file written from now on carries this marker, so a stored
# value is never divided twice. The marker is not a tuning knob.
STEAL_FREQ_REBASE_MARKER = "_steal_freq_scale_rebased_r4"
_STEAL_FREQ_REBASE_DIVISOR = 3.0

# Release 5 (owner decision 9): from engine generation 5 the Walk Rate, Zone
# Swing, Chase and Strikeout Rate sliders move new keys (odds multipliers,
# 1.0 = MLB), the two two-strike sliders become one and Contact Rate merges
# into Strikeout Rate (services/physics_tuning_spec). Which set a league is
# on comes from its season's ENGINE GENERATION
# (services.league_rating_centers), never from a switch in this file.
#
# A league's stored legacy values are converted when its overrides are first
# loaded -- or saved, e.g. by a rule preset -- under generation 5; a league
# still on the legacy engine keeps its file and its sliders exactly as they
# are. Conversion REPLACES the legacy keys: the new engine does not read
# them, so a legacy slider key found in a generation 5 file is always a
# value that still has to be converted, whatever the markers say, and a
# commissioner who sets a converted slider back to 1.0 leaves nothing behind
# that could be converted again. The values that were replaced are kept
# under ``LEGACY_SLIDERS_MARKER`` for reference. Every file written under
# generation 5 carries ``SWING_SLIDER_REBASE_MARKER``.
SWING_SLIDER_REBASE_MARKER = "_swing_sliders_rebased_r5"
LEGACY_SLIDERS_MARKER = "_legacy_sliders_r5"

# The engine models are the generation's to set. A copy in the overrides file
# is dropped on load and on save: a league must not change engines in the
# middle of a season because someone posted a switch to the tuning API.
GENERATION_OWNED_KEYS = (
    "swing_model",
    "command_model",
    "umpire_model",
    "hbp_model",
    "ibb_model",
    "contact_model",
)

# The legacy defaults the replaced sliders were set against, frozen here so
# the conversion does not move if DEFAULT_TUNING ever does.
_LEGACY_SWING_DEFAULTS = {
    "walk_scale": 0.83,
    "zone_swing_scale": 0.91,
    "chase_scale": 0.69,
    "two_strike_aggression_scale": 1.05,
    "two_strike_zone_protect": 0.63,
}
_LEGACY_CONTACT_DEFAULTS = {
    "k_scale": 0.51,
    "contact_prob_scale": 0.885,
}
# Every slider key generation 5 replaces.
LEGACY_SLIDER_KEYS = tuple(_LEGACY_SWING_DEFAULTS) + tuple(_LEGACY_CONTACT_DEFAULTS)
# The old model's swing chances for an average hitter (physics.simulate_pitch,
# swing_model 0): 0.62 in the zone and 0.28 out of it before the sliders, and
# with two strikes +0.10 x aggression plus a count bonus of about 0.08 in
# the zone, then the protect roll.
_LEGACY_ZONE_BASE = 0.62
_LEGACY_CHASE_BASE = 0.28
_LEGACY_TWO_STRIKE_ZONE_STEP = 0.10
_LEGACY_TWO_STRIKE_ZONE_BONUS = 0.08
# The old contact roll (contact_model 0): contact chance = contact_base / 100
# x contact_prob_scale / k_scale, under a ceiling of 1 - the whiff chance, so
# the two sliders are one factor, (k_scale / 0.51) / (contact_prob_scale /
# 0.885). The league contact rate that factor gave, measured on the legacy
# engine (162-game calibration seasons, seed 1; rows are k_scale 0.40,
# 0.45, the default, contact_prob_scale 0.85, k_scale 0.60, 0.75, 0.92 and
# 1.20; contact_prob_scale 1.0, factor 0.885, gave .859 against the .861 of
# k_scale 0.45, factor 0.882, so the two sliders do act as one). A table,
# not a formula: the ceiling and the per-count scales have no closed form.
# Strikeouts ran .130 at the first row, .215 at the default and .590 at the
# last.
_LEGACY_CONTACT_RATE_BY_FACTOR: Tuple[Tuple[float, float], ...] = (
    (0.7843, 0.9046),
    (0.8824, 0.8605),
    (1.0, 0.7870),
    (1.0412, 0.7606),
    (1.1765, 0.6740),
    (1.4706, 0.5387),
    (1.8039, 0.4397),
    (2.3529, 0.3365),
)

# Guards every read-modify-write of an overrides file in this process; the
# ``<file>.lock`` beside it (utils.stats_persistence) guards it across the
# parallel-day worker processes. Not re-entrant, like the file lock: nothing
# that holds it may load, save or reset.
_OVERRIDES_LOCK = threading.Lock()


def get_physics_tuning_overrides(
    generation: object | None = None,
    *,
    path: Path | str | None = None,
    migrate: bool = True,
) -> Dict[str, float]:
    """Return the current physics tuning overrides."""

    return load_physics_tuning_overrides(generation, path=path, migrate=migrate)


def effective_swing_model(generation: object | None = None) -> float:
    """The ``swing_model`` of a league season on engine ``generation``.

    ``None`` is the current league's season. The generation decides which
    slider set and which scale a league is on; nothing in its overrides
    file does.
    """
    return engine_defaults(_generation(generation)).get("swing_model", 0.0)


def effective_contact_model(generation: object | None = None) -> float:
    """The ``contact_model`` of a league season on engine ``generation``."""
    return engine_defaults(_generation(generation)).get("contact_model", 0.0)


def load_physics_tuning_overrides(
    generation: object | None = None,
    *,
    path: Path | str | None = None,
    migrate: bool = True,
) -> Dict[str, float]:
    """Load a league's tuning overrides, on the scales of its engine.

    ``generation`` is the league season's engine generation (``None``: the
    current league's, read without fixing it). ``path`` is the overrides
    file of a league other than the current one; with it, pass its
    ``generation`` too.

    A file that predates a slider rebase is migrated: the converted file is
    written back, so it is migrated once; if the write fails (a read-only
    copy) the conversion still applies in memory, from the unchanged file,
    on every load. ``migrate`` False never writes -- it is for readers that
    must not change a tuning file (a lineup action): they get the same
    converted values, in memory only.
    """

    target = Path(path) if path is not None else Path(TUNING_OVERRIDES_PATH)
    number = _generation(generation)
    cleaned, markers, changed = _migrated(_read_payload(target), number)
    if changed and migrate:
        try:
            with _overrides_lock(target):
                # Read again under the lock: a save (or another process's
                # migration) may have replaced the file since the read above.
                cleaned, markers, changed = _migrated(_read_payload(target), number)
                if changed:
                    _write_payload(target, cleaned, markers, number)
        except OSError:
            pass
    return cleaned


def load_physics_tuning_defaults(generation: object | None = None) -> Dict[str, float]:
    """Return every numeric knob's value with no override.

    The engine's defaults under the league's engine generation
    (``DEFAULT_TUNING`` itself for a legacy league). The tuning editor
    measures "changed" against these: handing it the effective values
    instead made it save only the knobs touched in that session, which
    dropped every other stored override.
    """

    return engine_defaults(_generation(generation))


def load_physics_tuning_values(generation: object | None = None) -> Dict[str, float]:
    """Return defaults merged with any stored overrides."""

    number = _generation(generation)
    values = load_physics_tuning_defaults(number)
    values.update(load_physics_tuning_overrides(number))
    return values


def save_physics_tuning_overrides(
    overrides: Dict[str, float],
    generation: object | None = None,
    *,
    path: Path | str | None = None,
) -> None:
    """Persist tuning overrides to disk (on the current slider scales).

    The file is replaced by ``overrides``, and its internal markers (the
    keys starting with ``_``) are carried forward from the file being
    replaced: a save can never make a migrated file look unmigrated. Under
    generation 5 a legacy slider key in ``overrides`` (a rule preset, a
    page that was loaded before the league changed engines) is converted,
    not stored. A value that is not a finite number is rejected with
    ``ValueError``. ``generation`` ``None`` is the current league's season,
    which a save fixes: the file is now on that generation's scales.
    """

    target = Path(path) if path is not None else Path(TUNING_OVERRIDES_PATH)
    number = _generation(generation, store=True)
    cleaned = _sanitize_overrides(overrides, strict=True)
    with _overrides_lock(target):
        markers = _markers(_read_payload(target))
        if number > LEGACY_ENGINE_GENERATION:
            cleaned, markers = _converted_for_new_sliders(cleaned, markers)
        if not cleaned:
            _unlink(target)
            return
        _write_payload(target, cleaned, markers, number)


def reset_physics_tuning_overrides() -> None:
    """Remove any saved overrides and fall back to defaults."""

    target = Path(TUNING_OVERRIDES_PATH)
    with _overrides_lock(target):
        _unlink(target)


def convert_swing_slider_overrides(overrides: Dict[str, float]) -> Dict[str, float]:
    """Stored legacy swing sliders re-expressed for ``swing_model`` 1.

    Each legacy slider scaled (or added to) a swing CHANCE; its replacement
    multiplies swing ODDS. A stored value becomes the odds ratio it produced
    in the old model for an average hitter, against the old default:

    * ``zone_swing_scale`` -> ``swing_zone_scale`` and ``chase_scale`` ->
      ``swing_chase_scale``: the odds ratio of the zone (chase) swing chance.
    * ``walk_scale`` -> ``swing_walk_scale``: the old slider divided the
      chase chance; the new one divides the chase odds by
      ``slider ** swing_walk_logit_gain``, so the odds ratio is inverted
      through that gain.
    * ``two_strike_aggression_scale`` and ``two_strike_zone_protect`` ->
      ``swing_two_strike_scale``: the odds ratio of the chance of swinging
      at a two-strike pitch in the zone (first roll or the protect roll),
      the two together.

    Each result is rounded to the slider step. The new sliders' ranges
    cover everything the old sliders' own ranges convert to; a value from
    outside those is held at the end of the new range and the clip is
    logged. A slider left at its old default converts to 1.0 and is not
    written. A new-scale value already present is never overwritten. The
    legacy keys are kept in the result (``convert_slider_overrides`` is the
    one that replaces them). Returns a new dict; with no legacy slider
    stored it equals ``overrides``.
    """
    legacy = _LEGACY_SWING_DEFAULTS
    converted = dict(overrides)

    def odds(chance: float) -> float:
        # 0.02 and 0.98 are the old model's own clamp on a swing chance.
        chance = min(max(chance, 0.02), 0.98)
        return chance / (1.0 - chance)

    def store(legacy_key: str, ratio: float) -> None:
        _store_converted(
            converted, overrides, legacy_key, _SWING_MODEL_SLIDERS[legacy_key], ratio
        )

    def stored(key: str) -> bool:
        return key in overrides and _is_finite(overrides[key])

    if stored("zone_swing_scale"):
        store(
            "zone_swing_scale",
            odds(_LEGACY_ZONE_BASE * overrides["zone_swing_scale"])
            / odds(_LEGACY_ZONE_BASE * legacy["zone_swing_scale"]),
        )
    # The old default chase chance: 0.28 x chase_scale / walk_scale.
    chase_ref = _LEGACY_CHASE_BASE * legacy["chase_scale"] / legacy["walk_scale"]
    if stored("chase_scale"):
        store(
            "chase_scale",
            odds(chase_ref * overrides["chase_scale"] / legacy["chase_scale"])
            / odds(chase_ref),
        )
    gain = overrides.get(
        "swing_walk_logit_gain", DEFAULT_TUNING["swing_walk_logit_gain"]
    )
    if stored("walk_scale") and _is_finite(gain) and gain > 0.0:
        # The old model ignored a walk_scale of 0 or less (it did not divide).
        value = overrides["walk_scale"]
        divisor = (value if value > 0.0 else 1.0) / legacy["walk_scale"]
        chase_ratio = odds(chase_ref / divisor) / odds(chase_ref)
        store("walk_scale", chase_ratio ** (-1.0 / gain))
    aggression_key = "two_strike_aggression_scale"
    protect_key = "two_strike_zone_protect"
    if stored(aggression_key) or stored(protect_key):

        def two_strike_zone_swing(aggression: float, protect: float) -> float:
            first = _LEGACY_ZONE_BASE * legacy["zone_swing_scale"]
            first += _LEGACY_TWO_STRIKE_ZONE_STEP * aggression
            first += _LEGACY_TWO_STRIKE_ZONE_BONUS
            first = min(max(first, 0.02), 0.98)
            protect = min(max(protect, 0.0), 1.0)
            return 1.0 - (1.0 - first) * (1.0 - protect)

        store(
            aggression_key,
            odds(
                two_strike_zone_swing(
                    overrides[aggression_key]
                    if stored(aggression_key)
                    else legacy[aggression_key],
                    overrides[protect_key]
                    if stored(protect_key)
                    else legacy[protect_key],
                )
            )
            / odds(
                two_strike_zone_swing(legacy[aggression_key], legacy[protect_key])
            ),
        )
    return converted


def convert_strikeout_slider_overrides(overrides: Dict[str, float]) -> Dict[str, float]:
    """Stored Strikeout Rate / Contact Rate re-expressed for ``contact_model`` 1.

    ``k_scale`` and ``contact_prob_scale`` together set how often a swing
    met the ball; ``contact_strikeout_scale`` divides the contact ODDS by
    ``slider ** contact_strikeout_logit_gain``. The stored pair becomes the
    slider that gives the league the contact rate the pair gave it
    (``_LEGACY_CONTACT_RATE_BY_FACTOR``), as an odds ratio against the old
    defaults' rate inverted through the gain -- so "Strikeout Rate up =
    more strikeouts" carries over. Rounding, range, clipping, the
    already-present rule and the kept legacy keys are as in
    :func:`convert_swing_slider_overrides`.
    """
    legacy = _LEGACY_CONTACT_DEFAULTS
    converted = dict(overrides)
    present = [
        key for key in legacy if key in overrides and _is_finite(overrides[key])
    ]
    gain = overrides.get(
        "contact_strikeout_logit_gain", DEFAULT_TUNING["contact_strikeout_logit_gain"]
    )
    if not present or not _is_finite(gain) or gain <= 0.0:
        return converted

    def value(key: str) -> float:
        return overrides[key] if key in present else legacy[key]

    # The old model: a k_scale under 0.1 read as 0.1, and the contact chance
    # could not leave 5% - 95% whatever contact_prob_scale said.
    factor = (max(0.1, value("k_scale")) / legacy["k_scale"]) / (
        max(1e-6, value("contact_prob_scale")) / legacy["contact_prob_scale"]
    )

    def odds(rate: float) -> float:
        return rate / (1.0 - rate)

    ratio = odds(_legacy_contact_rate(factor)) / odds(_legacy_contact_rate(1.0))
    _store_converted(
        converted,
        overrides,
        "k_scale",
        _CONTACT_MODEL_SLIDERS["k_scale"],
        ratio ** (-1.0 / gain),
    )
    return converted


def convert_slider_overrides(overrides: Dict[str, float]) -> Dict[str, float]:
    """``overrides`` as generation 5 stores them: every legacy slider value
    converted (:func:`convert_swing_slider_overrides`,
    :func:`convert_strikeout_slider_overrides`) and its legacy key REMOVED.

    Returns a new dict; with no legacy slider key it equals ``overrides``.
    """
    converted = convert_strikeout_slider_overrides(
        convert_swing_slider_overrides(overrides)
    )
    for key in LEGACY_SLIDER_KEYS:
        converted.pop(key, None)
    return converted


# A rule preset's rate name -> the legacy slider key that owns the rate.
_PRESET_RATE_SLIDERS = {
    "walk_rate": "walk_scale",
    "strikeout_rate": "k_scale",
}


def rule_preset_overrides(
    multipliers: Dict[str, float], generation: object | None = None
) -> Dict[str, float]:
    """A rule preset's relative changes as overrides for ``generation``.

    ``multipliers`` maps a knob to the factor applied to its normal value
    under the league's engine (``engine_defaults``), and ``walk_rate`` /
    ``strikeout_rate`` to the Walk Rate / Strikeout Rate slider setting on
    the 1.0 = MLB scale. From generation 5 those are the sliders' own keys.
    On the legacy engine, whose sliders are not on that scale, each becomes
    the legacy slider value that converts to it
    (:func:`convert_slider_overrides` run backwards), held inside the legacy
    slider's range. The presets used to state ``walk_scale`` 1.05 and
    ``k_scale`` 0.92 as if 1.0 were normal; against the real defaults of
    0.83 and 0.51 that was a league striking out in half its plate
    appearances. A factor of 1.0, an unknown knob and a value that is not a
    finite number are left out.
    """
    number = _generation(generation)
    defaults = engine_defaults(number)
    overrides: Dict[str, float] = {}
    for name, raw in multipliers.items():
        try:
            factor = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(factor) or factor <= 0.0 or factor == 1.0:
            continue
        legacy_key = _PRESET_RATE_SLIDERS.get(name)
        if legacy_key is None:
            if name in defaults and name not in GENERATION_OWNED_KEYS:
                overrides[name] = round(defaults[name] * factor, 4)
            continue
        spec = {**_SWING_MODEL_SLIDERS, **_CONTACT_MODEL_SLIDERS}[legacy_key]
        target = min(max(factor, spec.min_value), spec.max_value)
        if number > LEGACY_ENGINE_GENERATION:
            overrides[spec.key] = round(target, 2)
        else:
            overrides[legacy_key] = _legacy_slider_for(legacy_key, spec.key, target)
    return overrides


def _legacy_slider_for(legacy_key: str, new_key: str, target: float) -> float:
    """The legacy slider value whose conversion is ``target`` on the new
    scale: a bisection over the legacy slider's range (every conversion
    rises with its legacy slider), to the slider's 0.01 step."""
    from services.physics_tuning_spec import _TUNING_SECTIONS

    spec = next(
        s for _label, specs in _TUNING_SECTIONS for s in specs if s.key == legacy_key
    )

    def converted(value: float) -> float:
        return convert_slider_overrides({legacy_key: value}).get(new_key, 1.0)

    low, high = spec.min_value, spec.max_value
    for _ in range(40):
        middle = (low + high) / 2.0
        if converted(middle) < target:
            low = middle
        else:
            high = middle
    return round((low + high) / 2.0, 2)


def _legacy_contact_rate(factor: float) -> float:
    """The legacy league contact rate at ``factor``, interpolated on its log
    and held at the table's ends."""
    table = _LEGACY_CONTACT_RATE_BY_FACTOR
    if not table[0][0] <= factor <= table[-1][0]:
        _LOGGER.warning(
            "legacy strikeout / contact sliders combine to a factor of %.3f,"
            " outside the measured %.3f-%.3f; converted at the nearest end",
            factor,
            table[0][0],
            table[-1][0],
        )
    position = math.log(min(max(factor, table[0][0]), table[-1][0]))
    for (low, low_rate), (high, high_rate) in zip(table, table[1:]):
        if position <= math.log(high):
            share = (position - math.log(low)) / (math.log(high) - math.log(low))
            return low_rate + (high_rate - low_rate) * share
    return table[-1][1]


def _store_converted(
    converted: Dict[str, float],
    overrides: Dict[str, float],
    legacy_key: str,
    spec: Any,
    value: float,
) -> None:
    """Put a converted slider value into ``converted`` under ``spec.key``."""
    if spec.key in overrides:
        return  # a value already on the new scale is the commissioner's
    if not _is_finite(value):
        _LOGGER.warning(
            "tuning slider %s=%r has no finite conversion; ignored",
            legacy_key,
            overrides.get(legacy_key),
        )
        return
    held = min(max(value, spec.min_value), spec.max_value)
    if held != value:
        _LOGGER.warning(
            "tuning slider %s=%r converts to %s=%.3f, outside the slider's"
            " %s-%s range; stored as %s",
            legacy_key,
            overrides.get(legacy_key),
            spec.key,
            value,
            spec.min_value,
            spec.max_value,
            held,
        )
    held = round(held, 2)
    if held != 1.0:
        converted[spec.key] = held


def _generation(generation: object | None, *, store: bool = False) -> int:
    if generation is not None:
        return normalize_engine_generation(generation)
    from services.league_rating_centers import get_league_engine_generation

    return get_league_engine_generation(store=store)


def _markers(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if isinstance(key, str) and key.startswith("_")
    }


def _converted_for_new_sliders(
    cleaned: Dict[str, float], markers: Dict[str, Any]
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """``cleaned`` with its legacy slider keys converted and removed, and
    ``markers`` recording the values that were replaced."""
    replaced = {key: cleaned[key] for key in LEGACY_SLIDER_KEYS if key in cleaned}
    if not replaced:
        return cleaned, markers
    kept = markers.get(LEGACY_SLIDERS_MARKER)
    markers = dict(markers)
    markers[LEGACY_SLIDERS_MARKER] = {
        **(kept if isinstance(kept, dict) else {}),
        **replaced,
    }
    return convert_slider_overrides(cleaned), markers


def _migrated(
    payload: Dict[str, Any], generation: int
) -> Tuple[Dict[str, float], Dict[str, Any], bool]:
    """(overrides, markers, the file needs rewriting) for a stored payload."""
    cleaned = _sanitize_overrides(payload)
    markers = _markers(payload)
    changed = False
    if not markers.get(STEAL_FREQ_REBASE_MARKER) and "steal_freq_scale" in cleaned:
        # One-time Release 4 migration of a pre-rebase file (see the marker).
        cleaned["steal_freq_scale"] /= _STEAL_FREQ_REBASE_DIVISOR
        changed = True
    if generation > LEGACY_ENGINE_GENERATION:
        before = cleaned
        cleaned, markers = _converted_for_new_sliders(cleaned, markers)
        changed = changed or cleaned is not before
    return cleaned, markers, changed


def _read_payload(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_payload(
    path: Path, cleaned: Dict[str, float], markers: Dict[str, Any], generation: int
) -> None:
    payload: Dict[str, Any] = dict(markers)
    payload.update(cleaned)
    payload[STEAL_FREQ_REBASE_MARKER] = True
    if generation > LEGACY_ENGINE_GENERATION:
        payload[SWING_SLIDER_REBASE_MARKER] = True
    _write_atomic(path, payload)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@contextmanager
def _overrides_lock(path: Path) -> Iterator[None]:
    """Hold the overrides file's lock for a read-modify-write.

    A thread lock for this process and the ``<file>.lock`` byte-range lock
    the season stats use (``utils.stats_persistence``) for the others. Where
    the lock file cannot be opened (a read-only directory) the thread lock
    alone holds: nothing can be written there anyway.
    """
    from utils.stats_persistence import _locked

    with _OVERRIDES_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.with_name(f"{path.name}.lock").open("a+")
        except OSError:
            yield
            return
        with handle:
            with _locked(handle):
                yield


def _write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    # Replace, never rewrite in place: games read this file on every run,
    # and the one-time migration above may write it from inside a sim.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        # Never leave a partial temp file for the working-copy sync to push.
        tmp.unlink(missing_ok=True)
        raise


def _is_finite(value: object) -> bool:
    return (
        isinstance(value, _NUMERIC_TYPES)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _sanitize_overrides(
    data: Dict[str, Any], *, strict: bool = False
) -> Dict[str, float]:
    """The numeric tuning knobs in ``data``, as floats.

    Unknown keys, table knobs, the markers and the generation-owned engine
    switches are left out. A value that is not a finite number is left out
    too, or with ``strict`` (a save) raises ``ValueError``.
    """
    cleaned: Dict[str, float] = {}
    for key, value in data.items():
        if key not in DEFAULT_TUNING or key in GENERATION_OWNED_KEYS:
            continue
        default_value = DEFAULT_TUNING.get(key)
        if not isinstance(default_value, _NUMERIC_TYPES):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            if strict:
                raise ValueError(f"{key} must be a number, got {value!r}") from None
            continue
        if not math.isfinite(number):
            if strict:
                raise ValueError(f"{key} must be a finite number, got {value!r}")
            continue
        cleaned[key] = number
    return cleaned
