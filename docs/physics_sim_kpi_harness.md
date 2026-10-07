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
- `--tolerances path/to/tolerances.json` overrides defaults (keys must match KPI
  names; one file can override strict and report-only tolerances).

## Output

The JSON payload includes:

- `metrics`: computed KPIs (P/PA, zone/swing/contact rates, K%, BB%, HR/FB, BABIP,
  steals/attempts, BIP double-play rate, runs/hits/HR per team game).
- `deltas`: KPI minus MLB benchmark (where available).
- `tolerance_ok` and `tolerance_failures`: pass/fail summary vs the strict
  tolerances (`DEFAULT_TOLERANCES`); these decide `--strict`.
- `report_only_gates`: `results` (one row per report-only gate: value, target, delta,
  tolerance, `ok`) and `failures`. These gates never fail `--strict`; the
  table is also printed to stderr.
- `rating_splits`: top/bottom decile summaries for batter contact/power and pitcher control.

## Report-only gates (audit 2026-10-06, Release 2)

`REPORT_ONLY_TOLERANCES` holds corrected benchmarks and newly computed metrics
that the current engine is known to miss. They are measured and reported on
every run so the gap stays visible, without turning the CI calibration check
red. Move a key into `DEFAULT_TOLERANCES` when the engine fix for it lands.

| Metric | Target | Tol | Source | Calibration engine (seeds 1 / 2) |
| --- | --- | --- | --- | --- |
| `sba_per_pa` | 0.025 | 0.005 | MLB 2023-24 team totals (audit H2; was 0.050) | 0.050 / 0.051 |
| `sb_per_team_game` | 0.73 | 0.12 | MLB 2023-24 team totals (H2) | 1.41 / 1.43 |
| `qualified_hr40_count` | 5.0 | 3.0 | MLB 2021-24 had 3-5 (M3; was 2.5 +/- 5, could not fail low) | 2 / 2 (edge) |
| `hard_hit_pct` | 0.38 | 0.03 | Statcast, 95+ mph per batted ball (M2/M3) | 0.289 / 0.290 |
| `barrel_pct` | 0.075 | 0.015 | Statcast barrel rule per batted ball (M2/M3) | 0.043 / 0.045 |
| `sweet_spot_pct` | 0.33 | 0.03 | Statcast, 8-32 degrees per batted ball (M2) | 0.567 / 0.568 |
| `extra_base_advance_rate` | 0.40 | 0.05 | XBT%, Baseball-Reference definition (M7) | 0.681 / 0.689 |

Also corrected in the same release, and strict:

- `qualified_hr30_count`: 20 +/- 8 (was a 5.5 benchmark, ungated). The engine
  scores 15 / 20.
- `qualified_k_pct_sd` was renamed `qualified_hitter_k_pct_sd` (same 0.055
  target): it always measured qualified hitters' K% spread, not pitchers'. A
  `--tolerances` file using the old name still applies.

`extra_base_out_rate` (runners thrown out per XBT chance; MLB about 0.02-0.03)
is reported in `metrics` without a gate. XBT chances are counted by the engine
(`xbt_opp` / `xbt_taken` / `xbt_out` in each game's totals, see
`physics_sim.engine._tally_extra_bases_taken`): runner on 2nd on a single,
runner on 1st on a single when 3rd is open, runner on 1st on a double.

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
- Extra bases taken: XBT% and the runner-out rate come from the engine's
  counters (`extra_base_advance_rate` / `extra_base_out_rate` above). The
  extras report only `first_to_third_on_single_pct`, from hits with no out on
  the bases (the log can't say which runner was out).
- `range_plays_per_fa_sd_*` is a plays-made proxy (assists for infielders),
  not OAA, so it has no MLB reference row; true OAA needs engine logging.
- `extra_half_runs` / `extra_half_p_score` use top halves only: a bottom
  half in extras stops at the winning run.
- `--matchup-grid-pa N` adds the CH x pitcher K and PH x pitcher HR log5 grids
  (a PA Monte Carlo on the per-pitch code, N PA per cell; ~20000 resolves a
  2 pp K residual and takes about a minute). Off by default.
- The dispersion metrics (true sd, `team_true_wpct_sd`) and `home_wpct` are
  noisy within one seed; pool seeds before drawing conclusions (`tables`
  keeps the unclipped variances for pooling).
