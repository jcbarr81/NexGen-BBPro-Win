from __future__ import annotations

"""League Almanac export helpers."""

import csv
from dataclasses import dataclass
from datetime import date, datetime
import html
from html.parser import HTMLParser
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from playbalance.season_context import SeasonContext
from services.record_book import league_record_book, player_record_entries
from services.standings_repository import load_standings
from utils.path_utils import get_data_dir, resolve_app_path
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.team_loader import load_teams


@dataclass
class AlmanacExportResult:
    output_dir: Path
    index_html: Path
    files: Dict[str, Path]
    season_ids: List[str]


@dataclass
class AlmanacValidationResult:
    missing_files: List[str]
    broken_links: List[str]
    scanned_pages: int

    @property
    def is_valid(self) -> bool:
        return not self.missing_files and not self.broken_links

    @property
    def issues(self) -> List[str]:
        return [*self.missing_files, *self.broken_links]


class _HrefCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        if tag not in {"a", "link"}:
            return
        for key, value in attrs:
            if key == "href" and value:
                self.hrefs.append(value)


def export_almanac(output_dir: str | Path | None = None) -> AlmanacExportResult:
    """Export a baseball-reference style multi-page league almanac."""

    out_dir = _resolve_output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    almanac_dir = out_dir / "almanac"
    seasons_dir = almanac_dir / "seasons"
    teams_dir = almanac_dir / "teams"
    players_dir = almanac_dir / "players"
    awards_dir = almanac_dir / "awards"
    postseason_dir = almanac_dir / "postseason"
    leaders_dir = almanac_dir / "leaders"
    transactions_dir = almanac_dir / "transactions"
    finance_dir = almanac_dir / "finance"
    records_dir = almanac_dir / "records"
    assets_dir = almanac_dir / "assets"
    for target in (
        almanac_dir,
        seasons_dir,
        teams_dir,
        players_dir,
        awards_dir,
        postseason_dir,
        leaders_dir,
        transactions_dir,
        finance_dir,
        records_dir,
        assets_dir,
    ):
        target.mkdir(parents=True, exist_ok=True)

    css_path = assets_dir / "almanac.css"
    css_path.write_text(_base_css(), encoding="utf-8")

    context = SeasonContext.load()
    season_entries = _build_season_entries(context)
    team_lookup = _team_name_lookup()
    current_standings_rows = _standings_rows(
        load_standings(normalize=True),
        team_lookup=team_lookup,
    )
    season_payloads = _build_season_payloads(
        season_entries=season_entries,
        team_lookup=team_lookup,
        current_standings_rows=current_standings_rows,
    )
    team_history_by_team = _build_team_history_by_team(season_payloads)
    teams_rows = _team_rows(team_history_by_team=team_history_by_team)
    current_season_id = _current_season_id(season_entries)
    player_pages = _build_player_pages(
        team_lookup=team_lookup,
        current_season_id=current_season_id,
    )
    players_rows = player_pages["rows"]
    awards_rows = _award_rows(season_payloads)
    postseason_rows = _postseason_rows(season_payloads)
    leader_sections = _leader_sections(team_lookup=team_lookup)
    transaction_rows = _transaction_history_rows(season_payloads, current_season_id=current_season_id)
    finance_sections = _finance_history_sections(
        season_payloads=season_payloads,
        current_season_id=current_season_id,
        team_lookup=team_lookup,
    )
    record_rows = _record_rows()

    files: Dict[str, Path] = {"css": css_path}
    _write_team_pages(
        teams_dir=teams_dir,
        teams_rows=teams_rows,
        team_history_by_team=team_history_by_team,
        files=files,
    )
    season_pages = _write_season_pages(seasons_dir=seasons_dir, season_payloads=season_payloads, files=files)
    season_index = seasons_dir / "index.html"
    season_index.write_text(
        _season_index_html(season_entries, season_pages),
        encoding="utf-8",
    )
    files["seasons_index_html"] = season_index

    teams_index = teams_dir / "index.html"
    teams_index.write_text(_teams_html(teams_rows), encoding="utf-8")
    files["teams_index_html"] = teams_index

    _write_player_pages(players_dir=players_dir, player_pages=player_pages["pages"], files=files)
    players_index = players_dir / "index.html"
    players_index.write_text(_players_html(players_rows), encoding="utf-8")
    files["players_index_html"] = players_index

    awards_index = awards_dir / "index.html"
    awards_index.write_text(_awards_html(awards_rows), encoding="utf-8")
    files["awards_index_html"] = awards_index

    postseason_index = postseason_dir / "index.html"
    postseason_index.write_text(_postseason_html(postseason_rows), encoding="utf-8")
    files["postseason_index_html"] = postseason_index

    leaders_index = leaders_dir / "index.html"
    leaders_index.write_text(_leaders_html(leader_sections), encoding="utf-8")
    files["leaders_index_html"] = leaders_index

    transactions_index = transactions_dir / "index.html"
    transactions_index.write_text(_transactions_html(transaction_rows), encoding="utf-8")
    files["transactions_index_html"] = transactions_index

    finance_index = finance_dir / "index.html"
    finance_index.write_text(_finance_html(finance_sections), encoding="utf-8")
    files["finance_index_html"] = finance_index

    records_index = records_dir / "index.html"
    records_index.write_text(_records_html(record_rows), encoding="utf-8")
    files["records_index_html"] = records_index

    index_path = almanac_dir / "index.html"
    index_path.write_text(
        _landing_html(
            season_entries=season_entries,
            current_standings_rows=current_standings_rows,
            teams_count=len(teams_rows),
            players_count=len(players_rows),
        ),
        encoding="utf-8",
    )
    files["index_html"] = index_path
    files["almanac_dir"] = almanac_dir

    return AlmanacExportResult(
        output_dir=out_dir,
        index_html=index_path,
        files=files,
        season_ids=[entry["season_id"] for entry in season_entries],
    )


def validate_almanac_export(result: AlmanacExportResult) -> AlmanacValidationResult:
    """Validate required Almanac outputs and local link integrity."""

    missing_files: List[str] = []
    broken_links: List[str] = []
    required_files = {
        "index_html": result.index_html,
        "css": result.files.get("css"),
        "seasons_index_html": result.files.get("seasons_index_html"),
        "teams_index_html": result.files.get("teams_index_html"),
        "players_index_html": result.files.get("players_index_html"),
        "awards_index_html": result.files.get("awards_index_html"),
        "postseason_index_html": result.files.get("postseason_index_html"),
        "leaders_index_html": result.files.get("leaders_index_html"),
        "transactions_index_html": result.files.get("transactions_index_html"),
        "finance_index_html": result.files.get("finance_index_html"),
        "records_index_html": result.files.get("records_index_html"),
    }
    for season_id in result.season_ids:
        required_files[f"season_{season_id}_html"] = result.files.get(
            f"season_{season_id}_html"
        )

    for key, path in required_files.items():
        if path is None or not Path(path).exists():
            missing_files.append(key)

    almanac_dir = result.files.get("almanac_dir")
    if almanac_dir is None:
        almanac_dir = result.index_html.parent
    html_pages = sorted(Path(almanac_dir).rglob("*.html"))
    for page in html_pages:
        collector = _HrefCollector()
        try:
            collector.feed(page.read_text(encoding="utf-8"))
        except OSError:
            broken_links.append(f"{page.name}: unreadable")
            continue
        for href in collector.hrefs:
            target = _resolve_local_export_href(page, href)
            if target is None:
                continue
            if not target.exists():
                broken_links.append(
                    f"{page.relative_to(almanac_dir).as_posix()} -> {href}"
                )

    return AlmanacValidationResult(
        missing_files=sorted(set(missing_files)),
        broken_links=sorted(set(broken_links)),
        scanned_pages=len(html_pages),
    )


def _resolve_output_dir(output_dir: str | Path | None) -> Path:
    if output_dir is None:
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return get_data_dir() / "exports" / f"league_almanac_{stamp}"
    candidate = Path(output_dir)
    if not candidate.is_absolute():
        candidate = resolve_app_path(candidate)
    return candidate


def _current_season_id(season_entries: List[Dict[str, Any]]) -> str:
    for entry in season_entries:
        if str(entry.get("status") or "") == "current":
            return str(entry.get("season_id") or "")
    return ""


def _base_css() -> str:
    return """
:root{
  --paper:#f4efe2;
  --paper-deep:#ebe1c7;
  --ink:#1d2835;
  --muted:#5b6673;
  --line:#cdbf9f;
  --line-strong:#9f8c63;
  --panel:#fffdf8;
  --panel-alt:#f9f5ea;
  --accent:#173f5f;
  --accent-soft:#e2ebf2;
}
*{box-sizing:border-box;}
html{background:linear-gradient(180deg,#f7f2e6 0%,#efe6d0 100%);}
body{
  margin:0;
  padding:24px;
  font-family:Georgia,"Times New Roman",serif;
  color:var(--ink);
  background:
    radial-gradient(circle at top left,rgba(255,255,255,0.6),transparent 22%),
    linear-gradient(180deg,#f7f2e6 0%,#efe6d0 100%);
  line-height:1.45;
}
a{color:var(--accent);text-decoration:none;}
a:hover{text-decoration:underline;}
h1,h2,h3{margin:0 0 10px 0;line-height:1.15;}
h1{font-size:2rem;letter-spacing:0.02em;}
h2{
  font-size:1.05rem;
  text-transform:uppercase;
  letter-spacing:0.08em;
  color:#4b3d1f;
}
h3{font-size:0.95rem;color:#4b3d1f;}
ul{margin:0;padding-left:18px;}
.nav{
  display:flex;
  gap:8px;
  flex-wrap:wrap;
  margin:0 0 18px 0;
  padding:12px 14px;
  background:rgba(255,253,248,0.95);
  border:1px solid var(--line);
  border-radius:12px;
  box-shadow:0 8px 20px rgba(76,63,39,0.08);
}
.nav a{
  display:inline-flex;
  align-items:center;
  min-height:32px;
  padding:0 12px;
  border-radius:999px;
  border:1px solid transparent;
  background:var(--accent-soft);
  font-size:0.92rem;
}
.nav a:hover{
  border-color:var(--line-strong);
  text-decoration:none;
}
.meta{
  color:var(--muted);
  margin:0 0 14px 0;
  font-size:0.95rem;
}
.small{font-size:12px;color:var(--muted);}
.grid{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
  gap:12px;
}
.toc-grid{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  gap:12px;
}
.panel{
  background:var(--panel);
  border:1px solid var(--line);
  border-top:4px solid var(--line-strong);
  border-radius:12px;
  padding:14px 16px;
  margin:0 0 14px 0;
  box-shadow:0 10px 24px rgba(60,47,26,0.08);
}
.panel p{margin:0;}
.stat-card{
  background:linear-gradient(180deg,var(--panel) 0%,var(--panel-alt) 100%);
}
.stat-label{
  margin:0 0 6px 0;
  font-size:0.78rem;
  text-transform:uppercase;
  letter-spacing:0.12em;
  color:var(--muted);
}
.stat-value{
  margin:0;
  font-size:1.8rem;
  font-weight:bold;
  color:#2a2315;
}
.stat-note{
  margin-top:6px;
  color:var(--muted);
  font-size:0.85rem;
}
.toc-card{
  display:block;
  color:inherit;
}
.toc-card:hover{
  text-decoration:none;
  border-color:var(--accent);
  transform:translateY(-1px);
}
.toc-card .toc-title{
  margin:0 0 8px 0;
  font-size:1rem;
  color:#2a2315;
}
.toc-card .toc-copy{
  margin:0;
  color:var(--muted);
  font-size:0.92rem;
}
.table-wrap{
  overflow-x:auto;
  border:1px solid var(--line);
  border-radius:10px;
  background:#fff;
}
table{
  width:100%;
  border-collapse:collapse;
  background:#fff;
  font-size:0.94rem;
}
th,td{
  border-bottom:1px solid #ddd2b8;
  padding:8px 10px;
  text-align:left;
  vertical-align:top;
}
thead th{
  position:sticky;
  top:0;
  z-index:1;
  background:linear-gradient(180deg,#f2e9d6 0%,#e4d5b5 100%);
  border-bottom:2px solid var(--line-strong);
  font-size:0.8rem;
  text-transform:uppercase;
  letter-spacing:0.08em;
  color:#483919;
}
tbody tr:nth-child(even){background:#fcf9f1;}
tbody tr:hover{background:#f2f7fb;}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;}
.season-links{
  display:flex;
  gap:14px;
  flex-wrap:wrap;
}
@media (max-width: 720px){
  body{padding:14px;}
  h1{font-size:1.6rem;}
  .nav{padding:10px;}
  th,td{padding:7px 8px;}
}
@media print{
  html,body{background:#fff;}
  body{padding:0;color:#000;}
  .nav{display:none;}
  .panel{
    box-shadow:none;
    border:1px solid #888;
    break-inside:avoid;
    page-break-inside:avoid;
  }
  .table-wrap{
    overflow:visible;
    border-color:#888;
  }
  a{color:#000;text-decoration:none;}
}
""".strip()


def _season_sort_key(entry: Mapping[str, Any]) -> tuple[int, int]:
    year = _safe_int(entry.get("league_year"), fallback=0)
    seq = _safe_int(entry.get("sequence"), fallback=0)
    return (year, seq)


def _build_season_entries(context: SeasonContext) -> List[Dict[str, Any]]:
    seasons: List[Dict[str, Any]] = []
    for raw in list(context.seasons):
        if not isinstance(raw, Mapping):
            continue
        season_id = str(raw.get("season_id") or "").strip()
        if not season_id:
            continue
        seasons.append(
            {
                "season_id": season_id,
                "league_year": _safe_int(raw.get("league_year"), fallback=0),
                "sequence": _safe_int(raw.get("sequence"), fallback=0),
                "status": "archived",
                "started_on": str(raw.get("started_on") or ""),
                "ended_on": str(raw.get("ended_on") or ""),
                "archived_on": str(raw.get("archived_on") or ""),
                "artifacts": _season_artifacts(raw, season_id),
            }
        )
    current = context.current if isinstance(context.current, Mapping) else {}
    current_id = str(current.get("season_id") or "").strip()
    if current_id:
        seasons.append(
            {
                "season_id": current_id,
                "league_year": _safe_int(current.get("league_year"), fallback=0),
                "sequence": _safe_int(current.get("sequence"), fallback=0),
                "status": "current",
                "started_on": str(current.get("started_on") or ""),
                "ended_on": "",
                "archived_on": "",
                "artifacts": _season_artifacts(current, current_id),
            }
        )
    seasons.sort(key=_season_sort_key)
    return seasons


def _season_artifacts(season: Mapping[str, Any], season_id: str) -> Dict[str, str]:
    raw_artifacts = season.get("artifacts")
    if isinstance(raw_artifacts, Mapping) and raw_artifacts:
        return {
            str(key): str(value)
            for key, value in raw_artifacts.items()
            if str(value or "").strip()
        }
    metadata_path = get_data_dir() / "careers" / season_id / "metadata.json"
    payload = _read_json(metadata_path, default={})
    metadata_artifacts = payload.get("artifacts", {})
    if isinstance(metadata_artifacts, Mapping):
        return {
            str(key): str(value)
            for key, value in metadata_artifacts.items()
            if str(value or "").strip()
        }
    return {}


def _resolve_maybe_relative(path_value: str | None) -> Path | None:
    token = str(path_value or "").strip()
    if not token:
        return None
    candidate = Path(token)
    if not candidate.is_absolute():
        candidate = resolve_app_path(candidate)
    return candidate


def _team_name_lookup() -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for team in load_teams():
        team_id = str(getattr(team, "team_id", "") or "").strip()
        if not team_id:
            continue
        lookup[team_id] = f"{getattr(team, 'city', '')} {getattr(team, 'name', '')}".strip()
    return lookup


def _standings_rows(
    standings: Mapping[str, Mapping[str, Any]],
    *,
    team_lookup: Mapping[str, str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for team_id, payload in standings.items():
        wins = _safe_int(payload.get("wins"), fallback=0)
        losses = _safe_int(payload.get("losses"), fallback=0)
        games = wins + losses
        pct = round((wins / games), 3) if games else 0.0
        rows.append(
            {
                "team_id": str(team_id),
                "team_name": str(team_lookup.get(str(team_id), str(team_id))),
                "wins": wins,
                "losses": losses,
                "pct": pct,
                "runs_for": _safe_int(payload.get("runs_for"), fallback=0),
                "runs_against": _safe_int(payload.get("runs_against"), fallback=0),
            }
        )
    rows.sort(
        key=lambda item: (-_safe_int(item.get("wins"), fallback=0), item["team_id"])
    )
    return rows


def _season_standings_rows(
    entry: Mapping[str, Any],
    *,
    team_lookup: Mapping[str, str],
    current_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if str(entry.get("status") or "") == "current":
        return list(current_rows)
    artifacts = entry.get("artifacts", {})
    if not isinstance(artifacts, Mapping):
        return []
    standings_path = _resolve_maybe_relative(str(artifacts.get("standings") or ""))
    if standings_path is None or not standings_path.exists():
        return []
    standings = load_standings(base_path=standings_path, normalize=True)
    return _standings_rows(standings, team_lookup=team_lookup)


def _build_season_payloads(
    *,
    season_entries: List[Dict[str, Any]],
    team_lookup: Mapping[str, str],
    current_standings_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for idx, entry in enumerate(season_entries):
        season_id = str(entry["season_id"])
        payloads.append(
            {
                "entry": entry,
                "season_id": season_id,
                "prev_id": str(season_entries[idx - 1]["season_id"]) if idx > 0 else "",
                "next_id": (
                    str(season_entries[idx + 1]["season_id"])
                    if idx + 1 < len(season_entries)
                    else ""
                ),
                "standings_rows": _season_standings_rows(
                    entry,
                    team_lookup=team_lookup,
                    current_rows=current_standings_rows,
                ),
                "awards": _season_awards(entry),
                "postseason": _season_postseason_summary(entry, team_lookup=team_lookup),
            }
        )
    return payloads


def _build_team_history_by_team(
    season_payloads: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    team_history: Dict[str, List[Dict[str, Any]]] = {}
    for payload in season_payloads:
        entry = payload.get("entry", {})
        if not isinstance(entry, Mapping):
            continue
        season_id = str(payload.get("season_id") or entry.get("season_id") or "")
        league_year = _safe_int(entry.get("league_year"), fallback=0)
        status = str(entry.get("status") or "")
        postseason = payload.get("postseason", {})
        champion_team_id = ""
        if isinstance(postseason, Mapping):
            champion_team_id = str(postseason.get("champion_team_id") or "")
        for row in payload.get("standings_rows", []) or []:
            if not isinstance(row, Mapping):
                continue
            team_id = str(row.get("team_id") or "").strip()
            if not team_id:
                continue
            team_history.setdefault(team_id, []).append(
                {
                    "season_id": season_id,
                    "league_year": league_year,
                    "status": status,
                    "team_id": team_id,
                    "team_name": str(row.get("team_name") or team_id),
                    "wins": _safe_int(row.get("wins"), fallback=0),
                    "losses": _safe_int(row.get("losses"), fallback=0),
                    "pct": row.get("pct", 0.0),
                    "runs_for": _safe_int(row.get("runs_for"), fallback=0),
                    "runs_against": _safe_int(row.get("runs_against"), fallback=0),
                    "champion": "Yes" if champion_team_id and team_id == champion_team_id else "",
                }
            )
    for rows in team_history.values():
        rows.sort(key=lambda item: (_safe_int(item.get("league_year"), fallback=0), str(item.get("season_id") or "")))
    return team_history


def _team_rows(
    *,
    team_history_by_team: Mapping[str, List[Dict[str, Any]]],
) -> List[Dict[str, str]]:
    current_rows: Dict[str, Dict[str, str]] = {}
    for team in load_teams():
        team_id = str(getattr(team, "team_id", "") or "").strip()
        if not team_id:
            continue
        history_rows = list(team_history_by_team.get(team_id, []))
        total_wins, total_losses, championships, best_season = _summarize_team_history(history_rows)
        current_rows[team_id] = {
            "team_id": team_id,
            "team_name": f"{getattr(team, 'city', '')} {getattr(team, 'name', '')}".strip() or team_id,
            "abbreviation": str(getattr(team, "abbreviation", "") or ""),
            "division": str(getattr(team, "division", "") or ""),
            "owner_id": str(getattr(team, "owner_id", "") or ""),
            "stadium": str(getattr(team, "stadium", "") or ""),
            "seasons": str(len(history_rows)),
            "total_wins": str(total_wins),
            "total_losses": str(total_losses),
            "championships": str(championships),
            "best_season": best_season,
        }

    rows: List[Dict[str, str]] = []
    team_ids = set(current_rows.keys()) | set(str(team_id) for team_id in team_history_by_team.keys())
    for team_id in team_ids:
        row = current_rows.get(team_id)
        if row is None:
            history_rows = list(team_history_by_team.get(team_id, []))
            total_wins, total_losses, championships, best_season = _summarize_team_history(history_rows)
            row = {
                "team_id": str(team_id),
                "team_name": history_rows[-1]["team_name"] if history_rows else str(team_id),
                "abbreviation": "",
                "division": "",
                "owner_id": "",
                "stadium": "",
                "seasons": str(len(history_rows)),
                "total_wins": str(total_wins),
                "total_losses": str(total_losses),
                "championships": str(championships),
                "best_season": best_season,
            }
        linked = dict(row)
        linked["team_name"] = (
            f"<a href=\"{html.escape(str(row['team_id']))}.html\">"
            f"{html.escape(str(row['team_name']))}</a>"
        )
        rows.append(linked)
    rows.sort(key=lambda item: (item["division"], item["team_name"], item["team_id"]))
    return rows


def _summarize_team_history(
    history_rows: List[Dict[str, Any]],
) -> tuple[int, int, int, str]:
    total_wins = sum(_safe_int(row.get("wins"), fallback=0) for row in history_rows)
    total_losses = sum(_safe_int(row.get("losses"), fallback=0) for row in history_rows)
    championships = sum(1 for row in history_rows if str(row.get("champion") or "").strip())
    best_row = max(
        history_rows,
        key=lambda row: (
            _safe_float(row.get("pct"), fallback=0.0),
            _safe_int(row.get("wins"), fallback=0),
            _safe_int(row.get("league_year"), fallback=0),
        ),
        default=None,
    )
    if isinstance(best_row, Mapping):
        best_season = (
            f"{_safe_int(best_row.get('league_year'), fallback=0)} "
            f"({_safe_int(best_row.get('wins'), fallback=0)}-"
            f"{_safe_int(best_row.get('losses'), fallback=0)})"
        )
    else:
        best_season = ""
    return total_wins, total_losses, championships, best_season


def _player_team_map() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    roster_dir = get_data_dir() / "rosters"
    for team in load_teams():
        team_id = str(getattr(team, "team_id", "") or "").strip()
        if not team_id:
            continue
        try:
            roster = load_roster(team_id, roster_dir=roster_dir)
        except Exception:
            continue
        for pid in (
            list(getattr(roster, "act", []) or [])
            + list(getattr(roster, "aaa", []) or [])
            + list(getattr(roster, "low", []) or [])
            + list(getattr(roster, "dl", []) or [])
            + list(getattr(roster, "ir", []) or [])
        ):
            player_id = str(pid or "").strip()
            if player_id:
                mapping[player_id] = team_id
    return mapping


def _player_rows(*, team_lookup: Mapping[str, str]) -> List[Dict[str, str]]:
    return _build_player_pages(
        team_lookup=team_lookup,
        current_season_id="",
    )["rows"]


def _build_player_pages(
    *,
    team_lookup: Mapping[str, str],
    current_season_id: str,
) -> Dict[str, Any]:
    team_map = _player_team_map()
    rows: List[Dict[str, str]] = []
    pages: Dict[str, Dict[str, Any]] = {}
    for player in load_players_from_csv("data/players.csv"):
        player_id = str(getattr(player, "player_id", "") or "").strip()
        if not player_id:
            continue
        name = (
            f"{getattr(player, 'first_name', '')} "
            f"{getattr(player, 'last_name', '')}"
        ).strip() or player_id
        team_id = team_map.get(player_id, "")
        team_name = str(team_lookup.get(team_id, team_id))
        is_pitcher = bool(getattr(player, "is_pitcher", False))
        season_rows = _player_season_rows(
            player=player,
            current_season_id=current_season_id,
            current_team_id=team_id,
            team_lookup=team_lookup,
        )
        career_totals = _player_career_totals(
            player=player,
            season_rows=season_rows,
            include_current=bool(current_season_id),
        )
        record_rows = _player_record_rows(player_id)
        pages[player_id] = {
            "player_id": player_id,
            "name": name,
            "team_id": team_id,
            "team_name": team_name,
            "primary_position": str(getattr(player, "primary_position", "") or ""),
            "is_pitcher": is_pitcher,
            "bats": str(getattr(player, "bats", "") or ""),
            "birthdate": str(getattr(player, "birthdate", "") or ""),
            "age": _age_from_birthdate(str(getattr(player, "birthdate", "") or "")),
            "season_rows": season_rows,
            "career_totals": career_totals,
            "record_rows": record_rows,
        }
        linked_name = (
            f"<a href=\"{html.escape(player_id)}.html\">{html.escape(name)}</a>"
        )
        linked_team_name = html.escape(team_name)
        if team_id:
            linked_team_name = (
                f"<a href=\"../teams/{html.escape(team_id)}.html\">"
                f"{html.escape(team_name)}</a>"
            )
        rows.append(
            {
                "player_id": player_id,
                "name": linked_name,
                "team_id": team_id,
                "team_name": linked_team_name,
                "primary_position": str(getattr(player, "primary_position", "") or ""),
                "is_pitcher": "Yes" if is_pitcher else "No",
                "seasons": str(len(season_rows)),
            }
        )
    rows.sort(key=lambda item: (_strip_tags(item["name"]), item["player_id"]))
    return {"rows": rows, "pages": pages}


def _player_season_rows(
    *,
    player: Any,
    current_season_id: str,
    current_team_id: str,
    team_lookup: Mapping[str, str],
) -> List[Dict[str, Any]]:
    season_rows: List[Dict[str, Any]] = []
    raw_history = getattr(player, "career_history", {}) or {}
    if isinstance(raw_history, Mapping):
        for season_id, stats in raw_history.items():
            if not isinstance(stats, Mapping):
                continue
            season_rows.append(
                _normalize_player_season_row(
                    season_id=str(season_id),
                    stats=stats,
                    fallback_team_id="",
                    team_lookup=team_lookup,
                )
            )
    current_stats = getattr(player, "season_stats", None)
    if current_season_id and isinstance(current_stats, Mapping):
        season_rows = [row for row in season_rows if str(row.get("season_id") or "") != current_season_id]
        season_rows.append(
            _normalize_player_season_row(
                season_id=current_season_id,
                stats=current_stats,
                fallback_team_id=current_team_id,
                team_lookup=team_lookup,
            )
        )
    season_rows.sort(
        key=lambda row: (
            _safe_int(row.get("league_year"), fallback=0),
            str(row.get("season_id") or ""),
        )
    )
    return season_rows


def _normalize_player_season_row(
    *,
    season_id: str,
    stats: Mapping[str, Any],
    fallback_team_id: str,
    team_lookup: Mapping[str, str],
) -> Dict[str, Any]:
    row = dict(stats)
    team_id = str(
        row.get("team_id")
        or row.get("team")
        or row.get("team_abbr")
        or fallback_team_id
        or ""
    ).strip()
    outs = _safe_float(row.get("outs"), fallback=0.0)
    ip = _safe_float(row.get("ip"), fallback=0.0)
    if ip <= 0.0 and outs > 0.0:
        ip = outs / 3.0
    ab = _safe_float(row.get("ab"), fallback=0.0)
    hits = _safe_float(row.get("h"), fallback=0.0)
    doubles = _safe_float(row.get("2b", row.get("b2")), fallback=0.0)
    triples = _safe_float(row.get("3b", row.get("b3")), fallback=0.0)
    home_runs = _safe_float(row.get("hr"), fallback=0.0)
    walks = _safe_float(row.get("bb"), fallback=0.0)
    hbp = _safe_float(row.get("hbp"), fallback=0.0)
    sf = _safe_float(row.get("sf"), fallback=0.0)
    er = _safe_float(row.get("er"), fallback=0.0)
    strikeouts = _safe_float(row.get("so", row.get("k")), fallback=0.0)
    avg = _safe_float(row.get("avg"), fallback=0.0)
    if avg <= 0.0 and ab > 0.0:
        avg = hits / ab
    obp = _safe_float(row.get("obp"), fallback=0.0)
    slg = _safe_float(row.get("slg"), fallback=0.0)
    if slg <= 0.0 and ab > 0.0:
        singles = max(0.0, hits - doubles - triples - home_runs)
        total_bases = singles + (2.0 * doubles) + (3.0 * triples) + (4.0 * home_runs)
        slg = total_bases / ab
    if obp <= 0.0:
        denom = ab + walks + hbp + sf
        if denom > 0.0:
            obp = (hits + walks + hbp) / denom
    ops = _safe_float(row.get("ops"), fallback=0.0)
    if ops <= 0.0 and (obp > 0.0 or slg > 0.0):
        ops = obp + slg
    era = _safe_float(row.get("era"), fallback=0.0)
    if era <= 0.0 and ip > 0.0:
        era = (er * 9.0) / ip
    year = _safe_int(str(season_id).rsplit("-", 1)[-1], fallback=0)
    return {
        "season_id": season_id,
        "league_year": year,
        "team_id": team_id,
        "team_name": str(team_lookup.get(team_id, team_id)) if team_id else "",
        "g": _safe_int(row.get("g"), fallback=0),
        "ab": _safe_int(row.get("ab"), fallback=0),
        "h": _safe_int(row.get("h"), fallback=0),
        "hr": _safe_int(row.get("hr"), fallback=0),
        "rbi": _safe_int(row.get("rbi"), fallback=0),
        "avg": round(avg, 3) if avg > 0.0 else 0.0,
        "ops": round(ops, 3) if ops > 0.0 else 0.0,
        "gs": _safe_int(row.get("gs"), fallback=0),
        "w": _safe_int(row.get("w"), fallback=0),
        "l": _safe_int(row.get("l"), fallback=0),
        "sv": _safe_int(row.get("sv"), fallback=0),
        "ip": round(ip, 2) if ip > 0.0 else 0.0,
        "era": round(era, 2) if era > 0.0 else 0.0,
        "so": _safe_int(strikeouts, fallback=0),
    }


def _player_career_totals(
    *,
    player: Any,
    season_rows: List[Dict[str, Any]],
    include_current: bool,
) -> Dict[str, Any]:
    raw = getattr(player, "career_stats", {}) or {}
    if isinstance(raw, Mapping) and raw:
        totals = _normalize_player_season_row(
            season_id="career",
            stats=raw,
            fallback_team_id="",
            team_lookup={},
        )
    else:
        totals = {
            "g": sum(_safe_int(row.get("g"), fallback=0) for row in season_rows),
            "ab": sum(_safe_int(row.get("ab"), fallback=0) for row in season_rows),
            "h": sum(_safe_int(row.get("h"), fallback=0) for row in season_rows),
            "hr": sum(_safe_int(row.get("hr"), fallback=0) for row in season_rows),
            "rbi": sum(_safe_int(row.get("rbi"), fallback=0) for row in season_rows),
            "gs": sum(_safe_int(row.get("gs"), fallback=0) for row in season_rows),
            "w": sum(_safe_int(row.get("w"), fallback=0) for row in season_rows),
            "l": sum(_safe_int(row.get("l"), fallback=0) for row in season_rows),
            "sv": sum(_safe_int(row.get("sv"), fallback=0) for row in season_rows),
            "so": sum(_safe_int(row.get("so"), fallback=0) for row in season_rows),
            "ip": round(sum(_safe_float(row.get("ip"), fallback=0.0) for row in season_rows), 2),
        }
        ab = _safe_float(totals.get("ab"), fallback=0.0)
        hits = _safe_float(totals.get("h"), fallback=0.0)
        totals["avg"] = round((hits / ab), 3) if ab > 0.0 else 0.0
        innings = _safe_float(totals.get("ip"), fallback=0.0)
        earned_runs = 0.0
        for row in season_rows:
            era = _safe_float(row.get("era"), fallback=0.0)
            ip = _safe_float(row.get("ip"), fallback=0.0)
            if era > 0.0 and ip > 0.0:
                earned_runs += (era * ip) / 9.0
        totals["era"] = round((earned_runs * 9.0) / innings, 2) if innings > 0.0 else 0.0
        ops_values = [_safe_float(row.get("ops"), fallback=0.0) for row in season_rows if _safe_float(row.get("ops"), fallback=0.0) > 0.0]
        totals["ops"] = round(sum(ops_values) / len(ops_values), 3) if ops_values else 0.0
    totals["seasons"] = max(0, len(season_rows) - (1 if include_current else 0)) + (1 if include_current and season_rows else 0)
    return totals


def _player_record_rows(player_id: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for entry in player_record_entries(player_id):
        holder = entry.get("holder", {}) if isinstance(entry, Mapping) else {}
        if not isinstance(holder, Mapping):
            holder = {}
        season_id = str(holder.get("season_id") or "").strip()
        rows.append(
            {
                "category": str(entry.get("category") or ""),
                "label": str(entry.get("label") or ""),
                "value": str(entry.get("value_text") or entry.get("value") or ""),
                "season": (
                    f"<a href=\"../seasons/{html.escape(season_id)}.html\">"
                    f"{html.escape(str(holder.get('season_label') or season_id))}</a>"
                    if season_id
                    else "Career"
                ),
            }
        )
    rows.sort(key=lambda row: (row["category"], row["label"]))
    return rows


def _age_from_birthdate(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    try:
        born = date.fromisoformat(token.split("T", maxsplit=1)[0])
    except ValueError:
        return ""
    today = date.today()
    return str(today.year - born.year - ((today.month, today.day) < (born.month, born.day)))


def _season_awards(entry: Mapping[str, Any]) -> Dict[str, Any]:
    season_id = str(entry.get("season_id") or "").strip()
    if not season_id:
        return {}
    awards_path = _resolve_maybe_relative(str((entry.get("artifacts") or {}).get("awards") or ""))
    payload = _read_json(awards_path, default={})
    awards = payload.get("awards", {}) if isinstance(payload, Mapping) else {}
    return dict(awards) if isinstance(awards, Mapping) else {}


def _award_winner_link(awards: Mapping[str, Any], key: str) -> str:
    entry = awards.get(key, {})
    if not isinstance(entry, Mapping):
        return "--"
    player_id = str(entry.get("player_id") or "").strip()
    label = str(entry.get("player_name") or player_id or "").strip() or "--"
    if player_id:
        return f"<a href=\"../players/{html.escape(player_id)}.html\">{html.escape(label)}</a>"
    return html.escape(label)


def _season_award_display_rows(awards: Mapping[str, Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for award_key in sorted(str(key) for key in awards.keys()):
        rows.append(
            {
                "award": award_key.replace("_", " "),
                "winner": _award_winner_link(awards, award_key),
            }
        )
    if not rows:
        rows.append({"award": "Awards", "winner": "--"})
    return rows


def _season_postseason_summary(
    entry: Mapping[str, Any],
    *,
    team_lookup: Mapping[str, str],
) -> Dict[str, str]:
    season_id = str(entry.get("season_id") or "").strip()
    year = str(entry.get("league_year") or "").strip()
    if not season_id:
        return {}
    artifacts = entry.get("artifacts", {})
    if not isinstance(artifacts, Mapping):
        return {}
    champion_team_id = ""
    runner_up_team_id = ""
    series_result = ""
    champion_csv = _resolve_maybe_relative(str(artifacts.get("champions") or ""))
    champion_team_id, runner_up_team_id, series_result = _load_champion(champion_csv, year)
    if not (champion_team_id and runner_up_team_id and series_result):
        playoffs_path = _resolve_maybe_relative(str(artifacts.get("playoffs") or ""))
        bracket_champion, bracket_runner, bracket_series = _load_champion_from_bracket(playoffs_path, year)
        champion_team_id = champion_team_id or bracket_champion
        runner_up_team_id = runner_up_team_id or bracket_runner
        series_result = series_result or bracket_series
    champion_name = str(team_lookup.get(champion_team_id, champion_team_id)) if champion_team_id else ""
    runner_name = str(team_lookup.get(runner_up_team_id, runner_up_team_id)) if runner_up_team_id else ""
    return {
        "champion_team_id": champion_team_id,
        "champion_name": champion_name,
        "champion_link": _team_link(champion_team_id, champion_name),
        "runner_up_team_id": runner_up_team_id,
        "runner_up_name": runner_name,
        "runner_up_link": _team_link(runner_up_team_id, runner_name),
        "series_result": series_result or "--",
    }


def _season_postseason_display_rows(postseason: Mapping[str, Any]) -> List[Dict[str, str]]:
    if not postseason:
        return [{"champion": "--", "runner_up": "--", "series_result": "--"}]
    return [
        {
            "champion": str(postseason.get("champion_link") or "--"),
            "runner_up": str(postseason.get("runner_up_link") or "--"),
            "series_result": str(postseason.get("series_result") or "--"),
        }
    ]


def _load_champion(path: Path | None, league_year: str) -> tuple[str, str, str]:
    if not league_year or path is None or not path.exists():
        return "", "", ""
    target = league_year.strip()
    selected: Mapping[str, Any] | None = None
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not isinstance(row, Mapping):
                    continue
                if target and str(row.get("year") or "").strip() != target:
                    continue
                selected = row
    except OSError:
        return "", "", ""
    if selected is None:
        return "", "", ""
    return (
        str(selected.get("champion") or "").strip(),
        str(selected.get("runner_up") or "").strip(),
        str(selected.get("series_result") or "").strip(),
    )


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
        return "", "", ""
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
    if champion and not runner_up:
        try:
            final_round = _final_round_from_bracket(bracket)
            matchups = list(getattr(final_round, "matchups", []) or []) if final_round else []
            if matchups:
                matchup = matchups[0]
                high = getattr(getattr(matchup, "high", None), "team_id", "")
                low = getattr(getattr(matchup, "low", None), "team_id", "")
                if high and low:
                    runner_up = low if champion == high else high
        except Exception:
            runner_up = runner_up or ""
    return champion, runner_up, series_result


def _final_round_from_bracket(bracket: object) -> object | None:
    try:
        rounds = list(getattr(bracket, "rounds", []) or [])
    except Exception:
        rounds = []
    if not rounds:
        return None
    finals = []
    for round_obj in rounds:
        name = str(getattr(round_obj, "name", "") or "").lower()
        if any(token in name for token in ("ws", "world", "final", "championship")):
            finals.append(round_obj)
    return finals[-1] if finals else rounds[-1]


def _series_result_from_bracket(bracket: object) -> str:
    try:
        champion = str(getattr(bracket, "champion", "") or "").strip()
        if not champion:
            return ""
        final_round = _final_round_from_bracket(bracket)
        matchups = list(getattr(final_round, "matchups", []) or []) if final_round else []
        if not matchups:
            return ""
        wins_champion = 0
        wins_other = 0
        for game in list(getattr(matchups[0], "games", []) or []):
            result = str(getattr(game, "result", "") or "")
            if "-" not in result:
                continue
            try:
                home_score, away_score = [int(part) for part in result.split("-", maxsplit=1)]
            except Exception:
                continue
            if home_score == away_score:
                continue
            winner = getattr(game, "home", "") if home_score > away_score else getattr(game, "away", "")
            if winner == champion:
                wins_champion += 1
            else:
                wins_other += 1
        if wins_champion or wins_other:
            return f"{wins_champion}-{wins_other}"
    except Exception:
        return ""
    return ""


def _team_link(team_id: str, label: str) -> str:
    clean_team_id = str(team_id or "").strip()
    clean_label = str(label or clean_team_id or "--").strip() or "--"
    if clean_team_id:
        return f"<a href=\"../teams/{html.escape(clean_team_id)}.html\">{html.escape(clean_label)}</a>"
    return html.escape(clean_label)


def _player_link(player_id: str, label: str) -> str:
    clean_player_id = str(player_id or "").strip()
    clean_label = str(label or clean_player_id or "--").strip() or "--"
    if clean_player_id:
        return f"<a href=\"../players/{html.escape(clean_player_id)}.html\">{html.escape(clean_label)}</a>"
    return html.escape(clean_label)


def _player_name(player: Any) -> str:
    return (
        f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}"
    ).strip() or str(getattr(player, "player_id", "") or "")


def _record_rows() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    book = league_record_book()
    for category, entries in book.items():
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            holders = entry.get("holders", [])
            if not isinstance(holders, list):
                holders = []
            if holders:
                for holder in holders:
                    if not isinstance(holder, Mapping):
                        continue
                    rows.append(
                        {
                            "category": str(category),
                            "label": str(entry.get("label") or ""),
                            "value": str(entry.get("value_text") or entry.get("value") or ""),
                            "holder": _record_holder_link(holder),
                            "season": _record_season_link(holder),
                        }
                    )
            else:
                rows.append(
                    {
                        "category": str(category),
                        "label": str(entry.get("label") or ""),
                        "value": str(entry.get("value_text") or entry.get("value") or ""),
                        "holder": "",
                        "season": "",
                    }
                )
    rows.sort(key=lambda item: (item["category"], item["label"]))
    return rows


def _record_holder_link(holder: Mapping[str, Any]) -> str:
    player_id = str(holder.get("player_id") or "").strip()
    team_id = str(holder.get("team_id") or "").strip()
    label = str(
        holder.get("name")
        or holder.get("team_name")
        or player_id
        or team_id
        or ""
    ).strip()
    if player_id:
        return f"<a href=\"../players/{html.escape(player_id)}.html\">{html.escape(label)}</a>"
    if team_id:
        return f"<a href=\"../teams/{html.escape(team_id)}.html\">{html.escape(label)}</a>"
    return html.escape(label)


def _record_season_link(holder: Mapping[str, Any]) -> str:
    season_id = str(holder.get("season_id") or "").strip()
    label = str(holder.get("season_label") or season_id or "").strip()
    if season_id:
        return (
            f"<a href=\"../seasons/{html.escape(season_id)}.html\">"
            f"{html.escape(label or season_id)}</a>"
        )
    return html.escape(label)


def _award_rows(season_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for payload in season_payloads:
        entry = payload.get("entry", {})
        awards = payload.get("awards", {})
        if not isinstance(entry, Mapping):
            continue
        season_id = str(payload.get("season_id") or entry.get("season_id") or "")
        year = _safe_int(entry.get("league_year"), fallback=0)
        rows.append(
            {
                "season_id": f"<a href=\"../seasons/{html.escape(season_id)}.html\">{html.escape(season_id)}</a>",
                "league_year": year or "",
                "mvp": _award_winner_link(awards, "MVP"),
                "cy_young": _award_winner_link(awards, "CY_YOUNG"),
            }
        )
    rows.sort(key=lambda row: (_safe_int(row.get("league_year"), fallback=0), _strip_tags(str(row.get("season_id") or ""))))
    return rows


def _postseason_rows(season_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for payload in season_payloads:
        entry = payload.get("entry", {})
        postseason = payload.get("postseason", {})
        if not isinstance(entry, Mapping):
            continue
        season_id = str(payload.get("season_id") or entry.get("season_id") or "")
        year = _safe_int(entry.get("league_year"), fallback=0)
        if not isinstance(postseason, Mapping):
            postseason = {}
        rows.append(
            {
                "season_id": f"<a href=\"../seasons/{html.escape(season_id)}.html\">{html.escape(season_id)}</a>",
                "league_year": year or "",
                "champion": str(postseason.get("champion_link") or "--"),
                "runner_up": str(postseason.get("runner_up_link") or "--"),
                "series_result": str(postseason.get("series_result") or "--"),
            }
        )
    rows.sort(key=lambda row: (_safe_int(row.get("league_year"), fallback=0), _strip_tags(str(row.get("season_id") or ""))))
    return rows


def _leader_sections(*, team_lookup: Mapping[str, str]) -> Dict[str, List[Dict[str, Any]]]:
    team_map = _player_team_map()
    hitters: List[Dict[str, Any]] = []
    pitchers: List[Dict[str, Any]] = []
    for player in load_players_from_csv("data/players.csv"):
        player_id = str(getattr(player, "player_id", "") or "").strip()
        if not player_id:
            continue
        stats = getattr(player, "season_stats", None)
        if not isinstance(stats, Mapping) or not stats:
            continue
        team_id = str(team_map.get(player_id, "") or "").strip()
        base = {
            "player_id": player_id,
            "player_name": _player_name(player),
            "team_id": team_id,
            "team_name": str(team_lookup.get(team_id, team_id or "--")),
        }
        if bool(getattr(player, "is_pitcher", False)):
            pitchers.append({**base, **_pitching_leader_stats(stats)})
        else:
            hitters.append({**base, **_batting_leader_stats(stats)})
    return {
        "batting": _build_leader_rows(
            hitters,
            categories=[
                ("AVG", "avg", True),
                ("HR", "hr", False),
                ("RBI", "rbi", False),
                ("OPS", "ops", True),
            ],
        ),
        "pitching": _build_leader_rows(
            pitchers,
            categories=[
                ("W", "w", False),
                ("SO", "so", False),
                ("SV", "sv", False),
                ("ERA", "era", True),
            ],
        ),
    }


def _build_leader_rows(
    source_rows: List[Dict[str, Any]],
    *,
    categories: List[tuple[str, str, bool]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for label, key, ascending in categories:
        ranked = [
            row for row in source_rows
            if _safe_float(row.get(key), fallback=0.0) > 0.0
        ]
        if not ranked:
            continue
        ranked.sort(
            key=lambda row: (
                _safe_float(row.get(key), fallback=0.0),
                row.get("player_name", ""),
            ),
            reverse=not ascending,
        )
        leader = ranked[0]
        rows.append(
            {
                "stat": label,
                "player": (
                    f"<a href=\"../players/{html.escape(str(leader.get('player_id') or ''))}.html\">"
                    f"{html.escape(str(leader.get('player_name') or ''))}</a>"
                ),
                "team": (
                    f"<a href=\"../teams/{html.escape(str(leader.get('team_id') or ''))}.html\">"
                    f"{html.escape(str(leader.get('team_name') or '--'))}</a>"
                    if str(leader.get("team_id") or "").strip()
                    else html.escape(str(leader.get("team_name") or "--"))
                ),
                "value": _format_leader_value(label, leader.get(key)),
            }
        )
    return rows


def _batting_leader_stats(stats: Mapping[str, Any]) -> Dict[str, Any]:
    ab = _safe_float(stats.get("ab"), fallback=0.0)
    hits = _safe_float(stats.get("h"), fallback=0.0)
    avg = _safe_float(stats.get("avg"), fallback=0.0)
    if avg <= 0.0 and ab > 0.0:
        avg = hits / ab
    ops = _safe_float(stats.get("ops"), fallback=0.0)
    if ops <= 0.0 and ab > 0.0:
        doubles = _safe_float(stats.get("2b", stats.get("b2")), fallback=0.0)
        triples = _safe_float(stats.get("3b", stats.get("b3")), fallback=0.0)
        home_runs = _safe_float(stats.get("hr"), fallback=0.0)
        walks = _safe_float(stats.get("bb"), fallback=0.0)
        hbp = _safe_float(stats.get("hbp"), fallback=0.0)
        sf = _safe_float(stats.get("sf"), fallback=0.0)
        singles = max(0.0, hits - doubles - triples - home_runs)
        total_bases = singles + (2.0 * doubles) + (3.0 * triples) + (4.0 * home_runs)
        slg = total_bases / ab if ab > 0.0 else 0.0
        denom = ab + walks + hbp + sf
        obp = (hits + walks + hbp) / denom if denom > 0.0 else 0.0
        ops = obp + slg
    return {
        "avg": round(avg, 3) if avg > 0.0 else 0.0,
        "hr": _safe_int(stats.get("hr"), fallback=0),
        "rbi": _safe_int(stats.get("rbi"), fallback=0),
        "ops": round(ops, 3) if ops > 0.0 else 0.0,
    }


def _pitching_leader_stats(stats: Mapping[str, Any]) -> Dict[str, Any]:
    outs = _safe_float(stats.get("outs"), fallback=0.0)
    ip = _safe_float(stats.get("ip"), fallback=0.0)
    if ip <= 0.0 and outs > 0.0:
        ip = outs / 3.0
    era = _safe_float(stats.get("era"), fallback=0.0)
    if era <= 0.0 and ip > 0.0:
        era = (_safe_float(stats.get("er"), fallback=0.0) * 9.0) / ip
    return {
        "w": _safe_int(stats.get("w"), fallback=0),
        "so": _safe_int(stats.get("so"), fallback=0),
        "sv": _safe_int(stats.get("sv"), fallback=0),
        "era": round(era, 2) if era > 0.0 else 0.0,
    }


def _format_leader_value(label: str, value: Any) -> str:
    if label in {"AVG", "OPS"}:
        return _format_fixed(value, 3)
    if label == "ERA":
        return _format_fixed(value, 2)
    return str(_safe_int(value, fallback=0))


def _transaction_history_rows(
    season_payloads: List[Dict[str, Any]],
    *,
    current_season_id: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    current_path = get_data_dir() / "transactions.csv"
    rows.extend(_transaction_rows_for_file(current_path, season_id=current_season_id))
    for payload in season_payloads:
        entry = payload.get("entry", {})
        if not isinstance(entry, Mapping):
            continue
        season_id = str(payload.get("season_id") or entry.get("season_id") or "")
        if season_id == current_season_id:
            continue
        artifacts = entry.get("artifacts", {})
        if not isinstance(artifacts, Mapping):
            continue
        path = _resolve_maybe_relative(str(artifacts.get("transactions") or ""))
        rows.extend(_transaction_rows_for_file(path, season_id=season_id))
    rows.sort(
        key=lambda row: (
            str(row.get("season_id") or ""),
            str(row.get("timestamp") or ""),
        ),
        reverse=True,
    )
    return rows


def _transaction_rows_for_file(path: Path | None, *, season_id: str) -> List[Dict[str, Any]]:
    if path is None or not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                if not isinstance(raw, Mapping):
                    continue
                team_id = str(raw.get("team_id") or "").strip()
                player_id = str(raw.get("player_id") or "").strip()
                rows.append(
                    {
                        "season_id": (
                            f"<a href=\"../seasons/{html.escape(season_id)}.html\">"
                            f"{html.escape(season_id or '--')}</a>"
                        ),
                        "timestamp": str(raw.get("timestamp") or ""),
                        "season_date": str(raw.get("season_date") or ""),
                        "team": _team_link(team_id, team_id or "--"),
                        "player": _player_link(player_id, str(raw.get("player_name") or player_id or "--")),
                        "action": str(raw.get("action") or ""),
                        "from_level": str(raw.get("from_level") or ""),
                        "to_level": str(raw.get("to_level") or ""),
                        "counterparty": str(raw.get("counterparty") or ""),
                        "details": str(raw.get("details") or ""),
                    }
                )
    except OSError:
        return []
    return rows


def _finance_history_sections(
    *,
    season_payloads: List[Dict[str, Any]],
    current_season_id: str,
    team_lookup: Mapping[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    summary_rows: List[Dict[str, Any]] = []
    detail_rows: List[Dict[str, Any]] = []
    seen_seasons: set[str] = set()
    for payload in season_payloads:
        entry = payload.get("entry", {})
        if not isinstance(entry, Mapping):
            continue
        season_id = str(payload.get("season_id") or entry.get("season_id") or "")
        league_year = _safe_int(entry.get("league_year"), fallback=0)
        seen_seasons.add(season_id)
        finance_payload = _load_finance_snapshot(season_id=season_id, league_year=league_year, current_season_id=current_season_id)
        if not finance_payload:
            continue
        summary_rows.extend(
            _finance_summary_rows(
                finance_payload=finance_payload,
                season_id=season_id,
                league_year=league_year,
            )
        )
        detail_rows.extend(
            _finance_team_rows(
                finance_payload=finance_payload,
                season_id=season_id,
                team_lookup=team_lookup,
            )
        )
    summary_rows.sort(key=lambda row: (_safe_int(row.get("league_year"), fallback=0), _strip_tags(str(row.get("season_id") or ""))))
    detail_rows.sort(
        key=lambda row: (
            _strip_tags(str(row.get("season_id") or "")),
            _strip_tags(str(row.get("team") or "")),
        )
    )
    ledger_rows = _current_finance_ledger_rows(team_lookup=team_lookup)
    return {
        "season_summary": summary_rows,
        "team_details": detail_rows,
        "ledger_rows": ledger_rows,
    }


def _load_finance_snapshot(
    *,
    season_id: str,
    league_year: int,
    current_season_id: str,
) -> Dict[str, Any]:
    data_dir = get_data_dir()
    if season_id and season_id == current_season_id:
        current_financials = _read_json(data_dir / "team_financials.json", default={})
        settings_payload = _read_json(data_dir / "league_financial_settings.json", default={})
        return {
            "financials_enabled": _settings_enabled(settings_payload),
            "preset": _settings_preset(settings_payload),
            "team_financials": current_financials,
            "annual_payroll_totals": {},
        }
    snapshot_path = data_dir / "finance_snapshots" / f"{league_year}.json"
    return _read_json(snapshot_path, default={})


def _settings_enabled(payload: Mapping[str, Any]) -> bool:
    leagues = payload.get("leagues", {})
    if not isinstance(leagues, Mapping) or not leagues:
        return False
    first = next(iter(leagues.values()), {})
    return bool(first.get("enabled")) if isinstance(first, Mapping) else False


def _settings_preset(payload: Mapping[str, Any]) -> str:
    leagues = payload.get("leagues", {})
    if not isinstance(leagues, Mapping) or not leagues:
        return ""
    first = next(iter(leagues.values()), {})
    return str(first.get("preset") or "") if isinstance(first, Mapping) else ""


def _finance_summary_rows(
    *,
    finance_payload: Mapping[str, Any],
    season_id: str,
    league_year: int,
) -> List[Dict[str, Any]]:
    team_financials = finance_payload.get("team_financials", {})
    teams = team_financials.get("teams", {}) if isinstance(team_financials, Mapping) else {}
    if not isinstance(teams, Mapping):
        teams = {}
    total_cash = 0
    total_debt = 0
    total_revenue = 0
    total_expenses = 0
    total_payroll = 0
    for raw in teams.values():
        if not isinstance(raw, Mapping):
            continue
        total_cash += _safe_int(raw.get("cash_on_hand"), fallback=0)
        total_debt += _safe_int(raw.get("debt"), fallback=0)
        revenue = raw.get("revenue", {})
        expenses = raw.get("expenses", {})
        if isinstance(revenue, Mapping):
            total_revenue += sum(_safe_int(value, fallback=0) for value in revenue.values())
        if isinstance(expenses, Mapping):
            total_expenses += sum(_safe_int(value, fallback=0) for value in expenses.values())
            total_payroll += _safe_int(expenses.get("payroll"), fallback=0)
    annual_payroll = finance_payload.get("annual_payroll_totals", {})
    if isinstance(annual_payroll, Mapping) and annual_payroll:
        total_payroll = sum(_safe_int(value, fallback=0) for value in annual_payroll.values())
    return [
        {
            "season_id": f"<a href=\"../seasons/{html.escape(season_id)}.html\">{html.escape(season_id)}</a>",
            "league_year": league_year or "",
            "financials_enabled": "Yes" if bool(finance_payload.get("financials_enabled")) else "No",
            "preset": str(finance_payload.get("preset") or "--"),
            "teams": len(teams),
            "total_cash": _format_currency(total_cash),
            "total_debt": _format_currency(total_debt),
            "total_revenue": _format_currency(total_revenue),
            "total_expenses": _format_currency(total_expenses),
            "total_payroll": _format_currency(total_payroll),
        }
    ]


def _finance_team_rows(
    *,
    finance_payload: Mapping[str, Any],
    season_id: str,
    team_lookup: Mapping[str, str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    team_financials = finance_payload.get("team_financials", {})
    teams = team_financials.get("teams", {}) if isinstance(team_financials, Mapping) else {}
    annual_payroll = finance_payload.get("annual_payroll_totals", {})
    if not isinstance(teams, Mapping):
        return rows
    for team_id, raw in teams.items():
        if not isinstance(raw, Mapping):
            continue
        revenue = raw.get("revenue", {})
        expenses = raw.get("expenses", {})
        revenue_total = sum(_safe_int(value, fallback=0) for value in revenue.values()) if isinstance(revenue, Mapping) else 0
        expense_total = sum(_safe_int(value, fallback=0) for value in expenses.values()) if isinstance(expenses, Mapping) else 0
        payroll_total = _safe_int(expenses.get("payroll"), fallback=0) if isinstance(expenses, Mapping) else 0
        if isinstance(annual_payroll, Mapping) and annual_payroll:
            payroll_total = _safe_int(annual_payroll.get(team_id), fallback=payroll_total)
        team_name = str(team_lookup.get(str(team_id), str(team_id)))
        rows.append(
            {
                "season_id": f"<a href=\"../seasons/{html.escape(season_id)}.html\">{html.escape(season_id)}</a>",
                "team": _team_link(str(team_id), team_name),
                "cash_on_hand": _format_currency(_safe_int(raw.get("cash_on_hand"), fallback=0)),
                "debt": _format_currency(_safe_int(raw.get("debt"), fallback=0)),
                "revenue_total": _format_currency(revenue_total),
                "expense_total": _format_currency(expense_total),
                "payroll_total": _format_currency(payroll_total),
            }
        )
    return rows


def _current_finance_ledger_rows(*, team_lookup: Mapping[str, str]) -> List[Dict[str, Any]]:
    path = get_data_dir() / "financial_transactions.csv"
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                if not isinstance(raw, Mapping):
                    continue
                team_id = str(raw.get("team_id") or "").strip()
                team_name = str(team_lookup.get(team_id, team_id or "--"))
                rows.append(
                    {
                        "season_year": str(raw.get("season_year") or ""),
                        "team": _team_link(team_id, team_name) if team_id and team_id != "__system__" else html.escape(team_name),
                        "category": str(raw.get("category") or ""),
                        "amount": _format_currency(_safe_int(raw.get("amount"), fallback=0)),
                        "memo": str(raw.get("memo") or ""),
                    }
                )
    except OSError:
        return []
    rows.reverse()
    return rows[:50]


def _write_season_pages(
    *,
    seasons_dir: Path,
    season_payloads: List[Dict[str, Any]],
    files: Dict[str, Path],
) -> Dict[str, Path]:
    pages: Dict[str, Path] = {}
    for payload in season_payloads:
        entry = payload.get("entry", {})
        if not isinstance(entry, Mapping):
            continue
        season_id = str(payload.get("season_id") or entry.get("season_id") or "")
        standings_rows = list(payload.get("standings_rows", []) or [])
        path = seasons_dir / f"{season_id}.html"
        path.write_text(
            _season_page_html(
                entry=entry,
                standings_rows=standings_rows,
                awards=payload.get("awards", {}),
                postseason=payload.get("postseason", {}),
                prev_id=str(payload.get("prev_id") or ""),
                next_id=str(payload.get("next_id") or ""),
            ),
            encoding="utf-8",
        )
        key = f"season_{season_id}_html"
        files[key] = path
        pages[season_id] = path
    return pages


def _write_team_pages(
    *,
    teams_dir: Path,
    teams_rows: List[Dict[str, str]],
    team_history_by_team: Mapping[str, List[Dict[str, Any]]],
    files: Dict[str, Path],
) -> Dict[str, Path]:
    pages: Dict[str, Path] = {}
    for row in teams_rows:
        team_id = str(row.get("team_id") or "").strip()
        if not team_id:
            continue
        path = teams_dir / f"{team_id}.html"
        path.write_text(
            _team_page_html(
                team_row=row,
                history_rows=list(team_history_by_team.get(team_id, [])),
            ),
            encoding="utf-8",
        )
        files[f"team_{team_id}_html"] = path
        pages[team_id] = path
    return pages


def _write_player_pages(
    *,
    players_dir: Path,
    player_pages: Mapping[str, Dict[str, Any]],
    files: Dict[str, Path],
) -> Dict[str, Path]:
    pages: Dict[str, Path] = {}
    for player_id, payload in player_pages.items():
        clean_player_id = str(player_id or "").strip()
        if not clean_player_id:
            continue
        path = players_dir / f"{clean_player_id}.html"
        path.write_text(_player_page_html(payload), encoding="utf-8")
        files[f"player_{clean_player_id}_html"] = path
        pages[clean_player_id] = path
    return pages


def _page_start(title: str, *, path_prefix: str = "..") -> List[str]:
    return [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\">",
        f"<title>{html.escape(title)}</title>",
        f"<link rel=\"stylesheet\" href=\"{path_prefix}/assets/almanac.css\">",
        "</head><body>",
        "<div class=\"nav\">",
        f"<a href=\"{path_prefix}/index.html\">Almanac Home</a>",
        f"<a href=\"{path_prefix}/seasons/index.html\">Seasons</a>",
        f"<a href=\"{path_prefix}/teams/index.html\">Teams</a>",
        f"<a href=\"{path_prefix}/players/index.html\">Players</a>",
        f"<a href=\"{path_prefix}/awards/index.html\">Awards</a>",
        f"<a href=\"{path_prefix}/postseason/index.html\">Postseason</a>",
        f"<a href=\"{path_prefix}/leaders/index.html\">Leaders</a>",
        f"<a href=\"{path_prefix}/transactions/index.html\">Transactions</a>",
        f"<a href=\"{path_prefix}/finance/index.html\">Finance</a>",
        f"<a href=\"{path_prefix}/records/index.html\">Records</a>",
        "</div>",
    ]


def _stat_panel(title: str, value: Any, *, note: str = "") -> str:
    lines = [
        "<div class=\"panel stat-card\">",
        f"<div class=\"stat-label\">{html.escape(title)}</div>",
        f"<p class=\"stat-value\">{html.escape(str(value))}</p>",
    ]
    if note:
        lines.append(f"<div class=\"stat-note\">{html.escape(note)}</div>")
    lines.append("</div>")
    return "".join(lines)


def _toc_card(href: str, title: str, copy: str) -> str:
    return (
        f"<a class=\"panel toc-card\" href=\"{html.escape(href)}\">"
        f"<div class=\"toc-title\">{html.escape(title)}</div>"
        f"<p class=\"toc-copy\">{html.escape(copy)}</p>"
        "</a>"
    )


def _landing_html(
    *,
    season_entries: List[Dict[str, Any]],
    current_standings_rows: List[Dict[str, Any]],
    teams_count: int,
    players_count: int,
) -> str:
    season_count = len(season_entries)
    latest_year = (
        max((_safe_int(entry.get("league_year"), fallback=0) for entry in season_entries), default=0)
        if season_entries
        else 0
    )
    lines = _page_start("League Almanac", path_prefix=".")
    lines.extend(
        [
            "<h1>League Almanac</h1>",
            (
                "<div class=\"meta\">"
                f"Generated: {html.escape(datetime.utcnow().isoformat(timespec='seconds'))}Z"
                "</div>"
            ),
            "<div class=\"grid\">",
            _stat_panel("Seasons", season_count),
            _stat_panel("Latest Year", latest_year or "--"),
            _stat_panel("Teams", teams_count),
            _stat_panel("Players", players_count),
            "</div>",
            "<div class=\"panel\">",
            "<h2>Sections</h2>",
            "<div class=\"toc-grid\">",
            _toc_card("seasons/index.html", "Season Index", "Browse the league season by season."),
            _toc_card("teams/index.html", "Teams", "Franchise pages with year splits and all-time summaries."),
            _toc_card("players/index.html", "Players", "Career pages with logs, totals, and record links."),
            _toc_card("awards/index.html", "Awards", "Archived MVP, Cy Young, and season honor rolls."),
            _toc_card("postseason/index.html", "Postseason", "Championship results and playoff outcomes."),
            _toc_card("leaders/index.html", "Leaders", "Current leaderboard snapshot."),
            _toc_card("transactions/index.html", "Transactions", "Archived and current move history."),
            _toc_card("finance/index.html", "Finance", "Season finance snapshots and live ledger detail."),
            _toc_card("records/index.html", "Records", "League record book and all-time markers."),
            "</div>",
            "</div>",
            "<div class=\"panel\">",
            "<h2>Current Standings Snapshot</h2>",
            _table_html(
                _link_standings_rows(current_standings_rows[:10], "../teams", from_root=True),
                ["team_id", "team_name", "wins", "losses", "pct"],
                allow_html={"team_name"},
            ),
            "</div>",
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _season_index_html(
    season_entries: List[Dict[str, Any]],
    pages: Mapping[str, Path],
) -> str:
    lines = _page_start("Season Index")
    rows: List[Dict[str, Any]] = []
    for entry in season_entries:
        season_id = str(entry["season_id"])
        page = pages.get(season_id)
        rows.append(
            {
                "season_id": season_id,
                "league_year": _safe_int(entry.get("league_year"), fallback=0),
                "status": str(entry.get("status") or ""),
                "started_on": str(entry.get("started_on") or ""),
                "ended_on": str(entry.get("ended_on") or ""),
                "link": f"<a href=\"{html.escape(page.name if page else '')}\">Open</a>",
            }
        )
    lines.extend(
        [
            "<h1>Season Index</h1>",
            "<div class=\"meta\">Browse league progress year by year.</div>",
            _table_html(
                rows,
                ["season_id", "league_year", "status", "started_on", "ended_on", "link"],
                allow_html={"link"},
            ),
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _season_page_html(
    *,
    entry: Mapping[str, Any],
    standings_rows: List[Dict[str, Any]],
    awards: Mapping[str, Any],
    postseason: Mapping[str, Any],
    prev_id: str,
    next_id: str,
) -> str:
    season_id = str(entry.get("season_id") or "")
    year = _safe_int(entry.get("league_year"), fallback=0)
    status = str(entry.get("status") or "")
    started_on = str(entry.get("started_on") or "")
    ended_on = str(entry.get("ended_on") or "")
    lines = _page_start(f"Season {season_id}")
    nav_bits = []
    if prev_id:
        nav_bits.append(f"<a href=\"{html.escape(prev_id)}.html\">Previous Season</a>")
    if next_id:
        nav_bits.append(f"<a href=\"{html.escape(next_id)}.html\">Next Season</a>")
    lines.extend(
        [
            f"<h1>Season {html.escape(season_id)}</h1>",
            f"<div class=\"meta\">League Year: {year or '--'} | Status: {html.escape(status)}</div>",
            "<div class=\"panel\">",
            "<h2>Season Summary</h2>",
            "<ul>",
            f"<li>Started: {html.escape(started_on or '--')}</li>",
            f"<li>Ended: {html.escape(ended_on or '--')}</li>",
            f"<li>Archived: {html.escape(str(entry.get('archived_on') or '--'))}</li>",
            "</ul>",
            "</div>",
            "<div class=\"panel\">",
            "<h2>Standings</h2>",
            _table_html(
                _link_standings_rows(standings_rows, "../teams"),
                ["team_id", "team_name", "wins", "losses", "pct", "runs_for", "runs_against"],
                allow_html={"team_name"},
            ),
            "</div>",
            "<div class=\"panel\">",
            "<h2>Awards</h2>",
            _table_html(
                _season_award_display_rows(awards),
                ["award", "winner"],
                allow_html={"winner"},
            ),
            "</div>",
            "<div class=\"panel\">",
            "<h2>Postseason</h2>",
            _table_html(
                _season_postseason_display_rows(postseason),
                ["champion", "runner_up", "series_result"],
                allow_html={"champion", "runner_up"},
            ),
            "</div>",
            (
                "<div class=\"panel small season-links\">"
                + " | ".join(nav_bits)
                + "</div>"
                if nav_bits
                else ""
            ),
            "</body></html>",
        ]
    )
    return "\n".join([line for line in lines if line])


def _teams_html(rows: List[Dict[str, str]]) -> str:
    lines = _page_start("Teams")
    lines.extend(
        [
            "<h1>Teams</h1>",
            "<div class=\"meta\">Franchise directory with team-history links.</div>",
            _table_html(
                rows,
                [
                    "team_id",
                    "team_name",
                    "abbreviation",
                    "division",
                    "seasons",
                    "total_wins",
                    "total_losses",
                    "championships",
                    "best_season",
                    "stadium",
                ],
                allow_html={"team_name"},
            ),
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _team_page_html(
    *,
    team_row: Mapping[str, Any],
    history_rows: List[Dict[str, Any]],
) -> str:
    team_id = str(team_row.get("team_id") or "")
    team_name_plain = _strip_tags(str(team_row.get("team_name") or team_id))
    summary_rows = _linked_team_history_rows(history_rows)
    lines = _page_start(team_name_plain)
    lines.extend(
        [
            f"<h1>{html.escape(team_name_plain)}</h1>",
            f"<div class=\"meta\">Franchise ID: {html.escape(team_id)}</div>",
            "<div class=\"grid\">",
            _stat_panel("Seasons", team_row.get("seasons") or "0"),
            _stat_panel(
                "All-Time Record",
                f"{team_row.get('total_wins') or '0'}-{team_row.get('total_losses') or '0'}",
            ),
            _stat_panel("Titles", team_row.get("championships") or "0"),
            _stat_panel("Best Season", team_row.get("best_season") or "--"),
            "</div>",
            "<div class=\"panel\">",
            "<h2>Franchise Summary</h2>",
            "<ul>",
            f"<li>Abbreviation: {html.escape(str(team_row.get('abbreviation') or '--'))}</li>",
            f"<li>Division: {html.escape(str(team_row.get('division') or '--'))}</li>",
            f"<li>Owner: {html.escape(str(team_row.get('owner_id') or '--'))}</li>",
            f"<li>Stadium: {html.escape(str(team_row.get('stadium') or '--'))}</li>",
            "</ul>",
            "</div>",
            "<div class=\"panel\">",
            "<h2>Year-by-Year History</h2>",
            _table_html(
                summary_rows,
                [
                    "season_id",
                    "league_year",
                    "status",
                    "wins",
                    "losses",
                    "pct",
                    "runs_for",
                    "runs_against",
                    "champion",
                ],
                allow_html={"season_id"},
            ),
            "</div>",
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _players_html(rows: List[Dict[str, str]]) -> str:
    lines = _page_start("Players")
    lines.extend(
        [
            "<h1>Players</h1>",
            "<div class=\"meta\">Player directory with career-page links.</div>",
            _table_html(
                rows,
                ["player_id", "name", "team_id", "team_name", "primary_position", "is_pitcher", "seasons"],
                allow_html={"name", "team_name"},
            ),
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _player_page_html(payload: Mapping[str, Any]) -> str:
    player_id = str(payload.get("player_id") or "")
    name = str(payload.get("name") or player_id)
    team_id = str(payload.get("team_id") or "")
    team_name = str(payload.get("team_name") or team_id)
    is_pitcher = bool(payload.get("is_pitcher"))
    career_totals = payload.get("career_totals", {})
    if not isinstance(career_totals, Mapping):
        career_totals = {}
    season_rows = list(payload.get("season_rows", []) or [])
    record_rows = list(payload.get("record_rows", []) or [])

    team_display = "--"
    if team_id:
        team_display = (
            f"<a href=\"../teams/{html.escape(team_id)}.html\">"
            f"{html.escape(team_name or team_id)}</a>"
        )

    lines = _page_start(name)
    lines.extend(
        [
            f"<h1>{html.escape(name)}</h1>",
            (
                "<div class=\"meta\">"
                f"Player ID: {html.escape(player_id)} | "
                f"Position: {html.escape(str(payload.get('primary_position') or '--'))} | "
                f"Type: {'Pitcher' if is_pitcher else 'Hitter'}"
                "</div>"
            ),
            "<div class=\"grid\">",
            _stat_panel("Seasons", career_totals.get("seasons") or len(season_rows) or 0),
            (
                _stat_panel("Career IP", _format_fixed(career_totals.get("ip"), 2))
                if is_pitcher
                else _stat_panel("Career Hits", _safe_int(career_totals.get("h"), fallback=0))
            ),
            (
                _stat_panel("Career ERA", _format_fixed(career_totals.get("era"), 2))
                if is_pitcher
                else _stat_panel("Career HR", _safe_int(career_totals.get("hr"), fallback=0))
            ),
            (
                _stat_panel("Career SO", _safe_int(career_totals.get("so"), fallback=0))
                if is_pitcher
                else _stat_panel("Career OPS", _format_fixed(career_totals.get("ops"), 3))
            ),
            "</div>",
            "<div class=\"panel\">",
            "<h2>Player Summary</h2>",
            "<ul>",
            f"<li>Current Team: {team_display}</li>",
            f"<li>Bats: {html.escape(str(payload.get('bats') or '--'))}</li>",
            f"<li>Birthdate: {html.escape(str(payload.get('birthdate') or '--'))}</li>",
            f"<li>Age: {html.escape(str(payload.get('age') or '--'))}</li>",
            "</ul>",
            "</div>",
            "<div class=\"panel\">",
            "<h2>Year-by-Year Log</h2>",
            _player_log_table_html(season_rows, is_pitcher=is_pitcher),
            "</div>",
        ]
    )
    if record_rows:
        lines.extend(
            [
                "<div class=\"panel\">",
                "<h2>Record Book</h2>",
                _table_html(
                    record_rows,
                    ["category", "label", "value", "season"],
                    allow_html={"season"},
                ),
                "</div>",
            ]
        )
    lines.append("</body></html>")
    return "\n".join(lines)


def _player_log_table_html(
    season_rows: List[Dict[str, Any]],
    *,
    is_pitcher: bool,
) -> str:
    columns = (
        ["season_id", "team_name", "g", "gs", "w", "l", "sv", "ip", "era", "so"]
        if is_pitcher
        else ["season_id", "team_name", "g", "ab", "h", "hr", "rbi", "avg", "ops"]
    )
    linked_rows: List[Dict[str, Any]] = []
    for row in season_rows:
        linked = dict(row)
        season_id = str(row.get("season_id") or "").strip()
        if season_id:
            linked["season_id"] = (
                f"<a href=\"../seasons/{html.escape(season_id)}.html\">"
                f"{html.escape(season_id)}</a>"
            )
        team_id = str(row.get("team_id") or "").strip()
        team_name = str(row.get("team_name") or "")
        if team_id and team_name:
            linked["team_name"] = (
                f"<a href=\"../teams/{html.escape(team_id)}.html\">"
                f"{html.escape(team_name)}</a>"
            )
        else:
            linked["team_name"] = html.escape(team_name or "--")
        for key in ("avg", "ops"):
            linked[key] = _format_fixed(row.get(key), 3)
        for key in ("ip",):
            linked[key] = _format_fixed(row.get(key), 2)
        for key in ("era",):
            linked[key] = _format_fixed(row.get(key), 2)
        linked_rows.append(linked)
    return _table_html(linked_rows, columns, allow_html={"season_id", "team_name"})


def _awards_html(rows: List[Dict[str, Any]]) -> str:
    lines = _page_start("Awards")
    lines.extend(
        [
            "<h1>Awards</h1>",
            "<div class=\"meta\">Archived season award winners.</div>",
            _table_html(
                rows,
                ["season_id", "league_year", "mvp", "cy_young"],
                allow_html={"season_id", "mvp", "cy_young"},
            ),
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _postseason_html(rows: List[Dict[str, Any]]) -> str:
    lines = _page_start("Postseason")
    lines.extend(
        [
            "<h1>Postseason</h1>",
            "<div class=\"meta\">Championship results by season.</div>",
            _table_html(
                rows,
                ["season_id", "league_year", "champion", "runner_up", "series_result"],
                allow_html={"season_id", "champion", "runner_up"},
            ),
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _leaders_html(sections: Mapping[str, List[Dict[str, Any]]]) -> str:
    batting_rows = list(sections.get("batting", []) or [])
    pitching_rows = list(sections.get("pitching", []) or [])
    lines = _page_start("Leaders")
    lines.extend(
        [
            "<h1>Leaders</h1>",
            "<div class=\"meta\">Current season leaderboard snapshot.</div>",
            "<div class=\"panel\">",
            "<h2>Batting Leaders</h2>",
            _table_html(
                batting_rows,
                ["stat", "player", "team", "value"],
                allow_html={"player", "team"},
            ),
            "</div>",
            "<div class=\"panel\">",
            "<h2>Pitching Leaders</h2>",
            _table_html(
                pitching_rows,
                ["stat", "player", "team", "value"],
                allow_html={"player", "team"},
            ),
            "</div>",
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _transactions_html(rows: List[Dict[str, Any]]) -> str:
    lines = _page_start("Transactions")
    lines.extend(
        [
            "<h1>Transactions</h1>",
            "<div class=\"meta\">Archived and current transaction history when available.</div>",
            _table_html(
                rows,
                [
                    "season_id",
                    "timestamp",
                    "season_date",
                    "team",
                    "player",
                    "action",
                    "from_level",
                    "to_level",
                    "counterparty",
                    "details",
                ],
                allow_html={"season_id", "team", "player"},
            ),
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _finance_html(sections: Mapping[str, List[Dict[str, Any]]]) -> str:
    summary_rows = list(sections.get("season_summary", []) or [])
    team_rows = list(sections.get("team_details", []) or [])
    ledger_rows = list(sections.get("ledger_rows", []) or [])
    lines = _page_start("Finance")
    lines.extend(
        [
            "<h1>Finance</h1>",
            "<div class=\"meta\">Season finance snapshots and current finance ledger when available.</div>",
            "<div class=\"panel\">",
            "<h2>Season Finance Summary</h2>",
            _table_html(
                summary_rows,
                [
                    "season_id",
                    "league_year",
                    "financials_enabled",
                    "preset",
                    "teams",
                    "total_cash",
                    "total_debt",
                    "total_revenue",
                    "total_expenses",
                    "total_payroll",
                ],
                allow_html={"season_id"},
            ),
            "</div>",
            "<div class=\"panel\">",
            "<h2>Team Finance Details</h2>",
            _table_html(
                team_rows,
                [
                    "season_id",
                    "team",
                    "cash_on_hand",
                    "debt",
                    "revenue_total",
                    "expense_total",
                    "payroll_total",
                ],
                allow_html={"season_id", "team"},
            ),
            "</div>",
            "<div class=\"panel\">",
            "<h2>Current Finance Ledger</h2>",
            _table_html(
                ledger_rows,
                ["season_year", "team", "category", "amount", "memo"],
                allow_html={"team"},
            ),
            "</div>",
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _records_html(rows: List[Dict[str, str]]) -> str:
    lines = _page_start("Records")
    lines.extend(
        [
            "<h1>Records & Leaders</h1>",
            "<div class=\"meta\">League record book snapshot.</div>",
            _table_html(
                rows,
                ["category", "label", "value", "holder", "season"],
                allow_html={"holder", "season"},
            ),
            "</body></html>",
        ]
    )
    return "\n".join(lines)


def _link_standings_rows(
    rows: Iterable[Mapping[str, Any]],
    team_prefix: str,
    *,
    from_root: bool = False,
) -> List[Dict[str, Any]]:
    linked: List[Dict[str, Any]] = []
    for row in rows:
        team_id = str(row.get("team_id") or "").strip()
        team_name = str(row.get("team_name") or team_id)
        href = f"teams/{team_id}.html" if from_root else f"{team_prefix}/{team_id}.html"
        linked_row = dict(row)
        if team_id:
            linked_row["team_name"] = f"<a href=\"{html.escape(href)}\">{html.escape(team_name)}</a>"
        linked.append(linked_row)
    return linked


def _linked_team_history_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    linked: List[Dict[str, Any]] = []
    for row in rows:
        season_id = str(row.get("season_id") or "").strip()
        linked_row = dict(row)
        if season_id:
            linked_row["season_id"] = (
                f"<a href=\"../seasons/{html.escape(season_id)}.html\">"
                f"{html.escape(season_id)}</a>"
            )
        linked.append(linked_row)
    return linked


def _season_champion_team_id(entry: Mapping[str, Any]) -> str:
    if str(entry.get("status") or "") == "current":
        return ""
    season_id = str(entry.get("season_id") or "").strip()
    if not season_id:
        return ""
    league_year = _safe_int(entry.get("league_year"), fallback=0)
    artifacts = entry.get("artifacts", {})
    if not isinstance(artifacts, Mapping):
        return ""
    champion = _load_champion_from_csv(
        _resolve_maybe_relative(str(artifacts.get("champions") or "")),
        league_year=league_year,
    )
    if champion:
        return champion
    playoffs_path = _resolve_maybe_relative(str(artifacts.get("playoffs") or ""))
    payload = _read_json(playoffs_path, default={})
    if isinstance(payload, Mapping):
        return str(payload.get("champion") or "").strip()
    return ""


def _load_champion_from_csv(path: Path | None, *, league_year: int) -> str:
    if path is None or not path.exists():
        return ""
    target_year = str(league_year)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not isinstance(row, Mapping):
                    continue
                row_year = str(row.get("year") or "").strip()
                if row_year and row_year != target_year:
                    continue
                champion = str(row.get("champion") or "").strip()
                if champion:
                    return champion
    except OSError:
        return ""
    return ""


def _strip_tags(value: str) -> str:
    out = []
    inside = False
    for char in value:
        if char == "<":
            inside = True
            continue
        if char == ">":
            inside = False
            continue
        if not inside:
            out.append(char)
    return "".join(out).strip()


def _resolve_local_export_href(page: Path, href: str) -> Path | None:
    clean_href = str(href or "").strip()
    if not clean_href:
        return None
    clean_href = clean_href.split("#", 1)[0].split("?", 1)[0].strip()
    if not clean_href:
        return None
    lowered = clean_href.lower()
    if lowered.startswith(("http://", "https://", "mailto:", "javascript:")):
        return None
    return (page.parent / clean_href).resolve()


def _table_html(
    rows: Iterable[Mapping[str, Any]],
    columns: List[str],
    *,
    allow_html: set[str] | None = None,
) -> str:
    rows_list = list(rows)
    header = "".join(
        f"<th class=\"{'num' if _is_numeric_column(col) else ''}\">{html.escape(col)}</th>"
        for col in columns
    )
    body_parts: List[str] = []
    allowed = set(allow_html or set())
    for row in rows_list:
        cells: List[str] = []
        for col in columns:
            raw = row.get(col, "")
            css_class = "num" if _is_numeric_column(col) else ""
            if col in allowed:
                cells.append(f"<td class=\"{css_class}\">{str(raw)}</td>")
            else:
                cells.append(f"<td class=\"{css_class}\">{html.escape(str(raw))}</td>")
        body_parts.append("<tr>" + "".join(cells) + "</tr>")
    if not body_parts:
        body_parts.append(
            f"<tr><td colspan=\"{max(1, len(columns))}\">No rows available.</td></tr>"
        )
    return (
        "<div class=\"table-wrap\"><table class=\"data-table\"><thead><tr>"
        + header
        + "</tr></thead><tbody>"
        + "".join(body_parts)
        + "</tbody></table></div>"
    )


def _is_numeric_column(column: str) -> bool:
    return column in {
        "league_year",
        "wins",
        "losses",
        "pct",
        "runs_for",
        "runs_against",
        "seasons",
        "total_wins",
        "total_losses",
        "championships",
        "g",
        "ab",
        "h",
        "hr",
        "rbi",
        "avg",
        "ops",
        "gs",
        "w",
        "l",
        "sv",
        "ip",
        "era",
        "so",
        "value",
        "teams",
        "total_cash",
        "total_debt",
        "total_revenue",
        "total_expenses",
        "total_payroll",
        "cash_on_hand",
        "debt",
        "revenue_total",
        "expense_total",
        "payroll_total",
        "amount",
    }


def _read_json(path: Path | None, *, default: Any) -> Any:
    if path is None or not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _safe_int(value: Any, *, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _safe_float(value: Any, *, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _format_fixed(value: Any, digits: int) -> str:
    number = _safe_float(value, fallback=0.0)
    if number <= 0.0:
        return "--"
    return f"{number:.{digits}f}"


def _format_currency(value: Any) -> str:
    amount = _safe_int(value, fallback=0)
    return f"${amount:,.0f}"


__all__ = [
    "AlmanacExportResult",
    "AlmanacValidationResult",
    "export_almanac",
    "validate_almanac_export",
]
