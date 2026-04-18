"""League + team record book endpoints."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from services.record_book import league_record_book, team_record_book

from ..security import CurrentIdentity

router = APIRouter(tags=["records"], dependencies=[CurrentIdentity])


@router.get("/league/records")
def get_league_records() -> Dict[str, Any]:
    return {"records": league_record_book()}


@router.get("/teams/{team_id}/records")
def get_team_records(team_id: str) -> Dict[str, Any]:
    return {"team_id": team_id, "records": team_record_book(team_id)}
