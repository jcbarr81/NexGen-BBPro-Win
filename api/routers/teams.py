"""Team list / detail endpoints sourced from ``teams.csv``."""

from __future__ import annotations

import csv
from typing import List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, Response

from utils.path_utils import get_base_dir, get_data_dir

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


@router.get("/{team_id}/logo")
def get_team_logo(team_id: str) -> Response:
    """Serve a team's generated logo PNG from ``<base>/logo/teams``.

    Returns 204 when no logo has been generated yet so the client can cleanly
    fall back to the colored-abbreviation badge instead of error handling.
    """

    clean = team_id.strip().lower()
    if not clean or "/" in clean or "\\" in clean or ".." in clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid team id."
        )
    path = get_base_dir() / "logo" / "teams" / f"{clean}.png"
    if not path.exists():
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return FileResponse(
        str(path),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )
