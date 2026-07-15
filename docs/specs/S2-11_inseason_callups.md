# S2-11 — In-Season Callups + September Expansion (spec)

> Implementation-ready spec, verified against the working tree 2026-07-15.
> Depends on S2-09's `services/team_outlook.py` (outlook classification) —
> land S2-09 first or cherry-pick that module.

## Objective

Prospect promotion runs once per offseason only:
`services/prospect_promotion.py` (docstring lines 1-23: "Runs once per
offseason (called from `LeagueRolloverService` ...)"), and September roster
expansion doesn't exist (`playbalance/season_manager.py:73-79` mentions
August/September only in a phase-ordering comment). Add (1) a monthly
in-season AAA→ACT callup check wired into the sim's post-day automations,
outlook-weighted, protection/option-aware, (2) September 1 ACT expansion
25→28 with a revert at the end of the regular season, (3) transaction-log +
news visibility.

## Verified current state (load-bearing facts)

- **Hook point**: the only recurring in-sim automation site is
  `_run_daily_automations(played_dates)` in `api/routers/season.py:812-856`
  (finance cadence, `run_cpu_trade_proposal_cycle`, DL processing), called
  from `_simulate_n` at line 715 after each request's batch of days.
  `_simulate_n` is phase-gated to `REGULAR_SEASON` (line 557). There is no
  existing monthly cadence primitive — `owner_finance_engine.
  apply_owner_finance_cadence_for_dates(played_dates)` does its own
  date-window logic internally; we mirror that pattern.
- **Eligibility bars** (`services/prospect_promotion.py:42-44,68-92`):
  `AAA_TO_ACT_AGE = 23`, `AAA_TO_ACT_OVR = 65`, `AAA_TO_ACT_BLUECHIP_OVR = 72`;
  `evaluate_promotion(current_level=, age=, overall=)` returns `"ACT"|"AAA"|None`;
  `_player_overall` averages `(arm,control,movement,endurance)` for pitchers
  / `(ch,ph,sp,eye,fa,arm)` for hitters. Injured (DL/IR) players are excluded
  by the roster-level reader (lines 115-118).
- **Protection/options** (`services/prospect_rules.py`):
  `evaluate_roster_move(team_id, player_id, *, from_level, to_level,
  season_id=None, ...) -> ProspectMoveDecision` (line 512) blocks unprotected
  AAA→ACT promotion when rules are enabled (`protection_required`, line 611)
  unless auto-protect applies; `apply_roster_move(...)` (line 687) persists
  auto-protection and burns an option on ACT→AAA/LOW.
  `is_player_protected(team_id, player_id)` (line 408). Note default
  `enabled=False` (line 41) — when disabled every move is allowed
  (`rules_disabled`, line 536).
- **Roster machinery**: `models/roster.py` `Roster.move_player(pid, "aaa",
  "act")` (line 14) and `promote_replacements(target_size=25)` (line 28);
  `utils/roster_loader.py:24` `ACTIVE_ROSTER_SIZE = 25` (used at load time,
  lines 342/484); `services/roster_validation.py:58`
  `DEFAULT_LEVEL_CAPS = {"act": 25, "aaa": 15, "low": 10}` (compliance gate
  consumes it via `_team_roster_compliance_errors`,
  `api/routers/season.py:495-507`); `services/roster_auto_assign.py:32-34`
  `ACTIVE_MAX = 25`, `AAA_MAX = 15`, `LOW_MAX = 10` (used by DL automation's
  `_resolve_destination`, `services/dl_automation.py:62-69`).
- **Injury-replacement demotion machinery**: there is NO reusable standalone
  demotion helper. `services/injury_manager.py` has two inline patterns:
  `_enforce_injury_replacement_eligibility` (line 167, prospect-rules-aware
  promotion reconciliation) and `recover_from_injury`'s ad-hoc "demote the
  last ACT player" (lines 287-292, no rules check, no score). So this spec
  defines `_select_demotion_candidate` fresh (below) rather than pretending
  to reuse one.
- **Hitter-quality score**: `utils/lineup_autofill.py:82-92` `hitter_score` —
  `0.6*(0.5*ch+0.5*ph) + 0.2*sp + 0.2*(0.5*fa+0.5*arm)` (+ strategy bonus).
  It's a closure, not importable; the formula is duplicated below as
  `_hitter_score` (7 lines, acceptable duplication; do NOT refactor
  lineup_autofill in this task).
- **News/transactions**: `utils/news_logger.log_news_event(event, *,
  category=None, team_id=None, file_path=None)`;
  `services/transaction_log.record_transaction(*, action, team_id,
  player_id, player_name=None, from_level=None, to_level=None,
  counterparty=None, details=None, season_date=None, ...)` — the offseason
  promoter already writes both (prospect_promotion.py:199-256); reuse the
  same shapes.
- **Phase transitions**: `SeasonManager.advance_phase`
  (`playbalance/season_manager.py:88-112`) already hosts a
  REGULAR_SEASON-exit hook precedent (rollover fires on PLAYOFFS→OFFSEASON,
  lines 93-111). `_PHASE_AFTER` maps REGULAR_SEASON→PLAYOFFS.

## Acceptance criteria

1. During REGULAR_SEASON sims, on the first sim day of each calendar month a
   callup check runs once per league (idempotent across
   day/week/month/to-playoffs batches and across process restarts).
2. Contenders call up an eligible AAA prospect only into a demonstrated
   big-league hole; rebuilders call up their top eligible prospects
   unconditionally after the trade deadline; bubble teams only promote
   blue-chips (OVR ≥ 72) into holes.
3. Prospect rules are honored: `evaluate_roster_move` gates every promotion,
   `apply_roster_move` persists side effects; a blocked promotion is skipped
   (never forced), demotions burn options through the same pipeline.
4. Full ACT roster → the worst-`_hitter_score` demotable ACT player is sent
   to AAA to open the spot; if no legal demotion exists the callup is
   skipped.
5. From September 1 through the end of REGULAR_SEASON the ACT cap is 28 (a
   September check may fill to 28); on REGULAR_SEASON→PLAYOFFS the cap
   reverts to 25 and over-cap teams are trimmed by the same demotion logic.
6. Every move produces a transaction-log row and a news-feed line.
7. Existing suites green: `tests/test_prospect_promotion.py` (verify name via
   `pytest tests -k "prospect" --collect-only`), `tests/test_prospect_rules.py`,
   `tests/test_v53_acceptance.py` (contains
   `test_acceptance_prospect_workflow_regression` and
   `test_acceptance_injury_replacement_regression`), DL/injury suites.

## Decisions (no open choices)

- **D1 — New service `services/inseason_callups.py`**, hooked from
  `_run_daily_automations`. Rationale: the router function is the one place
  every multi-day sim batch already funnels through; a service module keeps
  it testable without FastAPI.
- **D2 — Month-boundary detection via persisted state**, not "played_dates
  contains a 1st": a batch can jump from Jul 28 to Aug 4 without playing
  Aug 1 (off days), and restarts must not re-run. State file
  `callup_state.json` in the league data dir stores
  `{"leagues": {league_id: {"last_check_month": "2026-07"}}}` (same
  versioned shape as `cpu_trade_proposal_state.json`).
- **D3 — Hole definition**: position P has a hole when the team's best ACT
  `_hitter_score` at P (players whose `primary_position` == P, pitchers
  excluded) is below the **25th percentile** (X = 25) of the league's
  per-team-best scores at P; a position with zero ACT players at it is
  always a hole. Pitching hole: fewer than 11 pitchers on ACT (one under the
  evaluator's 12-pitcher comfort line, `cpu_trade_evaluator.py:397-398`).
  Rationale: percentile-vs-league is roster-size independent and cheap
  (league scan is one pass over `players.csv` + rosters already loaded).
- **D4 — Volume caps**: max **2** promotions per team per monthly check
  (rebuild teams post-deadline), max **1** otherwise; September check may
  promote up to `active_roster_cap - len(act)` (i.e. fill to 28) for every
  team regardless of outlook, still eligibility- and rules-gated.
- **D5 — Cap plumbing**: add `active_roster_cap(sim_date=None) -> int` to
  `utils/roster_loader.py` (next to `ACTIVE_ROSTER_SIZE`) returning
  `SEPTEMBER_ROSTER_SIZE = 28` when the sim date is Sept 1-Dec 31 AND the
  season phase is REGULAR_SEASON, else 25. Consumers changed:
  `api/routers/season.py::_team_roster_compliance_errors` (pass
  `level_caps={**DEFAULT_LEVEL_CAPS, "act": active_roster_cap()}`) and
  `services/dl_automation.py::_resolve_destination` (replace `ACTIVE_MAX`
  with `active_roster_cap()`). `promote_replacements(target_size=...)` calls
  in roster_loader stay at 25 — passive loads must not auto-fill to 28
  (September depth is an active decision, not a side effect of reading a
  CSV). `services/roster_validation.DEFAULT_LEVEL_CAPS` stays 25 (it is the
  default; callers override). CPU teams are exempt from the compliance gate
  anyway (season.py:481-489 — owner team only).
- **D6 — Revert hook in `SeasonManager.advance_phase`**: when
  `previous == REGULAR_SEASON and self.phase == PLAYOFFS`, call
  `services.inseason_callups.revert_september_expansion()` (best-effort
  try/except, mirroring the rollover hook style at lines 99-111).
  Rationale: the only choke-point every league passes through at season end,
  including leagues advanced via the API's advance-phase endpoint.
- **D7 — Demotion selection** (`_select_demotion_candidate`): among ACT
  players excluding (a) pitchers when ACT pitcher count ≤ `MIN_ACTIVE_PITCHERS
  = 6` (roster_loader.py:28) — otherwise pitchers ARE demotable, (b) players
  protected via `is_player_protected`, (c) injured (`player.injured`), (d)
  the team's only catcher, (e) anyone whose `evaluate_roster_move(act→aaa)`
  is not allowed (option limits) — pick the minimum `_hitter_score` (for
  pitchers use `_pitcher_score = mean(arm, control, movement, endurance)`,
  compared on the same 0-99 scale). Return None when the set is empty.

## Files to change (verified anchors)

| File | Anchor | Change |
|---|---|---|
| `services/inseason_callups.py` | new | `run_monthly_callups`, `run_september_expansion`, `revert_september_expansion`, helpers |
| `api/routers/season.py` | 812-856 (`_run_daily_automations`) | add callup hook after the DL block |
| `utils/roster_loader.py` | 24-28 | `SEPTEMBER_ROSTER_SIZE = 28`, `active_roster_cap(sim_date=None)` |
| `api/routers/season.py` | 495-507 | compliance gate uses `active_roster_cap()` |
| `services/dl_automation.py` | 62-69 | `_resolve_destination` uses `active_roster_cap()` |
| `playbalance/season_manager.py` | 88-112 | revert hook on REGULAR_SEASON→PLAYOFFS |
| `tests/test_inseason_callups.py` | new | see Test plan |

## Exact implementation

### 1. `utils/roster_loader.py`

```python
SEPTEMBER_ROSTER_SIZE = 28

def active_roster_cap(sim_date: str | None = None) -> int:
    """25 normally; 28 from Sept 1 while the REGULAR_SEASON is running.
    sim_date: ISO date; defaults to utils.sim_date.get_current_sim_date().
    Phase read via playbalance.season_manager.SeasonManager (lazy import to
    avoid a cycle: season_manager imports nothing from roster_loader —
    verified). Any failure -> 25 (fail toward the strict cap)."""
    try:
        token = sim_date or get_current_sim_date()
        month = int(str(token)[5:7])
        if month >= 9:
            from playbalance.season_manager import SeasonManager, SeasonPhase
            if SeasonManager().phase == SeasonPhase.REGULAR_SEASON:
                return SEPTEMBER_ROSTER_SIZE
    except Exception:
        pass
    return ACTIVE_ROSTER_SIZE
```

### 2. `services/inseason_callups.py` (new)

Public API:

```python
def run_monthly_callups(*, played_dates: Sequence[str], data_dir: Path | None = None,
                        league_id: str | None = None) -> dict:
    """Idempotent monthly check. Returns
    {"applied": bool, "reason": str, "month": "YYYY-MM",
     "promotions": [...], "demotions": [...], "teams_checked": int}."""

def run_september_expansion(*, sim_date: str, data_dir=None) -> dict: ...
def revert_september_expansion(*, data_dir=None) -> dict: ...
```

`run_monthly_callups` flow:

1. `current = played_dates[-1]`; `month_key = current[:7]`. Load
   `callup_state.json`; if `last_check_month == month_key` →
   `{"applied": False, "reason": "already_ran"}`. (First-ever run on a
   mid-month league sets the marker and RUNS — a new league gets its first
   check immediately.)
2. Phase guard: `SeasonManager().phase != REGULAR_SEASON` → reason
   `"phase_blocked"` (defense in depth; `_simulate_n` already gates).
3. Load once: players (`load_players_from_csv(data_dir / "players.csv")`),
   teams (`load_teams(data_dir / "teams.csv")`), standings
   (`load_standings(base_path=data_dir, normalize=True)`), outlooks
   (`services.team_outlook.load_outlooks(data_dir=data_dir)`), rosters per
   team (`load_roster(team_id, data_dir / "rosters")`).
4. Deadline flag: `past_deadline = date.fromisoformat(current) >
   trade_deadline_for_year(int(current[:4]))` (`utils.trade_utils`).
5. League hole table (D3): for each position in
   `("C","1B","2B","3B","SS","LF","CF","RF")` collect every team's best ACT
   `_hitter_score` at that position; 25th percentile via
   `sorted(vals)[max(0, int(0.25 * (len(vals) - 1)))]` (no numpy).
6. Per team (skip teams whose owner is human? **No** — human teams are
   skipped: only CPU-controlled teams get automated callups. CPU set =
   complement of `_load_human_team_ids` exactly as
   `cpu_trade_proposals.py:141-161`; lift that helper into the new module by
   importing it: `from services.cpu_trade_proposals import _load_human_team_ids`
   is private — instead copy the 20-line reader; rationale: owners manage
   their own roster, and auto-moves on human teams would fight the UI):
   - Build eligible list: AAA ids where `evaluate_promotion(
     current_level="AAA", age=calculate_age(birthdate), overall=
     _player_overall(player)) == "ACT"`, excluding injured, sorted by
     `overall` desc. (`_player_overall`, `evaluate_promotion`,
     `calculate_age` imported from `services.prospect_promotion` /
     `playbalance.aging` — all public.)
   - Determine quota + filter by outlook (D4):
     - `contend`: quota 1; candidate must map to a hole — a position
       prospect qualifies if his `primary_position` is a hole position for
       this team; a pitcher qualifies if the team has a pitching hole.
     - `rebuild`: quota `2 if past_deadline else 1`; `past_deadline` →
       no hole requirement (top prospects play); pre-deadline → hole
       requirement like contenders.
     - `bubble`: quota 1; hole requirement AND `overall >=
       AAA_TO_ACT_BLUECHIP_OVR`.
   - For each selected candidate (best overall first, up to quota):
     a. Rules gate: `decision = evaluate_roster_move(team_id, pid,
        from_level="aaa", to_level="act")`; `not decision.allowed` → skip
        (count `blocked_by_rules`).
     b. Space: if `len(roster.act) >= active_roster_cap(current)` →
        `victim = _select_demotion_candidate(...)` (D7); None → skip
        (count `no_roster_space`); else demote: rules-gate the demotion
        (`evaluate_roster_move(act→aaa)` — already checked inside the
        selector), `roster.move_player(victim, "act", "aaa")`,
        `apply_roster_move(team_id, victim, from_level="act",
        to_level="aaa", actor="system", trigger="inseason_callup_demotion")`,
        record transaction (`action="demote"`, levels ACT→AAA, details
        `"Sent down to open a roster spot"`), news line
        `f"{team_id} option {name} to AAA."` category `"demotion"`.
     c. Promote: `roster.move_player(pid, "aaa", "act")`;
        `apply_roster_move(team_id, pid, from_level="aaa", to_level="act",
        decision=decision, actor="system", trigger="inseason_callup")`;
        transaction `action="promote"`, `from_level="AAA"`, `to_level="ACT"`,
        `season_date=current`, details
        `f"Called up ({outlook}{', post-deadline' if ... else ''}, OVR {overall})"`;
        news `f"{team_id} called up to the majors: {pos} {name} (age {age},
        OVR {overall})." ` category `"promotion"` — same voice as
        prospect_promotion.py:214-224.
   - `save_roster(team_id, roster)` once per changed team (mirror
     prospect_promotion.py:190-194).
7. September: if `int(current[5:7]) == 9` (or 10, for leagues whose schedule
   runs long) also call `run_september_expansion(sim_date=current, ...)`
   within the same run: every CPU team fills toward
   `active_roster_cap(current)` (28) with its best remaining eligible AAA
   players (eligibility + rules gates identical; no hole requirement, no
   demotions). Human teams: expansion applies automatically via the
   compliance gate now accepting 28 — owners promote manually.
8. Persist `last_check_month = month_key`; return summary.

`revert_september_expansion` flow: for every team (CPU **and** human —
the 25-cap becomes hard again and playoffs must start legal): while
`len(roster.act) > ACTIVE_ROSTER_SIZE`, demote `_select_demotion_candidate`
picks; if the selector returns None while still over cap, force-demote the
lowest-score non-injured, non-last-catcher ACT player WITHOUT the option
gate (log `trigger="september_revert_forced"` — being stuck over-cap in
playoffs is worse than burning an option irregularity); transaction + news
per move; save.

### 3. `api/routers/season.py::_run_daily_automations` — add after the DL
block (after line 855):

```python
try:
    from services.inseason_callups import run_monthly_callups

    summary["callups"] = run_monthly_callups(
        played_dates=played_dates, data_dir=get_data_dir()
    )
except Exception as exc:  # pragma: no cover - defensive
    summary["callups_error"] = str(exc)
```

### 4. `playbalance/season_manager.py::advance_phase` — after the existing
rollover block (line 111), add:

```python
if previous == SeasonPhase.REGULAR_SEASON and self.phase == SeasonPhase.PLAYOFFS:
    try:
        from services.inseason_callups import revert_september_expansion
        revert_september_expansion()
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("September roster revert failed: %s", exc)
```

## Edge cases

- **No eligible prospects** (thin AAA): team contributes zero moves; summary
  counts `no_candidates`; never promote sub-bar players to fill 28.
- **Tied standings / early season**: outlook = bubble (S2-09 rule 1) →
  blue-chip-only, which is the conservative behavior.
- **Mid-playoffs / offseason**: phase guard returns `phase_blocked`; the
  offseason promoter (`run_yearly_promotions`) remains the only offseason
  mover — no double promotion because the two never run in the same phase.
- **Prospect rules disabled** (default `enabled=False`): every
  `evaluate_roster_move` allows (`rules_disabled`) — checks still called so
  enabling the league setting immediately takes effect.
- **Protection required + auto-protect**: `decision.requires_auto_protect`
  is honored by passing the decision into `apply_roster_move` (it persists
  protection, prospect_rules.py:724-740).
- **Only-catcher demotion**: excluded by D7(d); if the only legal spot-opener
  is the backup catcher and the callup is a catcher, the swap is legal (the
  incoming player restores coverage) — implement the last-catcher check
  against the post-move roster, not the pre-move one.
- **DL returns during September**: `dl_automation._resolve_destination` now
  uses `active_roster_cap()` so returns prefer ACT while expanded.
- **Compliance gate**: owner's team at 26-28 in September passes
  (`_team_roster_compliance_errors` override); on Oct/phase flip the revert
  runs before playoff sims, so the gate never traps a league (revert is also
  idempotent — safe to call twice).
- **Month key across year boundary**: `"YYYY-MM"` string handles it.
- **Batch spanning two months** (e.g. month-sim Jul 15→Aug 14): one check
  runs (for August, keyed off the last played date) — acceptable cadence
  drift; the next batch triggers September normally.

## Test plan

Command: `pytest tests/test_inseason_callups.py tests/test_prospect_rules.py
tests/test_v53_acceptance.py -q` plus the collected prospect-promotion suite.

New tests (`tests/test_inseason_callups.py`; all on `tmp_path` data dirs
with hand-built `players.csv`/rosters, monkeypatching
`SeasonManager` phase and `services.team_outlook.load_outlooks`):

- `test_monthly_hook_fires_once_per_month` — call `run_monthly_callups`
  twice with dates in the same month → second returns
  `reason == "already_ran"`; a date in the next month runs again.
- `test_hook_wired_into_daily_automations` — monkeypatch
  `services.inseason_callups.run_monthly_callups` capture; call
  `api.routers.season._run_daily_automations(["2026-06-01"])`; assert called
  and summary key `"callups"` present.
- `test_contender_promotes_only_into_hole` — contender with a weak SS
  (league percentile forced) + eligible AAA SS (OVR 70, age 24) → promoted;
  same team with strong SS → not promoted.
- `test_rebuilder_promotes_after_deadline_regardless` — rebuild team,
  August date, no holes, two eligible prospects → both promoted (quota 2).
- `test_protection_respected` — prospect rules enabled,
  `require_protection_for_act_promotion=True`, unprotected candidate →
  skipped with `blocked_by_rules`; protected candidate → promoted.
- `test_full_roster_swap` (full-roster swap test) — ACT at 25, eligible
  blue-chip in AAA → worst-score unprotected ACT hitter demoted (assert the
  exact victim id), prospect promoted, roster size still 25, both
  transaction rows written (capture `record_transaction`).
- `test_full_roster_no_legal_demotion_skips` — every ACT player protected →
  callup skipped, `no_roster_space` counted, roster untouched.
- `test_september_expansion_size` (September-expansion size test) —
  `active_roster_cap("2026-09-01")` == 28 in REGULAR_SEASON, 25 in PLAYOFFS
  and on "2026-08-31"; September run fills a CPU team from 25 to 28 with its
  3 best eligible AAA players.
- `test_september_revert_on_phase_advance` — team at 28, call
  `SeasonManager.advance_phase()` from REGULAR_SEASON (phase file seeded) →
  PLAYOFFS and ACT trimmed to 25 via demotions.
- `test_human_teams_untouched` — team present in `users.txt` owner rows →
  zero automated moves.
- `test_compliance_gate_accepts_28_in_september` — monkeypatch sim date to
  Sept; `_team_roster_compliance_errors` on a 27-man legal roster → `[]`.

Season-scale audit (manual gate per truth doc "Roster-churn audit"): sim a
full season on a sandbox league; grep the transaction log for
`action=promote` with `trigger`-style details — expect roughly 1-3
promotions/team/season pre-September plus the September fills; verify
`validate_roster_state` passes for all teams on Oct 1 (post-revert) and
that injury replacement (`tests/test_v53_acceptance.py::
test_acceptance_injury_replacement_regression`) still passes.

## Non-goals

- LOW→AAA in-season moves (offseason promoter keeps that lane).
- Automated moves for human-owned teams (UI remains their tool).
- Service-time / Super-Two economics, 40-man roster or Rule 5 modeling.
- Performance-based (stats-driven) callup triggers — eligibility stays
  ratings-based via `evaluate_promotion` for now.
- Changing `promote_replacements` load-time behavior or AAA/LOW caps.
- September pitcher-usage tuning (S2-03/S2-12 territory).
