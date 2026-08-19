# S1-10 — Parallel Day Simulation (Side-Effect Journal)

**Status:** implementation-ready spec (verified against working tree @ 62f166edf, 2026-07-15)
**Architecture (fixed, do not revisit):** workers simulate games with ALL persistence
intercepted and returned as a data journal; the parent replays journals in serial game
order inside the existing `batched_stats_writes()` / `tracker.deferred_saves()` contexts.

Every file:line below was verified against current code. Line numbers shift after the
first edit — anchor on the quoted symbols, not raw numbers.

---

## 0. Decisions made in this spec (with rationale)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Opt-in** via `PB_PARALLEL_GAMES` env; unset/`"0"` = serial (today's behavior). `"auto"` = `min(os.cpu_count()-1, len(games))`; integer N = `min(N, len(games))`; resolved < 2 → serial | Cloud Run default is 1 vCPU; write surface is wide; first release must be zero-risk when the env is absent |
| D2 | Parallel path activates only when `simulate_game` is `SeasonSimulator._default_simulate_game` **or** `playbalance.game_runner.simulate_game_scores`, AND `_resolve_game_engine(None) == "physics"`, AND ≥2 games | Custom callables (tests, scripts) and the legacy engine have unaudited write paths; the two known callables cover benchmark + API production (api/routers/season.py:391-396) |
| D3 | Single new module `playbalance/parallel_day.py`; `game_runner` imports it at module top (`from playbalance.parallel_day import active_journal`); `parallel_day` imports `game_runner` **only inside function bodies** | Avoids the import cycle; keeps one spawn-importable module as required |
| D4 | Pool is a **module-level singleton** in `parallel_day` (`_POOL`), lazily created, `atexit` shutdown — NOT a `SeasonSimulator` attribute | The API rebuilds `SeasonSimulator` per HTTP request (`_build_manager_and_simulator`, season.py:363); a per-instance pool would respawn workers every request |
| D5 | `multiprocessing.get_context("spawn")` on all platforms | Windows is spawn anyway; fork on Linux would duplicate live FastAPI caches/locks and diverge from the tested behavior |
| D6 | Per-day seeds move from module-global `random` to a private `self._seed_rng` created on first `simulate_next_day()` call | `physics_sim.engine.simulate_game` reseeds **global** random per game (engine.py:3194-3195, `rng = random.Random(seed)` / `random.seed(seed)`); in serial that trashed state feeds next-day `random.randrange` at season_simulator.py:204 — parallel never runs engine in-parent, so day-2+ seeds would diverge. A decoupled generator makes serial ≡ parallel by construction (§5) |
| D7 | Physics `UsageState` (in-memory only, never persisted) rides the payload in and the journal out, per game | Worker processes have empty/stale fatigue state; fatigue affects outcomes → parity breaks without it (§2 row 9) |
| D8 | Payload carries `data_root` + `league_id`; worker sets `NEXGEN_DATA_ROOT` env and `set_request_league()` | Cloud multi-tenant league binding is a ContextVar from the `X-League-Id` header (utils/path_utils.py:24, 289-294) — it does NOT cross process boundaries; without this a cloud sim writes the wrong league |
| D9 | Worker resets per-process stale singletons per job: fresh `PitcherRecoveryTracker`, `game_runner._teams_by_id.cache_clear()` | Tracker singleton and the `lru_cache` of Team objects (game_runner.py:111-115, hydrates `season_stats` at load) are NOT mtime-keyed; a persistent pool reuses processes across days. Players/rosters are safe (mtime-keyed unified data service; `_apply_dynamic_player_data` re-hydrates on stats-file token change, player_loader.py:133-192) |
| D10 | Parent replays `tracker.bullpen_game_status(team, date, …)` for both teams of each game | That call normalizes stored pitcher budgets in memory (`_ensure_budget_initialized`, pitcher_recovery.py:665, 699-710) and those normalizations land in the day-end flush; skipping it makes `pitcher_recovery.json` diverge byte-wise |
| D11 | `_sanitize_lineup` salvage writes (lineups/{team}_vs_*.csv via lineup_autofill.py:190-194) are **allowed directly from the worker** — not journaled | Content is a deterministic pure function of roster (local `random.Random(f"{team_id}-lineup-fallback")`, lineup_autofill.py:169); teams are disjoint within a day; write is idempotent |
| D12 | Worker failure (any exception from the future) → parent re-runs that game **serially in-parent at its replay position**, with the pre-assigned starters, side effects direct | Replay order = serial order, so parent state at that point equals the serial baseline; correctness beats speed on the degraded path |
| D13 | Journal soft cap 32 MB: worker runs `json.dumps(journal)`; if it fails or exceeds the cap it raises → D12 fallback | The dumps doubles as a JSON-serializability invariant; only `boxscore_html` is unbounded and `PB_SKIP_BOXSCORE_HTML` bounds it |

---

## 1. Write-path audit — `run_single_game` / `_run_physics_game` call tree

Audit method: full read of `playbalance/game_runner.py`, `playbalance/season_simulator.py`,
`utils/stats_persistence.py`, `utils/pitcher_recovery.py`, `services/special_events.py`,
`utils/news_logger.py`, `services/injury_history.py`, `services/decision_explanations.py`,
`physics_sim/usage.py`, plus greps for `open(..."w"/"a")|write_text|json.dump|save_` over
`physics_sim/` (no hits — engine is pure), `services/injury_manager.py` (no writes;
`place_on_injury_list` mutates the roster object only), `utils/lineup_loader.py` (read-only),
and the tuning getters (`get_physics_tuning_overrides` / `get_injury_tuning_overrides` are
read-only; the `write_text` hits in those modules are in setter functions not on this path).

| # | Side effect | Fires at (current code) | Worker intercept | Parent replay |
|---|---|---|---|---|
| 1 | `season_stats.json` write (+ daily shard `season_history/<date>.json`, + `prime_stats_cache`) | `_persist_physics_stats` → `save_stats(updated_players.values(), teams)` game_runner.py:990; write machinery stats_persistence.py:420-501 | Journal captures cumulative post-game mappings: `stats.players[pid] = dict(player.season_stats)`, `stats.teams[tid] = dict(team.season_stats)`; skip `save_stats` | `save_stats([SimpleNamespace(player_id, season_stats)…], [SimpleNamespace(team_id, season_stats)…])` — the active day batch (stats_persistence.py:105-146, 391-417) absorbs it exactly as serial. ALSO copy each team mapping onto the parent's cached `Team` objects (`_teams_by_id(teams_path)[tid].season_stats = mapping`) so the in-memory cache mirrors serial mutation |
| 2 | `tracker.assign_starter` (rotation `next_index` advance + `_assignments` + dirty flag) | run_single_game:1257-1273 | Never runs in worker — parent passes both starters, so run_single_game takes the `tracker.ensure_team` branch (1265, 1273); worker tracker saves suppressed (row 6) | Parent pre-assigns for all games **before dispatch**, in `games` order, home then away (§4.1) |
| 3 | `tracker.bullpen_game_status` in-memory budget normalization (persisted at day-end flush) | `_apply_bullpen_usage_order` → tracker call, game_runner.py:263; normalization pitcher_recovery.py:643-711 | Runs in worker on its throwaway tracker copy (the status map is needed for bullpen ordering); worker saves suppressed | Parent calls `tracker.bullpen_game_status(home_id, date, players_file, roster_dir)` then same for away, discarding the result (D10) |
| 4 | `tracker.record_game` (physics) | game_runner.py:1219-1232 | Skipped under journal; inputs already captured (row 8's `pitcher_lines`) | Parent rebuilds `SimpleNamespace(player=players_lookup[pid], pitches_thrown=pitches, simulated_pitches=0)` lists from `lines.pitcher_lines` (mirror of `_states_from_lines`, game_runner.py:1200-1213) and calls `record_game(home…)`, `record_game(away…)` |
| 5 | `tracker.record_warmups` / `apply_penalties` | game_runner.py:1430-1463 — **legacy engine branch only** | Unreachable (D2 physics-only gate) | n/a |
| 6 | `pitcher_recovery.json` writes (`tracker.save`, pitcher_recovery.py:351-381 via `_mark_dirty`:182-187) | Any tracker mutation | New `PitcherRecoveryTracker.suppressed_saves()` context held for the whole worker job (§3.4) | Parent's existing `deferred_saves()` flushes once at day end (season_simulator.py:231) |
| 7 | `_apply_injury_events`: `save_players` (game_runner.py:1581), `save_roster` (1583-1584), `load_roster.cache_clear` (1585-1588), `log_news_event` (1559 → appends `news_feed.txt`, news_logger.py:39-66), `record_injury_event` (1564 → writes `injury_reports/<season>.json`, injury_history.py:40-84) | Call site game_runner.py:1171-1176 (events normalized with `team_id` at 1156-1170) | Intercept at the **call site**: `journal.injury_events = injury_events`; skip the call | Parent calls `_apply_injury_events(events, players_file=…, roster_dir=…, game_date=date)` verbatim, per game in order |
| 8 | `record_game_special_events`: writes `special_events.json` (special_events.py:110-135) + news feed lines (401-409) | Call site game_runner.py:1186-1197 | Intercept at call site: `journal.lines = {"batting_lines": metadata.get("batting_lines") or {}, "pitcher_lines": metadata.get("pitcher_lines") or {}}`; skip | Parent calls `record_game_special_events(metadata=journal["lines"], home_id=…, away_id=…, players_lookup=<parent day lookup>, game_date=date)` — the function reads only those two keys (special_events.py:199-201) |
| 9 | Physics usage state: module globals game_runner.py:47-51 + `_physics_usage_context` 54-86; mutated by engine `advance_day` (engine.py:3290-3327) and `record_outing`/`record_batter_game` (engine.py:5240-5273) — **in-memory only, never persisted, affects outcomes** | `usage_state, game_day = _physics_usage_context(date_token)` game_runner.py:1079 | Worker builds a private `UsageState` from `payload["usage_in"]` and bypasses `_physics_usage_context`; after the game, `journal.usage_out` = full serialized state | Parent gets `state, _ = _physics_usage_context(date)` and overwrites `state.workloads[pid]` / `state.batter_workloads[pid]` from `usage_out` (per-game player sets are disjoint within a day) |
| 10 | Boxscore HTML (pure render; `PB_SKIP_BOXSCORE_HTML` short-circuit simulation.py:4039-4040) | game_runner.py:1138-1142 | No intercept — rendered in worker, returned as `journal.boxscore_html` | `_apply_result_to_game` puts it on the game row; the API's `after_game`/persist step pops it to disk (season.py:771-782) — unchanged |
| 11 | `_log_bullpen_status` append to `data/tmp/bullpen_status.log` (env `PB_LOG_BULLPEN_STATUS`) | game_runner.py:207-246 (write 241-246) | Function builds the text block; under journal append the text to `journal.bullpen_status_logs` instead of writing | Parent appends each captured block to the same file during replay |
| 12 | `append_decision_log` → `decision_explanations.jsonl` (env `NEXGEN_DECISION_LOG`, decision_explanations.py:113-139) | game_runner.py:350-351 | Under journal: `journal.decision_logs.append(decision.to_dict())` | Parent calls `append_decision_log(entry)` per captured dict |
| 13 | Lineup salvage write `lineups/{team}_vs_*.csv` + `load_roster.cache_clear` | `_sanitize_lineup` game_runner.py:510-534 → lineup_autofill.py:181-194 | **Not intercepted** — direct worker write (D11) | none |
| 14 | Legacy writers: `save_stats` inside `GameSimulation.simulate_game` (simulation.py:1347), legacy tracker calls (row 5) | Legacy branch only | Unreachable (D2) | n/a |

Nothing else in the tree opens a file for writing or mutates cross-game module state.
(`load_players_by_id`, `serialize_game_result`, `load_tuning`, `load_park` are pure reads;
`SPECIAL_EVENTS_PATH` module constant is computed at import, harmless.)

---

## 2. Worker protocol — `playbalance/parallel_day.py`

New module. Top-level (spawn-picklable) functions only; **no lambdas/closures ever
submitted to the pool**. No top-level import of `game_runner` (D3).

```python
"""Parallel simulation of one schedule day via side-effect journals (S1-10)."""
from __future__ import annotations

import atexit, json, multiprocessing, os
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

JOURNAL_SCHEMA = 1
MAX_JOURNAL_BYTES = 32 * 1024 * 1024

@dataclass
class GameJournal:
    """Worker-side capture target. Exists only inside the worker process."""
    usage_in: Optional[Dict[str, Any]] = None      # set from payload before the game
    stats_players: Dict[str, dict] = field(default_factory=dict)
    stats_teams: Dict[str, dict] = field(default_factory=dict)
    injury_events: List[dict] = field(default_factory=list)
    lines: Dict[str, dict] = field(default_factory=dict)     # batting_lines / pitcher_lines
    usage_out: Optional[Dict[str, Any]] = None
    bullpen_status_logs: List[str] = field(default_factory=list)
    decision_logs: List[dict] = field(default_factory=list)

_ACTIVE_JOURNAL: Optional[GameJournal] = None

def active_journal() -> Optional[GameJournal]:
    return _ACTIVE_JOURNAL

@contextmanager
def journal_capture(journal: GameJournal):
    global _ACTIVE_JOURNAL
    prev, _ACTIVE_JOURNAL = _ACTIVE_JOURNAL, journal
    try:
        yield journal
    finally:
        _ACTIVE_JOURNAL = prev

def resolve_worker_count(num_games: int) -> int: ...   # D1 semantics; returns 0 for serial
def get_pool(workers: int) -> ProcessPoolExecutor: ...  # singleton, spawn ctx, recreate on size change / BrokenProcessPool
def shutdown_pool() -> None: ...                        # registered with atexit

def build_payload(*, home: str, away: str, seed: int, date: str,
                  home_starter: str | None, away_starter: str | None,
                  usage_in: Dict[str, Any]) -> Dict[str, Any]: ...

def simulate_game_job(payload: Dict[str, Any]) -> Dict[str, Any]: ...  # THE pool entry point
```

Interception flag: **module-level global** (`_ACTIVE_JOURNAL`), not a contextvar — workers
are single-threaded per job, the flag is process-local by construction, and a plain global
is checkable from `game_runner` with zero overhead. (A contextvar buys nothing here and
costs a lookup per check.)

### 2.1 Payload schema (parent → worker; JSON-safe dict, pickled by the pool)

| Key | Type | Source |
|---|---|---|
| `schema` | `1` | constant |
| `home`, `away` | str | game row |
| `seed` | int | pre-generated per game (§4) |
| `date` | str `YYYY-MM-DD` | `current_date` |
| `home_starter`, `away_starter` | str \| None | pre-assignment loop (§4.1) |
| `data_root` | str | `str(utils.path_utils.get_data_root())` |
| `league_id` | str \| None | `utils.path_utils.get_active_league_id()` (captures the request ContextVar league — D8) |
| `usage_in` | dict | `{"game_day": int, "current_day": int\|None, "workloads": {pid: workload-dict}, "batter_workloads": {pid: workload-dict}}` — parent calls `game_runner._physics_usage_context(date)` once for the day, then filters both dicts to `set(load_roster(home).act) | set(load_roster(away).act)` |

Workload dicts are the dataclass fields verbatim (`physics_sim/usage.py:10-24`):
`PitcherWorkload` → `{fatigue_debt, last_used_day, consecutive_days_used, last_update_day, appearances}`;
`BatterWorkload` → same minus `appearances`.

`TeamState` objects NEVER cross the boundary. The worker runs the game and extracts what
`simulate_game_scores` already extracts (game_runner.py:1629-1639): `home_state.runs`,
`away_state.runs`, `html`, `meta`. That is exactly what `_apply_result_to_game`
(season_simulator.py:206-220) consumes as the 4-tuple `(home_runs, away_runs, boxscore_html, meta)`.

### 2.2 Journal schema (worker → parent; JSON-serializable dict)

```json
{
  "schema": 1,
  "home": "TOR", "away": "BOS", "date": "2026-05-01", "seed": 123456,
  "result": {"home_runs": 4, "away_runs": 2},
  "boxscore_html": "<html…>  ('' when PB_SKIP_BOXSCORE_HTML)",
  "meta": { "home_innings": 9, "away_innings": 9, "extra_innings": false,
            "home_starter_hand": "R", "away_starter_hand": "L",
            "engine": "physics", "bullpen_usage_reasons": {"home": {...}} },
  "stats": {"players": {"P100": {…cumulative season_stats…}}, "teams": {"TOR": {…}, "BOS": {…}}},
  "injury_events": [ {"team_id": "BOS", "player_id": "P212", "days": 15, "dl_tier": "dl15", "description": "…", "trigger": "…", "severity": "…"} ],
  "lines": {"batting_lines": {"home": […], "away": […]}, "pitcher_lines": {"home": […], "away": […]}},
  "usage": {"game_day": 3, "current_day": 3, "workloads": {"P100": {…}}, "batter_workloads": {"P055": {…}}},
  "bullpen_status_logs": ["2026-05-01 team=TOR\n  P17 role=SU …"],
  "decision_logs": [ {"decision_type": "bullpen_usage_order", …} ]
}
```

`meta` from the physics branch (game_runner.py:1144-1154) is already JSON-safe. Defensive:
the journal builder `pop`s any non-JSON-safe key (`json.dumps` per-key try) before the D13
size check. The `box` dict (return element 3 of `run_single_game`) is **discarded**, matching
`simulate_game_scores` today — it contains live `Player` objects after `_hydrate_physics_boxscore`.

### 2.3 `simulate_game_job` body (exact steps)

1. `os.environ["NEXGEN_DATA_ROOT"] = payload["data_root"]`; if `payload["league_id"]`: `set_request_league(payload["league_id"])` (hold token; reset in `finally`).
2. Lazy imports: `from playbalance import game_runner`; `from utils.pitcher_recovery import PitcherRecoveryTracker`.
3. Stale-state reset (D9): `PitcherRecoveryTracker._instance = None`; `tracker = PitcherRecoveryTracker.instance()`; `tracker._current_date = payload["date"]` (enables the S1-02 `_ensured` memo for this job); `game_runner._teams_by_id.cache_clear()`.
4. Guard: `assert game_runner._resolve_game_engine(None) == "physics"` — raise `RuntimeError` otherwise.
5. `journal = GameJournal(usage_in=payload["usage_in"])`.
6. `with tracker.suppressed_saves(), journal_capture(journal):`
   `home_runs, away_runs, html, meta = game_runner.simulate_game_scores(payload["home"], payload["away"], seed=payload["seed"], game_date=payload["date"], home_starter=payload["home_starter"], away_starter=payload["away_starter"])`
   (default path kwargs — the worker's `get_data_dir()` resolves them, same as serial).
7. Assemble the journal dict (§2.2); `blob = json.dumps(journal_dict)`; if `len(blob) > MAX_JOURNAL_BYTES`: `raise RuntimeError("journal too large")` (→ parent serial fallback, D13). Return the dict (not the blob).
8. Any exception propagates — the parent's `future.result()` raises and triggers D12.

---

## 3. Interception mechanism — exact hook points in `game_runner.py`

Add at module top: `from playbalance.parallel_day import active_journal` (safe — `parallel_day`
has no top-level `game_runner` import, D3).

| Hook | Current anchor | New code shape |
|---|---|---|
| 3.1 stats | `_persist_physics_stats`, replace `save_stats(updated_players.values(), teams)` (game_runner.py:990) | `jr = active_journal()` → if `jr`: `jr.stats_players.update({pid: dict(p.season_stats) for pid, p in updated_players.items()}); jr.stats_teams.update({t.team_id: dict(t.season_stats) for t in teams})` else `save_stats(...)`. **Copies are mandatory** — the worker mutated shared cached objects in place |
| 3.2 injuries | `_run_physics_game`, the `_apply_injury_events(injury_events, …)` call (game_runner.py:1171-1176) | if `jr`: `jr.injury_events.extend(injury_events)` else call. Capture AFTER the `team_id` normalization loop (1156-1170) |
| 3.3 special events | the `record_game_special_events(...)` try-block (game_runner.py:1186-1197) | if `jr`: `jr.lines = {"batting_lines": metadata.get("batting_lines") or {}, "pitcher_lines": metadata.get("pitcher_lines") or {}}` else existing call. Set `jr.lines` unconditionally when journaling (tracker replay needs `pitcher_lines` even when no special event fires) — so hoist the lines capture ABOVE the try-block |
| 3.4 tracker record_game | the `if tracker and date_token:` block (game_runner.py:1199-1232) | prefix with `if jr is None and tracker and date_token:` — under journal the block is skipped entirely (lines already captured in 3.3) |
| 3.5 usage | `usage_state, game_day = _physics_usage_context(date_token)` (game_runner.py:1079) | `jr = active_journal()`; if `jr and jr.usage_in is not None`: build `UsageState(current_day=…, workloads={pid: PitcherWorkload(**d)}, batter_workloads={pid: BatterWorkload(**d)})` from `jr.usage_in`, `game_day = jr.usage_in["game_day"]`; else existing call. After `simulate_game` returns (post line 1109): if `jr`: `jr.usage_out = {"game_day": game_day, "current_day": usage_state.current_day, "workloads": {…dataclass→dict…}, "batter_workloads": {…}}` |
| 3.6 decision log | `if should_persist_decision_logs(): append_decision_log(decision)` (game_runner.py:350-351) | `if should_persist_decision_logs():` → if `jr`: `jr.decision_logs.append(decision.to_dict())` else `append_decision_log(decision)` |
| 3.7 bullpen log | `_log_bullpen_status` file write (game_runner.py:241-246) | build `text = header + "\n" + "\n".join(lines) + "\n"`; if `jr`: `jr.bullpen_status_logs.append(text)` else write as today |

Tracker save suppression — add to `utils/pitcher_recovery.py` (next to `deferred_saves`,
line 189):

```python
@contextmanager
def suppressed_saves(self):
    """Worker mode (S1-10): absorb all save() calls and DISCARD the dirty flag.

    The worker's tracker copy is throwaway; the parent replays the mutations."""
    prev = self._defer_saves
    self._defer_saves = True
    try:
        yield
    finally:
        self._defer_saves = prev
        self._dirty = False
```

---

## 4. Parent orchestration — `SeasonSimulator.simulate_next_day`

### 4.0 Starter plumbing (prerequisite)

- `simulate_game_scores` (game_runner.py:1591-1601): add kwargs `home_starter: str | None = None, away_starter: str | None = None`; forward both into the `run_single_game` call at 1629. (`run_single_game` already accepts them, 1243-1244.)
- `SeasonSimulator._default_simulate_game` (season_simulator.py:299-317): add the same two kwargs, forward to `simulate_game_scores`.
- Serial path is otherwise untouched — pre-assignment happens **only** in the parallel branch.

### 4.1 New parallel branch

Inside `simulate_next_day`, after `seeds = …` (see §5 for the seed change) and before the
`with batched_stats_writes(), self._tracker.deferred_saves():` block (season_simulator.py:231),
compute:

```python
from playbalance import parallel_day
workers = parallel_day.resolve_worker_count(len(games))
parallel = workers >= 2 and self._parallel_eligible()   # D2 gate; helper checks the two
                                                        # known callables + physics engine
```

Then, replacing the current serial `for game, seed in zip(games, seeds):` loop **only when
`parallel`** (the serial loop stays verbatim for the else-branch):

1. **Pre-assign starters** (before dispatch, inside the two `with` contexts so tracker
   dirty-writes stay deferred): for each `game` in `games` order:
   `h = self._tracker.assign_starter(game["home"], current_date, players_file, roster_dir)`,
   then the same for away. Paths = `get_data_dir()/"players.csv"`, `get_data_dir()/"rosters"`
   (identical to `simulate_game_scores` resolution, game_runner.py:1604-1627). This advances
   `next_index` per team exactly once, in the same per-team order as serial (each team plays
   ≤1 game/day, so cross-game interleaving is unobservable).
2. **Build payloads** (§2.1): one `_physics_usage_context(current_date)` call for the day
   (import from `playbalance.game_runner`), then per game filter workloads by both ACT rosters.
3. **Dispatch**: `pool = parallel_day.get_pool(workers)`;
   `futures = [pool.submit(parallel_day.simulate_game_job, payload) for payload in payloads]`.
4. **Replay in `games` list order** — for `game, seed, future` in zip:
   - `journal = future.result()` — on ANY exception (including BrokenProcessPool): log via
     `logging.getLogger(__name__).warning(...)`, then serial fallback (D12):
     `result = simulate_game_scores(game["home"], game["away"], seed=seed, game_date=current_date, home_starter=…, away_starter=…)` executed in-parent (side effects direct, batch contexts active). On BrokenProcessPool additionally `parallel_day.shutdown_pool()` and fall back serially for **all remaining games** of the day.
   - Otherwise replay the journal, per-game op order mirroring `_run_physics_game`:
     a. captured `decision_logs` → `append_decision_log` each; `bullpen_status_logs` → append to `get_data_dir()/"tmp"/"bullpen_status.log"`;
     b. `tracker.bullpen_game_status(home…)`, `(away…)` — discard results (D10);
     c. `_apply_injury_events(journal["injury_events"], players_file=…, roster_dir=…, game_date=current_date)` (import from `game_runner`);
     d. stats replay (audit row 1) — `save_stats(...)` into the live batch + refresh parent `_teams_by_id` Team objects;
     e. `record_game_special_events(metadata=journal["lines"], home_id, away_id, players_lookup=day_lookup, game_date=current_date)` where `day_lookup = {p.player_id: p for p in load_players_from_csv(players_file)}` built **once per day, after step c of the first game would be too late — build it lazily but rebuild if any injuries were applied that day** (simplest correct rule: rebuild `day_lookup` after every game that had `injury_events`; the loader is mtime-cached so this is cheap);
     f. tracker `record_game(home…)`, `(away…)` from `lines.pitcher_lines` (audit row 4);
     g. usage merge (audit row 9);
     h. `result = (journal["result"]["home_runs"], journal["result"]["away_runs"], journal["boxscore_html"], journal["meta"])`.
   - Common tail (identical to serial loop, season_simulator.py:234-244):
     `_apply_result_to_game(game, result)`; `after_game(game)` best-effort; `use_default_save`
     meta accumulation (`result[3]` is the meta dict in both paths).
5. The existing post-loop `use_default_save` fallback-totals block (246-295) runs unchanged.

`use_default_save` remains `self.simulate_game is self._default_simulate_game` — the journal
path reconstructs the exact 4-tuple, so both the API caller (`simulate_game_scores`,
`use_default_save=False`, persistence via `_persist_post_sim_state`, season.py:707-708) and
the benchmark caller (default, `use_default_save=True`) behave identically to serial.

### 4.2 Pool lifecycle

- `_POOL: ProcessPoolExecutor | None` + `_POOL_WORKERS: int` module globals in `parallel_day`.
- `get_pool(n)`: if `_POOL` exists and `_POOL_WORKERS == n` → return it; else shut the old one
  down (`shutdown(wait=False, cancel_futures=True)`) and create
  `ProcessPoolExecutor(max_workers=n, mp_context=multiprocessing.get_context("spawn"))`.
- Before first creation: `os.environ.setdefault("PYTHONHASHSEED", "0")` so spawned children
  hash deterministically (§5); note the parent's own hashing is already fixed for its lifetime.
- `atexit.register(shutdown_pool)` at module import.

---

## 5. RNG parity analysis

**Why per-game parity holds:** seeds are fixed in the parent before dispatch
(season_simulator.py:204). `physics_sim.engine.simulate_game` derives ALL in-game randomness
from that seed: `rng = random.Random(seed)` and `random.seed(seed)` (engine.py:3194-3195 —
the global reseed exists precisely because some engine paths still use module-level
`random`). Therefore a game with seed *s* is bit-identical in any process. The
`rng = random.Random(seed)` in `run_single_game` (game_runner.py:1335) feeds only the legacy
`GameSimulation` — unused on the physics path.

**Global-random consumers outside the seeded game (the cross-day bug):** the serial loop
leaves the parent's global `random` in a state determined by the last game's
`random.seed(seed)` + engine draws; `simulate_next_day` then generates the NEXT day's seeds
from that global state (line 204). In parallel the engine never runs in-parent → day-2+
seeds diverge. **Fix (D6), exact change** in `simulate_next_day`, replacing line 204:

```python
if not hasattr(self, "_seed_rng") or self._seed_rng is None:
    # One draw from the global stream (honors callers' random.seed(...)),
    # then a private generator the engine's global reseeding can't touch.
    self._seed_rng = random.Random(random.randrange(1 << 62))
seeds = [self._seed_rng.randrange(1 << 30) for _ in games]
```

(`self._seed_rng = None` in `__init__`.) Callers seed global `random` after construction
(benchmark_sim_days.py:110-111), so the lazy first draw preserves their seeding contract.
This changes serial seed VALUES from day 2 onward vs today's code — **the benchmark table in
deep_review_plan.md must be re-baselined** (digests are same-code comparisons; the harness
already requires same-day re-baselines).

**`_apply_bullpen_usage_order` RNG (verified):** game_runner.py:281-283 —
`ordering_rng = random.Random(hash((team_id, date_token, seed or 0)))`. It consumes NO global
random; it is a pure function of the payload **and of Python's string-hash seed** (a str is
in the tuple). Serial computes it in the parent, parallel in a worker → parity requires the
same `PYTHONHASHSEED` in both, which `scripts/benchmark_sim_days.py` already enforces by
re-exec with `PYTHONHASHSEED=0` (lines 40-46); spawned pool children inherit it.
`lineup_autofill`'s fallback shuffle uses `random.Random(f"{team_id}-lineup-fallback")`
(lineup_autofill.py:169) — hash-free, process-independent.

**Tracker/start_day:** no RNG anywhere in `utils/pitcher_recovery.py`. `start_day` saves to
disk before dispatch (pitcher_recovery.py:410-411, called at season_simulator.py:203), so
workers read the post-recovery state.

**Known non-gated consumers (unchanged behavior):** `on_all_star_break` / `on_draft_day`
callbacks run in-parent in both modes but read whatever global-random state exists; they are
outside the benchmark digest surface (benchmark passes no callbacks).

---

## 6. Guardrails

| Guardrail | Mechanism |
|---|---|
| Windows spawn pickling | Only `parallel_day.simulate_game_job` + a plain dict are ever submitted; module has no closures/lambdas at the submission boundary; guarded by test `test_payload_and_job_are_picklable` |
| Worker env inheritance | spawn children inherit `os.environ` (`NEXGEN_DATA_ROOT`, `PB_GAME_ENGINE`, `PB_PERSIST_STATS`, `PB_SKIP_BOXSCORE_HTML`, `PB_LOG_BULLPEN_STATUS`, `NEXGEN_DECISION_LOG`, `PYTHONHASHSEED`). Belt-and-suspenders: `data_root` + `league_id` ride the payload (D8) because the ContextVar league does NOT inherit |
| Env mutation ordering | Callers that set env in-process (e.g. `run_long_term_physics_sim.py:610` sets `PB_SKIP_BOXSCORE_HTML`) must do so before the first parallel day — the pool is created lazily on first use, document in the module docstring |
| Single-CPU degrade | `resolve_worker_count`: `"auto"` → `min((os.cpu_count() or 1) - 1, num_games)`; result < 2 → serial. Cloud Run 1 vCPU degrades even if someone sets `auto`. Default (unset) is serial (D1) |
| Worker crash | D12 per-game serial fallback; BrokenProcessPool → whole-day serial fallback + pool recreation next day |
| Max journal size | D13: 32 MB soft cap enforced worker-side via `json.dumps`; `PB_SKIP_BOXSCORE_HTML=1` is the recommended companion for bulk sims |
| Stale worker caches | D9 per-job resets; players/rosters covered by mtime-keyed unified service |
| Hash determinism | `os.environ.setdefault("PYTHONHASHSEED", "0")` before pool creation; parity gate always runs under the benchmark's pinned hash seed. Caveat: a D12 fallback game in an unpinned parent may order bullpen ties differently than the worker would have — acceptable on the degraded path |

---

## 7. Test plan

### 7.1 Parity gate (the release gate)

```powershell
# serial baseline (fresh sandbox each run; PYTHONHASHSEED handled by the script)
python scripts/benchmark_sim_days.py --source data/leagues/cbl/data --days 10 --seed 123 --json
# parallel
$env:PB_PARALLEL_GAMES = "4"
python scripts/benchmark_sim_days.py --source data/leagues/cbl/data --days 10 --seed 123 --json
Remove-Item Env:PB_PARALLEL_GAMES
```

Gate: all three digests (`scores`, `season_stats`, `pitcher_recovery`) identical, **same-day**
(the harness caveat about wall-clock-keyed trim windows applies unchanged). Because D6
changes day-2+ seeds, run the serial baseline with the NEW code — do not compare against
pre-S1-10 digest records.

**Wall-clock gate:** at 4 workers on a 12-team day (6 games/day), `seconds_per_day` must be
≥1.5× faster than the same-machine serial run of the same code — OR the run must prove
auto-degrade (with `PB_PARALLEL_GAMES=auto` on a 1-CPU container, output equals serial and
no pool is created). Record both numbers in the deep_review_plan benchmark table.

### 7.2 `tests/test_parallel_day.py` (new; all tests point `NEXGEN_DATA_ROOT` at a tmp copy of a fixture league — follow the `tests/test_api_smoke.py:22` pattern; never the active league)

| Test | Setup | Assert |
|---|---|---|
| `test_resolve_worker_count_defaults_serial` | unset env / `"0"` / `"1"` / `"auto"` with `os.cpu_count` monkeypatched to 1 / `"4"` with 6 games | returns 0 / 0 / 0 / 0 / 4 |
| `test_payload_and_job_are_picklable` | `build_payload(...)` for a 2-team fixture | `pickle.dumps(payload)` and `pickle.dumps(simulate_game_job)` succeed; `json.dumps(payload)` succeeds |
| `test_simulate_game_job_writes_nothing` | hash every file under the tmp league; call `simulate_game_job(payload)` **in-process** (no pool); re-hash | file set + hashes unchanged EXCEPT optionally `lineups/*_vs_*.csv` (D11); returned journal has every §2.2 key and `json.dumps` succeeds |
| `test_journal_replay_applies_all_side_effects` | hand-built journal (1 injury event, 2 players + 2 teams in `stats`, pitcher_lines with a 10-K line, one decision log) replayed via the parent replay helper inside `batched_stats_writes()`/`deferred_saves()` | after contexts exit: `season_stats.json` has the player/team mappings; `pitcher_recovery.json` shows `last_used`=date for the line's pitcher; `special_events.json` contains the strikeouts event; `news_feed.txt` gained injury + special-event lines; `players.csv` row marked injured; roster `dl` updated |
| `test_parallel_day_matches_serial_digests` | subprocess-run a small driver (so `PYTHONHASHSEED=0` env applies to parent AND workers) that copies a 4-team fixture league twice and sims 3 days with seed 42, once `PB_PARALLEL_GAMES=0`, once `=2` | `scores` / `season_stats` / `pitcher_recovery` digests equal across the two sandboxes; mark `@pytest.mark.slow` |
| `test_seed_rng_decoupled_from_global` | `SeasonSimulator` with stub `simulate_game` that calls `random.seed(0)` (simulating engine trash); record day-1/day-2 seeds via a spy; second simulator identical but stub does NOT touch global random | both runs produce identical day-2 seeds |
| `test_starter_preassignment_matches_serial` | fixture league; serial run capturing per-game `(home_starter, away_starter)` via monkeypatched `run_single_game`; then parallel pre-assignment loop on a fresh tracker | identical starter sequence and identical `next_index` per team afterwards |
| `test_worker_failure_falls_back_to_serial` | monkeypatch `parallel_day.get_pool` to return a fake executor whose futures raise `RuntimeError` | `simulate_next_day` completes; every game has `result`; digest equals a pure-serial run of the same seed |
| `test_usage_state_roundtrip` | build `usage_in` with nonzero `fatigue_debt`; run `simulate_game_job` in-process | `journal["usage"]["workloads"]` retains/updates the debt (starter's debt strictly increased); parent merge helper overwrites only the payload pids |

Run: `python -m pytest tests/test_parallel_day.py -q` plus the §7.1 commands.

---

## 8. Handoff deltas vs docs/deep_review_plan.md (S1-10 block, lines 121-151)

## 9a. Implementation notes / deviations (as-built, 2026-08-18)

Implemented on branch `s1-10-parallel-day`. Byte-parity verified serial-vs-parallel
across days {1,2,3,10,12,15,20}, seeds {42,123,999}, and worker counts {2,3,4,6}
via `benchmark_sim_days.py` (all three digests identical). Deviations from the
spec above, each forced by a re-verification against the real code:

- **D14 (NEW) — stateless pitcher-role derivation.** `utils/lineup_loader.py`
  `_build_default_lists` mutated `assigned_pitching_role` on **cached** player
  objects and relabeled extra-rotation arms to `"MR"` in place; the old
  `if not assigned:` guard then honored that persisted value on the next game.
  Result: staff ordering depended on whether a player had already appeared **in
  this process**, which (a) made parallel workers diverge from the serial parent
  from day 2 on and (b) made a persistent worker pool non-deterministic
  run-to-run. Fixed by **always re-deriving** the non-staff role from static
  ratings (`get_role`). This changes serial CBL digests (re-baselined) but is
  **provably KPI-neutral**: the calibration-league KPI JSON is byte-identical
  with and without the change (the calibration rosters list every pitcher in the
  staff CSV, so there is no `remaining` set to reorder). This single fix removed
  the need for `max_tasks_per_child=1`, so the pool reuses workers.
- **pitcher_roles journal field (NEW).** `record_game` derives `last_role` from
  `player.assigned_pitching_role` on the worker's in-game player instances. The
  parent's fresh `day_lookup` resolves that attribute differently, so the worker
  captures the exact per-pitcher role and the parent applies it before replaying
  `record_game` (else `pitcher_recovery.json` diverges on last_role/budgets).
- **usage_in is FULL, usage_out is diffed (revised D7).** The spec's per-game
  ACT-roster filter on `usage_in` dropped participants and broke day-2 fatigue.
  As built: every worker receives the **full** fatigue state; the worker returns
  only the workloads it **changed** (`diff_usage_out`), so the parent merge
  touches exactly the game's participants without reverting others.
- **Workload serialization is generic** (`dataclasses.asdict`), not the spec's
  hardcoded field list — the real `PitcherWorkload`/`BatterWorkload` carry extra
  fields (`last_pitches`, `last_rest_day`, `rests`).
- **Pool uses the persistent module singleton** (D4) with worker reuse; the D9
  per-job resets plus D14 make reuse deterministic.
- **Performance:** ~1.28x on the 12-team CBL benchmark (fast engine → IPC/pickle
  overhead dominates); auto-degrades to serial on 1-vCPU. Correctness-first: the
  full-state payload was kept over a smaller roster-filtered one.

New serial baseline (post-D14), `--source data/leagues/cbl/data --days 10 --seed 123`:
`scores=aa54184b1dbc941a season_stats=6c7393aac1af7c91 pitcher_recovery=d362dbb72724b58d`.

Pre-existing (NOT from this work): KPI seed 2 fails `tto_ops_gap` (0.088 vs
0.05±0.025) identically with and without D14.

## 9. Handoff deltas vs docs/deep_review_plan.md (S1-10 block, lines 121-151)

The handoff's intercept list was correct but incomplete. This spec adds, with evidence:
cross-day seed divergence fix D6 (mandatory, changes serial seeds → re-baseline);
UsageState payload round-trip D7 (fatigue affects outcomes — "usage day updates" alone is
insufficient); multi-tenant league binding D8 (ContextVar doesn't cross processes);
per-job worker cache resets D9 (`_teams_by_id`, tracker singleton); parent replay of
`bullpen_game_status` D10 (byte parity of pitcher_recovery.json); direct worker lineup
salvage writes D11; and the handoff's "default auto" suggestion is overridden to **opt-in**
(D1) for Cloud Run safety.
