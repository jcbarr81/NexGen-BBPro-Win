"""Utilities for handling player injuries and injured list logistics.

This module keeps a consistent contract between the roster and player data
when someone is moved to or from an injured list. It tracks minimum stint
lengths, start dates, and provides helpers for UI/simulation layers to reason
about eligibility.

Two rules from MLB drive everything here:

* The minimums are **calendar days on the LEAGUE's clock**, counted from the
  placement date — off days count. Every date in this module is a sim date, so
  a stint elapses when the season advances, not when the wall clock does.
* A minimum is a FLOOR, not the recovery time. A player can miss six weeks on
  the 10-day IL, so eligibility is ``max(tier minimum, the injury's own
  duration)`` and a longer injury is never shortened to its tier minimum.
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

# MLB's injured lists. The 10/15 split is real: position players go on the
# 10-day IL, while pitchers and two-way players were moved to a 15-day minimum
# in 2022 so clubs could not cycle fresh arms through short stints. The 60-day
# IL also clears the player off the 40-man roster.
IL_MINIMUM_DAYS = {"il7": 7, "il10": 10, "il15": 15, "il60": 60}
IL_LABELS = {
    "il7": "7-Day IL",
    "il10": "10-Day IL",
    "il15": "15-Day IL",
    "il60": "60-Day IL",
}

# Legacy tier names still present in stored rosters/players and in the injury
# catalog. "dl15" predates the 2017 split, so it resolves by role at read time;
# everything else maps straight across.
_LEGACY_TIER_ALIASES = {
    "dl": "dl15",
    "dl15": "dl15",
    "15": "dl15",
    "15-day": "dl15",
    "15 day": "dl15",
    "dl45": "il60",
    "45": "il60",
    "45-day": "il60",
    "45 day": "il60",
    "ir": "il60",
    "injured reserve": "il60",
    "il7": "il7",
    "il10": "il10",
    "il15": "il15",
    "il60": "il60",
    "7-day": "il7",
    "10-day": "il10",
}

# Back-compat aliases for callers that still import the old names.
DL_MINIMUM_DAYS = IL_MINIMUM_DAYS
DL_LABELS = IL_LABELS


def _today() -> date:
    """Today on the LEAGUE's calendar.

    The injured list is measured in league days, so this must be the sim date.
    It used to be ``date.today()``, which meant a stint expired after 15 days of
    real time no matter how much (or how little) baseball had been played: sim a
    season in an afternoon and nobody healed, leave the league alone for a
    fortnight and everyone did. Falls back to the wall clock only when there is
    no schedule to read (a bare fixture, or before a season exists).
    """

    try:
        from utils.sim_date import get_current_sim_date

        parsed = _parse_iso(get_current_sim_date())
        if parsed is not None:
            return parsed
    except Exception:  # pragma: no cover - defensive
        pass
    return date.today()


def injury_list_for(player: Player, list_name: str) -> str:
    """Resolve a tier name to the IL this player actually belongs on.

    A legacy ``dl15`` means "a standard IL stint", which is 15 days for a
    pitcher and 10 for a position player.
    """

    normalized = (list_name or "").strip().lower()
    resolved = _LEGACY_TIER_ALIASES.get(normalized, normalized)
    if resolved == "dl15":
        return "il15" if _is_pitcher(player) else "il10"
    return resolved


def _is_pitcher(player: object) -> bool:
    """Pitchers take the 15-day list, position players the 10-day.

    Checks the position as well as the flag: rosters built from CSV don't
    always carry ``is_pitcher``, and getting this wrong silently puts a
    pitcher on the position-player list.
    """

    if bool(getattr(player, "is_pitcher", False)):
        return True
    position = str(getattr(player, "primary_position", "") or "").strip().upper()
    return position in {"P", "SP", "RP", "CL", "SU"}


def _parse_iso(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_list_name(list_name: str, player: Optional[Player] = None) -> str:
    normalized = (list_name or "").strip().lower()
    resolved = _LEGACY_TIER_ALIASES.get(normalized, normalized)
    if resolved == "dl15":
        # Role-dependent, so it needs the player; without one assume a position
        # player's 10-day list.
        return "il15" if (player is not None and _is_pitcher(player)) else "il10"
    if resolved not in IL_MINIMUM_DAYS:
        raise ValueError(
            "list_name must be one of " + ", ".join(sorted(IL_MINIMUM_DAYS))
        )
    return resolved


def disabled_list_label(list_name: Optional[str]) -> str:
    """Return a user-friendly label for ``list_name``."""

    if not list_name:
        return ""
    normalized = list_name.strip().lower()
    resolved = _LEGACY_TIER_ALIASES.get(normalized, normalized)
    if resolved == "dl15":
        # No player in hand to pick 10 vs 15; label it generically.
        return "IL"
    return IL_LABELS.get(resolved, list_name.upper())


def disabled_list_days_remaining(player: Player, today: Optional[date] = None) -> Optional[int]:
    """League days remaining before the player can be activated.

    ``None`` means "not on an injured list" (day-to-day players have no
    minimum). Resolves legacy tier names so a roster saved before the MLB
    tiers landed still counts down instead of reading as no-minimum — which is
    how anyone stored on the old ``ir`` became instantly activatable.
    """

    stored = (getattr(player, "injury_list", None) or "").lower()
    if not stored or stored in {"none", "null"}:
        return None
    try:
        list_name = injury_list_for(player, stored)
    except Exception:  # pragma: no cover - defensive
        return None
    if list_name not in IL_MINIMUM_DAYS:
        return None
    today = today or _today()
    eligible_date = _parse_iso(getattr(player, "injury_eligible_date", None))
    if eligible_date is None:
        start = _parse_iso(getattr(player, "injury_start_date", None))
        if start is None:
            return None
        eligible_date = start + timedelta(days=IL_MINIMUM_DAYS[list_name])
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

    normalized = _normalize_list_name(list_name, player)
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

    # The 60-day list is the one that clears the player off the active roster
    # (in MLB it also drops him from the 40-man), so it uses the roster's `ir`
    # level. This compared against "ir" before the tiers were renamed — leaving
    # it would have quietly routed 60-day players onto the short-list level.
    if normalized == "il60":
        if player.player_id not in roster.ir:
            roster.ir.append(player.player_id)
    else:
        if player.player_id not in roster.dl:
            roster.dl.append(player.player_id)
        roster.dl_tiers[player.player_id] = normalized

    player.injured = True
    player.injury_list = normalized
    player.injury_start_date = today.isoformat()

    # The tier minimum is a FLOOR. The caller (the simulator) has already set
    # how long this injury actually keeps the player out, and a six-week
    # hamstring does not heal in ten days because that is the list minimum —
    # so take whichever is longer. Overwriting with the flat minimum is what
    # used to erase the injury's real duration.
    tier_minimum = IL_MINIMUM_DAYS.get(normalized, 0)
    try:
        injury_days = int(getattr(player, "injury_minimum_days", 0) or 0)
    except (TypeError, ValueError):
        injury_days = 0
    stint_days = max(tier_minimum, injury_days)

    player.injury_minimum_days = stint_days or None
    if stint_days:
        eligible_on = today + timedelta(days=stint_days)
        player.injury_eligible_date = eligible_on.isoformat()
        player.return_date = player.injury_eligible_date
    else:
        player.injury_eligible_date = None
        player.return_date = None
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

    stored = (getattr(player, "injury_list", None) or "").lower()
    list_name = ""
    if stored and stored not in {"none", "null"}:
        try:
            list_name = injury_list_for(player, stored)
        except Exception:  # pragma: no cover - defensive
            list_name = ""
    if list_name in IL_MINIMUM_DAYS and not force:
        if not is_player_dl_eligible(player, today=today):
            remaining = disabled_list_days_remaining(player, today=today)
            raise ValueError(
                f"{remaining} day(s) remaining on {IL_LABELS[list_name]}"
            )

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
    "IL_LABELS",
    "IL_MINIMUM_DAYS",
    "injury_list_for",
    "disabled_list_days_remaining",
    "disabled_list_label",
    "is_player_dl_eligible",
    "place_on_injury_list",
    "recover_from_injury",
]

