"""Track notable single-game events for league history and player profiles."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from playbalance.season_context import SeasonContext
from utils.path_utils import get_base_dir
from utils.sim_date import get_current_sim_date

__all__ = [
    "SPECIAL_EVENTS_PATH",
    "load_special_events",
    "load_player_special_events",
    "record_game_special_events",
    "record_special_events",
    "reset_special_events",
]

SPECIAL_EVENTS_PATH = get_base_dir() / "data" / "special_events.json"
_VERSION = 1


@dataclass(frozen=True)
class _SeasonInfo:
    season_id: str
    league_year: int | None


def _resolve_season_info() -> _SeasonInfo:
    try:
        ctx = SeasonContext.load()
        current = ctx.ensure_current_season()
        season_id = str(current.get("season_id") or "").strip() or "league"
        league_year = current.get("league_year")
        if league_year is not None:
            try:
                league_year = int(league_year)
            except (TypeError, ValueError):
                league_year = None
    except Exception:
        season_id = "league"
        league_year = None
    return _SeasonInfo(season_id=season_id, league_year=league_year)


def _load_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": _VERSION, "season_id": "", "events": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": _VERSION, "season_id": "", "events": []}
    if not isinstance(payload, dict):
        return {"version": _VERSION, "season_id": "", "events": []}
    payload.setdefault("version", _VERSION)
    payload.setdefault("season_id", "")
    payload.setdefault("events", [])
    if not isinstance(payload.get("events"), list):
        payload["events"] = []
    return payload


def _write_payload(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _format_ip(outs: int) -> str:
    innings = outs // 3
    remainder = outs % 3
    if remainder:
        return f"{innings}.{remainder}"
    return f"{innings}.0"


def _player_name(player: object | None, player_id: str) -> str:
    if player is None:
        return player_id
    first = str(getattr(player, "first_name", "") or "").strip()
    last = str(getattr(player, "last_name", "") or "").strip()
    name = f"{first} {last}".strip()
    return name or player_id


def _event_date(game_date: str | None) -> str:
    if game_date:
        return str(game_date)
    return str(get_current_sim_date() or "")


def record_special_events(
    events: Iterable[Dict[str, Any]],
    *,
    path: Path | None = None,
) -> None:
    event_list = [event for event in events if isinstance(event, dict)]
    if not event_list:
        return
    target = path or SPECIAL_EVENTS_PATH
    payload = _load_payload(target)
    info = _resolve_season_info()
    if not payload.get("season_id"):
        payload["season_id"] = info.season_id
    payload["version"] = _VERSION
    existing = payload.get("events", [])
    if not isinstance(existing, list):
        existing = []
    for event in event_list:
        event.setdefault("season_id", info.season_id)
        if info.league_year is not None:
            event.setdefault("league_year", info.league_year)
        if not event.get("date"):
            event["date"] = _event_date(None)
        existing.append(event)
    payload["events"] = existing
    _write_payload(target, payload)


def load_special_events(
    *,
    path: Path | None = None,
    season_id: str | None = None,
    team_id: str | None = None,
    player_id: str | None = None,
    limit: int | None = None,
) -> List[Dict[str, Any]]:
    payload = _load_payload(path or SPECIAL_EVENTS_PATH)
    events = payload.get("events", [])
    if not isinstance(events, list):
        return []
    filtered: List[Dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if season_id and str(event.get("season_id") or "") != season_id:
            continue
        if team_id and str(event.get("team_id") or "") != team_id:
            continue
        if player_id and str(event.get("player_id") or "") != player_id:
            continue
        filtered.append(dict(event))
    filtered.sort(key=lambda e: str(e.get("date") or ""), reverse=True)
    if limit is not None and limit >= 0:
        filtered = filtered[:limit]
    return filtered


def load_player_special_events(
    player_id: str,
    *,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    if not player_id:
        return []
    events = load_special_events(player_id=player_id)
    careers_dir = get_base_dir() / "data" / "careers"
    if careers_dir.exists():
        for path in sorted(careers_dir.glob("*/special_events.json")):
            events.extend(load_special_events(path=path, player_id=player_id))
    events.sort(key=lambda e: str(e.get("date") or ""), reverse=True)
    if limit is not None and limit >= 0:
        events = events[:limit]
    return events


def reset_special_events(*, path: Path | None = None) -> None:
    target = path or SPECIAL_EVENTS_PATH
    payload = {"version": _VERSION, "season_id": "", "events": []}
    _write_payload(target, payload)


def record_game_special_events(
    *,
    metadata: Dict[str, Any],
    home_id: str,
    away_id: str,
    players_lookup: Dict[str, object],
    game_date: str | None = None,
) -> List[Dict[str, Any]]:
    batting_lines = metadata.get("batting_lines", {}) or {}
    pitcher_lines = metadata.get("pitcher_lines", {}) or {}
    if not isinstance(batting_lines, dict) or not isinstance(pitcher_lines, dict):
        return []

    events: List[Dict[str, Any]] = []
    date_val = _event_date(game_date)

    def _emit(event: Dict[str, Any]) -> None:
        if "date" not in event:
            event["date"] = date_val
        events.append(event)

    def _offense_team(side: str) -> str:
        return home_id if side == "home" else away_id

    def _defense_team(side: str) -> str:
        return away_id if side == "home" else home_id

    for side in ("home", "away"):
        batting = batting_lines.get(side, [])
        pitching = pitcher_lines.get("away" if side == "home" else "home", [])
        if not isinstance(batting, list) or not isinstance(pitching, list):
            continue

        team_id = _offense_team(side)
        opponent_id = _defense_team(side)

        # Hitting feats
        for line in batting:
            if not isinstance(line, dict):
                continue
            pid = str(line.get("player_id") or "")
            if not pid:
                continue
            player = players_lookup.get(pid)
            name = _player_name(player, pid)
            h = _safe_int(line.get("h", 0))
            b1 = _safe_int(line.get("b1", line.get("1b", 0)))
            b2 = _safe_int(line.get("b2", line.get("2b", 0)))
            b3 = _safe_int(line.get("b3", line.get("3b", 0)))
            hr = _safe_int(line.get("hr", 0))
            rbi = _safe_int(line.get("rbi", 0))
            sb = _safe_int(line.get("sb", 0))
            if b1 and b2 and b3 and hr:
                _emit(
                    {
                        "type": "cycle",
                        "label": "Hit for the Cycle",
                        "category": "hitting",
                        "player_id": pid,
                        "player_name": name,
                        "team_id": team_id,
                        "opponent_id": opponent_id,
                    }
                )
            if hr >= 3:
                _emit(
                    {
                        "type": "multi_hr",
                        "label": f"{hr} HR Game",
                        "category": "hitting",
                        "player_id": pid,
                        "player_name": name,
                        "team_id": team_id,
                        "opponent_id": opponent_id,
                        "stat_key": "hr_game",
                        "value": hr,
                    }
                )
            if h >= 4:
                _emit(
                    {
                        "type": "multi_hit",
                        "label": f"{h} Hit Game",
                        "category": "hitting",
                        "player_id": pid,
                        "player_name": name,
                        "team_id": team_id,
                        "opponent_id": opponent_id,
                        "stat_key": "hits_game",
                        "value": h,
                    }
                )
            if rbi >= 5:
                _emit(
                    {
                        "type": "multi_rbi",
                        "label": f"{rbi} RBI Game",
                        "category": "hitting",
                        "player_id": pid,
                        "player_name": name,
                        "team_id": team_id,
                        "opponent_id": opponent_id,
                        "stat_key": "rbi_game",
                        "value": rbi,
                    }
                )
            if sb >= 3:
                _emit(
                    {
                        "type": "multi_sb",
                        "label": f"{sb} SB Game",
                        "category": "hitting",
                        "player_id": pid,
                        "player_name": name,
                        "team_id": team_id,
                        "opponent_id": opponent_id,
                        "stat_key": "sb_game",
                        "value": sb,
                    }
                )

        # Team-level no-hitter / perfect game checks
        total_hits = sum(_safe_int(line.get("h", 0)) for line in batting if isinstance(line, dict))
        if total_hits == 0 and pitching:
            total_bb = sum(_safe_int(line.get("bb", 0)) for line in batting if isinstance(line, dict))
            total_hbp = sum(_safe_int(line.get("hbp", 0)) for line in batting if isinstance(line, dict))
            total_roe = sum(_safe_int(line.get("roe", 0)) for line in batting if isinstance(line, dict))
            total_outs = sum(_safe_int(line.get("outs", 0)) for line in pitching if isinstance(line, dict))
            max_outs = 0
            primary = None
            for line in pitching:
                if not isinstance(line, dict):
                    continue
                outs = _safe_int(line.get("outs", 0))
                if outs > max_outs:
                    max_outs = outs
                    primary = line
            combined = True
            if primary and total_outs and max_outs >= total_outs:
                combined = False
            baserunners = total_bb + total_hbp + total_roe
            is_perfect = baserunners == 0

            def _pitcher_event(line: Dict[str, Any], combined_flag: bool) -> None:
                pid = str(line.get("player_id") or "")
                if not pid:
                    return
                player = players_lookup.get(pid)
                name = _player_name(player, pid)
                outs = _safe_int(line.get("outs", 0))
                if outs <= 0:
                    return
                so = _safe_int(line.get("so", 0))
                bb = _safe_int(line.get("bb", 0))
                hbp = _safe_int(line.get("hbp", 0))
                ip = _format_ip(outs)
                label = "Perfect Game" if is_perfect else "No-Hitter"
                event_type = "perfect_game" if is_perfect else "no_hitter"
                if combined_flag:
                    label = f"Combined {label}"
                    event_type = f"combined_{event_type}"
                detail = f"{label} vs {team_id} ({ip} IP, {so} K, {bb} BB, {hbp} HBP)"
                _emit(
                    {
                        "type": event_type,
                        "label": label,
                        "category": "pitching",
                        "player_id": pid,
                        "player_name": name,
                        "team_id": opponent_id,
                        "opponent_id": team_id,
                        "detail": detail,
                        "stat_key": "no_hitter" if not is_perfect else "perfect_game",
                        "value": 1,
                    }
                )

            if combined:
                for line in pitching:
                    if isinstance(line, dict):
                        _pitcher_event(line, True)
            elif primary:
                _pitcher_event(primary, False)

        # Pitching strikeout feats
        for line in pitching:
            if not isinstance(line, dict):
                continue
            pid = str(line.get("player_id") or "")
            if not pid:
                continue
            so = _safe_int(line.get("so", 0))
            if so < 10:
                continue
            player = players_lookup.get(pid)
            name = _player_name(player, pid)
            _emit(
                {
                    "type": "strikeouts",
                    "label": f"{so} Strikeouts",
                    "category": "pitching",
                    "player_id": pid,
                    "player_name": name,
                    "team_id": opponent_id,
                    "opponent_id": team_id,
                    "stat_key": "so_game",
                    "value": so,
                }
            )

    if events:
        record_special_events(events)
    return events
