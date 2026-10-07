from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, Iterable, Optional

from .config import TuningConfig
from .models import BatterRatings, PitcherRatings


@dataclass
class PitcherWorkload:
    fatigue_debt: float = 0.0
    last_used_day: int | None = None
    consecutive_days_used: int = 0
    last_update_day: int | None = None
    appearances: int = 0
    last_pitches: int = 0


@dataclass
class BatterWorkload:
    fatigue_debt: float = 0.0
    last_used_day: int | None = None
    consecutive_days_used: int = 0
    last_update_day: int | None = None
    last_rest_day: int | None = None  # S2-05: game_day of most recent forced rest
    rests: int = 0  # S2-05: season count of forced rests


def reliever_rest_days(pitches: int, tuning: "TuningConfig | None" = None) -> int:
    """Full off days required after a relief outing of ``pitches`` pitches.

    Canonical table shared by the physics engine (UsageState gating) and
    utils.pitcher_recovery (tracker availability) — S2-03.
    """
    def _knob(name: str, default: float) -> float:
        return tuning.get(name, default) if tuning is not None else default

    if pitches <= int(_knob("reliever_rest_b2b_max_pitches", 12.0)):
        return 0
    if pitches <= int(_knob("reliever_rest_one_day_max_pitches", 25.0)):
        return 1
    if pitches <= int(_knob("reliever_rest_two_day_max_pitches", 40.0)):
        return 2
    return 3


@dataclass
class UsageState:
    current_day: int | None = None
    # Release 3: 0-based index of the current game date -- the number of
    # distinct days advance_day has moved to, so off days never count. Kept
    # apart from ``current_day`` (the rest clock). Nothing in the engine reads
    # it yet; it is persisted and merged with the rest of the state.
    game_index: int = 0
    workloads: Dict[str, PitcherWorkload] = field(default_factory=dict)
    batter_workloads: Dict[str, BatterWorkload] = field(default_factory=dict)

    def workload_for(self, pitcher_id: str) -> PitcherWorkload:
        if pitcher_id not in self.workloads:
            self.workloads[pitcher_id] = PitcherWorkload()
        return self.workloads[pitcher_id]

    def batter_workload_for(self, player_id: str) -> BatterWorkload:
        if player_id not in self.batter_workloads:
            self.batter_workloads[player_id] = BatterWorkload()
        return self.batter_workloads[player_id]

    def advance_day(
        self,
        *,
        day: int,
        pitchers: Iterable[PitcherRatings],
        batters: Iterable[BatterRatings] | None = None,
        tuning: TuningConfig,
    ) -> None:
        if self.current_day is None:
            self.current_day = day
        elif day > self.current_day:
            self.current_day = day
            self.game_index += 1
        if day < self.current_day:
            return

        pitch_base = tuning.get("daily_recovery_base", 20.0)
        pitch_scale = tuning.get("daily_recovery_durability_scale", 0.4)
        for pitcher in pitchers:
            workload = self.workload_for(pitcher.player_id)
            last_update = workload.last_update_day
            if last_update is None:
                workload.last_update_day = day
                continue
            days_passed = day - last_update
            if days_passed <= 0:
                continue
            recovery = days_passed * (pitch_base + pitcher.durability * pitch_scale)
            workload.fatigue_debt = max(0.0, workload.fatigue_debt - recovery)
            workload.last_update_day = day
            if workload.last_used_day is not None and day - workload.last_used_day > 1:
                workload.consecutive_days_used = 0

        if batters:
            bat_base = tuning.get("batter_daily_recovery_base", 6.0)
            bat_scale = tuning.get("batter_daily_recovery_durability_scale", 0.05)
            for batter in batters:
                workload = self.batter_workload_for(batter.player_id)
                last_update = workload.last_update_day
                if last_update is None:
                    workload.last_update_day = day
                    continue
                days_passed = day - last_update
                if days_passed <= 0:
                    continue
                recovery = days_passed * (bat_base + batter.durability * bat_scale)
                workload.fatigue_debt = max(0.0, workload.fatigue_debt - recovery)
                workload.last_update_day = day
                if workload.last_used_day is not None and day - workload.last_used_day > 1:
                    workload.consecutive_days_used = 0

    def record_outing(
        self,
        *,
        pitcher_id: str,
        pitches: int,
        day: int,
        multiplier: float,
        tuning: TuningConfig,
    ) -> None:
        workload = self.workload_for(pitcher_id)
        debt_scale = tuning.get("fatigue_debt_scale", 1.0)
        workload.fatigue_debt += pitches * debt_scale * multiplier
        if workload.last_used_day is not None and day - workload.last_used_day == 1:
            workload.consecutive_days_used += 1
        else:
            workload.consecutive_days_used = 1
        workload.last_used_day = day
        workload.last_pitches = pitches
        workload.appearances += 1
        penalty = tuning.get("consecutive_usage_penalty", 8.0)
        if workload.consecutive_days_used > 1:
            workload.fatigue_debt += penalty * (workload.consecutive_days_used - 1)

    def record_batter_game(
        self,
        *,
        player_id: str,
        day: int,
        durability: float,
        tuning: TuningConfig,
    ) -> None:
        workload = self.batter_workload_for(player_id)
        cost_base = tuning.get("batter_fatigue_game_cost", 6.0)
        cost_scale = tuning.get("batter_fatigue_durability_scale", 0.02)
        cost = cost_base + max(0.0, (50.0 - durability) * cost_scale)
        workload.fatigue_debt += cost
        if workload.last_used_day is not None and day - workload.last_used_day == 1:
            workload.consecutive_days_used += 1
        else:
            workload.consecutive_days_used = 1
        workload.last_used_day = day


def _workload_from_dict(cls: type, data: Any) -> Any:
    """Build a workload dataclass from a stored dict, ignoring unknown keys
    so state saved by a newer or older build still loads."""
    names = {item.name for item in fields(cls)}
    if not isinstance(data, dict):
        return cls()
    return cls(**{key: value for key, value in data.items() if key in names})


def usage_state_to_dict(
    state: UsageState, *, pids: Optional[set] = None
) -> Dict[str, Any]:
    """Serialize a :class:`UsageState` to a JSON-safe dict (Release 3).

    Shared by the per-league store (``playbalance.usage_store``) and the
    parallel-day payloads. When *pids* is given only those players' workloads
    are included.
    """

    def _filter(workloads: Dict[str, Any]) -> Dict[str, dict]:
        return {
            pid: asdict(workload)
            for pid, workload in workloads.items()
            if pids is None or pid in pids
        }

    return {
        "current_day": state.current_day,
        "game_index": state.game_index,
        "workloads": _filter(state.workloads),
        "batter_workloads": _filter(state.batter_workloads),
    }


def usage_state_from_dict(data: Optional[Dict[str, Any]]) -> UsageState:
    """Rebuild a :class:`UsageState` from :func:`usage_state_to_dict` output."""

    data = data if isinstance(data, dict) else {}
    try:
        game_index = int(data.get("game_index") or 0)
    except (TypeError, ValueError):
        game_index = 0
    state = UsageState(current_day=data.get("current_day"), game_index=game_index)
    for pid, item in (data.get("workloads") or {}).items():
        state.workloads[str(pid)] = _workload_from_dict(PitcherWorkload, item)
    for pid, item in (data.get("batter_workloads") or {}).items():
        state.batter_workloads[str(pid)] = _workload_from_dict(BatterWorkload, item)
    return state
