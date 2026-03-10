"""Utilities for handling player injuries and disabled list logistics.

This module keeps a consistent contract between the roster and player data
when someone is moved to or from the 15-day disabled list or injured reserve.
It tracks minimum stint lengths, start dates, and provides helpers for
UI/simulation layers to reason about eligibility.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Mapping, Optional

from models.player import Player
from models.roster import Roster
from services.depth_chart_manager import promote_depth_chart_replacement
from services.prospect_event_log import (
    record_roster_level_movements,
    roster_level_map,
)
from services.prospect_rules import apply_roster_move, evaluate_roster_move

DL_MINIMUM_DAYS = {"dl15": 15}
DL_LABELS = {
    "dl15": "15-Day DL",
    "ir": "Injured Reserve",
}


def _today() -> date:
    return date.today()


def _parse_iso(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_list_name(list_name: str) -> str:
    normalized = (list_name or "").strip().lower()
    if normalized in {"dl", "dl15", "15", "15-day", "15 day"}:
        return "dl15"
    if normalized in {"dl45", "45", "45-day", "45 day"}:
        return "ir"
    if normalized in {"ir", "injured reserve"}:
        return "ir"
    raise ValueError("list_name must be one of dl15 or ir")


def disabled_list_label(list_name: Optional[str]) -> str:
    """Return a user-friendly label for ``list_name``."""

    if not list_name:
        return ""
    normalized = list_name.strip().lower()
    if normalized in {"dl45", "45", "45-day", "45 day"}:
        return DL_LABELS.get("ir", "Injured Reserve")
    return DL_LABELS.get(normalized, list_name.upper())


def disabled_list_days_remaining(player: Player, today: Optional[date] = None) -> Optional[int]:
    """Number of days remaining before the player can be activated."""

    list_name = (getattr(player, "injury_list", None) or "").lower()
    if list_name not in DL_MINIMUM_DAYS:
        return None
    today = today or _today()
    eligible_date = _parse_iso(getattr(player, "injury_eligible_date", None))
    if eligible_date is None:
        start = _parse_iso(getattr(player, "injury_start_date", None))
        if start is None:
            return None
        eligible_date = start + timedelta(days=DL_MINIMUM_DAYS[list_name])
    remaining = (eligible_date - today).days
    return max(0, remaining) if remaining > 0 else 0


def is_player_dl_eligible(player: Player, today: Optional[date] = None) -> bool:
    """Return ``True`` when the player may be activated from the DL."""

    remaining = disabled_list_days_remaining(player, today=today)
    return remaining is None or remaining <= 0


def place_on_injury_list(
    player: Player,
    roster: Roster,
    list_name: str = "dl15",
    *,
    today: Optional[date] = None,
) -> None:
    """Move *player* to an injury list and promote a replacement."""

    normalized = _normalize_list_name(list_name)
    today = today or _today()
    before_levels = roster_level_map(roster)
    if getattr(roster, "dl_tiers", None) is None:
        roster.dl_tiers = {}

    for level in ("act", "aaa", "low", "dl", "ir"):
        level_list = getattr(roster, level)
        if player.player_id in level_list:
            level_list.remove(player.player_id)
            if level == "dl":
                roster.dl_tiers.pop(player.player_id, None)
            break

    if normalized == "ir":
        if player.player_id not in roster.ir:
            roster.ir.append(player.player_id)
    else:
        if player.player_id not in roster.dl:
            roster.dl.append(player.player_id)
        roster.dl_tiers[player.player_id] = normalized

    player.injured = True
    player.injury_list = normalized
    player.injury_start_date = today.isoformat()
    player.injury_minimum_days = DL_MINIMUM_DAYS.get(normalized)
    if player.injury_minimum_days:
        eligible_on = today + timedelta(days=player.injury_minimum_days)
        player.injury_eligible_date = eligible_on.isoformat()
        if not player.return_date:
            player.return_date = player.injury_eligible_date
    else:
        player.injury_eligible_date = None
    player.injury_rehab_assignment = None
    player.injury_rehab_days = 0
    player.ready = False

    promoted = False
    try:
        promoted = promote_depth_chart_replacement(
            roster,
            getattr(player, "primary_position", None),
            exclude={player.player_id},
        )
    except Exception:
        promoted = False
    if not promoted:
        roster.promote_replacements()
    _enforce_injury_replacement_eligibility(roster, before_levels)
    after_levels = roster_level_map(roster)
    try:
        record_roster_level_movements(
            before_levels,
            after_levels,
            team_id=str(getattr(roster, "team_id", "") or ""),
            player_names={
                player.player_id: (
                    f"{getattr(player, 'first_name', '')} "
                    f"{getattr(player, 'last_name', '')}"
                ).strip()
            },
            actor="system",
            trigger="injury_list_placement",
            details={"list_name": normalized},
        )
    except Exception:
        pass


def _enforce_injury_replacement_eligibility(
    roster: Roster,
    before_levels: Mapping[str, str],
) -> None:
    team_id = str(getattr(roster, "team_id", "") or "").strip()
    if not team_id:
        return
    current_levels = roster_level_map(roster)
    blocked_promotions = 0
    for player_id, from_level in before_levels.items():
        if from_level not in {"aaa", "low"}:
            continue
        if current_levels.get(player_id) != "act":
            continue
        decision = evaluate_roster_move(
            team_id,
            player_id,
            from_level=from_level,
            to_level="act",
        )
        if decision.allowed:
            try:
                apply_roster_move(
                    team_id,
                    player_id,
                    from_level=from_level,
                    to_level="act",
                    decision=decision,
                    actor="system",
                    trigger="injury_replacement_promotion",
                )
            except Exception:
                pass
            continue

        blocked_promotions += 1
        if player_id in roster.act:
            roster.act.remove(player_id)
        if from_level == "aaa":
            if player_id not in roster.aaa:
                roster.aaa.append(player_id)
        elif from_level == "low" and player_id not in roster.low:
            roster.low.append(player_id)

    if blocked_promotions <= 0:
        return
    for source_level in ("aaa", "low"):
        source = getattr(roster, source_level)
        for player_id in list(source):
            if blocked_promotions <= 0:
                return
            decision = evaluate_roster_move(
                team_id,
                player_id,
                from_level=source_level,
                to_level="act",
            )
            if not decision.allowed:
                continue
            source.remove(player_id)
            roster.act.append(player_id)
            try:
                apply_roster_move(
                    team_id,
                    player_id,
                    from_level=source_level,
                    to_level="act",
                    decision=decision,
                    actor="system",
                    trigger="injury_replacement_promotion",
                )
            except Exception:
                pass
            blocked_promotions -= 1


def recover_from_injury(
    player: Player,
    roster: Roster,
    destination: str = "act",
    *,
    force: bool = False,
    today: Optional[date] = None,
) -> None:
    """Return *player* from an injury list to the roster."""

    if destination not in {"act", "aaa", "low"}:
        raise ValueError("destination must be one of act, aaa or low")

    before_levels = roster_level_map(roster)
    if getattr(roster, "dl_tiers", None) is None:
        roster.dl_tiers = {}

    list_name = (getattr(player, "injury_list", None) or "").lower()
    if list_name in DL_MINIMUM_DAYS and not force:
        if not is_player_dl_eligible(player, today=today):
            remaining = disabled_list_days_remaining(player, today=today)
            raise ValueError(f"{remaining} day(s) remaining on {DL_LABELS[list_name]}")

    for level in ("dl", "ir"):
        level_list = getattr(roster, level)
        if player.player_id in level_list:
            level_list.remove(player.player_id)
            if level == "dl":
                roster.dl_tiers.pop(player.player_id, None)
            break

    player.injured = False
    player.injury_description = None
    player.return_date = None
    player.injury_list = None
    player.injury_start_date = None
    player.injury_minimum_days = None
    player.injury_eligible_date = None
    player.injury_rehab_assignment = None
    player.injury_rehab_days = 0
    player.ready = True

    getattr(roster, destination).append(player.player_id)

    if destination == "act":
        for idx in range(len(roster.act) - 1, -1, -1):
            pid = roster.act[idx]
            if pid != player.player_id:
                roster.aaa.append(roster.act.pop(idx))
                break
    after_levels = roster_level_map(roster)
    try:
        record_roster_level_movements(
            before_levels,
            after_levels,
            team_id=str(getattr(roster, "team_id", "") or ""),
            player_names={
                player.player_id: (
                    f"{getattr(player, 'first_name', '')} "
                    f"{getattr(player, 'last_name', '')}"
                ).strip()
            },
            actor="system",
            trigger="injury_recovery",
            details={"destination": destination},
        )
    except Exception:
        pass


__all__ = [
    "DL_LABELS",
    "DL_MINIMUM_DAYS",
    "disabled_list_days_remaining",
    "disabled_list_label",
    "is_player_dl_eligible",
    "place_on_injury_list",
    "recover_from_injury",
]

