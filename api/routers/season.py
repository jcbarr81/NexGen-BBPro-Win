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

        played_set = {str(d) for d in played_dates}
        for game in simulator.schedule:
            if str(game.get("date", "")) in played_set:
                # `_apply_result_to_game` already set ``result``; mark
                # the row played so subsequent requests skip it.
                if str(game.get("result", "")).strip():
                    game["played"] = "1"
                # The simulator stores the boxscore path under
                # ``boxscore_html``; ``save_schedule`` writes the
                # ``boxscore`` column. Copy across so the schedule page
                # row links to the right HTML file.
                if game.get("boxscore_html") and not game.get("boxscore"):
                    game["boxscore"] = game["boxscore_html"]
        save_schedule(simulator.schedule, _schedule_path())
    except Exception:
        pass

    # 2. Sync standings.json from season_stats teams rollup.
    try:
        from services.standings_repository import save_standings
        from utils.stats_persistence import load_stats

        stats_path = get_data_dir() / "season_stats.json"
        season_stats = load_stats(stats_path) if stats_path.exists() else {}
        teams_block = (season_stats or {}).get("teams") or {}
        if teams_block:
            standings: Dict[str, Dict[str, Any]] = {}
            for team_id, raw in teams_block.items():
                if not isinstance(raw, dict):
                    continue
                wins = int(raw.get("w", 0) or 0)
                losses = int(raw.get("l", 0) or 0)
                runs_for = int(raw.get("r", 0) or 0)
                runs_against = int(raw.get("ra", 0) or 0)
                standings[str(team_id)] = {
                    "wins": wins,
                    "losses": losses,
                    "runs_for": runs_for,
                    "runs_against": runs_against,
                }
            save_standings(standings, base_path=get_data_dir())
    except Exception:
        pass

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

    return summary


# ---------------------------------------------------------------------------
# Endpoints


@router.get("/state")
def season_state() -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    return _state_payload(manager, simulator, draft_date)


def _team_id_from_identity(identity: Dict[str, Any]) -> Optional[str]:
    raw = str(identity.get("t") or "").strip()
    return raw or None


@router.post("/simulate/day")
def simulate_day(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(
        manager,
        simulator,
        1,
        draft_date=draft_date,
        team_id=_team_id_from_identity(identity),
    )
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/days")
def simulate_days(
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    try:
        n = int(payload.get("n", 1))
    except (TypeError, ValueError):
        n = 1
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(
        manager,
        simulator,
        n,
        draft_date=draft_date,
        team_id=_team_id_from_identity(identity),
    )
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/week")
def simulate_week(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(
        manager,
        simulator,
        7,
        draft_date=draft_date,
        team_id=_team_id_from_identity(identity),
    )
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/month")
def simulate_month(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    result = _simulate_n(
        manager,
        simulator,
        30,
        draft_date=draft_date,
        team_id=_team_id_from_identity(identity),
    )
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/to-draft")
def simulate_to_draft(
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
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
    result = _simulate_n(
        manager,
        simulator,
        n_days,
        draft_date=draft_date,
        team_id=_team_id_from_identity(identity),
    )
    return _state_payload(manager, simulator, draft_date, extra=result)


@router.post("/simulate/to-playoffs")
def simulate_to_playoffs(
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    manager, simulator, draft_date = _build_manager_and_simulator()
    n_days = max(0, len(simulator.dates) - simulator._index)
    result = _simulate_n(
        manager,
        simulator,
        n_days,
        draft_date=draft_date,
        team_id=_team_id_from_identity(identity),
    )
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

    # Guard: require the calendar to actually reach the draft date (or
    # the end of the schedule when no draft date is configured) before
    # leaving REGULAR_SEASON. Without this, clicking Advance Phase with
    # zero games played races REGULAR_SEASON → AMATEUR_DRAFT → PLAYOFFS
    # → OFFSEASON on an unplayed season.
    if (
        manager.phase == SeasonPhase.REGULAR_SEASON
        and len(simulator.dates) > 0
        and not force
    ):
        if draft_date:
            try:
                stop_idx = simulator.dates.index(draft_date)
            except ValueError:
                stop_idx = len(simulator.dates)
        else:
            stop_idx = len(simulator.dates)
        if simulator._index < stop_idx:
            remaining = stop_idx - simulator._index
            use_button = "To Draft" if draft_date else "To Playoffs"
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


@router.post("/preseason/list-unsigned")
def preseason_list_unsigned(
    payload: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    """List unsigned players and optionally run a CPU free-agency cycle.

    Ports ``ui/season_progress_window._show_free_agents``. Marks the
    ``preseason_done.free_agency`` flag so the UI can show it as done.
    """

    run_cpu = bool(payload.get("run_cpu", True))

    cpu_summary: Dict[str, Any] = {
        "applied": False,
        "signed_players": 0,
        "rounds_run": 0,
    }
    if run_cpu:
        try:
            from services.free_agency import run_cpu_free_agency_market

            cpu_summary = run_cpu_free_agency_market(data_dir=get_data_dir())
        except Exception as exc:  # pragma: no cover - defensive
            cpu_summary = {
                "applied": False,
                "signed_players": 0,
                "rounds_run": 0,
                "error": str(exc),
            }

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
        "cpu_signed": int(cpu_summary.get("signed_players", 0) or 0),
        "cpu_rounds": int(cpu_summary.get("rounds_run", 0) or 0),
        "cpu_applied": bool(cpu_summary.get("applied", False)),
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
