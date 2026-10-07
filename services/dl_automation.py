"""Automations for disabled list maintenance during simulations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Union

from services.injury_manager import (
    disabled_list_days_remaining,
    disabled_list_label,
    recover_from_injury,
)
from services.team_auto_reassign_settings import auto_reassign_team_if_enabled
from services.roster_auto_assign import ACTIVE_MAX, AAA_MAX, LOW_MAX
from services.players_repository import save_players
from utils.news_logger import log_news_event
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import active_pitcher_cap, active_roster_cap, load_roster
from utils.roster_loader import save_roster
from utils.roster_rules import counts_as_pitcher
from utils.team_loader import load_teams

DateLike = Union[None, str, date]


@dataclass
class DLAutomationSummary:
    activated: List[str] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    blocked: List[str] = field(default_factory=list)
    lineup_restored: List[str] = field(default_factory=list)
    awaiting_owner: List[str] = field(default_factory=list)

    def has_updates(self) -> bool:
        return any(
            (
                self.activated,
                self.alerts,
                self.blocked,
                self.lineup_restored,
                self.awaiting_owner,
            )
        )


def _coerce_date(value: DateLike) -> date:
    """Resolve a caller's date, defaulting to the LEAGUE's current sim date.

    The season router calls this with ``today=None`` and a comment saying it
    "defaults to current sim date" — which was not true: it fell through to the
    wall clock, so players were activated off the injured list after N days of
    real time rather than N days of league time.
    """

    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    try:
        from utils.sim_date import get_current_sim_date

        sim_date = (get_current_sim_date() or "").strip()
        if sim_date:
            return date.fromisoformat(sim_date[:10])
    except Exception:  # pragma: no cover - defensive
        pass
    return datetime.now(timezone.utc).date()


def _player_name(player) -> str:
    return f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip() or getattr(player, "player_id", "")


def _resolve_destination(
    roster,
    *,
    cpu_owned: bool = False,
    player=None,
    players_by_id: Optional[Dict[str, object]] = None,
) -> Optional[str]:
    # A CPU club always brings a healthy player back to the active roster;
    # recover_from_injury sends his like-for-like replacement down if the
    # roster is full (or a pitcher if the staff is). Sending the returner to
    # AAA instead is how CPU active rosters lost a hitter for good every time
    # one got hurt (audit H9).
    if cpu_owned:
        return "act"
    act = list(getattr(roster, "act", []) or [])
    room = len(act) < active_roster_cap()
    if room and counts_as_pitcher(player):
        # An owner's pitcher comes back to the active roster only if the
        # staff is under the limit (13; 14 in September): activating a 14th
        # would block the owner's next sim.
        lookup = players_by_id or {}
        arms = sum(1 for pid in act if counts_as_pitcher(lookup.get(pid)))
        room = arms < active_pitcher_cap()
    if room:
        return "act"
    if len(getattr(roster, "aaa", []) or []) < AAA_MAX:
        return "aaa"
    if len(getattr(roster, "low", []) or []) < LOW_MAX:
        return "low"
    return None


def _teams_managing_their_own_il(data_dir) -> set | None:
    """Human-owned teams that have opted out of automatic activation.

    CPU teams are never in this set: nobody is watching them, so a club without
    an owner must keep activating on its own or it would strand healthy players
    on the list forever.
    """

    try:
        from utils.league_settings import auto_activate_il

        if auto_activate_il():
            return set()
    except Exception:  # pragma: no cover - defensive
        return set()
    try:
        from services.team_ownership import human_owned_team_ids_strict

        # None (users.txt unreadable): every club waits a day rather than an
        # owner's injured list being run for him.
        return human_owned_team_ids_strict(data_dir)
    except Exception:  # pragma: no cover - defensive
        return None


def process_disabled_lists(
    today: DateLike = None,
    *,
    days_elapsed: int = 1,
    auto_activate: bool = True,
    force_auto_activate: bool = False,
) -> DLAutomationSummary:
    """Progress disabled list eligibility and optionally activate players.

    ``auto_activate`` is the caller's intent; the league's ``auto_activate_il``
    setting can still hold back HUMAN-owned teams so their owner decides when a
    player comes back. ``force_auto_activate`` overrides that for batch tools
    (the long-run sim harness) that have no owner to wait for.
    """

    summary = DLAutomationSummary()
    target_date = _coerce_date(today)
    owner_managed = (
        set()
        if (force_auto_activate or not auto_activate)
        else _teams_managing_their_own_il(get_data_dir())
    )
    players = list(load_players_from_csv("data/players.csv"))
    player_map = {getattr(p, "player_id", ""): p for p in players}
    teams = []
    try:
        teams = load_teams()
    except Exception:
        return summary

    rosters: Dict[str, object] = {}
    mutated_rosters: set[str] = set()
    try:
        from services.team_ownership import human_owned_team_ids_strict

        # None when ownership can't be read: treat every club as an owner's.
        human_ids = human_owned_team_ids_strict()
    except Exception:  # pragma: no cover - defensive
        human_ids = None
    mutated_players: set[str] = set()

    for team in teams:
        team_id = getattr(team, "team_id", "")
        if not team_id:
            continue
        try:
            roster = load_roster(team_id)
        except Exception:
            continue
        rosters[team_id] = roster
        # The 60-day list (roster.ir) is managed by hand -- except at a CPU
        # club, where nobody would ever activate him and his like-for-like
        # call-up would be permanent (audit H9 review).
        cpu_club = human_ids is not None and str(team_id).upper() not in human_ids
        dl_entries = list(getattr(roster, "dl", []) or [])
        if cpu_club:
            dl_entries += list(getattr(roster, "ir", []) or [])
        if not dl_entries:
            continue
        for pid in dl_entries:
            player = player_map.get(pid)
            if player is None:
                continue
            days_remaining = disabled_list_days_remaining(player, today=target_date)
            ready_for_return = False
            if days_remaining is not None and days_remaining <= 0:
                ready_for_return = True
                if not getattr(player, "ready", False):
                    player.ready = True
                    mutated_players.add(pid)

            if not ready_for_return:
                continue

            list_label = disabled_list_label(getattr(player, "injury_list", ""))
            base_msg = f"{_player_name(player)} ready to return from {list_label or 'injury list'} ({team_id})"

            if auto_activate and (
                owner_managed is None or str(team_id).upper() in owner_managed
            ):
                # The owner runs this team's injured list by hand -- or team
                # ownership couldn't be read, and every club waits a day.
                summary.awaiting_owner.append(
                    f"{_player_name(player)} is eligible to come off the "
                    f"{list_label or 'injured list'} ({team_id})"
                )
                why = (
                    " — team ownership couldn't be read; retrying next sim day."
                    if owner_managed is None
                    else " — waiting on the owner."
                )
                log_news_event(base_msg + why, category="injury")
                continue

            if auto_activate:
                destination = _resolve_destination(
                    roster,
                    cpu_owned=human_ids is not None and str(team_id).upper() not in human_ids,
                    player=player,
                    players_by_id=player_map,
                )
                if destination is None:
                    summary.blocked.append(f"{base_msg} but no roster room is available.")
                    log_news_event(f"{base_msg} but no roster space available.", category="injury")
                    continue
                try:
                    recover_from_injury(
                        player, roster, destination=destination, players_by_id=player_map
                    )
                except ValueError:
                    summary.alerts.append(base_msg)
                    log_news_event(base_msg, category="injury")
                    continue
                mutated_players.add(pid)
                mutated_rosters.add(team_id)
                dest_label = destination.upper()
                msg = f"Activated {_player_name(player)} to {dest_label} ({team_id})"

                # Coming off the list isn't symmetrical with going on it. The
                # injury left the lineup a man short, so the sim rebuilt it and
                # a replacement took the spot; activation restores the roster
                # but leaves a perfectly valid nine in place, so the regular
                # starter would sit behind his own backup indefinitely. Put him
                # back wherever the depth chart says he's the starter.
                if destination == "act":
                    try:
                        from services.lineup_restore import restore_depth_chart_starter

                        restored = restore_depth_chart_starter(
                            team_id,
                            pid,
                            lineup_dir=get_data_dir() / "lineups",
                            active_ids=list(getattr(roster, "act", []) or []),
                        )
                        if restored:
                            position = next(iter(restored.values()))
                            msg += f", back in the lineup at {position}"
                            summary.lineup_restored.append(
                                f"{_player_name(player)} restored at {position} ({team_id})"
                            )
                    except Exception:  # pragma: no cover - defensive
                        pass

                summary.activated.append(msg)
                log_news_event(msg, category="injury")
            else:
                summary.alerts.append(base_msg)
                log_news_event(base_msg, category="injury")

    if mutated_rosters:
        data_dir = get_data_dir()
        for team_id in mutated_rosters:
            save_roster(team_id, rosters[team_id])
            try:
                auto_reassign_team_if_enabled(
                    team_id,
                    players_file=data_dir / "players.csv",
                    roster_dir=data_dir / "rosters",
                    data_dir=data_dir,
                )
            except Exception:
                pass
        try:
            load_roster.cache_clear()  # type: ignore[attr-defined]
        except Exception:
            pass

    if mutated_players:
        dest_path = get_data_dir() / "players.csv"
        save_players(players, dest_path)

    return summary


__all__ = ["DLAutomationSummary", "process_disabled_lists"]
