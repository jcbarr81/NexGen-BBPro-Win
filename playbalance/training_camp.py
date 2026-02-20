"""Logic for handling spring training camp simulations.

The real game would feature complex simulations to evaluate players
before the season begins.  For the purposes of this project the training
camp simply marks each player as ``ready`` which can be used by other
parts of the system to determine if a player is prepared for the regular
season.
"""

from __future__ import annotations

import logging
from typing import Iterable, Mapping, Sequence

from models.base_player import BasePlayer
from playbalance.player_development import (
    TrainingReport,
    TrainingWeights,
    apply_training_plan,
    build_training_plan,
)
from services.training_history import record_training_session

logger = logging.getLogger(__name__)


def run_training_camp(
    players: Iterable[BasePlayer],
    allocations: Mapping[str, TrainingWeights] | None = None,
    intensity_by_player: Mapping[str, float] | None = None,
) -> Sequence[TrainingReport]:
    """Run a spring training simulation and return development reports.

    Each player receives a focused training plan. Attributes may see small,
    capped boosts based on age, potential, and the existing aging model. Every
    participant is marked ``ready`` when camp ends.  When ``allocations`` are
    provided, the per-track weightings influence which development focus is
    selected for each player. When ``intensity_by_player`` is provided, each
    player's gains are scaled by the configured multiplier.
    """

    reports: list[TrainingReport] = []
    for player in players:
        weights = None
        if allocations is not None:
            pid = getattr(player, "player_id", None)
            if pid is not None:
                weights = allocations.get(pid)
        intensity = 1.0
        if intensity_by_player is not None:
            pid = getattr(player, "player_id", None)
            if pid is not None:
                intensity = _normalize_intensity(intensity_by_player.get(pid, 1.0))
        plan = build_training_plan(player, weights=weights)
        report = apply_training_plan(
            player,
            plan,
            intensity_multiplier=intensity,
        )
        player.ready = True
        reports.append(report)
    try:
        record_training_session(reports)
    except Exception as exc:  # pragma: no cover - defensive, persistence should not block flow
        logger.exception("Failed to record training camp session: %s", exc)
    return reports


def _normalize_intensity(value: object) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 1.0
    return max(0.75, min(1.35, numeric))

