"""Automations for disabled list maintenance during simulations.

Who comes off an injured list on his own (Release 3, owner decision Q11):

* a CPU club activates everyone whose stint has run out, from the 15-day and
  the 60-day list alike -- nobody else would;
* an owner's club follows the owner's per-team choices in
  ``services.team_play_settings``: ``il_auto_activate_15`` (default: the
  league's ``auto_activate_il``) and ``il_auto_activate_60`` (default off);
* the deadline fallback (``force_auto_activate``) activates an owner's
  15-day returners only when that owner never made a 15-day choice: an
  owner who turned it off keeps his player listed;
* when team ownership can't be read, every club waits a day -- forced or not.

An owner's returner goes to the active roster only if there is room (and,
for a pitcher, room on the staff). Otherwise he goes to AAA (or Low-A, if he
is young enough for it), the owner gets a "ready - make room" action item on
the Season page, and nobody else on the owner's roster is moved: the CPU
never makes room on an owner's club.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Union

from services.injury_manager import (
    disabled_list_days_remaining,
    disabled_list_label,
    recover_from_injury,
)
from services.team_auto_reassign_settings import auto_reassign_team_if_enabled
from services.roster_auto_assign import ACTIVE_MAX, AAA_MAX, LOW_MAX
from services.roster_validation import LOW_LEVEL_MAX_AGE
from services.players_repository import save_players
from utils.news_logger import log_news_event
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import active_pitcher_cap, active_roster_cap, load_roster
from utils.roster_loader import save_roster
from utils.roster_rules import counts_as_pitcher
from utils.team_loader import load_teams

DateLike = Union[None, str, date]

#: Owner returners parked in the minors for lack of room, kept for the
#: Season page's "ready - make room" action item.
AWAITING_ROOM_FILENAME = "il_returns_awaiting_room.json"
#: How many league days the reminder stays up if the owner leaves him down.
AWAITING_ROOM_DAYS = 10
_AWAITING_ROOM_LOCK = threading.Lock()


@dataclass
class DLAutomationSummary:
    activated: List[str] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    blocked: List[str] = field(default_factory=list)
    lineup_restored: List[str] = field(default_factory=list)
    awaiting_owner: List[str] = field(default_factory=list)
    # Owner returners sent to the minors because the active roster was full.
    awaiting_room: List[str] = field(default_factory=list)

    def has_updates(self) -> bool:
        return any(
            (
                self.activated,
                self.alerts,
                self.blocked,
                self.lineup_restored,
                self.awaiting_owner,
                self.awaiting_room,
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


def _act_block_reason(
    roster,
    player=None,
    players_by_id: Optional[Dict[str, object]] = None,
) -> Optional[str]:
    """Why an owner's returner can't join the active roster, or None if he can.

    ``"active_full"`` when the active roster is at its cap; ``"pitcher_cap"``
    when there is an active spot but he is a pitcher and the staff is already
    at the limit (13; 14 in September) -- activating one more would block the
    owner's next sim.
    """

    act = list(getattr(roster, "act", []) or [])
    if len(act) >= active_roster_cap():
        return "active_full"
    if counts_as_pitcher(player):
        lookup = players_by_id or {}
        arms = sum(1 for pid in act if counts_as_pitcher(lookup.get(pid)))
        if arms >= active_pitcher_cap():
            return "pitcher_cap"
    return None


def _low_eligible(player) -> bool:
    """True unless ``player`` is known to be too old for Low-A.

    Age on the real calendar date, the basis the roster validator uses
    (``api.routers.validation``), so a returner the automation parks in Low-A
    is one the owner's own roster validation accepts.
    """

    raw = str(getattr(player, "birthdate", "") or "").strip()
    if not raw:
        return True
    try:
        born = date.fromisoformat(raw.split("T", 1)[0][:10])
    except ValueError:
        return True
    today = date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return age < LOW_LEVEL_MAX_AGE


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
    if _act_block_reason(roster, player, players_by_id) is None:
        return "act"
    if len(getattr(roster, "aaa", []) or []) < AAA_MAX:
        return "aaa"
    # Low-A takes only players under its age limit. A veteran with no room in
    # AAA stays listed (blocked) and the owner gets the "ready" item instead.
    if len(getattr(roster, "low", []) or []) < LOW_MAX and _low_eligible(player):
        return "low"
    return None


def _owner_chose(team_id: str, list_level: str, data_dir) -> bool:
    """True when the owner explicitly stored a choice for this list.

    A settings file that exists but can't be read counts as a choice, so the
    deadline fallback never overrides an owner on a guess.
    """

    from services.team_play_settings import (
        IL_AUTO_ACTIVATE_15,
        IL_AUTO_ACTIVATE_60,
        SETTINGS_FILENAME,
        load_team_play_overrides,
    )

    key = IL_AUTO_ACTIVATE_60 if list_level == "ir" else IL_AUTO_ACTIVATE_15
    try:
        path = Path(data_dir) / SETTINGS_FILENAME
        if path.exists():
            json.loads(path.read_text(encoding="utf-8"))
        return key in load_team_play_overrides(team_id, data_dir=data_dir)
    except Exception:
        return True


def _owner_auto_activates(team_id: str, list_level: str, data_dir) -> bool:
    """The owner's per-team choice for this list (owner decision Q11).

    ``list_level`` is the roster level: ``"dl"`` (the 7/10/15-day lists) or
    ``"ir"`` (the 60-day list). A broken settings read falls back to the
    defaults: the 15-day list follows the league setting, which itself fails
    open, and the 60-day list stays manual.
    """

    from services.team_play_settings import (
        IL_AUTO_ACTIVATE_15,
        IL_AUTO_ACTIVATE_60,
        get_team_play_setting,
    )

    key = IL_AUTO_ACTIVATE_60 if list_level == "ir" else IL_AUTO_ACTIVATE_15
    try:
        return bool(get_team_play_setting(team_id, key, data_dir=data_dir))
    except Exception:  # pragma: no cover - defensive
        return list_level != "ir"


def process_disabled_lists(
    today: DateLike = None,
    *,
    days_elapsed: int = 1,
    auto_activate: bool = True,
    force_auto_activate: bool = False,
    force_teams: Optional[Iterable[str]] = None,
) -> DLAutomationSummary:
    """Progress disabled list eligibility and optionally activate players.

    ``auto_activate`` is the caller's intent. A CPU club always activates; an
    owner's club follows the owner's per-team 15-day and 60-day choices
    (``services.team_play_settings``). ``force_auto_activate`` is the
    fallback for batch tools and the deadline CPU fill: it activates an
    owner's 15-day returners only when the owner never chose for that list
    (owner decision Q11: an explicit "off" is honoured every day); an owner's
    60-day list always follows his 60-day choice. When team ownership can't
    be read nobody is activated, forced or not. ``force_teams`` limits the
    fallback to those clubs (the deadline passes the owners who are not
    ready, i.e. not showing up); None applies it to every club.
    """

    forced_ids = (
        None if force_teams is None else {str(t).upper() for t in force_teams}
    )

    summary = DLAutomationSummary()
    target_date = _coerce_date(today)
    data_dir = get_data_dir()
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
    parked: Dict[str, List[dict]] = {}

    for team in teams:
        team_id = getattr(team, "team_id", "")
        if not team_id:
            continue
        try:
            roster = load_roster(team_id)
        except Exception:
            continue
        rosters[team_id] = roster
        cpu_club = human_ids is not None and str(team_id).upper() not in human_ids
        entries = [(pid, "dl") for pid in list(getattr(roster, "dl", []) or [])]
        entries += [(pid, "ir") for pid in list(getattr(roster, "ir", []) or [])]
        for pid, list_level in entries:
            player = player_map.get(pid)
            if player is None:
                continue
            days_remaining = disabled_list_days_remaining(player, today=target_date)
            if days_remaining is None or days_remaining > 0:
                continue
            # ``ready`` also records that the "ready" news line went out. On a
            # day ownership can't be read the only line logged is "retrying",
            # so the flag waits for the first day ownership is known and the
            # owner still gets his "waiting on the owner" line then.
            newly_ready = not getattr(player, "ready", False)
            if newly_ready and human_ids is not None:
                player.ready = True
                mutated_players.add(pid)

            list_label = disabled_list_label(getattr(player, "injury_list", ""))
            base_msg = f"{_player_name(player)} ready to return from {list_label or 'injury list'} ({team_id})"

            if not auto_activate:
                summary.alerts.append(base_msg)
                log_news_event(base_msg, category="injury")
                continue

            if human_ids is None:
                # Ownership unknown: stand down, even under force. A guess
                # could activate an owner's player or park a CPU returner.
                activate = False
            elif cpu_club:
                activate = True
            elif (
                force_auto_activate
                and (forced_ids is None or str(team_id).upper() in forced_ids)
                and list_level == "dl"
                and not _owner_chose(team_id, list_level, data_dir)
            ):
                # The deadline fallback, for an owner who never chose.
                activate = True
            else:
                activate = _owner_auto_activates(team_id, list_level, data_dir)
            if not activate:
                # The owner runs this list by hand -- or team ownership
                # couldn't be read, and every club waits a day.
                summary.awaiting_owner.append(
                    f"{_player_name(player)} is eligible to come off the "
                    f"{list_label or 'injured list'} ({team_id})"
                )
                if newly_ready:
                    why = (
                        " — team ownership couldn't be read; retrying next sim day."
                        if human_ids is None
                        else " — waiting on the owner."
                    )
                    log_news_event(base_msg + why, category="injury", team_id=team_id)
                continue

            block_reason = (
                None if cpu_club else _act_block_reason(roster, player, player_map)
            )
            destination = _resolve_destination(
                roster,
                cpu_owned=cpu_club,
                player=player,
                players_by_id=player_map,
            )
            if destination is None:
                summary.blocked.append(f"{base_msg} but no roster room is available.")
                if newly_ready:  # once per stint; the Season page keeps reminding
                    log_news_event(
                        f"{base_msg} but no roster space available.",
                        category="injury",
                        team_id=team_id,
                    )
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

            if destination != "act" and not cpu_club:
                # An owner's club with no room: he waits in the minors and
                # the owner decides who makes way. Nobody else is moved.
                entry = {
                    "player_id": pid,
                    "list": list_label or "injured list",
                    "level": destination,
                    "date": target_date.isoformat(),
                    # The Season page item says why he is waiting.
                    "reason": block_reason or "active_full",
                }
                if block_reason == "pitcher_cap":
                    entry["pitcher_cap"] = active_pitcher_cap()
                parked.setdefault(str(team_id).upper(), []).append(entry)
                summary.awaiting_room.append(
                    f"{_player_name(player)} is healthy and waiting in "
                    f"{dest_label} for an active-roster spot ({team_id})"
                )
                if block_reason == "pitcher_cap":
                    msg += (
                        " — the pitching staff is at the "
                        f"{active_pitcher_cap()}-pitcher limit. Make room to "
                        "bring him up."
                    )
                else:
                    msg += (
                        " — no room on the active roster. Make room to bring "
                        "him up."
                    )

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
            log_news_event(msg, category="injury", team_id=team_id)

    if mutated_rosters:
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

    try:
        _update_awaiting_room(
            parked, rosters=rosters, today=target_date, data_dir=data_dir
        )
    except Exception:  # pragma: no cover - the reminder is best effort
        pass

    return summary


# ---------------------------------------------------------------------------
# "Ready - make room" reminders for owners
# ---------------------------------------------------------------------------


def players_awaiting_room(
    team_id: str,
    *,
    levels: Mapping[str, Sequence[str]],
    today: DateLike = None,
    data_dir=None,
) -> List[dict]:
    """Owner returners still parked in the minors for lack of room.

    ``levels`` is the team's current roster as ``{level: [player_id, ...]}``
    (``api.routers.validation.load_team_levels``). An entry counts while the
    player is still in the club's AAA/Low-A and the reminder is under
    :data:`AWAITING_ROOM_DAYS` league days old. Read-only.
    """

    key = str(team_id or "").strip().upper()
    if not key:
        return []
    payload = _load_awaiting_room(data_dir)
    entries = (payload.get("teams") or {}).get(key) or []
    minors = set(levels.get("aaa", []) or []) | set(levels.get("low", []) or [])
    current = _coerce_date(today)
    out: List[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("player_id") or "") not in minors:
            continue
        if _entry_expired(entry, current):
            continue
        out.append(dict(entry))
    return out


def _entry_expired(entry: Mapping[str, object], today: date) -> bool:
    try:
        when = date.fromisoformat(str(entry.get("date") or "")[:10])
    except ValueError:
        return True
    return today - when > timedelta(days=AWAITING_ROOM_DAYS)


def _awaiting_room_path(data_dir) -> Path:
    base = Path(data_dir) if data_dir is not None else get_data_dir()
    return base / AWAITING_ROOM_FILENAME


def _load_awaiting_room(data_dir) -> dict:
    try:
        payload = json.loads(_awaiting_room_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "teams": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("teams"), dict):
        return {"version": 1, "teams": {}}
    return payload


def _update_awaiting_room(
    parked: Mapping[str, List[dict]],
    *,
    rosters: Mapping[str, object],
    today: date,
    data_dir,
) -> None:
    """Add today's parked returners and drop reminders that no longer apply."""

    with _AWAITING_ROOM_LOCK:
        payload = _load_awaiting_room(data_dir)
        teams = payload.get("teams") or {}
        if not teams and not parked:
            return
        roster_by_key = {str(t).upper(): r for t, r in rosters.items()}
        updated: Dict[str, List[dict]] = {}
        for key in sorted(set(teams) | set(parked)):
            entries = [e for e in teams.get(key) or [] if isinstance(e, dict)]
            fresh = list(parked.get(key) or [])
            fresh_ids = {e["player_id"] for e in fresh}
            entries = [e for e in entries if e.get("player_id") not in fresh_ids]
            roster = roster_by_key.get(key)
            if roster is not None:
                minors = set(getattr(roster, "aaa", []) or []) | set(
                    getattr(roster, "low", []) or []
                )
                entries = [e for e in entries if e.get("player_id") in minors]
            entries = [e for e in entries if not _entry_expired(e, today)]
            entries += fresh
            if entries:
                updated[key] = entries
        if updated == teams:
            return
        path = _awaiting_room_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
        try:
            tmp.write_text(
                json.dumps({"version": 1, "teams": updated}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


__all__ = [
    "AWAITING_ROOM_DAYS",
    "AWAITING_ROOM_FILENAME",
    "DLAutomationSummary",
    "players_awaiting_room",
    "process_disabled_lists",
]
