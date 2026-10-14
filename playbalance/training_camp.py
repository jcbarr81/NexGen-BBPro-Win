"""Logic for handling spring training camp simulations.

The real game would feature complex simulations to evaluate players
before the season begins.  For the purposes of this project the training
camp simply marks each player as ``ready`` which can be used by other
parts of the system to determine if a player is prepared for the regular
season.

Players on rating scale 2 do not gain ratings in camp: their year's
development (growth shared out by the training focus, budgets, decline)
ran at the season rollover (``playbalance.development``,
``services.offseason_development``). Camp marks them ready and reports
that development, so the camp summary and the "(+x)" badges keep showing
the year's gains. Players on scale 1 train exactly as they did in 7.51.2,
except in the spring after a rollback to scale 1 that came after the
offseason's development (``services.offseason_development.
withhold_scale1_camp``): those players already grew that offseason, so camp
marks them ready and reports that development, with no gains of its own.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Mapping, Sequence

from models.base_player import BasePlayer
from playbalance.player_development import (
    TrainingReport,
    TrainingWeights,
    apply_training_plan,
    build_training_plan,
    require_engine_scale_players,
)
from services.training_history import record_training_session
from utils.rating_scale import LEGACY_RATING_SCALE, rating_scale_of

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

    A scale 2 player's ratings are not touched (module docstring); his
    report carries the last offseason's development.
    """

    players = list(players)
    legacy = [p for p in players if rating_scale_of(p) == LEGACY_RATING_SCALE]
    # Scale 1 players only: the training mechanics refuse anyone else.
    require_engine_scale_players(legacy, "Training camp")
    withheld = bool(legacy) and _camp_gains_withheld()
    developed = (
        _offseason_development() if withheld or len(legacy) < len(players) else {}
    )
    reports: list[TrainingReport] = []
    trained: list[TrainingReport] = []
    for player in players:
        if withheld or rating_scale_of(player) != LEGACY_RATING_SCALE:
            player.ready = True
            reports.append(_development_report(player, developed))
            continue
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
        trained.append(report)
    try:
        # The offseason development is already in the training history (it
        # was recorded when it ran); only what camp itself did goes in.
        record_training_session(trained)
    except Exception as exc:  # pragma: no cover - defensive, persistence should not block flow
        logger.exception("Failed to record training camp session: %s", exc)
    return reports


def _current_league_year() -> Any:
    try:
        from playbalance.season_context import SeasonContext

        return (SeasonContext.load().current or {}).get("league_year")
    except Exception:
        return None


def _camp_gains_withheld() -> bool:
    """True in the spring after a rollback to scale 1 that came after the
    offseason's development (module docstring)."""

    try:
        from services.offseason_development import (
            CAMP_WITHHELD_KEY,
            camp_gains_withheld,
            load_development_record,
        )

        record = load_development_record()
        if not record.get(CAMP_WITHHELD_KEY):
            return False  # every league that was not rolled back
        return camp_gains_withheld(record, _current_league_year())
    except Exception:
        return False


def _offseason_development() -> Dict[str, Any]:
    """player id -> {"focus", "changes"} of this season's offseason
    development; empty when the record is missing or from another year."""

    try:
        from services.offseason_development import load_development_record

        record = load_development_record()
    except Exception:
        return {}
    players = record.get("players")
    if not isinstance(players, dict):
        return {}
    try:
        from playbalance.season_context import SeasonContext

        year = (SeasonContext.load().current or {}).get("league_year")
    except Exception:
        year = None
    if year is not None and record.get("season") is not None:
        try:
            if int(year) != int(record["season"]):
                return {}
        except (TypeError, ValueError):
            return {}
    return players


def _development_report(player: BasePlayer, developed: Mapping[str, Any]) -> TrainingReport:
    from services.offseason_development import DEVELOPMENT_NOTE, DEVELOPMENT_TIER

    pid = str(getattr(player, "player_id", "") or "")
    entry = developed.get(pid) if isinstance(developed, Mapping) else None
    entry = entry if isinstance(entry, Mapping) else {}
    changes = {
        str(key): int(value)
        for key, value in (entry.get("changes") or {}).items()
        if isinstance(value, (int, float)) and value
    }
    return TrainingReport(
        player_id=pid,
        player_name=f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip(),
        focus=str(entry.get("focus") or "Offseason development"),
        tier=DEVELOPMENT_TIER,
        attributes=tuple(sorted(changes)),
        note=DEVELOPMENT_NOTE,
        changes=changes,
    )


def _normalize_intensity(value: object) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 1.0
    return max(0.75, min(1.35, numeric))
