"""Season progression endpoints.

The real workflow is simulating whole days (or weeks / months / to a
milestone), not pitch-by-pitch live streams. This router mirrors the
core flow of ``ui/season_progress_window.py`` -- the PyQt window users
actually drive the season with.

Every request builds a fresh :class:`SeasonSimulator` on top of the
persisted ``season_state.json`` + ``schedule.csv`` so owner-side writes
(lineup edits, trades, etc.) feed into the next sim call.

No long-lived workers or WebSockets: sims are fast enough (~tens of
games per second with the physics engine) to run inline within a single
HTTP request for a day, a week, or a month. Longer jumps (to-draft,
to-playoffs) cap out at a reasonable day budget per call so the client
can poll to show progress.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, status

from playbalance.game_runner import simulate_game_scores
from playbalance.season_manager import SeasonManager, SeasonPhase
from playbalance.season_simulator import SeasonSimulator
from utils.path_utils import get_data_dir

from ..security import CurrentIdentity

router = APIRouter(prefix="/season", tags=["season"], dependencies=[CurrentIdentity])


# Safety cap so a runaway request can't spin forever. One full season is
# typically ~180 days so anything up to ~220 covers all reasonable jumps.
_MAX_DAYS_PER_CALL = 220


def _schedule_path() -> Path:
    return get_data_dir() / "schedule.csv"


def _load_schedule() -> List[Dict[str, str]]:
    path = _schedule_path()
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _compute_draft_date(first_game_date: Optional[str]) -> Optional[str]:
    """Third Tuesday in July (matches ui/season_progress_window._compute_draft_date)."""
    if not first_game_date:
        return None
    try:
        year = int(str(first_game_date).split("-")[0])
    except Exception:
        return None
    import calendar
    from datetime import date as _date

    july_cal = calendar.Calendar().itermonthdates(year, 7)
    tuesdays = [d for d in july_cal if d.month == 7 and d.weekday() == 1]
    if len(tuesdays) < 3:
        return None
    return tuesdays[2].isoformat()


def _build_manager_and_simulator() -> tuple[SeasonManager, SeasonSimulator, Optional[str]]:
    schedule = _load_schedule()
    first_date = schedule[0].get("date") if schedule else None
    draft_date = _compute_draft_date(first_date)

    manager = SeasonManager()
    simulator = SeasonSimulator(
        schedule,
        simulate_game_scores,
        draft_date=draft_date,
    )
    # Skip past any dates whose games are fully played so simulate_next_day
    # truly advances the sim instead of replaying finished dates.
    played: set[str] = set()
    for row in schedule:
        if str(row.get("played", "")).strip().lower() in {"1", "true", "yes"} or str(
            row.get("result", "")
        ).strip():
            played.add(str(row.get("date", "")).strip())
    while (
        simulator._index < len(simulator.dates)
        and simulator.dates[simulator._index] in played
    ):
        simulator._index += 1

    return manager, simulator, draft_date


def _state_payload(
    manager: SeasonManager,
    simulator: SeasonSimulator,
    draft_date: Optional[str],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    current_date = (
        simulator.dates[simulator._index]
        if simulator._index < len(simulator.dates)
        else None
    )
    payload: Dict[str, Any] = {
        "phase": manager.phase.value,
        "current_date": current_date,
        "draft_date": draft_date,
        "days_total": len(simulator.dates),
        "days_played": simulator._index,
        "days_remaining": max(0, len(simulator.dates) - simulator._index),
        "mid_remaining": simulator.remaining_days(),
        "all_star_played": simulator._all_star_played,
        "draft_triggered": simulator._draft_triggered,
    }
    if extra:
        payload.update(extra)
    return payload


def _simulate_n(
    manager: SeasonManager,
    simulator: SeasonSimulator,
    n: int,
    *,
    draft_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Run up to *n* days and return the list of dates we actually played.

    Mirrors the full post-day flow from PyQt's
    ``ui/season_progress_window._simulate_day`` — running games is only
    step 1. After each batch of sim days we also run finance cadence
    updates, CPU trade proposals, and DL/injury recovery, then log a
    recap. Without these post-day hooks the sim produces box scores but
    leaves the economic and roster-management side of the league frozen.

    If the simulator hits the configured ``draft_date`` we stop early
    and set ``draft_blocked=True`` so the UI can prompt the commissioner
    to run the draft before any more days tick over.
    """

    n = max(1, min(int(n), _MAX_DAYS_PER_CALL))
    played_dates: List[str] = []
    errors: List[str] = []
    draft_blocked = False
    # An empty schedule means ``simulator.dates`` is zero-length — without
    # this check the sim quietly "plays" 0 days, which looks to the user
    # like the button did nothing. Surface an explicit error so the UI
    # can show a banner pointing them at /admin-league to regenerate.
    if len(simulator.dates) == 0:
        errors.append(
            "No schedule loaded. Generate one from Admin → Regenerate schedule."
        )
    for _ in range(n):
        if simulator._index >= len(simulator.dates):
            break
        target_date = simulator.dates[simulator._index]
        # Draft-day intercept. PyQt's ``_on_draft_day`` pauses the sim
        # and opens the draft console; the React equivalent is to stop,
        # flip the phase, and hand off to /draft.
        if draft_date and target_date == draft_date:
            try:
                manager.phase = SeasonPhase.AMATEUR_DRAFT
                manager.save()
            except Exception:
                pass
            draft_blocked = True
            break
        try:
            simulator.simulate_next_day()
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"{target_date}: {exc}")
            break
        played_dates.append(target_date)

    # Post-day automations. Only run these if we actually played days —
    # a no-op sim (draft pause, empty schedule, etc.) shouldn't trigger
    # finance settlement or trade offers.
    automations: Dict[str, Any] = {}
    if played_dates:
        automations = _run_daily_automations(played_dates)

    result: Dict[str, Any] = {
        "played_dates": played_dates,
        "errors": errors,
        "draft_blocked": draft_blocked,
    }
    if automations:
        result["automations"] = automations
    return result


def _run_daily_automations(played_dates: List[str]) -> Dict[str, Any]:
    """Run the same post-day service cycle PyQt's season window runs:
    owner finance cadence, CPU trade proposal cycle, and DL/injury
    recovery. Each block is wrapped so a single misbehaving service
    can't block the others or roll back the game results we just
    persisted."""

    summary: Dict[str, Any] = {}

    try:
        from services.owner_finance_engine import (
            apply_owner_finance_cadence_for_dates,
        )

        summary["finance"] = apply_owner_finance_cadence_for_dates(played_dates)
    except Exception as exc:  # pragma: no cover - defensive
        summary["finance_error"] = str(exc)

    try:
        from services.cpu_trade_proposals import run_cpu_trade_proposal_cycle

        summary["cpu_trades"] = run_cpu_trade_proposal_cycle(
            simulated_dates=played_dates,
            data_dir=get_data_dir(),
        )
    except Exception as exc:  # pragma: no cover - defensive
        summary["cpu_trades_error"] = str(exc)

    try:
        from services.dl_automation import process_disabled_lists

        dl_summary = process_disabled_lists(
            today=None,  # defaults to current sim date
            days_elapsed=len(played_dates),
            auto_activate=True,
        )
        summary["dl_updates"] = {
            "activated": len(getattr(dl_summary, "activated", []) or []),
            "alerts": len(getattr(dl_summary, "alerts", []) or []),
            "blocked": len(getattr(dl_summary, "blocked", []) or []),
        }
    except Exception as exc:  # pragma: no cover - defensive
        summary["dl_updates_error"] = str(exc)

    return summary


# ---------------------------------------------------------------------------
# Endpoints


@router.get("/state")
def season_state() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    return _state_payload(manager, simulator, draft_date)


@router.post("/simulate/day")
def simulate_day() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(manager, simulator, 1, draft_date=draft_date)
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/days")
def simulate_days(
    payload: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    try:
        n = int(payload.get("n", 1))
    except (TypeError, ValueError):
        n = 1
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(manager, simulator, n, draft_date=draft_date)
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/week")
def simulate_week() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(manager, simulator, 7, draft_date=draft_date)
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/month")
def simulate_month() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(manager, simulator, 30, draft_date=draft_date)
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/to-draft")
def simulate_to_draft() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    if not draft_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft date is not available (empty schedule?).",
        )
    # Days until draft date, capped.
    try:
        idx = simulator.dates.index(draft_date)
    except ValueError:
        idx = len(simulator.dates)
    n_days = max(0, idx - simulator._index)
    result = _simulate_n(manager, simulator, n_days, draft_date=draft_date)
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/to-playoffs")
def simulate_to_playoffs() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    n_days = max(0, len(simulator.dates) - simulator._index)
    result = _simulate_n(manager, simulator, n_days, draft_date=draft_date)
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/advance-phase")
def advance_phase(
    payload: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()

    # Guard: if there's no schedule AND the caller didn't explicitly opt
    # in via ``force=true``, refuse to bump the phase. Without this, a
    # fresh league can race REGULAR_SEASON → DRAFT → PLAYOFFS without a
    # single game being simulated. The UI offers a clear "schedule
    # missing" banner before this point, so hitting the block here is
    # the safety net, not the primary messaging.
    force = bool(payload.get("force", False))
    if (
        manager.phase == SeasonPhase.REGULAR_SEASON
        and len(simulator.dates) == 0
        and not force
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No schedule loaded — generate one in Admin → Regenerate "
                "schedule before advancing past the regular season."
            ),
        )

    # Guard: require the amateur draft to be committed before leaving
    # AMATEUR_DRAFT phase. Ports PyQt's ``_draft_blocked`` gate so the
    # user can't skip the draft by double-clicking Advance Phase.
    if manager.phase == SeasonPhase.AMATEUR_DRAFT and not force:
        if not _draft_completed_for_current_year():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Amateur draft hasn't been committed yet. Run the "
                    "draft from /draft before advancing past this phase."
                ),
            )

    try:
        new_phase: SeasonPhase = manager.advance_phase()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to advance phase: {exc}",
        ) from exc

    extra: Dict[str, Any] = {"new_phase": new_phase.value}

    # Playoff bracket auto-generation — ports ``_ensure_playoff_bracket``
    # from PyQt's season window. Without this the phase flips to
    # PLAYOFFS but no bracket exists for the UI to render.
    if new_phase == SeasonPhase.PLAYOFFS:
        try:
            bracket_summary = _ensure_playoff_bracket()
            if bracket_summary:
                extra["playoffs"] = bracket_summary
        except Exception as exc:  # pragma: no cover - defensive
            extra["playoffs_error"] = str(exc)

    return _state_payload(manager, simulator, draft_date, extra=extra)


def _draft_completed_for_current_year() -> bool:
    """True when a draft results CSV exists for the current league year.

    Keeps the check simple and filesystem-based so it works whether the
    commit came from the live draft, a manual admin override, or an
    import — any of those leave the ``draft_results_<year>.csv`` behind.
    """

    try:
        from services.trade_settings import current_league_year

        year = int(current_league_year())
    except Exception:
        from datetime import date as _date

        year = _date.today().year
    results = get_data_dir() / f"draft_results_{year}.csv"
    if not results.exists():
        return False
    try:
        with results.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for _ in reader:
                return True
    except OSError:
        return False
    return False


def _ensure_playoff_bracket() -> Optional[Dict[str, Any]]:
    """Build + persist a playoff bracket from current standings + teams.

    Uses ``playbalance.playoffs.generate_bracket`` — same source PyQt
    eventually calls — and saves it so ``/playoffs`` can render
    immediately after the phase flip.
    """

    try:
        from playbalance import playoffs as _pf
    except Exception:
        return None

    # Skip if a bracket already exists for the current year.
    try:
        existing = _pf.load_bracket()
    except Exception:
        existing = None
    if existing is not None:
        return {"reused_existing": True}

    try:
        from utils.team_loader import load_teams
    except Exception:
        return None

    try:
        teams = load_teams()
    except Exception:
        teams = []
    if not teams:
        return None

    try:
        standings = _pf._load_standings_snapshot()
    except Exception:
        standings = {}
    if not standings:
        return None

    try:
        from playbalance import playbalance_config as _cfg
    except Exception:
        _cfg = None

    try:
        bracket = _pf.generate_bracket(standings, teams, _cfg)
    except Exception as exc:
        return {"error": str(exc)}
    try:
        path = _pf.save_bracket(bracket)
    except Exception as exc:
        return {"error": f"Bracket built but save failed: {exc}"}

    return {
        "saved": True,
        "path": str(path),
        "teams_seeded": sum(
            len(getattr(r, "matchups", []) or []) * 2
            for r in getattr(bracket, "rounds", []) or []
        ),
    }
