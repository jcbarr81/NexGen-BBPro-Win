"""League-wide standings grouped by division.

Ports the data side of ``ui/standings_screen.py`` / the league standings
widget. We reuse ``services.standings_repository.load_standings`` plus
``teams.csv`` metadata and return divisions sorted by win pct.
"""

from __future__ import annotations

import csv
from typing import Any, Dict, List

from fastapi import APIRouter

from services.standings_repository import load_standings
from utils.path_utils import get_data_dir

from ..security import CurrentIdentity

router = APIRouter(prefix="/standings", tags=["standings"], dependencies=[CurrentIdentity])


def _load_team_meta() -> Dict[str, Dict[str, str]]:
    path = get_data_dir() / "teams.csv"
    if not path.exists():
        return {}
    meta: Dict[str, Dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            team_id = str(row.get("team_id", "")).strip()
            if not team_id:
                continue
            meta[team_id] = {
                "team_id": team_id,
                "name": row.get("name", ""),
                "city": row.get("city", ""),
                "abbreviation": row.get("abbreviation", ""),
                "division": row.get("division", "") or "—",
                "primary_color": row.get("primary_color", ""),
            }
    return meta


def _format_streak(record: Dict[str, Any]) -> str:
    streak = record.get("streak") or {}
    try:
        result = str(streak.get("result", "")).upper()
        length = int(streak.get("length", 0) or 0)
        if result in {"W", "L"} and length > 0:
            return f"{result}{length}"
    except Exception:
        pass
    return "--"


def _format_last10(record: Dict[str, Any]) -> str:
    raw = record.get("last10")
    if isinstance(raw, list) and raw:
        wins = sum(1 for item in raw if str(item).upper().startswith("W"))
        losses = sum(1 for item in raw if str(item).upper().startswith("L"))
        if wins or losses:
            return f"{wins}-{losses}"
    return "--"


@router.get("/league")
def league_standings() -> Dict[str, Any]:
    """Return standings grouped by division."""

    standings = load_standings(base_path=get_data_dir())
    meta = _load_team_meta()

    # Build per-division list of rows.
    divisions: Dict[str, List[Dict[str, Any]]] = {}
    for team_id, info in meta.items():
        division = info.get("division") or "—"
        record = standings.get(team_id) or {}
        wins = int(record.get("wins", 0) or 0)
        losses = int(record.get("losses", 0) or 0)
        runs_for = int(record.get("runs_for", 0) or 0)
        runs_against = int(record.get("runs_against", 0) or 0)
        games = wins + losses
        pct = wins / games if games else 0.0
        divisions.setdefault(division, []).append(
            {
                "team_id": team_id,
                "name": info.get("name", ""),
                "city": info.get("city", ""),
                "abbreviation": info.get("abbreviation", team_id),
                "primary_color": info.get("primary_color", ""),
                "wins": wins,
                "losses": losses,
                "pct": round(pct, 3),
                "runs_for": runs_for,
                "runs_against": runs_against,
                "run_diff": runs_for - runs_against,
                "streak": _format_streak(record),
                "last10": _format_last10(record),
            }
        )

    # Sort teams within each division and compute games behind.
    out_divisions: List[Dict[str, Any]] = []
    for division, rows in divisions.items():
        rows.sort(key=lambda r: (-r["pct"], -r["wins"]))
        if rows:
            leader_w = rows[0]["wins"]
            leader_l = rows[0]["losses"]
            for r in rows:
                gb = ((leader_w - r["wins"]) + (r["losses"] - leader_l)) / 2
                if abs(gb) < 1e-6:
                    r["gb"] = "—"
                else:
                    r["gb"] = f"{gb:.1f}".rstrip("0").rstrip(".")
        out_divisions.append({"division": division, "teams": rows})

    # Divisions themselves sorted alphabetically for stable order.
    out_divisions.sort(key=lambda d: d["division"])
    return {"divisions": out_divisions}
