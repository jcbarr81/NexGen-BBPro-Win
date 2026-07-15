# S2-10 — CPU-to-CPU Trades (spec)

> Implementation-ready spec, verified against the working tree 2026-07-15.
> Depends on S2-09 landing first (uses `services/team_outlook.py`,
> `days_to_deadline`, and the `timeline_weight_factor` evaluator kwarg —
> all specified in `S2-09_deadline_aware_trading.md`).

## Objective

CPU proposals only ever target human teams:
`run_cpu_trade_proposal_cycle` splits teams into `cpu_teams` /
`human_teams` (`services/cpu_trade_proposals.py:141-161`, via
`_load_human_team_ids` reading `users.txt` owner rows, lines 673-695), bails
with `insufficient_teams` when either side is empty (line 163-165), and
`_build_best_offer(human_team_ids=human_teams, ...)` (lines 249, 361) iterates
only human targets. The other ~28 CPU teams never trade among themselves.
Add an auto-resolved CPU→CPU lane: proposer builds an offer, the receiver
evaluates it with the existing evaluator, accepted deals commit through the
same execution path owner-accepted trades use, with visible transaction-log +
news entries and hard volume caps.

## Verified current state (load-bearing facts)

- **Commit path**: `_commit_trade(trade)` lives in
  `api/routers/trades.py:136-257`. It is *almost* UI-independent — pure
  `load_roster`/`save_roster` ACT swaps, `transfer_pick`, and
  `record_transaction` calls — **except** it raises `fastapi.HTTPException`
  on bad pick ownership (lines 168-172, 176-180). It must be extracted (see
  D1). Callers today: `propose_trade` auto-accept (line 430), owner
  `accept_trade` (line 501), `admin_approve_trade` (line 568),
  `counter_trade` auto-accept (line 752).
- **Evaluator works for CPU receivers by construction**:
  `evaluate_cpu_trade_offer` returns `None` unless `trade.to_team` is
  CPU-owned (`cpu_trade_evaluator.py:106-112`), evaluates from the
  **receiver's** (`to_team`) perspective, and returns
  `action in {"accept","reject","counter"}` with
  `threshold = _window_threshold(window) + _decision_variation(trade_id, team_id)`
  (lines 194-199; contend 0.90 / balanced 0.45 / rebuild 0.10 ± 0.22).
  `counter_offer` payload keys: `incoming_player_ids`, `outgoing_player_ids`,
  `incoming_pick_ids`, `outgoing_pick_ids` (+ `counter_kind`), expressed from
  the **evaluating team's** perspective (lines 550-717).
- **Anti-spam structures that already exist and get reused**:
  `_MAX_PENDING_CPU_OFFERS_TOTAL = 8`, `_REPEAT_PACKAGE_BLOCK_DAYS = 45`,
  `_PACKAGE_HISTORY_RETENTION_DAYS = 180` (lines 65-67); per-league state in
  `cpu_trade_proposal_state.json` with `team_last_offer_dates`,
  `target_last_offer_dates`, `recent_packages` (lines 174-190);
  `_offer_package_signature` (line 610).
- **Finance/roster guards do NOT run at commit today**: `validate_trade`
  (`services/roster_validation.py:545`, level caps 25/15/10 via
  `DEFAULT_LEVEL_CAPS`) runs only in `propose_trade`/`counter_trade`/
  `admin_approve_trade`; `_commit_trade` itself validates nothing.
  `services/payroll_policy.evaluate_trade_payroll_impact(trade,
  players_by_id=..., data_dir=..., league_id=...) -> PayrollPolicyResult`
  (payroll_policy.py:150-190, result fields `allowed/warning/mode/level/
  violations`) exists but is **never called anywhere in the trade flow**
  (verified: only finance.py/free_agency.py/season.py import policy fns).
  `services/prospect_rules` never gates trades (only ACT promotions /
  option demotions) — trades move ACT↔ACT, so no prospect-rule call is
  needed; protection travels implicitly (protected_players is keyed by team,
  and a traded player simply isn't protected on the new team — acceptable,
  matches human-trade behavior today).
- **`save_trade` deadline guard** applies to `pending` rows only
  (`utils/trade_utils.py:99`); rows written with `status="accepted"` bypass
  it — CPU-CPU trades are never persisted as pending (see flow below), so
  they are only legal pre-deadline because the whole cycle is deadline-gated
  by S2-09's `past_deadline` early-exit.
- **Stability tooling**: `scripts/sim_finance_stability.py`
  (`--seasons/--data-dir/--seed/--json-out/--strict`, drives
  `services/finance_stability.run_finance_stability_simulation`) and
  `scripts/validate_finance_release.py --seasons 8` exist. Neither simulates
  the on-field schedule day-by-day, so the trade-volume acceptance run uses
  the season sim loop instead (see Test plan).

## Acceptance criteria

1. CPU teams propose to and complete trades with other CPU teams without any
   human/owner interaction; humans are never a party to an auto-resolved
   trade (invariant test).
2. Auto-resolution: receiver evaluates via `evaluate_cpu_trade_offer`
   unchanged thresholds; `accept` commits immediately; `counter` gets exactly
   one counter round (receiver's counter evaluated by the proposer; accept →
   commit counter package, anything else → drop); `reject` drops.
3. Executed CPU-CPU trades appear in `trades_pending.csv` with
   `status="accepted"`, `initiated_by="cpu"`, in the transaction log
   (`trade_out`/`trade_in` rows), and in the news feed (one line per deal).
4. Caps hold: ≤ 2 executed CPU-CPU trades per cycle-week (rolling 7 sim
   days), 21-day per-team CPU-CPU cooldown, and CPU-CPU work runs only when
   the pending-offer global cap hasn't tripped.
5. Guards: `validate_trade` (level caps) must pass and
   `evaluate_trade_payroll_impact(...).allowed` must be True for both sides
   before commit; failure drops the deal silently (counted in
   `filtered_counts`).
6. 3-season stability: 15-40 executed CPU-CPU trades per simulated season and
   the stddev of team win% does not grow season-over-season (measurement
   defined below).
7. Existing suites green: `tests/test_cpu_trade_proposals.py`,
   `tests/test_cpu_trade_evaluator.py`, `tests/test_v53_acceptance.py`,
   `tests/test_trades_api.py` if present (verify with
   `pytest tests -k "trade" --collect-only` before starting).

## Decisions (no open choices)

- **D1 — Extract the commit function** to
  `services/trade_execution.py::commit_trade(trade, *, data_dir=None) -> None`,
  a verbatim move of `api/routers/trades.py::_commit_trade` with the two
  `HTTPException` raises replaced by `ValueError` (message preserved).
  `api/routers/trades.py` keeps a thin `_commit_trade` wrapper that calls it
  and re-raises `ValueError` as `HTTPException(400)`. Rationale: the function
  is otherwise UI/HTTP-free; the service module must not import fastapi.
- **D2 — One counter round max.** Proposer→receiver offer; if receiver
  counters, the counter trade (from_team=receiver, to_team=proposer, package
  from `counter_offer` mapped below) is evaluated by the proposer with
  `evaluate_cpu_trade_offer`; `accept` → commit, `reject`/`counter`/None →
  drop entirely. Rationale: bounded work per cycle, no oscillation, and the
  evaluator's `_build_counter_offer` already aims for minimal viable deltas
  so one round captures most of the surplus.
- **D3 — Accept threshold is the evaluator's existing logic, unmodified**
  (`total_score >= _window_threshold(window) + _decision_variation`). No
  separate CPU-CPU threshold. Rationale: symmetric with human-target offers;
  the proposer side already enforces `min_score_margin` from cadence config
  so double-agreeable deals are genuinely positive-sum.
- **D4 — Numbers**: `_CPU_CPU_MAX_PER_WEEK = 2` (rolling 7 sim-day window),
  `_CPU_CPU_TEAM_COOLDOWN_DAYS = 21`, at most `1` CPU-CPU execution attempt
  per cycle run (an executed deal ends the CPU-CPU pass for that run).
  Rationale: 2/week ≈ 24-48 per 26-week season → lands inside the 15-40
  acceptance band after evaluator rejections; 21 days mirrors the "low"
  cadence `min_days_between`.
- **D5 — CPU-CPU pass runs after the human-target pass** inside
  `run_cpu_trade_proposal_cycle` (not a new service): it shares every loaded
  artifact (players, rosters, teams, state file, outlooks) and the state
  write at line 320. A separate module would reload all of it per sim day.
- **D6 — Timeline reweight applies to both sides** by passing S2-09's
  `timeline_weight_factor` per evaluating team's own outlook (factor 1.5
  inside 30 days for contend/rebuild evaluators, else 1.0). Rationale: a
  rebuilding receiver near the deadline should demand youth just as a buying
  proposer overpays.

## Files to change (verified anchors)

| File | Anchor | Change |
|---|---|---|
| `services/trade_execution.py` | new | `commit_trade` (moved from router) + news-feed emission |
| `api/routers/trades.py` | 136-257 | delete body, delegate to service; map `ValueError`→400 |
| `services/cpu_trade_proposals.py` | 65-67 (constants), 163-165 (insufficient_teams), 320 (state write), after 318 (new pass) | CPU-CPU pass, caps, state keys |
| `tests/test_cpu_trade_proposals.py` | append | forced-pair / cap / invariant tests |
| `tests/test_trade_execution.py` | new | commit parity test |

## Exact implementation

### 1. `services/trade_execution.py` (new)

```python
"""UI-independent trade commit shared by the trades router and CPU-CPU lane."""
from models.trade import Trade
from services.draft_pick_ledger import format_pick_label, transfer_pick
from services.transaction_log import record_transaction
from utils.roster_loader import load_roster, save_roster

def commit_trade(trade: Trade, *, data_dir=None) -> None:
    """Apply roster + pick swap and write transaction-log rows.
    Verbatim logic of api/routers/trades.py:136-257 with HTTPException ->
    ValueError. Raises ValueError on pick-ownership failure; roster moves
    ACT<->ACT exactly as today."""

def announce_trade(trade: Trade, *, players_by_id=None, data_dir=None) -> None:
    """News-feed line so users SEE the deal. Uses utils.news_logger.log_news_event
    (signature verified utils/news_logger.py:39-45):
      log_news_event(
        f"TRADE: {from_team} send {give_names} to {to_team} for {recv_names}."
        (+ " Picks included." when pick ids present),
        category="trade", team_id=trade.from_team,
        file_path=(data_dir / "news_feed.txt") if data_dir else None)
    Names resolved from players_by_id (fallback: raw ids). Best-effort:
    wrap in try/except."""
```

Router keeps behavior: `_commit_trade(trade)` = `try: commit_trade(trade);
except ValueError as exc: raise HTTPException(400, str(exc))`, then also call
`announce_trade(trade)` in `accept_trade` / `admin_approve_trade` /
propose-auto-accept / counter-auto-accept (human-visible trades get news too
— free consistency win; note it in release notes).

### 2. `services/cpu_trade_proposals.py` — CPU-CPU pass

Constants (with the existing block, lines 65-67):

```python
_CPU_CPU_MAX_PER_WEEK = 2          # executed deals per rolling 7 sim days
_CPU_CPU_TEAM_COOLDOWN_DAYS = 21   # either party
_CPU_CPU_DAILY_CHANCE = 0.30       # per-cycle gate before any pairing work
```

League-state additions (persisted in the same
`cpu_trade_proposal_state.json`, coerced like the existing maps at
lines 178-189): `cpu_cpu_last_trade_dates: {TEAM_ID: iso_date}` and
`cpu_cpu_executions: [iso_date, ...]` (pruned to 30 days on load).

**Gate change at line 163**: `insufficient_teams` currently requires both
lists non-empty. Change to: bail only when `len(cpu_teams) < 2 and not
(cpu_teams and human_teams)` — i.e. the human-target pass needs
`cpu_teams and human_teams` (skip it otherwise, `filtered_counts` note), the
CPU-CPU pass needs `len(cpu_teams) >= 2`. An all-CPU league (zero owners)
now trades internally instead of returning `insufficient_teams`.

**New pass** — after the human-target loop finishes (after line 318), before
`_write_state` (line 320):

```python
cpu_cpu_result = _run_cpu_cpu_pass(
    cpu_teams=cpu_teams, players_by_id=players,
    rosters_by_team=rosters_by_team, teams_by_id=teams_by_id,
    pending_trades=pending_trades, league_state=league_state,
    current_date=current_date, days_to_deadline=days_to_deadline,
    outlooks=outlooks, data_dir=resolved_data_dir, rng=randomizer,
    min_score_margin=min_score_margin,
    blocked_packages=blocked_package_signatures,
    recent_packages=recent_packages,
)
result["cpu_cpu_trades"] = cpu_cpu_result   # {"executed": [...], "filtered": {...}}
```

`_run_cpu_cpu_pass` algorithm (module-private):

1. **Caps first**: if `len([d for d in cpu_cpu_executions if (current_date - d).days < 7]) >= _CPU_CPU_MAX_PER_WEEK` → return `{"executed": [], "filtered": {"weekly_cap": 1}}`.
   If `rng.random() > _window_probability(_CPU_CPU_DAILY_CHANCE, len(dates))` → filtered `cadence_skip`.
2. **Proposer loop**: iterate `rng.sample(cpu_teams, len(cpu_teams))`;
   skip proposer when `cpu_cpu_last_trade_dates` shows either a proposal or
   execution within `_CPU_CPU_TEAM_COOLDOWN_DAYS`, or the proposer's outlook
   is `"bubble"` (only contenders/rebuilders initiate — gives the lane a
   deadline-story shape and halves pairing work).
3. **Offer build**: call the existing `_build_best_offer` with
   `human_team_ids=[t for t in cpu_teams if t != proposer and not on cooldown]`
   (the parameter is just a target list — verified it does nothing
   human-specific; rename the kwarg to `target_team_ids` in the same commit,
   updating the one call site at line 249). Pass `outlook` +
   `days_to_deadline` (S2-09 kwargs).
4. **Receiver evaluation** (the offer as-built is
   `from_team=proposer, to_team=receiver` — already receiver-oriented for
   `evaluate_cpu_trade_offer`):
   ```python
   evaluation = evaluate_cpu_trade_offer(
       offer.trade, players_by_id=..., data_dir=..., teams_by_id=...,
       rosters_by_team=..., allow_counter_offers=True,
       timeline_weight_factor=_factor_for(outlooks.get(receiver), days_to_deadline))
   ```
   - `accept` → go to step 6 with `final = offer.trade`.
   - `counter` with payload → step 5. `reject`/None → next proposer.
5. **One counter round**: build
   `counter = Trade(trade_id=uuid4().hex[:8], from_team=receiver,
   to_team=proposer, give_player_ids=counter_offer["outgoing_player_ids"],
   receive_player_ids=counter_offer["incoming_player_ids"],
   give_pick_ids=counter_offer["outgoing_pick_ids"],
   receive_pick_ids=counter_offer["incoming_pick_ids"],
   initiated_by="cpu")` — note the perspective flip: the evaluator's
   `incoming_*` are assets the receiver wants, i.e. what the proposer
   `gives`… **mapping check**: evaluator "incoming" = flowing TO the
   evaluating receiver = FROM the proposer; on the flipped trade
   (from_team=receiver) those are `receive_*`. So:
   `give_player_ids=outgoing_player_ids` (receiver parts with),
   `receive_player_ids=incoming_player_ids`. Evaluate
   `evaluate_cpu_trade_offer(counter, ..., allow_counter_offers=False,
   timeline_weight_factor=_factor_for(outlooks.get(proposer), ...))`
   (to_team=proposer, so the proposer judges). `accept` → `final = counter`;
   else drop, count `counter_dropped`.
6. **Guards before commit** (count failures as `validation_failed` /
   `payroll_blocked`):
   - `services.roster_validation.validate_trade(give_player_ids=...,
     receive_player_ids=..., give_pick_ids=..., receive_pick_ids=...,
     from_team_levels=..., to_team_levels=..., players=players_as_mappings,
     settings={"draft_pick_trading_enabled": settings.draft_pick_trading_enabled,
     "max_pick_trade_years": settings.max_pick_trade_years,
     "current_year": current_league_year()})` must return `.ok`.
     Level maps built from `rosters_by_team` (act/aaa/low lists); players
     mapping built once per pass via
     `{pid: {"is_pitcher": ..., "primary_position": ..., "other_positions": ...,
     "first_name": ..., "last_name": ...} for pid, p in players.items()}`.
   - `evaluate_trade_payroll_impact(final, players_by_id=players,
     data_dir=resolved_data_dir).allowed` must be True (this makes CPU-CPU
     the FIRST trade lane with a payroll gate — deliberate; human lanes stay
     as-is, out of scope).
7. **Commit + visibility**:
   ```python
   final.status = "accepted"
   from services.trade_execution import commit_trade, announce_trade
   commit_trade(final, data_dir=resolved_data_dir)      # ValueError -> drop, count commit_failed
   save_trade(final, resolved_data_dir / "trades_pending.csv")  # accepted rows bypass deadline guard
   announce_trade(final, players_by_id=players, data_dir=resolved_data_dir)
   ```
   Then update state: `cpu_cpu_last_trade_dates[proposer] =
   cpu_cpu_last_trade_dates[receiver] = current_date.isoformat()`,
   append to `cpu_cpu_executions`, append the package to `recent_packages`
   and its signature to `blocked_packages` (reusing lines 293-308's shapes),
   and **update `rosters_by_team` in-memory** (pop/append ACT ids exactly as
   commit did) so a same-run second attempt can't double-trade a player.
   Return — one execution per cycle run (D4).

Roster invalidation: `commit_trade` calls `save_roster`, which updates the
unified data service (roster_loader.py:506-521), so subsequent loads are
fresh; no extra invalidation needed.

## Edge cases

- **No CPU teams / one CPU team**: pass skips (`len(cpu_teams) >= 2` guard).
- **All-human league**: `cpu_teams` empty → both passes skip, reason "ok",
  zero offers (was `insufficient_teams`; keep that reason when BOTH passes
  are structurally impossible).
- **Player traded twice in one run**: prevented by the in-memory
  `rosters_by_team` mutation in step 7 + single-execution-per-run.
- **Pending human-facing offer involving the same player**: a CPU-CPU commit
  can invalidate a pending CPU→human offer's `give_player_ids`. Accept path
  already tolerates this (`_commit_trade` removes only if present), but add:
  after commit, mark any pending trade whose asset lists intersect the
  executed package as `status="withdrawn"` via `save_trade` (loop over
  `pending_trades`).
- **Deadline**: the whole cycle already early-exits `past_deadline` (S2-09),
  so no CPU-CPU deals after July 31.
- **Draft-pick trading disabled**: offers are player-for-player only today
  (`_build_best_offer` never adds picks); counter offers CAN add picks
  (evaluator options 1/3) — `validate_trade` settings gate rejects those
  when disabled (step 6 handles it; counted, dropped).
- **Payroll policy off** (`mode == "off"`): result.allowed is True → lane
  works in finance-less leagues.

## Test plan

Commands:
`pytest tests/test_cpu_trade_proposals.py tests/test_trade_execution.py tests/test_cpu_trade_evaluator.py tests/test_v53_acceptance.py -q`

New tests:

- `tests/test_trade_execution.py::test_commit_trade_parity_with_router` —
  build two 3-player rosters on `tmp_path`, commit a 1-for-1; assert roster
  CSVs swapped and two `trade_out` + two `trade_in` rows recorded
  (monkeypatch `record_transaction` capture).
- `tests/test_trade_execution.py::test_commit_trade_bad_pick_raises_valueerror`.
- `tests/test_cpu_trade_proposals.py::test_cpu_cpu_forced_pair_executes` —
  two CPU teams, zero humans; monkeypatch evaluator → accept, payroll →
  allowed, `_window_probability` → 1.0, rng seeded; assert
  `result["cpu_cpu_trades"]["executed"]` length 1, saved trade
  `status=="accepted"`, `initiated_by=="cpu"`, news + transaction hooks
  called (capture monkeypatches).
- `tests/test_cpu_trade_proposals.py::test_cpu_cpu_counter_round_accepted` —
  evaluator returns `counter` first (with payload), then `accept` on the
  flipped trade (side-effect list); assert executed package equals the
  counter package and exactly 2 evaluator calls.
- `tests/test_cpu_trade_proposals.py::test_cpu_cpu_counter_round_dropped` —
  second evaluation rejects → nothing executed.
- `tests/test_cpu_trade_proposals.py::test_cpu_cpu_weekly_cap` — seed state
  with 2 executions dated 3 days ago → pass filtered `weekly_cap`.
- `tests/test_cpu_trade_proposals.py::test_cpu_cpu_team_cooldown` — seed
  `cpu_cpu_last_trade_dates` 10 days ago for the only viable pair → skipped.
- `tests/test_cpu_trade_proposals.py::test_cpu_cpu_never_touches_humans`
  (no-human-involvement invariant) — mixed league, force 50 cycle runs with
  aggressive rng; assert every executed CPU-CPU deal has both parties in
  `cpu_teams` and no pending human-target offer was auto-accepted.
- `tests/test_cpu_trade_proposals.py::test_cpu_cpu_payroll_block` —
  payroll monkeypatch returns `allowed=False` → filtered `payroll_blocked`,
  nothing committed.

3-season stability acceptance (manual gate, record in the truth doc):

```
python scripts/simulate_season.py  # NOT used — no trade hooks; use the API loop:
# On a sandbox copy of the league (set NEXGEN_DATA_ROOT to a tmp clone),
# drive three full seasons through the season router's day loop
# (uvicorn + POST /season/simulate/to-playoffs, advance-phase x2, repeat x3)
# or equivalently a small driver script scripts/sim_seasons_with_automations.py
# (add it in this task: loop _simulate_n + advance_phase using the router
# helpers directly, no HTTP).
```

Measurements after each season, from the sandbox data dir:
- CPU-CPU volume: `python scripts/list_transactions.py` (exists) or count
  rows in `trades_pending.csv` where `status==accepted and initiated_by==cpu`
  and both teams CPU → must be 15-40 per season.
- Talent balance: stddev of final team win% per season from
  `standings.json`; assert season3_std <= season1_std * 1.15 (no runaway
  consolidation). Then run
  `python scripts/validate_finance_release.py --seasons 8` → must stay green.

## Non-goals

- Multi-player or pick-seeded initial CPU-CPU packages (initial offers stay
  1-for-1; counters may add picks). Human notification/approval UI for
  CPU-CPU deals (news feed + transactions page are the surface).
  Commissioner veto flow for CPU-CPU (admin can still see them; veto of
  already-executed trades is out of scope). Adding payroll gates to
  human-initiated lanes. Rebalancing evaluator thresholds.
