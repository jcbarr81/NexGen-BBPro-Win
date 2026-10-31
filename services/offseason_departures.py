"""Who left each club at the rollover (8.1.3).

The rollover's contract step turns every expiring deal into a free agent and
its retirement step retires the players past it; each posted one news line
per player among a hundred or more, so an owner had to dig for his own. This
records, per club, who retired and whose contract expired (and was not
re-signed through a qualifying offer), so the owner's rollover notice and the
Roster page can name them.

The record is ``offseason_departures.json`` in the league's data dir:
``{"year": <new league year>, "teams": {TEAM: {"retired": [...],
"contract_expired": [...]}}}``, each entry ``{player_id, name, position,
age}``. The next rollover replaces it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

_LOGGER = logging.getLogger(__name__)

FILENAME = "offseason_departures.json"

__all__ = [
    "FILENAME",
    "expiring_contract_clubs",
    "record_departures",
    "load_departures",
    "departures_text",
]


def expiring_contract_clubs(*, data_dir: Path | str) -> Dict[str, str]:
    """``{player_id: club}`` for every contract the rollover is about to
    expire (``years_left`` 1 or less). Read BEFORE the contract step, which
    deletes them; an exercised option keeps the player, and the caller only
    counts the ids the step reports as expired."""

    from services.contracts_service import load_contracts_payload

    payload = load_contracts_payload(data_dir=data_dir)
    out: Dict[str, str] = {}
    for pid, raw in (payload.get("players") or {}).items():
        if not isinstance(raw, Mapping):
            continue
        try:
            years = int(raw.get("years_left", 1) or 1)
        except (TypeError, ValueError):
            years = 1
        team = str(raw.get("team_id") or "").strip().upper()
        if years <= 1 and team:
            out[str(pid)] = team
    return out


def _player_rows(path: Path) -> Dict[str, Dict[str, str]]:
    """players.csv rows by id: only names, position and birthdate are read,
    so a plain read (no ratings, no loader cache) is enough."""

    import csv

    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return {str(r.get("player_id") or ""): r for r in csv.DictReader(fh)}
    except Exception:
        return {}


def _entry(pid: str, row: Optional[Mapping[str, str]], *, age: Optional[int] = None) -> Dict[str, Any]:
    row = row or {}
    first = str(row.get("first_name") or "")
    last = str(row.get("last_name") or "")
    if age is None and row.get("birthdate"):
        try:
            from playbalance.aging import calculate_age

            age = calculate_age(str(row.get("birthdate")))
        except Exception:
            age = None
    return {
        "player_id": pid,
        "name": f"{first} {last}".strip() or pid,
        "position": str(row.get("primary_position") or ""),
        "age": age,
    }


def record_departures(
    year: Optional[int],
    *,
    data_dir: Path | str,
    expiring: Mapping[str, str],
    expired_ids: Iterable[str],
    retirees: Iterable[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """Write who left each club and return the record.

    ``expiring`` is :func:`expiring_contract_clubs` from before the contract
    step, ``expired_ids`` the ids it expired, ``retirees`` the retirement
    step's entries (``team_id``, names, ``primary_position``, ``age``). A
    player whose club re-signed him since (an accepted qualifying offer puts
    his contract back) did not leave; a retiree is listed as retired only.
    """

    from services.contracts_service import load_contracts_payload

    root = Path(data_dir)
    rows = _player_rows(root / "players.csv")
    current = load_contracts_payload(data_dir=root).get("players") or {}
    teams: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    def _bucket(team: str) -> Dict[str, List[Dict[str, Any]]]:
        return teams.setdefault(team, {"retired": [], "contract_expired": []})

    retired_ids = set()
    for item in retirees or ():
        pid = str(item.get("player_id") or "").strip()
        # 8.6.5: a player whose contract ran out at this rollover can retire
        # as a free agent; he is listed as his old club's retiree.
        team = str(item.get("team_id") or expiring.get(pid, "") or "").strip().upper()
        if not pid or not team:
            continue
        retired_ids.add(pid)
        entry = _entry(pid, rows.get(pid), age=item.get("age"))
        name = f"{item.get('first_name', '')} {item.get('last_name', '')}".strip()
        if name:
            entry["name"] = name
        entry["position"] = str(item.get("primary_position") or entry["position"])
        _bucket(team)["retired"].append(entry)
    for raw in expired_ids or ():
        pid = str(raw or "").strip()
        team = expiring.get(pid, "")
        if not pid or not team or pid in retired_ids:
            continue
        again = current.get(pid)
        if isinstance(again, Mapping) and str(again.get("team_id") or "").strip().upper() == team:
            continue  # re-signed (accepted his club's qualifying offer)
        _bucket(team)["contract_expired"].append(_entry(pid, rows.get(pid)))
    for bucket in teams.values():
        for key in bucket:
            bucket[key].sort(key=lambda e: e["name"])
    record = {"year": year, "teams": teams}
    (root / FILENAME).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def load_departures(team_id: str, *, data_dir: Path | str | None = None) -> Dict[str, Any]:
    """``{"year", "retired": [...], "contract_expired": [...]}`` for one club
    (empty lists when there is no record or the club lost nobody)."""

    if data_dir is None:
        from utils.path_utils import get_data_dir

        data_dir = get_data_dir()
    path = Path(data_dir) / FILENAME
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        record = {}
    team = (record.get("teams") or {}).get(str(team_id or "").strip().upper()) or {}
    return {
        "year": record.get("year"),
        "retired": list(team.get("retired") or []),
        "contract_expired": list(team.get("contract_expired") or []),
    }


def departures_text(departures: Mapping[str, Any]) -> str:
    """"Retired: Ed Lovingood (P), Luis Delgado (2B). Contract expired (now
    free agents): Carlo Bartoli (1B)." Empty when nobody left."""

    def _names(items: Iterable[Mapping[str, Any]]) -> str:
        out = []
        for item in items:
            pos = str(item.get("position") or "").strip()
            out.append(f"{item.get('name')} ({pos})" if pos else str(item.get("name")))
        return ", ".join(out)

    parts = []
    retired = list(departures.get("retired") or [])
    expired = list(departures.get("contract_expired") or [])
    if retired:
        parts.append(f"Retired: {_names(retired)}.")
    if expired:
        parts.append(f"Contract expired (now free agents): {_names(expired)}.")
    return " ".join(parts)
