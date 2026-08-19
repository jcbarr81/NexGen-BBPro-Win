# S3-13 — Team Strategy Identity In-Game (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 Manager-depth track.

## Objective

Team strategy profiles exist (`services/team_strategy_profiles.py`) but **never
reach the physics engine** — every team runs, bunts, and steals off the same
global tuning. Thread a per-team strategy identity (aggressive/conservative
baserunning, small-ball vs power) into the in-game steal/bunt/hit-and-run
decisions so teams feel distinct.

## Verified current state

- `services/team_strategy_profiles.py` — resolves a strategy profile per team
  (already consumed by CPU trading / prospect rules).
- Steal decision: `physics_sim/engine.py:1886-1931` —
  `_steal_attempt_rate(...)` uses global knobs (`steal_attempt_rate_first`,
  `steal_freq_scale`, `steal_pitcher_arm_deterrent`, …) with **no team term**.
- Bunt: sac-bunt / squeeze logic in the engine (search `bunt`), also global.
- The engine receives per-game context but **not** a per-team strategy
  multiplier today.

## Acceptance criteria

1. Each offense carries a resolved strategy identity into the engine as
   **multipliers**: `steal_freq_mult`, `bunt_freq_mult`, `hit_and_run_mult`
   (H&R lands with S3-14), defaulting to 1.0 (neutral) so unset teams are
   unchanged.
2. `_steal_attempt_rate` and the bunt decision apply the offense's multiplier.
3. Aggressive-baserunning teams attempt visibly more steals; small-ball teams
   bunt more — over a season the per-team SB and SH totals spread out.
4. League-average SB/CS, SH rates stay within the KPI band (`--strict`, seeds
   1 & 2) — this redistributes, not inflates.

## Decisions (no open choices)

- **D1 — Multipliers, not new decision logic.** Map the strategy profile to a
  small set of multipliers (a pure function `strategy_to_multipliers(profile) ->
  {steal, bunt, hit_and_run}`), applied on top of the existing rate math.
  Neutral profile = all 1.0.
- **D2 — Plumb via per-game context.** The batting team's multipliers ride the
  same per-game context dict the engine already builds (keyed by offense team),
  resolved once per game from `team_strategy_profiles`. No new global state.
- **D3 — Bounded.** Clamp each multiplier to a sane band (e.g. [0.5, 1.75]) so a
  profile can't produce cartoonish rates.

## Files to change

| File | Change |
|---|---|
| `services/team_strategy_profiles.py` | `strategy_to_multipliers(profile)` helper (or reuse an existing mapping). |
| `physics_sim/engine.py` | Resolve the batting team's multipliers per game; apply in `_steal_attempt_rate` and the bunt decision. |
| `physics_sim/config.py` | Multiplier clamp bounds if configurable. |
| `scripts/physics_sim_season_kpis.py` | (Optional) per-team SB/SH spread sanity metric. |
| `tests/test_team_strategy_ingame.py` (new) | Aggressive profile → higher steal rate than neutral on identical inputs; neutral = unchanged. |

## Verification gate

- Unit test (aggressive > neutral > conservative steal rate). KPI `--strict`
  green seeds 1 & 2 — league SB/CS/SH means unchanged, per-team spread up.

## Non-goals

- Defensive shifts / positioning identity. Lineup-construction identity (that's
  the autofill/strategy elsewhere). Manager "personality" beyond these
  multipliers. Hit-and-run itself (S3-14 adds the mechanic; this only carries its
  multiplier).
