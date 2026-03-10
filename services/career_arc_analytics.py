from __future__ import annotations

"""Career-arc analytics derived from archived league seasons."""

from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping
import csv
import json

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir, resolve_app_path
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.stats_persistence import load_stats as load_season_stats
from utils.standings_utils import normalize_record
from utils.team_loader import load_teams

__all__ = [
    "CAREER_ARC_YOY_FIELDS",
    "CAREER_ARC_TREND_FIELDS",
    "CAREER_ARC_ERA_FIELDS",
    "CAREER_ARC_SIMILARITY_FIELDS",
    "CAREER_ARC_AGING_BUCKET_FIELDS",
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

CAREER_ARC_SIMILARITY_FIELDS = [
    "target_player_id",
    "target_player_name",
    "target_team_id",
    "target_primary_position",
    "target_age",
    "comparable_player_id",
    "comparable_player_name",
    "comparable_team_id",
    "comparable_primary_position",
    "comparable_age",
    "same_position",
    "similarity_score",
    "rating_distance",
    "stat_distance",
    "age_distance",
]

CAREER_ARC_AGING_BUCKET_FIELDS = [
    "position_group",
    "bucket_label",
    "age_min",
    "age_max",
    "players",
    "avg_overall",
    "avg_potential",
    "avg_perf_index",
    "avg_ops",
    "avg_era",
]


def build_career_arc_analytics(
    *,
    data_dir: Path | str | None = None,
    era_window: int = 3,
    filters: Mapping[str, object] | None = None,
    target_player_id: str | None = None,
    similarity_top_n: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build v2 career analytics from archives and current-season player data."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    context = SeasonContext.load(path=resolved_data_dir / "career_index.json")
    team_names = _load_team_names(resolved_data_dir)
    parsed_filters = _normalize_filters(filters)
    year_rows = _build_team_year_rows(context.seasons, team_names, resolved_data_dir)
    year_rows = _apply_team_filters(year_rows, parsed_filters)
    yoy_rows = _build_yoy_rows(year_rows)
    trend_rows = _build_trend_rows(yoy_rows)
    era_rows = _build_era_rows(yoy_rows, window=max(2, int(era_window)))
    player_context = _build_player_context(resolved_data_dir, filters=parsed_filters)
    similarity_rows = _build_similarity_rows(
        player_context,
        target_player_id=target_player_id,
        top_n=max(1, int(similarity_top_n)),
    )
    aging_rows = _build_aging_bucket_rows(player_context)
    return {
        "yoy": yoy_rows,
        "trends": trend_rows,
        "team_eras": era_rows,
        "similarity": similarity_rows,
        "aging_buckets": aging_rows,
        "filters_applied": [parsed_filters],
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


def _normalize_filters(filters: Mapping[str, object] | None) -> Dict[str, object]:
    source = filters if isinstance(filters, Mapping) else {}
    team_ids = source.get("team_ids", [])
    if not isinstance(team_ids, (list, tuple, set)):
        team_ids = []
    clean_team_ids = sorted(
        {
            str(team_id or "").strip().upper()
            for team_id in team_ids
            if str(team_id or "").strip()
        }
    )
    season_from = _safe_int(source.get("season_from"))
    season_to = _safe_int(source.get("season_to"))
    min_age = _safe_int(source.get("min_age"))
    max_age = _safe_int(source.get("max_age"))
    if season_from <= 0:
        season_from = None
    if season_to <= 0:
        season_to = None
    if min_age <= 0:
        min_age = None
    if max_age <= 0:
        max_age = None
    if season_from and season_to and season_from > season_to:
        season_from, season_to = season_to, season_from
    if min_age and max_age and min_age > max_age:
        min_age, max_age = max_age, min_age
    position_group = str(source.get("position_group") or "all").strip().lower()
    if position_group not in {"all", "pitcher", "hitter"}:
        position_group = "all"
    return {
        "team_ids": clean_team_ids,
        "season_from": season_from,
        "season_to": season_to,
        "position_group": position_group,
        "min_age": min_age,
        "max_age": max_age,
    }


def _apply_team_filters(
    year_rows: List[Dict[str, Any]],
    filters: Mapping[str, object],
) -> List[Dict[str, Any]]:
    team_ids = {
        str(team_id or "").strip().upper()
        for team_id in (filters.get("team_ids") or [])
        if str(team_id or "").strip()
    }
    season_from = filters.get("season_from")
    season_to = filters.get("season_to")
    out: List[Dict[str, Any]] = []
    for row in year_rows:
        team_id = str(row.get("team_id") or "").strip().upper()
        league_year = _safe_int(row.get("league_year"))
        if team_ids and team_id not in team_ids:
            continue
        if isinstance(season_from, int) and season_from > 0 and league_year < season_from:
            continue
        if isinstance(season_to, int) and season_to > 0 and league_year > season_to:
            continue
        out.append(row)
    return out


def _age_from_birthdate(raw_birthdate: object) -> int | None:
    token = str(raw_birthdate or "").strip()
    if not token:
        return None
    value = token.split("T", maxsplit=1)[0]
    try:
        born = date.fromisoformat(value)
    except ValueError:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _player_position_group(player: object) -> str:
    is_pitcher = bool(getattr(player, "is_pitcher", False)) or str(
        getattr(player, "primary_position", "") or ""
    ).strip().upper() == "P"
    return "pitcher" if is_pitcher else "hitter"


def _norm_rating(value: object) -> float:
    return max(0.0, min(99.0, _safe_float(value))) / 99.0


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def _safe_div(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return num / den


def _build_player_context(
    data_dir: Path,
    *,
    filters: Mapping[str, object],
) -> List[Dict[str, Any]]:
    try:
        players = list(load_players_from_csv(data_dir / "players.csv"))
    except Exception:
        players = []
    if not players:
        return []

    team_map = _build_player_team_map(data_dir)
    stats_payload = load_season_stats(data_dir / "season_stats.json")
    player_stats = stats_payload.get("players", {}) if isinstance(stats_payload, dict) else {}

    allowed_team_ids = {
        str(team_id or "").strip().upper()
        for team_id in (filters.get("team_ids") or [])
        if str(team_id or "").strip()
    }
    position_group = str(filters.get("position_group") or "all").strip().lower()
    min_age = filters.get("min_age")
    max_age = filters.get("max_age")

    rows: List[Dict[str, Any]] = []
    for player in players:
        player_id = str(getattr(player, "player_id", "") or "").strip()
        if not player_id:
            continue
        team_id = str(team_map.get(player_id, "") or "").strip().upper()
        if allowed_team_ids and team_id not in allowed_team_ids:
            continue
        group = _player_position_group(player)
        if position_group in {"pitcher", "hitter"} and group != position_group:
            continue
        age = _age_from_birthdate(getattr(player, "birthdate", ""))
        if isinstance(min_age, int) and min_age > 0 and isinstance(age, int) and age < min_age:
            continue
        if isinstance(max_age, int) and max_age > 0 and isinstance(age, int) and age > max_age:
            continue

        stats = dict(player_stats.get(player_id, {}) or {})
        if group == "pitcher":
            overall = _mean(
                [
                    _safe_float(getattr(player, "arm", 0)),
                    _safe_float(getattr(player, "control", 0)),
                    _safe_float(getattr(player, "movement", 0)),
                    _safe_float(getattr(player, "endurance", 0)),
                    _safe_float(getattr(player, "hold_runner", 0)),
                ]
            )
            potential = _mean(
                [
                    _safe_float(getattr(player, "pot_arm", getattr(player, "arm", 0))),
                    _safe_float(getattr(player, "pot_control", getattr(player, "control", 0))),
                    _safe_float(getattr(player, "pot_movement", getattr(player, "movement", 0))),
                    _safe_float(getattr(player, "pot_endurance", getattr(player, "endurance", 0))),
                ]
            )
            outs = _safe_float(stats.get("outs"))
            ip = _safe_float(stats.get("ip"))
            innings = ip if ip > 0 else outs / 3.0
            era = _safe_div(_safe_float(stats.get("er")) * 9.0, innings)
            whip = _safe_div(_safe_float(stats.get("bb")) + _safe_float(stats.get("h")), innings)
            so9 = _safe_div(_safe_float(stats.get("so")) * 9.0, innings)
            perf_index = ((4.20 - era) * 4.5) + (so9 * 0.8) - (whip * 2.5)
            feature_vector = [
                _norm_rating(getattr(player, "arm", 0)),
                _norm_rating(getattr(player, "control", 0)),
                _norm_rating(getattr(player, "movement", 0)),
                _norm_rating(getattr(player, "endurance", 0)),
                _norm_rating(getattr(player, "hold_runner", 0)),
                max(0.0, min(1.0, _safe_div(5.0 - era, 5.0))),
                max(0.0, min(1.0, _safe_div(2.0 - whip, 2.0))),
                max(0.0, min(1.0, _safe_div(so9, 12.0))),
            ]
            ops = 0.0
        else:
            overall = _mean(
                [
                    _safe_float(getattr(player, "ch", 0)),
                    _safe_float(getattr(player, "ph", 0)),
                    _safe_float(getattr(player, "sp", 0)),
                    _safe_float(getattr(player, "eye", 0)),
                    _safe_float(getattr(player, "fa", 0)),
                    _safe_float(getattr(player, "arm", 0)),
                    _safe_float(getattr(player, "gf", 0)),
                ]
            )
            potential = _mean(
                [
                    _safe_float(getattr(player, "pot_ch", getattr(player, "ch", 0))),
                    _safe_float(getattr(player, "pot_ph", getattr(player, "ph", 0))),
                    _safe_float(getattr(player, "pot_sp", getattr(player, "sp", 0))),
                    _safe_float(getattr(player, "pot_eye", getattr(player, "eye", 0))),
                    _safe_float(getattr(player, "pot_fa", getattr(player, "fa", 0))),
                    _safe_float(getattr(player, "pot_arm", getattr(player, "arm", 0))),
                ]
            )
            ab = _safe_float(stats.get("ab"))
            hits = _safe_float(stats.get("h"))
            doubles = _safe_float(stats.get("2b", stats.get("b2", 0)))
            triples = _safe_float(stats.get("3b", stats.get("b3", 0)))
            hr = _safe_float(stats.get("hr"))
            walks = _safe_float(stats.get("bb"))
            hbp = _safe_float(stats.get("hbp"))
            sf = _safe_float(stats.get("sf"))
            singles = max(0.0, hits - doubles - triples - hr)
            total_bases = singles + (2.0 * doubles) + (3.0 * triples) + (4.0 * hr)
            obp = _safe_div(hits + walks + hbp, ab + walks + hbp + sf)
            slg = _safe_div(total_bases, ab)
            ops = obp + slg
            perf_index = (ops * 100.0) + (_safe_float(stats.get("hr")) * 1.2) + (_safe_float(stats.get("sb")) * 0.6)
            era = 0.0
            whip = 0.0
            feature_vector = [
                _norm_rating(getattr(player, "ch", 0)),
                _norm_rating(getattr(player, "ph", 0)),
                _norm_rating(getattr(player, "sp", 0)),
                _norm_rating(getattr(player, "eye", 0)),
                _norm_rating(getattr(player, "fa", 0)),
                _norm_rating(getattr(player, "arm", 0)),
                max(0.0, min(1.0, _safe_div(ops, 1.200))),
                max(0.0, min(1.0, _safe_div(_safe_float(stats.get("hr")), 55.0))),
            ]

        rows.append(
            {
                "player_id": player_id,
                "player_name": f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip(),
                "team_id": team_id,
                "primary_position": str(getattr(player, "primary_position", "") or "").strip().upper(),
                "position_group": group,
                "age": age if isinstance(age, int) else None,
                "overall": round(overall, 2),
                "potential": round(potential, 2),
                "ops": round(ops, 3),
                "era": round(era, 2),
                "whip": round(whip, 2),
                "perf_index": round(perf_index, 2),
                "features": feature_vector,
            }
        )
    return rows


def _build_player_team_map(data_dir: Path) -> Dict[str, str]:
    teams = _load_team_names(data_dir)
    roster_dir = data_dir / "rosters"
    out: Dict[str, str] = {}
    for team_id in teams.keys():
        try:
            roster = load_roster(team_id, roster_dir=roster_dir)
        except Exception:
            continue
        for player_id in list(roster.act) + list(roster.aaa) + list(roster.low) + list(roster.dl) + list(roster.ir):
            token = str(player_id or "").strip()
            if token:
                out[token] = team_id
    return out


def _feature_distance(a: List[float], b: List[float]) -> float:
    size = min(len(a), len(b))
    if size <= 0:
        return 1.0
    total = 0.0
    for idx in range(size):
        total += abs(_safe_float(a[idx]) - _safe_float(b[idx]))
    return total / float(size)


def _build_similarity_rows(
    players: List[Dict[str, Any]],
    *,
    target_player_id: str | None,
    top_n: int,
) -> List[Dict[str, Any]]:
    if not players:
        return []
    lookup = {str(row.get("player_id") or ""): row for row in players}
    if target_player_id and str(target_player_id).strip() in lookup:
        targets = [lookup[str(target_player_id).strip()]]
    else:
        ordered = sorted(
            players,
            key=lambda row: (
                -_safe_float(row.get("overall")),
                str(row.get("player_id") or ""),
            ),
        )
        targets = ordered[: min(20, len(ordered))]

    rows: List[Dict[str, Any]] = []
    for target in targets:
        target_id = str(target.get("player_id") or "")
        candidates = [
            player for player in players
            if str(player.get("player_id") or "") != target_id
            and str(player.get("position_group") or "") == str(target.get("position_group") or "")
        ]
        ranked: List[tuple[float, float, float, Dict[str, Any]]] = []
        for candidate in candidates:
            rating_distance = _feature_distance(
                list(target.get("features") or [])[:5],
                list(candidate.get("features") or [])[:5],
            )
            stat_distance = _feature_distance(
                list(target.get("features") or [])[5:],
                list(candidate.get("features") or [])[5:],
            )
            target_age = target.get("age")
            candidate_age = candidate.get("age")
            if isinstance(target_age, int) and isinstance(candidate_age, int):
                age_distance = min(1.0, abs(target_age - candidate_age) / 15.0)
            else:
                age_distance = 0.25
            total_distance = (0.6 * rating_distance) + (0.3 * stat_distance) + (0.1 * age_distance)
            similarity = max(0.0, min(100.0, (1.0 - total_distance) * 100.0))
            ranked.append((similarity, rating_distance, stat_distance, candidate))
        ranked.sort(
            key=lambda entry: (
                -entry[0],
                entry[1],
                entry[2],
                str(entry[3].get("player_id") or ""),
            )
        )
        for similarity, rating_distance, stat_distance, candidate in ranked[:top_n]:
            target_pos = str(target.get("primary_position") or "")
            comp_pos = str(candidate.get("primary_position") or "")
            rows.append(
                {
                    "target_player_id": target.get("player_id", ""),
                    "target_player_name": target.get("player_name", ""),
                    "target_team_id": target.get("team_id", ""),
                    "target_primary_position": target_pos,
                    "target_age": target.get("age", ""),
                    "comparable_player_id": candidate.get("player_id", ""),
                    "comparable_player_name": candidate.get("player_name", ""),
                    "comparable_team_id": candidate.get("team_id", ""),
                    "comparable_primary_position": comp_pos,
                    "comparable_age": candidate.get("age", ""),
                    "same_position": int(bool(target_pos and comp_pos and target_pos == comp_pos)),
                    "similarity_score": round(similarity, 2),
                    "rating_distance": round(rating_distance, 4),
                    "stat_distance": round(stat_distance, 4),
                    "age_distance": round(
                        min(1.0, abs(_safe_int(target.get("age")) - _safe_int(candidate.get("age"))) / 15.0),
                        4,
                    ),
                }
            )
    return rows


def _age_bucket(age: int | None) -> tuple[int, int, str]:
    if age is None:
        return (0, 0, "Unknown")
    if age <= 20:
        return (17, 20, "17-20")
    if age <= 24:
        return (21, 24, "21-24")
    if age <= 28:
        return (25, 28, "25-28")
    if age <= 32:
        return (29, 32, "29-32")
    if age <= 36:
        return (33, 36, "33-36")
    return (37, 50, "37+")


def _build_aging_bucket_rows(players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for player in players:
        age = player.get("age")
        if isinstance(age, int):
            _, _, label = _age_bucket(age)
        else:
            label = "Unknown"
        group = str(player.get("position_group") or "hitter")
        buckets.setdefault((group, label), []).append(player)

    rows: List[Dict[str, Any]] = []
    for (group, label), members in buckets.items():
        if label == "Unknown":
            age_min, age_max = 0, 0
        else:
            age_min, age_max, _ = _age_bucket(_safe_int(members[0].get("age")))
        ops_values = [_safe_float(item.get("ops")) for item in members if _safe_float(item.get("ops")) > 0]
        era_values = [_safe_float(item.get("era")) for item in members if _safe_float(item.get("era")) > 0]
        rows.append(
            {
                "position_group": group,
                "bucket_label": label,
                "age_min": age_min,
                "age_max": age_max,
                "players": len(members),
                "avg_overall": round(_mean([_safe_float(item.get("overall")) for item in members]), 2),
                "avg_potential": round(_mean([_safe_float(item.get("potential")) for item in members]), 2),
                "avg_perf_index": round(_mean([_safe_float(item.get("perf_index")) for item in members]), 3),
                "avg_ops": round(_mean(ops_values), 3) if ops_values else 0.0,
                "avg_era": round(_mean(era_values), 2) if era_values else 0.0,
            }
        )
    rows.sort(
        key=lambda row: (
            str(row.get("position_group") or ""),
            _safe_int(row.get("age_min")),
            str(row.get("bucket_label") or ""),
        )
    )
    return rows


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
