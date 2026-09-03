"""Simulation helpers for deriving injuries from gameplay triggers.

This module consumes ``data/injury_catalog.json`` and exposes a small API that
simulators can call whenever an injury-eligible trigger occurs (collisions,
HBPs, pitcher overuse, etc.).  It translates the trigger context into a
probability, selects an injury template, and returns a structured outcome that
callers can pass to ``services.injury_manager.place_on_injury_list``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from utils.path_utils import resolve_app_path


CATALOG_PATH = "data/injury_catalog.json"
DEFAULT_SEVERITY_WEIGHTS = {"minor": 0.7, "moderate": 0.25, "major": 0.05}
logger = logging.getLogger(__name__)

_FALLBACK_INJURY_CATALOG: Dict[str, Any] = {
    "metadata": {
        "name": "Auto-generated fallback",
        "source": "services.injury_simulator",
        "description": (
            "Generated when data/injury_catalog.json is missing so that the season "
            "simulator can continue to run with a small injury set."
        ),
    },
    "triggers": {
        "collision": {
            "base_probability": 0.12,
            "modifiers": {"durability_factor": -0.35},
            "severities": ["minor", "moderate"],
        },
        "hit_by_pitch": {
            "base_probability": 0.08,
            "modifiers": {"durability_factor": -0.25},
            "severities": ["minor"],
        },
        "pitcher_overuse": {
            "base_probability": 0.18,
            "modifiers": {"fatigue_factor": 0.45},
            "severities": ["moderate", "major"],
        },
        # Phase 1 of injury calibration: these three triggers are DEFINED (and
        # kept identical to data/injury_catalog.json so the seed test's
        # calibration-neutrality check passes) but the engines don't yet roll
        # them. Engine call sites (Phase 2) + probability calibration (Phase 3)
        # are pending. Values here are starting points, not final.
        "throwing": {
            "base_probability": 0.06,
            "modifiers": {"durability_factor": -0.30},
            "severities": ["minor", "moderate", "major"],
        },
        "swing": {
            "base_probability": 0.008,
            "modifiers": {"durability_factor": -0.20},
            "severities": ["minor", "moderate", "major"],
        },
        "fielding": {
            "base_probability": 0.05,
            "modifiers": {"durability_factor": -0.30},
            "severities": ["minor", "moderate", "major"],
        },
    },
    "injuries": [
        {
            "id": "fallback_bruise",
            "name": "Bruised Shoulder",
            "body_part": "shoulder",
            "eligible_triggers": ["collision", "hit_by_pitch"],
            "severity_profiles": {
                "minor": {
                    "min_days": 1,
                    "max_days": 3,
                    "dl_tier": "none",
                    "description": "Day-to-day shoulder bruise",
                    "attributes_penalty": {"pow": -2, "con": -1},
                }
            },
        },
        {
            "id": "fallback_oblique",
            "name": "Strained Oblique",
            "body_part": "core",
            "eligible_triggers": ["collision"],
            "severity_profiles": {
                "moderate": {
                    "min_days": 7,
                    "max_days": 12,
                    "dl_tier": "dl15",
                    "description": "Moderate oblique strain",
                    "attributes_penalty": {"spd": -3, "con": -2},
                }
            },
        },
        {
            "id": "fallback_elbow",
            "name": "Elbow Tendinitis",
            "body_part": "elbow",
            "eligible_triggers": ["pitcher_overuse"],
            "pitcher_only": True,
            "severity_profiles": {
                "moderate": {
                    "min_days": 10,
                    "max_days": 18,
                    "dl_tier": "dl15",
                    "description": "Tendinitis flare-up",
                    "attributes_penalty": {"vel": -3, "ctrl": -2},
                },
                "major": {
                    "min_days": 30,
                    "max_days": 45,
                    "dl_tier": "ir",
                    "description": "Severe tendinitis",
                    "attributes_penalty": {"vel": -5, "sta": -4},
                },
            },
        },
    ],
}


def _fallback_catalog() -> Dict[str, Any]:
    """Return a deep copy of the embedded fallback catalog."""

    return json.loads(json.dumps(_FALLBACK_INJURY_CATALOG))


def _bootstrap_catalog_file(path: Path) -> Dict[str, Any]:
    """Write a fallback catalog to ``path`` and return its data."""

    catalog = _fallback_catalog()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(catalog, fh, indent=2)
    except Exception as exc:  # pragma: no cover - best-effort bootstrap
        logger.warning("Unable to write fallback injury catalog to %s: %s", path, exc)
    return catalog


def _catalog_cache_key(path: Path) -> tuple[str, int | None, int | None]:
    resolved = path.resolve(strict=False)
    try:
        stat_result = resolved.stat()
    except OSError:
        return str(resolved), None, None
    mtime_ns = getattr(stat_result, "st_mtime_ns", None)
    if mtime_ns is None:
        mtime_ns = int(stat_result.st_mtime * 1_000_000_000)
    return str(resolved), mtime_ns, stat_result.st_size


@lru_cache(maxsize=16)
def _load_injury_catalog_cached(
    source_key: tuple[str, int | None, int | None],
) -> Dict[str, Any]:
    catalog_path = Path(source_key[0])
    try:
        with catalog_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:  # pragma: no cover - runtime bootstrap
        catalog = _bootstrap_catalog_file(catalog_path)
        logger.warning(
            "Injury catalog missing at %s; generated fallback catalog with %d injuries.",
            catalog_path,
            len(catalog.get("injuries", [])),
        )
        return catalog
    except json.JSONDecodeError as exc:  # pragma: no cover - recover from corruption
        catalog = _bootstrap_catalog_file(catalog_path)
        logger.warning(
            "Injury catalog at %s is corrupt (%s); regenerated fallback catalog.",
            catalog_path,
            exc,
        )
        return catalog


def load_injury_catalog(path: str = CATALOG_PATH) -> Dict[str, Any]:
    """Load and cache the injury catalog JSON file."""

    catalog_path = resolve_app_path(path)
    return _load_injury_catalog_cached(_catalog_cache_key(catalog_path))


load_injury_catalog.cache_clear = _load_injury_catalog_cached.cache_clear  # type: ignore[attr-defined]


@dataclass
class InjuryOutcome:
    """Structured result describing a freshly-created injury."""

    injury_id: str
    name: str
    severity: str
    days: int
    dl_tier: str
    body_part: str
    attributes_penalty: Mapping[str, int]
    description: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "injury_id": self.injury_id,
            "name": self.name,
            "severity": self.severity,
            "days": self.days,
            "dl_tier": self.dl_tier,
            "body_part": self.body_part,
            "attributes_penalty": dict(self.attributes_penalty),
            "description": self.description,
        }


class InjurySimulator:
    """Probability engine that selects injuries based on catalog metadata."""

    def __init__(
        self,
        *,
        catalog: Optional[Dict[str, Any]] = None,
        rng: Optional[random.Random] = None,
        severity_weights: Optional[Mapping[str, float]] = None,
    ) -> None:
        self.catalog = catalog or load_injury_catalog()
        self.triggers = self.catalog.get("triggers", {})
        self.injuries = list(self.catalog.get("injuries", []))
        self.rng = rng or random.Random()
        self.severity_weights = dict(severity_weights or DEFAULT_SEVERITY_WEIGHTS)

    @staticmethod
    def _normalize_tier(value: str | None) -> str:
        """Map catalog tiers onto MLB's injured lists.

        ``dl15`` stays as-is here rather than resolving to a list: the standard
        stint is 10 days for a position player and 15 for a pitcher, and this
        function has no player in hand. ``services.injury_manager`` makes that
        call at placement time.
        """

        tier = (value or "dl15").strip().lower()
        if tier in {"dl45", "45", "45-day", "45 day", "ir", "injured reserve", "il60"}:
            return "il60"
        if tier in {"il7", "7-day", "7 day"}:
            return "il7"
        if tier in {"il10", "10-day", "10 day"}:
            return "il10"
        if tier in {"il15", "dl15", "dl", "15", "15-day", "15 day"}:
            return "dl15"
        if tier == "none":
            return "none"
        return "dl15"

    def available_triggers(self) -> List[str]:
        return list(self.triggers.keys())

    def maybe_create_injury(
        self,
        trigger: str,
        player: object,
        *,
        context: Optional[Mapping[str, float]] = None,
        force: bool = False,
        severity_override: Optional[str] = None,
        is_pitcher: Optional[bool] = None,
    ) -> Optional[InjuryOutcome]:
        """Attempt to generate an injury for ``player`` based on ``trigger``.

        Parameters
        ----------
        trigger:
            Name of the injury trigger (e.g., ``collision``, ``hit_by_pitch``).
        player:
            Player-like object; fields ``is_pitcher``/``primary_position`` are
            inspected to enforce pitcher-only injuries.
        context:
            Optional mapping of modifier values (e.g., ``fatigue``,
            ``pitch_velocity``). All unspecified metrics default to ``0``.
        force:
            When ``True`` the probability roll is skipped. Useful for tests or
            scripted outcomes.
        severity_override:
            Force a specific severity tier (``minor``/``moderate``/``major``).
        """

        trigger_def = self.triggers.get(trigger)
        if not trigger_def:
            return None

        ctx = dict(context or {})
        ctx.setdefault("durability", self._player_durability(player))
        probability = self._compute_probability(trigger_def, ctx)
        if not force:
            roll = self.rng.random()
            if roll >= probability:
                return None

        severity = severity_override or self._choose_severity(trigger_def)
        if severity is None:
            return None

        template_pair = self._choose_injury_template(
            trigger, severity, player, is_pitcher=is_pitcher
        )
        if template_pair is None:
            return None
        injury, profile = template_pair
        min_days = int(profile.get("min_days", 1))
        max_days = int(max(min_days, profile.get("max_days", min_days)))
        days = self.rng.randint(min_days, max_days)
        dl_tier = self._normalize_tier(profile.get("dl_tier"))
        attributes_penalty = profile.get("attributes_penalty", {})
        description = profile.get("description") or injury.get("name", "Injury")

        return InjuryOutcome(
            injury_id=str(injury.get("id") or injury.get("name", "")).lower(),
            name=injury.get("name", "Injury"),
            severity=severity,
            days=days,
            dl_tier=dl_tier,
            body_part=injury.get("body_part", ""),
            attributes_penalty=attributes_penalty,
            description=description,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _compute_probability(
        self,
        trigger_def: Mapping[str, Any],
        context: Mapping[str, float],
    ) -> float:
        probability = float(trigger_def.get("base_probability", 0.0))
        modifiers = trigger_def.get("modifiers") or {}
        for modifier_key, factor in modifiers.items():
            metric_key = modifier_key.replace("_factor", "")
            metric_value = float(context.get(metric_key, 0.0) or 0.0)
            probability *= max(0.0, 1.0 + (float(factor) * metric_value))
        return min(max(probability, 0.0), 1.0)

    def _choose_severity(self, trigger_def: Mapping[str, Any]) -> Optional[str]:
        severities: List[str] = list(trigger_def.get("severities") or [])
        if not severities:
            severities = list(self.severity_weights.keys())
        # A trigger may override the global minor/moderate/major mix with its own
        # "severity_weights" — e.g. arm injuries skew toward the longer "major"
        # tier so average days-per-stint reflects real serious injuries.
        weight_source = trigger_def.get("severity_weights") or self.severity_weights
        weights = [float(weight_source.get(sev, 0.0)) for sev in severities]
        total = sum(weights)
        if total <= 0:
            return self.rng.choice(severities) if severities else None
        roll = self.rng.random() * total
        upto = 0.0
        for sev, weight in zip(severities, weights):
            upto += weight
            if roll <= upto:
                return sev
        return severities[-1]

    def _choose_injury_template(
        self,
        trigger: str,
        severity: str,
        player: object,
        is_pitcher: Optional[bool] = None,
    ) -> Optional[tuple[Mapping[str, Any], Mapping[str, Any]]]:
        # Physics-engine pitcher objects (PitcherRatings) carry neither
        # ``is_pitcher`` nor ``primary_position``, so callers that know the role
        # (e.g. the overuse path) pass it explicitly; otherwise auto-detect.
        if is_pitcher is None:
            is_pitcher = bool(
                getattr(player, "is_pitcher", False)
                or str(getattr(player, "primary_position", "")).upper() == "P"
            )
        candidates: List[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        for injury in self.injuries:
            triggers = injury.get("eligible_triggers") or []
            if trigger not in triggers:
                continue
            if injury.get("pitcher_only") and not is_pitcher:
                continue
            if injury.get("hitter_only") and is_pitcher:
                continue
            severity_profiles = injury.get("severity_profiles") or {}
            profile = severity_profiles.get(severity)
            if profile is None:
                continue
            candidates.append((injury, profile))
        if not candidates:
            return None
        return self.rng.choice(candidates)

    @staticmethod
    def _player_durability(player: object) -> float:
        value = getattr(player, "durability", 50)
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 50.0
        return max(0.0, min(1.0, value / 100.0))


__all__ = ["InjurySimulator", "InjuryOutcome", "load_injury_catalog"]
