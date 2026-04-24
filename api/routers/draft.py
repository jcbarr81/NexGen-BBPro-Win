"""Draft endpoints.

Read-only surface over ``services.draft_state`` plus the finalized results
CSV. If no state exists yet (pre-draft or in-memory only), the response
still returns a well-formed empty structure so the UI can render gracefully.
"""

from __future__ import annotations

import csv
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, status

from services import draft_state
from services.trade_settings import current_league_year
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv

from ..security import CurrentIdentity
from ._rating_presentation import compute_overall

router = APIRouter(prefix="/draft", tags=["draft"], dependencies=[CurrentIdentity])


def _resolve_year(year: Optional[int]) -> int:
    if year and year > 0:
        return year
    try:
        return int(current_league_year())
    except Exception:
        from datetime import date

        return date.today().year


def _player_lookup() -> Dict[str, Any]:
    """Cache players.csv by id for the duration of one request so pick rows
    can carry player metadata without N+1 load_players calls."""

    try:
        players = load_players_from_csv("data/players.csv")
    except Exception:
        return {}
    return {getattr(p, "player_id", ""): p for p in players}


def _load_results(year: int) -> List[Dict[str, Any]]:
    path = get_data_dir() / f"draft_results_{year}.csv"
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append(
                    {
                        "overall": int(row.get("overall", 0) or 0),
                        "round": int(row.get("round", 0) or 0),
                        "team_id": str(row.get("team_id", "")).strip(),
                        "player_id": str(row.get("player_id", "")).strip(),
                    }
                )
    except OSError:
        return []
    rows.sort(key=lambda r: r["overall"])

    # Join each pick with its player's name + position + overall display so
    # the UI can render stars inline with the pick card, matching the
    # PyQt draft_console presentation.
    players = _player_lookup()
    for row in rows:
        player = players.get(row["player_id"])
        if player is None:
            row["first_name"] = ""
            row["last_name"] = ""
            row["primary_position"] = ""
            row["is_pitcher"] = False
            row["overall_raw"] = None
            row["overall_display"] = None
            row["overall_stars_text"] = None
            continue
        is_pitcher = bool(getattr(player, "is_pitcher", False))
        position = getattr(player, "primary_position", None)
        overall = compute_overall(
            lambda k, p=player: getattr(p, k, None),
            is_pitcher=is_pitcher,
            position=position,
        )
        row["first_name"] = getattr(player, "first_name", "") or ""
        row["last_name"] = getattr(player, "last_name", "") or ""
        row["primary_position"] = position or ""
        row["is_pitcher"] = is_pitcher
        row["overall_raw"] = overall["overall_raw"]
        row["overall_display"] = overall["overall_display"]
        row["overall_stars_text"] = overall["overall_stars_text"]
    return rows


@router.get("/state")
def draft_state_view(
    year: Optional[int] = Query(default=None, description="Defaults to current league year"),
) -> Dict[str, Any]:
    from services.draft_settings import load_draft_settings

    y = _resolve_year(year)
    state = draft_state.load_state(y) or {}
    order = list(state.get("order") or [])
    selected = list(state.get("selected") or [])
    settings = load_draft_settings()
    return {
        "year": y,
        "round": int(state.get("round", 1) or 1),
        "overall_pick": int(state.get("overall_pick", 1) or 1),
        "seed": state.get("seed"),
        "order": order,
        "selected": selected,
        "exists": bool(state),
        "configured_rounds": settings.rounds,
        "configured_pool_size": settings.pool_size,
    }


@router.get("/results")
def draft_results_view(
    year: Optional[int] = Query(default=None, description="Defaults to current league year"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> Dict[str, Any]:
    y = _resolve_year(year)
    rows = _load_results(y)[:limit]
    return {"year": y, "count": len(rows), "picks": rows}


# ---------------------------------------------------------------------------
# Admin-only draft controls.
from fastapi import Depends

from ..security import require_bearer


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminDep = Depends(_require_admin)


@router.get("/settings")
def draft_settings_view() -> Dict[str, Any]:
    """Current draft config (rounds + pool size). Readable to any signed-in
    user so the league-create wizard can pre-populate defaults."""

    from services.draft_settings import (
        DEFAULT_POOL_SIZE,
        DEFAULT_ROUNDS,
        MAX_POOL_SIZE,
        MAX_ROUNDS,
        MIN_POOL_SIZE,
        MIN_ROUNDS,
        load_draft_settings,
    )

    settings = load_draft_settings()
    return {
        "rounds": settings.rounds,
        "pool_size": settings.pool_size,
        "limits": {
            "rounds": {"min": MIN_ROUNDS, "max": MAX_ROUNDS, "default": DEFAULT_ROUNDS},
            "pool_size": {
                "min": MIN_POOL_SIZE,
                "max": MAX_POOL_SIZE,
                "default": DEFAULT_POOL_SIZE,
            },
        },
    }


@router.put("/settings")
def draft_settings_save(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminDep,
) -> Dict[str, Any]:
    """Admin save of draft config."""

    from services.draft_settings import DraftSettings, save_draft_settings

    incoming = DraftSettings(
        rounds=int(payload.get("rounds", 0) or 0),
        pool_size=int(payload.get("pool_size", 0) or 0),
    )
    saved = save_draft_settings(incoming)
    return {"rounds": saved.rounds, "pool_size": saved.pool_size}


@router.post("/admin/initialize")
def admin_initialize(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminDep,
) -> Dict[str, Any]:
    """Seed a brand-new draft state for the given year."""

    year = int(payload.get("year") or _resolve_year(None))
    seed = payload.get("seed")
    try:
        seed_int = int(seed) if seed is not None else None
    except (TypeError, ValueError):
        seed_int = None
    order = draft_state.compute_order_from_season_stats(seed=seed_int)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot compute order — no season stats yet.",
        )
    state = draft_state.initialize_state(year, order=order, seed=seed_int)
    return {"year": year, "order": state.get("order"), "seed": state.get("seed")}


@router.post("/admin/reset")
def admin_reset(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminDep,
) -> Dict[str, Any]:
    """Clear draft state + results CSV for the given year."""

    year = int(payload.get("year") or _resolve_year(None))
    state_path = get_data_dir() / f"draft_state_{year}.json"
    results_path = get_data_dir() / f"draft_results_{year}.csv"
    for p in (state_path, results_path):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    return {"year": year, "reset": True}


@router.post("/admin/generate-pool")
def admin_generate_pool(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminDep,
) -> Dict[str, Any]:
    """Generate a fresh amateur draft pool of the configured size.

    Caller can pass ``pool_size`` to override the saved settings (one-off);
    otherwise we use the per-league default.
    """

    from services.draft_settings import load_draft_settings

    year = int(payload.get("year") or _resolve_year(None))
    settings = load_draft_settings()
    requested_size = payload.get("pool_size")
    try:
        size = int(requested_size) if requested_size is not None else settings.pool_size
    except (TypeError, ValueError):
        size = settings.pool_size

    try:
        from playbalance.draft_pool import generate_draft_pool

        # The underlying generator signature varies — most versions accept
        # ``year`` and ``count``/``size``. Call the simplest positional form
        # first, fall back to the year-only one if the signature's narrower.
        try:
            pool = generate_draft_pool(year=year, count=size)
        except TypeError:
            pool = generate_draft_pool(year=year)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pool generation failed: {exc}",
        ) from exc
    return {
        "year": year,
        "requested_size": size,
        "pool_size": len(pool) if hasattr(pool, "__len__") else 0,
    }


@router.post("/admin/manual-pick")
def admin_manual_pick(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminDep,
) -> Dict[str, Any]:
    """Commissioner override: assign a player to the current pick."""

    year = int(payload.get("year") or _resolve_year(None))
    player_id = str(payload.get("player_id", "")).strip()
    if not player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id is required.",
        )
    state = draft_state.load_state(year)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active draft state for that year.",
        )
    order: List[str] = list(state.get("order") or [])
    rnd = int(state.get("round", 1) or 1)
    overall = int(state.get("overall_pick", 1) or 1)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft order is empty.",
        )
    pick_idx = (overall - 1) % len(order)
    team_id = order[pick_idx]

    selected = list(state.get("selected") or [])
    selected.append(
        {"overall": overall, "round": rnd, "team_id": team_id, "player_id": player_id}
    )
    state["selected"] = selected
    state["overall_pick"] = overall + 1
    if (overall % len(order)) == 0:
        state["round"] = rnd + 1
    draft_state.save_state(year, state)
    draft_state.append_result(
        year, team_id=team_id, player_id=player_id, rnd=rnd, overall=overall
    )
    return {
        "year": year,
        "round": rnd,
        "overall": overall,
        "team_id": team_id,
        "player_id": player_id,
    }
