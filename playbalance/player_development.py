"""Training plan helpers used by the spring training camp flow.

The goal is to make training outcomes feel intentional without replacing the
full franchise-mode development pipeline.  Every player gets a lightweight
plan that:

* Picks a focus track (contact, defense, etc.) based on potential gaps.
* Uses the aging curve from :mod:`playbalance.aging` to bias goals for each age.
* Applies capped rating boosts so attributes stay within [0, 99].

The module exposes small dataclasses so UI layers can surface the outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from models.base_player import BasePlayer
from playbalance.aging import AGE_ADJUSTMENTS, calculate_age, spring_training_pitch

# Pitch fields are duplicated here instead of importing the private constant in
# playbalance.aging.  Both modules need to stay in sync if the pitch model
# evolves.
PITCH_FIELDS = ("fb", "cu", "cb", "sl", "si", "scb", "kn")

_HITTER_TRACKS: Dict[str, Tuple[str, ...]] = {
    "contact": ("ch", "vl", "pl"),
    "power": ("ph", "fa"),
    "speed": ("sp",),
    "discipline": ("eye",),
    "defense": ("fa", "arm", "gf"),
}

_PITCHER_TRACKS: Dict[str, Tuple[str, ...]] = {
    "command": ("control",),
    "movement": ("movement",),
    "stamina": ("endurance",),
    "velocity": ("fa", "arm"),
    "hold": ("hold_runner",),
    "pitch_lab": tuple(),
}

_TRACK_LABELS: Dict[str, str] = {
    "contact": "Barrel Control",
    "power": "Strength & Lift",
    "speed": "Speed Lab",
    "discipline": "Approach Review",
    "defense": "Glove & Footwork",
    "command": "Command Clinic",
    "movement": "Movement Lab",
    "stamina": "Endurance Circuit",
    "velocity": "Power Arms",
    "hold": "Running Game Defense",
    "pitch_lab": "Pitch Design",
}

_TRACK_NOTES: Dict[str, str] = {
    "contact": "High-rep contact sessions to tighten strike-zone coverage.",
    "power": "Lower-body strength plus launch-focused cage work.",
    "speed": "Acceleration and agility work to keep legs lively.",
    "discipline": "Film, VR, and decision trays to improve swing decisions.",
    "defense": "Daily glove reps and positioning walkthroughs.",
    "command": "Flat-ground command work and pitch shaping targets.",
    "movement": "Spin efficiency and seam-shifted wake experiments.",
    "stamina": "Long-toss and conditioning to stretch outings.",
    "velocity": "Weighted balls and lower-half sequencing for more zip.",
    "hold": "Slide-step packages and pickoff timing drills.",
    "pitch_lab": "Pitch design groups focusing on a single breaking ball.",
}

_AGE_TIERS = {
    "prospect": range(16, 24),
    "prime": range(24, 30),
    "veteran": range(30, 35),
}

_TIER_GAINS = {"prospect": 4, "prime": 3, "veteran": 2, "mentor": 1}


@dataclass(frozen=True)
class TrainingWeights:
    """Percent allocations applied to hitter/pitcher training tracks."""

    hitters: Mapping[str, float]
    pitchers: Mapping[str, float]

    def hitter_weight(self, track: str) -> float:
        value = self.hitters.get(track)
        return float(value) if value is not None else 0.0

    def pitcher_weight(self, track: str) -> float:
        value = self.pitchers.get(track)
        return float(value) if value is not None else 0.0


@dataclass(slots=True)
class TrainingPlan:
    """Lightweight description of what a player will work on."""

    player_id: str
    player_name: str
    focus: str
    tier: str
    attributes: Tuple[str, ...]
    note: str


@dataclass(slots=True)
class TrainingReport(TrainingPlan):
    """Outcome of executing a training plan."""

    changes: Dict[str, int]


def build_training_plan(
    player: BasePlayer,
    weights: Optional[TrainingWeights] = None,
) -> TrainingPlan:
    """Create a training plan tailored to ``player``."""

    age = calculate_age(player.birthdate)
    tier = _age_tier(age)
    aging_bias = AGE_ADJUSTMENTS.get(age, {})

    if getattr(player, "is_pitcher", False):
        focus, attrs = _select_pitcher_track(player, aging_bias, weights)
    else:
        focus, attrs = _select_hitter_track(player, aging_bias, weights)

    label = _TRACK_LABELS.get(focus, focus.title())
    note = _TRACK_NOTES.get(focus, "Focused skill work during camp.")
    return TrainingPlan(
        player_id=player.player_id,
        player_name=f"{player.first_name} {player.last_name}",
        focus=label,
        tier=tier,
        attributes=attrs,
        note=note,
    )


def apply_training_plan(
    player: BasePlayer,
    plan: TrainingPlan,
    *,
    intensity_multiplier: float = 1.0,
) -> TrainingReport:
    """Apply ``plan`` to ``player`` and return a detailed report."""

    age = calculate_age(player.birthdate)
    tier_gain = _TIER_GAINS[plan.tier]
    adjustments = AGE_ADJUSTMENTS.get(age, {})
    intensity = _normalize_intensity_multiplier(intensity_multiplier)
    changes: Dict[str, int] = {}

    if plan.focus == _TRACK_LABELS.get("pitch_lab"):
        changes = _run_pitch_lab(player, intensity_multiplier=intensity)
    else:
        for attr in plan.attributes:
            delta = _boost_attribute(
                player,
                attr,
                tier_gain,
                adjustments,
                intensity_multiplier=intensity,
            )
            if delta:
                changes[attr] = delta

    return TrainingReport(
        player_id=plan.player_id,
        player_name=plan.player_name,
        focus=plan.focus,
        tier=plan.tier,
        attributes=plan.attributes,
        note=plan.note,
        changes=changes,
    )


def execute_training_cycle(
    players: Iterable[BasePlayer],
    *,
    weights_by_player: Optional[Mapping[str, TrainingWeights]] = None,
) -> Sequence[TrainingReport]:
    """Convenience helper that runs the plan pipeline for an iterable."""

    reports: list[TrainingReport] = []
    for player in players:
        weights = None
        if weights_by_player is not None:
            pid = getattr(player, "player_id", None)
            if pid is not None:
                weights = weights_by_player.get(pid)
        plan = build_training_plan(player, weights=weights)
        reports.append(apply_training_plan(player, plan))
    return reports


# ---------------------------------------------------------------------------
# Plan selection helpers
# ---------------------------------------------------------------------------

def _age_tier(age: int) -> str:
    for tier, age_range in _AGE_TIERS.items():
        if age in age_range:
            return tier
    return "mentor"


def _select_hitter_track(
    player: BasePlayer,
    adjustments: Dict[str, int],
    weights: Optional[TrainingWeights] = None,
) -> Tuple[str, Tuple[str, ...]]:
    best = ("contact", ("ch",))
    best_score = float("-inf")
    for track, attrs in _HITTER_TRACKS.items():
        attr_scores = [
            (attr, _score_attribute(player, attr, adjustments)) for attr in attrs
        ]
        score = sum(val for _, val in attr_scores)
        score *= _track_weight(weights, track, is_pitcher=False)
        candidate = tuple(
            attr for attr, _ in sorted(attr_scores, key=lambda item: item[1], reverse=True)
        )[:2]
        if score > best_score:
            best_score = score
            best = (track, candidate or attrs[:1])
    return best


def _select_pitcher_track(
    player: BasePlayer,
    adjustments: Dict[str, int],
    weights: Optional[TrainingWeights] = None,
) -> Tuple[str, Tuple[str, ...]]:
    best = ("command", ("control",))
    best_score = float("-inf")
    for track, attrs in _PITCHER_TRACKS.items():
        if track == "pitch_lab":
            score = _pitch_lab_score(player)
            score *= _track_weight(weights, track, is_pitcher=True)
            candidate: Tuple[str, ...] = tuple()
        else:
            attr_scores = [
                (attr, _score_attribute(player, attr, adjustments)) for attr in attrs
            ]
            score = sum(val for _, val in attr_scores)
            score *= _track_weight(weights, track, is_pitcher=True)
            candidate = tuple(
                attr
                for attr, _ in sorted(attr_scores, key=lambda item: item[1], reverse=True)
            )[:1]
        if score > best_score:
            best_score = score
            best = (track, candidate)
    focus, attrs = best
    if focus == "pitch_lab":
        return focus, tuple()
    return focus, attrs or ("control",)


def _score_attribute(player: BasePlayer, attr: str, adjustments: Dict[str, int]) -> float:
    current = getattr(player, attr, None)
    if current is None:
        return 0.0
    potential = _resolve_potential(player, attr)
    if potential is None:
        gap = max(0, 75 - current)
    else:
        gap = max(0, potential - current)
    bias = adjustments.get(attr, 0)
    return gap * 1.4 + bias


def _pitch_lab_score(player: BasePlayer) -> float:
    deficits = []
    for pitch in PITCH_FIELDS:
        rating = getattr(player, pitch, 0)
        if rating > 0:
            deficits.append(max(0, 80 - rating))
    if not deficits:
        return 0.0
    return sum(deficits) / len(deficits) + 5.0


# ---------------------------------------------------------------------------
# Weight helpers
# ---------------------------------------------------------------------------


def _track_weight(
    weights: Optional[TrainingWeights], track: str, *, is_pitcher: bool
) -> float:
    if weights is None:
        return 1.0
    value = (
        weights.pitcher_weight(track) if is_pitcher else weights.hitter_weight(track)
    )
    if value <= 0:
        return 0.1
    return value


# ---------------------------------------------------------------------------
# Application helpers
# ---------------------------------------------------------------------------

def _resolve_potential(player: BasePlayer, attr: str) -> int | None:
    candidate = None
    if hasattr(player, "potential") and isinstance(player.potential, dict):
        candidate = player.potential.get(attr)
    if candidate is None:
        pot_field = f"pot_{attr}"
        candidate = getattr(player, pot_field, None)
    if candidate is not None and candidate <= 0:
        return None
    return candidate


def _boost_attribute(
    player: BasePlayer,
    attr: str,
    base_gain: int,
    adjustments: Dict[str, int],
    *,
    intensity_multiplier: float = 1.0,
) -> int:
    current = getattr(player, attr, None)
    if current is None:
        return 0

    potential = _resolve_potential(player, attr)
    ceiling = potential if potential is not None else 99
    room = max(0, ceiling - current)
    if room == 0:
        room = max(0, 99 - current)

    bias = adjustments.get(attr, 0)
    intensity = _normalize_intensity_multiplier(intensity_multiplier)
    gain = max(1, int(round(float(base_gain) * intensity)))
    if bias > 0:
        gain += min(2, (bias + 1) // 2)
    elif bias < 0:
        gain = max(1, gain + bias // 2)

    if room > 0:
        gain = min(gain, room, 5)
    else:
        gain = 1

    if gain <= 0:
        return 0

    setattr(player, attr, current + gain)
    return gain


def _run_pitch_lab(
    player: BasePlayer,
    *,
    intensity_multiplier: float = 1.0,
) -> Dict[str, int]:
    before = {pitch: getattr(player, pitch, 0) for pitch in PITCH_FIELDS}
    spring_training_pitch(player)  # Reuse the existing aging helper for parity.
    intensity = _normalize_intensity_multiplier(intensity_multiplier)
    if abs(intensity - 1.0) > 1e-6:
        for pitch in PITCH_FIELDS:
            old_value = int(before.get(pitch, 0) or 0)
            current = int(getattr(player, pitch, 0) or 0)
            gained = max(0, current - old_value)
            if gained <= 0:
                continue
            scaled_gain = max(1, int(round(gained * intensity)))
            setattr(player, pitch, min(99, old_value + scaled_gain))
    changes: Dict[str, int] = {}
    for pitch, old_value in before.items():
        new_value = getattr(player, pitch, 0)
        delta = new_value - old_value
        if delta > 0:
            changes[pitch] = delta
    return changes


def _normalize_intensity_multiplier(value: object) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 1.0
    return max(0.75, min(1.35, numeric))
