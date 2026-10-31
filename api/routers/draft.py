"""Draft endpoints.

Read-only surface over ``services.draft_state`` plus the finalized results
CSV. If no state exists yet (pre-draft or in-memory only), the response
still returns a well-formed empty structure so the UI can render gracefully.
"""

from __future__ import annotations

import csv
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, HTTPException, Query, status

from services import draft_board, draft_clock, draft_state
from services.trade_settings import current_league_year
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.rating_display import display_rating, display_scale_for
from utils.player_overall import player_overall_score

from ..security import CurrentIdentity
from ._rating_presentation import compute_overall, page_scale

router = APIRouter(prefix="/draft", tags=["draft"], dependencies=[CurrentIdentity])


def _resolve_year(year: Optional[int]) -> int:
    if year and year > 0:
        return year
    upcoming = _upcoming_preseason_draft_year()
    if upcoming:
        return upcoming
    try:
        return int(current_league_year())
    except Exception:
        from datetime import date

        return date.today().year


def _upcoming_preseason_draft_year() -> Optional[int]:
    """The coming season's year, during the offseason of a preseason-draft league.

    Such a league generates the next draft class when the season rolls over
    so owners can scout it all offseason, but the new schedule (which is what
    ``current_league_year`` reads) does not exist until the preseason. The
    season context already knows the coming league year.
    """
    try:
        from services.draft_settings import (
            DRAFT_TIMING_PRESEASON,
            load_draft_settings,
        )

        if load_draft_settings().timing != DRAFT_TIMING_PRESEASON:
            return None
        from playbalance.season_manager import SeasonManager, SeasonPhase

        if SeasonManager().phase != SeasonPhase.OFFSEASON:
            return None
        from playbalance.season_context import SeasonContext

        current = SeasonContext.load().current
        value = int(current.get("league_year") or 0) if isinstance(current, dict) else 0
        return value if value > 0 else None
    except Exception:
        return None


def _require_draft_open_for(year: int) -> None:
    """Refuse to start or run the coming year's draft during the offseason.

    A preseason-draft league shows the coming class all offseason, and the
    draft itself opens when the preseason begins. Starting it early would put
    the first team on the clock (and let the clock run out) months before
    anyone expects to pick.
    """

    upcoming = _upcoming_preseason_draft_year()
    if upcoming and int(year) == int(upcoming):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"The {upcoming} draft opens when the preseason begins. "
                "Until then the draft class is here to scout."
            ),
        )


def _player_lookup() -> Dict[str, Any]:
    """Cache players.csv by id for the duration of one request so pick rows
    can carry player metadata without N+1 load_players calls."""

    try:
        players = load_players_from_csv("data/players.csv")
    except Exception:
        return {}
    return {getattr(p, "player_id", ""): p for p in players}


def _prospect_lookup(year: int) -> Dict[str, Dict[str, Any]]:
    """Cache the year's draft pool by player_id so we can hydrate live-
    draft picks before they've been written into ``players.csv`` by the
    post-draft commit step. Without this fallback, the "Recent Picks"
    panel shows raw prospect IDs (``D20260094``) for every pick made in
    the current session because ``_player_lookup`` only sees committed
    rosters.
    """

    try:
        from playbalance.draft_pool import load_draft_pool

        pool = load_draft_pool(year) or []
    except Exception:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for prospect in pool:
        pid = str(prospect.get("player_id", "")).strip()
        if pid:
            out[pid] = prospect
    return out


def _prospect_shown_overall(
    prospect: Dict[str, Any], is_pitcher: bool, scale: int
) -> Dict[str, Any]:
    """The overall a page shows for a draft pool entry: the shared overall
    every other page shows, on the page's scale, so a prospect's OVR does
    not change once he is drafted (backlog #52)."""

    return compute_overall(
        prospect.get,
        is_pitcher=is_pitcher,
        position=str(prospect.get("primary_position", "") or "") or None,
        scale=scale,
    )


def _hydrate_pick(
    row: Dict[str, Any],
    players: Dict[str, Any],
    prospects: Dict[str, Dict[str, Any]],
    league_scale: Any = None,
) -> None:
    """Fill ``first_name``/``last_name``/``primary_position`` + overall on
    a draft selection dict in place. Players.csv wins (post-commit data),
    then falls back to the draft pool (pre-commit), then leaves blanks.
    """

    pid = str(row.get("player_id") or "")
    player = players.get(pid) if pid else None
    if player is not None:
        is_pitcher = bool(getattr(player, "is_pitcher", False))
        position = getattr(player, "primary_position", None)
        overall = compute_overall(
            lambda k, p=player: getattr(p, k, None),
            is_pitcher=is_pitcher,
            position=position,
            scale=display_scale_for(player, league_scale),
        )
        row["first_name"] = getattr(player, "first_name", "") or ""
        row["last_name"] = getattr(player, "last_name", "") or ""
        row["primary_position"] = position or ""
        row["is_pitcher"] = is_pitcher
        row["overall_raw"] = overall["overall_raw"]
        row["overall_display"] = overall["overall_display"]
        row["overall_stars_text"] = overall["overall_stars_text"]
        return

    prospect = prospects.get(pid) if pid else None
    if prospect is not None:
        is_pitcher_raw = prospect.get("is_pitcher")
        is_pitcher = (
            bool(is_pitcher_raw)
            if isinstance(is_pitcher_raw, bool)
            else str(is_pitcher_raw or "").strip().lower() in {"1", "true", "yes", "y"}
        )
        row["first_name"] = str(prospect.get("first_name", "") or "")
        row["last_name"] = str(prospect.get("last_name", "") or "")
        row["primary_position"] = str(prospect.get("primary_position", "") or "")
        row["is_pitcher"] = is_pitcher
        shown = _prospect_shown_overall(
            prospect, is_pitcher, display_scale_for(prospect, league_scale)
        )
        row["overall_raw"] = shown["overall_raw"]
        row["overall_display"] = shown["overall_display"]
        row["overall_stars_text"] = shown["overall_stars_text"]
        return

    row["first_name"] = ""
    row["last_name"] = ""
    row["primary_position"] = ""
    row["is_pitcher"] = False
    row["overall_raw"] = None
    row["overall_display"] = None
    row["overall_stars_text"] = None


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
    # PyQt draft_console presentation. Hydrate from players.csv first
    # (the post-commit source of truth); fall back to the draft pool
    # for picks made during the current session that haven't been
    # promoted into players.csv yet.
    players = _player_lookup()
    prospects = _prospect_lookup(year)
    league_scale = page_scale()
    for row in rows:
        _hydrate_pick(row, players, prospects, league_scale)
    return rows


@router.get("/state")
def draft_state_view(
    year: Optional[int] = Query(default=None, description="Defaults to current league year"),
) -> Dict[str, Any]:
    from services.draft_settings import load_draft_settings

    y = _resolve_year(year)
    state = draft_state.load_state(y) or {}
    order = list(state.get("order") or [])
    raw_selected = list(state.get("selected") or [])

    # Hydrate each pick with the player's name + position so the Recent
    # Picks panel can render "Smith, John (SS)" instead of the raw
    # prospect id ``D20260094``. State-on-disk only carries
    # ``{overall, round, team_id, player_id}``; the names live in the
    # draft pool (or players.csv once committed).
    players = _player_lookup() if raw_selected else {}
    prospects = _prospect_lookup(y) if raw_selected else {}
    league_scale = page_scale() if raw_selected else None
    selected: List[Dict[str, Any]] = []
    for entry in raw_selected:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        _hydrate_pick(row, players, prospects, league_scale)
        selected.append(row)

    settings = load_draft_settings()
    from services.team_ownership import human_owned_team_ids

    human_ids = human_owned_team_ids()
    on_clock = _team_on_clock(state) if state else None
    complete = _draft_complete(state, settings.rounds) if state else False

    # Start the clock lazily as well as on each pick, so a draft that was
    # already mid-pick when the clock shipped gets one rather than waiting
    # forever. Only persist when this actually starts it.
    due = None
    remaining = None
    if state and on_clock and not complete:
        if draft_clock.started_at(state, on_clock) is None:
            draft_clock.ensure_started(state, on_clock)
            draft_state.save_state(y, state)
        due = draft_clock.deadline(state, on_clock, settings.pick_clock_hours)
        remaining = draft_clock.seconds_remaining(
            state, on_clock, settings.pick_clock_hours
        )

    seq = state.get("pick_sequence")
    total_picks = (
        len(seq)
        if isinstance(seq, list) and seq
        else (len(order) * max(1, int(settings.rounds)) if order else 0)
    )
    if state.get("completed") is True:
        # A finished draft is as long as it was, whatever the round count
        # has been changed to since.
        total_picks = len(raw_selected)
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
        # Backend is authoritative for these (compensation picks make a flat
        # modulo over ``order`` wrong). The UI should prefer them.
        "team_on_clock": on_clock,
        "draft_complete": complete,
        "total_picks": total_picks,
        "has_compensation": bool(isinstance(seq, list) and seq),
        # Who is a real person, so the UI can mark owner picks and show a
        # countdown only where one applies.
        "human_teams": sorted(human_ids),
        "on_clock_is_human": bool(on_clock and on_clock.strip().upper() in human_ids),
        "pick_clock_hours": settings.pick_clock_hours,
        "pick_deadline": due.isoformat() if due is not None else None,
        "seconds_remaining": remaining,
    }


def _prospect_row(
    prospect: Dict[str, Any], league_scale: Any, *, available: bool
) -> Dict[str, Any]:
    """One draft-pool prospect as the pages show him."""

    pid = str(prospect.get("player_id", "")).strip()
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
    scale = display_scale_for(prospect, league_scale)
    shown_overall = _prospect_shown_overall(
        prospect, is_pitcher, scale
    )["overall_display"]
    # rating-scale: display payload; shows the ratings as stored on the
    # page's scale (display_rating)
    return {
        "player_id": pid,
        "first_name": prospect.get("first_name", ""),
        "last_name": prospect.get("last_name", ""),
        "primary_position": prospect.get("primary_position", ""),
        "is_pitcher": is_pitcher,
        "bats": prospect.get("bats", ""),
        "throws": prospect.get("throws", ""),
        "birthdate": birthdate,
        "age": age,
        "overall": shown_overall,
        "available": available,
        "ratings": {
            k: display_rating(prospect, k, scale)
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

    league_scale = page_scale()
    rows: List[Dict[str, Any]] = []
    for prospect in pool:
        pid = str(prospect.get("player_id", "")).strip()
        if not pid:
            continue
        is_taken = pid in taken
        if available_only and is_taken:
            continue
        rows.append(_prospect_row(prospect, league_scale, available=not is_taken))

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

from ..security import require_bearer, require_team_owner


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
        DEFAULT_PICK_CLOCK_HOURS,
        DEFAULT_POOL_SIZE,
        DEFAULT_ROUNDS,
        DEFAULT_POST_DRAFT_WAIT_HOURS,
        MAX_PICK_CLOCK_HOURS,
        MAX_POOL_SIZE,
        MAX_POST_DRAFT_WAIT_HOURS,
        MAX_ROUNDS,
        MIN_PICK_CLOCK_HOURS,
        MIN_POOL_SIZE,
        MIN_POST_DRAFT_WAIT_HOURS,
        MIN_ROUNDS,
        load_draft_settings,
    )

    settings = load_draft_settings()
    return {
        "rounds": settings.rounds,
        "pool_size": settings.pool_size,
        "pick_clock_hours": settings.pick_clock_hours,
        "post_draft_wait_hours": settings.post_draft_wait_hours,
        "timing": settings.timing,
        "timing_options": _timing_options(),
        "limits": {
            "rounds": {"min": MIN_ROUNDS, "max": MAX_ROUNDS, "default": DEFAULT_ROUNDS},
            "pool_size": {
                "min": MIN_POOL_SIZE,
                "max": MAX_POOL_SIZE,
                "default": DEFAULT_POOL_SIZE,
            },
            "pick_clock_hours": {
                "min": MIN_PICK_CLOCK_HOURS,
                "max": MAX_PICK_CLOCK_HOURS,
                "default": DEFAULT_PICK_CLOCK_HOURS,
            },
            "post_draft_wait_hours": {
                "min": MIN_POST_DRAFT_WAIT_HOURS,
                "max": MAX_POST_DRAFT_WAIT_HOURS,
                "default": DEFAULT_POST_DRAFT_WAIT_HOURS,
            },
        },
    }


@router.put("/settings")
def draft_settings_save(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminDep,
) -> Dict[str, Any]:
    """Admin save of draft config."""

    from services.draft_settings import (
        DRAFT_TIMINGS,
        DraftSettings,
        load_draft_settings,
        normalize_timing,
        save_draft_settings,
    )

    current = load_draft_settings()
    # Absent means "leave it alone", so an older client that does not know
    # about the pick clock (or the draft timing, or the wait after the
    # draft) cannot silently reset it on save. Rounds and pool size follow
    # the same rule so a caller can change the timing alone.
    clock = payload.get("pick_clock_hours", None)
    wait = payload.get("post_draft_wait_hours", None)
    timing = payload.get("timing", None)
    if timing is not None:
        # normalize_timing falls back to the default on junk, which is right
        # for a stored file but would turn a typo into a silent change here.
        text = str(timing).strip().lower().replace("-", "").replace("_", "")
        if text not in DRAFT_TIMINGS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"timing must be one of {list(DRAFT_TIMINGS)}.",
            )
        timing = normalize_timing(text)
    rounds = payload.get("rounds", None)
    pool_size = payload.get("pool_size", None)
    try:
        incoming = DraftSettings(
            rounds=current.rounds if rounds is None else int(rounds or 0),
            pool_size=(
                current.pool_size if pool_size is None else int(pool_size or 0)
            ),
            pick_clock_hours=(
                current.pick_clock_hours if clock is None else int(clock or 0)
            ),
            timing=current.timing if timing is None else timing,
            post_draft_wait_hours=(
                current.post_draft_wait_hours if wait is None else int(wait or 0)
            ),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "rounds, pool_size, pick_clock_hours and post_draft_wait_hours "
                "must be whole numbers."
            ),
        ) from exc
    saved = save_draft_settings(incoming)
    out: Dict[str, Any] = {
        "rounds": saved.rounds,
        "pool_size": saved.pool_size,
        "pick_clock_hours": saved.pick_clock_hours,
        "post_draft_wait_hours": saved.post_draft_wait_hours,
        "timing": saved.timing,
        "timing_options": _timing_options(),
    }
    if saved.timing != current.timing:
        out["timing_change"] = _apply_timing_change()
    return out


def _timing_options() -> List[Dict[str, str]]:
    from services.draft_settings import (
        DRAFT_TIMING_MIDSEASON,
        DRAFT_TIMING_PRESEASON,
    )

    return [
        {
            "id": DRAFT_TIMING_MIDSEASON,
            "label": "Mid-season (July)",
            "description": (
                "The draft is held on the third Tuesday in July. The regular "
                "season pauses until the last pick is made."
            ),
        },
        {
            "id": DRAFT_TIMING_PRESEASON,
            "label": "Preseason (before spring training)",
            "description": (
                "The draft is held when the new season begins, before spring "
                "training, so the draft class gets a training camp and no "
                "regular-season sim waits on the draft."
            ),
        },
    ]


def _apply_timing_change() -> Dict[str, Any]:
    """What a change of draft timing does right now, and what it will do.

    A change applies to the next draft that has not been held. Switching to
    a preseason draft while the league is in the preseason, before spring
    training, opens this year's draft at once; in the offseason it makes the
    coming draft class available to scout. Anywhere else nothing changes
    until the next preseason (the regular season in progress keeps its July
    draft).
    """
    out: Dict[str, Any] = {"applies": "next_draft"}
    try:
        from api.routers import season as season_router
        from playbalance.season_manager import SeasonManager, SeasonPhase

        manager = SeasonManager()
        opened = season_router._maybe_open_preseason_draft(manager)
        out["preseason_draft"] = opened
        if opened.get("opened"):
            out["applies"] = "now"
        elif manager.phase == SeasonPhase.OFFSEASON:
            seeded = season_router._seed_next_draft_pool_if_preseason()
            if seeded:
                out["draft_pool"] = seeded
        out["phase"] = manager.phase.value
    except Exception as exc:  # pragma: no cover - defensive
        out["error"] = str(exc)
    return out


@router.post("/admin/initialize")
def admin_initialize(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminDep,
) -> Dict[str, Any]:
    """Seed a brand-new draft state for the given year."""

    year = int(payload.get("year") or _resolve_year(None))
    _require_draft_open_for(year)
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
    # Reflect any qualifying-offer draft compensation from the prior offseason
    # as real supplemental picks (comp teams gain an end-of-round-1 pick; teams
    # that signed a QO'd FA forfeit their round-2 pick).
    supplemental: List[str] = []
    forfeited: List[str] = []
    try:
        from services.qualifying_offers import compensation_for_draft

        comp = compensation_for_draft(year)
        supplemental = list(comp.get("comp_teams", []))
        forfeited = list(comp.get("forfeit_teams", []))
    except Exception:
        supplemental, forfeited = [], []
    state = draft_state.initialize_state(
        year,
        order=order,
        seed=seed_int,
        total_rounds=_load_settings_rounds(),
        supplemental=supplemental,
        forfeited=forfeited,
    )
    return {
        "year": year,
        "order": state.get("order"),
        "seed": state.get("seed"),
        "compensation_picks": len(supplemental),
        "forfeited_picks": len(forfeited),
    }


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
    overall = int(state.get("overall_pick", 1) or 1)
    seq = state.get("pick_sequence")
    if isinstance(seq, list) and seq:
        idx = overall - 1
        if 0 <= idx < len(seq) and isinstance(seq[idx], dict):
            return str(seq[idx].get("team_id") or "").strip() or None
        return None
    order: List[str] = list(state.get("order") or [])
    if not order:
        return None
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
    return draft_state.state_is_complete(state, total_rounds)


def _load_settings_rounds() -> int:
    try:
        from services.draft_settings import load_draft_settings

        return int(load_draft_settings().rounds)
    except Exception:
        return 10


def _prospect_overall(prospect: Dict[str, Any]) -> int:
    """Best-available score (the auto-pick): the shared overall
    (``utils.player_overall``, backlog #52), on the engine scale so it does
    not move with the pool's rating scale. It used to be a flat mean that
    counted a pitcher's arm and endurance and left out eye."""

    try:
        score = player_overall_score(prospect)
    except Exception:
        return 0
    return int(round(score)) if score is not None else 0


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


def _announce_picks(year: int, picks: List[Dict[str, Any]], *, draft_complete: bool) -> None:
    """Post ``picks`` (``_do_pick`` results) to the league's draft channel on
    Discord (8.6.6). Best-effort: the picks are already made and saved."""

    if not picks:
        return
    try:
        from services import discord_notify
        from services.draft_announcement import build_pick_messages
        from utils import path_utils

        if not discord_notify.is_configured(discord_notify.DRAFT):
            return
        prospects = _prospect_lookup(year)
        rows = []
        for pick in picks:
            prospect = prospects.get(str(pick.get("player_id") or ""), {})
            name = f"{prospect.get('first_name', '')} {prospect.get('last_name', '')}".strip()
            rows.append(
                {
                    "round": pick.get("round"),
                    "overall": pick.get("overall"),
                    "team_id": pick.get("team_id"),
                    "player_id": pick.get("player_id"),
                    "name": name or pick.get("player_id"),
                    "position": prospect.get("primary_position") or "",
                    "source": pick.get("source") or "",
                }
            )
        league = path_utils.get_request_league() or path_utils.get_active_league_id() or ""
        for text in build_pick_messages(
            league_id=league, year=year, picks=rows, draft_complete=draft_complete
        ):
            discord_notify.post(text, channel=discord_notify.DRAFT)
    except Exception:  # pragma: no cover - a post must never break a pick
        pass


def _do_pick(
    year: int,
    state: Dict[str, Any],
    *,
    player_id: str,
    season_date: Optional[str] = None,
    announce: bool = True,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a pick + commit it to the team's roster. Mutates ``state``.

    ``announce`` posts the pick to the draft channel; a caller making a run
    of picks passes False and announces them together. ``source`` marks a
    pick made for an owner (8.7.0): ``"board"`` from his draft board,
    ``"clock"`` best available when his clock ran out without one."""

    order: List[str] = list(state.get("order") or [])
    seq = state.get("pick_sequence")
    overall = int(state.get("overall_pick", 1) or 1)
    if isinstance(seq, list) and seq:
        if not (0 <= overall - 1 < len(seq)) or not isinstance(seq[overall - 1], dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Draft is already complete.",
            )
        team_id = str(seq[overall - 1].get("team_id") or "").strip()
        rnd = int(seq[overall - 1].get("round", 1) or 1)
    else:
        if not order:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Draft order is empty.",
            )
        rnd = int(state.get("round", 1) or 1)
        team_id = order[(overall - 1) % len(order)]

    selected = list(state.get("selected") or [])
    pick_entry = {"overall": overall, "round": rnd, "team_id": team_id, "player_id": player_id}
    if source:
        pick_entry["source"] = source
    selected.append(pick_entry)
    state["selected"] = selected
    state["overall_pick"] = overall + 1
    if isinstance(seq, list) and seq:
        nxt = seq[overall] if overall < len(seq) else None
        state["round"] = int(nxt.get("round", rnd)) if isinstance(nxt, dict) else rnd
    elif order and (overall % len(order)) == 0:
        state["round"] = rnd + 1
    # Whoever is up next goes on the clock as of now. Reset here rather than
    # only on read, so the deadline an owner is shown starts when the previous
    # pick was actually made.
    draft_clock.start(state, _team_on_clock(state))
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

    # When the final pick lands, the amateur draft is over — resume the
    # regular season so the calendar can advance again. The draft is a
    # mid-July interruption, not the end of the year; leaving the phase at
    # AMATEUR_DRAFT is what dead-locked the sim buttons (they're gated to
    # REGULAR_SEASON) and pushed "Advance Phase" straight to the playoffs.
    try:
        if _draft_complete(state, _load_settings_rounds()):
            # Stamp it finished, so a later change to the round count (made
            # for next year's draft) cannot reopen this one.
            # ``completed_at`` starts the wait before an automatic scheduled
            # run may touch owner rosters (services.draft_settings).
            if state.get("completed") is not True:
                from datetime import datetime, timezone

                state["completed"] = True
                state["completed_at"] = datetime.now(timezone.utc).isoformat()
                draft_state.save_state(year, state)
            _resume_regular_season_after_draft()
            # Give the freshly-drafted players avatars in the SAME consistent AI
            # style as the rest of the league (runs in the background so it never
            # blocks the draft). Scoped to JUST the drafted players so a fresh
            # league doesn't accidentally AI-generate the entire roster.
            _generate_draft_avatars_async(_selected_ids(state))
    except Exception:  # pragma: no cover - defensive
        pass

    result = {
        "year": year,
        "round": rnd,
        "overall": overall,
        "team_id": team_id,
        "player_id": player_id,
        "commit": commit_summary,
        "draft_complete": _draft_complete(state, _load_settings_rounds()),
    }
    if source:
        result["source"] = source
    if announce:
        _announce_picks(year, [result], draft_complete=result["draft_complete"])
    return result


def _resume_regular_season_after_draft() -> None:
    """Leave AMATEUR_DRAFT once the draft finishes.

    The season goes back to whichever phase the draft interrupted: the
    regular season for the mid-season draft, the preseason (spring training
    is next) for a draft held before the season.
    """
    try:
        from playbalance.season_manager import SeasonManager

        SeasonManager().resume_after_draft()
    except Exception:  # pragma: no cover - defensive
        pass


def _generate_draft_avatars_async(player_ids: set[str]) -> None:
    """Background AI-avatar fill for the freshly-drafted players.

    Mirrors the export/sim background jobs: the worker rebinds the request league
    (ContextVars don't cross threads), generates avatars ONLY for ``player_ids``
    (the draftees) via the AI engine, then pushes the working copy so the new
    PNGs persist. Fire and forget — the draft response returns immediately."""
    import threading

    from utils import path_utils

    if not player_ids:
        return
    league = path_utils.get_active_league_id()

    def _run() -> None:
        token = path_utils.set_request_league(league) if league else None
        try:
            from utils.avatar_generator import generate_player_avatars

            generate_player_avatars(
                engine="ai",
                initial_creation=False,
                only_player_ids=set(player_ids),
            )
            try:
                from api import working_copy

                if working_copy.is_enabled():
                    working_copy.push_changes()
            except Exception:
                logging.getLogger("nexgen.draft").exception(
                    "draft-avatar working-copy push failed"
                )
        except Exception:
            logging.getLogger("nexgen.draft").exception(
                "draft avatar generation failed"
            )
        finally:
            if token is not None:
                path_utils.reset_request_league(token)

    from api import working_copy

    threading.Thread(
        target=working_copy.as_background_writer("draft-avatars", _run),
        name="draft-avatars",
        daemon=True,
    ).start()


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
    team_on_clock = _ensure_pick_authorized(identity, state)

    # A club with a draft board gets its board's pick (8.7.0), whoever asked.
    if draft_board.has_board(year, team_on_clock):
        mine = str(identity.get("t") or "").strip().upper() == team_on_clock.strip().upper()
        result = _pick_for_owner(
            year, state, team_on_clock, why="owner" if mine else "commissioner"
        )
        if result is not None:
            return result
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
    - ``"next_human"` — stop as soon as ANY human-owned team is on the clock
    - ``"end_of_round"`` — stop when the active round changes
    - ``"end_of_draft"`` — pick to the end of the draft

    In every mode the loop also stops when a human-owned team reaches the
    clock, so a commissioner advancing the draft cannot spend an owner's pick
    for him. That is what ``next_human`` asks for directly, and what the other
    modes previously got wrong: with seven owners drafting 11th through 20th,
    "advance to the end of the round" used to draft for all of them. Pass
    ``include_human_teams: true`` to override it and pick for everyone — the
    way to force a draft to completion when owners have gone quiet.

    Admins running ``"my_pick"`` may pass ``team_id`` to specify which
    team's turn to wait for; otherwise we use the caller's identity team.
    Hard cap of 2,000 picks per call so a misconfigured order can't spin.
    """

    year = int(payload.get("year") or _resolve_year(None))
    stop_mode = str(payload.get("stop", "my_pick")).strip().lower() or "my_pick"
    include_humans = bool(payload.get("include_human_teams", False))
    if include_humans and str(identity.get("r", "")).lower() != "admin":
        # Picking for every team on the board, owners included, is the
        # commissioner's call alone. Without this any signed-in owner could
        # have the CPU spend every other owner's picks.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the commissioner can auto-pick for owner-controlled teams.",
        )
    if stop_mode not in {"my_pick", "next_human", "end_of_round", "end_of_draft"}:
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

    # An empty draft order makes `_team_on_clock` return None, so the loop
    # below would break immediately and return 0 picks with no explanation —
    # the caller can't tell "malformed draft" from "nothing to do" and the UI
    # spins waiting for a pick that never comes. Fail loudly instead.
    if not list(state.get("order") or []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Draft order is empty — seed the draft order (Admin → "
                "initialize draft) before auto-advancing."
            ),
        )

    rounds_total = _load_settings_rounds()
    role = str(identity.get("r", "")).lower()
    from services.team_ownership import human_owned_team_ids_strict

    owner_ids = human_owned_team_ids_strict()
    human_ids = set() if include_humans else owner_ids
    # Picking for everyone: an owner's pick still comes from his board.
    owner_ids = set(owner_ids or ())
    if human_ids is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Team ownership couldn't be read, so the CPU won't pick for "
                "anyone right now. Try again in a moment."
            ),
        )

    target_team: Optional[str] = None
    if stop_mode == "my_pick":
        target_team = (
            str(payload.get("team_id", "")).strip()
            or str(identity.get("t", "")).strip()
            or None
        )
        # Require a concrete team for ANY caller (including admins/commissioners
        # browsing a team). Without it the stop condition below can never match,
        # so the loop would silently run the entire draft to completion — the
        # exact bug where "auto-draft until my pick" drafted everyone.
        if not target_team:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Auto-advance to 'my pick' needs a team to stop at — pass "
                    "team_id (no team is associated with this user)."
                ),
            )

    starting_round = int(state.get("round", 1) or 1)

    picks_made: List[Dict[str, Any]] = []
    cap = 2000
    # Why the loop stopped, so the caller never sees an unexplained 0-pick run.
    stopped_reason = "reached_cap"
    while len(picks_made) < cap:
        if _draft_complete(state, rounds_total):
            stopped_reason = "draft_complete"
            break
        on_clock = _team_on_clock(state)
        if on_clock is None:
            stopped_reason = "no_team_on_clock"
            break
        # Stop conditions checked BEFORE picking so we don't pick for the
        # owner's team (they should choose).
        if stop_mode == "my_pick" and target_team and on_clock == target_team:
            stopped_reason = "reached_target"
            break
        new_round = (
            stop_mode == "end_of_round" and int(state.get("round", 1) or 1) != starting_round
        )
        if str(on_clock).strip().upper() in human_ids:
            # A real person is on the clock. Their pick is theirs to make,
            # unless they told their draft board to make it the moment
            # they are up (8.7.0).
            if new_round or not _autodraft_ready(year, state, on_clock):
                stopped_reason = "human_on_clock"
                break
            try:
                result = _pick_for_owner(
                    year, state, on_clock, why="autodraft", announce=False
                )
            except HTTPException:
                stopped_reason = "pick_failed"
                break
            if result is None:
                stopped_reason = "pool_exhausted"
                break
            picks_made.append(result)
            continue
        if new_round:
            stopped_reason = "end_of_round"
            break

        if str(on_clock).strip().upper() in owner_ids:
            # The commissioner is finishing the draft for everyone.
            try:
                result = _pick_for_owner(
                    year, state, on_clock, why="commissioner", announce=False
                )
            except HTTPException:
                stopped_reason = "pick_failed"
                break
            if result is None:
                stopped_reason = "pool_exhausted"
                break
            picks_made.append(result)
            continue

        best = _best_available(year, state)
        if not best:
            stopped_reason = "pool_exhausted"
            break
        try:
            result = _do_pick(
                year, state, player_id=str(best.get("player_id", "")), announce=False
            )
        except HTTPException:
            stopped_reason = "pick_failed"
            break
        picks_made.append(result)

    # One post for the whole run (Discord rate-limits a webhook).
    _announce_picks(
        year, picks_made, draft_complete=_draft_complete(state, rounds_total)
    )

    return {
        "year": year,
        "stop": stop_mode,
        "target_team": target_team,
        "include_human_teams": include_humans,
        "picks": picks_made,
        "picks_made": len(picks_made),
        "stopped_reason": stopped_reason,
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
    result = {
        "year": year,
        "round": rnd,
        "overall": overall,
        "team_id": team_id,
        "player_id": player_id,
    }
    _announce_picks(year, [result], draft_complete=_draft_complete(state, _load_settings_rounds()))
    return result


# ---------------------------------------------------------------------------
# Draft boards (8.7.0): an owner's instructions for a pick made for him
# (services.draft_board). Private to the club's owner, the commissioner
# included.

DRAFT_PICK_RULE_ID = "draft_pick_made"


def _current_round(state: Dict[str, Any]) -> int:
    overall = int(state.get("overall_pick", 1) or 1)
    seq = state.get("pick_sequence")
    if isinstance(seq, list) and seq and 0 <= overall - 1 < len(seq):
        entry = seq[overall - 1]
        if isinstance(entry, dict):
            return int(entry.get("round", 1) or 1)
    return int(state.get("round", 1) or 1)


def _next_pick_of(
    state: Dict[str, Any], team_id: str, rounds_total: int
) -> Optional[Tuple[int, int]]:
    """``(overall, round)`` of the club's next pick, or ``None``."""

    team = str(team_id or "").strip().upper()
    overall = int(state.get("overall_pick", 1) or 1)
    seq = state.get("pick_sequence")
    if isinstance(seq, list) and seq:
        for idx in range(max(0, overall - 1), len(seq)):
            entry = seq[idx]
            if isinstance(entry, dict) and str(entry.get("team_id") or "").strip().upper() == team:
                return idx + 1, int(entry.get("round", 1) or 1)
        return None
    order = [str(t).strip().upper() for t in state.get("order") or []]
    if not order:
        return None
    total = len(order) * max(1, int(rounds_total or 1))
    for pick in range(overall, total + 1):
        if order[(pick - 1) % len(order)] == team:
            return pick, (pick - 1) // len(order) + 1
    return None


def _drafted_by(
    state: Dict[str, Any], team_id: str, by_id: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """The prospects the club has drafted so far, whoever made the pick."""

    team = str(team_id or "").strip().upper()
    out = []
    for entry in state.get("selected") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("team_id") or "").strip().upper() != team:
            continue
        prospect = by_id.get(str(entry.get("player_id") or ""))
        if prospect is not None:
            out.append(prospect)
    return out


def _board_choice(
    year: int, state: Dict[str, Any], team_id: str
) -> Optional[draft_board.BoardChoice]:
    """The pick the club's board makes right now (``None`` without a board)."""

    if not draft_board.has_board(year, team_id):
        return None
    by_id = _prospect_lookup(year)
    return draft_board.choose(
        draft_board.load_board(year, team_id),
        pool=list(by_id.values()),
        taken=_selected_ids(state),
        drafted=_drafted_by(state, team_id, by_id),
        round_no=_current_round(state),
    )


def _autodraft_ready(year: int, state: Dict[str, Any], team_id: str) -> bool:
    """True when the club's board says to pick the moment it is up."""

    if not draft_board.has_board(year, team_id):
        return False
    mode = draft_board.load_board(year, team_id).get("autodraft")
    if mode not in ("board", "all"):
        return False
    choice = _board_choice(year, state, team_id)
    return choice is not None and (mode == "all" or choice.source == "board")


_WHY_TEXT = {
    "clock": "Your pick clock ran out",
    "autodraft": "Auto-draft is on",
    "commissioner": "The commissioner had the CPU make your pick",
    "owner": "You asked for an auto-pick",
}


def _pick_for_owner(
    year: int,
    state: Dict[str, Any],
    team_id: str,
    *,
    why: str,
    announce: bool = True,
) -> Optional[Dict[str, Any]]:
    """Make the pick for a club whose owner is not making it: from its draft
    board when it has one, otherwise the best player available. The owner
    is told which player, and why. ``None`` when nobody is left.

    ``why`` is ``"clock"`` (his clock ran out), ``"autodraft"`` (his board
    picks as soon as he is up), ``"commissioner"`` or ``"owner"`` (the
    Auto-pick button)."""

    choice = _board_choice(year, state, team_id)
    if choice is not None:
        player_id, source, reason = choice.player_id, "board", choice.reason
    else:
        best = _best_available(year, state)
        if not best:
            return None
        player_id = str(best.get("player_id", ""))
        source = "clock" if why == "clock" else None
        reason = "You have no draft board, so the CPU took the best player available."
    result = _do_pick(year, state, player_id=player_id, announce=announce, source=source)
    _tell_owner_of_pick(year, team_id, result, reason=reason, why=why, board=choice is not None)
    return result


def _tell_owner_of_pick(
    year: int,
    team_id: str,
    result: Dict[str, Any],
    *,
    reason: str,
    why: str,
    board: bool,
) -> None:
    """Keep the pick on the club's board and tell its owner. Never raises."""

    log = logging.getLogger("nexgen.draft")
    pid = str(result.get("player_id") or "")
    who = draft_board.describe_pick(_prospect_lookup(year).get(pid), pid)
    if board:
        try:
            draft_board.record_pick(
                year,
                team_id,
                {
                    "overall": result.get("overall"),
                    "round": result.get("round"),
                    "player_id": pid,
                    "name": who,
                    "why": why,
                    "reason": reason,
                },
            )
        except Exception:
            log.exception("draft board: could not record the pick for %s", team_id)
    if why == "owner":
        return  # he pressed the button himself
    try:
        from services.notification_engine import NotificationEvent, append_history
        from services.notification_settings import load_notification_settings
        from services.team_ownership import human_owned_team_ids_strict

        owners = human_owned_team_ids_strict() or set()
        if str(team_id).strip().upper() not in owners:
            return
        rule = load_notification_settings(team_id).rule(DRAFT_PICK_RULE_ID)
        if not rule.enabled:
            return
        picker = "your draft board" if board else "the CPU"
        message = (
            f"Round {result.get('round')}, pick {result.get('overall')}: "
            f"{_WHY_TEXT.get(why, 'A pick was made for you')}, so {picker} took {who}. "
            f"{reason}"
        )
        append_history(team_id, [NotificationEvent(
            rule_id=DRAFT_PICK_RULE_ID,
            severity="info",
            title="Draft pick made for you",
            message=message,
            payload={"team_id": team_id, "player_id": pid},
            notify=bool(rule.notify),
        )])
    except Exception:
        log.exception("draft board: could not notify %s", team_id)


def _require_own_board(identity: Dict[str, Any], team_id: str) -> str:
    """A board is its club's owner's alone: the commissioner may act for any
    club, but may not read another club's draft plans."""

    team = str(team_id or "").strip().upper()
    if not team or str(identity.get("t") or "").strip().upper() != team:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Draft boards are private: only the club's owner can open its board.",
        )
    return team


def _board_payload(year: int, team_id: str) -> Dict[str, Any]:
    """The board as the page shows it: each player with his ratings and
    whether he is gone, what the board would take at the club's next pick,
    and the picks it has made."""

    from services.draft_settings import load_draft_settings

    board = draft_board.load_board(year, team_id)
    by_id = _prospect_lookup(year)
    state = draft_state.load_state(year) or {}
    rounds = int(load_draft_settings().rounds)
    taken: Dict[str, Dict[str, Any]] = {}
    for entry in state.get("selected") or []:
        if isinstance(entry, dict) and entry.get("player_id"):
            taken[str(entry["player_id"])] = {
                "team_id": entry.get("team_id"),
                "overall": entry.get("overall"),
                "round": entry.get("round"),
            }
    league_scale = page_scale()
    entries = []
    for entry in board["entries"]:
        prospect = by_id.get(entry["player_id"])
        row = dict(entry)
        row["prospect"] = (
            _prospect_row(prospect, league_scale, available=entry["player_id"] not in taken)
            if prospect is not None
            else None
        )
        row["taken"] = taken.get(entry["player_id"])
        entries.append(row)

    complete = bool(state) and _draft_complete(state, rounds)
    drafted = _drafted_by(state, team_id, by_id)
    next_pick = None
    preview = None
    if not complete and by_id:
        found = _next_pick_of(state, team_id, rounds) if state else None
        if found is not None:
            next_pick = {"overall": found[0], "round": found[1]}
        # Before the draft opens the preview is for the club's first pick.
        if found is not None or not state:
            round_no = found[1] if found else 1
            choice = draft_board.choose(
                board,
                pool=list(by_id.values()),
                taken=set(taken),
                drafted=drafted,
                round_no=round_no,
            )
            if choice is not None:
                preview = {
                    "player_id": choice.player_id,
                    "name": draft_board.describe_pick(by_id.get(choice.player_id), choice.player_id),
                    "source": choice.source,
                    "reason": choice.reason,
                    "round": round_no,
                }
    counts: Dict[str, int] = {}
    for prospect in drafted:
        for key in draft_board.position_groups_of(prospect):
            counts[key] = counts.get(key, 0) + 1
    on_clock = _team_on_clock(state) if state and not complete else None
    return {
        "year": year,
        "team_id": team_id,
        "board": {k: v for k, v in board.items() if k not in ("made", "entries")},
        "entries": entries,
        "made": board.get("made") or [],
        "preview": preview,
        "next_pick": next_pick,
        "drafted_counts": counts,
        "draft": {
            "exists": bool(state),
            "complete": complete,
            "rounds": rounds,
            "on_clock": bool(on_clock) and str(on_clock).strip().upper() == team_id,
        },
        "options": {
            "positions": list(draft_board.POSITION_GROUPS),
            "groups": list(draft_board.GROUP_LABELS),
            "fallbacks": [
                {"id": key, "label": label} for key, label in draft_board.FALLBACKS.items()
            ],
            "autodraft": list(draft_board.AUTODRAFT_MODES),
        },
    }


@router.get("/board/{team_id}")
def draft_board_view(
    team_id: str,
    year: Optional[int] = Query(default=None),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """The club's draft board, with what it would pick right now."""

    require_team_owner(identity, team_id)
    team = _require_own_board(identity, team_id)
    return _board_payload(_resolve_year(year), team)


@router.put("/board/{team_id}")
def draft_board_save(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Save the club's draft board (the whole board, as the page holds it)."""

    require_team_owner(identity, team_id)
    team = _require_own_board(identity, team_id)
    year = int(payload.get("year") or _resolve_year(None))
    state = draft_state.load_state(year) or {}
    if state and _draft_complete(state, _load_settings_rounds()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The {year} draft is over.",
        )
    by_id = _prospect_lookup(year)
    if not by_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"There is no {year} draft class yet.",
        )
    raw = payload.get("board")
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="board is required.",
        )
    try:
        draft_board.save_board(year, team, raw, pool_ids=set(by_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _board_payload(year, team)
