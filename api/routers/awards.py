"""Awards endpoints — surface MVP/Cy Young/ROY/Manager-of-the-Year etc.

`AwardsManager` already computes winners during the season-end rollover
and writes them to ``<careers>/<season_id>/awards.json``. These endpoints
just read those files back so the UI has something to render — without
this, the awards exist on disk but no part of the React app ever shows
them.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from playbalance.season_context import CAREER_DATA_DIR, SeasonContext

from ..security import CurrentIdentity

router = APIRouter(prefix="/awards", tags=["awards"], dependencies=[CurrentIdentity])


def _load_awards_file(season_dir: str) -> Dict[str, Any]:
    path = CAREER_DATA_DIR / season_dir / "awards.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _flatten_winners(awards_block: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    block = awards_block.get("awards") if isinstance(awards_block, dict) else {}
    if not isinstance(block, dict):
        return rows
    for award_name, winner in block.items():
        if not isinstance(winner, dict):
            continue
        rows.append(
            {
                "award": str(award_name),
                "player_id": str(winner.get("player_id") or ""),
                "player_name": str(winner.get("player_name") or ""),
                "metric": str(winner.get("metric") or ""),
            }
        )
    return rows


@router.get("")
def list_awards(
    year: Optional[int] = Query(default=None, description="Filter to one league year"),
) -> Dict[str, Any]:
    """List archived season awards, newest year first.

    Each season returns ``{season_id, league_year, awards: [{award, player_id, player_name, metric}]}``.
    Pass ``year`` to restrict to a single season.
    """

    try:
        ctx = SeasonContext.load()
    except Exception:
        return {"seasons": []}

    seasons: List[Dict[str, Any]] = []
    for season in ctx.iter_archived_seasons():
        season_id = str(season.get("season_id") or "")
        if not season_id:
            continue
        league_year = season.get("league_year")
        try:
            league_year_int = int(league_year) if league_year is not None else None
        except (TypeError, ValueError):
            league_year_int = None
        if year is not None and league_year_int != int(year):
            continue
        payload = _load_awards_file(season_id)
        rows = _flatten_winners(payload)
        if not rows:
            continue
        seasons.append(
            {
                "season_id": season_id,
                "league_year": league_year_int,
                "awards": rows,
            }
        )

    seasons.sort(key=lambda s: (s.get("league_year") or 0), reverse=True)
    return {"seasons": seasons}
