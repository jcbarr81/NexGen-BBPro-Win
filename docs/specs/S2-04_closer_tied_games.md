# S2-04 — Closer usage in tied games (9th inning and extras)

Status: spec ready for implementation. Zero open decisions.
Plan reference: `docs/deep_review_plan.md` line 188 (task S2-04). Plan cites
`engine.py:691-698` / `_reliever_score:636-637`; current verified anchors are
`_select_reliever` CL filter at engine.py:698-705 and the not-ahead penalty at
engine.py:642-644 (code drifted a few lines since the review).

## Objective

`_select_reliever` (physics_sim/engine.py:682-734) drops the CL from candidates unless
`leverage == "high" and score_diff > 0`, and `_reliever_score` (engine.py:622-657) hits
CL/SU with a flat −6.0 whenever the team is not ahead in high leverage. Result: tied 9th
innings and extra innings are pitched by whoever is left, never the closer. Real managers
use the closer in a tied 9th at home (no save chance ever materializes for the home team
in a walkoff-able inning) and in extras on both sides. Allow it, keep save-situation
priority untouched.

## Home/away at selection time (verified)

The engine knows it: `play_half_inning` (engine.py:3391) sets `defense_team = "home"`
(line 3411) or `"away"` (line 3415). It is in scope at both in-inning selection sites
(the 9th-inning entry block at 3444-3514 and the hook path at 5103-5119). The overuse
injury path receives it as the `team` parameter (`_maybe_pitcher_overuse_injury`, call at
engine.py:5085-5101 passes `team=defense_team`; used at 2933). `_select_reliever` itself
gets a new keyword argument (below).

## Exact implementation

### 1. `_select_reliever` (engine.py:682-734)

New signature (add one keyword-only param, default False so existing tests/callers keep
working):

```python
def _select_reliever(
    team_state: TeamPitchingState,
    leverage: str,
    *,
    inning: int,
    score_diff: int,
    is_home_defense: bool = False,
    upcoming_batters: List[BatterRatings] | None = None,
    tuning: TuningConfig | None = None,
) -> PitcherState:
```

Replace the body between the empty-candidates guard (lines 696-697) and the `score`
closure (line 727) with:

```python
    closer_inning = int((tuning.get("closer_inning_min", 9.0) if tuning else 9.0))
    tied_road_inning = int(
        (tuning.get("closer_tied_road_inning_min", 10.0) if tuning else 10.0)
    )
    save_chance = leverage == "high" and score_diff > 0
    tied_closer_ok = (
        score_diff == 0
        and inning >= closer_inning
        and (is_home_defense or inning >= tied_road_inning)
    )
    if not (save_chance or tied_closer_ok):
        non_cl = [
            pitcher
            for pitcher in candidates
            if (pitcher.staff_role or "").upper() != "CL"
        ]
        if non_cl:
            candidates = non_cl
    if save_chance or tied_closer_ok:
        closers: list[PitcherState] = []
        if inning >= closer_inning:
            closers = [
                pitcher
                for pitcher in candidates
                if (pitcher.staff_role or "").upper() == "CL"
            ]
            if closers:
                candidates = closers
        if not closers and save_chance:
            setup = [
                pitcher
                for pitcher in candidates
                if (pitcher.staff_role or "").upper() == "SU"
            ]
            if setup:
                candidates = setup
```

Semantics (each decided, with rationale):
- **Tied, inning >= 9, home defense → CL eligible and prioritized.** Home team can never
  earn a save from a tie; holding the closer is strictly worse.
- **Tied, inning 9, away defense → CL still held** (SU preferred): the road team can take
  a lead in the top of a later inning and hand the closer a save — the classic
  hold-your-closer-on-the-road pattern. Knob `closer_tied_road_inning_min = 10.0` lifts
  the hold once extras start (both sides use the CL in extras; bullpen is emptying).
- **Extra innings (>= 10) tied → CL eligible for both sides** (subsumed by
  `inning >= tied_road_inning`).
- **Save-situation priority unchanged:** the `save_chance` branch is byte-for-byte the old
  `leverage == "high" and score_diff > 0` behavior including the SU fallback; the SU
  fallback is intentionally NOT extended to `tied_closer_ok` (when tied and the CL is
  unavailable, scoring — below — already prefers SU without a hard filter).

### 2. `_reliever_score` (engine.py:622-657)

Replace the high-leverage not-ahead branch (lines 642-644):

```python
        else:
            if role in {"CL", "SU"}:
                score -= 6.0
```

with:

```python
        elif score_diff == 0:
            if role == "SU":
                score += 4.0
            elif role == "MR":
                score += 1.0
            # CL: 0.0 — no penalty when tied (eligibility is gated in
            # _select_reliever; when the CL is allowed in, don't handicap him)
        else:
            if role == "CL":
                score -= 6.0
            elif role == "SU":
                score -= 2.0
```

Exact new penalty values and rationale:
- **Tied: CL 0.0** (was −6.0) — the tie is exactly when a fresh CL should be usable; the
  hard eligibility gate in `_select_reliever` already prevents premature/road-9th use.
- **Tied: SU +4.0** (was −6.0) — the setup man is the default tied-game high-leverage arm
  (8th tied, 9th tied on the road); +4 beats MR's +1 for equal stuff but loses to a
  CL-only candidate pool when the gate filters to closers.
- **Behind: CL −6.0 unchanged** — never burn the closer down a run.
- **Behind: SU −2.0** (was −6.0) — setup men routinely pitch high-leverage 8th/9th down
  1; −6 pushed those innings to MRs (+2 in mid leverage) and long men.
- No leverage-type changes: `_leverage_type` (engine.py:737-747) already classifies tied
  innings >= 8 as "high" (`abs(0) <= close_game_run_diff` and `inning >= 8`).

### 3. 9th-inning proactive closer entry (engine.py:3444-3514)

The block currently triggers only when `lead > 0` and a save opportunity exists. Extend it
to bring the closer in at the start of a tied half-inning the defense is allowed to use
him in. Replace lines 3444-3454 header logic:

```python
        if inning >= 9:
            lead = defense_score - offense_score
            save_opp = False
            if lead > 0:
                save_opp = _save_opportunity(
                    lead=lead, inning=inning, bases=bases, tuning=tuning
                )
            closer_inning = int(tuning.get("closer_inning_min", 9.0))
            tied_road_inning = int(tuning.get("closer_tied_road_inning_min", 10.0))
            tied_entry = (
                lead == 0
                and inning >= closer_inning
                and (defense_team == "home" or inning >= tied_road_inning)
            )
            current_role = (pitching_state.current.staff_role or "").upper()
            if (save_opp or tied_entry) and current_role != "CL":
                ...existing body (3455-3514) unchanged...
```

Inside the existing body, `leverage = _leverage_type(inning, lead, tuning)` (line 3459)
already returns "high" for `lead == 0, inning >= 9`; `_reliever_score(candidate, leverage,
score_diff=lead)` with `lead == 0` now scores the CL fairly (change #2). The
`_select_reliever` fallback call at 3484-3491 gains
`is_home_defense=(defense_team == "home")`.
Save accounting is untouched: `_save_opportunity(lead=0)` is False (engine.py:787), so
`_pitcher_enter_stats` (engine.py:849-853) records no `svo`, and the end-of-game
`award_save` path (engine.py:5218-5238) is unreachable from a tie at entry — the S2-04
KPI "saves distribution unchanged" holds by construction for tied entries.

### 4. Call sites of `_select_reliever` (all three, verified by grep)

- engine.py:5112 (hook path): add `is_home_defense=(defense_team == "home")` —
  `defense_team` is in scope (set at 3411/3415); note `score_diff` here is
  `pitching_score - batting_score` (line 5082), defense perspective, correct as-is.
- engine.py:3484 (9th-inning entry fallback): add
  `is_home_defense=(defense_team == "home")`.
- engine.py:2933 (inside `_maybe_pitcher_overuse_injury`): add
  `is_home_defense=(team == "home")` — `team` is the defense team (passed as
  `team=defense_team` at engine.py:5098).

### 5. Config knob (physics_sim/config.py, insert next to `"closer_inning_min"` at line 464)

- ADD `"closer_tied_road_inning_min": 10.0`.
- `"closer_inning_min": 9.0` unchanged (now also gates tied-game entry).

## Postseason 8th-inning fireman — DECIDED: explicit non-goal

`simulate_game` has a `postseason: bool = False` parameter (engine.py:3185) consumed by
`_hook_aggression`/`_usage_multiplier`, but **no production caller ever sets it**:
grep over `playbalance/game_runner.py`, `playbalance/season_simulator.py`, and
`scripts/physics_sim_season_kpis.py` shows zero `postseason` references — playoff games
run with `postseason=False`. A fireman rule keyed on a flag that is never true would be
dead code. Non-goal here; it belongs to the task that wires playoff context from
`services`/season runner into `simulate_game` (log as a follow-up plan row when S2-04
lands).

## Acceptance criteria

1. Forced-scenario unit tests below pass.
2. Full-season KPI (S2-12 harness, `scripts/physics_sim_season_kpis.py`): league save
   totals within ±5% of pre-change baseline (saves distribution unchanged), and CL
   game-log spot check shows CL appearances in tied 9th/extras for home teams.
3. No regression in `tests/test_physics_season_smoke.py`.

## Test plan (new file `tests/test_closer_tied_games.py`)

Helpers: build `PitcherState` objects directly (`physics_sim.engine.PitcherState`,
fields at engine.py:81-96) with `staff_role` in {"CL","SU","MR","LR"}, identical ratings
except role, wrap in `TeamPitchingState(starter=..., bullpen=[...], current=starter)`
(engine.py:209-216), and call `_select_reliever` with `tuning=load_tuning()`.

- `test_closer_selected_tied_ninth_home` — inning=9, score_diff=0,
  is_home_defense=True → returned state has `staff_role == "CL"`.
- `test_setup_selected_tied_ninth_away` — inning=9, score_diff=0,
  is_home_defense=False → `staff_role == "SU"` (CL filtered; SU +4 beats MR +1).
- `test_closer_selected_tied_extras_away` — inning=10, score_diff=0,
  is_home_defense=False → `staff_role == "CL"`.
- `test_closer_never_selected_in_blowout` — for score_diff in (5, -5), inning in (7, 9),
  both home/away → returned `staff_role != "CL"` (leverage from `_leverage_type` — mid;
  CL filtered and penalized −4).
- `test_save_situation_priority_unchanged` — inning=9, score_diff=2,
  is_home_defense=False → `staff_role == "CL"`; and with the CL marked
  `available=False`, → `staff_role == "SU"` (SU fallback intact).
- `test_reliever_score_tied_values` — direct `_reliever_score` asserts: high leverage,
  score_diff=0 → CL score equals base `stuff*1.1 + endurance*0.1` (no penalty), SU gets
  +4.0; score_diff=-1 → CL −6.0, SU −2.0.
- `test_tied_ninth_entry_block_brings_in_closer` — integration-lite: run
  `simulate_game` with a seeded 2-pitcher-per-side staff is NOT deterministic enough;
  instead unit-test the extracted condition by calling `_select_reliever` through the
  3484 path shape: construct pitching_state with a non-CL `current`, assert the tied_entry
  predicate `(lead==0 and inning>=9 and (home or inning>=10))` for the four
  (lead, inning, side) combos: (0,9,home)=True, (0,9,away)=False, (0,10,away)=True,
  (1,9,away)=False-with-save_opp-True.

Commands:
```
python -m pytest tests/test_closer_tied_games.py -q
python -m pytest tests/test_physics_season_smoke.py -q
```

## Edge cases

- **Walkoff exposure (home tied 9th, top half):** intended — that IS the use case; the CL
  entering the top of the 9th tied at home may later pitch the 10th (fatigue rules from
  S2-03 apply; `used` flag keeps him in `team_state.current`, not re-selected).
- **CL already used earlier:** `not pitcher.used` filter (engine.py:694) removes him; the
  candidate pool falls through to SU/MR by score — no crash, no special case.
- **CL unavailable (rest/injury):** tied_entry block's `available_closers` /
  `closer_candidates` lists (engine.py:3466-3482) go empty → `_select_reliever` fallback;
  with `tied_closer_ok` true but no CL in `candidates`, max-score picks SU (+4).
- **Extra-innings ghost runner** (engine.py:3435-3442, `extra_innings_runner` knob): the
  ghost is placed after the tied_entry block runs at half-inning start with empty bases —
  `_save_opportunity(lead=0)` unaffected; no interaction.
- **Both `save_opp` and `tied_entry` false in extras when defense trails:** defense behind
  in a half-inning of extras (walkoff loss pending) → CL correctly filtered (score_diff <
  0); no change.
- **max_innings tie (engine.py:5170-5172):** game can end tied; no save awarded — already
  handled by `score_home != score_away` guard at 5181.

## Non-goals

- Postseason 8th-inning fireman (see decision above — flag never set by callers).
- Multi-inning closer outings / closer usage in the 8th with a lead (existing
  `closer_inning_min` behavior retained).
- Warmup modeling, legacy engine (`playbalance/substitution_manager.py` already handles
  tied-9th CL via its own path — tests at `tests/test_bullpen_role_selection.py:55-71`).
- Retuning of `bullpen_platoon_weight` or leverage thresholds.
