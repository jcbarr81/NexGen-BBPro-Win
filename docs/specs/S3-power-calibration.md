# S3 — Make power hit for power

Status: **shipped in 7.45.0** (2026-10-03), rolled out mid-season on
alpha-test at the commissioner's request — it is the test league. Phases 0, 1, 2
and 4 are done; Phase 3 is deferred (see below).

## Outcome

| | before | after (7.45.0) |
|---|---|---|
| Fixture, HR vs Power (seeds 1 / 2) | 0.08 / 0.01 | **0.59 / 0.60** |
| Fixture, HR vs Contact | 0.80 / 0.80 | **0.19 / 0.22** |
| Fixture, ISO vs Power | 0.05 / 0.02 | **0.62 / 0.62** |
| Fixture, qualified 30-HR hitters (MLB ≈ 5.5) | 29 / 31 | 15 / 20 |
| alpha-test copy, 30 days: HR vs Power | +0.01 | **+0.45** |
| alpha-test copy, 30 days: HR vs Contact | +0.70 | **+0.06** |
| alpha-test copy: league HR per PA | .0295 | .0298 |
| Leroy Harris (CH 73 / PH 52), same 30 days | 9 HR in 114 PA | 3 HR in 105 PA, .310 |
| Strict gates green | seeds 1, 2 | seeds 1, 2, 4 |

The shipped config was green only on the two seeds it was calibrated on (it
fails seed 3 on the .300-hitter count and seed 4 on OPS spread); the new one
also passes seed 4 and misses seed 3 by a hair on OPS (.730) and the platoon
gap. AVG vs Contact fell from ~0.75 to ~0.48 — contact still drives batting
average, it just no longer drives how hard the ball is hit.

### What changed (`physics_sim/config.py`, `physics_sim/physics.py`)

- `bat_speed_contact_scale` 0.15 → **0.0**; new `ev_contact_quality_weight`
  **0.0** — contact is out of bat speed and the exit-velocity quality term.
- New `barrel_power_weight` **1.0** — timing accuracy stays a contact skill;
  barrel accuracy (squaring the ball up) now draws on Power.
- `bat_speed_power_scale` 0.09 → **0.15**, with a new knee: above
  `bat_speed_power_knee` **52** each point adds `bat_speed_power_knee_scale`
  **0.8** more.
- `bat_speed_base` 69.3 → **68.8** to hold league offense level;
  `handedness_contact_bonus` / `handedness_power_bonus` 1.2 → **1.8 / 2.0**
  because handedness had acted partly through contact's old EV effect.
- Harness: `corr_hr_power`, `corr_iso_power`, `corr_hr_contact`,
  `corr_avg_contact`, now **gated** (`RATING_OUTCOME_TARGETS`).

### Trap found on the way

`TuningConfig.from_overrides` silently drops any override key that is not
already in `DEFAULT_TUNING`. The first two calibration rounds tried the new
knobs as overrides and every one was ignored — configurations differing only in
those knobs produced identical numbers to the last digit. New knobs must be
registered in `DEFAULT_TUNING` before they can be tuned.

### Deferred: Phase 3 (restore the power spread for new leagues)

Not done. Widening generated power means changes the calibration fixture, which
means regenerating it and recalibrating against a different rating population —
a separate loop. The curve already works on today's compressed ratings
(alpha-test power p10 48 / p90 59), so existing leagues get the full benefit
without it.

## The problem

Measured on alpha-test, 163 qualified hitters, 2026-10-02:

| Relationship | Correlation | Should be |
|---|---|---|
| HR rate vs **Power** (PH) | **−0.06** | strong, positive |
| HR rate vs **Contact** (CH) | **+0.77** | weak |
| AVG vs Contact | +0.68 | strong (correct) |

Holding power at 45–55, HR rate **triples** as contact rises from 45 to 65+.
Holding contact level, power barely moves it (0.027 → 0.031 HR/AB).

Owner-visible: Leroy Harris (SAN1), 19, contact 73 / power 52, hitting
.394 / .462 / .828 with 20 HR in 198 AB. Cordell Mcgoon (HOU), power 49,
22 HR. Neither is luck — two average-power hitters at 3× the league HR rate is
the engine working as configured.

## Why it happened

S2-08 (2026-07-15, aa33faa44) repaired calibration and found the engine's
rating→outcome gains were 2–3× steeper than assumed. HR is a distance-vs-fence
**threshold**, so a linear power→exit-velocity slope turned a normal power
spread into far too many 30-HR hitters. The repair:

1. cut `bat_speed_power_scale` 0.35 → **0.09** (code default 0.55), now smaller
   than `bat_speed_contact_scale` (0.15);
2. compressed the generated power spread (position means 45–58 → 47–54);
3. stopped gating `qualified_hr30_count` ("right-skewed elite power the engine
   can't reproduce").

League totals passed; nothing checked that *power* produces the power. Contact,
meanwhile, reaches exit velocity through three paths — bat speed, the base
quality multiplier, and timing/barrel accuracy (which also shrinks the EV
penalties) — so it took over.

S2-08 listed the real fix as an open follow-up and it was never done:
*"a nonlinear ph→EV power curve … would let hr30/sub220 be re-gated at MLB
targets."* This spec is that follow-up.

## Goals

- Power drives home runs; contact drives batting average.
- League aggregates (AVG/OBP/SLG, HR per team-game, K%, BB%) stay where they are.
- A realistic power tail: a handful of 30+ and the odd 40-HR season, from the
  hitters with the most power.
- No change to any existing league's player ratings.

## Plan

### Phase 0 — Gate the relationship before changing it

Add rating→outcome metrics to `scripts/physics_sim_season_kpis.py`, report-only
first:

- `corr_hr_power` — HR/PA vs PH among qualified hitters. Target ≥ 0.55.
- `corr_hr_contact` — HR/PA vs CH. Target ≤ 0.25.
- `corr_avg_contact` — AVG vs CH. Keep ≥ 0.5 (already true).
- `corr_iso_power` — ISO vs PH. Target ≥ 0.5.

Baseline them on the calibration fixture (seeds 1 and 2) **and** on a copy of
alpha-test, since live ratings differ from the fixture. This is the missing
guard: it would have failed S2-08 the day it landed.

### Phase 1 — A nonlinear power curve

Replace the linear `bat_speed_power_scale` term in `physics_sim/physics.py`
(bat speed, ~line 809) with a curve that is nearly flat through average power
and steepens above it, e.g. a centred logistic or a piecewise-linear knee at
~55. Average hitters lose almost nothing; genuine sluggers separate. Retune
`bat_speed_base` so league-mean exit velocity, and therefore HR per team-game,
is unchanged.

### Phase 2 — Take contact out of the exit-velocity ceiling

Contact should decide *whether and how squarely* the ball is hit — fewer
whiffs, tighter timing and barrel error, better launch consistency — not how
hard a perfect swing is. Reduce `bat_speed_contact_scale` toward 0 and bound
contact's share of the `quality` multiplier, so a high-contact hitter becomes a
.320 line-drive hitter rather than a 40-HR one.

### Phase 3 — Restore the power spread, new leagues only

Once the curve stops a normal spread from exploding into 30-HR hitters, widen
the generated power means back toward the original 45–58 spec in
`scripts/generate_calibration_roster.py` and the league player generator.
Existing leagues keep their ratings — this is a generation change, not a data
migration.

### Phase 4 — Re-gate and verify

- `--games 162 --strict` green on seeds 1 and 2, with all existing gates.
- Phase 0 correlation gates switched from report-only to gated.
- Re-gate `qualified_hr30_count` if it now lands near MLB; otherwise leave it
  reported and record why.
- Full-season sim on a copy of alpha-test: compare leaderboards and
  distributions before and after; Harris-type high-contact/average-power
  hitters should land around .300 with ordinary power.

### Phase 5 — Rollout (a decision for the commissioner)

This changes how every hitter performs. Two options:

- **At the season boundary (recommended).** Ship it in the offseason. Season
  stats stay internally consistent and nobody's numbers change character
  mid-year.
- **Immediately.** Fixes the visible oddity now, at the cost of a mid-season
  shift in who hits home runs.

## Related, found during the same investigation

- **The run environment is on a knife edge, and was leaning on a bug.** The
  7.44.6 pinch-run fix (runners only for the tying or go-ahead run) removed
  ~0.08 runs per team-game that bench speedsters had been supplying, which
  pushed seed 1 below the `runs_per_team_game` floor (4.17 vs 4.22). It was
  restored with `offense_scale` 1.015 → 1.0175, now green on seeds 1 and 2 —
  but that knob moves runs by ~0.39 per +0.01, and the neighbouring values each
  fail a different gate (1.017 the TTO gap, 1.018 OPS). Pre-fix, the baseline
  sat only 0.04 runs above the floor. Phase 4 should aim for margin, not just a
  pass, and should not lean on one global multiplier to do it.

- **Stolen-base volume.** alpha-test steals 2.31 bases per team-game (after the
  7.44.6 pinch-run fix; 2.41 before), against roughly 0.7 in recent MLB
  seasons. The harness gates attempts at `sba_per_pa` 0.050, which looks about
  double the real rate (~0.025) — verify the benchmark against its source, then
  recalibrate the steal-attempt knobs alongside Phase 4 so both land in one
  rebalance.
- **Survivorship.** Real leagues bench and demote players who stop hitting; this
  sim does not (S2-05 / S2-11). It is part of why sub-.220 and 30-HR counts are
  hard to hit, and is out of scope here.

## Effort and risk

Phases 0–2 are the core: a day or two of engine work plus repeated 162-game KPI
runs, which take minutes each on the fixture. The risk is the usual
calibration see-saw — moving power moves runs, which moves pitching gates — so
every change is checked against the full strict harness, never tuned on one
metric at a time, and never tried on a live league first.
