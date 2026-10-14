"""Engine generations: which set of engine behaviour a league season plays.

Release 5 (owner decision 12) does not reach a league in the middle of a
season. ``DEFAULT_TUNING`` stays the engine every league plays today, the
LEGACY generation, and each later generation is a tuning PROFILE laid over
it: a plain JSON file of the knobs that generation switches on, in this
package so the backend image always carries it
(``physics_sim/profiles/engine_<N>.json``; ``scripts/`` and ``data/`` are not
places a running server may depend on).

A league's season is given its generation once, when the season starts
(``services.league_rating_centers.league_engine_generation``), and the
tuning of every game it plays is assembled as: engine defaults, then the
generation's profile, then the league's stored commissioner overrides, then
its rating centres (``services.league_tuning``).

The profile file has the format of the KPI harness's ``--tuning-overrides``:
a JSON object of registered knobs, a table knob naming only the entries it
changes. ``scripts/kpi_profiles/r5.json`` is the harness-facing copy of
generation 5 and must stay identical to it (tests/test_r5_flip_registry.py).

Release 6a adds generations UNDER DEVELOPMENT
(``DEVELOPMENT_ENGINE_GENERATIONS``): a profile file exists and the KPI
harness can run it (``--engine 6``), but no league season is ever given one.
They are not in :func:`known_engine_generations`, which is the list the
league side reads -- the operations switch, the generation a new season
gets, what a stored generation is checked against -- so
:func:`engine_profile` refuses them unless the caller says it is a
development run. Switching a generation on is moving it out of the
development list and making it ``CURRENT_ENGINE_GENERATION``.
``scripts/kpi_profiles/r6.json`` is the harness-facing copy of generation 6
(tests/test_r6a_tools_generation.py).

This module imports nothing but the tuning defaults, so the engine, the
services and the scripts can all read it.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Dict, Tuple

from .config import DEFAULT_TUNING

__all__ = [
    "LEGACY_ENGINE_GENERATION",
    "CURRENT_ENGINE_GENERATION",
    "DEVELOPMENT_ENGINE_GENERATIONS",
    "ENGINE_PROFILE_DIR",
    "engine_defaults",
    "engine_profile",
    "engine_profile_path",
    "harness_engine_generations",
    "known_engine_generations",
    "load_engine_profile_file",
    "normalize_engine_generation",
]

# Today's engine: DEFAULT_TUNING with no profile (Release 4b, 7.49 - 7.50).
LEGACY_ENGINE_GENERATION = 4
# The generation a season that has not started yet is given.
CURRENT_ENGINE_GENERATION = 5
# Generations being built (module docstring): the KPI harness runs them, no
# league season is given one. Release 6a: generation 6, whose profile starts
# as generation 5's values exactly.
DEVELOPMENT_ENGINE_GENERATIONS: Tuple[int, ...] = (6,)

ENGINE_PROFILE_DIR = Path(__file__).resolve().parent / "profiles"

# path -> ((mtime_ns, size), parsed profile). The file is re-read when it
# changes, so a retuned profile needs no restart in development.
_PROFILE_CACHE: Dict[str, Tuple[Tuple[int, int], Dict[str, Any]]] = {}


def known_engine_generations() -> Tuple[int, ...]:
    """Every generation a season may be given, the legacy one first."""

    return (LEGACY_ENGINE_GENERATION, CURRENT_ENGINE_GENERATION)


def harness_engine_generations() -> Tuple[int, ...]:
    """Every generation the KPI harness can run (``--engine``): the ones a
    season may be given, then the ones under development."""

    return known_engine_generations() + tuple(DEVELOPMENT_ENGINE_GENERATIONS)


def normalize_engine_generation(value: object) -> int:
    """``value`` as a generation number; anything unreadable is legacy.

    A number below the legacy generation is the legacy generation: there is
    one engine before Release 5 as far as a season is concerned.
    """

    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return LEGACY_ENGINE_GENERATION
    if not math.isfinite(number):
        return LEGACY_ENGINE_GENERATION
    return max(LEGACY_ENGINE_GENERATION, int(number))


def engine_profile_path(generation: object) -> Path:
    """Where the profile of ``generation`` lives (one file per generation)."""

    return ENGINE_PROFILE_DIR / f"engine_{normalize_engine_generation(generation)}.json"


def engine_profile(
    generation: object, *, development: bool = False
) -> Dict[str, Any]:
    """The tuning overrides ``generation`` lays over ``DEFAULT_TUNING``.

    ``{}`` for the legacy generation, so a legacy league's tuning is built
    from exactly what it is built from today. A table knob comes back whole
    (the default table with the profile's entries replaced), ready for
    ``TuningConfig.from_overrides``. Raises ``ValueError`` when the profile
    of a later generation is missing or invalid: a season that was started
    on the new engine must never be played on the old one in silence.

    ``development`` True also answers for a generation that is still being
    built (``DEVELOPMENT_ENGINE_GENERATIONS``). Only the KPI harness passes
    it; without it such a generation is unknown, so nothing on the league
    side can play one.
    """

    number = normalize_engine_generation(generation)
    if number <= LEGACY_ENGINE_GENERATION:
        return {}
    allowed = known_engine_generations()
    if development:
        allowed = harness_engine_generations()
    if number not in allowed:
        raise ValueError(f"unknown engine generation {number}")
    return copy.deepcopy(_cached_profile(engine_profile_path(number)))


def engine_defaults(
    generation: object, *, development: bool = False
) -> Dict[str, float]:
    """Every numeric knob's value with no league override, for ``generation``.

    ``DEFAULT_TUNING`` with the generation's profile over it: what a slider
    reads before the commissioner touches it. ``development`` as in
    :func:`engine_profile`.
    """

    defaults = {
        key: float(value)
        for key, value in DEFAULT_TUNING.items()
        if _is_number(value)
    }
    for key, value in engine_profile(generation, development=development).items():
        if _is_number(value):
            defaults[key] = float(value)
    return defaults


def load_engine_profile_file(path: Path | str) -> Dict[str, Any]:
    """Read and validate a profile file (see the module docstring).

    Every key must be registered in ``DEFAULT_TUNING`` and every value a
    finite number -- ``TuningConfig.from_overrides`` drops an unknown key
    without a word, which would run the old engine while claiming the new
    one. A table knob takes an object of the entries to change and is
    returned as the whole table.
    """

    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"engine profile {path}: cannot read JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"engine profile {path}: expected a JSON object of knobs")
    unknown = sorted(key for key in payload if key not in DEFAULT_TUNING)
    if unknown:
        raise ValueError(
            f"engine profile {path}: unknown tuning key(s) {', '.join(unknown)}"
        )
    profile: Dict[str, Any] = {}
    for key, value in payload.items():
        default = DEFAULT_TUNING[key]
        if isinstance(default, dict):
            profile[key] = _merged_table(path, key, default, value)
        elif _is_number(default) and _is_number(value) and math.isfinite(value):
            profile[key] = float(value)
        else:
            raise ValueError(
                f"engine profile {path}: {key} must be a finite number, got {value!r}"
            )
    return profile


def _cached_profile(path: Path) -> Dict[str, Any]:
    key = str(path)
    try:
        stat = path.stat()
    except OSError as exc:
        raise ValueError(f"engine profile {path}: missing ({exc})") from exc
    signature = (stat.st_mtime_ns, stat.st_size)
    hit = _PROFILE_CACHE.get(key)
    if hit is not None and hit[0] == signature:
        return hit[1]
    profile = load_engine_profile_file(path)
    _PROFILE_CACHE[key] = (signature, profile)
    return profile


def _merged_table(
    path: Path, name: str, default: Dict[str, Any], value: object
) -> Dict[str, Any]:
    """``default`` with the profile's entries replaced, at any depth.

    Tables nest (``swing_count_table`` is count -> zone / chase), so an
    entry that is itself a table is merged the same way. An entry the
    default does not have and a leaf that is not a finite number (or whose
    default is not a number) are errors. ``DEFAULT_TUNING`` is not touched.
    """

    if not isinstance(value, dict):
        raise ValueError(
            f"engine profile {path}: {name} is a table and takes an object"
        )
    merged = copy.deepcopy(default)
    for key, entry in value.items():
        if key not in default:
            raise ValueError(f"engine profile {path}: unknown entry {name}.{key}")
        base = default[key]
        if isinstance(base, dict):
            merged[key] = _merged_table(path, f"{name}.{key}", base, entry)
        elif _is_number(base) and _is_number(entry) and math.isfinite(entry):
            merged[key] = float(entry)
        else:
            raise ValueError(
                f"engine profile {path}: {name}.{key} must be a finite number,"
                f" got {entry!r}"
            )
    return merged


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
