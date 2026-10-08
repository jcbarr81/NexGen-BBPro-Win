"""Parallel simulation of one schedule day via side-effect journals (S1-10).

Workers simulate games with ALL persistence intercepted and captured into a
JSON-serializable *journal*; the parent replays the journals in serial game
order inside the existing ``batched_stats_writes()`` / tracker
``deferred_saves()`` contexts, so the final on-disk state is byte-identical to a
serial day.

Design invariants (see docs/specs/S1-10_parallel_day.md):

* **Opt-in.** Activated only when ``PB_PARALLEL_GAMES`` resolves to >= 2 workers;
  unset / ``"0"`` / ``"1"`` runs the untouched serial path. The default is
  serial so a Cloud Run 1-vCPU deploy is zero-risk.
* **Lazy pool.** The process pool is created on first parallel day, so any env a
  caller sets in-process (e.g. ``PB_SKIP_BOXSCORE_HTML``) must be set BEFORE the
  first parallel ``simulate_next_day``.
* **No import cycle.** ``game_runner`` imports :func:`active_journal` from this
  module at its top level; therefore this module imports ``game_runner`` (and
  other heavy modules) ONLY inside function bodies.
* **Spawn only.** ``multiprocessing.get_context("spawn")`` on all platforms; the
  only things submitted to the pool are :func:`simulate_game_job` and a plain
  JSON-safe dict (no closures / lambdas ever cross the boundary).
"""
from __future__ import annotations

import atexit
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

JOURNAL_SCHEMA = 1
MAX_JOURNAL_BYTES = 32 * 1024 * 1024


# ---------------------------------------------------------------------------
# Worker-side capture target + interception flag
# ---------------------------------------------------------------------------
@dataclass
class GameJournal:
    """Side-effect capture target. Exists only inside the worker process.

    ``game_runner`` writes into the active journal (via :func:`active_journal`)
    instead of touching disk / global state whenever one is active.
    """

    usage_in: Optional[Dict[str, Any]] = None  # set from payload before the game
    stats_players: Dict[str, dict] = field(default_factory=dict)
    stats_teams: Dict[str, dict] = field(default_factory=dict)
    injury_events: List[dict] = field(default_factory=list)
    lines: Dict[str, dict] = field(default_factory=dict)  # batting_lines / pitcher_lines
    pitcher_roles: Dict[str, str] = field(default_factory=dict)  # pid -> in-game role
    usage_out: Optional[Dict[str, Any]] = None
    bullpen_status_logs: List[str] = field(default_factory=list)
    decision_logs: List[dict] = field(default_factory=list)
    # News items written while the game's state was prepared (the owner's
    # "auto-fill rebuilt your lineup" notice); the parent logs them in game
    # order, so the feed reads exactly as a serial day.
    news_events: List[dict] = field(default_factory=list)


_ACTIVE_JOURNAL: Optional[GameJournal] = None


def active_journal() -> Optional[GameJournal]:
    """Return the journal being captured on this thread/process, or ``None``.

    ``None`` (the parent's steady state and any non-parallel run) means "write
    side effects directly", so the serial path is completely unaffected.
    """

    return _ACTIVE_JOURNAL


@contextmanager
def journal_capture(journal: GameJournal):
    global _ACTIVE_JOURNAL
    prev, _ACTIVE_JOURNAL = _ACTIVE_JOURNAL, journal
    try:
        yield journal
    finally:
        _ACTIVE_JOURNAL = prev


# ---------------------------------------------------------------------------
# Worker-count resolution (D1)
# ---------------------------------------------------------------------------
def resolve_worker_count(num_games: int) -> int:
    """Resolve ``PB_PARALLEL_GAMES`` to a worker count. ``0`` means run serially.

    * unset / ``"0"`` / ``"1"`` / falsey tokens -> 0 (serial, the default).
    * ``"auto"`` -> ``min(os.cpu_count() - 1, num_games)``.
    * integer N -> ``min(N, num_games)``.
    * anything that resolves < 2 -> 0 (serial).
    """

    if num_games < 2:
        return 0
    raw = os.getenv("PB_PARALLEL_GAMES")
    if raw is None:
        return 0
    token = str(raw).strip().lower()
    if token in ("", "0", "1", "off", "no", "false", "serial"):
        return 0
    if token == "auto":
        workers = (os.cpu_count() or 1) - 1
    else:
        try:
            workers = int(token)
        except ValueError:
            return 0
    workers = min(workers, num_games)
    return workers if workers >= 2 else 0


# ---------------------------------------------------------------------------
# Pool lifecycle (D4/D5) — module-level singleton, spawn context, atexit
# ---------------------------------------------------------------------------
_POOL: Optional[ProcessPoolExecutor] = None
_POOL_WORKERS: int = 0


def get_pool(workers: int) -> ProcessPoolExecutor:
    """Return the shared spawn pool, (re)creating it when the size changes."""

    global _POOL, _POOL_WORKERS
    if _POOL is not None and _POOL_WORKERS == workers:
        return _POOL
    if _POOL is not None:
        _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None
        _POOL_WORKERS = 0
    # Spawned children inherit os.environ; pin the hash seed so tuple/str hashing
    # (bullpen tie-break ordering) matches the parent (§5). setdefault so a
    # caller that already pinned it wins.
    os.environ.setdefault("PYTHONHASHSEED", "0")
    _POOL = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
    )
    _POOL_WORKERS = workers
    return _POOL


def shutdown_pool() -> None:
    global _POOL, _POOL_WORKERS
    if _POOL is not None:
        _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None
        _POOL_WORKERS = 0


atexit.register(shutdown_pool)


# ---------------------------------------------------------------------------
# UsageState (fatigue) serialization helpers (D7) — used by BOTH the worker
# (game_runner hook) and the parent (season_simulator merge).
# ---------------------------------------------------------------------------
def usage_state_to_payload(
    state: Any, game_day: Optional[int], *, pids: Optional[set] = None
) -> Dict[str, Any]:
    """Serialize a physics ``UsageState`` to a JSON-safe dict.

    Workload dataclasses are serialized field-generically (see
    ``physics_sim.usage.usage_state_to_dict``) so this stays correct as fields
    are added. When *pids* is given, only those players
    are included (per-game roster filtering keeps payloads small).
    """

    from physics_sim.usage import usage_state_to_dict

    return {"game_day": game_day, **usage_state_to_dict(state, pids=pids)}


def usage_payload_to_state(payload: Optional[Dict[str, Any]]) -> Any:
    """Build a fresh ``UsageState`` from a usage_in payload dict."""

    from physics_sim.usage import usage_state_from_dict

    return usage_state_from_dict(payload)


def diff_usage_out(
    usage_in: Optional[Dict[str, Any]], usage_out: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Reduce a full post-game usage snapshot to only the workloads the engine
    changed vs the pre-game snapshot.

    The engine touches exactly this game's participants (roster members passed
    to it), so "changed vs usage_in" is precisely the set the parent must merge
    — no roster-list guessing, and it can never revert another game's players.
    """

    if not usage_out:
        return usage_out
    in_w = (usage_in or {}).get("workloads") or {}
    in_b = (usage_in or {}).get("batter_workloads") or {}
    out_w = usage_out.get("workloads") or {}
    out_b = usage_out.get("batter_workloads") or {}
    return {
        "game_day": usage_out.get("game_day"),
        "current_day": usage_out.get("current_day"),
        "game_index": usage_out.get("game_index"),
        "workloads": {pid: v for pid, v in out_w.items() if in_w.get(pid) != v},
        "batter_workloads": {pid: v for pid, v in out_b.items() if in_b.get(pid) != v},
    }


def merge_usage_into_state(state: Any, usage_out: Optional[Dict[str, Any]]) -> None:
    """Overwrite the parent shared state's per-player workloads from a journal.

    Per-game player sets are disjoint within a day, so overwrites never collide.
    ``current_day`` and ``game_index`` are advanced to the max seen: every
    worker starts from the same pre-day snapshot and advances it once, so the
    max is exactly what one serial pass over the day produces.
    """

    if not usage_out:
        return
    from physics_sim.usage import BatterWorkload, PitcherWorkload, _workload_from_dict

    for pid, data in (usage_out.get("workloads") or {}).items():
        state.workloads[pid] = _workload_from_dict(PitcherWorkload, data)
    for pid, data in (usage_out.get("batter_workloads") or {}).items():
        state.batter_workloads[pid] = _workload_from_dict(BatterWorkload, data)
    current_day = usage_out.get("current_day")
    if current_day is not None:
        if state.current_day is None or current_day > state.current_day:
            state.current_day = current_day
    game_index = usage_out.get("game_index")
    if game_index is not None and int(game_index) > state.game_index:
        state.game_index = int(game_index)


# ---------------------------------------------------------------------------
# Payload construction (parent -> worker)
# ---------------------------------------------------------------------------
def build_payload(
    *,
    home: str,
    away: str,
    seed: int,
    date: str,
    home_starter: Optional[str],
    away_starter: Optional[str],
    data_root: str,
    league_id: Optional[str],
    usage_in: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble the JSON-safe payload dict submitted to :func:`simulate_game_job`."""

    return {
        "schema": JOURNAL_SCHEMA,
        "home": home,
        "away": away,
        "seed": seed,
        "date": date,
        "home_starter": home_starter,
        "away_starter": away_starter,
        "data_root": data_root,
        "league_id": league_id,
        "usage_in": usage_in,
    }


# ---------------------------------------------------------------------------
# THE pool entry point (worker process)
# ---------------------------------------------------------------------------
def simulate_game_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate one game in a worker process and return its side-effect journal.

    Writes NOTHING that the parent will later replay: all persistence is captured
    into the journal via the active-journal interception in ``game_runner``. The
    one exception is the deterministic lineup-salvage CSV (D11), which is a pure
    function of the roster and is written directly.
    """

    from utils.path_utils import reset_request_league, set_request_league

    os.environ["NEXGEN_DATA_ROOT"] = payload["data_root"]
    league_token = None
    league_id = payload.get("league_id")
    if league_id:
        league_token = set_request_league(league_id)
    try:
        from playbalance import game_runner
        from utils.pitcher_recovery import PitcherRecoveryTracker
        from utils.player_loader import load_players_from_csv
        from utils.roster_loader import load_roster

        # D9: this process's singletons may be stale from an earlier job on the
        # persistent pool. Reset the tracker, the Team lru_cache (which
        # hydrates season_stats at load) and the roster cache. Rosters are NOT
        # mtime-keyed: the unified data service keeps whatever this process
        # loaded first, so after the parent replayed an injury (IL placement,
        # call-up) a worker that had simmed the club before still dressed the
        # injured arm and left the call-up out. players.csv is cached the same
        # way (by path only), so it is dropped too.
        PitcherRecoveryTracker._instance = None
        tracker = PitcherRecoveryTracker.instance()
        tracker._current_date = payload["date"]  # enable the S1-02 per-day memo
        game_runner._teams_by_id.cache_clear()
        load_roster.cache_clear()
        load_players_from_csv.cache_clear()

        if game_runner._resolve_game_engine(None) != "physics":
            raise RuntimeError("parallel_day requires the physics engine (D2)")

        journal = GameJournal(usage_in=payload["usage_in"])
        with tracker.suppressed_saves(), journal_capture(journal):
            home_runs, away_runs, html, meta = game_runner.simulate_game_scores(
                payload["home"],
                payload["away"],
                seed=payload["seed"],
                game_date=payload["date"],
                home_starter=payload["home_starter"],
                away_starter=payload["away_starter"],
            )

        journal_dict = {
            "schema": JOURNAL_SCHEMA,
            "home": payload["home"],
            "away": payload["away"],
            "date": payload["date"],
            "seed": payload["seed"],
            "result": {"home_runs": home_runs, "away_runs": away_runs},
            "boxscore_html": html,
            "meta": _json_safe(meta),
            "stats": {"players": journal.stats_players, "teams": journal.stats_teams},
            "injury_events": journal.injury_events,
            "lines": journal.lines,
            "pitcher_roles": journal.pitcher_roles,
            # Filter the full post-game usage snapshot down to only the players
            # this game changed, so the parent merge touches exactly the game's
            # participants (never reverts or misses a player).
            "usage": diff_usage_out(payload["usage_in"], journal.usage_out),
            "bullpen_status_logs": journal.bullpen_status_logs,
            "decision_logs": journal.decision_logs,
            "news_events": journal.news_events,
        }

        # D13: the dumps doubles as a JSON-serializability invariant and a size
        # guard; on failure the parent's future.result() raises -> serial
        # fallback for this game.
        blob = json.dumps(journal_dict)
        if len(blob.encode("utf-8")) > MAX_JOURNAL_BYTES:
            raise RuntimeError("journal exceeds MAX_JOURNAL_BYTES")
        return journal_dict
    finally:
        if league_token is not None:
            reset_request_league(league_token)


def _json_safe(mapping: Any) -> Any:
    """Drop any non-JSON-serializable keys from a metadata dict (defensive)."""

    if not isinstance(mapping, dict):
        return mapping
    safe: Dict[str, Any] = {}
    for key, value in mapping.items():
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue
        safe[key] = value
    return safe
