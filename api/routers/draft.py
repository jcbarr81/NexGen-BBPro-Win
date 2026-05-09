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
                # CSV header (written by services.draft_state.append_result)
                # is ``round, overall_pick, team_id, player_id``. Tolerate
                # the legacy ``overall`` key for old files imported by hand.
                overall_raw = row.get("overall_pick")
                if overall_raw in (None, ""):
                    overall_raw = row.get("overall", 0)
                rows.append(
                    {
                        "overall": int(overall_raw or 0),
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


@router.get("/pool")
def draft_pool_view(
    year: Optional[int] = Query(default=None),
    available_only: bool = Query(default=True),
    limit: int = Query(default=500, ge=1, le=5000),
) -> Dict[str, Any]:
    """List prospects in this year's draft pool.

    Defaults to showing only un-drafted players sorted by overall (best
    first), since that's what the live draft UI needs to populate the
    pick-selector. Pass ``available_only=false`` to include drafted
    players too — useful for browsing post-draft.
    """

    from playbalance.draft_pool import load_draft_pool

    y = _resolve_year(year)
    pool = load_draft_pool(y)
    if not pool:
        return {"year": y, "count": 0, "prospects": []}

    state = draft_state.load_state(y) or {}
    taken: set[str] = set()
    for entry in state.get("selected") or []:
        if isinstance(entry, dict):
            pid = str(entry.get("player_id") or "").strip()
            if pid:
                taken.add(pid)

    rows: List[Dict[str, Any]] = []
    for prospect in pool:
        pid = str(prospect.get("player_id", "")).strip()
        if not pid:
            continue
        is_taken = pid in taken
        if available_only and is_taken:
            continue
        is_pitcher = str(prospect.get("is_pitcher", "")).lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        birthdate = str(prospect.get("birthdate", "") or "").strip()
        age: Optional[int] = None
        if birthdate:
            try:
                from datetime import date as _date

                bd = _date.fromisoformat(birthdate[:10])
                today = _date.today()
                age = (
                    today.year
                    - bd.year
                    - ((today.month, today.day) < (bd.month, bd.day))
                )
            except Exception:
                age = None
        rows.append(
            {
                "player_id": pid,
                "first_name": prospect.get("first_name", ""),
                "last_name": prospect.get("last_name", ""),
                "primary_position": prospect.get("primary_position", ""),
                "is_pitcher": is_pitcher,
                "bats": prospect.get("bats", ""),
                "throws": prospect.get("throws", ""),
                "birthdate": birthdate,
                "age": age,
                "overall": _prospect_overall(prospect),
                "available": not is_taken,
                "ratings": {
                    k: prospect.get(k)
                    for k in (
                        "ch",
                        "ph",
                        "sp",
                        "eye",
                        "fa",
                        "arm",
                        "fb",
                        "sl",
                        "cu",
                        "cb",
                        "si",
                        "control",
                        "movement",
                        "endurance",
                    )
                    if prospect.get(k) not in (None, "")
                },
            }
        )

    rows.sort(key=lambda r: int(r.get("overall") or 0), reverse=True)
    return {"year": y, "count": len(rows), "prospects": rows[:limit]}


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
    # Year 2+ pulls from the prior season's archived final standings;
    # year 1 (or any year missing an archive) falls back to the current
    # season's running stats. Mirrors the MLB convention of drafting
    # order based on the previous year's record.
    order = draft_state.compute_order_for_draft_year(year, seed=seed_int)
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
        from playbalance.draft_pool import generate_draft_pool, save_draft_pool

        pool = generate_draft_pool(year=year, size=size)
        # generate_draft_pool returns the in-memory list — actually persist
        # it so the live draft pool endpoint and pick endpoints can find
        # it on disk as ``draft_pool_<year>.{csv,json}``.
        save_draft_pool(year, pool)
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


# ---------------------------------------------------------------------------
# Pick-by-pick draft flow (single-player + future multi-owner foundation).


def _team_on_clock(state: Dict[str, Any]) -> Optional[str]:
    order: List[str] = list(state.get("order") or [])
    if not order:
        return None
    overall = int(state.get("overall_pick", 1) or 1)
    return order[(overall - 1) % len(order)]


def _selected_ids(state: Dict[str, Any]) -> set[str]:
    selected = state.get("selected") or []
    out: set[str] = set()
    for entry in selected:
        if isinstance(entry, dict):
            pid = str(entry.get("player_id") or "").strip()
            if pid:
                out.add(pid)
    return out


def _draft_complete(state: Dict[str, Any], total_rounds: int) -> bool:
    return int(state.get("round", 1) or 1) > max(1, total_rounds)


def _load_settings_rounds() -> int:
    try:
        from services.draft_settings import load_draft_settings

        return int(load_draft_settings().rounds)
    except Exception:
        return 10


def _prospect_overall(prospect: Dict[str, Any]) -> int:
    """Crude best-available score: max of hitter chunk vs pitcher chunk."""

    is_pitcher = str(prospect.get("is_pitcher", "")).lower() in {
        "1",
        "true",
        "yes",
        "y",
    }
    try:
        if is_pitcher:
            keys = ("control", "movement", "endurance", "fb", "arm")
        else:
            keys = ("ch", "ph", "sp", "eye", "fa", "arm")
        values = []
        for k in keys:
            v = prospect.get(k)
            if v in (None, ""):
                continue
            try:
                values.append(int(v))
            except (TypeError, ValueError):
                continue
        if not values:
            return 0
        return sum(values) // len(values)
    except Exception:
        return 0


def _best_available(year: int, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from playbalance.draft_pool import load_draft_pool

    pool = load_draft_pool(year)
    if not pool:
        return None
    taken = _selected_ids(state)
    candidates = [p for p in pool if str(p.get("player_id", "")) not in taken]
    if not candidates:
        return None
    candidates.sort(key=_prospect_overall, reverse=True)
    return candidates[0]


def _do_pick(
    year: int,
    state: Dict[str, Any],
    *,
    player_id: str,
    season_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a pick + commit it to the team's roster. Mutates ``state``."""

    order: List[str] = list(state.get("order") or [])
    if not order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft order is empty.",
        )
    rnd = int(state.get("round", 1) or 1)
    overall = int(state.get("overall_pick", 1) or 1)
    team_id = order[(overall - 1) % len(order)]

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

    commit_summary: Dict[str, Any] = {}
    try:
        from services.draft_assignment import commit_single_pick

        commit_summary = commit_single_pick(
            year,
            team_id=team_id,
            player_id=player_id,
            round_number=rnd,
            overall_pick=overall,
            season_date=season_date,
        )
    except Exception as exc:  # pragma: no cover - defensive
        commit_summary = {"error": str(exc)}

    return {
        "year": year,
        "round": rnd,
        "overall": overall,
        "team_id": team_id,
        "player_id": player_id,
        "commit": commit_summary,
    }


def _ensure_pick_authorized(
    identity: Dict[str, Any],
    state: Dict[str, Any],
) -> str:
    """Return the team_id on the clock if the caller may act for it.

    Admins can act on any pick. Owners can only act on their own team.
    """

    role = str(identity.get("r", "")).lower()
    team_on_clock = _team_on_clock(state)
    if not team_on_clock:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft order is empty.",
        )
    if role == "admin":
        return team_on_clock
    callers_team = str(identity.get("t", "")).strip()
    if callers_team and callers_team == team_on_clock:
        return team_on_clock
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"It's {team_on_clock}'s pick — only that team's owner (or an admin) "
            "can submit it."
        ),
    )


@router.post("/pick")
def make_pick(
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Submit the pick for the team currently on the clock.

    Caller must be either an admin OR the owner of the team on the clock.
    Validates the player is in the pool and not already selected.
    """

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
    rounds_total = _load_settings_rounds()
    if _draft_complete(state, rounds_total):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft is already complete.",
        )
    _ensure_pick_authorized(identity, state)

    # Validate the player is a real, still-available prospect.
    from playbalance.draft_pool import load_draft_pool

    pool = load_draft_pool(year)
    pool_ids = {str(p.get("player_id", "")) for p in pool}
    if pool_ids and player_id not in pool_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{player_id} is not in this year's draft pool.",
        )
    if player_id in _selected_ids(state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{player_id} has already been picked.",
        )

    return _do_pick(year, state, player_id=player_id)


@router.post("/auto-pick")
def auto_pick(
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Pick best-available for whichever team is on the clock right now."""

    year = int(payload.get("year") or _resolve_year(None))
    state = draft_state.load_state(year)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active draft state for that year.",
        )
    rounds_total = _load_settings_rounds()
    if _draft_complete(state, rounds_total):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft is already complete.",
        )
    _ensure_pick_authorized(identity, state)

    best = _best_available(year, state)
    if not best:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft pool is empty (or all players already picked).",
        )
    return _do_pick(year, state, player_id=str(best.get("player_id", "")))


@router.post("/auto-advance")
def auto_advance(
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Run CPU auto-picks until the requested stop condition.

    ``stop`` (default ``"my_pick"``) controls when the loop halts:

    - ``"my_pick"`` — stop as soon as the caller's team is on the clock
    - ``"end_of_round"`` — stop when the active round changes
    - ``"end_of_draft"`` — pick to the end of the draft

    Admins running ``"my_pick"`` may pass ``team_id`` to specify which
    team's turn to wait for; otherwise we use the caller's identity team.
    Hard cap of 2,000 picks per call so a misconfigured order can't spin.
    """

    year = int(payload.get("year") or _resolve_year(None))
    stop_mode = str(payload.get("stop", "my_pick")).strip().lower() or "my_pick"
    if stop_mode not in {"my_pick", "end_of_round", "end_of_draft"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stop mode: {stop_mode!r}",
        )

    state = draft_state.load_state(year)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active draft state for that year.",
        )

    rounds_total = _load_settings_rounds()
    role = str(identity.get("r", "")).lower()
    target_team: Optional[str] = None
    if stop_mode == "my_pick":
        target_team = (
            str(payload.get("team_id", "")).strip()
            or str(identity.get("t", "")).strip()
            or None
        )
        if role != "admin" and not target_team:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Auto-advance to 'my_pick' needs a team_id (no team is "
                    "associated with this user)."
                ),
            )

    starting_round = int(state.get("round", 1) or 1)

    picks_made: List[Dict[str, Any]] = []
    cap = 2000
    while len(picks_made) < cap:
        if _draft_complete(state, rounds_total):
            break
        on_clock = _team_on_clock(state)
        if on_clock is None:
            break
        # Stop conditions checked BEFORE picking so we don't pick for the
        # owner's team (they should choose).
        if stop_mode == "my_pick" and target_team and on_clock == target_team:
            break
        if stop_mode == "end_of_round" and int(state.get("round", 1) or 1) != starting_round:
            break

        best = _best_available(year, state)
        if not best:
            break
        try:
            result = _do_pick(year, state, player_id=str(best.get("player_id", "")))
        except HTTPException:
            break
        picks_made.append(result)

    return {
        "year": year,
        "stop": stop_mode,
        "target_team": target_team,
        "picks": picks_made,
        "picks_made": len(picks_made),
        "draft_complete": _draft_complete(state, rounds_total),
        "team_on_clock": _team_on_clock(state),
        "round": int(state.get("round", 1) or 1),
        "overall_pick": int(state.get("overall_pick", 1) or 1),
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
