"""Standings read endpoint backed by ``standings.json``."""

from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter

from utils.path_utils import get_data_dir

from ..file_lock import locked_read
from ..schemas import StandingsEntry
from ..security import CurrentIdentity

router = APIRouter(prefix="/standings", tags=["standings"], dependencies=[CurrentIdentity])


def _coerce_entry(raw: dict) -> StandingsEntry | None:
    team_id = str(raw.get("team_id") or raw.get("id") or "").strip()
    if not team_id:
        return None
    wins = int(raw.get("wins", 0) or 0)
    losses = int(raw.get("losses", 0) or 0)
    ties = int(raw.get("ties", 0) or 0)
    games = wins + losses + ties
    pct = float(wins / games) if games else 0.0
    return StandingsEntry(
        team_id=team_id,
        wins=wins,
        losses=losses,
        ties=ties,
        pct=round(pct, 3),
        division=str(raw.get("division", "") or ""),
    )


@router.get("", response_model=List[StandingsEntry])
def get_standings() -> List[StandingsEntry]:
    path = get_data_dir() / "standings.json"
    if not path.exists():
        return []
    with locked_read(path) as data:
        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            return []

    # Accept either {"teams": [...]} or a raw list.
    rows = payload.get("teams") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []

    out: List[StandingsEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry = _coerce_entry(row)
        if entry is not None:
            out.append(entry)
    return out
