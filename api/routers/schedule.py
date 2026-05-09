"""Schedule endpoint.

Ports the data side of ``ui/schedule_page.py``: lists games from
``schedule.csv`` with optional team / date filters, plus a helper for the
next upcoming matchup used by the dashboard hero.
"""

from __future__ import annotations

import calendar
import csv
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from utils.path_utils import get_data_dir
from utils.sim_date import get_current_sim_date

from ..security import CurrentIdentity

router = APIRouter(prefix="/schedule", tags=["schedule"], dependencies=[CurrentIdentity])


def _parse_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _is_played(value: str, result: str) -> bool:
    flag = value.strip().lower() in {"1", "true", "yes", "y"}
    return flag or bool(result.strip())


def _load_all() -> List[Dict[str, Any]]:
    path = get_data_dir() / "schedule.csv"
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            game_date = str(row.get("date", "")).strip()
            home = str(row.get("home", "")).strip()
            away = str(row.get("away", "")).strip()
            result = str(row.get("result", "")).strip()
            played = _is_played(str(row.get("played", "")), result)
            if not game_date or not home or not away:
                continue
            rows.append(
                {
                    "date": game_date,
                    "home": home,
                    "away": away,
                    "result": result or None,
                    "played": played,
                    "boxscore": str(row.get("boxscore", "")).strip() or None,
                }
            )
    return rows


def _detect_all_star_break(rows: List[Dict[str, Any]]) -> List[str]:
    """Find the first mid-season run of empty days (≥3 consecutive).

    The schedule generator inserts a 6-day gap mid-season for the All-Star
    break. We detect that by walking the date range from first game to
    last game, identifying the longest contiguous run of game-less days
    in the middle third of the season, and returning those ISO dates.
    """

    if not rows:
        return []
    dates_with_games: set[str] = {g["date"] for g in rows if g.get("date")}
    if not dates_with_games:
        return []
    first = min(_parse_date(d) for d in dates_with_games if _parse_date(d))
    last = max(_parse_date(d) for d in dates_with_games if _parse_date(d))
    if not first or not last or first >= last:
        return []

    # Walk every date between first and last, find runs of empty days.
    runs: List[List[date]] = []
    current_run: List[date] = []
    cursor = first
    while cursor <= last:
        if cursor.isoformat() in dates_with_games:
            if current_run:
                runs.append(current_run)
                current_run = []
        else:
            current_run.append(cursor)
        cursor += timedelta(days=1)
    if current_run:
        runs.append(current_run)

    # Pick the longest run of ≥3 days that falls in the middle half of
    # the season (roughly when the All-Star break is scheduled).
    season_span = (last - first).days or 1
    candidates: List[List[date]] = []
    for run in runs:
        if len(run) < 3:
            continue
        midpoint = run[len(run) // 2]
        offset = (midpoint - first).days / season_span
        if 0.30 <= offset <= 0.70:
            candidates.append(run)
    if not candidates:
        return []
    best = max(candidates, key=len)
    return [d.isoformat() for d in best]


def _compute_draft_date(year: int) -> Optional[str]:
    """Third Tuesday in July — mirrors api/routers/season.py."""

    july_cal = calendar.Calendar().itermonthdates(year, 7)
    tuesdays = [d for d in july_cal if d.month == 7 and d.weekday() == 1]
    if len(tuesdays) < 3:
        return None
    return tuesdays[2].isoformat()


def _today_iso() -> str:
    sim = get_current_sim_date()
    if sim:
        return str(sim)[:10]
    return date.today().isoformat()


def _build_markers(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    today = _today_iso()
    parsed_dates = [_parse_date(g["date"]) for g in rows]
    parsed_dates = [d for d in parsed_dates if d]
    season_start = min(parsed_dates).isoformat() if parsed_dates else None
    season_end = max(parsed_dates).isoformat() if parsed_dates else None

    year = None
    if season_start:
        try:
            year = int(season_start.split("-")[0])
        except Exception:
            year = None
    if year is None:
        try:
            year = int(today.split("-")[0])
        except Exception:
            year = date.today().year

    return {
        "today": today,
        "season_start": season_start,
        "season_end": season_end,
        "all_star_break": _detect_all_star_break(rows),
        "trade_deadline": date(year, 7, 31).isoformat(),
        "draft_date": _compute_draft_date(year),
    }


@router.get("")
def list_schedule(
    team_id: Optional[str] = Query(default=None, description="Only games for this team"),
    start: Optional[str] = Query(default=None, description="YYYY-MM-DD inclusive"),
    end: Optional[str] = Query(default=None, description="YYYY-MM-DD inclusive"),
    played: Optional[bool] = Query(default=None, description="Filter by played flag"),
    limit: int = Query(default=500, ge=1, le=5000),
    include_markers: bool = Query(default=False, description="Include season markers (all-star break, trade deadline, etc.)"),
) -> Dict[str, Any]:
    start_date = _parse_date(start) if start else None
    end_date = _parse_date(end) if end else None

    all_rows = _load_all()
    out: List[Dict[str, Any]] = []
    for game in all_rows:
        if team_id and team_id not in (game["home"], game["away"]):
            continue
        if played is not None and bool(game["played"]) != played:
            continue
        gd = _parse_date(game["date"])
        if start_date and gd and gd < start_date:
            continue
        if end_date and gd and gd > end_date:
            continue
        if team_id:
            is_home = game["home"] == team_id
            opponent = game["away"] if is_home else game["home"]
            game = {**game, "is_home": is_home, "opponent": opponent}
        out.append(game)
        if len(out) >= limit:
            break

    out.sort(key=lambda g: g["date"])
    response: Dict[str, Any] = {"games": out, "count": len(out)}
    if include_markers:
        # Markers are computed from the full unfiltered schedule so the
        # all-star/deadline/draft anchors don't shift when the user
        # narrows to one team.
        response["markers"] = _build_markers(all_rows)
    return response


@router.get("/next")
def next_game(team_id: str = Query(..., description="Team to find the next upcoming game for")) -> Dict[str, Any]:
    today = date.today()
    upcoming: List[Dict[str, Any]] = []
    for game in _load_all():
        if team_id not in (game["home"], game["away"]):
            continue
        if game["played"]:
            continue
        gd = _parse_date(game["date"])
        if gd is None or gd < today:
            continue
        is_home = game["home"] == team_id
        upcoming.append(
            {
                **game,
                "is_home": is_home,
                "opponent": game["away"] if is_home else game["home"],
            }
        )
    upcoming.sort(key=lambda g: g["date"])
    return {"game": upcoming[0] if upcoming else None}
