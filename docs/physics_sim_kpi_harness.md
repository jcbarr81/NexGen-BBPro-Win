# Physics Sim KPI Harness

This harness runs a deterministic physics-sim mini season and reports KPIs
alongside MLB benchmark deltas and tolerance checks.

## Run

```bash
./.venv/bin/python scripts/physics_sim_season_kpis.py \
  --games 50 \
  --seed 1 \
  --players data/players_normalized.csv \
  --ensure-lineups \
  --output tmp/physics_kpis.json \
  --strict
```

- `--strict` exits non-zero if any KPI drifts outside the configured tolerance.
- `--tolerances path/to/tolerances.json` overrides defaults (keys must match KPI names).

## Output

The JSON payload includes:

- `metrics`: computed KPIs (P/PA, zone/swing/contact rates, K%, BB%, HR/FB, BABIP,
  steals/attempts, BIP double-play rate, runs/hits/HR per team game).
- `deltas`: KPI minus MLB benchmark (where available).
- `tolerance_ok` and `tolerance_failures`: pass/fail summary vs tolerances.
- `rating_splits`: top/bottom decile summaries for batter contact/power and pitcher control.

## Notes

- The DP check uses `bip_double_play_pct` (GIDP per ball in play) because the MLB
  benchmark file does not include a direct DP-per-game target.
- The harness defaults to `data/players_normalized.csv` when present.

## Report-only KPIs (audit 2026-10-06, Release 2)

`scripts/kpi_extras.py` adds about 100 KPIs the strict gates cannot see:
bullpen usage, per-count swing rates, walk/strikeout/HR dispersion, the
in-game velocity fade, extra bases taken, situational run scoring (RE24, run
probability, runs per half-inning, late & close), platoon gaps by hand, team
talent spread and more. The module cites the audit finding each one tracks
(`docs/audits/2026-10-06-engine-ratings-audit/REPORT.md`).

- They land in the JSON under `report_only` (`metrics`, `tables`, `reference`,
  `deltas`, `coverage`, `runtime_s`) and are printed to stderr after every run.
- They are **never gated**: `--strict` only reads `metrics`. Promote one to a
  gate only in the engine release that fixes what it measures.
- MLB references live in `data/MLB_avg/mlb_report_only_reference.csv`
  (`approximate` = 1 marks rough values; the printout tags them with `~`).
- Situational metrics need the engine's base-out logging: the first
  `pitch_log` entry of each PA carries `pa_start`, `inning`, `half`,
  `outs_before`, `bases_before` (bitmask 1/2/4), `bat_score_before` and
  `fld_score_before`. Games without it are counted under `coverage`, and those
  metrics come back `null`.
- `runs_on_inning_ending_plays` must be 0 (rule 5.08(a); audit L15).
- `--matchup-grid-pa N` adds the CH x pitcher K and PH x pitcher HR log5 grids
  (a PA Monte Carlo on the per-pitch code, N PA per cell; ~20000 resolves a
  2 pp K residual and takes about a minute). Off by default.
- The dispersion metrics (true sd, `team_true_wpct_sd`) and `home_wpct` are
  noisy within one seed; pool seeds before drawing conclusions (`tables`
  keeps the unclipped variances for pooling).
