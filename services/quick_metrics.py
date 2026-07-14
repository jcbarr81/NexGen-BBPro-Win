from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from utils.path_utils import get_base_dir, get_data_dir
from utils.pitcher_recovery import PitcherRecoveryTracker
from utils.pitcher_role import get_role
from utils.sim_date import get_current_sim_date
from utils.standings_utils import default_record
# Cached read-only variant (S1-05) — metrics only aggregate, never mutate.
from utils.stats_persistence import load_stats_cached as _load_season_stats
from services.standings_repository import load_standings
try:
    from playbalance.config import load_config as _load_playbalance_config
except Exception:  # pragma: no cover - optional dependency in some test harnesses
    _load_playbalance_config = None  # type: ignore

DATE_FMT = "%Y-%m-%d"


def _resolve_data_dir(base_dir: Path | None) -> Path:
    if base_dir is None:
        return get_data_dir()
    base = Path(base_dir)
    try:
        if base.resolve() == get_base_dir().resolve():
            return get_data_dir()
    except Exception:
        pass
    if (base / "rosters").exists() and not (base / "data").exists():
        return base
    return base / "data"


@dataclass
class _ScheduleEntry:
    date: str
    home: str
    away: str
    result: str | None
    played: bool

    def opponent_for(self, team_id: str) -> str | None:
        if self.home == team_id:
            return self.away
        if self.away == team_id:
            return self.home
        return None

    def is_home_for(self, team_id: str) -> bool:
        return self.home == team_id


def gather_owner_quick_metrics(
    team_id: str,
    *,
    base_path: Path | None = None,
    roster: Any | None = None,
    players: Mapping[str, Any] | None = None,
    window: int = 12,
) -> Dict[str, Any]:
    """Collect lightweight metrics plus bullpen/matchup insights for owners."""

    base_dir = get_base_dir() if base_path is None else Path(base_path)
    data_dir = _resolve_data_dir(base_dir)

    standings_normalized = load_standings(base_path=data_dir)
    team_standings = standings_normalized.get(team_id, {})

    schedule_path = data_dir / "schedule.csv"
    schedule_entries = _load_schedule(schedule_path)
    team_schedule = [entry for entry in schedule_entries if entry.opponent_for(team_id)]

    today = _current_date()
    next_game = _find_next_game(team_schedule, today)
    next_opponent, next_date = _describe_next_game(next_game, team_id)

    last_game_played = _find_last_game(team_schedule)
    trend_data = _collect_trend_data(
        team_id, base_dir, team_schedule, standings_normalized, window=window
    )
    performers = _collect_recent_performers(
        team_id, base_dir, roster, players, window=7, limit=3
    )
    division_standings = _collect_division_standings(
        team_id, base_dir, standings_normalized
    )

    injuries = _count_injuries(roster)
    probable_sp = _probable_starter_for_team(roster, players)

    bullpen = _compute_bullpen_readiness(team_id, base_dir, roster, players, today)
    if probable_sp and bullpen.get("probable_starter") in {None, "--"}:
        bullpen["probable_starter"] = probable_sp
    matchup = _build_matchup_scout(
        team_id,
        next_game,
        standings_normalized,
        bullpen.get("probable_starter"),
    )

    metrics = {
        "record": _format_record(team_standings),
        "run_diff": _format_run_diff(team_standings),
        "next_opponent": next_opponent,
        "next_date": next_date,
        "streak": _format_streak(team_standings),
        "last10": _format_last10(team_standings),
        "injuries": injuries,
        "prob_sp": probable_sp,
        "bullpen": bullpen,
        "matchup": matchup,
        "trends": trend_data,
        "performers": performers,
        "division_standings": division_standings,
        "last_game": last_game_played,
    }

    metrics["calibration"] = _calibration_summary(base_dir)
    metrics["usage_calibration"] = _usage_calibration_summary(base_dir)

    (
        batting_leaders,
        pitching_leaders,
        leader_meta,
    ) = _collect_team_leaders(
        base_dir, roster, players
    )
    metrics["batting_leaders"] = batting_leaders
    metrics["pitching_leaders"] = pitching_leaders
    metrics["leader_meta"] = leader_meta
    return metrics


# ---------------------------------------------------------------------------
# Standings helpers


def _format_record(standing: Mapping[str, Any]) -> str:
    if not standing:
        return "--"
    try:
        wins = int(standing.get("wins", standing.get("w", 0)) or 0)
        losses = int(standing.get("losses", standing.get("l", 0)) or 0)
        return f"{wins}-{losses}"
    except Exception:
        return "--"


def _format_run_diff(standing: Mapping[str, Any]) -> str:
    if not standing:
        return "--"
    try:
        runs_for = int(standing.get("runs_for", standing.get("r", 0)) or 0)
        runs_against = int(standing.get("runs_against", standing.get("ra", 0)) or 0)
        diff = runs_for - runs_against
        return f"{diff:+d}"
    except Exception:
        return "--"


def _format_streak(standing: Mapping[str, Any]) -> str:
    if not standing:
        return "--"
    streak = standing.get("streak", {})
    try:
        result = str(streak.get("result", "")).upper()
        length = int(streak.get("length", 0) or 0)
        if result in {"W", "L"} and length > 0:
            return f"{result}{length}"
    except Exception:
        pass
    return "--"


def _format_last10(standing: Mapping[str, Any]) -> str:
    if not standing:
        return "--"
    raw = standing.get("last10")
    if isinstance(raw, Sequence):
        wins = sum(1 for item in raw if str(item).upper().startswith("W"))
        losses = sum(1 for item in raw if str(item).upper().startswith("L"))
        if wins or losses:
            return f"{wins}-{losses}"
    return "--"


# ---------------------------------------------------------------------------
# Schedule loading


def _load_schedule(path: Path) -> List[_ScheduleEntry]:
    """Parse the schedule into entries, mtime-cached (S1-05).

    The dashboard calls this from three endpoints per page load; entries are
    frozen dataclass rows read-only downstream, so sharing is safe.
    """
    from utils.file_cache import cached_read

    return cached_read(
        f"quick_metrics_schedule|{path}",
        (path,),
        lambda: _parse_schedule(path),
    )


def _parse_schedule(path: Path) -> List[_ScheduleEntry]:
    if not path.exists():
        return []
    entries: List[_ScheduleEntry] = []
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                date_token = str(row.get("date") or "").strip()
                home = str(row.get("home") or "").strip()
                away = str(row.get("away") or "").strip()
                if not (date_token and home and away):
                    continue
                result = str(row.get("result") or "").strip() or None
                played_flag = str(row.get("played") or "").strip()
                played = played_flag == "1" or bool(result)
                entries.append(
                    _ScheduleEntry(
                        date=date_token,
                        home=home,
                        away=away,
                        result=result,
                        played=played,
                    )
                )
    except OSError:
        return []
    return entries


def _find_next_game(
    schedule: Sequence[_ScheduleEntry], today: date
) -> Optional[_ScheduleEntry]:
    for entry in schedule:
        if entry.played:
            continue
        entry_date = _parse_date(entry.date)
        if entry_date >= today:
            return entry
    # Fall back to first future game even if earlier dates missing
    for entry in schedule:
        if not entry.played:
            return entry
    return None


def _find_last_game(
    schedule: Sequence[_ScheduleEntry],
) -> Optional[Dict[str, Any]]:
    for entry in reversed(schedule):
        if entry.played:
            return {
                "date": entry.date,
                "home": entry.home,
                "away": entry.away,
                "result": entry.result,
            }
    return None


def _describe_next_game(
    next_game: Optional[_ScheduleEntry], team_id: str
) -> Tuple[str, str]:
    if next_game is None:
        return "--", "--"
    opponent = next_game.opponent_for(team_id) or "--"
    prefix = "vs " if next_game.is_home_for(team_id) else "at "
    return prefix + opponent, next_game.date


# ---------------------------------------------------------------------------
# Injuries and probable starters


def _count_injuries(roster: Any | None) -> int:
    if roster is None:
        return 0
    try:
        disabled = len(getattr(roster, "dl", []) or [])
        injured = len(getattr(roster, "ir", []) or [])
        return int(disabled + injured)
    except Exception:
        return 0


def _probable_starter_for_team(
    roster: Any | None,
    players: Mapping[str, Any] | None,
) -> str:
    if roster is None or not players:
        return "--"
    try:
        act_ids = set(getattr(roster, "act", []) or [])
        starters = []
        for pid in act_ids:
            player = players.get(pid)
            if player is None:
                continue
            role = getattr(player, "role", None) or get_role(player)
            if role == "SP":
                endurance = int(getattr(player, "endurance", 0) or 0)
                starters.append((endurance, player))
        if starters:
            starters.sort(key=lambda item: item[0], reverse=True)
            candidate = starters[0][1]
            return _format_player_name(candidate)
    except Exception:
        pass
    return "--"


# ---------------------------------------------------------------------------
# Bullpen readiness


def _compute_bullpen_readiness(
    team_id: str,
    base_dir: Path,
    roster: Any | None,
    players: Mapping[str, Any] | None,
    today: date,
) -> Dict[str, Any]:
    result = {
        "ready": 0,
        "limited": 0,
        "rest": 0,
        "total": 0,
        "avg_available_pct": None,
        "detail": [],
        "headline": "--",
        "probable_starter": "--",
    }
    if roster is None or not players:
        return result

    try:
        data_dir = _resolve_data_dir(base_dir)
        players_file = data_dir / "players.csv"
        roster_dir = data_dir / "rosters"
        tracker = PitcherRecoveryTracker.instance()
        tracker.ensure_team(
            team_id,
            players_file,
            roster_dir,
        )
        status_map = tracker.bullpen_game_status(
            team_id, today.strftime(DATE_FMT), players_file, roster_dir
        )
        entry = tracker.data.get("teams", {}).get(team_id, {})
        statuses = entry.get("pitchers", {}) or {}

        bullpen_ids = [
            pid
            for pid in getattr(roster, "act", []) or []
            if _is_bullpen_pitcher(players.get(pid))
        ]
        result["total"] = len(bullpen_ids)
        available_pcts: list[float] = []

        for pid in bullpen_ids:
            player = players.get(pid)
            usage = status_map.get(pid, {}) if isinstance(status_map, Mapping) else {}
            status = statuses.get(pid, {})
            available_on = _coerce_date(usage.get("available_on")) or _coerce_date(
                status.get("available_on")
            )
            last_used = status.get("last_used") or None
            last_pitches = int(
                usage.get("last_pitches", status.get("last_pitches", 0)) or 0
            )
            available_pct = _safe_float(usage.get("available_pct"))
            if available_pct is None:
                max_pitches = _safe_float(status.get("max_pitches")) or 0.0
                available_pitches = _safe_float(status.get("available_pitches"))
                if max_pitches > 0 and available_pitches is not None:
                    available_pct = available_pitches / max_pitches
                else:
                    available_pct = 1.0
            available_pct = max(0.0, min(1.0, float(available_pct)))
            days = (available_on - today).days if available_on else 0
            if days <= 0:
                bucket = "ready"
                label = "Ready"
            elif days == 1:
                bucket = "limited"
                label = "Limited"
            else:
                bucket = "rest"
                label = f"Rest {days}d"
            result[bucket] = int(result[bucket]) + 1
            available_pcts.append(available_pct)
            result["detail"].append(
                {
                    "player_id": pid,
                    "name": _format_player_name(player),
                    "status": label,
                    "days": days if days > 0 else 0,
                    "last_used": last_used,
                    "last_pitches": last_pitches,
                    "available_pct": round(available_pct, 3),
                }
            )

        if result["total"]:
            avg_available = (
                sum(available_pcts) / len(available_pcts) if available_pcts else 0.0
            )
            result["avg_available_pct"] = round(avg_available, 3)
            result["headline"] = (
                f"{result['ready']} ready / "
                f"{result['limited']} limited / "
                f"{result['rest']} resting"
                f" | Avg budget {avg_available:.0%}"
            )
    except Exception:
        pass

    return result


def _is_bullpen_pitcher(player: Any | None) -> bool:
    if player is None:
        return False
    role = getattr(player, "role", None) or get_role(player)
    if role == "SP":
        return False
    is_pitcher = bool(getattr(player, "is_pitcher", False))
    primary = str(getattr(player, "primary_position", "")).upper()
    return is_pitcher or primary in {"P", "RP", "CL"}


# ---------------------------------------------------------------------------
# Matchup scouting


def _build_matchup_scout(
    team_id: str,
    next_game: Optional[_ScheduleEntry],
    standings: Mapping[str, Mapping[str, Any]],
    probable_starter: str | None,
) -> Dict[str, Any]:
    if next_game is None:
        return {
            "opponent": "--",
            "venue": "--",
            "record": "--",
            "run_diff": "--",
            "streak": "--",
            "note": "No games remaining on the schedule.",
            "opponent_probable": "--",
            "team_probable": probable_starter or "--",
        }
    opponent = next_game.opponent_for(team_id) or "--"
    entry = standings.get(opponent, {})
    venue = "Home" if next_game.is_home_for(team_id) else "Road"
    return {
        "opponent": opponent,
        "venue": venue,
        "record": _format_record(entry),
        "run_diff": _format_run_diff(entry),
        "streak": _format_streak(entry),
        "note": _build_matchup_note(entry),
        "opponent_probable": "--",
        "team_probable": probable_starter or "--",
        "date": next_game.date,
    }


def _build_matchup_note(standing: Mapping[str, Any]) -> str:
    try:
        runs_for = int(standing.get("runs_for", standing.get("r", 0)) or 0)
        runs_against = int(standing.get("runs_against", standing.get("ra", 0)) or 0)
        games = int(standing.get("games_played", standing.get("g", 0)) or 0)
        if games <= 0:
            return "Limited opponent data."
        rpg = runs_for / games
        rapg = runs_against / games
        diff = rpg - rapg
        if diff >= 0.75:
            return "High-powered offense; expect a slugfest."
        if diff <= -0.5:
            return "Run prevention club; prioritize contact hitters."
        if rapg <= 3.5:
            return "Opponent bullpen trending strong; manufacture runs."
        return "Balanced opponent; leverage platoon advantages."
    except Exception:
        return "Opponent analytics unavailable."


# ---------------------------------------------------------------------------
# Trend data


def _collect_trend_data(
    team_id: str,
    base_dir: Path,
    schedule: Sequence[_ScheduleEntry],
    standings: Mapping[str, Mapping[str, Any]],
    *,
    window: int,
) -> Dict[str, Any]:
    history_dir = _resolve_data_dir(base_dir) / "season_history"
    snapshots = sorted(history_dir.glob("*.json"))
    trend_points = []
    for path in snapshots[-max(window, 4) :]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        team_entry = payload.get("teams", {}).get(team_id)
        if not team_entry:
            continue
        games = int(team_entry.get("g", 0) or 0)
        wins = int(team_entry.get("w", 0) or 0)
        runs = float(team_entry.get("r", 0) or 0.0)
        runs_allowed = float(team_entry.get("ra", 0) or 0.0)
        rpg = runs / games if games else 0.0
        rapg = runs_allowed / games if games else 0.0
        win_pct = wins / games if games else 0.0
        trend_points.append(
            {
                "date": path.stem,
                "runs_per_game": round(rpg, 2),
                "runs_allowed_per_game": round(rapg, 2),
                "win_pct": round(win_pct, 3),
            }
        )
    if not trend_points:
        return {"series": [], "dates": []}
    dates = [p["date"] for p in trend_points]
    return {
        "dates": dates,
        "series": {
            "runs_per_game": [p["runs_per_game"] for p in trend_points],
            "runs_allowed_per_game": [
                p["runs_allowed_per_game"] for p in trend_points
            ],
            "win_pct": [p["win_pct"] for p in trend_points],
        },
    }


# ---------------------------------------------------------------------------
# Recent performers and division standings


def _team_player_ids(roster: Any | None) -> list[str]:
    if roster is None:
        return []
    candidate_ids: list[str] = []
    seen: set[str] = set()
    for attr in ("act", "dl", "ir"):
        try:
            ids = getattr(roster, attr, []) or []
        except Exception:
            ids = []
        for pid in ids:
            if not pid:
                continue
            pid_str = str(pid)
            if pid_str in seen:
                continue
            candidate_ids.append(pid_str)
            seen.add(pid_str)
    return candidate_ids


def _load_recent_snapshots(base_dir: Path, *, window: int) -> list[Mapping[str, Any]]:
    history_dir = _resolve_data_dir(base_dir) / "season_history"
    snapshots = sorted(history_dir.glob("*.json")) if history_dir.exists() else []
    entries: list[Mapping[str, Any]] = []
    for path in snapshots[-max(window, 2) :]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if "date" not in payload:
            payload["date"] = path.stem
        entries.append(payload)
    if entries:
        return entries

    try:
        stats_payload = _load_season_stats(_resolve_data_dir(base_dir) / "season_stats.json")
    except Exception:
        return []
    history = stats_payload.get("history", [])
    if not isinstance(history, list):
        return []
    entries = [entry for entry in history if isinstance(entry, Mapping)]
    entries.sort(key=lambda entry: str(entry.get("date", "")))
    return entries[-max(window, 2) :]


def _stat_delta(
    new_stats: Mapping[str, Any],
    old_stats: Mapping[str, Any],
    keys: Sequence[str],
) -> float:
    new_val = _safe_float(_first_value(new_stats, keys)) or 0.0
    old_val = _safe_float(_first_value(old_stats, keys)) or 0.0
    delta = new_val - old_val
    return delta if delta > 0 else 0.0


def _ip_value(stats: Mapping[str, Any]) -> float:
    ip_val = _safe_float(_first_value(stats, ("ip", "IP")))
    if ip_val is not None:
        return ip_val
    outs = _safe_float(_first_value(stats, ("outs", "OUTS")))
    if outs is not None:
        return outs / 3.0
    return 0.0


def _ip_delta(new_stats: Mapping[str, Any], old_stats: Mapping[str, Any]) -> float:
    delta = _ip_value(new_stats) - _ip_value(old_stats)
    return delta if delta > 0 else 0.0


def _collect_recent_performers(
    team_id: str,
    base_dir: Path,
    roster: Any | None,
    players: Mapping[str, Any] | None,
    *,
    window: int,
    limit: int,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "window": window,
        "hitters": {"hot": [], "cold": []},
        "pitchers": {"hot": [], "cold": []},
    }
    if roster is None or not players:
        result["note"] = "Roster data unavailable."
        return result

    snapshots = _load_recent_snapshots(base_dir, window=window)
    if len(snapshots) < 2:
        snapshots = []

    start_players: Mapping[str, Any] = {}
    end_players: Mapping[str, Any] = {}
    if snapshots:
        start_players = snapshots[0].get("players", {}) or {}
        end_players = snapshots[-1].get("players", {}) or {}
        if not isinstance(start_players, Mapping) or not isinstance(end_players, Mapping):
            start_players = {}
            end_players = {}

    start_date = ""
    end_date = ""
    if snapshots:
        start_date = str(snapshots[0].get("date") or "")
        end_date = str(snapshots[-1].get("date") or "")
        if start_date and end_date:
            result["range"] = {"start": start_date, "end": end_date}

    candidate_ids = _team_player_ids(roster)
    if not candidate_ids:
        result["note"] = "No roster data available."
        return result

    try:
        season_stats = _load_season_stats(_resolve_data_dir(base_dir) / "season_stats.json")
        current_players = season_stats.get("players", {}) or {}
        if not isinstance(current_players, Mapping):
            current_players = {}
    except Exception:
        current_players = {}

    used_current = False
    min_ab = 8.0
    min_ip = 3.0
    hitters: list[Dict[str, Any]] = []
    pitchers: list[Dict[str, Any]] = []
    for pid in candidate_ids:
        player = players.get(pid)
        if player is None:
            continue
        start_stats = start_players.get(pid, {}) or {}
        end_stats = end_players.get(pid, {}) or {}
        if current_players and (not end_stats or not isinstance(end_stats, Mapping)):
            fallback = current_players.get(pid, {}) or {}
            if isinstance(fallback, Mapping) and fallback:
                end_stats = fallback
                used_current = True
        if not isinstance(start_stats, Mapping):
            start_stats = {}
        if not isinstance(end_stats, Mapping):
            end_stats = {}
        if not start_stats and not end_stats:
            continue

        if _is_pitcher_type(player):
            ip = _ip_delta(end_stats, start_stats)
            if ip < min_ip:
                continue
            er = _stat_delta(end_stats, start_stats, ("er", "ER"))
            bb = _stat_delta(end_stats, start_stats, ("bb", "BB"))
            hits = _stat_delta(end_stats, start_stats, ("h", "H"))
            so = _stat_delta(end_stats, start_stats, ("so", "SO", "k", "K"))
            era = (er * 9.0) / ip if ip else None
            whip = (bb + hits) / ip if ip else None
            if era is None:
                continue
            pitchers.append(
                {
                    "player_id": str(pid),
                    "name": _format_player_name(player),
                    "era": round(float(era), 2),
                    "whip": round(float(whip), 2) if whip is not None else None,
                    "ip": float(ip),
                    "so": int(round(so)),
                }
            )
        else:
            ab = _stat_delta(end_stats, start_stats, ("ab", "AB"))
            if ab < min_ab:
                continue
            hits = _stat_delta(end_stats, start_stats, ("h", "H"))
            hr = _stat_delta(end_stats, start_stats, ("hr", "HR"))
            rbi = _stat_delta(end_stats, start_stats, ("rbi", "RBI"))
            bb = _stat_delta(end_stats, start_stats, ("bb", "BB"))
            hbp = _stat_delta(end_stats, start_stats, ("hbp", "HBP"))
            sf = _stat_delta(end_stats, start_stats, ("sf", "SF"))
            doubles = _stat_delta(end_stats, start_stats, ("2b", "b2", "B2"))
            triples = _stat_delta(end_stats, start_stats, ("3b", "b3", "B3"))
            singles = max(hits - doubles - triples - hr, 0.0)
            avg = hits / ab if ab else None
            denom_obp = ab + bb + hbp + sf
            obp = (hits + bb + hbp) / denom_obp if denom_obp else None
            total_bases = singles + 2 * doubles + 3 * triples + 4 * hr
            slg = total_bases / ab if ab else None
            ops = (obp + slg) if obp is not None and slg is not None else None
            if ops is None:
                continue
            hitters.append(
                {
                    "player_id": str(pid),
                    "name": _format_player_name(player),
                    "avg": round(float(avg), 3) if avg is not None else None,
                    "ops": round(float(ops), 3) if ops is not None else None,
                    "hr": int(round(hr)),
                    "rbi": int(round(rbi)),
                    "ab": int(round(ab)),
                }
            )

    if hitters:
        hot_hitters = sorted(
            hitters,
            key=lambda entry: (
                entry.get("ops", 0.0),
                entry.get("avg", 0.0),
                entry.get("ab", 0),
            ),
            reverse=True,
        )
        cold_hitters = sorted(
            hitters,
            key=lambda entry: (
                entry.get("ops", 0.0),
                entry.get("avg", 0.0),
                entry.get("ab", 0),
            ),
        )
        result["hitters"]["hot"] = hot_hitters[:limit]
        result["hitters"]["cold"] = cold_hitters[:limit]

    if pitchers:
        hot_pitchers = sorted(
            pitchers,
            key=lambda entry: (entry.get("era", 0.0), -entry.get("ip", 0.0)),
        )
        cold_pitchers = sorted(
            pitchers,
            key=lambda entry: (-entry.get("era", 0.0), -entry.get("ip", 0.0)),
        )
        result["pitchers"]["hot"] = hot_pitchers[:limit]
        result["pitchers"]["cold"] = cold_pitchers[:limit]

    if not hitters and not pitchers:
        result["note"] = "Recent performance samples unavailable."
    elif used_current:
        note = "Using season-to-date stats for missing history snapshots."
        if result.get("note"):
            result["note"] = f"{result['note']} {note}"
        else:
            result["note"] = note
    return result


def _load_team_metadata(base_dir: Path) -> Dict[str, Dict[str, str]]:
    path = _resolve_data_dir(base_dir) / "teams.csv"
    if not path.exists():
        return {}
    metadata: Dict[str, Dict[str, str]] = {}
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                team_id = str(row.get("team_id") or "").strip()
                if not team_id:
                    continue
                city = str(row.get("city") or "").strip()
                name = str(row.get("name") or "").strip()
                division = str(row.get("division") or "").strip()
                abbr = str(row.get("abbreviation") or team_id).strip()
                full_name = " ".join(part for part in (city, name) if part).strip()
                metadata[team_id] = {
                    "division": division,
                    "label": abbr or team_id,
                    "name": full_name or team_id,
                }
    except OSError:
        return {}
    return metadata


def _collect_division_standings(
    team_id: str,
    base_dir: Path,
    standings: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    meta = _load_team_metadata(base_dir)
    team_meta = meta.get(team_id, {})
    division = team_meta.get("division") or "--"
    if division == "--":
        return {"division": division, "teams": []}

    division_teams = [
        (tid, info) for tid, info in meta.items() if info.get("division") == division
    ]
    if not division_teams:
        return {"division": division, "teams": []}

    def win_pct(record: Mapping[str, Any]) -> float:
        wins = int(record.get("wins", 0) or 0)
        losses = int(record.get("losses", 0) or 0)
        games = wins + losses
        return wins / games if games else 0.0

    def sort_key(team_info: tuple[str, Mapping[str, str]]) -> tuple[float, int]:
        record = standings.get(team_info[0], default_record())
        return (win_pct(record), int(record.get("wins", 0)))

    teams_sorted = sorted(division_teams, key=sort_key, reverse=True)
    leader_record = (
        standings.get(teams_sorted[0][0], default_record())
        if teams_sorted
        else default_record()
    )
    leader_wins = int(leader_record.get("wins", 0))
    leader_losses = int(leader_record.get("losses", 0))

    rows: list[Dict[str, Any]] = []
    for tid, info in teams_sorted:
        record = standings.get(tid, default_record())
        wins = int(record.get("wins", 0))
        losses = int(record.get("losses", 0))
        games = wins + losses
        pct = wins / games if games else 0.0
        gb_value = ((leader_wins - wins) + (losses - leader_losses)) / 2
        if abs(gb_value) < 1e-6:
            gb_str = "0"
        else:
            gb_str = f"{gb_value:.1f}".rstrip("0").rstrip(".")
        rows.append(
            {
                "team_id": tid,
                "label": info.get("label") or tid,
                "name": info.get("name") or tid,
                "wins": wins,
                "losses": losses,
                "pct": round(pct, 3),
                "gb": gb_str,
                "streak": _format_streak(record),
                "last10": _format_last10(record),
                "is_current": tid == team_id,
            }
        )
    return {"division": division, "teams": rows}


# ---------------------------------------------------------------------------
# Team leader helpers


def _collect_team_leaders(
    base_dir: Path,
    roster: Any | None,
    players: Mapping[str, Any] | None,
) -> tuple[Dict[str, str], Dict[str, str], Dict[str, Dict[str, Dict[str, Any]]]]:
    batting = {"avg": "--", "hr": "--", "rbi": "--"}
    pitching = {"wins": "--", "so": "--", "saves": "--"}
    meta: Dict[str, Dict[str, Dict[str, Any]]] = {"batting": {}, "pitching": {}}
    if roster is None or not players:
        return batting, pitching, meta

    candidate_ids: list[str] = []
    seen: set[str] = set()
    for attr in ("act", "dl", "ir"):
        try:
            ids = getattr(roster, attr, []) or []
        except Exception:
            ids = []
        for pid in ids:
            if not pid:
                continue
            pid_str = str(pid)
            if pid_str in seen:
                continue
            candidate_ids.append(pid_str)
            seen.add(pid_str)
    if not candidate_ids:
        return batting, pitching, meta

    try:
        stats_payload = _load_season_stats(_resolve_data_dir(base_dir) / "season_stats.json")
    except Exception:
        stats_payload = {}
    raw_player_stats = (
        stats_payload.get("players", {}) if isinstance(stats_payload, Mapping) else {}
    )
    team_stats = (
        stats_payload.get("teams", {}) if isinstance(stats_payload, Mapping) else {}
    )
    team_games = 0
    try:
        team_id = getattr(roster, "team_id", None)
        if team_id and isinstance(team_stats, Mapping):
            team_entry = team_stats.get(str(team_id), {}) or {}
            team_games = int(team_entry.get("g", team_entry.get("games", 0)) or 0)
        if not team_games and isinstance(team_stats, Mapping):
            games_list = [
                int(v.get("g", v.get("games", 0)) or 0) for v in team_stats.values()
            ]
            team_games = max(games_list) if games_list else 0
    except Exception:
        team_games = 0
    min_pa = int(round(team_games * 3.1)) if team_games else 0
    min_ip = float(round(team_games * 1.0, 2)) if team_games else 0.0

    hitters_all: list[tuple[Any, Mapping[str, Any]]] = []
    hitters_qualified: list[tuple[Any, Mapping[str, Any]]] = []
    pitchers_all: list[tuple[Any, Mapping[str, Any]]] = []
    pitchers_qualified: list[tuple[Any, Mapping[str, Any]]] = []
    for pid in candidate_ids:
        player = players.get(pid)
        if player is None:
            continue
        stats = raw_player_stats.get(pid, {})
        if not isinstance(stats, Mapping):
            stats = {}
        if not stats:
            local_stats = getattr(player, "season_stats", None)
            if isinstance(local_stats, Mapping):
                stats = local_stats
        if _is_pitcher_type(player):
            if _has_pitcher_sample(stats):
                pitchers_all.append((player, stats))
                if _qualifies_pitcher(stats, min_ip):
                    pitchers_qualified.append((player, stats))
        else:
            if _has_batter_sample(stats):
                hitters_all.append((player, stats))
                if _qualifies_batter(stats, min_pa):
                    hitters_qualified.append((player, stats))

    hitters = hitters_qualified or hitters_all
    pitchers = pitchers_qualified or pitchers_all
    save_pool = pitchers_all or pitchers

    avg_leader = _find_avg_leader(hitters)
    hr_leader = _find_stat_leader(hitters, ("hr", "HR"))
    rbi_leader = _find_stat_leader(hitters, ("rbi", "RBI"))
    win_leader = _find_stat_leader(pitchers, ("w", "wins", "W"))
    so_leader = _find_stat_leader(pitchers, ("so", "SO", "k", "K"))
    save_leader = _find_stat_leader(save_pool, ("sv", "SV", "saves", "S"))

    batting["avg"], meta_entry = _format_leader_entry(avg_leader, stat="avg")
    if meta_entry and meta_entry.get("player_id"):
        meta["batting"]["avg"] = meta_entry
    batting["hr"], meta_entry = _format_leader_entry(hr_leader, stat="int")
    if meta_entry and meta_entry.get("player_id"):
        meta["batting"]["hr"] = meta_entry
    batting["rbi"], meta_entry = _format_leader_entry(rbi_leader, stat="int")
    if meta_entry and meta_entry.get("player_id"):
        meta["batting"]["rbi"] = meta_entry

    pitching["wins"], meta_entry = _format_leader_entry(win_leader, stat="int")
    if meta_entry and meta_entry.get("player_id"):
        meta["pitching"]["wins"] = meta_entry
    pitching["so"], meta_entry = _format_leader_entry(so_leader, stat="int")
    if meta_entry and meta_entry.get("player_id"):
        meta["pitching"]["so"] = meta_entry
    pitching["saves"], meta_entry = _format_leader_entry(save_leader, stat="int")
    if meta_entry and meta_entry.get("player_id"):
        meta["pitching"]["saves"] = meta_entry

    return batting, pitching, meta


def _has_batter_sample(stats: Mapping[str, Any]) -> bool:
    ab = _safe_float(_first_value(stats, ("ab", "AB")))
    pa = _safe_float(_first_value(stats, ("pa", "PA")))
    sample = ab if ab is not None else pa
    return sample is not None and sample > 0


def _has_pitcher_sample(stats: Mapping[str, Any]) -> bool:
    outs = _safe_float(_first_value(stats, ("outs", "OUTS")))
    if outs is None:
        ip_val = _safe_float(_first_value(stats, ("ip", "IP")))
        if ip_val is not None:
            outs = ip_val * 3.0
    return outs is not None and outs > 0


def _batter_pa(stats: Mapping[str, Any]) -> float:
    pa = _safe_float(_first_value(stats, ("pa", "PA")))
    if pa is not None:
        return pa
    ab = _safe_float(_first_value(stats, ("ab", "AB"))) or 0.0
    bb = _safe_float(_first_value(stats, ("bb", "BB"))) or 0.0
    hbp = _safe_float(_first_value(stats, ("hbp", "HBP"))) or 0.0
    sf = _safe_float(_first_value(stats, ("sf", "SF"))) or 0.0
    ci = _safe_float(_first_value(stats, ("ci", "CI"))) or 0.0
    return ab + bb + hbp + sf + ci


def _pitcher_ip(stats: Mapping[str, Any]) -> float:
    ip_val = _safe_float(_first_value(stats, ("ip", "IP")))
    if ip_val is not None:
        return ip_val
    outs = _safe_float(_first_value(stats, ("outs", "OUTS")))
    return (outs / 3.0) if outs is not None else 0.0


def _qualifies_batter(stats: Mapping[str, Any], min_pa: int) -> bool:
    if min_pa <= 0:
        return True
    return _batter_pa(stats) >= min_pa


def _qualifies_pitcher(stats: Mapping[str, Any], min_ip: float) -> bool:
    if min_ip <= 0:
        return True
    return _pitcher_ip(stats) >= min_ip


def _find_avg_leader(
    hitters: Sequence[tuple[Any, Mapping[str, Any]]],
) -> Optional[tuple[Any, float]]:
    leader: Optional[tuple[Any, float]] = None
    for player, stats in hitters:
        avg_val = _safe_float(_first_value(stats, ("avg", "AVG")))
        if avg_val is None:
            hits = _safe_float(_first_value(stats, ("h", "H"))) or 0.0
            ab = _safe_float(_first_value(stats, ("ab", "AB")))
            if ab is not None and ab > 0:
                avg_val = hits / ab
        ab_sample = _safe_float(_first_value(stats, ("ab", "AB")))
        if avg_val is None or ab_sample is None or ab_sample <= 0:
            continue
        if leader is None or avg_val > leader[1]:
            leader = (player, avg_val)
    return leader


def _find_stat_leader(
    candidates: Sequence[tuple[Any, Mapping[str, Any]]],
    keys: Sequence[str],
) -> Optional[tuple[Any, float]]:
    leader: Optional[tuple[Any, float]] = None
    for player, stats in candidates:
        value = _safe_float(_first_value(stats, keys))
        if value is None:
            continue
        if leader is None or value > leader[1]:
            leader = (player, value)
    return leader


def _player_identifier(player: Any) -> Optional[str]:
    """Best-effort player identifier extraction for leader links."""

    for attr in ("player_id", "playerId", "id", "mlb_id"):  # noqa: SIM118
        candidate = getattr(player, attr, None)
        if candidate:
            return str(candidate)
    return None


def _calibration_summary(base_dir: Path) -> Dict[str, Any]:
    """Expose pitch calibration status for quick diagnostics."""

    defaults = {
        "enabled": False,
        "target_p_per_pa": None,
        "tolerance": None,
        "per_plate_cap": None,
        "per_game_cap": None,
        "min_pa": None,
        "ema_alpha": None,
    }
    if _load_playbalance_config is None:
        return defaults

    try:
        cfg = _load_playbalance_config(
            pbini_path=base_dir / "playbalance" / "PBINI.txt",
            overrides_path=_resolve_data_dir(base_dir) / "playbalance_overrides.json",
        )
        pb = cfg.sections.get("PlayBalance")
        if pb is None:
            return defaults
        enabled = bool(getattr(pb, "pitchCalibrationEnabled", 0))
        return {
            "enabled": enabled,
            "target_p_per_pa": float(getattr(pb, "pitchCalibrationTarget", 0.0)),
            "tolerance": float(getattr(pb, "pitchCalibrationTolerance", 0.0)),
            "per_plate_cap": int(getattr(pb, "pitchCalibrationPerPlateCap", 0) or 0),
            "per_game_cap": int(getattr(pb, "pitchCalibrationPerGameCap", 0) or 0),
            "min_pa": int(getattr(pb, "pitchCalibrationMinPA", 0) or 0),
            "ema_alpha": float(getattr(pb, "pitchCalibrationEmaAlpha", 0.0)),
        }
    except Exception:
        return defaults


def _usage_calibration_summary(base_dir: Path) -> Dict[str, Any]:
    """Load the latest usage calibration artifact for owner dashboard context."""

    defaults: Dict[str, Any] = {
        "available": False,
        "path": None,
        "generated_at": "--",
        "summary": "Usage calibration summary unavailable.",
        "roles": {},
        "targets": {},
        "target_groups": 0,
        "target_groups_in_range": 0,
        "target_pass_rate": None,
    }
    data_dir = _resolve_data_dir(base_dir)
    candidates = [
        data_dir / "reports" / "usage_calibration_summary.json",
        base_dir / "reports" / "usage_calibration_summary.json",
    ]
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, Mapping):
            continue
        targets = payload.get("targets")
        if not isinstance(targets, Mapping):
            targets = {}
        roles = payload.get("roles")
        if not isinstance(roles, Mapping):
            roles = {}
        total = 0
        in_range = 0
        for role_payload in targets.values():
            if not isinstance(role_payload, Mapping):
                continue
            total += 1
            if bool(role_payload.get("all_in_range")):
                in_range += 1
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            if total:
                summary = f"{in_range}/{total} role targets in range."
            else:
                summary = "Usage calibration summary loaded."
        generated_at = str(payload.get("generated_at") or "--")
        pass_rate = round(in_range / total, 3) if total else None
        return {
            "available": True,
            "path": str(path),
            "generated_at": generated_at,
            "summary": summary,
            "roles": dict(roles),
            "targets": dict(targets),
            "target_groups": total,
            "target_groups_in_range": in_range,
            "target_pass_rate": pass_rate,
        }
    return defaults


def _format_leader_entry(
    leader: Optional[tuple[Any, float]],
    *,
    stat: str,
) -> tuple[str, Optional[Dict[str, Any]]]:
    if leader is None:
        return "--", None
    player, value = leader
    name = _format_player_name(player)
    if name == "--":
        return "--", None
    if stat == "avg":
        if not math.isfinite(value):
            return "--", None
        formatted = f"{value:.3f}"
        if value < 1:
            formatted = formatted.lstrip("0")
        return f"{name} {formatted}".strip(), {
            "player_id": _player_identifier(player),
            "name": name,
            "stat": "avg",
            "value": round(value, 3),
        }
    if not math.isfinite(value):
        return "--", None
    count = int(round(value))
    return f"{name} {count}".strip(), {
        "player_id": _player_identifier(player),
        "name": name,
        "stat": stat,
        "value": count,
    }


def _is_pitcher_type(player: Any) -> bool:
    if player is None:
        return False
    if bool(getattr(player, "is_pitcher", False)):
        return True
    primary = str(getattr(player, "primary_position", "")).upper()
    return primary in {"P", "SP", "RP", "CL"}


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        if not math.isfinite(result):
            return None
        return result
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped in {"--", "NA", "N/A"}:
            return None
        try:
            result = float(stripped)
        except ValueError:
            return None
        if not math.isfinite(result):
            return None
        return result
    return None


def _first_value(stats: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in stats:
            return stats[key]
    return None


def _current_date() -> date:
    sim_date = get_current_sim_date()
    if sim_date:
        try:
            return datetime.strptime(str(sim_date), DATE_FMT).date()
        except Exception:
            pass
    return datetime.utcnow().date()


def _parse_date(value: str | None) -> date:
    if not value:
        return datetime.utcnow().date()
    try:
        return datetime.strptime(value, DATE_FMT).date()
    except Exception:
        return datetime.utcnow().date()


def _coerce_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value), DATE_FMT).date()
    except Exception:
        return None


def _format_player_name(player: Any | None) -> str:
    if player is None:
        return "--"
    first = str(getattr(player, "first_name", "")).strip()
    last = str(getattr(player, "last_name", "")).strip()
    full = " ".join(part for part in (first, last) if part)
    return full or str(getattr(player, "player_id", "--"))


__all__ = ["gather_owner_quick_metrics"]

