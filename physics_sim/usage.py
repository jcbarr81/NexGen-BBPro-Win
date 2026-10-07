from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date
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


#: A break of more than this many calendar days between his team's games (the
#: All-Star break, a stint off the roster) ends a batter's games-in-a-row
#: streak; a single team off day does not.
_BATTER_STREAK_BREAK_DAYS = 2


@dataclass
class BatterWorkload:
    fatigue_debt: float = 0.0
    last_used_day: int | None = None
    consecutive_days_used: int = 0
    last_update_day: int | None = None
    last_rest_day: int | None = None  # S2-05: game_day of most recent forced rest
    rests: int = 0  # S2-05: season count of forced rests
    # Release 3 fix: his team's games he started in a row. Unlike the
    # calendar-day ``consecutive_days_used``, a team off day does not break
    # it (sitting a team game, or a longer break, does); the pre-game rest's
    # streak limits read it. Older stored workloads load it as 0.
    games_in_a_row: int = 0


def batter_fatigue_threshold(durability: float, tuning: TuningConfig) -> float:
    """Fatigue debt at which a position player starts to play tired.

    The engine's in-game batter penalty starts above it, and the pre-game
    rest trigger sits at ``batter_rest_fatigue_ratio`` (0.85) of it. A more
    durable player carries more: 35 + 0.45 * durability by default (57.5 at
    durability 50).
    """

    threshold = tuning.get("batter_fatigue_threshold_base", 35.0)
    threshold += float(durability or 0.0) * tuning.get("batter_fatigue_threshold_scale", 0.45)
    return threshold


def batter_fatigue_debt_ceiling(durability: float, tuning: TuningConfig) -> float:
    """The most fatigue debt a position player can carry (Release 3).

    The debt at which the in-game penalty reaches its cap:
    threshold * (1 + ``batter_fatigue_penalty_cap`` /
    ``batter_fatigue_penalty_scale``), about 98 at durability 50. Debt past it
    changed nothing in the game but kept growing (to 669 for a catcher nobody
    could rest), so a backup who finally arrived had to sit the regular for a
    dozen straight games while it drained.
    """

    threshold = batter_fatigue_threshold(durability, tuning)
    scale = tuning.get("batter_fatigue_penalty_scale", 0.5)
    cap = tuning.get("batter_fatigue_penalty_cap", 0.35)
    if scale <= 0.0:
        return threshold
    return threshold * (1.0 + max(0.0, cap) / scale)


def batter_game_cost(
    durability: float,
    tuning: TuningConfig,
    *,
    position: str | None = None,
    started: bool = True,
) -> float:
    """Fatigue debt one game adds (Release 3, audit M16).

    By the position he started at: a catcher pays
    ``batter_fatigue_game_cost_catcher``, a DH ``batter_fatigue_game_cost_dh``,
    any other fielder (or an unknown position) the flat
    ``batter_fatigue_game_cost``. A player who only came off the bench (pinch
    hitter, pinch runner, defensive replacement) pays
    ``batter_fatigue_game_cost_sub``. Below durability 50 every cost grows by
    ``batter_fatigue_durability_scale`` per point.
    """

    pos = str(position or "").strip().upper()
    if not started:
        base = tuning.get("batter_fatigue_game_cost_sub", 1.5)
    elif pos == "C":
        base = tuning.get("batter_fatigue_game_cost_catcher", 6.0)
    elif pos in {"DH", "PH", "PR"}:
        base = tuning.get("batter_fatigue_game_cost_dh", 6.0)
    else:
        base = tuning.get("batter_fatigue_game_cost", 6.0)
    scale = tuning.get("batter_fatigue_durability_scale", 0.02)
    return base + max(0.0, (50.0 - float(durability or 0.0)) * scale)


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


def calendar_day(when: date | str, season_start: date | str) -> int:
    """Calendar days from *season_start* to *when* (Release 3 rest clock).

    Opening Day is day 0 and an off day is one more day of rest. Accepts
    ``date`` objects or ISO ``YYYY-MM-DD`` strings; raises ``ValueError`` for
    anything else.
    """

    def _as_date(value: date | str) -> date:
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value).strip()[:10])

    return (_as_date(when) - _as_date(season_start)).days


@dataclass
class UsageState:
    # The rest clock: the CALENDAR day of the current game, counted from the
    # season's first simmed date (decision 9, Release 3). Rest tables, the
    # third-straight-day block, fatigue recovery and batter streaks all count
    # in these days, so an off day is rest.
    current_day: int | None = None
    # Release 3: 0-based index of the current game date -- the number of
    # distinct days advance_day has moved to, so off days never count. Kept
    # apart from ``current_day``; read by the rotation fallback and the
    # appearance caps, which are per game, not per calendar day.
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
            # Release 3 (audit M16): fatigue now accrues. Every calendar day
            # recovers base + scale * durability -- less than a game costs,
            # so an everyday player builds debt -- and a game day he sat out
            # (on the roster, not in the game) recovers
            # ``batter_rest_day_recovery_bonus`` on top: a day off is what
            # clears it. A team off day is only a plain day: under the
            # calendar-day clock (Release 3 item A) off days slow the build-up
            # without stopping it.
            #
            # ``consecutive_days_used`` counts calendar days in a row, so a
            # team off day ends it. ``games_in_a_row`` (Release 3 fix) counts
            # his team's GAMES in a row: sitting a team game resets it, a team
            # off day does not, a longer break (the All-Star break, a stint
            # in the minors) does. The rest limits read it: on the calendar
            # streak every weekly off day reset the count, so the backstop
            # never fired and nearly every regular started all 162.
            bat_base = tuning.get("batter_daily_recovery_base", 6.0)
            bat_scale = tuning.get("batter_daily_recovery_durability_scale", 0.05)
            rest_bonus = tuning.get("batter_rest_day_recovery_bonus", 0.0)
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
                sat_out = workload.last_used_day != last_update
                if sat_out:
                    recovery += rest_bonus  # he sat out his team's game that day
                workload.fatigue_debt = max(0.0, workload.fatigue_debt - recovery)
                workload.last_update_day = day
                if workload.last_used_day is not None and day - workload.last_used_day > 1:
                    workload.consecutive_days_used = 0
                if sat_out or days_passed > _BATTER_STREAK_BREAK_DAYS:
                    workload.games_in_a_row = 0

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
        position: str | None = None,
        started: bool = True,
    ) -> None:
        """Charge one game to ``player_id`` (see :func:`batter_game_cost`).

        A start extends his consecutive-days streak and is his "last used"
        day. Coming off the bench (``started=False``) adds the small
        substitute cost only, so a regular resting today who pinch-hits late
        still had his day off.
        """

        workload = self.batter_workload_for(player_id)
        workload.fatigue_debt += batter_game_cost(
            durability, tuning, position=position, started=started
        )
        # Never past the point where the in-game penalty caps.
        workload.fatigue_debt = min(
            workload.fatigue_debt, batter_fatigue_debt_ceiling(durability, tuning)
        )
        if not started:
            return
        # One more team game in a row (advance_day resets it when he sat a
        # team game); the second game of a doubleheader is the same day.
        if workload.last_used_day is None or workload.games_in_a_row <= 0:
            workload.games_in_a_row = 1
        elif day != workload.last_used_day:
            workload.games_in_a_row += 1
        if workload.last_used_day is not None and day - workload.last_used_day == 1:
            workload.consecutive_days_used += 1
        else:
            workload.consecutive_days_used = 1
        workload.last_used_day = day

    def batter_fatigue_level(
        self, player_id: str, durability: float, tuning: TuningConfig
    ) -> float:
        """How tired ``player_id`` is, as debt / :func:`batter_fatigue_threshold`.

        0 is fresh. At ``batter_rest_fatigue_ratio`` (0.85) the pre-game rest
        triggers; above 1.0 he plays with an in-game penalty. Read-only: never
        creates a workload, so asking about an unknown player returns 0.

        This is not the injury model's scale: the post-game fatigue injury
        roll (``physics_sim.arm_injury.batter_fatigue_level``) reads the
        ``fatigue_level`` the engine stamps on a tired batter -- the penalty
        he actually played with over ``batter_fatigue_penalty_cap``, 0 to 1 --
        so the extra risk follows the applied penalty.
        """

        workload = self.batter_workloads.get(player_id)
        if workload is None:
            return 0.0
        threshold = batter_fatigue_threshold(durability, tuning)
        if threshold <= 0.0:
            return 0.0
        return max(0.0, workload.fatigue_debt) / threshold

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
