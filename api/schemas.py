"""Pydantic response models.

Kept in one file for Phase 1 -- will split into ``api/schemas/*.py`` as the
surface grows in later phases.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    data_root: str
    active_league: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str
    team_id: str = ""


class LeagueRecordOut(BaseModel):
    id: str
    display_name: str
    mode: str
    status: str
    created_at: str
    last_opened_at: Optional[str] = None
    version_created: Optional[str] = None
    version_last_opened: Optional[str] = None


class TeamOut(BaseModel):
    team_id: str
    name: str
    city: str
    abbreviation: str
    division: str
    stadium: str
    primary_color: str
    secondary_color: str
    owner_id: str = ""


class PlayerSummary(BaseModel):
    player_id: str
    first_name: str
    last_name: str
    primary_position: str
    is_pitcher: bool = False
    bats: str = ""
    role: str = ""
    # Surface only headline ratings in the list view; detail endpoint can
    # hydrate the full row.
    ratings: Dict[str, Any] = Field(default_factory=dict)


class StandingsEntry(BaseModel):
    team_id: str
    wins: int = 0
    losses: int = 0
    ties: int = 0
    pct: float = 0.0
    division: str = ""
