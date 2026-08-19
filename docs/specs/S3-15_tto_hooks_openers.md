# S3-15 — TTO-Quality Hooks + Openers (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 Manager-depth track. Builds on S2-07 (times-through-
> order batter bonus) which already computes TTO.

## Objective

Two bullpen-management refinements:
1. **TTO-aware hooks.** The pitcher-hook logic (`engine.py:565-621`,
   `_should_hook_pitcher`) currently pulls on runs/hits/pitch-count. It has an
   "unconditional TTO≥3 hook term" (per the plan) — pull weight should scale with
   how many times through the order the starter is, especially for weaker arms,
   rather than a flat term.
2. **Openers.** A weak 5th starter should be usable as an **opener** (1-2 innings)
   followed by a bulk reliever — a real modern pattern the sim never produces.

## Verified current state

- `engine.py:565` `_hook_aggression(score_diff, postseason, tuning)`.
- `engine.py:575` `_should_hook_pitcher(...)` accumulates a `hook_score` from
  `hook_runs_allowed` (5.5), `hook_hits_allowed` (8.0), pitch count, etc.
- TTO is available via S2-07's `_batter_context` (`tto`) and the usage state; the
  starter's times-through-order is derivable from batters faced / lineup slot.
- Rotation / role assignment: `PitcherRecoveryTracker.assign_starter` +
  `_apply_bullpen_usage_order`; "opener" is not a modeled role.

## Acceptance criteria

1. `_should_hook_pitcher` gains a **TTO term** that raises hook probability as
   the starter enters his 3rd time through, scaled by the pitcher's quality
   (weaker starters get pulled earlier on the 3rd pass; aces go deeper).
2. An **opener** role: a designated weak-5th-starter is scheduled to face ~1-2
   innings, then a pre-assigned bulk reliever finishes — modeled without
   breaking the reliever-rest table (S2-03) or the usage KPIs (S2-12).
3. KPI gates hold: avg pitches/start, TTO-3 exposure, and reliever appearances
   stay within the S2-12 usage bands (`--strict`, seeds 1 & 2); 3rd-time-through
   OPS-against for starters trends down vs today.

## Decisions (no open choices)

- **D1 — TTO term is quality-scaled.** `hook_score += tto_hook_weight *
  max(0, tto - tto_hook_start) * (1 + quality_penalty(pitcher))` where
  `tto_hook_start` ≈ 2 and weaker starters (low control/movement/endurance) get a
  larger penalty. New knobs `tto_hook_weight`, `tto_hook_start`.
- **D2 — Opener is a scheduled 2-arm plan, not mid-game emergence.** When a
  team's 5th starter is below an "opener threshold", the rotation entry becomes
  `(opener_reliever, bulk_reliever)`: the opener pitches to a batter/inning cap,
  then the bulk arm takes over as the de-facto starter for rest/stat purposes.
  Gate behind a config flag `openers_enabled` (default on) + `opener_quality_max`.
- **D3 — Rest accounting.** The opener counts as a short reliever outing
  (`reliever_rest_days` table); the bulk arm counts as a start-length outing.
  Reuse the S2-03 table so nothing double-rests.

## Files to change

| File | Change |
|---|---|
| `physics_sim/engine.py` | TTO hook term in `_should_hook_pitcher`; opener/bulk two-arm handling in the starter-assignment + first-inning path. |
| `physics_sim/config.py` | `tto_hook_weight`, `tto_hook_start`, `openers_enabled`, `opener_quality_max`, opener inning/batter cap. |
| `utils/pitcher_recovery.py` / rotation | Opener + bulk scheduling; rest attribution. |
| `scripts/physics_sim_season_kpis.py` | Confirm usage bands; add starter-3rd-TTO OPS-against metric. |
| `tests/test_tto_hooks_openers.py` (new) | Weak starter pulled earlier on TTO-3; ace goes deeper; opener→bulk plan executes with correct rest. |

## Verification gate

- Unit tests above. KPI `--strict` green seeds 1 & 2 incl. S2-12 usage gates and
  the new starter-TTO metric.

## Non-goals

- Full leverage-index bullpen optimization. Piggyback/tandem starts beyond the
  opener pattern. Platoon-based mid-PA pitching changes. Postseason-specific
  bullpen usage.
