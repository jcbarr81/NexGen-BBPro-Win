# S3-16 — Intentional-Walk Depth (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 Manager-depth track. Small, self-contained.

## Objective

Intentional walks are decided by a coarse rule (`engine.py:2703`
`_should_intentional_walk`, gated only by inning + close run-diff). Add the two
judgments real managers make: **compare the current batter to the on-deck
hitter** (only IBB when the next guy is meaningfully weaker) and the **base/out
force logic** (late-inning, base open, set up the double play or dodge a slugger
with first base open).

## Verified current state

- `engine.py:2703` `_should_intentional_walk(...)`:
  ```python
  if inning < int(tuning.get("ibb_inning", 7.0)): ...
  close_diff = tuning.get("ibb_close_run_diff", 2.0)
  ```
  No on-deck comparison, no base-state / force awareness.
- The on-deck hitter (next lineup slot) and the base state are both available at
  the decision site (the PA loop knows the lineup index + `BaseState`).
- Batter quality is available via ratings (`ch`/`ph`) or a value helper.

## Acceptance criteria

1. IBB only fires when **first base is open** (never with the bases loaded; rare
   with a runner on 1st) — enforce the base-state precondition.
2. IBB fires when the **current batter is meaningfully stronger than the on-deck
   hitter** (a quality gap threshold), in a late/close context — walking a
   slugger to face a weaker bat.
3. Bottom-of-the-order / pitcher-spot cases handled (don't IBB to bring up a
   pinch-hit opportunity you'd regret; keep it simple: only IBB when on-deck is
   the weaker option).
4. League IBB rate lands in a realistic low band (~0.2-0.4/game); no regression
   in runs/game (`--strict`, seeds 1 & 2).

## Decisions (no open choices)

- **D1 — Base-state precondition first.** Require first base open (2nd and/or 3rd
  may be occupied for the classic "open base, set up the force/DP") and outs
  context (typically 1-2 outs). No IBB with the bases loaded.
- **D2 — On-deck quality gap.** IBB only when `value(current) - value(on_deck) >=
  ibb_ondeck_gap` (new knob), so you're trading a strong bat for a weak one.
  Reuse the batter-value helper the engine already uses (or `0.55*ch + 0.45*ph`).
- **D3 — Keep the inning/close gate** (`ibb_inning`, `ibb_close_run_diff`) as the
  outer context; the new checks are additional necessary conditions.

## Files to change

| File | Change |
|---|---|
| `physics_sim/engine.py::_should_intentional_walk` | Add base-open precondition + on-deck quality-gap check. |
| `physics_sim/config.py` | `ibb_ondeck_gap`, base-state gates. |
| `scripts/physics_sim_season_kpis.py` | IBB/game sanity band. |
| `tests/test_ibb_depth.py` (new) | IBB fires: 1st open + strong batter vs weak on-deck, late/close; does NOT fire bases-loaded or when on-deck is stronger. |

## Verification gate

- Unit tests above. KPI `--strict` green seeds 1 & 2 — IBB/game in band,
  runs/game unchanged.

## Non-goals

- Four-pitch vs signaled IBB mechanics (a signaled walk is fine). Semi-
  intentional / pitch-around gradations beyond the existing model. Lefty/righty
  bullpen-driven IBB chains.
