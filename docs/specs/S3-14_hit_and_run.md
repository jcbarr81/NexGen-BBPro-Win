# S3-14 — Hit-and-Run (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 Manager-depth track. Pairs with `S3-13_team_strategy.md`
> (supplies the `hit_and_run_mult`).

## Objective

Hit-and-run does not exist in `physics_sim` (grep: no `hit_and_run`). Add it as a
pre-pitch offensive decision alongside the existing bunt/steal decisions: with a
runner on first (and often a contact hitter + favorable count), the runner goes
and the batter is required to swing/protect — trading a swing-through risk
(runner exposed to a caught-stealing/DP-avoidance) for staying out of the double
play and advancing extra bases on a hit.

## Verified current state

- Steal decision at `engine.py:1886-1931`; sac-bunt/squeeze decisions elsewhere
  in the plate-appearance loop (search `bunt`) — these are the sibling pre-pitch
  decisions the H&R sits next to.
- Batter contact rating (`ch`) and count are already available at the decision
  site.
- No hit-and-run knobs in `config.py`.

## Acceptance criteria

1. A pre-pitch **hit-and-run** decision fires with a runner on 1st (empty 2nd),
   gated by count (e.g. 1-0/2-1 hitter's counts), batter contact, outs < 2, and
   the offense's `hit_and_run_mult` (S3-13).
2. On a hit-and-run: the runner is sent (steal attempt semantics) **and** the
   batter's outcome is nudged toward contact / away from the double play:
   - Swing-and-miss or called strike → runner is exposed (elevated CS).
   - Ground ball → runner already going avoids the standard 6-4-3 DP; more
     first-to-third / extra bases on singles.
3. New KPIs / sanity: hit-and-run attempts per game land in a realistic low band
   (~0.2-0.5/game); GIDP rate does not spike; league SB/CS bands hold
   (`--strict`, seeds 1 & 2).

## Decisions (no open choices)

- **D1 — Reuse the steal machinery for the runner.** The runner's send/out uses
  the existing steal-success model; H&R just raises the send probability and, on
  a whiff, applies the higher CS the runner-in-motion incurs.
- **D2 — Batter effect is a modifier, not a new outcome path.** On a hit-and-run
  pitch, apply a small contact-up / whiff-slightly-up adjustment and a
  **GIDP-avoidance** factor (runner in motion → fewer force DPs, more
  fielder's-choice/advance). Keep it a modifier on the existing batted-ball
  resolution.
- **D3 — Config knobs:** `hit_and_run_base_rate`, count gates,
  `hit_and_run_gidp_avoid`, `hit_and_run_contact_bonus`,
  `hit_and_run_whiff_penalty`, `hit_and_run_runner_cs_bonus`.

## Files to change

| File | Change |
|---|---|
| `physics_sim/engine.py` | `_should_hit_and_run(...)` pre-pitch decision; on-play handling (runner send + batter modifiers + DP avoidance). |
| `physics_sim/config.py` | H&R knobs (above). |
| `scripts/physics_sim_season_kpis.py` | H&R attempts/game sanity; confirm GIDP + SB/CS bands. |
| `tests/test_hit_and_run.py` (new) | Decision fires on a favorable count/runner-on-1st; whiff exposes the runner; grounder avoids the DP; disabled by mult 0. |

## Verification gate

- Unit tests above. KPI `--strict` green seeds 1 & 2 — GIDP and SB/CS league
  bands unchanged; H&R attempt rate in the realistic band.

## Non-goals

- Run-and-hit vs hit-and-run distinction. Fake bunt / slash. Defensive
  counter-strategies (pitchouts already exist in the legacy config; not required
  here). Manager tendencies beyond the S3-13 multiplier.
