"""League and team record book helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Dict, List

from playbalance.season_context import CAREER_DATA_DIR
from utils.player_loader import load_players_from_csv
from utils.team_loader import load_teams

__all__ = [
    "league_record_book",
    "player_record_entries",
    "team_record_book",
    "team_record_entries",
]


@dataclass(frozen=True)
class RecordDefinition:
    label: str
    stat_key: str
    scope: str
    category: str
    descending: bool = True
    compute: Callable[[Dict[str, Any]], float | None] | None = None


_PLAYER_RECORDS: List[RecordDefinition] = [
    RecordDefinition("Career Hits", "h", "career", "batting"),
    RecordDefinition("Career Home Runs", "hr", "career", "batting"),
    RecordDefinition("Career RBI", "rbi", "career", "batting"),
    RecordDefinition("Career Runs", "r", "career", "batting"),
    RecordDefinition("Career Stolen Bases", "sb", "career", "batting"),
    RecordDefinition("Career Doubles", "b2", "career", "batting"),
    RecordDefinition("Career Triples", "b3", "career", "batting"),
    RecordDefinition("Single Season Hits", "h", "season", "batting"),
    RecordDefinition("Single Season Home Runs", "hr", "season", "batting"),
    RecordDefinition("Single Season RBI", "rbi", "season", "batting"),
    RecordDefinition("Single Season Runs", "r", "season", "batting"),
    RecordDefinition("Single Season Stolen Bases", "sb", "season", "batting"),
    RecordDefinition("Career Wins", "w", "career", "pitching"),
    RecordDefinition("Career Strikeouts", "so", "career", "pitching"),
    RecordDefinition("Career Saves", "sv", "career", "pitching"),
    RecordDefinition("Career Innings", "outs", "career", "pitching"),
    RecordDefinition("Single Season Wins", "w", "season", "pitching"),
    RecordDefinition("Single Season Strikeouts", "so", "season", "pitching"),
    RecordDefinition("Single Season Saves", "sv", "season", "pitching"),
    RecordDefinition("Single Season Innings", "outs", "season", "pitching"),
]


def _run_diff(stats: Dict[str, Any]) -> float | None:
    runs = _coerce_number(stats.get("r"))
    allowed = _coerce_number(stats.get("ra"))
    if runs is None or allowed is None:
        return None
    return runs - allowed


_TEAM_RECORDS: List[RecordDefinition] = [
    RecordDefinition("Single Season Wins", "w", "season", "team"),
    RecordDefinition("Single Season Runs", "r", "season", "team"),
    RecordDefinition("Fewest Runs Allowed", "ra", "season", "team", descending=False),
    RecordDefinition("Best Run Differential", "run_diff", "season", "team", compute=_run_diff),
    RecordDefinition("Career Wins", "w", "career", "team"),
    RecordDefinition("Career Runs", "r", "career", "team"),
    RecordDefinition("Career Run Differential", "run_diff", "career", "team", compute=_run_diff),
]


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return dict(default)
    if not isinstance(data, dict):
        return dict(default)
    return data


def _coerce_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return float(value)
        except Exception:
            return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _format_ip_from_outs(outs: float | int) -> str:
    try:
        outs_int = int(round(float(outs)))
    except Exception:
        return "--"
    innings = outs_int // 3
    remainder = outs_int % 3
    return f"{innings}.{remainder}"


def _format_value(stat_key: str, value: float | None) -> str:
    if value is None:
        return "--"
    if stat_key == "outs":
        return _format_ip_from_outs(value)
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.3f}"


def _season_label(season_id: str | None) -> str:
    if not season_id:
        return ""
    token = str(season_id).strip()
    if not token:
        return ""
    try:
        return str(int(token.split("-")[-1]))
    except (ValueError, TypeError):
        return token


def _player_index() -> Dict[str, Dict[str, Any]]:
    try:
        players = load_players_from_csv("data/players.csv")
    except Exception:
        return {}
    index: Dict[str, Dict[str, Any]] = {}
    for player in players:
        pid = getattr(player, "player_id", "")
        name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip()
        index[pid] = {
            "name": name or pid,
            "is_pitcher": bool(getattr(player, "is_pitcher", False)),
        }
    return index


def _team_index() -> Dict[str, str]:
    try:
        teams = load_teams()
    except Exception:
        return {}
    index: Dict[str, str] = {}
    for team in teams:
        label = f"{getattr(team, 'city', '')} {getattr(team, 'name', '')}".strip()
        index[getattr(team, "team_id", "")] = label or getattr(team, "team_id", "")
    return index


def _load_career_players() -> Dict[str, Any]:
    return _read_json(
        CAREER_DATA_DIR / "career_players.json",
        {"players": {}},
    )


def _load_career_teams() -> Dict[str, Any]:
    return _read_json(
        CAREER_DATA_DIR / "career_teams.json",
        {"teams": {}},
    )


def _select_best(
    candidates: List[Dict[str, Any]],
    *,
    descending: bool,
) -> tuple[float, List[Dict[str, Any]]] | None:
    if not candidates:
        return None
    values = [c["value"] for c in candidates if c.get("value") is not None]
    if not values:
        return None
    best = max(values) if descending else min(values)
    tol = 1e-6
    holders = [c for c in candidates if c.get("value") is not None and abs(c["value"] - best) <= tol]
    return best, holders


def _build_player_records(
    players_map: Dict[str, Dict[str, Any]],
    index: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for definition in _PLAYER_RECORDS:
        candidates: List[Dict[str, Any]] = []
        for pid, entry in players_map.items():
            info = index.get(pid, {})
            is_pitcher = info.get("is_pitcher")
            if definition.category == "batting" and is_pitcher is True:
                continue
            if definition.category == "pitching" and is_pitcher is False:
                continue
            if definition.scope == "career":
                stats = entry.get("totals", {}) if isinstance(entry, dict) else {}
                value = _stat_value(definition, stats)
                if value is None or value <= 0:
                    continue
                candidates.append({"player_id": pid, "value": value, "season_id": None})
            else:
                seasons = entry.get("seasons", {}) if isinstance(entry, dict) else {}
                if not isinstance(seasons, dict):
                    continue
                for season_id, stats in seasons.items():
                    if not isinstance(stats, dict):
                        continue
                    value = _stat_value(definition, stats)
                    if value is None or value <= 0:
                        continue
                    candidates.append(
                        {
                            "player_id": pid,
                            "value": value,
                            "season_id": str(season_id),
                        }
                    )
        selected = _select_best(candidates, descending=definition.descending)
        if not selected:
            continue
        value, holders = selected
        record_entry = _record_entry_base(definition, value)
        record_entry["holders"] = [
            _player_holder(h, index)
            for h in holders
        ]
        records.append(record_entry)
    return records


def _build_team_records(
    teams_map: Dict[str, Dict[str, Any]],
    index: Dict[str, str],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for definition in _TEAM_RECORDS:
        candidates: List[Dict[str, Any]] = []
        for tid, entry in teams_map.items():
            if definition.scope == "career":
                stats = entry.get("totals", {}) if isinstance(entry, dict) else {}
                value = _stat_value(definition, stats)
                if value is None:
                    continue
                candidates.append({"team_id": tid, "value": value, "season_id": None})
            else:
                seasons = entry.get("seasons", {}) if isinstance(entry, dict) else {}
                if not isinstance(seasons, dict):
                    continue
                for season_id, stats in seasons.items():
                    if not isinstance(stats, dict):
                        continue
                    value = _stat_value(definition, stats)
                    if value is None:
                        continue
                    candidates.append(
                        {
                            "team_id": tid,
                            "value": value,
                            "season_id": str(season_id),
                        }
                    )
        selected = _select_best(candidates, descending=definition.descending)
        if not selected:
            continue
        value, holders = selected
        record_entry = _record_entry_base(definition, value)
        record_entry["holders"] = [
            _team_holder(h, index)
            for h in holders
        ]
        records.append(record_entry)
    return records


def _record_entry_base(definition: RecordDefinition, value: float) -> Dict[str, Any]:
    return {
        "label": definition.label,
        "stat_key": definition.stat_key,
        "scope": definition.scope,
        "category": definition.category,
        "descending": definition.descending,
        "value": value,
        "value_text": _format_value(definition.stat_key, value),
    }


def _stat_value(definition: RecordDefinition, stats: Dict[str, Any]) -> float | None:
    if definition.compute is not None:
        return definition.compute(stats)
    return _coerce_number(stats.get(definition.stat_key))


def _player_holder(holder: Dict[str, Any], index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    pid = str(holder.get("player_id") or "")
    info = index.get(pid, {})
    season_id = holder.get("season_id")
    return {
        "player_id": pid,
        "name": info.get("name") or pid,
        "season_id": season_id,
        "season_label": _season_label(season_id),
    }


def _team_holder(holder: Dict[str, Any], index: Dict[str, str]) -> Dict[str, Any]:
    tid = str(holder.get("team_id") or "")
    season_id = holder.get("season_id")
    return {
        "team_id": tid,
        "team_name": index.get(tid) or tid,
        "season_id": season_id,
        "season_label": _season_label(season_id),
    }


def league_record_book() -> Dict[str, List[Dict[str, Any]]]:
    players_doc = _load_career_players()
    teams_doc = _load_career_teams()
    players_map = players_doc.get("players", {}) if isinstance(players_doc, dict) else {}
    teams_map = teams_doc.get("teams", {}) if isinstance(teams_doc, dict) else {}
    if not isinstance(players_map, dict):
        players_map = {}
    if not isinstance(teams_map, dict):
        teams_map = {}

    player_index = _player_index()
    team_index = _team_index()

    batting = _build_player_records(players_map, player_index)
    pitching = [r for r in batting if r.get("category") == "pitching"]
    batting = [r for r in batting if r.get("category") == "batting"]
    teams = _build_team_records(teams_map, team_index)
    return {"batting": batting, "pitching": pitching, "team": teams}


def player_record_entries(player_id: str) -> List[Dict[str, Any]]:
    if not player_id:
        return []
    book = league_record_book()
    results: List[Dict[str, Any]] = []
    for section in book.values():
        for entry in section:
            for holder in entry.get("holders", []):
                if holder.get("player_id") == player_id:
                    record = dict(entry)
                    record["holder"] = dict(holder)
                    results.append(record)
    return results


def team_record_entries(team_id: str) -> List[Dict[str, Any]]:
    if not team_id:
        return []
    book = league_record_book()
    results: List[Dict[str, Any]] = []
    for section in book.values():
        for entry in section:
            for holder in entry.get("holders", []):
                if holder.get("team_id") == team_id:
                    record = dict(entry)
                    record["holder"] = dict(holder)
                    results.append(record)
    return results


def team_record_book(team_id: str) -> List[Dict[str, Any]]:
    if not team_id:
        return []
    teams_doc = _load_career_teams()
    teams_map = teams_doc.get("teams", {}) if isinstance(teams_doc, dict) else {}
    if not isinstance(teams_map, dict):
        return []
    entry = teams_map.get(team_id)
    if not isinstance(entry, dict):
        return []
    records: List[Dict[str, Any]] = []
    team_index = _team_index()
    team_name = team_index.get(team_id, team_id)
    for definition in _TEAM_RECORDS:
        if definition.scope == "career":
            stats = entry.get("totals", {}) if isinstance(entry, dict) else {}
            value = _stat_value(definition, stats)
            if value is None:
                continue
            record = _record_entry_base(definition, value)
            record["team_id"] = team_id
            record["team_name"] = team_name
            record["season_label"] = "Career"
            records.append(record)
            continue
        seasons = entry.get("seasons", {}) if isinstance(entry, dict) else {}
        if not isinstance(seasons, dict):
            continue
        candidates: List[Dict[str, Any]] = []
        for season_id, stats in seasons.items():
            if not isinstance(stats, dict):
                continue
            value = _stat_value(definition, stats)
            if value is None:
                continue
            candidates.append({"value": value, "season_id": str(season_id)})
        selected = _select_best(candidates, descending=definition.descending)
        if not selected:
            continue
        value, holders = selected
        season_id = holders[0].get("season_id") if holders else None
        record = _record_entry_base(definition, value)
        record["team_id"] = team_id
        record["team_name"] = team_name
        record["season_id"] = season_id
        record["season_label"] = _season_label(season_id) or "-"
        records.append(record)
    return records
