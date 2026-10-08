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

The strict contract is the CI configuration: 162 games per team on the
`data/calibration` fixture, with `PYTHONHASHSEED=0`. Check seeds 1 AND 2
before pushing an engine change:

```bash
PYTHONHASHSEED=0 python scripts/physics_sim_season_kpis.py --games 162 \
  --seed 1 --base-dir data/calibration \
  --players data/calibration/players.csv --strict
```

CI also runs the league-like fixture (`data/calibration_league`, built by
`scripts/generate_league_fixture.py`) on seed 1, report-only: it never fails
the job.

The season is the `mlb_162` schedule template (owner decision Q4: MLB-dense;
weekly off day and the All-Star break, no off day after every series),
starting 2025-04-01. Pitcher rest is counted in calendar days (decision 9),
so the harness sees the off days owners see.

## Output

The JSON payload includes:

- `metrics`: computed KPIs (P/PA, zone/swing/contact rates, K%, BB%, HR/FB, BABIP,
  steals/attempts, BIP double-play rate, runs/hits/HR per team game), plus
  the kpi_extras metrics promoted to strict gates (below).
- `deltas`: KPI minus MLB benchmark (where available).
- `tolerance_ok` and `tolerance_failures`: pass/fail summary vs the strict
  tolerances (`DEFAULT_TOLERANCES`); these decide `--strict`.
- `report_only_gates`: `results` (one row per report-only gate: value, target, delta,
  tolerance, `ok`) and `failures`. These gates never fail `--strict`; the
  table is also printed to stderr.
- `rating_splits`: top/bottom decile summaries for batter contact/power and pitcher control.

## Release 3 strict-gate changes (7.47.0)

Release 3 fixed the bullpen usage, the extra-inning rules and the
inning-ending-run bug (audit H1, M8, L15, decision 11). The strict gate
changed in four ways.

### Promoted to strict

Three report-only kpi_extras metrics became strict gates.
`_promote_extras_metrics` copies them from the report-only block into
`metrics`. Their targets are in `STRICT_EXTRAS_TARGETS`, and each matches its
row in `mlb_report_only_reference.csv`. If a promoted metric was not computed
(the extras raised, or no game carried base-out logging), it is listed as a
failure with value NaN. A strict gate cannot pass by being skipped.

| Metric | Target | Tol | What it gates | 7.46.0 (cal s1 / s2) | 7.47.0 (cal s1 / s2 / s3) |
| --- | --- | --- | --- | --- | --- |
| `runs_on_inning_ending_plays` | 0 | 0 | Rule 5.08(a): no run on a third-out force or a batter-runner out before first (L15). Season total | 79 / 55 | 0 / 0 / 0 |
| `relief_60plus_pct` | 0.01 | 0.01 | Relief outings of 60+ pitches (H1); band 0-2% | .0168 / .0166 | .0017 / .0008 / .0023 |
| `closer_third_straight_day` | 0 | 0 | Closer outings on a third straight calendar day (H1). Season total | 290 / 338 | 0 / 0 / 0 |

`closer_third_straight_day` counts closer (`CL`) relief outings whose
`prior_streak` (days in a row pitched up to yesterday) is 2 or more. The
engine blocks those outings. The only exception is the last-resort tier for
an injury or an empty pen, which can still pick a blocked closer when no other
arm is left.

`starts_120plus_pct` (0 / 0 / 0 on calibration) and `closer_ip_per_app`
(.92-.95) stay report-only for one more release, as planned.

### `reliever_b2b_share` is counted in calendar days

The gated `reliever_b2b_share` (0.15 +/- 0.06) counts relief outings by the
same pitcher on consecutive **calendar days**, which is the MLB meaning
(decision 9 / owner decision Q2). An off day breaks the streak, and two games
on the same day are not a back-to-back. Release 2 compared consecutive league
game dates. That version is now reported, not gated, as
`reliever_b2b_game_share` in `metrics`: it reads about 0.18 on calibration,
against 0.14-0.15 for the calendar version.

### Temporary `platoon_gap_woba` widening

`platoon_gap_woba` tolerance: 0.006 -> **0.009** (target 0.026, pass band
0.017-0.035). The comment in the code reads: "temporary (owner decision Q2,
2026-10-07): RNG-fragile until the Release 5 platoon retune (H7); restore
0.006 then."

Release 3 did not move a platoon mechanism (6-seed mean .0307, against .0310
before). Calibration seed 1 rerolled to .0334, against the old .032 ceiling.
**Restore 0.006 in Release 5.**

### Reference rows

- `extra_half_runs` and `extra_half_p_score` now hold the automatic-runner
  values: 0.95 runs and a 0.62 scoring share per extra half. The runner is on
  in the regular season (decision 11). The no-runner values (0.48 / 0.27)
  moved to the note rows `extra_half_runs_no_runner` and
  `extra_half_p_score_no_runner`. They apply to the postseason and to leagues
  that switch the runner off. The old `ghost_runner_runs_per_extra_half` note
  row is gone.
- New rows: `closer_third_straight_day` (0, the strict target) and
  `emergency_apps_per_team_season` (about 1: a rested starter relieves only
  when the pen is empty, decision 7).

## Current baselines (7.47.0)

`PYTHONHASHSEED=0`, 162 games per team, 30 teams. "League" is the
regenerated `data/calibration_league` (seed 20261006). 7.46.0 is the
pre-Release-3 run on the old fixture.

| Metric | Calibration s1 / s2 / s3 | League s1 | League s1, 7.46.0 |
| --- | --- | --- | --- |
| Strict gates failed | 0 / 0 / 0 | 11 (report-only) | 12 |
| `runs_per_team_game` | 4.308 / 4.348 / 4.324 | 4.105 | 4.016 |
| `ops` | .719 / .720 / .720 | .686 | .688 |
| `relievers_per_team_game` | 3.20 / 3.20 / 3.23 | 3.22 | 2.30 |
| `reliever_top_appearances` | 81 / 81 / 81 | 81 | 80 |
| `reliever_b2b_share` (calendar) | .144 / .142 / .150 | .133 | .108 (game dates) |
| `reliever_b2b_game_share` | .181 / .181 / .188 | .176 | -- |
| `saves_per_team_game` | .280 / .266 / .275 | .277 | .324 |
| `pitches_per_start` / `ip_per_start` | 86.4 / 86.6 / 86.2 ; 5.28 / 5.31 / 5.26 | 87.2 ; 5.15 | 88.1 ; 5.18 |
| `platoon_gap_woba` | .0334 / .0310 / .0314 | .0403 | .0478 |
| `tto_ops_gap` | .057 / .053 / .071 | .077 | .091 |
| `runs_on_inning_ending_plays` | 0 / 0 / 0 | 0 | 57 |
| `relief_60plus_pct` | .0017 / .0008 / .0023 | .0006 | .0988 |
| `closer_third_straight_day` | 0 / 0 / 0 | 0 | -- |
| `extra_half_runs` (report-only) | 1.04 / 1.06 / 0.98 | 1.02 | 0.45 |
| `extra_inning_game_share` (report-only) | .096 / .102 / .112 | .108 | .123 |

The league fixture's 11 failures are `pitches_per_pa`, `babip`, `avg`, `iso`,
`runs_per_team_game`, `hits_per_team_game`, `hr_per_team_game`,
`triples_per_team_game`, `qualified_hr30_count`, `platoon_gap_woba` and
`tto_ops_gap`.

- Fixed since 7.46.0: `relievers_per_team_game` and `saves_per_team_game`
  (the bullpen fix). `bb_pct` also passes now, but only just, at .0900.
- Newly failing: `hits_per_team_game` (7.63 against 8.2 +/- 0.5) and
  `triples_per_team_game` (.224 against .14 +/- .08). Both were already
  near their edges at 7.46.0 (7.76 and .207). The regenerated player pool is
  faster: 19.0% of active hitters now have SP >= 70, up from 14.6%. They
  belong to the batted-ball and baserunning work in Releases 4 and 6.

Tightest strict margins on calibration: `platoon_gap_woba` on seed 1 (.0016
under the widened ceiling) and `qualified_hitter_k_pct_sd` (about .003 above
its floor).

## Report-only gates (audit 2026-10-06, Release 2)

`REPORT_ONLY_TOLERANCES` holds corrected benchmarks and newly computed metrics
that the current engine is known to miss. They are measured and reported on
every run so the gap stays visible, without turning the CI calibration check
red. Move a key into `DEFAULT_TOLERANCES` when the engine fix for it lands.

| Metric | Target | Tol | Source | Calibration engine (seeds 1 / 2), 7.47.0 |
| --- | --- | --- | --- | --- |
| `sba_per_pa` | 0.025 | 0.005 | MLB 2023-24 team totals (audit H2; was 0.050) | 0.050 / 0.050 |
| `sb_per_team_game` | 0.73 | 0.12 | MLB 2023-24 team totals (H2) | 1.42 / 1.40 |
| `qualified_hr40_count` | 5.0 | 3.0 | MLB 2021-24 had 3-5 (M3; was 2.5 +/- 5, could not fail low) | 4 / 5 |
| `hard_hit_pct` | 0.38 | 0.03 | Statcast, 95+ mph per batted ball (M2/M3) | 0.287 / 0.288 |
| `barrel_pct` | 0.075 | 0.015 | Statcast barrel rule per batted ball (M2/M3) | 0.044 / 0.044 |
| `sweet_spot_pct` | 0.33 | 0.03 | Statcast, 8-32 degrees per batted ball (M2) | 0.568 / 0.567 |
| `extra_base_advance_rate` | 0.40 | 0.05 | XBT%, Baseball-Reference definition (M7) | 0.688 / 0.688 |

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
- They are **not gated**, except for the keys in `STRICT_EXTRAS_TARGETS`
  (see "Release 3 strict-gate changes"). `--strict` only reads `metrics`.
  Promote a metric to a gate only in the engine release that fixes what it
  measures.
- MLB references live in `data/MLB_avg/mlb_report_only_reference.csv`
  (`approximate` = 1 marks rough values; the printout tags them with `~`).
- Situational metrics need the engine's base-out logging: the first
  `pitch_log` entry of each PA carries `pa_start`, `inning`, `half`,
  `outs_before`, `bases_before` (bitmask 1/2/4), `bat_score_before` and
  `fld_score_before`. Games without it are counted under `coverage`, and those
  metrics come back `null`.
- `runs_on_inning_ending_plays` must be 0 (rule 5.08(a); audit L15). It is a
  strict gate since Release 3.
- Extra bases taken: XBT% and the runner-out rate come from the engine's
  counters (`extra_base_advance_rate` / `extra_base_out_rate` above). The
  extras report only `first_to_third_on_single_pct`, from hits with no out on
  the bases (the log can't say which runner was out).
- `range_plays_per_fa_sd_*` is a plays-made proxy (assists for infielders),
  not OAA, so it has no MLB reference row; true OAA needs engine logging.
- `extra_half_runs` / `extra_half_p_score` use top halves only: a bottom
  half in extras stops at the winning run. Their references assume the
  automatic runner (0.95 / 0.62).
- `--matchup-grid-pa N` adds the CH x pitcher K and PH x pitcher HR log5 grids
  (a PA Monte Carlo on the per-pitch code, N PA per cell; ~20000 resolves a
  2 pp K residual and takes about a minute). Off by default.
- The dispersion metrics (true sd, `team_true_wpct_sd`) and `home_wpct` are
  noisy within one seed; pool seeds before drawing conclusions (`tables`
  keeps the unclipped variances for pooling).

### Release 3 additions (report-only)

These metrics come from the engine's per-game `pitcher_usage` and
`bench_usage` metadata.

**Bullpen**

| Metric | What it reports | Calibration s1 / s2 / s3 | League s1 |
| --- | --- | --- | --- |
| `bullpen_fallback_share` | Relief entries by a rest-flagged arm | .066 / .068 / .071 | .073 |
| `emergency_apps_per_team_season` | Rested-starter relief outings per club per 162 (about 1, decision 7) | 1.3 / 1.7 / 1.4 | 1.3 |
| `emergency_multi_games` | Club-games with two or more such outings | 0 / 0 / 0 | 0 |

Also in this group:

- `emergency_starter_relief_apps`: the season total of the same outings.
- `closer_entries_before_7th_share`: closer outings that started before the
  7th inning.
- `relief_outs_per_app_{cl,su,mr,lr}`: relief outs per appearance by role.

**Bench and fatigue** (audit M16)

| Metric | What it reports | Calibration s1 / s2 / s3 | League s1 |
| --- | --- | --- | --- |
| `backup_c_starts_mean_per_162` / `_min_per_162` | Backup-catcher starts per 162 | 41.4 / 40 on every seed | 49.4 / 40 |
| `hitters_starting_every_game` | Hitters who started every game | 0 / 0 / 0 | 3 |
| `bench_rests_blocked_field_per_162` | League rests blocked at a field position (target under 500) | 109 / 109 / 109 | 1198 |
| `bench_rests_blocked_c_per_162` | League rests blocked at catcher (target under 50) | 0 / 0 / 0 | 0 |
| `fatigue_tired_starter_share` | Share of starts by a tired regular | 0 / 0 / 0 | 0 |

Also in this group:

- `bench_rests_per_team_season`: rest days per club per 162.
- `bench_chain_subs_per_team_season` and
  `bench_similar_subs_per_team_season`: how the rested starters were
  replaced, per club per 162.
- `starting_c_max_starts_per_162`: the most starts by any club's top catcher,
  per 162.

On the league fixture, field rests blocked for want of a substitute (1198) are
still above the under-500 target.
