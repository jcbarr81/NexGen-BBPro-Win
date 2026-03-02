from __future__ import annotations

"""Career-arc analytics derived from archived league seasons."""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping
import csv
import json

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir, resolve_app_path
from utils.standings_utils import normalize_record
from utils.team_loader import load_teams

__all__ = [
    "CAREER_ARC_YOY_FIELDS",
    "CAREER_ARC_TREND_FIELDS",
    "CAREER_ARC_ERA_FIELDS",
    "build_career_arc_analytics",
]


CAREER_ARC_YOY_FIELDS = [
    "team_id",
    "team_name",
    "season_id",
    "league_year",
    "wins",
    "losses",
    "games",
    "win_pct",
    "runs_for",
    "runs_against",
    "run_diff",
    "prev_wins",
    "prev_win_pct",
    "prev_run_diff",
    "delta_wins",
    "delta_win_pct",
    "delta_run_diff",
    "is_champion",
]

CAREER_ARC_TREND_FIELDS = [
    "team_id",
    "team_name",
    "seasons",
    "first_year",
    "last_year",
    "avg_wins",
    "avg_win_pct",
    "avg_run_diff",
    "win_pct_slope",
    "run_diff_slope",
    "recent_win_pct",
    "recent_run_diff",
    "win_pct_momentum",
    "run_diff_momentum",
    "championships",
]

CAREER_ARC_ERA_FIELDS = [
    "team_id",
    "team_name",
    "era_label",
    "era_start_year",
    "era_end_year",
    "seasons",
    "wins",
    "losses",
    "win_pct",
    "avg_run_diff",
    "championships",
]


def build_career_arc_analytics(
    *,
    data_dir: Path | str | None = None,
    era_window: int = 3,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build YoY, trend, and team-era career analytics from archives."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    context = SeasonContext.load(path=resolved_data_dir / "career_index.json")
    team_names = _load_team_names(resolved_data_dir)
    year_rows = _build_team_year_rows(context.seasons, team_names, resolved_data_dir)
    yoy_rows = _build_yoy_rows(year_rows)
    trend_rows = _build_trend_rows(yoy_rows)
    era_rows = _build_era_rows(yoy_rows, window=max(2, int(era_window)))
    return {
        "yoy": yoy_rows,
        "trends": trend_rows,
        "team_eras": era_rows,
    }


def _load_team_names(data_dir: Path) -> Dict[str, str]:
    try:
        teams = load_teams(data_dir / "teams.csv")
    except Exception:
        return {}
    names: Dict[str, str] = {}
    for team in teams:
        team_id = str(getattr(team, "team_id", "") or "").strip()
        if not team_id:
            continue
        full_name = f"{getattr(team, 'city', '')} {getattr(team, 'name', '')}".strip()
        names[team_id] = full_name or team_id
    return names


def _build_team_year_rows(
    seasons: Iterable[Dict[str, Any]],
    team_names: Mapping[str, str],
    data_dir: Path,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for season in seasons:
        if not isinstance(season, dict):
            continue
        season_id = str(season.get("season_id") or "").strip()
        if not season_id:
            continue
        year = _parse_year(season.get("league_year"), season_id)
        if year is None:
            continue
        standings = _load_archived_standings(season, season_id, data_dir)
        champion = _resolve_champion_team_id(season, season_id, year, data_dir)
        for team_id, raw_record in standings.items():
            record = normalize_record(raw_record if isinstance(raw_record, dict) else {})
            wins = int(record.get("wins", 0) or 0)
            losses = int(record.get("losses", 0) or 0)
            games = wins + losses
            runs_for = int(record.get("runs_for", 0) or 0)
            runs_against = int(record.get("runs_against", 0) or 0)
            rows.append(
                {
                    "team_id": team_id,
                    "team_name": team_names.get(team_id, team_id),
                    "season_id": season_id,
                    "league_year": year,
                    "wins": wins,
                    "losses": losses,
                    "games": games,
                    "win_pct": round((wins / games) if games else 0.0, 3),
                    "runs_for": runs_for,
                    "runs_against": runs_against,
                    "run_diff": runs_for - runs_against,
                    "is_champion": int(bool(champion and team_id == champion)),
                }
            )
    rows.sort(key=lambda row: (str(row["team_id"]), int(row["league_year"])))
    return rows


def _build_yoy_rows(year_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    previous_by_team: Dict[str, Dict[str, Any]] = {}
    for row in year_rows:
        team_id = str(row.get("team_id") or "")
        previous = previous_by_team.get(team_id, {})
        prev_wins = _safe_int(previous.get("wins"))
        prev_win_pct = _safe_float(previous.get("win_pct"))
        prev_run_diff = _safe_int(previous.get("run_diff"))
        wins = _safe_int(row.get("wins"))
        win_pct = _safe_float(row.get("win_pct"))
        run_diff = _safe_int(row.get("run_diff"))
        result.append(
            {
                **row,
                "prev_wins": prev_wins if previous else None,
                "prev_win_pct": round(prev_win_pct, 3) if previous else None,
                "prev_run_diff": prev_run_diff if previous else None,
                "delta_wins": (wins - prev_wins) if previous else None,
                "delta_win_pct": round(win_pct - prev_win_pct, 3) if previous else None,
                "delta_run_diff": (run_diff - prev_run_diff) if previous else None,
            }
        )
        previous_by_team[team_id] = row
    return result


def _build_trend_rows(yoy_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    team_rows: Dict[str, List[Dict[str, Any]]] = {}
    for row in yoy_rows:
        team_rows.setdefault(str(row.get("team_id") or ""), []).append(row)

    trends: List[Dict[str, Any]] = []
    for team_id, rows in team_rows.items():
        rows = sorted(rows, key=lambda item: int(item.get("league_year", 0)))
        years = [int(item.get("league_year", 0)) for item in rows]
        wins = [_safe_int(item.get("wins")) for item in rows]
        win_pct = [_safe_float(item.get("win_pct")) for item in rows]
        run_diff = [_safe_float(item.get("run_diff")) for item in rows]
        championships = sum(int(item.get("is_champion", 0) or 0) for item in rows)
        recent_size = 3 if len(rows) >= 3 else len(rows)
        recent_win_pct = _avg(win_pct[-recent_size:]) if recent_size else 0.0
        recent_run_diff = _avg(run_diff[-recent_size:]) if recent_size else 0.0
        prior_window = win_pct[:-recent_size] if recent_size and len(win_pct) > recent_size else []
        prior_run_window = run_diff[:-recent_size] if recent_size and len(run_diff) > recent_size else []
        prior_win_pct = _avg(prior_window) if prior_window else win_pct[0] if win_pct else 0.0
        prior_run_diff = _avg(prior_run_window) if prior_run_window else run_diff[0] if run_diff else 0.0

        trends.append(
            {
                "team_id": team_id,
                "team_name": rows[-1].get("team_name", team_id) if rows else team_id,
                "seasons": len(rows),
                "first_year": years[0] if years else "",
                "last_year": years[-1] if years else "",
                "avg_wins": round(_avg(wins), 2),
                "avg_win_pct": round(_avg(win_pct), 3),
                "avg_run_diff": round(_avg(run_diff), 2),
                "win_pct_slope": round(_slope(win_pct), 4),
                "run_diff_slope": round(_slope(run_diff), 4),
                "recent_win_pct": round(recent_win_pct, 3),
                "recent_run_diff": round(recent_run_diff, 2),
                "win_pct_momentum": round(recent_win_pct - prior_win_pct, 3),
                "run_diff_momentum": round(recent_run_diff - prior_run_diff, 2),
                "championships": championships,
            }
        )
    trends.sort(
        key=lambda row: (
            -_safe_float(row.get("avg_win_pct")),
            -_safe_float(row.get("avg_run_diff")),
            str(row.get("team_id") or ""),
        )
    )
    return trends


def _build_era_rows(
    yoy_rows: List[Dict[str, Any]],
    *,
    window: int,
) -> List[Dict[str, Any]]:
    team_rows: Dict[str, List[Dict[str, Any]]] = {}
    for row in yoy_rows:
        team_rows.setdefault(str(row.get("team_id") or ""), []).append(row)

    era_rows: List[Dict[str, Any]] = []
    for team_id, rows in team_rows.items():
        ordered = sorted(rows, key=lambda item: int(item.get("league_year", 0)))
        slices: List[List[Dict[str, Any]]] = []
        if len(ordered) <= window:
            slices.append(ordered)
        else:
            for idx in range(0, len(ordered) - window + 1):
                slices.append(ordered[idx : idx + window])
        for segment in slices:
            if not segment:
                continue
            start_year = int(segment[0].get("league_year", 0) or 0)
            end_year = int(segment[-1].get("league_year", 0) or 0)
            wins = sum(_safe_int(item.get("wins")) for item in segment)
            losses = sum(_safe_int(item.get("losses")) for item in segment)
            games = wins + losses
            run_diff = [_safe_float(item.get("run_diff")) for item in segment]
            championships = sum(int(item.get("is_champion", 0) or 0) for item in segment)
            era_rows.append(
                {
                    "team_id": team_id,
                    "team_name": segment[-1].get("team_name", team_id),
                    "era_label": f"{start_year}-{end_year}",
                    "era_start_year": start_year,
                    "era_end_year": end_year,
                    "seasons": len(segment),
                    "wins": wins,
                    "losses": losses,
                    "win_pct": round((wins / games) if games else 0.0, 3),
                    "avg_run_diff": round(_avg(run_diff), 2),
                    "championships": championships,
                }
            )
    era_rows.sort(
        key=lambda row: (
            -_safe_float(row.get("win_pct")),
            -_safe_int(row.get("wins")),
            str(row.get("team_id") or ""),
            str(row.get("era_label") or ""),
        )
    )
    return era_rows


def _season_artifacts(season: Dict[str, Any], season_id: str, data_dir: Path) -> Dict[str, str]:
    artifacts = season.get("artifacts")
    if isinstance(artifacts, dict) and artifacts:
        return {
            str(key): str(value)
            for key, value in artifacts.items()
            if value
        }
    meta_path = data_dir / "careers" / season_id / "metadata.json"
    payload = _read_json(meta_path, {})
    meta_artifacts = payload.get("artifacts", {})
    if isinstance(meta_artifacts, dict) and meta_artifacts:
        return {
            str(key): str(value)
            for key, value in meta_artifacts.items()
            if value
        }
    return {}


def _load_archived_standings(
    season: Dict[str, Any],
    season_id: str,
    data_dir: Path,
) -> Dict[str, Dict[str, Any]]:
    artifacts = _season_artifacts(season, season_id, data_dir)
    path = _resolve_path(artifacts.get("standings"))
    if path is None:
        fallback = data_dir / "careers" / season_id / "standings.json"
        path = fallback if fallback.exists() else None
    payload = _read_json(path, {}) if path is not None else {}
    if not isinstance(payload, dict):
        return {}
    rows: Dict[str, Dict[str, Any]] = {}
    for team_id, entry in payload.items():
        clean_team_id = str(team_id or "").strip()
        if not clean_team_id or not isinstance(entry, dict):
            continue
        rows[clean_team_id] = entry
    return rows


def _resolve_champion_team_id(
    season: Dict[str, Any],
    season_id: str,
    league_year: int,
    data_dir: Path,
) -> str:
    artifacts = _season_artifacts(season, season_id, data_dir)
    champions_path = _resolve_path(artifacts.get("champions"))
    champion = _load_champion_from_csv(champions_path, league_year)
    if champion:
        return champion

    playoffs_path = _resolve_path(artifacts.get("playoffs"))
    if playoffs_path is None:
        fallback = data_dir / "careers" / season_id / f"playoffs_{league_year}.json"
        if fallback.exists():
            playoffs_path = fallback
    payload = _read_json(playoffs_path, {}) if playoffs_path is not None else {}
    if isinstance(payload, dict):
        return str(payload.get("champion") or "").strip()
    return ""


def _load_champion_from_csv(path: Path | None, league_year: int) -> str:
    if path is None or not path.exists():
        return ""
    target = str(league_year)
    selected: Dict[str, Any] | None = None
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not row:
                    continue
                row_year = str(row.get("year") or "").strip()
                if row_year and row_year != target:
                    continue
                selected = row
    except OSError:
        return ""
    if not selected:
        return ""
    return str(selected.get("champion") or "").strip()


def _resolve_path(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    candidate = Path(path_str)
    if candidate.is_absolute():
        return candidate
    return resolve_app_path(candidate)


def _read_json(path: Path | None, default: Any) -> Any:
    if path is None or not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def _parse_year(raw_year: Any, season_id: str) -> int | None:
    try:
        year = int(raw_year)
    except Exception:
        year = 0
    if year > 0:
        return year
    token = str(season_id or "").strip().rsplit("-", maxsplit=1)
    if len(token) != 2:
        return None
    try:
        parsed = int(token[-1])
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _safe_int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _avg(values: List[float] | List[int]) -> float:
    if not values:
        return 0.0
    return float(sum(values)) / float(len(values))


def _slope(values: List[float]) -> float:
    n = len(values)
    if n <= 1:
        return 0.0
    x_vals = list(range(n))
    x_mean = _avg(x_vals)
    y_mean = _avg(values)
    numerator = 0.0
    denominator = 0.0
    for idx, y_value in zip(x_vals, values):
        x_delta = float(idx) - x_mean
        numerator += x_delta * (float(y_value) - y_mean)
        denominator += x_delta * x_delta
    if denominator <= 0.0:
        return 0.0
    return numerator / denominator
