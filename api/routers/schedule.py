"""Schedule endpoint.

Ports the data side of ``ui/schedule_page.py``: lists games from
``schedule.csv`` with optional team / date filters, plus a helper for the
next upcoming matchup used by the dashboard hero.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from utils.path_utils import get_data_dir

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


@router.get("")
def list_schedule(
    team_id: Optional[str] = Query(default=None, description="Only games for this team"),
    start: Optional[str] = Query(default=None, description="YYYY-MM-DD inclusive"),
    end: Optional[str] = Query(default=None, description="YYYY-MM-DD inclusive"),
    played: Optional[bool] = Query(default=None, description="Filter by played flag"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> Dict[str, Any]:
    start_date = _parse_date(start) if start else None
    end_date = _parse_date(end) if end else None

    out: List[Dict[str, Any]] = []
    for game in _load_all():
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
    return {"games": out, "count": len(out)}


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
