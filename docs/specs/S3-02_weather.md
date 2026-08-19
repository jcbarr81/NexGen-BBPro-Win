# S3-02 — Weather + Day/Night (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 park/environment track. Shares the carry-distance path
> with `S3-01_park_factors.md` — land S3-01 first (altitude/park residual) so the
> carry lever is clean before adding weather on top.

## Objective

Weather has **zero** effect: `physics_sim/config.py:390-391` define
`"wind_speed": 0.0` and `"wind_angle_deg": 0.0`, but **grep confirms neither is
read anywhere in `physics_sim/`** — they are dead knobs. Sample per-game
temperature + wind and feed them into carry (temperature) and spray-vs-wind
(vector), giving day-to-day and seasonal HR variance.

## Verified current state

- `config.py:390-391` — `wind_speed`, `wind_angle_deg` exist, **never read**
  (verified: `grep -rn "wind_speed\|wind_angle" physics_sim/*.py` returns only
  config.py). No temperature knob exists.
- Carry is computed in `physics_sim/physics.py::estimate_carry_distance`
  (~physics.py:961+): `carry_scale` is the single distance lever; altitude is
  already folded in there (S3-01).
- Spray angle: `physics.py::spray_to_field_angle(spray_deg)` (0 = RF line,
  π/2 = LF line) — the hook for a wind **vector** (tail/cross/in).
- Games are driven per date by `SeasonSimulator`; there is no per-game weather
  context today.

## Acceptance criteria

1. Each game samples a temperature and a wind (speed + direction) deterministic
   from the game seed (so parity holds), optionally park/season-biased.
2. **Temperature → carry:** ~+2.5 ft of carry per +10°F (a standard, cite it in
   a comment), applied in `estimate_carry_distance`.
3. **Wind → carry + spray:** a tailwind toward the pull field boosts HR on
   pulled fly balls; an in-blowing wind suppresses; crosswind nudges spray. Wind
   effect scales with launch angle / hang time (grounders unaffected).
4. New KPI: **seasonal HR variance** — HR/game standard deviation across
   simulated games lands in a realistic band (weather adds spread without moving
   the league mean).
5. League HR/game / SLG means stay green (`--strict`, seeds 1 & 2).

## Decisions (no open choices)

- **D1 — Deterministic per-game sampling.** Derive `(temp, wind_speed,
  wind_angle)` from `random.Random(hash((park_id, date, seed)))` (hash-seed
  pinned, like `_apply_bullpen_usage_order`) so a game is reproducible. No
  global-random draws (keeps serial/parallel parity intact for S1-10).
- **D2 — Weather is a game context, not a config global.** Pass the sampled
  weather into the batted-ball path via the existing per-game context dict
  (the same one that already carries `foul_territory_scale`), not by mutating
  `DEFAULT_TUNING`. The `wind_speed`/`wind_angle_deg` config entries become the
  *mean/band* for sampling, and are finally read.
- **D3 — Temperature model.** `carry_scale *= 1.0 + (temp_f - 70) *
  temp_carry_scale` with `temp_carry_scale` ≈ 0.0007 (≈ +2.5 ft on a ~350 ft fly
  per 10°F). Clamp to a sane range.

## Files to change

| File | Change |
|---|---|
| `physics_sim/config.py` | Retask `wind_speed`/`wind_angle_deg` to sampling mean/band; add `temp_mean_f`, `temp_band_f`, `temp_carry_scale`, `wind_carry_scale`, `wind_spray_scale`. |
| `physics_sim/engine.py` | Sample per-game weather (deterministic) and add it to the per-game context. |
| `physics_sim/physics.py::estimate_carry_distance` + spray path | Apply temp (carry) and wind (carry + spray-vs-vector). |
| `scripts/physics_sim_season_kpis.py` | Seasonal HR-variance KPI + tolerance. |
| `tests/test_weather.py` (new) | Same batted ball hotter/tailwind → more carry; grounders unaffected; determinism from seed. |

## Verification gate

- KPI `--strict` green seeds 1 & 2 incl. the HR-variance gate; league HR/game
  mean unchanged. Same seed → identical weather (parity check).

## Non-goals

- Rain delays / postponements. Humidity, dew point. Day/night lineup or fatigue
  effects beyond carry (a `day_night` flag may be sampled for future use but is
  out of scope here). Roof/dome per-park modeling beyond a "no wind indoors"
  flag if `park.dome` exists.
