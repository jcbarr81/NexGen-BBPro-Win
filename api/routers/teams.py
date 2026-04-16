"""Team list / detail endpoints sourced from ``teams.csv``."""

from __future__ import annotations

import csv
from typing import List

from fastapi import APIRouter, HTTPException, status

from utils.path_utils import get_data_dir

from ..schemas import TeamOut
from ..security import CurrentIdentity

router = APIRouter(prefix="/teams", tags=["teams"], dependencies=[CurrentIdentity])


def _load_teams() -> List[TeamOut]:
    path = get_data_dir() / "teams.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        out: List[TeamOut] = []
        for row in reader:
            try:
                out.append(
                    TeamOut(
                        team_id=row["team_id"],
                        name=row.get("name", ""),
                        city=row.get("city", ""),
                        abbreviation=row.get("abbreviation", ""),
                        division=row.get("division", ""),
                        stadium=row.get("stadium", ""),
                        primary_color=row.get("primary_color", "#000000"),
                        secondary_color=row.get("secondary_color", "#FFFFFF"),
                        owner_id=row.get("owner_id", "") or "",
                    )
                )
            except Exception:
                # Skip malformed rows rather than failing the whole request.
                continue
    return out


@router.get("", response_model=List[TeamOut])
def list_teams() -> List[TeamOut]:
    return _load_teams()


@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: str) -> TeamOut:
    for team in _load_teams():
        if team.team_id.lower() == team_id.lower():
            return team
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
