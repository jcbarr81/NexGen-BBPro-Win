# S3-04 — Extra-Innings Modernization (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 track. Smallest of the physics items — self-contained,
> low-risk, and a good first Sprint 3 implementation.

## Objective

Extra innings use a retired ruleset: the **ghost runner is off by default**
(`physics_sim/config.py:298` `"extra_innings_runner": 0.0`) and games can run to
an 18-inning tie cap (`config.py:300` `"max_innings": 18.0`). Modernize: ghost
runner on the 2nd base to start each extra half-inning by default, no tie cap,
and a per-league setting to opt out.

## Verified current state

- `config.py:298` `"extra_innings_runner": 0.0` — the automatic runner is a
  probability/flag currently 0 (off).
- `config.py:299` `"extra_innings_runner_start": 10.0` — the inning from which
  the rule would apply (10th).
- `config.py:300` `"max_innings": 18.0` — hard tie cap (games can end tied).
- The extra-innings loop lives in `physics_sim/engine.py` (search the inning
  loop that references `max_innings` / the tied-game continuation). Verify the
  exact half-inning setup site before coding.

## Acceptance criteria

1. From `extra_innings_runner_start` (10th) onward, each half-inning **begins
   with a runner on 2nd** (the last batter to make an out in the prior inning,
   or a placeholder) by default.
2. **No tie cap:** games continue until a half-inning ends with a leader; remove
   the 18-inning termination (or raise it far enough that a natural resolution
   is guaranteed — the ghost runner makes ties vanishingly rare).
3. A **per-league setting** (`extra_innings_ghost_runner: bool`, default **on**)
   opts out — with the runner off AND the tie cap restored for that league, to
   avoid infinite games.
4. Sanity KPIs: average game length (innings) and extra-inning frequency land in
   a realistic band; no game exceeds a safety cap (e.g. 30 innings) even with
   the runner off (keep a high hard stop as a guard).

## Decisions (no open choices)

- **D1 — Ghost runner on by default.** Flip `extra_innings_runner` semantics to
  a flag defaulting on (or set the probability to 1.0) from the start inning.
  The placed runner is the player who made the final out of the previous inning
  (fallback: bottom-of-order hitter). Score him as unearned if he comes around
  (standard MLB rule — verify the earned/unearned attribution in the run-scoring
  path).
- **D2 — Keep a hard safety cap.** Remove the *default* tie cap but keep a
  high guard (e.g. `max_innings_hard = 30`) so a pathological league (runner off)
  can't loop forever; a game hitting the guard ends tied and logs a warning.
- **D3 — League setting** lives with the other league gameplay settings (verify
  where extra-innings config is surfaced; wire the toggle through to the tuning
  the engine reads).

## Files to change

| File | Change |
|---|---|
| `physics_sim/config.py` | `extra_innings_runner` default on; `max_innings` → default no-cap + `max_innings_hard` guard. |
| `physics_sim/engine.py` | Place the ghost runner at the start of each extra half-inning ≥ start; remove the default tie cap; keep the hard guard; unearned-run attribution. |
| League settings (services + desktop) | `extra_innings_ghost_runner` toggle (default on) → tuning. |
| `tests/test_extra_innings.py` (new) | Tied game reaches the 10th → runner on 2nd; game resolves (no tie) with runner on; opt-out league can end tied at the cap; runner scores as unearned. |

## Verification gate

- Unit tests above green. KPI harness: average innings/game and extra-inning
  rate within a realistic band; no runaway game length in a full season
  (`--strict` league gates unchanged, seeds 1 & 2).

## Non-goals

- Postseason-specific extra-innings rules. Pitcher-usage changes driven by
  longer games (existing reliever rest already applies). Changing regulation
  9-inning logic.
