# S3-01 — Park Factors Done Right (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Part of the Sprint 3 park/environment track. Companion specs:
> `S3-02_weather.md` (shares the carry-distance path), `S3-03_foul_outs.md`.

## Objective

Ballpark identity currently has **zero** effect on offense:
`physics_sim/config.py:388` sets `"park_factor_scale": 0.0`, so the park term in
the carry calculation collapses to 1.0. Re-enable park effects **without the
naive blow-up** the plan warns about — the bundled per-park factor is an
empirical **HR** factor, and applying it as a **carry-distance** multiplier
(`physics.py:970-979`) is nonlinear (distance feeds an exponential-ish
HR-probability curve), double-counts wall geometry, and triple-counts altitude
at high-elevation parks. Convert the empirical park factor into an HR-*rate*
adjustment layered on top of the geometry the engine already models.

## Verified current state (load-bearing facts)

- **The park term is off.** `config.py:388` `"park_factor_scale": 0.0`.
- **How the park term is applied today** (`physics_sim/physics.py:970-979`):
  ```python
  altitude_ft = float(getattr(park, "altitude_ft", 0.0) or 0.0)
  altitude_factor = 1.0 + altitude_ft * tuning.get("altitude_ft_scale", 0.00002)
  altitude_factor = max(0.9, min(1.25, altitude_factor))
  park_factor_scale = tuning.get("park_factor_scale", 1.0)
  park_factor = 1.0 + (park.park_factor - 1.0) * park_factor_scale
  carry_scale *= tuning.get("altitude_scale", 1.0) * park_factor * altitude_factor
  ```
  `park.park_factor` (empirical HR factor) is multiplied into **carry_scale** (a
  distance multiplier) — this is the wrong lever, and it stacks with
  `altitude_factor`, which is ALSO derived from park altitude → altitude is
  counted twice at Coors-like parks.
- **Park data** lives in `physics_sim/park.py` (a `Park` dataclass with at least
  `park_factor`, `altitude_ft`, `foul_territory_scale`, wall geometry). Verify
  the exact field set before coding. Per-park values are seeded from the bundled
  park CSV / generator (`scripts/generate_park_factors.py`,
  `scripts/generate_park_diagrams.py`).
- **The KPI harness** (`scripts/physics_sim_season_kpis.py`) is the gate; it has
  no per-park metric yet.

## Acceptance criteria

1. Park effects are ON by default and applied as an **HR-probability
   adjustment**, not a raw carry-distance multiplier.
2. The empirical park factor is applied as a **residual**: `residual = empirical
   HR factor ÷ geometry-implied HR rate for that park`, so parks whose HR boost
   is already explained by short walls / altitude don't get it added twice.
3. Altitude is counted **once** (fold the altitude contribution into either the
   carry path OR the residual, not both).
4. A new **per-park HR-rate-rank KPI** (`park_hr_rank_corr` or per-park HR/game
   spread) is added to the harness and gated: simulated per-park HR ranking
   correlates with the empirical factor within tolerance.
5. Overall HR/game, SLG, ISO league gates stay green (`--strict`, seeds 1 & 2).

## Decisions (no open choices)

- **D1 — Residual HR-probability adjustment, not carry multiplier.** Compute the
  geometry-implied HR rate the engine already produces for a park (from walls +
  altitude carry), then multiply the final HR *probability* by
  `clamp(empirical_factor / geometry_rate, [lo, hi])`. New knob
  `park_hr_residual_scale` (default 1.0) + clamp knobs. Leave the carry path's
  raw `park_factor` term removed (set `park_factor_scale` semantics to "residual
  mode").
- **D2 — Altitude once.** Keep `altitude_factor` in the carry path (physical:
  thin air → more carry) and EXCLUDE altitude from the empirical residual (or
  vice-versa). Pick the carry path (it's physical); document it.
- **D3 — Optional wall refinement (stretch).** If per-park HR rank still doesn't
  track, refine the 5-point wall model / heights in `physics_sim/park.py`; keep
  this behind the same KPI gate. Not required for the core fix.

## Files to change

| File | Change |
|---|---|
| `physics_sim/physics.py` (~970-979 + the HR-decision site) | Remove the raw `park_factor` carry term; apply a residual HR-probability multiplier at the fly-ball→HR decision. |
| `physics_sim/config.py` (~388-393) | Replace/retask `park_factor_scale`; add `park_hr_residual_scale` + clamp knobs. |
| `physics_sim/park.py` | (Stretch, D3) wall/height refinement. |
| `scripts/physics_sim_season_kpis.py` | New per-park HR KPI + tolerance. |
| `tests/test_park_factors.py` (new) | Unit: same batted ball in a hitter's vs pitcher's park yields a higher HR probability in the hitter's park; residual clamps hold. |

## Verification gate

- KPI `--strict` green on **seeds 1 & 2** including the new per-park HR KPI;
  league HR/game, SLG, ISO gates unchanged.
- Eyeball: a known hitter's park (Coors-like) ranks top-3 in simulated HR/game;
  a known pitcher's park ranks bottom-3.

## Non-goals

- Park effects on non-HR outcomes (doubles/triples alleys) beyond what geometry
  already produces. Weather (S3-02). Per-league custom park editing UI.
