"""League + team record book endpoints, and a club's postseason history."""

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


@router.get("/teams/{team_id}/postseason")
def get_team_postseason(team_id: str) -> Dict[str, Any]:
    """The club's postseason runs, newest first (8.4.0): W-L, runs, how far
    it went, its series and its top hitters and pitchers in each. Empty
    when it never reached one."""

    from services.postseason_stats import club_postseasons

    return {"team_id": team_id.upper(), "postseasons": club_postseasons(team_id)}
