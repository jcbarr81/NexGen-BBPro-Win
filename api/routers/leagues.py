"""League registry + active-league endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import List

from fastapi import APIRouter, HTTPException, status

from services import league_registry
from utils import path_utils

from ..schemas import LeagueRecordOut
from ..security import CurrentIdentity

router = APIRouter(prefix="/leagues", tags=["leagues"], dependencies=[CurrentIdentity])


@router.get("", response_model=List[LeagueRecordOut])
def list_leagues() -> List[LeagueRecordOut]:
    records = league_registry.list_leagues()
    return [LeagueRecordOut(**asdict(record)) for record in records]


@router.get("/active")
def get_active() -> dict:
    return {"league_id": path_utils.get_active_league_id()}


@router.post("/active/{league_id}")
def set_active(league_id: str) -> dict:
    record = league_registry.get_league(league_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown league")
    path_utils.set_active_league_id(league_id)
    return {"league_id": path_utils.get_active_league_id()}
