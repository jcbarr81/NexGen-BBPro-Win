"""Exhibition game simulator (admin).

One-off game simulation outside the schedule — "what if" tool. Wraps
``playbalance.game_runner.run_single_game`` and saves an HTML boxscore
like the sim loop does, so the result links into /boxscore like any
regular game.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from utils.path_utils import get_data_dir

from ..security import require_bearer

router = APIRouter(prefix="/exhibition", tags=["exhibition"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


@router.post("/simulate")
async def simulate_exhibition(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    home_id = str(payload.get("home_team", "")).strip()
    away_id = str(payload.get("away_team", "")).strip()
    if not home_id or not away_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="home_team and away_team are required.",
        )
    if home_id == away_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="home_team and away_team must be different.",
        )

    # Lazy import so the sidecar boots cheap even if playbalance.game_runner
    # has heavy deps at import time.
    try:
        from playbalance.game_runner import run_single_game
        from playbalance.simulation import save_boxscore_html
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Exhibition engine unavailable: {exc}",
        ) from exc

    data_dir = get_data_dir()
    try:
        home_state, away_state, box, html, meta = await asyncio.to_thread(
            run_single_game,
            home_id,
            away_id,
            players_file=str(data_dir / "players.csv"),
            roster_dir=str(data_dir / "rosters"),
            lineup_dir=str(data_dir / "lineups"),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing data: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Simulation failed: {exc}",
        ) from exc

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        boxscore_path = await asyncio.to_thread(
            save_boxscore_html, "exhibition", html, timestamp
        )
    except Exception:
        boxscore_path = None

    # Serialize the box score to JSON-safe primitives. The Player objects
    # come back live; we just pull the fields the UI needs.
    def _summarize_batter(entry: Dict[str, Any]) -> Dict[str, Any]:
        p = entry.get("player")
        return {
            "player_id": getattr(p, "player_id", ""),
            "name": f"{getattr(p, 'first_name', '')} {getattr(p, 'last_name', '')}".strip(),
            "ab": entry.get("ab", 0),
            "h": entry.get("h", 0),
            "bb": entry.get("bb", 0),
            "so": entry.get("so", 0),
            "sb": entry.get("sb", 0),
        }

    def _summarize_pitcher(entry: Dict[str, Any]) -> Dict[str, Any]:
        p = entry.get("player")
        return {
            "player_id": getattr(p, "player_id", ""),
            "name": f"{getattr(p, 'first_name', '')} {getattr(p, 'last_name', '')}".strip(),
            "pitches": entry.get("pitches", 0),
            "bb": entry.get("bb", 0),
            "so": entry.get("so", 0),
        }

    def _side(side_key: str) -> Dict[str, Any]:
        side = box.get(side_key, {}) if isinstance(box, dict) else {}
        return {
            "score": side.get("score", 0),
            "batting": [_summarize_batter(e) for e in side.get("batting", []) or []],
            "pitching": [_summarize_pitcher(e) for e in side.get("pitching", []) or []],
        }

    return {
        "home_team": home_id,
        "away_team": away_id,
        "home": _side("home"),
        "away": _side("away"),
        "boxscore_path": str(boxscore_path) if boxscore_path else None,
        "debug_log": list(meta.get("debug_log", []) or []) if isinstance(meta, dict) else [],
        "field_positions": dict(meta.get("field_positions", {}) or {})
        if isinstance(meta, dict)
        else {},
    }
