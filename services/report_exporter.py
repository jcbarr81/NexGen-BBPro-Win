from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from playbalance.season_context import SeasonContext
from services.career_arc_analytics import (
    CAREER_ARC_AGING_BUCKET_FIELDS,
    CAREER_ARC_ERA_FIELDS,
    CAREER_ARC_SIMILARITY_FIELDS,
    CAREER_ARC_TREND_FIELDS,
    CAREER_ARC_YOY_FIELDS,
    build_career_arc_analytics,
)
from services.record_book import league_record_book
from services.standings_repository import load_standings
from utils.path_utils import get_data_dir, resolve_app_path
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.stats_persistence import load_stats as _load_season_stats
from utils.team_loader import load_teams
from utils.standings_utils import default_record, normalize_record


_BATTING_COLS = [
    "g",
    "ab",
    "r",
    "h",
    "2b",
    "3b",
    "hr",
    "rbi",
    "bb",
    "so",
    "sb",
    "avg",
    "obp",
    "slg",
]

_PITCHING_COLS = [
    "w",
    "l",
    "era",
    "g",
    "gs",
    "sv",
    "ip",
    "h",
    "er",
    "bb",
    "so",
    "whip",
]

_TEAM_STATS_COLS = ["team_id", "team_name", "g", "w", "l", "r", "ra", "der"]

_BATTING_CATEGORIES = [
    ("Average", "avg", True, False, 3),
    ("Home Runs", "hr", True, False, 0),
    ("RBI", "rbi", True, False, 0),
    ("Stolen Bases", "sb", True, False, 0),
    ("On-Base %", "obp", True, False, 3),
]

_PITCHING_CATEGORIES = [
    ("ERA", "era", False, True, 2),
    ("WHIP", "whip", False, True, 2),
    ("Wins", "w", True, True, 0),
    ("Strikeouts", "so", True, True, 0),
    ("Saves", "sv", True, True, 0),
]


@dataclass
class ExportResult:
    output_dir: Path
    files: Dict[str, Path]
    pdf_written: bool = False


def export_reports(
    output_dir: str | Path | None = None,
    *,
    report_format: str = "csv",
    include_csv: bool | None = None,
    include_pdf: bool = True,
) -> ExportResult:
    """Export league history + analytics reports in CSV and/or HTML formats."""
    out_dir = _resolve_output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    normalized_format = str(report_format or "csv").strip().lower()
    if normalized_format not in {"csv", "html", "both"}:
        normalized_format = "csv"
    if include_csv is None:
        include_csv = normalized_format in {"csv", "both"}
    include_html = normalized_format in {"html", "both"}

    files: Dict[str, Path] = {}
    files["standings_csv"] = _export_standings(out_dir)
    files["league_stats_teams_csv"] = _export_league_team_stats(out_dir)
    files["league_stats_batting_csv"] = _export_league_player_stats(
        out_dir,
        batting=True,
    )
    files["league_stats_pitching_csv"] = _export_league_player_stats(
        out_dir,
        batting=False,
    )
    files["league_leaders_batting_csv"] = _export_league_leaders(
        out_dir,
        batting=True,
    )
    files["league_leaders_pitching_csv"] = _export_league_leaders(
        out_dir,
        batting=False,
    )
    files.update(_export_career_arc_analytics(out_dir))
    files["league_history_csv"] = _export_league_history(out_dir)
    record_files = _export_record_book(out_dir)
    files.update(record_files)

    if include_html:
        files.update(_export_html_report_bundle(out_dir, files))

    if not include_csv:
        for key in list(files.keys()):
            if not key.endswith("_csv"):
                continue
            path = files.pop(key)
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    summary_lines = _build_summary_lines(out_dir, files)
    summary_txt = out_dir / "report_summary.txt"
    summary_txt.write_text("\n".join(summary_lines), encoding="utf-8")
    files["summary_txt"] = summary_txt

    pdf_written = False
    if include_pdf:
        pdf_path = out_dir / "report_summary.pdf"
        pdf_written = _write_summary_pdf(pdf_path, summary_lines)
        if pdf_written:
            files["summary_pdf"] = pdf_path

    return ExportResult(output_dir=out_dir, files=files, pdf_written=pdf_written)


def _resolve_output_dir(output_dir: str | Path | None) -> Path:
    if output_dir is None:
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return get_data_dir() / "exports" / f"league_reports_{stamp}"
    candidate = Path(output_dir)
    if not candidate.is_absolute():
        candidate = resolve_app_path(candidate)
    return candidate


def _export_standings(out_dir: Path) -> Path:
    standings = load_standings()
    teams = load_teams()
    team_lookup = {t.team_id: t for t in teams}

    records: List[Dict[str, Any]] = []
    for team_id, raw in standings.items():
        record = normalize_record(raw)
        wins = int(record.get("wins", 0) or 0)
        losses = int(record.get("losses", 0) or 0)
        games = wins + losses
        pct = wins / games if games else 0.0
        streak = record.get("streak", {}) or {}
        streak_text = "--"
        if isinstance(streak, dict):
            result = streak.get("result")
            length = streak.get("length", 0)
            if result in {"W", "L"}:
                streak_text = f"{result}{int(length or 0)}"
        last10 = record.get("last10", []) or []
        if isinstance(last10, list):
            last10_text = "".join(last10)
        else:
            last10_text = ""
        team = team_lookup.get(team_id)
        team_name = ""
        division = ""
        if team is not None:
            team_name = f"{team.city} {team.name}".strip()
            division = str(getattr(team, "division", "") or "")
        records.append(
            {
                "team_id": team_id,
                "team_name": team_name or team_id,
                "division": division,
                "wins": wins,
                "losses": losses,
                "games": games,
                "pct": round(pct, 3),
                "runs_for": record.get("runs_for", 0),
                "runs_against": record.get("runs_against", 0),
                "run_diff": int(record.get("runs_for", 0) or 0) - int(record.get("runs_against", 0) or 0),
                "streak": streak_text,
                "last10": last10_text,
                "home_wins": record.get("home_wins", 0),
                "home_losses": record.get("home_losses", 0),
                "road_wins": record.get("road_wins", 0),
                "road_losses": record.get("road_losses", 0),
                "division_wins": record.get("division_wins", 0),
                "division_losses": record.get("division_losses", 0),
            }
        )

    if not records:
        for team in teams:
            record = default_record()
            records.append(
                {
                    "team_id": team.team_id,
                    "team_name": f"{team.city} {team.name}".strip() or team.team_id,
                    "division": str(getattr(team, "division", "") or ""),
                    "wins": record["wins"],
                    "losses": record["losses"],
                    "games": 0,
                    "pct": 0.0,
                    "runs_for": record["runs_for"],
                    "runs_against": record["runs_against"],
                    "run_diff": 0,
                    "streak": "--",
                    "last10": "",
                    "home_wins": record["home_wins"],
                    "home_losses": record["home_losses"],
                    "road_wins": record["road_wins"],
                    "road_losses": record["road_losses"],
                    "division_wins": record["division_wins"],
                    "division_losses": record["division_losses"],
                }
            )

    path = out_dir / "standings.csv"
    _write_csv(path, records, fieldnames=list(records[0].keys()) if records else None)
    return path


def _export_league_team_stats(out_dir: Path) -> Path:
    stats = _load_season_stats()
    team_stats = stats.get("teams", {}) if isinstance(stats, dict) else {}
    teams = load_teams()
    rows: List[Dict[str, Any]] = []
    for team in teams:
        raw = team_stats.get(team.team_id, {}) if isinstance(team_stats, dict) else {}
        row = {
            "team_id": team.team_id,
            "team_name": f"{team.city} {team.name}".strip() or team.team_id,
            "g": raw.get("g", raw.get("games", 0)),
            "w": raw.get("w", raw.get("wins", 0)),
            "l": raw.get("l", raw.get("losses", 0)),
            "r": raw.get("r", 0),
            "ra": raw.get("ra", 0),
            "der": raw.get("der", ""),
        }
        rows.append(row)
    path = out_dir / "league_stats_teams.csv"
    _write_csv(path, rows, fieldnames=_TEAM_STATS_COLS)
    return path


def _export_league_player_stats(out_dir: Path, *, batting: bool) -> Path:
    stats = _load_season_stats()
    player_stats = stats.get("players", {}) if isinstance(stats, dict) else {}
    players = list(load_players_from_csv("data/players.csv"))
    player_team = _build_player_team_map()
    rows: List[Dict[str, Any]] = []

    for player in players:
        is_pitcher = bool(getattr(player, "is_pitcher", False))
        if batting and is_pitcher:
            continue
        if not batting and not is_pitcher:
            continue
        pid = getattr(player, "player_id", "")
        stat = dict(player_stats.get(pid, {}) or {})
        stat = _normalize_player_stats(stat)
        if batting:
            stat = _ensure_batting_metrics(stat)
            columns = _BATTING_COLS
        else:
            stat = _ensure_pitching_metrics(stat)
            columns = _PITCHING_COLS

        row = {
            "player_id": pid,
            "player_name": f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip(),
            "team_id": player_team.get(pid, ""),
        }
        for key in columns:
            row[key] = stat.get(key, 0)
        rows.append(row)

    filename = "league_stats_batting.csv" if batting else "league_stats_pitching.csv"
    path = out_dir / filename
    fieldnames = ["player_id", "player_name", "team_id"] + (columns if rows else (_BATTING_COLS if batting else _PITCHING_COLS))
    _write_csv(path, rows, fieldnames=fieldnames)
    return path


def _export_league_leaders(out_dir: Path, *, batting: bool) -> Path:
    stats = _load_season_stats()
    player_stats = stats.get("players", {}) if isinstance(stats, dict) else {}
    team_stats = stats.get("teams", {}) if isinstance(stats, dict) else {}
    players = list(load_players_from_csv("data/players.csv"))
    player_team = _build_player_team_map()

    max_games = 0
    for team_data in team_stats.values() if isinstance(team_stats, dict) else []:
        try:
            max_games = max(max_games, int(team_data.get("g", team_data.get("games", 0)) or 0))
        except Exception:
            continue

    min_pa = int(round(max_games * 3.1)) if max_games else 0
    min_ip = int(round(max_games * 1.0)) if max_games else 0

    def batter_pa(stat: Dict[str, Any]) -> int:
        pa = stat.get("pa")
        if pa is None:
            pa = (
                stat.get("ab", 0)
                + stat.get("bb", 0)
                + stat.get("hbp", 0)
                + stat.get("sf", 0)
                + stat.get("ci", 0)
            )
        try:
            return int(pa or 0)
        except Exception:
            return 0

    def pitcher_ip(stat: Dict[str, Any]) -> float:
        ip = stat.get("ip")
        if ip is None:
            outs = stat.get("outs")
            if outs is not None:
                ip = outs / 3.0
        try:
            return float(ip or 0)
        except Exception:
            return 0.0

    def has_sample(stat: Dict[str, Any], key: str, *, pitcher_only: bool) -> bool:
        if pitcher_only:
            if min_ip and pitcher_ip(stat) < min_ip and key != "sv":
                return False
        else:
            if min_pa and batter_pa(stat) < min_pa:
                return False
        if key in {"era", "whip"}:
            return pitcher_ip(stat) > 0
        if key == "avg":
            try:
                return int(stat.get("ab", 0) or 0) > 0
            except Exception:
                return False
        if key == "obp":
            ab = float(stat.get("ab", 0) or 0)
            bb = float(stat.get("bb", 0) or 0)
            hbp = float(stat.get("hbp", 0) or 0)
            sf = float(stat.get("sf", 0) or 0)
            return (ab + bb + hbp + sf) > 0
        return True

    rows: List[Dict[str, Any]] = []
    categories = _BATTING_CATEGORIES if batting else _PITCHING_CATEGORIES

    for label, key, descending, pitcher_only, decimals in categories:
        ranked: List[Dict[str, Any]] = []
        for player in players:
            if bool(getattr(player, "is_pitcher", False)) != pitcher_only:
                continue
            pid = getattr(player, "player_id", "")
            stat = dict(player_stats.get(pid, {}) or {})
            stat = _normalize_player_stats(stat)
            if pitcher_only:
                stat = _ensure_pitching_metrics(stat)
            else:
                stat = _ensure_batting_metrics(stat)
            if not has_sample(stat, key, pitcher_only=pitcher_only):
                continue
            value = stat.get(key, 0)
            ranked.append(
                {
                    "player_id": pid,
                    "player_name": f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip(),
                    "team_id": player_team.get(pid, ""),
                    "value": value,
                }
            )
        ranked.sort(key=lambda item: item.get("value", 0), reverse=descending)
        for idx, entry in enumerate(ranked[:5], start=1):
            rows.append(
                {
                    "category": label,
                    "rank": idx,
                    "player_id": entry["player_id"],
                    "player_name": entry["player_name"],
                    "team_id": entry["team_id"],
                    "value": entry["value"],
                }
            )

    filename = "league_leaders_batting.csv" if batting else "league_leaders_pitching.csv"
    path = out_dir / filename
    _write_csv(
        path,
        rows,
        fieldnames=["category", "rank", "player_id", "player_name", "team_id", "value"],
    )
    return path


def _export_league_history(out_dir: Path) -> Path:
    context = SeasonContext.load()
    rows: List[Dict[str, Any]] = []
    for season in context.seasons:
        if not isinstance(season, dict):
            continue
        season_id = str(season.get("season_id", "") or "").strip()
        if not season_id:
            continue
        league_year = str(season.get("league_year", "") or "").strip()
        artifacts = _season_artifacts(season, season_id)
        awards = _load_awards(_resolve_path(artifacts.get("awards")))
        champions_path = _resolve_path(artifacts.get("champions"))
        champion, runner_up, series_result = _load_champion(champions_path, league_year)
        if not (champion and runner_up and series_result):
            playoffs_path = _resolve_path(artifacts.get("playoffs"))
            b_champ, b_runner, b_series = _load_champion_from_bracket(playoffs_path, league_year)
            champion = champion or b_champ
            runner_up = runner_up or b_runner
            series_result = series_result or b_series
        rows.append(
            {
                "season_id": season_id,
                "league_year": league_year,
                "ended_on": season.get("ended_on", ""),
                "archived_on": season.get("archived_on", ""),
                "champion": champion,
                "runner_up": runner_up,
                "series_result": series_result,
                "mvp": _award_name(awards, "MVP"),
                "cy_young": _award_name(awards, "CY_YOUNG"),
            }
        )
    path = out_dir / "league_history.csv"
    _write_csv(
        path,
        rows,
        fieldnames=[
            "season_id",
            "league_year",
            "ended_on",
            "archived_on",
            "champion",
            "runner_up",
            "series_result",
            "mvp",
            "cy_young",
        ],
    )
    return path


def _export_career_arc_analytics(out_dir: Path) -> Dict[str, Path]:
    payload = build_career_arc_analytics()
    yoy_rows = payload.get("yoy", []) if isinstance(payload, dict) else []
    trend_rows = payload.get("trends", []) if isinstance(payload, dict) else []
    era_rows = payload.get("team_eras", []) if isinstance(payload, dict) else []
    similarity_rows = payload.get("similarity", []) if isinstance(payload, dict) else []
    aging_rows = payload.get("aging_buckets", []) if isinstance(payload, dict) else []

    yoy_path = out_dir / "career_arc_yoy.csv"
    _write_csv(yoy_path, yoy_rows if isinstance(yoy_rows, list) else [], fieldnames=CAREER_ARC_YOY_FIELDS)

    trends_path = out_dir / "career_arc_trends.csv"
    _write_csv(
        trends_path,
        trend_rows if isinstance(trend_rows, list) else [],
        fieldnames=CAREER_ARC_TREND_FIELDS,
    )

    eras_path = out_dir / "career_arc_team_eras.csv"
    _write_csv(
        eras_path,
        era_rows if isinstance(era_rows, list) else [],
        fieldnames=CAREER_ARC_ERA_FIELDS,
    )

    similarity_path = out_dir / "career_arc_similarity.csv"
    _write_csv(
        similarity_path,
        similarity_rows if isinstance(similarity_rows, list) else [],
        fieldnames=CAREER_ARC_SIMILARITY_FIELDS,
    )

    aging_path = out_dir / "career_arc_aging_buckets.csv"
    _write_csv(
        aging_path,
        aging_rows if isinstance(aging_rows, list) else [],
        fieldnames=CAREER_ARC_AGING_BUCKET_FIELDS,
    )

    return {
        "career_arc_yoy_csv": yoy_path,
        "career_arc_trends_csv": trends_path,
        "career_arc_team_eras_csv": eras_path,
        "career_arc_similarity_csv": similarity_path,
        "career_arc_aging_buckets_csv": aging_path,
    }


def _export_record_book(out_dir: Path) -> Dict[str, Path]:
    book = league_record_book()
    files: Dict[str, Path] = {}
    for key, entries in book.items():
        rows: List[Dict[str, Any]] = []
        for entry in entries:
            holders = entry.get("holders", []) if isinstance(entry, dict) else []
            for holder in holders or [{}]:
                row = {
                    "label": entry.get("label", ""),
                    "stat_key": entry.get("stat_key", ""),
                    "scope": entry.get("scope", ""),
                    "category": entry.get("category", ""),
                    "value": entry.get("value", ""),
                    "value_text": entry.get("value_text", ""),
                    "holder_id": holder.get("player_id") or holder.get("team_id") or "",
                    "holder_name": holder.get("name") or holder.get("team_name") or "",
                    "season_label": holder.get("season_label") or "",
                }
                rows.append(row)
        filename = f"record_book_{key}.csv"
        path = out_dir / filename
        _write_csv(
            path,
            rows,
            fieldnames=[
                "label",
                "stat_key",
                "scope",
                "category",
                "value",
                "value_text",
                "holder_id",
                "holder_name",
                "season_label",
            ],
        )
        files[f"record_book_{key}_csv"] = path
    return files


def _build_summary_lines(out_dir: Path, files: Mapping[str, Path]) -> List[str]:
    lines = [
        "NexGen BBPro League Report Summary",
        f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z",
        f"Output Directory: {out_dir}",
        "",
        "Included Files:",
    ]
    for key, path in sorted(files.items()):
        lines.append(f"- {key}: {path.name}")
    return lines


def _export_html_report_bundle(out_dir: Path, files: Mapping[str, Path]) -> Dict[str, Path]:
    html_dir = out_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    pages: Dict[str, Path] = {}
    csv_keys = [key for key in sorted(files.keys()) if key.endswith("_csv")]
    for key in csv_keys:
        csv_path = files.get(key)
        if csv_path is None:
            continue
        page_name = f"{csv_path.stem}.html"
        page_path = html_dir / page_name
        _write_html_table_page(page_path, key, csv_path)
        pages[f"{key[:-4]}_html"] = page_path

    links = []
    for key, path in sorted(pages.items()):
        label = key.replace("_html", "").replace("_", " ").title()
        links.append(f"<li><a href=\"html/{html.escape(path.name)}\">{html.escape(label)}</a></li>")
    if not links:
        links.append("<li>No report pages generated.</li>")

    index_path = out_dir / "reports_index.html"
    index_html = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\">",
        "<title>NexGen BBPro Reports</title>",
        "<style>",
        "body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f7f8fa;color:#1f2933;}",
        "h1{margin:0 0 10px 0;} .meta{color:#52606d;margin-bottom:16px;}",
        "ul{line-height:1.7;} a{color:#0a66c2;text-decoration:none;} a:hover{text-decoration:underline;}",
        "</style></head><body>",
        "<h1>NexGen BBPro Report Bundle</h1>",
        f"<div class=\"meta\">Generated: {html.escape(datetime.utcnow().isoformat(timespec='seconds'))}Z</div>",
        "<p>Open any section below. HTML is the default report surface.</p>",
        "<ul>",
        *links,
        "</ul>",
        "</body></html>",
    ]
    index_path.write_text("\n".join(index_html), encoding="utf-8")
    pages["reports_index_html"] = index_path
    return pages


def _write_html_table_page(path: Path, key: str, csv_path: Path) -> None:
    rows: List[Dict[str, str]] = []
    fieldnames: List[str] = []
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            for row in reader:
                rows.append({str(k): str(v or "") for k, v in (row or {}).items()})
    except OSError:
        fieldnames = []
        rows = []

    title = key.replace("_csv", "").replace("_", " ").title()
    header_cells = "".join(f"<th>{html.escape(name)}</th>" for name in fieldnames)
    body_rows: List[str] = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(row.get(name, '')))}</td>" for name in fieldnames)
        body_rows.append(f"<tr>{cells}</tr>")
    if not body_rows:
        body_rows.append(
            "<tr><td colspan=\"100%\">No rows available for this section.</td></tr>"
        )

    payload = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\">",
        f"<title>{html.escape(title)}</title>",
        "<style>",
        "body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f7f8fa;color:#1f2933;}",
        "a{color:#0a66c2;text-decoration:none;} a:hover{text-decoration:underline;}",
        "table{border-collapse:collapse;width:100%;background:#fff;font-size:13px;}",
        "th,td{border:1px solid #d9e2ec;padding:6px 8px;text-align:left;vertical-align:top;}",
        "th{background:#f0f4f8;position:sticky;top:0;} .meta{margin-bottom:12px;color:#52606d;}",
        "</style></head><body>",
        "<p><a href=\"../reports_index.html\">Back to report index</a></p>",
        f"<h1>{html.escape(title)}</h1>",
        f"<div class=\"meta\">Source CSV: {html.escape(csv_path.name)} | Rows: {len(rows)}</div>",
        "<table>",
        f"<thead><tr>{header_cells}</tr></thead>",
        "<tbody>",
        *body_rows,
        "</tbody></table>",
        "</body></html>",
    ]
    path.write_text("\n".join(payload), encoding="utf-8")


def _write_summary_pdf(path: Path, lines: Iterable[str]) -> bool:
    """PDF export was provided by ``QTextDocument``/``QPrinter`` from the
    retired PyQt UI. The shipped sidecar excludes PyQt6, so this has
    been a no-op in every installer for a while — make that explicit
    rather than carrying the dead import. ``report_summary.txt`` still
    captures the same content for callers that need a portable summary.
    """

    return False


def _write_csv(path: Path, rows: List[Dict[str, Any]], *, fieldnames: List[str] | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _build_player_team_map() -> Dict[str, str]:
    data_dir = get_data_dir()
    roster_dir = data_dir / "rosters"
    player_team: Dict[str, str] = {}
    if not roster_dir.exists():
        return player_team
    for roster_file in roster_dir.glob("*.csv"):
        if roster_file.name.endswith("_pitching.csv"):
            continue
        team_id = roster_file.stem
        try:
            roster = load_roster(team_id, roster_dir=roster_dir)
        except Exception:
            continue
        for pid in list(roster.act) + list(roster.aaa) + list(roster.low) + list(roster.dl) + list(roster.ir):
            clean = str(pid or "").strip()
            if clean:
                player_team[clean] = team_id
    return player_team


def _normalize_player_stats(data: Dict[str, Any]) -> Dict[str, Any]:
    stats = dict(data or {})
    if "b2" in stats and "2b" not in stats:
        stats["2b"] = stats.get("b2", 0)
    if "b3" in stats and "3b" not in stats:
        stats["3b"] = stats.get("b3", 0)
    stats.setdefault("w", stats.get("wins", stats.get("w", 0)))
    stats.setdefault("l", stats.get("losses", stats.get("l", 0)))
    return stats


def _ensure_batting_metrics(stats: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(stats)
    ab = float(data.get("ab", 0) or 0)
    h = float(data.get("h", 0) or 0)
    doubles = float(data.get("2b", data.get("b2", 0)) or 0)
    triples = float(data.get("3b", data.get("b3", 0)) or 0)
    hr = float(data.get("hr", 0) or 0)
    singles = max(h - doubles - triples - hr, 0)
    walks = float(data.get("bb", 0) or 0)
    hbp = float(data.get("hbp", 0) or 0)
    sf = float(data.get("sf", 0) or 0)
    total_bases = singles + 2 * doubles + 3 * triples + 4 * hr
    data["avg"] = h / ab if ab else 0.0
    denom_obp = ab + walks + hbp + sf
    data["obp"] = (h + walks + hbp) / denom_obp if denom_obp else 0.0
    data["slg"] = total_bases / ab if ab else 0.0
    return data


def _ensure_pitching_metrics(stats: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(stats)
    ip = data.get("ip")
    if ip is None:
        outs = data.get("outs")
        if outs is not None:
            ip = float(outs) / 3.0
    try:
        ip = float(ip or 0.0)
    except Exception:
        ip = 0.0
    data["ip"] = ip
    er = float(data.get("er", 0) or 0)
    bb = float(data.get("bb", 0) or 0)
    h = float(data.get("h", 0) or 0)
    data["era"] = (er * 9) / ip if ip else 0.0
    data["whip"] = (bb + h) / ip if ip else 0.0
    data.setdefault("w", data.get("wins", data.get("w", 0)))
    data.setdefault("l", data.get("losses", data.get("l", 0)))
    return data


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def _resolve_path(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = resolve_app_path(candidate)
    return candidate


def _season_artifacts(season: Dict[str, Any], season_id: str) -> Dict[str, str]:
    artifacts = season.get("artifacts")
    if isinstance(artifacts, dict) and artifacts:
        return {str(key): str(value) for key, value in artifacts.items() if value}
    meta_path = get_data_dir() / "careers" / season_id / "metadata.json"
    payload = _read_json(meta_path, {})
    meta_artifacts = payload.get("artifacts", {})
    if isinstance(meta_artifacts, dict) and meta_artifacts:
        return {str(key): str(value) for key, value in meta_artifacts.items() if value}
    return {}


def _load_awards(path: Path | None) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = _read_json(path, {})
    awards = payload.get("awards", {})
    return awards if isinstance(awards, dict) else {}


def _award_name(awards: Dict[str, Any], key: str) -> str:
    entry = awards.get(key, {})
    if not isinstance(entry, dict):
        return ""
    name = str(entry.get("player_name") or "").strip()
    if not name:
        name = str(entry.get("player_id") or "").strip()
    return name


def _load_champion(path: Path | None, league_year: str) -> tuple[str, str, str]:
    if not league_year or path is None or not path.exists():
        return "", "", ""
    target = league_year.strip()
    selected = None
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not row:
                    continue
                if target and str(row.get("year", "")).strip() != target:
                    continue
                selected = row
    except OSError:
        return "", "", ""
    if not selected:
        return "", "", ""
    return (
        str(selected.get("champion", "") or "").strip(),
        str(selected.get("runner_up", "") or "").strip(),
        str(selected.get("series_result", "") or "").strip(),
    )


def _final_round_from_bracket(bracket: object) -> object | None:
    try:
        rounds = list(getattr(bracket, "rounds", []) or [])
    except Exception:
        rounds = []
    if not rounds:
        return None

    def _is_final(name: str) -> bool:
        tokens = [
            t.lower()
            for t in str(name or "").replace("-", " ").replace("_", " ").split()
            if t
        ]
        finals = {"ws", "world", "worlds", "final", "finals", "championship"}
        return any(t in finals for t in tokens)

    finals = [r for r in rounds if _is_final(getattr(r, "name", ""))]
    if finals:
        return finals[-1]
    return rounds[-1]


def _series_result_from_bracket(bracket: object) -> str:
    try:
        champ = getattr(bracket, "champion", None)
        if not champ:
            return ""
        final_round = _final_round_from_bracket(bracket)
        if final_round is None:
            return ""
        matchups = list(getattr(final_round, "matchups", []) or [])
        if not matchups:
            return ""
        matchup = matchups[0]
        wins_c = 0
        wins_o = 0
        for game in list(getattr(matchup, "games", []) or []):
            res = str(getattr(game, "result", "") or "")
            if "-" not in res:
                continue
            try:
                home_score, away_score = map(int, res.split("-", 1))
            except Exception:
                continue
            if home_score > away_score:
                winner = getattr(game, "home", "")
            elif away_score > home_score:
                winner = getattr(game, "away", "")
            else:
                continue
            if winner == champ:
                wins_c += 1
            else:
                wins_o += 1
        return f"{wins_c}-{wins_o}" if (wins_c or wins_o) else ""
    except Exception:
        return ""


def _load_champion_from_bracket(path: Path | None, league_year: str) -> tuple[str, str, str]:
    if not league_year or path is None or not path.exists():
        return "", "", ""
    try:
        from playbalance.playoffs import load_bracket
    except Exception:
        return "", "", ""
    try:
        bracket = load_bracket(path=path)
    except Exception:
        bracket = None
    if bracket is None:
        return "", "", ""
    try:
        bracket_year = int(getattr(bracket, "year", 0) or 0)
    except Exception:
        bracket_year = 0
    if bracket_year and str(bracket_year) != league_year.strip():
        return "", "", ""

    champion = str(getattr(bracket, "champion", "") or "").strip()
    runner_up = str(getattr(bracket, "runner_up", "") or "").strip()
    series_result = _series_result_from_bracket(bracket)
    return champion, runner_up, series_result


__all__ = ["ExportResult", "export_reports"]
