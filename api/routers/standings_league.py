"""League-wide standings grouped by division.

Ports the data side of ``ui/standings_screen.py`` / the league standings
widget. We reuse ``services.standings_repository.load_standings`` plus
``teams.csv`` metadata and return divisions sorted by win pct.
"""

from __future__ import annotations

import csv
from typing import Any, Dict, List

from fastapi import APIRouter

from services.standings_form import streak_last10_from_schedule
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


def _games_remaining_by_team() -> Dict[str, int]:
    """Count unplayed games per team_id from schedule.csv."""

    remaining: Dict[str, int] = {}
    schedule_path = get_data_dir() / "schedule.csv"
    if not schedule_path.exists():
        return remaining
    try:
        with schedule_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                played_flag = str(row.get("played", "")).strip().lower() in {
                    "1",
                    "true",
                    "yes",
                }
                has_result = bool(str(row.get("result", "")).strip())
                if played_flag or has_result:
                    continue
                for key in ("home", "away"):
                    tid = str(row.get(key, "") or "").strip()
                    if tid:
                        remaining[tid] = remaining.get(tid, 0) + 1
    except OSError:
        return remaining
    return remaining


@router.get("/league")
def league_standings() -> Dict[str, Any]:
    """Return standings grouped by division.

    Each row carries the canonical W/L/pct/streak fields plus
    ``games_remaining`` and either:
      - ``status="clinched_division"`` and ``magic_number=0`` for a
        team that has clinched
      - ``status="leader"`` and ``magic_number=N`` (games needed to
        clinch over the runner-up) for the division leader
      - ``status="in_race"`` and ``magic_number=N`` (elimination
        number — combined leader-wins-plus-this-team's-losses needed
        to eliminate this team) for chasers
      - ``status="eliminated"`` and ``magic_number=0`` for chasers
        whose best-possible record can't catch the leader
    """

    standings = load_standings(base_path=get_data_dir())
    meta = _load_team_meta()
    remaining_map = _games_remaining_by_team()
    sched_form = streak_last10_from_schedule()

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
                # Prefer a persisted streak/last10 if the record ever carries
                # one; otherwise reconstruct from the played schedule.
                "streak": (
                    _format_streak(record)
                    if _format_streak(record) != "--"
                    else sched_form.get(team_id, {}).get("streak", "--")
                ),
                "last10": (
                    _format_last10(record)
                    if _format_last10(record) != "--"
                    else sched_form.get(team_id, {}).get("last10", "--")
                ),
                "games_remaining": int(remaining_map.get(team_id, 0)),
            }
        )

    # Sort teams within each division and compute games behind +
    # magic numbers + clinch / elimination status.
    out_divisions: List[Dict[str, Any]] = []
    for division, rows in divisions.items():
        rows.sort(key=lambda r: (-r["pct"], -r["wins"]))
        if rows:
            leader = rows[0]
            leader_w = leader["wins"]
            leader_l = leader["losses"]
            leader_remaining = leader["games_remaining"]
            leader_max_wins = leader_w + leader_remaining
            for r in rows:
                gb = ((leader_w - r["wins"]) + (r["losses"] - leader_l)) / 2
                if abs(gb) < 1e-6:
                    r["gb"] = "—"
                else:
                    r["gb"] = f"{gb:.1f}".rstrip("0").rstrip(".")

            # Leader's magic number = games to clinch over the closest
            # plausible chaser (the runner-up by current standings).
            if len(rows) >= 2:
                runner = rows[1]
                runner_max_wins = runner["wins"] + runner["games_remaining"]
                magic_to_clinch = max(
                    0, (runner_max_wins - leader_w) + 1,
                )
                if magic_to_clinch == 0:
                    leader["status"] = "clinched_division"
                    leader["magic_number"] = 0
                else:
                    leader["status"] = "leader"
                    leader["magic_number"] = magic_to_clinch
            else:
                # Single-team division — leader trivially clinches.
                leader["status"] = "clinched_division"
                leader["magic_number"] = 0

            # Non-leaders: eliminated if best-possible < leader's
            # current wins; otherwise their tragic number is leader's
            # remaining wins to clinch.
            for r in rows[1:]:
                best_possible = r["wins"] + r["games_remaining"]
                if best_possible < leader_w:
                    r["status"] = "eliminated"
                    r["magic_number"] = 0
                else:
                    r["status"] = "in_race"
                    # Elimination number: combined leader wins + this
                    # team's losses needed to put them out.
                    elim = max(0, leader_max_wins - best_possible + 1)
                    r["magic_number"] = elim
        out_divisions.append({"division": division, "teams": rows})

    # Divisions themselves sorted alphabetically for stable order.
    out_divisions.sort(key=lambda d: d["division"])
    return {"divisions": out_divisions}
