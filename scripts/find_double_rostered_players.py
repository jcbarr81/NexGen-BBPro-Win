#!/usr/bin/env python3
"""List every player on more than one club in a league's files (READ-ONLY).

    python scripts/find_double_rostered_players.py <league data dir> [--json]

``<league data dir>`` is the folder holding ``rosters/``, ``contracts.json``,
``players.csv``, ``transactions.csv`` and ``users.txt`` (for a hosted league,
``<root>/leagues/<league>/data``). Nothing is written: every file is opened
for reading only, and no repair is made. Repairing a live league is the
owner's decision.

For each player on two (or more) clubs' roster files it prints his clubs and
levels, his contract, his injury, his transactions, and a proposed
resolution: keep him with the club that held him before the free-agent
signing that put him on the second club (an older build listed a player on
an injured list as a free agent, so another club could sign him -- the
signing is void), remove him from the other club, and what that does to the
other club's roster counts. When the transactions do not show such a
signing, the club named by his contract is kept.

It also lists, for information, players named on a club's pitching-staff
file while not on that club's roster (a staff file only labels roles), and
contracts that name a different club than the roster (trades in the web app
do not move the contract's club).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# The active-roster size (owner decision 8): 26.
ACTIVE_ROSTER_SIZE = 26
ORG_LIMIT = 50
_SIGNING_ACTIONS = {"sign", "fa_signing", "gm_finance_target_signing"}
_LEVEL_NAMES = {
    "ACT": "active roster",
    "AAA": "AAA",
    "LOW": "Low-A",
    "DL": "injured list",
    "DL15": "injured list (short)",
    "DL45": "60-day injured list",
    "IR": "60-day injured list",
}


def _read_rows(path: Path) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.reader(fh):
                if len(row) >= 2 and row[0].strip() and row[0].strip() != "player_id":
                    rows.append((row[0].strip(), row[1].strip().upper()))
    except OSError:
        pass
    return rows


def _rosters(data: Path) -> Dict[str, List[Tuple[str, str]]]:
    """``{team: [(pid, level), ...]}`` from every ``rosters/<TEAM>.csv``."""

    out: Dict[str, List[Tuple[str, str]]] = {}
    roster_dir = data / "rosters"
    if not roster_dir.is_dir():
        return out
    for path in sorted(roster_dir.glob("*.csv")):
        if path.stem.endswith("_pitching") or path.name.startswith("_"):
            continue
        out[path.stem] = _read_rows(path)
    return out


def _staff(data: Path) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for path in sorted((data / "rosters").glob("*_pitching.csv")):
        team = path.stem[: -len("_pitching")]
        ids: List[str] = []
        try:
            with path.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.reader(fh):
                    if row and row[0].strip():
                        ids.append(row[0].strip())
        except OSError:
            continue
        out[team] = ids
    return out


def _contracts(data: Path) -> Dict[str, Dict[str, Any]]:
    try:
        payload = json.loads((data / "contracts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    players = payload.get("players") if isinstance(payload, dict) else None
    return players if isinstance(players, dict) else {}


def _players(data: Path) -> Dict[str, Dict[str, str]]:
    try:
        with (data / "players.csv").open("r", encoding="utf-8", newline="") as fh:
            return {row.get("player_id", ""): row for row in csv.DictReader(fh)}
    except OSError:
        return {}


def _transactions(data: Path) -> List[Dict[str, str]]:
    try:
        with (data / "transactions.csv").open("r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def _owner_clubs(data: Path) -> Optional[set]:
    """Clubs with a human owner (users.txt), None when unreadable."""

    path = data / "users.txt"
    if not path.exists():
        return None
    owned = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4 and parts[3] and parts[2].lower() not in {"admin", "commissioner", "viewer"}:
                owned.add(parts[3].upper())
    except OSError:
        return None
    return owned


def _counts(rows: List[Tuple[str, str]]) -> Dict[str, int]:
    c = Counter(level for _, level in rows)
    org = c.get("ACT", 0) + c.get("AAA", 0) + c.get("LOW", 0)
    return {
        "ACT": c.get("ACT", 0),
        "AAA": c.get("AAA", 0),
        "LOW": c.get("LOW", 0),
        "IL": sum(v for k, v in c.items() if k in {"DL", "DL15", "DL45", "IR"}),
        "org": org,
    }


def _name(players: Dict[str, Dict[str, str]], pid: str) -> str:
    row = players.get(pid) or {}
    name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
    return name or pid


def _arrivals(txs: List[Dict[str, str]], pid: str) -> List[Dict[str, str]]:
    return [t for t in txs if t.get("player_id") == pid]


def _propose(
    pid: str,
    places: List[Tuple[str, str]],
    contract: Optional[Dict[str, Any]],
    history: List[Dict[str, str]],
) -> Tuple[Optional[str], str]:
    """``(club to keep, reason)``; club None when the files cannot tell."""

    clubs = [team for team, _ in places]
    # The club that signed him as a free agent while another club listed him.
    fa_signings = [
        t for t in history
        if t.get("action") in _SIGNING_ACTIONS
        and str(t.get("from_level", "")).upper() == "FA"
        and t.get("team_id") in clubs
    ]
    if fa_signings:
        last = fa_signings[-1]
        signer = last.get("team_id")
        others = [c for c in clubs if c != signer]
        later_arrivals = [
            t for t in history
            if t.get("team_id") in others
            and t.get("action") in (_SIGNING_ACTIONS | {"trade_in", "draft"})
            and (t.get("timestamp", "") > last.get("timestamp", ""))
        ]
        if len(others) == 1 and not later_arrivals:
            keep = others[0]
            reason = (
                f"{signer} signed him as a free agent on {last.get('season_date') or last.get('timestamp')} "
                f"while he was on {keep}'s roster -- the signing is void (an older build "
                f"listed injured-list players as free agents)."
            )
            if contract and str(contract.get("team_id", "")) == signer:
                reason += (
                    f" His contract in contracts.json is {signer}'s new one; {keep}'s "
                    "earlier terms are not in the league files (restore them from a copy "
                    "of contracts.json taken before that signing)."
                )
            return keep, reason
    team = str((contract or {}).get("team_id", "") or "")
    if team in clubs:
        return team, f"his contract (contracts.json) is with {team}."
    return None, "the files do not show which club holds him validly: decide by hand."


def find(data: Path) -> Dict[str, Any]:
    rosters = _rosters(data)
    staff = _staff(data)
    contracts = _contracts(data)
    players = _players(data)
    txs = _transactions(data)
    owners = _owner_clubs(data)

    places: Dict[str, List[Tuple[str, str]]] = {}
    for team, rows in rosters.items():
        for pid, level in rows:
            places.setdefault(pid, []).append((team, level))

    doubles: List[Dict[str, Any]] = []
    for pid in sorted(places):
        memberships = places[pid]
        if len({team for team, _ in memberships}) < 2:
            continue
        contract = contracts.get(pid)
        history = _arrivals(txs, pid)
        keep, reason = _propose(pid, memberships, contract, history)
        removals = []
        for team, level in memberships:
            if team == keep:
                continue
            before = _counts(rosters.get(team, []))
            after_rows = [r for r in rosters.get(team, []) if r[0] != pid]
            after = _counts(after_rows)
            note = ""
            if level == "ACT" and after["ACT"] < ACTIVE_ROSTER_SIZE:
                owner = owners is not None and team.upper() in owners
                note = (
                    f"active roster {before['ACT']} -> {after['ACT']} of {ACTIVE_ROSTER_SIZE}: "
                    + ("an owner's club -- the owner calls someone up."
                       if owner else "a CPU club -- filled before its next game day.")
                )
            removals.append({
                "team_id": team,
                "level": level,
                "owner_club": bool(owners is not None and team.upper() in owners),
                "before": before,
                "after": after,
                "note": note,
            })
        row = players.get(pid) or {}
        doubles.append({
            "player_id": pid,
            "name": _name(players, pid),
            "clubs": [
                {
                    "team_id": team,
                    "level": level,
                    "level_name": _LEVEL_NAMES.get(level, level),
                    "owner_club": bool(owners is not None and team.upper() in owners),
                    "on_staff_file": pid in staff.get(team, []),
                }
                for team, level in memberships
            ],
            "contract": contract,
            "injury": {
                "injured": row.get("injured", ""),
                "description": row.get("injury_description", ""),
                "list": row.get("injury_list", ""),
                "return_date": row.get("return_date", ""),
            },
            "transactions": history[-10:],
            "proposal": {"keep_with": keep, "reason": reason, "remove_from": removals},
        })

    stray_staff = []
    for team, ids in staff.items():
        listed = {pid for pid, _ in rosters.get(team, [])}
        for pid in ids:
            if pid not in listed:
                stray_staff.append({
                    "player_id": pid,
                    "name": _name(players, pid),
                    "staff_file_of": team,
                    "roster_clubs": places.get(pid, []),
                })

    contract_elsewhere = []
    for pid, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            continue
        team = str(contract.get("team_id", "") or "")
        clubs = {t for t, _ in places.get(pid, [])}
        if team and clubs and team not in clubs:
            contract_elsewhere.append({
                "player_id": pid,
                "name": _name(players, pid),
                "contract_team": team,
                "roster_clubs": sorted(clubs),
                "last_transaction": (_arrivals(txs, pid) or [{}])[-1].get("action", ""),
            })

    return {
        "data_dir": str(data),
        "double_rostered": doubles,
        "staff_file_without_roster": stray_staff,
        "contract_club_differs": contract_elsewhere,
    }


def _print(report: Dict[str, Any]) -> None:
    doubles = report["double_rostered"]
    print(f"League files: {report['data_dir']}")
    print(f"Players on more than one club: {len(doubles)}")
    for item in doubles:
        clubs = ", ".join(
            f"{c['team_id']} {c['level']}" + (" (owner)" if c["owner_club"] else "")
            for c in item["clubs"]
        )
        print()
        print(f"{item['player_id']} {item['name']}: {clubs}")
        ct = item["contract"] or {}
        if ct:
            print(
                f"  contract: {ct.get('team_id')} ${int(ct.get('annual_salary', 0) or 0):,}/yr, "
                f"{ct.get('years_left')} yr left"
            )
        else:
            print("  contract: none")
        inj = item["injury"]
        if str(inj.get("injured", "")).lower() in {"1", "true"}:
            print(f"  injury: {inj.get('description')} ({inj.get('list')}, back {inj.get('return_date') or '?'})")
        for t in item["transactions"]:
            print(
                f"  tx {t.get('season_date') or t.get('timestamp')}: {t.get('team_id')} "
                f"{t.get('action')} {t.get('from_level')}->{t.get('to_level')} {t.get('details', '')}"
            )
        prop = item["proposal"]
        if prop["keep_with"]:
            print(f"  PROPOSED: keep with {prop['keep_with']} -- {prop['reason']}")
        else:
            print(f"  PROPOSED: {prop['reason']}")
        for rem in prop["remove_from"]:
            b, a = rem["before"], rem["after"]
            print(
                f"    remove from {rem['team_id']} {rem['level']}: ACT {b['ACT']}->{a['ACT']}, "
                f"AAA {b['AAA']}->{a['AAA']}, LOW {b['LOW']}->{a['LOW']}, IL {b['IL']}->{a['IL']}, "
                f"organisation {b['org']}->{a['org']} of {ORG_LIMIT}. {rem['note']}"
            )
    stray = report["staff_file_without_roster"]
    if stray:
        print()
        print(f"Named on a club's pitching-staff file but not on its roster: {len(stray)}")
        for s in stray:
            where = ", ".join(f"{t} {lv}" for t, lv in s["roster_clubs"]) or "no roster"
            print(f"  {s['player_id']} {s['name']}: staff file of {s['staff_file_of']}; roster: {where}")
    diff = report["contract_club_differs"]
    if diff:
        print()
        print(f"Contract names a different club than the roster: {len(diff)}"
              " (trades do not move the contract's club)")
        for d in diff:
            print(f"  {d['player_id']} {d['name']}: contract {d['contract_team']}, "
                  f"roster {', '.join(d['roster_clubs'])} (last tx: {d['last_transaction'] or '-'})")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", type=Path, help="the league's data folder")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    if not (args.data_dir / "rosters").is_dir():
        print(f"no rosters/ folder under {args.data_dir}", file=sys.stderr)
        return 2
    report = find(args.data_dir)
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        _print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
