# S2-09 — Deadline-Aware CPU Trading (spec)

> Implementation-ready spec. All file/line anchors verified against `main`
> @ working tree on 2026-07-15. Companion specs: `S2-10_cpu_to_cpu_trades.md`
> (consumes the same outlook + deadline plumbing), `S2-11_inseason_callups.md`
> (consumes `services/team_outlook.py`).

## Objective

CPU trade proposals (`services/cpu_trade_proposals.py`) are cadence-random and
standings-blind: `run_cpu_trade_proposal_cycle` samples CPU teams
(lines 230-246), rolls `daily_chance`, and `_build_best_offer` (line 330)
searches near-equal-value 1-for-1 swaps (value band ±18/22%, lines 391-393)
with no notion of contender/seller or the July 31 deadline. Make CPU teams
buy when contending, sell when rebuilding, ramp volume into the deadline, and
stop proposing after it — while keeping the human-side deadline rules
consistent.

## Verified current state (load-bearing facts)

- **The deadline date already has a canonical accessor set** — it is NOT
  UI-only. `utils/trade_utils.py:27-51` defines
  `trade_deadline_for_year(year) -> date(year, 7, 31)`,
  `current_trade_deadline()`, `is_past_trade_deadline()`,
  `days_until_trade_deadline()`, all sim-date-aware via `_today()`
  (`utils/trade_utils.py:14-24`, falls back to wall-clock pre-opening-day).
  `GET /trades/deadline` (`api/routers/trades.py:51-70`) and the Command
  Center countdown card (`services/league_command_center.py:336`,
  `trade_deadline = date(season_year, 7, 31)`) are both consistent with it.
  **Do not add a new accessor to `trade_settings`** — reuse
  `utils/trade_utils`. (The legacy constant
  `playbalance/season_manager.py:16` `TRADE_DEADLINE = date(date.today().year, 7, 31)`
  uses the wall-clock year and is only imported, never evaluated, by
  `utils/trade_utils.py:11` and `tests/test_trade_utils.py` — leave it, it is
  test-referenced.)
- **A de-facto hard block already exists for ALL pending trades** —
  `utils/trade_utils.save_trade` (line 99) raises
  `RuntimeError("Trade deadline (...) has passed.")` for any `pending` trade
  when `is_past_trade_deadline()`. Human proposals hit this via
  `api/routers/trades.py:387` (`propose_trade` → 400), CPU proposals hit it
  via `services/cpu_trade_proposals.py:282-286` (counted as `save_failed` —
  wasted work, cycle still runs). This block also covers OFFSEASON/PRESEASON
  because the sim date stays past July 31 until the league year rolls.
- **Contend/rebuild classification exists twice**, both unfit to import
  directly: `services/finance_ai.py:483-504` `_resolve_profile(win_pct, *,
  cash_on_hand, debt, projected_net)` entangles liquidity;
  `services/cpu_trade_evaluator.py:339-349` `_resolve_competitive_window`
  keys off strategy profile + raw win_pct with no games-back.
- The evaluator's scoring output fields (used below):
  `CpuTradeEvaluation.value_delta / fit_delta / timeline_delta /
  total_score / threshold` combined at `cpu_trade_evaluator.py:193` as
  `total_score = 0.68*value_delta + 0.20*fit_delta + 0.12*timeline_delta`;
  `_timeline_value` (line 482) already flips sign by window (contend favors
  prime-age current value, rebuild favors youth/upside), and `_pick_value` /
  `_pick_timeline_bonus` (lines 505-532) already up-weight picks 1.15× for
  rebuild / down-weight 0.92× for contend.
- Standings come from `services/standings_repository.load_standings`
  (normalized records carry `wins`/`losses`; see
  `utils/standings_utils.default_record`). `models/team.py:18` has
  `division: str` on every team.
- `_run_daily_automations` (`api/routers/season.py:812-856`) is the only sim
  hook calling `run_cpu_trade_proposal_cycle`, and `_simulate_n` is gated to
  `REGULAR_SEASON` (`api/routers/season.py:557`), so the CPU cycle never runs
  in playoffs/offseason today.

## Acceptance criteria

1. A shared `services/team_outlook.py` exposes
   `team_outlook(team_id, *, standings, teams_by_id, sim_date=None)`
   returning `"contend" | "bubble" | "rebuild"`, used by the proposal cycle
   (and by S2-10/S2-11).
2. Within 30 days of the deadline, contender-proposers acquire veterans
   (target pool + evaluation reweighted 1.5× timeline), rebuild-proposers
   ship veterans for youth/picks; outside that window behavior is unchanged
   except outlook-aware candidate pools.
3. `run_cpu_trade_proposal_cycle` early-exits with
   `reason == "past_deadline"` after July 31 (regular season) instead of
   burning save attempts.
4. Human proposals remain blocked Aug 1 → end of playoffs, and become
   ALLOWED in OFFSEASON/PRESEASON (phase-aware window; new behavior,
   deliberate — see Decision D3).
5. Cadence probability doubles in the last 14 days before the deadline.
6. `pytest tests/test_cpu_trade_proposals.py tests/test_cpu_trade_evaluator.py
   tests/test_v53_acceptance.py tests/test_trade_utils.py` green
   (`tests/test_v53_acceptance.py` verified to exist with 4 tests:
   `test_acceptance_cpu_trade_quality_matrix`,
   `test_acceptance_cpu_proposal_cycle_quality_gate`,
   `test_acceptance_prospect_workflow_regression`,
   `test_acceptance_injury_replacement_regression`).

## Decisions (no open choices)

- **D1 — New shared module, not a lift of `finance_ai._resolve_profile`.**
  Create `services/team_outlook.py`. Rationale: finance's profile mixes
  liquidity (`cash_on_hand`/`debt`/`projected_net`) which must not gate
  deadline buy/sell classification, and importing finance_ai would pull
  payroll/contract loads into the per-sim-day trade path. `finance_ai.py` is
  NOT modified. Thresholds are kept numerically aligned with
  `finance_ai._resolve_profile` (0.565 / 0.445) so the two views of a team
  rarely disagree.
- **D2 — Deadline reweighting happens inside the evaluator via a new
  optional `timeline_weight_factor` kwarg**, not by post-hoc score fiddling
  in the proposer. Rationale: `_timeline_value`/`_pick_timeline_bonus`
  already encode buy-veterans-vs-buy-youth per window; amplifying the 0.12
  timeline weight is the smallest change that reweights both players AND
  picks correctly for both proposer and receiver, and the S2-10 auto-resolve
  reuses it for free.
- **D3 — Phase-aware trade window.** `is_past_trade_deadline()` currently
  blocks offseason trading as a side effect. Add
  `is_trade_window_open()` and use it in `save_trade`; window is open in
  PRESEASON/OFFSEASON and open in REGULAR_SEASON/AMATEUR_DRAFT until the
  deadline; closed after the deadline through PLAYOFFS. Rationale: matches
  MLB (offseason trades legal), matches the plan text "hard-block trades
  after deadline **until offseason**", and keeps a single choke-point
  (`save_trade`) for both human and CPU writes.
- **D4 — Deadline proximity windows: 30 days for reweighting, 14 days for
  volume.** Rationale: 30 days ≈ the real July trade month; 14 days matches
  the Command Center "near" band (`league_command_center.py:358`).

## Files to change (verified anchors)

| File | Anchor | Change |
|---|---|---|
| `services/team_outlook.py` | new | `team_outlook(...)` + `games_back(...)` |
| `services/cpu_trade_proposals.py` | 78 (`run_cpu_trade_proposal_cycle`), 191-198 (cadence math), 230-246 (per-team loop), 330 (`_build_best_offer`), 350-393 (candidate pools + value band) | deadline gate, volume shaping, outlook-aware pools |
| `services/cpu_trade_evaluator.py` | 89-100 (signature), 193 (`total_score`) | `timeline_weight_factor` kwarg |
| `utils/trade_utils.py` | 44-51, 99-102 | `is_trade_window_open()`; `save_trade` uses it |
| `services/league_command_center.py` | 336 | replace `date(season_year, 7, 31)` with `trade_deadline_for_year(season_year)` (single source) |
| `tests/test_team_outlook.py` | new | classification tests |
| `tests/test_cpu_trade_proposals.py` | append | deadline-gate + volume tests |
| `tests/test_trade_utils.py` | append | phase-aware window tests |

## Exact implementation

### 1. `services/team_outlook.py` (new)

```python
"""Standings-based competitive outlook shared by trading + callups."""
from __future__ import annotations
from typing import Mapping

__all__ = ["OUTLOOK_CONTEND", "OUTLOOK_BUBBLE", "OUTLOOK_REBUILD",
           "games_back", "team_outlook", "load_outlooks"]

OUTLOOK_CONTEND = "contend"
OUTLOOK_BUBBLE = "bubble"
OUTLOOK_REBUILD = "rebuild"
_MIN_GAMES_FOR_SIGNAL = 20   # before ~3 weeks of games, everyone is a bubble team
_CONTEND_WIN_PCT = 0.565     # aligned with finance_ai._resolve_profile (finance_ai.py:491)
_REBUILD_WIN_PCT = 0.445     # aligned with finance_ai._resolve_profile (finance_ai.py:493)
_CONTEND_GB = 4.0            # within 4 of the division lead == in the race
_REBUILD_GB = 12.0           # 12+ back == out of it

def games_back(team_id: str, *, standings: Mapping[str, Mapping[str, object]],
               teams_by_id: Mapping[str, object]) -> float:
    """GB vs the leader of the team's division (models/team.py:18 `division`).
    Teams with unknown division compare against the overall league leader.
    GB = ((lead_w - w) + (l - lead_l)) / 2, floored at 0.0."""

def team_outlook(team_id: str, *, standings: Mapping[str, Mapping[str, object]],
                 teams_by_id: Mapping[str, object], sim_date: str | None = None) -> str:
    """Classify. Order of rules (first match wins):
    1. games_played (wins+losses) < _MIN_GAMES_FOR_SIGNAL -> OUTLOOK_BUBBLE
    2. win_pct >= _CONTEND_WIN_PCT or games_back <= _CONTEND_GB -> OUTLOOK_CONTEND
    3. win_pct <= _REBUILD_WIN_PCT or games_back >= _REBUILD_GB -> OUTLOOK_REBUILD
    4. else -> OUTLOOK_BUBBLE
    win_pct: wins/(wins+losses) from the normalized standings record
    (utils/standings_utils.normalize_record keys `wins`/`losses`); 0.500 when
    the team is missing from standings. `sim_date` is accepted for signature
    stability (S2-11 passes it) but unused here."""

def load_outlooks(*, data_dir=None) -> dict[str, str]:
    """Convenience: load standings via services.standings_repository.load_standings
    (normalize=True) + teams via utils.team_loader.load_teams, return
    {TEAM_ID_UPPER: outlook} for every team in teams.csv."""
```

Tie handling: with tied records the division leader is whichever sorts first
by `(-wins, losses, team_id)` — deterministic; co-leaders all get GB 0.0 and
classify contend once past the games floor (rule 2).

### 2. `utils/trade_utils.py` — phase-aware window

Add after `is_past_trade_deadline` (line 45):

```python
def _current_phase() -> str:
    try:
        from playbalance.season_manager import SeasonManager
        return SeasonManager().phase.value        # reads season_state.json
    except Exception:
        return "REGULAR_SEASON"                    # fail toward current behavior

def is_trade_window_open() -> bool:
    """Open in PRESEASON/OFFSEASON; open until the deadline in
    REGULAR_SEASON/AMATEUR_DRAFT; closed after it (incl. PLAYOFFS)."""
    phase = _current_phase()
    if phase in {"PRESEASON", "OFFSEASON"}:
        return True
    return not is_past_trade_deadline()
```

Change `save_trade` line 99 from
`if is_past_trade_deadline() and str(trade.status).lower() == "pending":`
to `if not is_trade_window_open() and str(trade.status).lower() == "pending":`
(error message unchanged). This is the single consistency point for human
(`propose_trade`, `counter_trade`) and CPU writes. `accept`/`reject` status
writes are unaffected (they are not `pending`).

### 3. `services/cpu_trade_evaluator.py` — `timeline_weight_factor`

- Signature (line 89): add kwarg `timeline_weight_factor: float = 1.0`.
- Line 193 becomes:
  ```python
  timeline_w = 0.12 * max(0.25, min(3.0, float(timeline_weight_factor)))
  total_score = (0.68 * value_delta) + (0.20 * fit_delta) + (timeline_w * timeline_delta)
  ```
- No other evaluator change. Default 1.0 keeps every existing caller
  (`api/routers/trades.py:408,731`, `_build_best_offer`) byte-identical in
  behavior.

### 4. `services/cpu_trade_proposals.py`

**Module constants** (near line 65):

```python
_DEADLINE_REWEIGHT_DAYS = 30       # timeline reweight window
_DEADLINE_VOLUME_DAYS = 14         # cadence-boost window
_DEADLINE_CADENCE_MULT = 2.0       # daily_chance multiplier in the last 14 days
_DEADLINE_TIMELINE_FACTOR = 1.5    # 0.12 -> 0.18 effective timeline weight
_VETERAN_AGE = 28                  # "veteran" for pool shaping
_YOUTH_AGE = 25                    # "youth" for pool shaping
```

**(a) Hard block** — in `run_cpu_trade_proposal_cycle`, immediately after
`current_date` is parsed (line 124-127), insert:

```python
from utils.trade_utils import trade_deadline_for_year
deadline = trade_deadline_for_year(current_date.year)
if current_date > deadline:
    result["reason"] = "past_deadline"
    result["deadline"] = deadline.isoformat()
    return result
days_to_deadline = (deadline - current_date).days
```

(No phase check needed here: the cycle only runs from `_run_daily_automations`
during REGULAR_SEASON, verified `api/routers/season.py:557,830-836`. The
early-exit replaces today's silent `save_failed` churn.)

**(b) Volume shaping** — at line 192, replace
`cadence_chance = float(cadence_cfg.get("daily_chance", 0.0) or 0.0)` with:

```python
cadence_chance = float(cadence_cfg.get("daily_chance", 0.0) or 0.0)
if 0 <= days_to_deadline <= _DEADLINE_VOLUME_DAYS:
    cadence_chance = min(0.95, cadence_chance * _DEADLINE_CADENCE_MULT)
```

(normal cadence: 0.45 → 0.90 daily inside the window.)

**(c) Outlook plumbing** — before the per-team loop (line 230), compute once:

```python
from services.team_outlook import load_outlooks, OUTLOOK_CONTEND, OUTLOOK_REBUILD
outlooks = load_outlooks(data_dir=resolved_data_dir)   # {} on any failure
```

Pass `outlook=outlooks.get(cpu_team_id, "bubble")` and
`days_to_deadline=days_to_deadline` into `_build_best_offer`.

**(d) `_build_best_offer` changes** (line 330) — add kwargs
`outlook: str = "bubble"`, `days_to_deadline: int = 999`. Then:

1. Add module helper `_player_age(player)` (copy of
   `cpu_trade_evaluator._player_age`, lines 873-882 — 12 lines; duplicating
   beats importing a private).
2. **Pool shaping**, replacing the flat pools at lines 350-354 / 370-374,
   active only when `0 <= days_to_deadline <= _DEADLINE_REWEIGHT_DAYS` and
   `outlook != "bubble"`:
   - `outlook == OUTLOOK_CONTEND` (buyer): `send_candidates` = own ACT
     sorted ascending by trade value **with players aged <= _YOUTH_AGE
     ordered first** (sort key `(0 if age<=25 else 1, value)`), still `[:10]`;
     `request_candidates` = target ACT filtered to `age >= _VETERAN_AGE`
     sorted by value desc `[:14]` (fall back to unfiltered when the filter
     leaves < 3 names). Value band loosens upward: replace the two band
     checks (lines 391-393) with `0.82 <= ratio <= 1.35` where
     `ratio = owner_value / cpu_value` (buyers overpay).
   - `outlook == OUTLOOK_REBUILD` (seller): `send_candidates` = own ACT
     filtered to `age >= _VETERAN_AGE` sorted by value **desc** `[:10]`
     (sellers shop their best vets, not their scraps; fall back unfiltered
     when < 3); `request_candidates` = target ACT filtered to
     `age <= _YOUTH_AGE` sorted by value desc `[:14]` (fall back
     unfiltered when < 3). Band loosens downward: `0.70 <= ratio <= 1.22`
     (sellers take 70 cents on the dollar for youth).
   - Outside the window or `bubble`: pools and band exactly as today
     (0.82-1.22).
3. **Evaluation reweight** — the `evaluate_cpu_trade_offer` call at line 413
   gains `timeline_weight_factor=factor` where
   `factor = _DEADLINE_TIMELINE_FACTOR if (0 <= days_to_deadline <= _DEADLINE_REWEIGHT_DAYS and outlook in {OUTLOOK_CONTEND, OUTLOOK_REBUILD}) else 1.0`.
   Note the eval trade is oriented `to_team=cpu_team_id` (self-evaluation,
   lines 406-412), and the evaluator resolves the CPU team's own window from
   standings — so ×1.5 timeline amplifies "veterans now" for contenders and
   "youth/picks" for rebuilders symmetrically. This is the exact scoring
   adjustment: effective weights become `0.68 / 0.20 / 0.18` inside 30 days.

**(e) result payload** — add `result["days_to_deadline"] = days_to_deadline`
and per-offer `"proposer_outlook": outlook` (in the dict at line 309) for the
season-log audit.

### 5. `services/league_command_center.py:336`

`trade_deadline = trade_deadline_for_year(season_year)` (import from
`utils.trade_utils`). Pure de-duplication; card output identical.

## Edge cases

- **No standings yet / all 0-0** (opening week): `games_played < 20` →
  everyone `bubble` → behavior identical to today. Forced by design.
- **Tied standings**: deterministic leader sort (see §1); co-leaders GB 0.0.
- **Deadline day itself** (`days_to_deadline == 0`): window open, reweight +
  volume boost active; `current_date > deadline` is strictly-after, matching
  `is_past_trade_deadline`'s `>` (trade_utils.py:45).
- **AMATEUR_DRAFT pause** (mid-July): `is_trade_window_open()` treats it like
  regular season (pre-deadline open) — the draft intercept happens ~3rd
  Tuesday of July (season.py:272-273), before the 31st.
- **Mid-playoffs**: cycle never runs (phase gate); human `save_trade` blocked
  by window (unchanged from today).
- **Missing `age`/birthdate**: `_player_age` returns None → player passes no
  age filter; fall-back-to-unfiltered rule prevents empty pools.
- **Leagues with picks disabled**: untouched — this spec never adds picks to
  proposals (that stays S2-10/evaluator territory).

## Test plan

Commands:
`pytest tests/test_team_outlook.py tests/test_cpu_trade_proposals.py tests/test_trade_utils.py tests/test_cpu_trade_evaluator.py tests/test_v53_acceptance.py -q`

New tests (forced-standings scenarios use injected `standings=` dicts —
`team_outlook` takes mappings, no disk):

- `tests/test_team_outlook.py::test_outlook_contender_by_win_pct` — 40-20
  team (.667) → contend.
- `tests/test_team_outlook.py::test_outlook_contender_by_games_back` — .520
  team 2.0 GB behind a .560 division leader → contend.
- `tests/test_team_outlook.py::test_outlook_rebuild_by_games_back` — .480
  team 14 GB back → rebuild.
- `tests/test_team_outlook.py::test_outlook_bubble_early_season` — 8-6 team
  (.571, over threshold) but < 20 games → bubble.
- `tests/test_team_outlook.py::test_outlook_tied_division_leaders` — two
  teams tied on top → both contend, GB 0.0.
- `tests/test_cpu_trade_proposals.py::test_cycle_blocks_after_deadline` —
  `simulated_dates=["2026-08-02"]` (monkeypatch settings/teams as existing
  tests do) → `reason == "past_deadline"`, `offers_created == 0`.
- `tests/test_cpu_trade_proposals.py::test_cycle_allows_on_deadline_day` —
  `["2026-07-31"]` → reason "ok".
- `tests/test_cpu_trade_proposals.py::test_deadline_volume_boost` —
  monkeypatch `_window_probability` capture: with date 2026-07-25 the chance
  passed in is `min(0.95, 0.45*2.0)`.
- `tests/test_cpu_trade_proposals.py::test_contender_requests_veterans` —
  forced outlooks (`monkeypatch services.cpu_trade_proposals.load_outlooks`),
  target roster of 3 vets (age 30) + 3 kids (age 22): saved offer's
  `receive_player_ids[0]` is a vet.
- `tests/test_cpu_trade_proposals.py::test_rebuilder_ships_veterans_for_youth`
  — mirror case: give side is a vet, receive side age <= 25.
- `tests/test_cpu_trade_evaluator.py::test_timeline_weight_factor_scales_score`
  — same trade evaluated with factor 1.0 vs 1.5: `total_score` differs by
  exactly `0.06 * timeline_delta`.
- `tests/test_trade_utils.py::test_window_open_in_offseason` /
  `test_window_closed_in_playoffs_past_deadline` — monkeypatch
  `utils.trade_utils._current_phase` + `_today`.

Existing suites that must stay green (all verified present):
`tests/test_cpu_trade_proposals.py` (4 tests — note they monkeypatch
`save_trade` and use April dates, unaffected),
`tests/test_cpu_trade_evaluator.py`, `tests/test_v53_acceptance.py`,
`tests/test_trade_utils.py` (7 uses of `TRADE_DEADLINE` ± timedelta — they
patch `_today`, and `is_trade_window_open` must be exercised through the
patched `_today`, so keep `_current_phase` defaulting to REGULAR_SEASON in
tests via monkeypatch where phase files are absent — add
`monkeypatch.setattr("utils.trade_utils._current_phase", lambda: "REGULAR_SEASON")`
to a shared fixture if `season_state.json` leakage appears).

Season-log audit (manual gate from the truth doc): sim May→August on a dev
league, then inspect `result["automations"]["cpu_trades"]` payloads /
`trades_pending.csv`: buyer teams' `receive_player_ids` skew age 28+, seller
teams' skew ≤ 25, zero offers dated after 07-31.

## Non-goals

- CPU→CPU trades (S2-10). Multi-player/pick-package proposal construction.
- Changing evaluator thresholds (`_window_threshold`) or the ±0.22 decision
  variation. Waiver trades / August waiver system. Deadline-date
  configurability per league (stays fixed July 31). Touching
  `finance_ai.py`.
