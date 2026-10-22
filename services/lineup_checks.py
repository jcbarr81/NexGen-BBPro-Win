"""Lineups, staff and depth charts that name players a club no longer has,
and a club with no catcher (8.4.1).

At the rollover, expiring contracts and retirements take players off every
roster, but an owner's saved lineups, pitching staff and depth chart are the
owner's and are left alone. In alpha-test six of the seven owners' lineups
still named players who had left. A game copes: it rebuilds a saved lineup
that names an inactive player (``playbalance.game_runner._sanitize_lineup``)
and plays the active pitchers only, but the owner learned of it from a news
item after the first game. These reports let the Spotlight and the
commissioner's readiness board say so before Opening Day.

Everything here is advisory and read-only. None of it is a readiness
*issue*: the not-ready list also drives the scheduled runs' CPU fill of an
owner's roster and their forced injured-list activations, which a stale
lineup must not trigger.

A club with no healthy catcher on its active roster plays a position player
behind the plate (``utils.lineup_autofill.build_lineup``); stats-test's OKL
carries one catcher in its whole organisation and lost him to the injured
list in the playoffs. :func:`catcher_report` names who could catch instead.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "stale_assignments",
    "catcher_report",
    "stale_assignment_notes",
    "stale_assignments_text",
]

_LEVEL_NOTES = {
    "aaa": "in AAA",
    "low": "in Low-A",
    "dl": "on the injured list",
    "ir": "on the injured list",
}


def _data_dir() -> Path:
    from utils.path_utils import get_data_dir

    return Path(get_data_dir())


def _name(players: Mapping[str, Mapping[str, Any]], pid: str) -> str:
    row = players.get(pid) or {}
    name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
    return name or pid


class _Whereabouts:
    """Where each player is now, relative to one club: its own roster levels,
    another club, retired, or gone (a free agent)."""

    def __init__(self, team_id: str, levels: Mapping[str, List[str]], root: Path) -> None:
        self.team_id = team_id
        self.level: Dict[str, str] = {}
        for level, ids in levels.items():
            for pid in ids or ():
                self.level.setdefault(pid, level)
        self._root = root
        self._clubs: Optional[Dict[str, str]] = None
        self._retired: Optional[set] = None

    def _other_club(self, pid: str) -> str:
        if self._clubs is None:
            self._clubs = {}
            for path in sorted((self._root / "rosters").glob("*.csv")):
                club = path.stem
                if club.endswith("_pitching") or club == self.team_id:
                    continue
                try:
                    with path.open("r", encoding="utf-8", newline="") as fh:
                        for row in csv.reader(fh):
                            if row and row[0].strip():
                                self._clubs.setdefault(row[0].strip(), club)
                except OSError:
                    continue
        return self._clubs.get(pid, "")

    def _is_retired(self, pid: str) -> bool:
        if self._retired is None:
            try:
                from services.player_retirement import load_retirees

                self._retired = set(load_retirees(self._root))
            except Exception:
                self._retired = set()
        return pid in self._retired

    def in_org(self, pid: str) -> bool:
        return pid in self.level

    def note(self, pid: str) -> str:
        """Why ``pid`` is not on the active roster ("" when he is)."""

        level = self.level.get(pid)
        if level == "act":
            return ""
        if level:
            return _LEVEL_NOTES.get(level, "not active")
        if self._is_retired(pid):
            return "retired"
        club = self._other_club(pid)
        return f"now with {club}" if club else "left the club"


def _lineup_rows(team_id: str, vs: str) -> List[tuple]:
    from utils.lineup_loader import load_lineup

    try:
        return list(load_lineup(team_id, vs=vs))
    except FileNotFoundError:
        return []


def _staff_rows(root: Path, team_id: str) -> List[tuple]:
    path = root / "rosters" / f"{team_id}_pitching.csv"
    if not path.exists():
        return []
    rows: List[tuple] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) >= 2 and row[0].strip():
                rows.append((row[0].strip(), row[1].strip().upper()))
    return rows


def stale_assignments(team_id: str) -> Dict[str, Any]:
    """What the club's saved lineups, staff and depth chart name that it
    cannot use.

    ``lineups``: batters in the vs-LHP or vs-RHP lineup who are not on the
    active roster, once each, with ``sides`` (["LHP", "RHP"]). ``staff``:
    staff roles held by a pitcher who is not active. ``depth_chart``: players
    on the chart who have left the organisation (a minor leaguer listed as
    depth is a choice, not an error). Each entry is ``{player_id, name,
    position, note}``; ``note`` says where the player is now.
    """

    from api.routers.validation import load_players_map, load_team_levels

    tid = str(team_id or "").strip().upper()
    root = _data_dir()
    report: Dict[str, Any] = {"team_id": tid, "lineups": [], "staff": [], "depth_chart": []}
    if not (root / "rosters" / f"{tid}.csv").exists():
        return report
    levels = load_team_levels(tid)
    where = _Whereabouts(tid, levels, root)
    players = load_players_map()

    batters: Dict[str, Dict[str, Any]] = {}
    for vs in ("lhp", "rhp"):
        for pid, pos in _lineup_rows(tid, vs):
            pid = str(pid).strip()
            note = where.note(pid) if pid else ""
            if not note:
                continue
            entry = batters.setdefault(
                pid,
                {"player_id": pid, "name": _name(players, pid),
                 "position": str(pos).upper(), "note": note, "sides": []},
            )
            entry["sides"].append(vs.upper())
    report["lineups"] = list(batters.values())

    for pid, role in _staff_rows(root, tid):
        note = where.note(pid)
        if note:
            report["staff"].append(
                {"player_id": pid, "name": _name(players, pid), "position": role, "note": note}
            )

    try:
        from utils.depth_chart import has_depth_chart, load_depth_chart

        chart = load_depth_chart(tid) if has_depth_chart(tid) else {}
    except Exception:
        chart = {}
    gone: Dict[str, Dict[str, Any]] = {}
    for pos, ids in chart.items():
        for pid in ids or ():
            if pid and not where.in_org(pid) and pid not in gone:
                gone[pid] = {"player_id": pid, "name": _name(players, pid),
                             "position": str(pos).upper(), "note": where.note(pid)}
    report["depth_chart"] = list(gone.values())
    return report


def catcher_report(team_id: str) -> Dict[str, Any]:
    """``{healthy_active, others}``: healthy catchers on the active roster,
    and every other catcher in the organisation with where he is (an injured
    one on the active roster reads "injured")."""

    from api.routers.validation import load_players_map, load_team_levels
    from utils.roster_rules import is_catcher

    tid = str(team_id or "").strip().upper()
    levels = load_team_levels(tid)
    players = load_players_map()
    healthy = 0
    others: List[Dict[str, Any]] = []
    for level in ("act", "dl", "ir", "aaa", "low"):
        for pid in levels.get(level) or ():
            row = players.get(pid)
            if not row or not is_catcher(row):
                continue
            hurt = str(row.get("injured", "") or "").strip().lower() in {"1", "true", "yes"}
            if level == "act" and not hurt:
                healthy += 1
                continue
            note = "injured" if level == "act" else _LEVEL_NOTES[level]
            if hurt and level in ("aaa", "low"):
                note += ", injured"
            others.append({"player_id": pid, "name": _name(players, pid),
                           "position": str(row.get("primary_position") or "C").upper(),
                           "note": note})
    return {"team_id": tid, "healthy_active": healthy, "others": others}


def _who(entries: List[Mapping[str, Any]], limit: int = 4, *, role_first: bool = False) -> str:
    bits = []
    for e in entries[:limit]:
        if role_first:
            bits.append(f"{e['position']} {e['name']} ({e['note']})")
        else:
            bits.append(f"{e['name']} ({e['note']})")
    more = len(entries) - limit
    if more > 0:
        bits.append(f"{more} more")
    return ", ".join(bits)


def stale_assignment_notes(team_id: str) -> List[str]:
    """Readiness-board notes, one per kind of problem. Never raises."""

    try:
        report = stale_assignments(team_id)
    except Exception:
        _LOGGER.exception("lineup checks: could not read %s", team_id)
        return []
    notes: List[str] = []
    if report["lineups"]:
        notes.append(
            "Lineups name players not on the active roster (each game rebuilds "
            f"the lineup until it is reset): {_who(report['lineups'])}."
        )
    if report["staff"]:
        notes.append(
            "Pitching staff roles held by inactive pitchers: "
            f"{_who(report['staff'], role_first=True)}."
        )
    if report["depth_chart"]:
        notes.append(
            "Depth chart lists players who left the club: "
            f"{_who(report['depth_chart'])}."
        )
    return notes


def stale_assignments_text(team_id: str) -> str:
    """One sentence for the rollover notice, "" when nothing is stale."""

    try:
        report = stale_assignments(team_id)
    except Exception:
        _LOGGER.exception("lineup checks: could not read %s", team_id)
        return ""
    where = []
    if report["lineups"]:
        where.append("lineups")
    if report["staff"]:
        where.append("pitching staff")
    if not where:
        return ""
    return (
        f"Your {' and '.join(where)} still name players who are not on your "
        "active roster; reset them on the Lineup page before Opening Day."
    )
