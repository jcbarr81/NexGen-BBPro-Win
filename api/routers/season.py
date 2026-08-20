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
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status

from playbalance.game_runner import simulate_game_scores
from playbalance.season_manager import SeasonManager, SeasonPhase
from playbalance.season_simulator import SeasonSimulator
from services.notification_engine import (
    NotificationEvent,
    append_history,
    capture_pre_state,
    detect_events,
)
from services.notification_settings import load_notification_settings
from utils.path_utils import get_data_dir

from ..security import CurrentIdentity, require_bearer

router = APIRouter(prefix="/season", tags=["season"], dependencies=[CurrentIdentity])


# Safety cap so a runaway request can't spin forever. One full season is
# typically ~180 days so anything up to ~220 covers all reasonable jumps.
_MAX_DAYS_PER_CALL = 220


# In-process progress tracker for live "X of Y days" updates while a
# multi-day sim runs. The HTTP request that drives the sim returns a
# single response when the whole batch finishes, so the overlay polls
# ``GET /season/sim-progress`` to show real-time advancement instead of
# a fake elapsed-time animation. Single-process desktop app: one global
# slot is enough; we don't need per-league/per-user buckets.
_SIM_PROGRESS_LOCK = threading.Lock()
_SIM_PROGRESS: Dict[str, Any] = {
    # Live counter (managed by _simulate_n via _begin/_bump/_end).
    "active": False,
    "target": 0,
    "played": 0,
    "started_at": 0.0,
    # Job lifecycle (managed by the background launcher). Multi-day sims now
    # run in a background thread and the client polls /season/sim-progress for
    # completion — a long sim must never be held open inside the HTTP request,
    # because Firebase Hosting caps proxied requests at ~60s and a week/month/
    # to-draft jump runs well past that, surfacing a false "Action failed" even
    # though the sim finished server-side.
    "status": "idle",  # "idle" | "running" | "done" | "error"
    "result": None,  # final state payload when status == "done"
    "error": None,  # message when status == "error"
    "run_id": 0,
    # Set by /season/sim-cancel; the day loop checks it and stops cleanly
    # (already-played days are persisted). Reset to False for each new job.
    "cancel_requested": False,
}


def _begin_sim_progress(target: int) -> None:
    with _SIM_PROGRESS_LOCK:
        _SIM_PROGRESS.update(
            {
                "active": True,
                "target": int(max(0, target)),
                "played": 0,
                "started_at": time.time(),
            }
        )


def _bump_sim_progress() -> None:
    with _SIM_PROGRESS_LOCK:
        if _SIM_PROGRESS.get("active"):
            _SIM_PROGRESS["played"] = int(_SIM_PROGRESS.get("played", 0)) + 1


def _end_sim_progress() -> None:
    with _SIM_PROGRESS_LOCK:
        _SIM_PROGRESS["active"] = False


# A run still flagged "running" after this long is treated as dead (e.g. the
# thread was lost to an instance restart mid-sim) so it can't wedge the slot
# and 409 every future sim. Set well above any realistic full-season jump.
_SIM_STALE_SECONDS = 60 * 60


def _sim_running() -> bool:
    with _SIM_PROGRESS_LOCK:
        if _SIM_PROGRESS.get("status") != "running":
            return False
        started = float(_SIM_PROGRESS.get("started_at") or 0.0)
        if started and (time.time() - started) > _SIM_STALE_SECONDS:
            return False
        return True


def _begin_sim_job() -> int:
    """Reset the slot for a new background run and return its run id."""
    with _SIM_PROGRESS_LOCK:
        _SIM_PROGRESS["run_id"] = int(_SIM_PROGRESS.get("run_id", 0)) + 1
        _SIM_PROGRESS.update(
            {
                "status": "running",
                "result": None,
                "error": None,
                "active": True,
                "target": 0,
                "played": 0,
                "cancel_requested": False,
                "started_at": time.time(),
            }
        )
        return int(_SIM_PROGRESS["run_id"])


def _finish_sim_job(
    *, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None
) -> None:
    with _SIM_PROGRESS_LOCK:
        _SIM_PROGRESS["active"] = False
        _SIM_PROGRESS["cancel_requested"] = False
        if error is not None:
            _SIM_PROGRESS["status"] = "error"
            _SIM_PROGRESS["error"] = str(error)
        else:
            _SIM_PROGRESS["status"] = "done"
            _SIM_PROGRESS["result"] = result


def _request_sim_cancel() -> bool:
    """Flag the in-flight sim to stop after its current day. Returns True when a
    running sim was actually flagged (False if nothing is running)."""
    with _SIM_PROGRESS_LOCK:
        if _SIM_PROGRESS.get("status") != "running" or not _SIM_PROGRESS.get(
            "active"
        ):
            return False
        _SIM_PROGRESS["cancel_requested"] = True
        return True


def _sim_cancel_requested() -> bool:
    with _SIM_PROGRESS_LOCK:
        return bool(_SIM_PROGRESS.get("cancel_requested"))


def _days_for_kind(
    kind: str,
    n_arg: int,
    simulator: SeasonSimulator,
    draft_date: Optional[str],
) -> int:
    """Translate a sim 'kind' into a concrete day count to run."""
    if kind == "day":
        return 1
    if kind == "days":
        return max(1, int(n_arg))
    if kind == "week":
        return 7
    if kind == "month":
        return 30
    if kind == "to-draft":
        if not draft_date:
            raise ValueError("Draft date is not available (empty schedule?).")
        try:
            idx = simulator.dates.index(draft_date)
        except ValueError:
            idx = len(simulator.dates)
        # +1 so the loop actually REACHES the draft-day iteration. The draft
        # fires via the draft-day intercept in `_simulate_n`, which triggers at
        # the TOP of the iteration whose ``target_date == draft_date``. Running
        # exactly ``idx - _index`` days leaves the cursor parked ON draft day
        # with the loop already exhausted — one iteration short of the intercept,
        # forcing the user to sim an extra day before the draft starts. The
        # intercept ``break``s before playing draft day as games, so the +1
        # can't overshoot into the regular season.
        return max(0, idx - simulator._index + 1)
    if kind == "to-playoffs":
        return max(0, len(simulator.dates) - simulator._index)
    return 1


def _maybe_enter_playoffs(
    manager: SeasonManager,
    simulator: SeasonSimulator,
    result: Dict[str, Any],
    *,
    can_progress: bool,
) -> None:
    """After a 'to-playoffs' run finishes the regular season, seed the playoff
    bracket and flip the league into the PLAYOFFS phase — the same transition
    ``POST /season/advance-phase`` performs.

    Without this the 'To Playoffs' button sims to the final regular-season day
    and stops at the doorstep, never actually starting the postseason. Mutates
    ``result`` in place so the polled sim payload reflects what happened.

    Only acts once the WHOLE schedule is played and the league is still in
    REGULAR_SEASON; a run stopped early (draft intercept, injury pause, cancel)
    is left untouched so the user just keeps simming.
    """

    if manager.phase != SeasonPhase.REGULAR_SEASON:
        return
    if len(simulator.dates) == 0 or simulator._index < len(simulator.dates):
        # Regular season not finished yet — nothing to hand off to the postseason.
        return
    # The regular season is complete. Entering the playoffs is a season-
    # progression action, which in owner leagues belongs to the commissioner —
    # mirror the /advance-phase permission gate rather than letting any owner
    # flip the whole league into the postseason.
    if not can_progress:
        result["playoffs_pending_commissioner"] = True
        return
    # Refresh standings so the bracket seeds off the just-finished season, then
    # build it BEFORE flipping the phase (a bracket that can't seed leaves the
    # league recoverable in REGULAR_SEASON) — same order as /advance-phase.
    _sync_standings_from_stats()
    try:
        bracket = _ensure_playoff_bracket()
    except Exception as exc:  # pragma: no cover - defensive
        bracket = {"error": str(exc)}
    if not bracket or (isinstance(bracket, dict) and bracket.get("error")):
        result["playoffs_error"] = (
            (bracket.get("error") if isinstance(bracket, dict) else None)
            or "Couldn't seed the playoff bracket — standings or teams are missing."
        )
        return
    try:
        new_phase = manager.advance_phase()
    except Exception as exc:  # pragma: no cover - defensive
        result["playoffs_error"] = f"Failed to enter playoffs: {exc}"
        return
    result["new_phase"] = new_phase.value
    if new_phase == SeasonPhase.PLAYOFFS:
        result["playoffs"] = bracket


def _launch_sim_background(
    kind: str,
    *,
    n_arg: int = 1,
    team_id: Optional[str] = None,
    can_progress: bool = False,
) -> int:
    """Start a sim in a daemon thread and return its run id immediately.

    The thread rebinds the per-request league (ContextVars don't cross the
    thread boundary), runs the sim, builds the state payload, and pushes the
    working copy to durable storage — mirroring the export/asset jobs. The
    client polls /season/sim-progress until ``status`` flips to done/error.
    """
    from utils import path_utils

    league = path_utils.get_active_league_id()
    run_id = _begin_sim_job()

    def _run() -> None:
        token = path_utils.set_request_league(league) if league else None
        try:
            manager, simulator, draft_date = _build_manager_and_simulator()
            n = _days_for_kind(kind, n_arg, simulator, draft_date)
            result = _simulate_n(
                manager, simulator, n, draft_date=draft_date, team_id=team_id
            )
            # 'To Playoffs' means "take me INTO the postseason", not just to the
            # last regular-season day — seed the bracket + flip the phase once
            # the schedule is complete (permission-gated like /advance-phase).
            if kind == "to-playoffs":
                _maybe_enter_playoffs(
                    manager, simulator, result, can_progress=can_progress
                )
            payload = _state_payload(manager, simulator, draft_date, extra=result)
            # Persist sim writes (season_state, standings, stats, rosters…) to
            # GCS. The request middleware already returned on the 202, so the
            # push must happen here or a restart would lose the simulated days.
            try:
                from api import working_copy

                if working_copy.is_enabled():
                    working_copy.push_changes()
            except Exception:
                import logging

                logging.getLogger("nexgen.season").exception(
                    "sim working-copy push failed"
                )
            _finish_sim_job(result=payload)
        except Exception as exc:  # pragma: no cover - defensive
            import logging

            logging.getLogger("nexgen.season").exception("Background sim failed")
            _finish_sim_job(error=str(exc))
        finally:
            if token is not None:
                path_utils.reset_request_league(token)

    threading.Thread(target=_run, name=f"sim-{kind}", daemon=True).start()
    return run_id


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


def _auto_initialize_draft(draft_date: str) -> Dict[str, Any]:
    """Seed draft order + pool when the sim first hits draft day.

    Idempotent: if the draft state file for this year already exists,
    the call is a no-op so re-runs (or admins who already initialized
    manually) don't get clobbered. Failures are returned in the result
    rather than raised so the sim's draft-day intercept stays robust.
    """

    out: Dict[str, Any] = {"order_seeded": False, "pool_seeded": False}
    try:
        year = int(str(draft_date).split("-")[0])
    except Exception as exc:
        out["error"] = f"bad draft_date {draft_date!r}: {exc}"
        return out

    try:
        from services import draft_state as _ds
    except Exception as exc:
        out["error"] = f"draft_state import failed: {exc}"
        return out

    existing = _ds.load_state(year) or {}
    if not existing:
        try:
            order = _ds.compute_order_for_draft_year(year)
        except Exception as exc:
            out["error"] = f"order compute failed: {exc}"
            return out
        if not order:
            out["error"] = "no season stats yet — cannot compute draft order"
            return out
        supplemental: List[str] = []
        forfeited: List[str] = []
        rounds = 10
        try:
            from services.qualifying_offers import compensation_for_draft
            from services.draft_settings import load_draft_settings

            comp = compensation_for_draft(year)
            supplemental = list(comp.get("comp_teams", []))
            forfeited = list(comp.get("forfeit_teams", []))
            rounds = int(load_draft_settings().rounds)
        except Exception:
            supplemental, forfeited = [], []
        try:
            _ds.initialize_state(
                year,
                order=order,
                total_rounds=rounds,
                supplemental=supplemental,
                forfeited=forfeited,
            )
            out["order_seeded"] = True
            out["order_count"] = len(order)
            out["compensation_picks"] = len(supplemental)
        except Exception as exc:
            out["error"] = f"order init failed: {exc}"
            return out
    else:
        out["order_already_existed"] = True

    # Seed the amateur pool only if it's not already on disk for this year.
    pool_path = get_data_dir() / f"draft_pool_{year}.csv"
    if not pool_path.exists():
        try:
            from services.draft_settings import load_draft_settings
            from playbalance.draft_pool import generate_draft_pool, save_draft_pool

            settings = load_draft_settings()
            pool = generate_draft_pool(year=year, size=settings.pool_size)
            # generate_draft_pool returns the list — save_draft_pool is
            # what actually writes it to disk for the draft endpoints.
            save_draft_pool(year, pool)
            out["pool_seeded"] = True
            out["pool_size"] = settings.pool_size
        except Exception as exc:
            out["pool_error"] = f"pool generation failed: {exc}"
    else:
        out["pool_already_existed"] = True

    return out


def _build_manager_and_simulator() -> tuple[SeasonManager, SeasonSimulator, Optional[str]]:
    schedule = _load_schedule()
    first_date = schedule[0].get("date") if schedule else None
    draft_date = _compute_draft_date(first_date)

    # When the sim crosses the All-Star break midpoint, run the actual
    # game (roster select + flavor sim + MVP) instead of letting the
    # break exist as a 6-day calendar gap with no event.
    def _fire_all_star() -> None:
        try:
            from services.all_star_game import play_all_star_game

            year = None
            if first_date:
                try:
                    year = int(str(first_date).split("-")[0])
                except Exception:
                    year = None
            if year is None:
                from datetime import date as _date

                year = _date.today().year
            play_all_star_game(year=year)
        except Exception:
            # Flavor feature — never block the sim if it errors.
            pass

    manager = SeasonManager()
    simulator = SeasonSimulator(
        schedule,
        simulate_game_scores,
        draft_date=draft_date,
        on_all_star_break=_fire_all_star,
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
        # Authoritative flags so the UI never has to *infer* season state from
        # current_date/draft_date (which is what produced the contradictory
        # "next milestone is the draft" banner at season end). ``season_complete``
        # means the whole regular-season schedule is played; ``draft_completed``
        # means the amateur draft for this year is committed to disk.
        "season_complete": len(simulator.dates) > 0
        and simulator._index >= len(simulator.dates),
        "draft_completed": _draft_completed_for_current_year(),
        # True only in PLAYOFFS once a champion is crowned — lets the UI gate
        # the Advance Phase button to match the backend's champion guard.
        "playoffs_complete": (
            _playoffs_champion_recorded()
            if manager.phase == SeasonPhase.PLAYOFFS
            else False
        ),
        "preseason_done": _read_preseason_done(),
    }
    if extra:
        payload.update(extra)
    return payload


def _read_preseason_done() -> Dict[str, bool]:
    """Read the preseason_done flags from season_progress.json so the UI
    can disable buttons that were already executed this preseason."""

    import json as _json

    progress_path = get_data_dir() / "season_progress.json"
    out = {"free_agency": False, "training_camp": False, "schedule": False}
    if not progress_path.exists():
        return out
    try:
        payload = _json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        return out
    if not isinstance(payload, dict):
        return out
    done = payload.get("preseason_done")
    if isinstance(done, dict):
        for key in out:
            if bool(done.get(key)):
                out[key] = True
    return out


def _team_roster_compliance_errors(team_id: str | None) -> List[str]:
    """Return a list of human-readable compliance errors for the user's
    team. Empty list means the roster is legal and the sim can proceed.

    Scoped to the owner's team rather than the entire league — CPU
    teams can carry temporary cap violations after the draft commits,
    and we don't want a CPU's busted roster to block the human from
    advancing the calendar.
    """

    if not team_id:
        return []

    from api.routers.validation import load_players_map, load_team_levels
    from services.roster_validation import (
        DEFAULT_LEVEL_CAPS,
        validate_roster_state,
    )

    from utils.roster_loader import active_roster_cap

    players = load_players_map()
    levels = load_team_levels(team_id)
    # S2-11: honor September expansion (ACT cap 25 -> 28 while REGULAR_SEASON).
    result = validate_roster_state(
        current_levels=levels,
        players=players,
        level_caps={**DEFAULT_LEVEL_CAPS, "act": active_roster_cap()},
    )
    return [f"{team_id}: {msg}" for msg in result.errors]


def _simulate_n(
    manager: SeasonManager,
    simulator: SeasonSimulator,
    n: int,
    *,
    draft_date: Optional[str] = None,
    team_id: Optional[str] = None,
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

    When ``team_id`` is set the notification engine runs after each day
    and the loop breaks early as soon as a rule with ``stop_sim=True``
    fires — that's how owners get the "stop on injury" behavior they
    configure on the Notifications page.
    """

    n = max(1, min(int(n), _MAX_DAYS_PER_CALL))
    played_dates: List[str] = []
    errors: List[str] = []
    draft_blocked = False
    notification_events: List[NotificationEvent] = []
    stop_reason: Optional[str] = None
    # A committed draft means the AMATEUR_DRAFT pause is over — resume the
    # regular season automatically rather than dead-ending the sim buttons.
    # This also self-heals any league left parked in AMATEUR_DRAFT by an
    # older build (the draft is a mid-season interruption, not a phase the
    # owner should have to manually Advance out of).
    if manager.phase == SeasonPhase.AMATEUR_DRAFT and _draft_completed_for_current_year():
        manager.phase = SeasonPhase.REGULAR_SEASON
        manager.save()

    # Regular-season games can only be simulated while the league is in
    # the REGULAR_SEASON phase. Without this gate a fresh league sitting
    # in PRESEASON will happily play games even though the owner hasn't
    # advanced past spring training, breaking the preseason workflow
    # (training camp readiness, free-agency review, etc.).
    if manager.phase != SeasonPhase.REGULAR_SEASON:
        errors.append(
            f"Cannot simulate games in {manager.phase.value} phase — "
            f"advance to REGULAR_SEASON first."
        )
        return {
            "played_dates": played_dates,
            "errors": errors,
            "draft_blocked": draft_blocked,
            "sim_stopped_reason": "phase_blocked",
        }

    # Roster-compliance gate. Refuse to advance the calendar while the
    # owner's team isn't carrying a legal roster — most often this
    # fires after the amateur draft commits picks into LOW and pushes
    # the team over the 10-player cap, but it also catches missing
    # defensive coverage or an active roster that's lost too many
    # position players. CPU teams' busted rosters are out of scope for
    # this gate; an admin can run a cleanup utility for those.
    try:
        compliance_errors = _team_roster_compliance_errors(team_id)
    except Exception as exc:
        # Fail closed: if we can't validate the roster (corrupt/missing data
        # file, etc.) we must NOT silently let a possibly-illegal roster sim.
        # Surface the failure so the user can fix it instead of swallowing it.
        compliance_errors = [
            f"Couldn't validate roster compliance ({exc}). "
            "Resolve the data issue before simulating."
        ]
    if compliance_errors:
        errors.extend(compliance_errors)
        return {
            "played_dates": played_dates,
            "errors": errors,
            "draft_blocked": draft_blocked,
            "sim_stopped_reason": "roster_noncompliant",
        }
    # An empty schedule means ``simulator.dates`` is zero-length — without
    # this check the sim quietly "plays" 0 days, which looks to the user
    # like the button did nothing. Surface an explicit error so the UI
    # can show a banner pointing them at /admin-league to regenerate.
    if len(simulator.dates) == 0:
        errors.append(
            "No schedule loaded. Generate one from Admin → Regenerate schedule."
        )

    notif_settings = (
        load_notification_settings(team_id) if team_id else None
    )

    # Seed the live progress tracker with the realistic upper bound so
    # the overlay can show "X of Y days" instead of just spinning. The
    # actual played count may finish lower if a draft-day intercept or
    # an injury notification stops the run early. ``_end_sim_progress``
    # is called on the normal return path; the only way to leave it set
    # is an unhandled exception bubbling out of FastAPI, in which case
    # the next ``_begin_sim_progress`` call resets it.
    playable = max(0, min(n, len(simulator.dates) - simulator._index))
    _begin_sim_progress(playable)

    for _ in range(n):
        # Cooperative cancellation: stop after the current day on request. The
        # days already played are persisted below, so cancelling is safe.
        if _sim_cancel_requested():
            stop_reason = "Simulation cancelled"
            break
        if simulator._index >= len(simulator.dates):
            break
        target_date = simulator.dates[simulator._index]
        # Draft-day intercept. PyQt's ``_on_draft_day`` pauses the sim
        # and opens the draft console; the React equivalent is to stop,
        # flip the phase, and hand off to /draft. Skip the pause once the
        # draft for this year is already committed — otherwise the cursor,
        # which is parked on draft day, would re-trigger the draft on every
        # Sim Day and dead-lock the season right after the draft finishes.
        if (
            draft_date
            and target_date == draft_date
            and not _draft_completed_for_current_year()
        ):
            try:
                manager.phase = SeasonPhase.AMATEUR_DRAFT
                manager.save()
            except Exception:
                pass
            # Auto-seed draft order + pool so the owner doesn't have to
            # log in as admin and run the two prep buttons before the
            # draft is usable. Idempotent, error-tolerant.
            try:
                draft_init = _auto_initialize_draft(draft_date)
                if draft_init.get("error"):
                    errors.append(
                        f"Draft auto-init: {draft_init['error']}"
                    )
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"Draft auto-init crashed: {exc}")
            draft_blocked = True
            break

        # Snapshot pre-day state for the notification engine. Cheap —
        # one news file stat, one standings read, one finance file read.
        pre_state = None
        pre_phase = None
        if notif_settings is not None and team_id:
            try:
                pre_phase = getattr(manager, "phase", None)
                pre_phase_str = pre_phase.name if pre_phase is not None else None
                pre_state = capture_pre_state(team_id, phase=pre_phase_str)
            except Exception:
                pre_state = None

        try:
            simulator.simulate_next_day()
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"{target_date}: {exc}")
            break
        played_dates.append(target_date)
        _bump_sim_progress()

        if notif_settings is not None and team_id and pre_state is not None:
            try:
                post_phase = getattr(manager, "phase", None)
                post_phase_str = post_phase.name if post_phase is not None else None
                day_events = detect_events(
                    team_id,
                    notif_settings,
                    pre_state,
                    sim_date=target_date,
                    new_phase=post_phase_str,
                )
            except Exception:
                day_events = []
            if day_events:
                notification_events.extend(day_events)
                try:
                    append_history(team_id, day_events)
                except Exception:
                    pass
                # Stop the multi-day sim early as soon as one fires —
                # the owner asked to be paused for this kind of event.
                stopper = next((e for e in day_events if e.stop_sim), None)
                if stopper is not None:
                    stop_reason = stopper.title
                    break

    # Persist what the in-memory simulator just mutated (schedule
    # results, standings rollup, progress cursor). Without this the
    # next request would rebuild the simulator from a "no games
    # played" schedule and we'd silently re-sim day 1 forever — and
    # the standings page would keep showing 0-0 records.
    if played_dates:
        _persist_post_sim_state(simulator, played_dates)

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
    if notification_events:
        result["notifications"] = [e.to_dict() for e in notification_events]
    if stop_reason:
        result["sim_stopped_reason"] = stop_reason
    _end_sim_progress()
    return result


def _persist_post_sim_state(
    simulator: SeasonSimulator, played_dates: List[str]
) -> None:
    """Write everything the sim mutated in-memory back to disk.

    The simulator updates ``self.schedule`` with each game's score and
    advances ``self._index`` per day, but never writes those out — so
    on the next HTTP request we'd rebuild a fresh simulator from a
    schedule with no played markers and re-sim day 1 forever. This
    also seeds ``standings.json`` from the team rollups in
    ``season_stats.json`` (the full simulator updates per-team season
    stats but skips the standings file). Finally, the schedule cursor
    in ``season_progress.json`` is bumped so the UI shows the new
    ``days_played`` immediately.

    Each block is best-effort: a single failure can't roll back the
    games we already simulated.
    """

    if not played_dates:
        return

    # 1. Persist the schedule with the now-populated result + played columns.
    try:
        from playbalance.schedule_generator import save_schedule
        from playbalance.simulation import save_boxscore_html

        played_set = {str(d) for d in played_dates}
        for game in simulator.schedule:
            if str(game.get("date", "")) in played_set:
                # `_apply_result_to_game` already set ``result``; mark
                # the row played so subsequent requests skip it.
                if str(game.get("result", "")).strip():
                    game["played"] = "1"
                # The simulator hands back the rendered boxscore HTML under
                # ``boxscore_html``. Write it to data/boxscores/season/ and
                # store the PATH in the schedule's ``boxscore`` column (S1-04)
                # — the boxscore API serves by path, and embedding megabytes
                # of HTML in schedule.csv made every save O(season).
                html = game.pop("boxscore_html", None)
                if html and not game.get("boxscore"):
                    try:
                        game_id = (
                            f"{game.get('date', '')}_{game.get('away', '')}"
                            f"_at_{game.get('home', '')}"
                        )
                        game["boxscore"] = save_boxscore_html(
                            "season", str(html), game_id
                        )
                    except Exception:
                        pass
        save_schedule(simulator.schedule, _schedule_path())
    except Exception:
        pass

    # 2. Sync standings.json from season_stats teams rollup.
    _sync_standings_from_stats()

    # 3. Bump season_progress.json::sim_index so phase / progress widgets
    # update without waiting for a refetch of the schedule walk.
    try:
        import json

        progress_path = get_data_dir() / "season_progress.json"
        progress: Dict[str, Any] = {}
        if progress_path.exists():
            try:
                progress = json.loads(progress_path.read_text(encoding="utf-8"))
                if not isinstance(progress, dict):
                    progress = {}
            except Exception:
                progress = {}
        progress["sim_index"] = int(simulator._index)
        progress_path.write_text(
            json.dumps(progress, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


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

    try:
        from services.inseason_callups import run_monthly_callups

        summary["callups"] = run_monthly_callups(
            played_dates=played_dates, data_dir=get_data_dir()
        )
    except Exception as exc:  # pragma: no cover - defensive
        summary["callups_error"] = str(exc)

    return summary


# ---------------------------------------------------------------------------
# Endpoints


@router.get("/state")
def season_state() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    return _state_payload(manager, simulator, draft_date)


@router.get("/sim-progress")
def sim_progress() -> Dict[str, Any]:
    """Live "X of Y days" snapshot polled by the SimProgressOverlay.

    Returns the in-process counters set by ``_simulate_n`` so the
    overlay can replace its indeterminate progress bar with a real
    "3 of 30 days" readout. ``active`` flips false the moment the sim
    request returns; ``elapsed_seconds`` is computed server-side so the
    client doesn't need its own clock.
    """

    with _SIM_PROGRESS_LOCK:
        snap = dict(_SIM_PROGRESS)
    started_at = float(snap.get("started_at") or 0.0)
    elapsed = max(0.0, time.time() - started_at) if started_at else 0.0
    return {
        "active": bool(snap.get("active")),
        "target": int(snap.get("target") or 0),
        "played": int(snap.get("played") or 0),
        "elapsed_seconds": round(elapsed, 1),
        # Background-job fields. The client polls these to learn when a
        # background sim has finished (and to pick up its final state) instead
        # of holding the sim request open past the proxy timeout.
        "status": str(snap.get("status") or "idle"),
        "run_id": int(snap.get("run_id") or 0),
        "result": snap.get("result"),
        "error": snap.get("error"),
        "cancel_requested": bool(snap.get("cancel_requested")),
    }


@router.post("/sim-cancel")
def sim_cancel(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    """Request cancellation of the in-flight simulation. It stops after the
    current day; days already simulated are kept. No-op if nothing is running."""

    cancelled = _request_sim_cancel()
    with _SIM_PROGRESS_LOCK:
        run_id = int(_SIM_PROGRESS.get("run_id") or 0)
    return {"cancel_requested": cancelled, "run_id": run_id}


def _team_id_from_identity(identity: Dict[str, Any]) -> Optional[str]:
    raw = str(identity.get("t") or "").strip()
    return raw or None


# All multi-day sims run as background jobs (see _launch_sim_background): the
# endpoint returns immediately with {status:"running", run_id} and the client
# polls /season/sim-progress for the final state. This keeps every sim request
# well under the proxy/request timeout no matter how many days it spans.


def _start_sim(kind: str, identity: Dict[str, Any], *, n_arg: int = 1) -> Dict[str, Any]:
    if _sim_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A simulation is already in progress.",
        )
    # Whether this caller may drive season progression (commissioner in owner
    # leagues, the owner in solo leagues). Only used by 'to-playoffs' to decide
    # if it can flip the whole league into the postseason once the schedule ends.
    from utils.league_settings import can_run_season_progression

    can_progress = can_run_season_progression(str(identity.get("r", "")).lower())
    run_id = _launch_sim_background(
        kind,
        n_arg=n_arg,
        team_id=_team_id_from_identity(identity),
        can_progress=can_progress,
    )
    return {"status": "running", "run_id": run_id, "kind": kind}


@router.post("/simulate/day")
def simulate_day(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    return _start_sim("day", identity)


@router.post("/simulate/days")
def simulate_days(
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    try:
        n = int(payload.get("n", 1))
    except (TypeError, ValueError):
        n = 1
    return _start_sim("days", identity, n_arg=n)


@router.post("/simulate/week")
def simulate_week(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    return _start_sim("week", identity)


@router.post("/simulate/month")
def simulate_month(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    return _start_sim("month", identity)


@router.post("/simulate/to-draft")
def simulate_to_draft(
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    return _start_sim("to-draft", identity)


@router.post("/simulate/to-playoffs")
def simulate_to_playoffs(
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    return _start_sim("to-playoffs", identity)


@router.post("/advance-phase")
def advance_phase(
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    # In owner leagues phase advancement belongs to the commissioner;
    # in solo leagues the owner is the only one who can do it (and is
    # allowed to). ``can_run_season_progression`` collapses both cases.
    from utils.league_settings import can_run_season_progression

    role = str(identity.get("r", "")).lower()
    if not can_run_season_progression(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Phase advancement is restricted to the commissioner in "
                "owner leagues."
            ),
        )

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

    # Guard: leaving REGULAR_SEASON for the PLAYOFFS requires the WHOLE
    # schedule to have been played. The amateur draft is a mid-season
    # interruption (handled by the sim's draft-day intercept + the draft
    # console), not the end of the regular season — so the gate is the end
    # of the schedule, never the draft date. Without this, Advance Phase
    # could skip August/September and jump an unfinished season straight to
    # the playoffs.
    if (
        manager.phase == SeasonPhase.REGULAR_SEASON
        and len(simulator.dates) > 0
        and not force
    ):
        stop_idx = len(simulator.dates)
        if simulator._index < stop_idx:
            remaining = stop_idx - simulator._index
            # Point at the draft only while it's still ahead on the calendar.
            draft_ahead = (
                bool(draft_date)
                and draft_date in simulator.dates
                and simulator._index < simulator.dates.index(draft_date)
            )
            use_button = "To Draft" if draft_ahead else "To Playoffs"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Regular season not finished — {remaining} game "
                    f"day(s) remain. Use '{use_button}' to play the "
                    "remaining days before advancing."
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

    # Guard: require a crowned champion before leaving PLAYOFFS.
    # Otherwise Advance Phase can flip to OFFSEASON on an unfinished
    # bracket and the post-season workflows run against stale state.
    if manager.phase == SeasonPhase.PLAYOFFS and not force:
        if not _playoffs_champion_recorded():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Playoffs aren't finished — no champion has been "
                    "recorded. Resolve the bracket from /playoffs before "
                    "advancing past this phase."
                ),
            )

    # Hard finance deadline: a team must be solvent to start the season.
    # Exceeding the luxury threshold is allowed (it's taxed in-season); this
    # only blocks an Opening Day that would begin insolvent (projected debt over
    # the league cap). Enforcement-off leagues always pass.
    if manager.phase == SeasonPhase.PRESEASON and not force:
        opening_team = str(identity.get("t") or "").strip()
        if opening_team:
            try:
                from services.payroll_policy import evaluate_opening_day_payroll

                solvency = evaluate_opening_day_payroll(
                    opening_team, data_dir=get_data_dir()
                )
            except Exception:  # pragma: no cover - defensive
                solvency = None
            if solvency is not None and not solvency.allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Your team isn't solvent for Opening Day — projected debt "
                        "exceeds the league cap. Clear debt or shed payroll before "
                        "starting the regular season."
                    ),
                )

    # Build + verify the playoff bracket BEFORE flipping into PLAYOFFS. The
    # old order flipped the phase first and built the bracket after in a
    # swallow-all try/except — so a failed build stranded the league in
    # PLAYOFFS with nothing to render and the champion gate blocking any
    # further advance (a dead-end only ``force`` could escape). Now, on the
    # normal path, a bracket that can't be seeded raises and leaves the league
    # in REGULAR_SEASON, fully recoverable.
    pending_bracket: Optional[Dict[str, Any]] = None
    if manager.phase == SeasonPhase.REGULAR_SEASON and not force:
        # The bracket seeds from standings — make sure they reflect the
        # just-finished season before we read them.
        _sync_standings_from_stats()
        try:
            pending_bracket = _ensure_playoff_bracket()
        except Exception as exc:  # pragma: no cover - defensive
            pending_bracket = {"error": str(exc)}
        if not pending_bracket or (
            isinstance(pending_bracket, dict) and pending_bracket.get("error")
        ):
            detail = (
                pending_bracket.get("error")
                if isinstance(pending_bracket, dict)
                else None
            ) or (
                "Couldn't seed the playoff bracket — standings or teams are "
                "missing. Sim the final regular-season day (or regenerate "
                "standings) and try again."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=detail
            )

    try:
        new_phase: SeasonPhase = manager.advance_phase()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to advance phase: {exc}",
        ) from exc

    extra: Dict[str, Any] = {"new_phase": new_phase.value}

    if new_phase == SeasonPhase.PLAYOFFS:
        if pending_bracket and not (
            isinstance(pending_bracket, dict) and pending_bracket.get("error")
        ):
            extra["playoffs"] = pending_bracket
        else:
            # Force path (pre-check skipped): best-effort build, surface any
            # error so the admin who forced through sees what's missing.
            try:
                bracket_summary = _ensure_playoff_bracket()
                if bracket_summary:
                    extra["playoffs"] = bracket_summary
            except Exception as exc:  # pragma: no cover - defensive
                extra["playoffs_error"] = str(exc)

    # OFFSEASON → PRESEASON: spring training camp normally requires a
    # manual click on the preseason checklist. In solo-player leagues
    # there's no reason to gate it — auto-run so opening day finds
    # players with their fresh ratings already applied.
    if new_phase == SeasonPhase.PRESEASON:
        # A new season has begun — make sure it has a schedule so the
        # commissioner doesn't have to manually regenerate one every year.
        try:
            extra["schedule"] = _ensure_new_season_schedule()
        except Exception as exc:  # pragma: no cover - defensive
            extra["schedule_error"] = str(exc)
        try:
            extra["training_camp"] = _auto_run_training_camp_if_needed()
        except Exception as exc:  # pragma: no cover - defensive
            extra["training_camp_error"] = str(exc)
        # If a schedule was just generated, rebuild the simulator so the
        # returned payload reflects the new game count (days_total, draft_date).
        if isinstance(extra.get("schedule"), dict) and extra["schedule"].get(
            "generated"
        ):
            try:
                manager, simulator, draft_date = _build_manager_and_simulator()
            except Exception:  # pragma: no cover - defensive
                pass

    # REGULAR_SEASON → AMATEUR_DRAFT (manual phase advance, not via the
    # sim hitting draft day): make sure the order + pool are seeded so
    # the user lands on a usable draft console.
    if new_phase == SeasonPhase.AMATEUR_DRAFT and draft_date:
        try:
            init_summary = _auto_initialize_draft(draft_date)
            extra["draft_init"] = init_summary
        except Exception as exc:  # pragma: no cover - defensive
            extra["draft_init_error"] = str(exc)

    return _state_payload(manager, simulator, draft_date, extra=extra)


def _ensure_new_season_schedule() -> Dict[str, Any]:
    """Generate a schedule for the new season if one doesn't exist yet.

    Runs on the OFFSEASON → PRESEASON transition so every new season starts
    with a schedule automatically — the commissioner no longer has to manually
    regenerate one each year. Idempotent: a non-empty existing schedule is left
    untouched. Uses the new ``league_year`` (the season rollover already
    advanced it when archiving the prior season).
    """

    try:
        if _load_schedule():
            return {"generated": False, "reason": "schedule_exists"}
    except Exception:
        pass

    data_root = get_data_dir()
    try:
        from utils.team_loader import load_teams

        teams = [t.team_id for t in load_teams(data_root / "teams.csv")]
    except Exception as exc:
        return {"generated": False, "reason": f"teams_error: {exc}"}
    if not teams:
        return {"generated": False, "reason": "no_teams"}

    year: Optional[int] = None
    try:
        from playbalance.season_context import SeasonContext

        ctx = SeasonContext.load()
        cur = ctx.current if isinstance(ctx.current, dict) else {}
        if cur.get("league_year") is not None:
            year = int(cur["league_year"])
    except Exception:
        year = None
    if year is None:
        from datetime import date as _date

        year = _date.today().year

    # Default schedule template — matches league creation / admin regenerate.
    template_id = "mlb_162"
    try:
        from services.league_presets import generate_schedule_from_template
        from playbalance.schedule_generator import save_schedule

        schedule = generate_schedule_from_template(template_id, teams, year=year)
        if not schedule:
            return {"generated": False, "reason": "empty_schedule"}
        save_schedule(schedule, _schedule_path())
    except Exception as exc:
        return {"generated": False, "reason": str(exc)}
    return {
        "generated": True,
        "games": len(schedule),
        "year": year,
        "template_id": template_id,
    }


def _auto_run_training_camp_if_needed() -> Dict[str, Any]:
    """Trigger spring training automatically when entering PRESEASON.

    Idempotent: skips if ``preseason_done.training_camp`` is already
    set in season_progress.json. Owner leagues can still re-run from
    the preseason checklist; this just removes the click for solo
    players who otherwise hit "I have to log in as admin to start a
    new season" frustration.
    """

    out: Dict[str, Any] = {"ran": False}
    progress_path = get_data_dir() / "season_progress.json"
    try:
        if progress_path.exists():
            import json as _json

            payload = _json.loads(progress_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                done = payload.get("preseason_done") or {}
                if isinstance(done, dict) and done.get("training_camp"):
                    out["skipped"] = "already_done"
                    return out
    except Exception:
        pass
    try:
        result = preseason_training_camp()
        out["ran"] = True
        out.update(result)
    except HTTPException as exc:
        out["error"] = str(exc.detail)
    return out


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


def _run_cpu_free_agency_async() -> None:
    """Run the CPU free-agency market in a background daemon thread.

    The market re-parses teams/players/rosters for several rounds and writes
    signings across the whole league — far too heavy to run inline on the
    preseason "show me the free agents" request (that's what left the button
    spinning). Mirrors the background-sim job: rebind the league (ContextVars
    don't cross threads), run, then push the working copy so signings persist.
    """
    from utils import path_utils

    league = path_utils.get_active_league_id()

    def _run() -> None:
        import logging

        token = path_utils.set_request_league(league) if league else None
        try:
            from services.free_agency import run_cpu_free_agency_market

            run_cpu_free_agency_market(data_dir=get_data_dir())
            try:
                from api import working_copy

                if working_copy.is_enabled():
                    working_copy.push_changes()
            except Exception:
                logging.getLogger("nexgen.season").exception(
                    "CPU free-agency working-copy push failed"
                )
        except Exception:
            logging.getLogger("nexgen.season").exception(
                "Background CPU free agency failed"
            )
        finally:
            if token is not None:
                path_utils.reset_request_league(token)

    threading.Thread(target=_run, name="cpu-free-agency", daemon=True).start()


@router.post("/preseason/list-unsigned")
def preseason_list_unsigned(
    payload: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    """List unsigned free agents; kick off the CPU market in the background.

    Listing is read-only and fast. The CPU free-agency cycle (CPU teams filling
    roster holes) is heavy, so it runs in a background thread instead of
    blocking this request — previously it ran inline and left the UI spinning,
    especially right after a season rollover when the unsigned pool is large.
    This step is optional: it lets you review/sign free agents, but the season
    can be played without it.
    """

    run_cpu = bool(payload.get("run_cpu", True))
    cpu_running = False
    if run_cpu:
        try:
            _run_cpu_free_agency_async()
            cpu_running = True
        except Exception:  # pragma: no cover - defensive
            cpu_running = False

    try:
        from services.free_agency import list_unsigned_players_from_files

        agents = list(list_unsigned_players_from_files())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list unsigned players: {exc}",
        ) from exc

    names = [
        f"{getattr(p, 'first_name', '')} {getattr(p, 'last_name', '')}".strip()
        for p in agents
    ]

    _mark_preseason_done("free_agency")

    return {
        "unsigned_count": len(agents),
        "unsigned_names": names[:50],  # cap for payload size
        # CPU signings now settle in the background; report that it's running
        # rather than a (not-yet-known) count.
        "cpu_signed": 0,
        "cpu_rounds": 0,
        "cpu_applied": False,
        "cpu_running": cpu_running,
    }


@router.post("/preseason/training-camp")
def preseason_training_camp() -> Dict[str, Any]:
    """Run spring training camp for every player.

    Ports ``ui/season_progress_window._run_training_camp``. Marks the
    ``preseason_done.training_camp`` flag so the UI reflects completion.
    """

    data_dir = get_data_dir()

    try:
        from utils.player_loader import load_players_from_csv
        from services.players_repository import save_players

        players = list(load_players_from_csv(data_dir / "players.csv"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load players: {exc}",
        ) from exc

    if not players:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No players loaded — training camp has nothing to run.",
        )

    # Build per-player team lookup from rosters for training focus + intensity.
    team_lookup: Dict[str, str] = {}
    try:
        from utils.roster_loader import load_roster

        roster_dir = data_dir / "rosters"
        if roster_dir.exists():
            for roster_file in roster_dir.glob("*.csv"):
                team_id = roster_file.stem
                try:
                    roster = load_roster(team_id, roster_dir)
                except Exception:
                    continue
                for pid in list(getattr(roster, "act", []) or []) + list(
                    getattr(roster, "aaa", []) or []
                ) + list(getattr(roster, "low", []) or []):
                    team_lookup[str(pid)] = team_id
    except Exception:
        pass

    # Resolve training allocations (team-override → league-default).
    allocations: Dict[str, Any] = {}
    try:
        from services.training_settings import load_training_settings

        settings = load_training_settings()
        for player in players:
            pid = getattr(player, "player_id", None)
            if pid is None:
                continue
            team_id = team_lookup.get(str(pid))
            allocations[str(pid)] = settings.for_player(str(pid), team_id)
    except Exception:
        allocations = {}

    # Per-player intensity multipliers from finance budgets.
    intensity: Dict[str, float] = {}
    try:
        from services.finance_budget_effects import (
            training_camp_multiplier_by_player,
        )

        intensity = training_camp_multiplier_by_player(
            team_lookup,
            data_dir=data_dir,
        )
    except Exception:
        intensity = {}

    try:
        from playbalance.training_camp import run_training_camp

        reports = run_training_camp(
            players,
            allocations=allocations or None,
            intensity_by_player=intensity or None,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Training camp simulation failed: {exc}",
        ) from exc

    try:
        save_players(players, data_dir / "players.csv")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Training complete but saving players failed: {exc}",
        ) from exc

    # Persist this year's per-player rating deltas so the player-profile
    # career ledger can show "(+x)" badges next to the current ratings.
    # Overwrites each year so the file always reflects the most recent
    # spring training rather than accumulating noise.
    try:
        import json as _json
        from datetime import date as _date

        deltas_path = data_dir / "spring_training_last.json"
        deltas_payload: Dict[str, Any] = {
            "year": _date.today().year,
            "players": {},
        }
        for report in reports:
            pid = getattr(report, "player_id", None)
            if not pid:
                continue
            changes = {
                str(k): int(v)
                for k, v in (getattr(report, "changes", {}) or {}).items()
                if v
            }
            if not changes:
                continue
            deltas_payload["players"][str(pid)] = {
                "focus": str(getattr(report, "focus", "") or ""),
                "changes": changes,
            }
        deltas_path.parent.mkdir(parents=True, exist_ok=True)
        deltas_path.write_text(
            _json.dumps(deltas_payload, indent=2), encoding="utf-8"
        )
    except Exception:
        # Non-fatal: the deltas badge is a nice-to-have, training itself
        # already succeeded.
        pass

    # Build a compact top-gainers summary for the UI toast.
    top_gainers: list[Dict[str, Any]] = []
    try:
        ranked = sorted(
            reports,
            key=lambda r: sum((getattr(r, "changes", {}) or {}).values()),
            reverse=True,
        )[:3]
        players_by_id = {
            getattr(p, "player_id", ""): p for p in players
        }
        for report in ranked:
            pid = getattr(report, "player_id", "") or ""
            player = players_by_id.get(pid)
            name = (
                f"{getattr(player, 'first_name', '')} "
                f"{getattr(player, 'last_name', '')}".strip()
                if player is not None
                else pid
            )
            changes = getattr(report, "changes", {}) or {}
            gain_total = sum(float(v) for v in changes.values())
            top_gainers.append(
                {
                    "player_id": pid,
                    "name": name,
                    "focus": str(getattr(report, "focus", "")),
                    "total_gain": round(gain_total, 2),
                }
            )
    except Exception:
        top_gainers = []

    _mark_preseason_done("training_camp")

    return {
        "players_processed": len(players),
        "top_gainers": top_gainers,
    }


def _mark_preseason_done(flag: str) -> None:
    """Set ``preseason_done.{flag} = True`` in season_progress.json."""

    import json as _json

    progress_path = get_data_dir() / "season_progress.json"
    try:
        payload: Dict[str, Any] = {}
        if progress_path.exists():
            try:
                payload = _json.loads(progress_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        done = payload.setdefault("preseason_done", {})
        if isinstance(done, dict):
            done[flag] = True
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(
            _json.dumps(payload, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _team_records_from_schedule() -> Dict[str, Dict[str, int]]:
    """Compute team W/L/RF/RA from the authoritative played schedule.

    Standings are a PURE FUNCTION of the game results in schedule.csv, so this
    is idempotent — re-running or overlapping sims can never inflate it (marking
    a game played twice is harmless). This is deliberately NOT derived from the
    ``season_stats`` team rollup, which accumulates on an in-memory counter and
    was observed to drift badly (team records inflated ~2.5x, some teams dropped
    entirely) when sims overlapped, even though the schedule and the player
    stats stayed correct. Every team that has appeared in a decided game is
    included, so no team can silently show 0-0.

    Only rows with a parseable ``home-away`` score (written as ``f"{home}-{away}"``
    by ``season_simulator._apply_result_to_game``) count.
    """

    import re as _re

    records: Dict[str, Dict[str, int]] = {}
    for row in _load_schedule():
        result = str(row.get("result", "")).strip()
        m = _re.match(r"^(\d+)\s*-\s*(\d+)$", result)
        if not m:
            continue
        home = str(row.get("home", "")).strip()
        away = str(row.get("away", "")).strip()
        if not home or not away:
            continue
        home_runs, away_runs = int(m.group(1)), int(m.group(2))
        for tid in (home, away):
            records.setdefault(
                tid, {"wins": 0, "losses": 0, "runs_for": 0, "runs_against": 0}
            )
        records[home]["runs_for"] += home_runs
        records[home]["runs_against"] += away_runs
        records[away]["runs_for"] += away_runs
        records[away]["runs_against"] += home_runs
        if home_runs > away_runs:
            records[home]["wins"] += 1
            records[away]["losses"] += 1
        elif away_runs > home_runs:
            records[away]["wins"] += 1
            records[home]["losses"] += 1
        # exact tie: no decision recorded
    return records


def _sync_standings_from_stats() -> bool:
    """Rebuild standings.json from the authoritative schedule results.

    Shared by the post-sim persistence path and the playoff-bracket pre-check
    (the bracket seeds from standings, so they must be fresh before we build
    it). Derives from ``schedule.csv`` (idempotent, drift-proof — see
    ``_team_records_from_schedule``) rather than the ``season_stats`` team
    rollup. Falls back to the season_stats team block only when the schedule has
    no decided games yet (e.g. a freshly seeded league). Best-effort: returns
    True when standings were written.
    """

    try:
        from services.standings_repository import save_standings

        records = _team_records_from_schedule()
        if records:
            save_standings(records, base_path=get_data_dir())
            return True

        # Fallback: no decided games in the schedule yet — pull whatever the
        # season_stats team block has so a freshly-seeded league still renders.
        from utils.stats_persistence import load_stats

        stats_path = get_data_dir() / "season_stats.json"
        season_stats = load_stats(stats_path) if stats_path.exists() else {}
        teams_block = (season_stats or {}).get("teams") or {}
        if not teams_block:
            return False
        standings: Dict[str, Dict[str, Any]] = {}
        for team_id, raw in teams_block.items():
            if not isinstance(raw, dict):
                continue
            standings[str(team_id)] = {
                "wins": int(raw.get("w", 0) or 0),
                "losses": int(raw.get("l", 0) or 0),
                "runs_for": int(raw.get("r", 0) or 0),
                "runs_against": int(raw.get("ra", 0) or 0),
            }
        save_standings(standings, base_path=get_data_dir())
        return True
    except Exception:
        return False


def _playoffs_champion_recorded() -> bool:
    """True when the persisted playoff bracket has a champion set."""

    try:
        from playbalance import playoffs as _pf

        bracket = _pf.load_bracket()
    except Exception:
        return False
    if bracket is None:
        return False
    champion = getattr(bracket, "champion", None)
    return bool(str(champion or "").strip())


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
