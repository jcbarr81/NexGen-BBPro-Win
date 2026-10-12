"""Persistence helpers for physics engine tuning overrides."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

from physics_sim.config import DEFAULT_TUNING
from services.physics_tuning_spec import _SWING_MODEL_SLIDERS
from utils.path_utils import ActivePath, get_data_dir

__all__ = [
    "STEAL_FREQ_REBASE_MARKER",
    "SWING_SLIDER_REBASE_MARKER",
    "TUNING_OVERRIDES_PATH",
    "convert_swing_slider_overrides",
    "effective_swing_model",
    "get_physics_tuning_overrides",
    "load_physics_tuning_defaults",
    "load_physics_tuning_overrides",
    "load_physics_tuning_values",
    "reset_physics_tuning_overrides",
    "save_physics_tuning_overrides",
]

TUNING_OVERRIDES_PATH = ActivePath(lambda: get_data_dir() / "physics_tuning_overrides.json")
_NUMERIC_TYPES = (int, float)

# Release 4 (audit H2, owner decision): the Steal Frequency slider was rebased
# so 1.0 = MLB volume (the old default 3.0 is the new 1.0). A file saved
# before the rebase holds steal_freq_scale on the old scale; it is divided by
# 3 once. Every file written from now on carries this marker, so a stored
# value is never divided twice. The marker is not a tuning knob.
STEAL_FREQ_REBASE_MARKER = "_steal_freq_scale_rebased_r4"
_STEAL_FREQ_REBASE_DIVISOR = 3.0

# Release 5 (owner decision 9): under ``swing_model`` 1 the Walk Rate, Zone
# Swing and Chase sliders move new keys (odds multipliers, 1.0 = MLB) and the
# two two-strike sliders become one (services/physics_tuning_spec). A league's
# stored legacy values are converted ONCE, the first time its overrides are
# loaded while it runs the new model -- not at deploy: a league still on
# ``swing_model`` 0 keeps its file and its sliders exactly as they are. The
# marker is written with the converted file (and by every save made under
# the new model), so a legacy value is never converted twice, e.g. after the
# commissioner has set the new slider back to 1.0. The legacy keys stay in
# the file: the new model does not read them, and the league gets its old
# settings back if it returns to ``swing_model`` 0.
SWING_SLIDER_REBASE_MARKER = "_swing_sliders_rebased_r5"

# The swing_model 0 defaults the legacy sliders were set against, frozen
# here so the conversion does not move if DEFAULT_TUNING ever does.
_LEGACY_SWING_DEFAULTS = {
    "walk_scale": 0.83,
    "zone_swing_scale": 0.91,
    "chase_scale": 0.69,
    "two_strike_aggression_scale": 1.05,
    "two_strike_zone_protect": 0.63,
}
# The old model's swing chances for an average hitter (physics.simulate_pitch,
# swing_model 0): 0.62 in the zone and 0.28 out of it before the sliders, and
# with two strikes +0.10 x aggression plus a count bonus of about 0.08 in
# the zone, then the protect roll.
_LEGACY_ZONE_BASE = 0.62
_LEGACY_CHASE_BASE = 0.28
_LEGACY_TWO_STRIKE_ZONE_STEP = 0.10
_LEGACY_TWO_STRIKE_ZONE_BONUS = 0.08


def get_physics_tuning_overrides() -> Dict[str, float]:
    """Return the current physics tuning overrides."""

    return load_physics_tuning_overrides()


def effective_swing_model(overrides: Dict[str, Any] | None = None) -> float:
    """The ``swing_model`` a league with these stored overrides runs.

    Its own stored value if it has one, else the engine default. This is the
    one place that decides which slider set and which scale a league is on
    (a per-league engine profile, if Release 5b adds one, plugs in here).
    """
    value = (overrides or {}).get("swing_model", DEFAULT_TUNING["swing_model"])
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(DEFAULT_TUNING["swing_model"])


def load_physics_tuning_overrides() -> Dict[str, float]:
    """Load tuning overrides from disk."""

    if not TUNING_OVERRIDES_PATH.exists():
        return {}
    try:
        payload = json.loads(TUNING_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    cleaned = _sanitize_overrides(payload)
    swing_rebased = bool(payload.get(SWING_SLIDER_REBASE_MARKER))
    if not payload.get(STEAL_FREQ_REBASE_MARKER):
        cleaned = _rebase_steal_freq(cleaned, swing_rebased=swing_rebased)
    if effective_swing_model(cleaned) >= 1.0 and not swing_rebased:
        cleaned = _rebase_swing_sliders(cleaned)
    return cleaned


def load_physics_tuning_defaults() -> Dict[str, float]:
    """Return the engine's own default for every numeric knob.

    What a knob reads with no override. The tuning editor measures "changed"
    against these: handing it the effective values instead made it save only
    the knobs touched in that session, which dropped every other stored
    override.
    """

    return {
        key: float(value)
        for key, value in DEFAULT_TUNING.items()
        if isinstance(value, _NUMERIC_TYPES)
    }


def load_physics_tuning_values() -> Dict[str, float]:
    """Return defaults merged with any stored overrides."""

    values = load_physics_tuning_defaults()
    values.update(load_physics_tuning_overrides())
    return values


def save_physics_tuning_overrides(overrides: Dict[str, float]) -> None:
    """Persist tuning overrides to disk (on the current slider scales)."""

    _save_overrides(overrides, swing_rebased=None)


def _save_overrides(
    overrides: Dict[str, float], *, swing_rebased: bool | None
) -> None:
    """Write ``overrides`` with the migration markers.

    ``swing_rebased`` None, a save from outside, marks the file as on the
    Release 5 swing-slider scale when the league it describes runs
    ``swing_model`` 1 (that is the slider set it was just saved from); the
    migrations pass the file's own state.
    """
    cleaned = _sanitize_overrides(overrides)
    if not cleaned:
        reset_physics_tuning_overrides()
        return
    payload: Dict[str, Any] = dict(cleaned)
    payload[STEAL_FREQ_REBASE_MARKER] = True
    if swing_rebased is None:
        swing_rebased = effective_swing_model(cleaned) >= 1.0
    if swing_rebased:
        payload[SWING_SLIDER_REBASE_MARKER] = True
    _write_atomic(Path(TUNING_OVERRIDES_PATH), payload)


def reset_physics_tuning_overrides() -> None:
    """Remove any saved overrides and fall back to defaults."""

    try:
        TUNING_OVERRIDES_PATH.unlink()
    except FileNotFoundError:
        pass


def _rebase_steal_freq(
    cleaned: Dict[str, float], *, swing_rebased: bool = False
) -> Dict[str, float]:
    """One-time Release 4 migration of a pre-rebase file (see the marker).

    The divided value is written back with the marker so the file itself is
    migrated; if the write fails (a read-only copy) the division still
    applies in memory, from the unchanged file, on every load.
    """
    if "steal_freq_scale" not in cleaned:
        return cleaned
    migrated = dict(cleaned)
    migrated["steal_freq_scale"] = (
        cleaned["steal_freq_scale"] / _STEAL_FREQ_REBASE_DIVISOR
    )
    try:
        _save_overrides(migrated, swing_rebased=swing_rebased)
    except OSError:
        pass
    return migrated


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

    Each result is rounded to the slider step and held inside the new
    slider's range. A slider left at its old default converts to 1.0 and is
    not written. A new-scale value already present is never overwritten, and
    the legacy keys are kept (see ``SWING_SLIDER_REBASE_MARKER``). Returns a
    new dict; with no legacy slider stored it equals ``overrides``.
    """
    legacy = _LEGACY_SWING_DEFAULTS
    converted = dict(overrides)

    def odds(chance: float) -> float:
        # 0.02 and 0.98 are the old model's own clamp on a swing chance.
        chance = min(max(chance, 0.02), 0.98)
        return chance / (1.0 - chance)

    def store(legacy_key: str, ratio: float) -> None:
        spec = _SWING_MODEL_SLIDERS[legacy_key]
        if spec.key in overrides:
            return
        value = round(min(max(ratio, spec.min_value), spec.max_value), 2)
        if value != 1.0:
            converted[spec.key] = value

    if "zone_swing_scale" in overrides:
        store(
            "zone_swing_scale",
            odds(_LEGACY_ZONE_BASE * overrides["zone_swing_scale"])
            / odds(_LEGACY_ZONE_BASE * legacy["zone_swing_scale"]),
        )
    # The old default chase chance: 0.28 x chase_scale / walk_scale.
    chase_ref = _LEGACY_CHASE_BASE * legacy["chase_scale"] / legacy["walk_scale"]
    if "chase_scale" in overrides:
        store(
            "chase_scale",
            odds(chase_ref * overrides["chase_scale"] / legacy["chase_scale"])
            / odds(chase_ref),
        )
    gain = overrides.get(
        "swing_walk_logit_gain", DEFAULT_TUNING["swing_walk_logit_gain"]
    )
    if "walk_scale" in overrides and gain > 0.0:
        # The old model ignored a walk_scale of 0 or less (it did not divide).
        stored = overrides["walk_scale"]
        divisor = (stored if stored > 0.0 else 1.0) / legacy["walk_scale"]
        chase_ratio = odds(chase_ref / divisor) / odds(chase_ref)
        store("walk_scale", chase_ratio ** (-1.0 / gain))
    aggression_key = "two_strike_aggression_scale"
    protect_key = "two_strike_zone_protect"
    if aggression_key in overrides or protect_key in overrides:

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
                    overrides.get(aggression_key, legacy[aggression_key]),
                    overrides.get(protect_key, legacy[protect_key]),
                )
            )
            / odds(
                two_strike_zone_swing(legacy[aggression_key], legacy[protect_key])
            ),
        )
    return converted


def _rebase_swing_sliders(cleaned: Dict[str, float]) -> Dict[str, float]:
    """One-time Release 5 migration of a league's legacy swing sliders.

    Runs when a file without the marker is loaded for a league on
    ``swing_model`` 1. Like the steal rebase, the converted file is written
    back with its marker; if the write fails the conversion still applies
    in memory on every load. A file with no legacy swing slider is left
    alone (there is nothing to convert).
    """
    if not any(key in cleaned for key in _LEGACY_SWING_DEFAULTS):
        return cleaned
    migrated = convert_swing_slider_overrides(cleaned)
    try:
        _save_overrides(migrated, swing_rebased=True)
    except OSError:
        pass
    return migrated


def _write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    # Replace, never rewrite in place: games read this file on every run,
    # and the one-time migration below may write it from inside a sim.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        # Never leave a partial temp file for the working-copy sync to push.
        tmp.unlink(missing_ok=True)
        raise


def _sanitize_overrides(data: Dict[str, Any]) -> Dict[str, float]:
    cleaned: Dict[str, float] = {}
    for key, value in data.items():
        if key not in DEFAULT_TUNING:
            continue
        default_value = DEFAULT_TUNING.get(key)
        if not isinstance(default_value, _NUMERIC_TYPES):
            continue
        try:
            cleaned[key] = float(value)
        except (TypeError, ValueError):
            continue
    return cleaned
