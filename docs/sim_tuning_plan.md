# Simulation Realism Recovery Task List

> **⚠️ Historical — superseded 2026-07-13.** This plan targets the legacy
> `playbalance/` engine, which is now **archived** (games run on `physics_sim/`;
> the legacy engine only runs behind `PB_ALLOW_LEGACY_ENGINE=1`). The headline
> problem here — walks far below MLB — was **solved in `physics_sim`** (BB% ≈
> 0.085, on target, now guarded by the strict KPI CI gate
> `.github/workflows/physics_sim_kpi.yml`). Do **not** action this plan against
> the live engine. The one real remaining sim gap is the disabled empirical
> park-factor multiplier (`park_factor_scale=0.0` in `physics_sim/config.py`).
> Kept for historical context only.

This document tracks the sequencing needed to bring league-wide stats back in line with MLB benchmarks. Each task has explicit acceptance criteria so we can work through the plan step by step.

## 1. Validate And Normalize Player Inputs *(Completed — normalized roster + generator in sync)*
- **Description:** Audit `data/players.csv` (pitcher control/movement, batter contact/discipline/power) and the roster-building helpers to ensure inputs match expected MLB distributions.
- **Acceptance criteria:**
  - A short report (table or markdown) summarizing current rating histograms vs. MLB references.
  - Documented adjustments (either edits to the CSV or transform logic) that bring means/variance within ±10% of MLB.
  - `build_default_game_state` confirmed to pick realistic lineups/rotations after the adjustments.
- **Sub‑tasks:**
  1. Write and check in a reproducible rating-distribution script/notebook under `docs/` that exports histograms for hitter contact/power/speed/discipline and pitcher velocity/control/movement/endurance from `data/players.csv`.
  2. Define and document explicit archetype envelopes (contact/power/balanced hitters; power/finesse/balanced starters, setup, closers, etc.) plus target percentages, ensuring each archetype includes jitter/randomness so players stay unique.
  3. Decide and document the normalization implementation strategy (CSV regeneration vs. loader-time transforms) including how randomness is applied, how the `playbalance.player_generator.generate_player` pipeline will consume the archetype blueprint, and how we will regression-test the results (rerunning the histogram script to verify archetype ratios and means).

## 2. Instrument Swing/Pitch Decisions
- **Description:** Add high-visibility diagnostics to `batter_ai.decide_swing`, `pitcher_ai.select_pitch`, and `GameSimulation` pitch accounting so we can see classification and randomization outcomes.
- **Acceptance criteria:**
  - `playbalance_simulate.py --diag-output` emits JSON including per-count swing rates, penalty factors, pitch objective frequencies, and real vs. simulated pitch totals.
  - `results.json` gains the extra raw counters (balls_thrown, strikes_thrown, fouls, etc.) required to compute swing/K/BB metrics outside the script.
  - Documentation in `docs/` describing how to interpret the new diagnostics.
- **Sub‑tasks:**
  1. **Batter diagnostics:** extend `batter_ai.decide_swing` to log per-count swing chances, discipline adjustments, punch-list referencing pitch class and archetype; gate via config flag and expose aggregated stats through `playbalance_simulate.py --diag-output`.
  2. **Pitcher/objective traces:** add trackers inside `pitcher_ai.select_pitch` (and `GameSimulation`) to record objective weights, pitch selection, and resulting in-zone/out-of-zone counts; ensure `PitcherState` persists real vs injected pitches for later aggregation.
  3. **Results wiring:** add a smoke test that runs a short sim with instrumentation enabled, asserting that the results JSON includes `pitch_counts` and `pitch_objectives`. Keep a doc (see `docs/instrumentation_usage.md`) explaining how to run diagnostics manually.

## 3. Remove Or Rework Phantom Pitch Injection
- **Description:** Disable or redesign the `targetPitchesPerPA` calibration that currently pads plate appearances with synthetic strikes/balls.
- **Acceptance criteria:**
  - Configuration knob (default off) controlling pitch injection, with tests verifying natural pitch counts are recorded when disabled.
  - Updated benchmarks/tests reflecting the new default path.
  - Evidence (mini sim run) showing pitches/PA now comes purely from live pitches.

## 4. Calibrate Strike-Zone Geometry And Pitch Classification
- **Description:** Align `plateWidth`/`plateHeight`, `sureStrikeDist`, `closeStrikeDist`, and `closeBallDist` with actual pitch location distributions from the physics layer.
- **Acceptance criteria:**
  - Histogram of pitch distances for a sample run included in `docs/`.
  - Config tuned so at least 40% of pitches fall into “ball” buckets on average.
  - Regression sim (≥50 games) showing MLB-like zone% (~49%) within ±3%.

## 5. Tune Discipline / Swing Probabilities
- **Description:** Use the instrumentation to target MLB O-Swing, Z-Swing, and total Swing percentages.
- **Acceptance criteria:**
  - For a 50-game orchestrator run: O-Swing 0.32 ±0.03, Z-Swing 0.65 ±0.03, overall swing% 0.47 ±0.03.
  - Two-strike floors documented so that called strikeout share matches 0.23 ±0.03.
  - Auto-take logic verified via diagnostics (forced take counts per situation).

### Step-by-step Solver (discipline/pitch mix nudges)
- **Description:** After implementing the batter/pitcher changes above, run `scripts/auto_tune_playbalance.py` against the latest `results.json` to make small, deterministic adjustments to `swingProbScale`, `z/oSwingProbScale`, `pitchAroundChance*`, and `ballInPlayPitchPct`. This avoids the oversized manual swings that derailed the last tuning loop.
- **Usage:** `python scripts/auto_tune_playbalance.py --results results.json --write` updates `data/playbalance_overrides.json` with the suggested nudges. Omit `--write` to preview the changes.
- **Acceptance criteria:** Script reports adjustments only when metrics drift outside the tolerances above and keeps deltas ≤0.05 for swing scales, ≤5 for `pitchAroundChance*`, and ≤3 for `ballInPlayPitchPct`.

## 6. Restore K% / BB% Balance
- **Description:** After swings are reasonable, adjust miss probabilities, pitcher control variance, and discipline penalties to hit MLB strikeout and walk rates.
- **Acceptance criteria:**
  - 50-game sim yields league K% 0.22 ±0.02 and BB% 0.08 ±0.01.
  - Tests updated (`tests/test_playbalance_orchestrator.py`) to reflect the acceptable tolerance window, all passing.

## 7. Rebalance Contact Quality And BABIP
- **Description:** With plate-discipline fixed, adjust `_swing_result` hit probability scalars and fielding conversion rates to reach MLB BABIP.
- **Acceptance criteria:**
  - League BABIP (from orchestrator run) 0.291 ±0.01.
  - Additional metrics (AVG/SLG) fall within ±0.015 / ±0.02 of MLB references.
  - Defensive efficiency and double-play rates within documented tolerances.

## 8. Validate Secondary Systems (Baserunning, SB%, DP Rates)
- **Description:** Once offense/defense baseline is sound, tune baserunning aggression and steal logic.
- **Acceptance criteria:**
  - SB attempt rate 0.05 ±0.005 and success 0.78 ±0.03 over 50-game sims.
  - Double-play % 0.028 ±0.005 with supporting proof from diagnostics.

## 9. Regression Harness And Documentation
- **Description:** Automate the tuning checkpoints and document the workflow.
- **Acceptance criteria:**
  - Script (or Make target) that runs a deterministic 50-game sim and prints the key KPIs vs benchmarks.
  - `docs/simulation_tuning.md` updated to outline the step-by-step tuning procedure using the instrumentation.
  - CI hook or pre-commit job that fails if KPIs drift outside the accepted windows.
