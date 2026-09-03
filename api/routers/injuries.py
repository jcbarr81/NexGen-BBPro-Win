"""Injury center endpoint.

Surfaces a team's DL + IR rosters with descriptions, list type, return
date, days remaining, and rehab status. Reuses the same helpers the PyQt
``ui/injury_center_window.py`` calls.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status

from services.injury_manager import (
    disabled_list_days_remaining,
    disabled_list_label,
    is_player_dl_eligible,
)
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster

from ..security import CurrentIdentity

router = APIRouter(prefix="/teams/{team_id}", tags=["injuries"], dependencies=[CurrentIdentity])


def _sim_today() -> date:
    """The league's current date — the clock the injured list is measured in."""

    try:
        from utils.sim_date import get_current_sim_date

        sim_date = (get_current_sim_date() or "").strip()
        if sim_date:
            return date.fromisoformat(sim_date[:10])
    except Exception:  # pragma: no cover - defensive
        pass
    return date.today()


def _player_block(player: Any, level: str, dl_tier: str | None) -> Dict[str, Any]:
    today = _sim_today()
    days_remaining: int | None = None
    try:
        days_remaining = disabled_list_days_remaining(player, today)
    except Exception:
        days_remaining = None
    eligible = False
    try:
        eligible = bool(is_player_dl_eligible(player, today))
    except Exception:
        eligible = False
    return {
        "player_id": getattr(player, "player_id", ""),
        "first_name": getattr(player, "first_name", ""),
        "last_name": getattr(player, "last_name", ""),
        "primary_position": getattr(player, "primary_position", ""),
        "is_pitcher": bool(getattr(player, "is_pitcher", False)),
        "level": level,
        "dl_tier": dl_tier,
        "list_label": disabled_list_label(dl_tier or ""),
        "injury_description": getattr(player, "injury_description", "") or "",
        "return_date": getattr(player, "return_date", "") or "",
        "injury_eligible_date": getattr(player, "injury_eligible_date", "") or "",
        "injury_start_date": getattr(player, "injury_start_date", "") or "",
        "injury_minimum_days": getattr(player, "injury_minimum_days", "") or "",
        "rehab_assignment": bool(getattr(player, "injury_rehab_assignment", False)),
        "rehab_days": int(getattr(player, "injury_rehab_days", 0) or 0),
        "days_remaining": days_remaining,
        "dl_eligible": eligible,
    }


@router.get("/injuries")
def team_injuries(team_id: str) -> Dict[str, Any]:
    try:
        roster = load_roster(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load roster for {team_id}: {exc}",
        ) from exc

    try:
        players_by_id = {
            getattr(p, "player_id", ""): p
            for p in load_players_from_csv("data/players.csv")
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load players.csv: {exc}",
        ) from exc

    dl: List[Dict[str, Any]] = []
    for pid in roster.dl:
        player = players_by_id.get(pid)
        if player is None:
            continue
        dl.append(_player_block(player, "DL", roster.dl_tiers.get(pid, "dl15")))

    ir: List[Dict[str, Any]] = []
    for pid in roster.ir:
        player = players_by_id.get(pid)
        if player is None:
            continue
        ir.append(_player_block(player, "IR", "ir"))

    # Also surface ACT players flagged as injured (day-to-day) so the
    # owner can see them in one place even when not on a list.
    day_to_day: List[Dict[str, Any]] = []
    for pid in roster.act:
        player = players_by_id.get(pid)
        if player is None:
            continue
        if bool(getattr(player, "injured", False)):
            day_to_day.append(_player_block(player, "ACT", None))

    eligible_to_activate = sum(1 for p in dl if p.get("dl_eligible"))
    return {
        "team_id": team_id,
        "counts": {
            "dl": len(dl),
            "ir": len(ir),
            "day_to_day": len(day_to_day),
            "eligible_to_activate": eligible_to_activate,
        },
        "dl": dl,
        "ir": ir,
        "day_to_day": day_to_day,
    }
