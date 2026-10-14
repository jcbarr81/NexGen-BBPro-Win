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
    "GENERATION_6_OWNED_KEYS",
    "GENERATION_OWNED_KEYS",
    "LEGACY_SLIDER_KEYS",
    "LEGACY_SLIDERS_MARKER",
    "PRE_GENERATION_6_MARKER",
    "R6A_PITCHING_GROUP_KEYS",
    "R6A_PITCHING_KEYS",
    "VELOCITY_SLIDER_KEYS",
    "VELOCITY_SLIDER_REBASE_MARKER",
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
# A league's stored legacy values are read on the scales of the engine its
# season is on: every load under generation 5 converts them, in memory. The
# FILE is converted only once the season's generation is fixed on 5 -- by a
# season game (``convert=True``) or by a save made while the season is
# recorded as generation 5 -- because until then the league may still play
# the season on the legacy engine (the operations hold), and a page load, a
# watched game or an exhibition must not have rewritten its sliders by then.
# A league still on the legacy engine keeps its file and its sliders exactly
# as they are.
#
# Conversion REPLACES the legacy keys: the new engine does not read them,
# so a legacy slider key found in a generation 5 file is always a value
# that still has to be converted, whatever the markers say, and a
# commissioner who sets a converted slider back to 1.0 leaves nothing behind
# that could be converted again. The values that were replaced are kept
# under ``LEGACY_SLIDERS_MARKER``, and a league that is loaded as LEGACY
# with a converted file (the hold, a season put back on the old engine)
# gets them back from there, in memory, so a commissioner's settings are
# not dropped in either direction; a save made on the legacy engine writes
# the file back on the legacy scales.
#
# ``SWING_SLIDER_REBASE_MARKER`` is written only while the season is
# recorded as generation 5, and removed by a save on the legacy engine, so
# it is also evidence of the league's engine if the season's own records
# are lost (``services.league_rating_centers``).
SWING_SLIDER_REBASE_MARKER = "_swing_sliders_rebased_r5"
LEGACY_SLIDERS_MARKER = "_legacy_sliders_r5"

# The engine models are the generation's to set. A copy in the overrides file
# is dropped on load and on save: a league must not change engines in the
# middle of a season because someone posted a switch to the tuning API.
# These are owned on every generation; what else a generation owns is
# ``_owned_keys(generation)``.
GENERATION_OWNED_KEYS = (
    "swing_model",
    "command_model",
    "umpire_model",
    "hbp_model",
    "ibb_model",
    "contact_model",
)

# Release 6a (pitching): the stuff / velocity / exit-velocity / fatigue
# group only works whole (physics_sim/config.py, "ONE SWITCH GROUP"), and
# two of its four parts have no model switch: the pitch-quality weights and
# the three pitch-quality paths ARE the engine's formula. A league's saved
# tuning must not lose or change anything at this release, so ownership
# depends on the league's generation:
#
# * every key this release registers (``R6A_PITCHING_KEYS``) means nothing
#   to a legacy or generation 5 league: there, as before the release (when
#   the key was not registered), a copy in the file is not read and a save
#   does not keep it;
# * from generation 6 the keys that DEFINE the group
#   (``R6A_PITCHING_GROUP_KEYS``) are the generation's -- its three
#   switches, the weights, the three paths and the chase slope -- and its
#   sizes (the fatigue points, the velocity terms, the manager's weights)
#   are ordinary knobs;
# * ``contact_logit_velo`` is an ordinary knob before this release and
#   stays one for legacy and generation 5 leagues (generation 5's contact
#   model reads it); from generation 6 it is the group's (on the old fatigue
#   it is wrong-signed). A value a league stored is kept under
#   ``PRE_GENERATION_6_MARKER`` when the league moves, the way Release 5
#   kept its replaced sliders, and a league loaded on an earlier generation
#   gets it back.
GENERATION_6 = 6
R6A_PITCHING_GROUP_KEYS = (
    "ev_velocity_model",
    "fatigue_model",
    "pitcher_score_model",
    "pq_weight_control",
    "pq_weight_movement",
    "pq_weight_grade",
    "ev_pq_contact_base_weight",
    "ev_pq_slope",
    "difficulty_pq_scale",
    "difficulty_velocity_scale",
    "swing_pq_chase_logit",
)
R6A_PITCHING_KEYS = R6A_PITCHING_GROUP_KEYS + (
    "ev_velo_dev_weight",
    "ev_base_offset_mph",
    "fatigue_control_points",
    "fatigue_movement_points",
    "fatigue_stuff_points",
    "fatigue_velocity_mph",
    "pitcher_score_weight_control",
    "pitcher_score_weight_movement",
    "pitcher_score_weight_grade",
    "pitcher_score_weight_arm",
)
# Ordinary knobs before generation 6 that generation 6 owns.
GENERATION_6_OWNED_KEYS = ("contact_logit_velo",)
# Release 6a: Velocity Scale keeps its key, but from generation 6 more
# velocity helps the pitcher (services/physics_tuning_spec). A value stored
# before is on the old meaning, so it is not carried over: the slider goes
# back to 1.0 and the value is kept under ``PRE_GENERATION_6_MARKER``.
# ``VELOCITY_SLIDER_REBASE_MARKER`` marks a file whose velocity_scale is on
# the generation 6 meaning. Timing as Release 5's conversion: a load
# converts in memory every time; the FILE is converted by a generation 6
# season's game (``convert=True``) or by a save under generation 6 (the
# page showed the converted value, and a value posted from it is on the
# new meaning).
VELOCITY_SLIDER_KEYS = ("velocity_scale",)
VELOCITY_SLIDER_REBASE_MARKER = "_velocity_slider_rebased_r6"
PRE_GENERATION_6_MARKER = "_pre_generation_6_r6"


def _owned_keys(generation: int) -> frozenset:
    """The keys a league on ``generation`` cannot store (see above)."""
    if generation >= GENERATION_6:
        return frozenset(
            GENERATION_OWNED_KEYS + R6A_PITCHING_GROUP_KEYS + GENERATION_6_OWNED_KEYS
        )
    return frozenset(GENERATION_OWNED_KEYS + R6A_PITCHING_KEYS)

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
# Legacy slider key -> the generation 5 key its value converts into (the
# two two-strike sliders into one, Strikeout Rate and Contact Rate into one).
_NEW_SLIDER_KEY = {
    "walk_scale": _SWING_MODEL_SLIDERS["walk_scale"].key,
    "zone_swing_scale": _SWING_MODEL_SLIDERS["zone_swing_scale"].key,
    "chase_scale": _SWING_MODEL_SLIDERS["chase_scale"].key,
    "two_strike_aggression_scale": (
        _SWING_MODEL_SLIDERS["two_strike_aggression_scale"].key
    ),
    "two_strike_zone_protect": (
        _SWING_MODEL_SLIDERS["two_strike_aggression_scale"].key
    ),
    "k_scale": _CONTACT_MODEL_SLIDERS["k_scale"].key,
    "contact_prob_scale": _CONTACT_MODEL_SLIDERS["k_scale"].key,
}
# The other way: generation 5 key -> the legacy keys it replaced. The first
# is the one a generation 5 value is converted back onto (``_legacy_view``).
_LEGACY_KEYS_OF: Dict[str, Tuple[str, ...]] = {}
for _legacy_key in LEGACY_SLIDER_KEYS:
    _LEGACY_KEYS_OF[_NEW_SLIDER_KEY[_legacy_key]] = _LEGACY_KEYS_OF.get(
        _NEW_SLIDER_KEY[_legacy_key], ()
    ) + (_legacy_key,)
del _legacy_key
# The knobs a conversion reads besides the slider itself.
_CONVERSION_GAIN_KEYS = ("swing_walk_logit_gain", "contact_strikeout_logit_gain")
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
    convert: bool = False,
) -> Dict[str, float]:
    """Return the current physics tuning overrides."""

    return load_physics_tuning_overrides(
        generation, path=path, migrate=migrate, convert=convert
    )


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
    convert: bool = False,
) -> Dict[str, float]:
    """Load a league's tuning overrides, on the scales of its engine.

    ``generation`` is the league season's engine generation (``None``: the
    current league's, read without fixing it). ``path`` is the overrides
    file of a league other than the current one; with it, pass its
    ``generation`` too.

    The values returned are always on ``generation``'s scales: under
    generation 5 stored legacy sliders are converted, and under the legacy
    generation a file that was converted gives the legacy values it
    replaced back. What is WRITTEN is narrower:

    * a file that predates the Release 4 Steal Frequency rebase is migrated
      and written back, once, by any load, as it always was;
    * the generation 5 slider conversion is written back only with
      ``convert`` True, which is for the caller that has just fixed the
      season on that generation -- a season game. Every other reader (a
      page load, a watched game, an exhibition, a replay, a lineup action)
      converts in memory, every time, and leaves the file on the scales it
      is on: the season may yet be played on the legacy engine.

    Release 6a: under generation 6 the Velocity Scale stored on the old
    meaning and the keys generation 6 owns are set aside the same way --
    in memory on every load, in the file only with ``convert`` -- and a
    legacy or generation 5 load of a file converted for generation 6 gets
    the set-aside values back.

    If a write fails (a read-only copy) the values still come back right,
    from the unchanged file, on every load. ``migrate`` False never writes
    at all -- for readers that must not touch a tuning file.
    """

    target = Path(path) if path is not None else Path(TUNING_OVERRIDES_PATH)
    number = _generation(generation)
    cleaned, rewritten = _migrated(_read_payload(target), number, convert=convert)
    if rewritten is not None and migrate:
        try:
            with _overrides_lock(target):
                # Read again under the lock: a save (or another process's
                # migration) may have replaced the file since the read above.
                cleaned, rewritten = _migrated(
                    _read_payload(target), number, convert=convert
                )
                if rewritten is not None:
                    _write_atomic(target, rewritten)
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
    replaced: a save can never make a migrated file look unmigrated. A
    value that is not a finite number is rejected with ``ValueError``.
    ``generation`` ``None`` is the current league's season, which a save
    fixes when the season has a schedule: the file is now on that
    generation's scales.

    Under generation 5 a legacy slider key in ``overrides`` (a rule preset,
    a page that was loaded before the league changed engines) is converted,
    not stored, and the legacy sliders still in the file being replaced --
    the page showed their conversions -- are kept under
    ``LEGACY_SLIDERS_MARKER`` with them. The file is marked as rebased
    (``SWING_SLIDER_REBASE_MARKER``) only when the season is recorded as
    that generation: an offseason save, or a rule preset applied while a
    league is being created, fixes nothing, and the season it is for may
    still be played on the legacy engine, which then reads the kept legacy
    values. Under the legacy generation the file goes back on the legacy
    scales: what is saved is the whole legacy state, so the kept values
    and the rebase marker are dropped.

    Release 6a: under generation 6 a key generation 6 owns is not stored,
    the old-meaning Velocity Scale and any ``GENERATION_6_OWNED_KEYS`` value
    in the file being replaced are kept under ``PRE_GENERATION_6_MARKER``,
    and the file is marked as on the new Velocity Scale meaning. A save
    under an earlier generation drops both markers: the page showed the
    kept values, and they are what it sent back.
    """

    target = Path(path) if path is not None else Path(TUNING_OVERRIDES_PATH)
    number = _generation(generation, store=True)
    # A generation the caller names is the caller's word that the season is
    # on it; the current league's is checked against what is written down.
    fixed = generation is not None or _season_is_recorded_as(number)
    cleaned = _sanitize_overrides(overrides, strict=True, generation=number)
    with _overrides_lock(target):
        payload = _read_payload(target)
        markers = _markers(payload)
        if number > LEGACY_ENGINE_GENERATION:
            replaced = {
                key: value
                for key, value in _sanitize_overrides(payload).items()
                if key in LEGACY_SLIDER_KEYS
            }
            if replaced:
                markers = _with_kept_legacy_sliders(markers, replaced)
            cleaned, markers = _converted_for_new_sliders(cleaned, markers)
        else:
            markers = {
                key: value
                for key, value in markers.items()
                if key not in (LEGACY_SLIDERS_MARKER, SWING_SLIDER_REBASE_MARKER)
            }
        if number >= GENERATION_6:
            # Release 6a: what generation 6 sets aside from the file being
            # replaced is kept, a key generation 6 owns is not stored, and
            # the Velocity Scale now in the file is on the new meaning.
            _view, markers, _kept = _generation_6_view(
                _sanitize_overrides(payload, generation=number), markers
            )
            cleaned = {
                key: value
                for key, value in cleaned.items()
                if key not in GENERATION_6_OWNED_KEYS
            }
            markers = {**markers, VELOCITY_SLIDER_REBASE_MARKER: True}
        else:
            # The whole state on an earlier generation is what the page
            # showed, the kept values included: nothing is held back.
            markers = _without_generation_6_markers(markers)
        if not cleaned:
            _unlink(target)
            return
        rebased = number > LEGACY_ENGINE_GENERATION and fixed
        _write_atomic(target, _file_payload(cleaned, markers, rebased=rebased))


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
            if name in defaults and name not in _owned_keys(number):
                overrides[name] = round(defaults[name] * factor, 4)
            continue
        spec = {**_SWING_MODEL_SLIDERS, **_CONTACT_MODEL_SLIDERS}[legacy_key]
        target = min(max(factor, spec.min_value), spec.max_value)
        if number > LEGACY_ENGINE_GENERATION:
            overrides[spec.key] = round(target, 2)
        else:
            overrides[legacy_key] = _legacy_slider_for(legacy_key, spec.key, target)
    return overrides


def _legacy_slider_for(
    legacy_key: str,
    new_key: str,
    target: float,
    gains: Dict[str, float] | None = None,
) -> float:
    """The legacy slider value whose conversion is ``target`` on the new
    scale: a bisection over the legacy slider's range (every conversion
    rises with its legacy slider), to the slider's 0.01 step. ``gains`` are
    the league's stored conversion gains, if it overrides them."""
    from services.physics_tuning_spec import _TUNING_SECTIONS

    spec = next(
        s for _label, specs in _TUNING_SECTIONS for s in specs if s.key == legacy_key
    )

    def converted(value: float) -> float:
        return convert_slider_overrides({**(gains or {}), legacy_key: value}).get(
            new_key, 1.0
        )

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


def _season_is_recorded_as(generation: int) -> bool:
    """True when the current league's season is written down as
    ``generation``, a generation above legacy (the season is fixed on it)."""
    if generation <= LEGACY_ENGINE_GENERATION:
        return False
    from services.league_rating_centers import recorded_league_engine_generation

    return recorded_league_engine_generation() == generation


def _with_kept_legacy_sliders(
    markers: Dict[str, Any], replaced: Dict[str, float]
) -> Dict[str, Any]:
    """``markers`` with ``replaced`` (legacy slider values a conversion
    removes) added to the values kept under ``LEGACY_SLIDERS_MARKER``."""
    kept = markers.get(LEGACY_SLIDERS_MARKER)
    markers = dict(markers)
    markers[LEGACY_SLIDERS_MARKER] = {
        **(kept if isinstance(kept, dict) else {}),
        **replaced,
    }
    return markers


def _converted_for_new_sliders(
    cleaned: Dict[str, float], markers: Dict[str, Any]
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """``cleaned`` with its legacy slider keys converted and removed, and
    ``markers`` recording the values that were replaced."""
    replaced = {key: cleaned[key] for key in LEGACY_SLIDER_KEYS if key in cleaned}
    if not replaced:
        return cleaned, markers
    return (
        convert_slider_overrides(cleaned),
        _with_kept_legacy_sliders(markers, replaced),
    )


def _legacy_view(
    cleaned: Dict[str, float], markers: Dict[str, Any]
) -> Dict[str, float]:
    """A stored file's overrides as the LEGACY engine reads them.

    ``cleaned`` itself for a file that has never been on generation 5's
    scales (no kept legacy values, no generation 5 slider key): every
    league that has not switched. For a file that has, slider by slider:

    * a legacy key stored since (a save on the legacy engine) is the
      setting;
    * else, if the generation 5 value is still what the kept legacy values
      converted to, the commissioner has not touched the slider since the
      conversion and gets exactly those legacy values back;
    * else the generation 5 value is his latest setting, and is converted
      back onto the legacy slider (``_legacy_slider_for``; the slider's
      range holds it). A slider set back to 1.0 is the legacy default, and
      the old legacy value does not return.

    The generation 5 keys themselves are left out: the legacy engine does
    not read them, and a legacy page that sent them back would keep the
    next conversion of the legacy values from applying.
    """
    kept = markers.get(LEGACY_SLIDERS_MARKER)
    kept = (
        {
            key: value
            for key, value in _sanitize_overrides(kept).items()
            if key in LEGACY_SLIDER_KEYS
        }
        if isinstance(kept, dict)
        else {}
    )
    if not kept and not any(key in cleaned for key in _LEGACY_KEYS_OF):
        return cleaned
    gains = {key: cleaned[key] for key in _CONVERSION_GAIN_KEYS if key in cleaned}
    view = dict(cleaned)
    for new_key, legacy_keys in _LEGACY_KEYS_OF.items():
        current = view.pop(new_key, None)
        if any(key in cleaned for key in legacy_keys):
            continue
        replaced = {key: kept[key] for key in legacy_keys if key in kept}
        if replaced and _same_setting(
            convert_slider_overrides({**gains, **replaced}).get(new_key), current
        ):
            view.update(replaced)
        elif current is not None:
            primary = legacy_keys[0]
            value = _legacy_slider_for(primary, new_key, current, gains)
            if not _same_setting(value, float(DEFAULT_TUNING[primary])):
                view[primary] = value
    return view


def _same_setting(first: float | None, second: float | None) -> bool:
    """Two slider values are the same setting (``None``: not stored)."""
    if first is None or second is None:
        return first is None and second is None
    return abs(first - second) < 1e-9


def _migrated(
    payload: Dict[str, Any], generation: int, *, convert: bool
) -> Tuple[Dict[str, float], Dict[str, Any] | None]:
    """(overrides on ``generation``'s scales, the payload to write back or
    ``None``) for a stored payload.

    The Release 4 Steal Frequency rebase is written back whenever it is
    due. The generation 5 slider conversion is written back only with
    ``convert`` (the season is fixed on that generation); without it the
    file stays on the scales it is on and only the returned values are
    converted. Nothing a legacy load returns is ever written.
    """
    stored = _sanitize_overrides(payload, generation=generation)
    markers = _markers(payload)
    changed = False
    if not markers.get(STEAL_FREQ_REBASE_MARKER) and "steal_freq_scale" in stored:
        # One-time Release 4 migration of a pre-rebase file (see the marker).
        stored["steal_freq_scale"] /= _STEAL_FREQ_REBASE_DIVISOR
        changed = True
    if generation <= LEGACY_ENGINE_GENERATION:
        view = _legacy_view(_pre_generation_6_view(stored, markers), markers)
        return view, (_file_payload(stored, markers) if changed else None)
    view, converted_markers = _converted_for_new_sliders(stored, markers)
    generation_6 = generation >= GENERATION_6
    if generation_6:
        view, converted_markers, _kept = _generation_6_view(view, converted_markers)
    else:
        restored = _pre_generation_6_view(view, markers)
        if restored is not view:
            # Written back (below) with the kept values in the file itself.
            view = restored
            converted_markers = _without_generation_6_markers(converted_markers)
    if convert and stored:
        # Also when nothing needs converting: a file read by a season game
        # of a generation 5 season is marked as on that generation's scales.
        marked = markers.get(SWING_SLIDER_REBASE_MARKER) is True
        if generation_6:
            marked = marked and markers.get(VELOCITY_SLIDER_REBASE_MARKER) is True
        if changed or view is not stored or not marked:
            return view, _file_payload(
                view, converted_markers, rebased=True, velocity_rebased=generation_6
            )
        return view, None
    return view, (_file_payload(stored, markers) if changed else None)


def _read_payload(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _generation_6_view(
    stored: Dict[str, float], markers: Dict[str, Any]
) -> Tuple[Dict[str, float], Dict[str, Any], Dict[str, float]]:
    """(overrides as generation 6 reads them, ``markers`` with what was set
    aside kept under ``PRE_GENERATION_6_MARKER``, what was set aside).

    Set aside: every key generation 6 owns that the file holds
    (``GENERATION_6_OWNED_KEYS``), and Velocity Scale unless the file is
    marked as on the new meaning (``VELOCITY_SLIDER_REBASE_MARKER``). With
    nothing to set aside ``stored`` and ``markers`` come back themselves.
    """
    kept = {key: stored[key] for key in GENERATION_6_OWNED_KEYS if key in stored}
    if markers.get(VELOCITY_SLIDER_REBASE_MARKER) is not True:
        kept.update(
            {key: stored[key] for key in VELOCITY_SLIDER_KEYS if key in stored}
        )
    if not kept:
        return stored, markers, kept
    view = {key: value for key, value in stored.items() if key not in kept}
    previous = markers.get(PRE_GENERATION_6_MARKER)
    markers = dict(markers)
    markers[PRE_GENERATION_6_MARKER] = {
        **(previous if isinstance(previous, dict) else {}),
        **kept,
    }
    return view, markers, kept


def _pre_generation_6_view(
    stored: Dict[str, float], markers: Dict[str, Any]
) -> Dict[str, float]:
    """A file's overrides as a legacy or generation 5 league reads them.

    ``stored`` itself unless the file was converted for generation 6: then
    every value kept under ``PRE_GENERATION_6_MARKER`` comes back, unless
    the file holds a value of that key since (a save on an earlier
    generation, or a Velocity Scale the commissioner set on generation 6:
    the setting is the pitch speed, kept as it is).
    """
    kept = markers.get(PRE_GENERATION_6_MARKER)
    if not isinstance(kept, dict):
        return stored
    restorable = {
        key: value
        for key, value in _sanitize_overrides(kept).items()
        if key in GENERATION_6_OWNED_KEYS + VELOCITY_SLIDER_KEYS and key not in stored
    }
    if not restorable:
        return stored
    return {**stored, **restorable}


def _without_generation_6_markers(markers: Dict[str, Any]) -> Dict[str, Any]:
    """``markers`` without the Release 6a conversion's two markers."""
    return {
        key: value
        for key, value in markers.items()
        if key not in (PRE_GENERATION_6_MARKER, VELOCITY_SLIDER_REBASE_MARKER)
    }


def _file_payload(
    cleaned: Dict[str, float],
    markers: Dict[str, Any],
    *,
    rebased: bool = False,
    velocity_rebased: bool = False,
) -> Dict[str, Any]:
    """What an overrides file holds: the markers, the knobs, and the marks
    of the rebases it has been through (``rebased``: written while the
    season is fixed on generation 5 or later; ``velocity_rebased``: Velocity
    Scale is on the generation 6 meaning)."""
    payload: Dict[str, Any] = dict(markers)
    payload.update(cleaned)
    payload[STEAL_FREQ_REBASE_MARKER] = True
    if rebased:
        payload[SWING_SLIDER_REBASE_MARKER] = True
    if velocity_rebased:
        payload[VELOCITY_SLIDER_REBASE_MARKER] = True
    return payload


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
    data: Dict[str, Any],
    *,
    strict: bool = False,
    generation: int = LEGACY_ENGINE_GENERATION,
) -> Dict[str, float]:
    """The numeric tuning knobs in ``data``, as floats, for a league on
    ``generation``.

    Unknown keys, table knobs, the markers and the keys the generation owns
    are left out -- except ``GENERATION_6_OWNED_KEYS``, which the caller
    sets aside on generation 6 (:func:`_generation_6_view`). Below
    generation 6 every key Release 6a registered is left out, as it was
    before the release registered it. A value that is not a finite number
    is left out too, or with ``strict`` (a save) raises ``ValueError``.
    """
    owned = _owned_keys(generation) - frozenset(GENERATION_6_OWNED_KEYS)
    cleaned: Dict[str, float] = {}
    for key, value in data.items():
        if key not in DEFAULT_TUNING or key in owned:
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
