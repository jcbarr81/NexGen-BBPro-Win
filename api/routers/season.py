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
) -> Dict[str, Any]:
    """Run up to *n* days and return the list of dates we actually played."""

    n = max(1, min(int(n), _MAX_DAYS_PER_CALL))
    played_dates: List[str] = []
    errors: List[str] = []
    for _ in range(n):
        if simulator._index >= len(simulator.dates):
            break
        target_date = simulator.dates[simulator._index]
        try:
            simulator.simulate_next_day()
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"{target_date}: {exc}")
            break
        played_dates.append(target_date)
    return {"played_dates": played_dates, "errors": errors}


# ---------------------------------------------------------------------------
# Endpoints


@router.get("/state")
def season_state() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    return _state_payload(manager, simulator, draft_date)


@router.post("/simulate/day")
def simulate_day() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(manager, simulator, 1)
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
    result = _simulate_n(manager, simulator, n)
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/week")
def simulate_week() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(manager, simulator, 7)
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/month")
def simulate_month() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(manager, simulator, 30)
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
    result = _simulate_n(manager, simulator, n_days)
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/to-playoffs")
def simulate_to_playoffs() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    n_days = max(0, len(simulator.dates) - simulator._index)
    result = _simulate_n(manager, simulator, n_days)
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/advance-phase")
def advance_phase() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    try:
        new_phase: SeasonPhase = manager.advance_phase()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to advance phase: {exc}",
        ) from exc
    return _state_payload(manager, simulator, draft_date, extra={"new_phase": new_phase.value})
