# S2-08 — Calibration Repair: Roster, Engine Recalibration, Dispersion Gates, CI

**Status:** Spec approved for implementation (2026-07-15). Prerequisite for S2-07 and S2-12.
**All file:line anchors verified against `main` @ `62f166edf` on 2026-07-15.**

## Objective

Restore a working, committed calibration fixture for the physics-sim KPI harness
(`data/players_normalized.csv` was deleted in v3.1.17 and the CI gate has been dead
since), recalibrate the engine against it until the full Sprint-0 `--strict` gate set
is green, add player-dispersion gates (SD of qualified AVG/OPS, HR-leader counts,
outlier-hitter counts, ERA/K% spread), widen the engine's compression knobs so those
gates can pass, repair `.github/workflows/physics_sim_kpi.yml`, and fix the 16 failing
`tests/test_physics.py` tests plus `tests/test_simulation_averages.py`.

## Root causes (verified during spec work — do not re-litigate)

1. **Normalizer drift mechanism:** `scripts/normalize_players.py:79/97` calls
   `pg._sample_normalized_hitter/_pitcher`, which sample template *percentile bands*
   of the **source CSV's own rating distribution**
   (`playbalance/player_generator.py:324-341` `_sample_from_values` →
   `_percentile_value(values, pct)` where `values` come from
   `_load_rating_distributions(players_path)` at `normalize_players.py:113`).
   Feeding it today's hot `data/players.csv` (hitter means: ch 63.8, ph 57.6,
   eye 62.7, sp 58.0 — engine-neutral is 50) re-amplifies the heat → SLG 1.31 /
   EV 112 mph rosters. The sampling is self-referential; no fix to the templates can
   make it produce an absolute, stable calibration roster.
2. **Harness data-root mixing:** `scripts/physics_sim_season_kpis.py` reads teams via
   `load_teams()` (no path → active league via `get_data_dir()`), rosters/lineups via
   `simulate_matchup_from_files(base_dir=None)` (`physics_sim/engine.py:3046` →
   `get_data_dir()` = the user's live league), but players from
   `_default_players_path()` (repo `data/players.csv`,
   `scripts/physics_sim_season_kpis.py:64-68`). This is why the harness both ran hot
   against the live league and why `tests/test_simulation_averages.py` crashes
   (league lineups reference league player IDs missing from repo players.csv →
   `resolve_lineup` drops all 9 → `ValueError` at `physics_sim/engine.py:3266`) —
   and why that test **writes into the active league**
   (`data/leagues/cbl/data/lineups/BOS_vs_*.csv`; observed and reverted during spec work).
3. **Benchmarks gap:** `data/MLB_avg/mlb_league_benchmarks_2025_filled.csv` has no
   `runs_per_team_game` (or any per-game counting-stat) key, so runs/game was never
   actually gated, even after QW-12.

## Decision 1 — Calibration roster strategy

**DECISION: build a new dedicated generator (`scripts/generate_calibration_roster.py`)
that samples ratings from ABSOLUTE normal distributions and writes a self-contained,
committed fixture league under `data/calibration/`.**
Rationale (one line): the existing normalizer is source-relative by construction
(root cause 1) and the KPI gate must be decoupled from the evolving live-league
generator — an absolute, seeded, committed artifact is the only stable reference.
(Rejected: fixing `normalize_players.py` templates — still self-referential; freezing a
hand-tuned CSV — not reproducible, no way to regenerate after schema changes.)

### 1a. Fixture layout (all committed)

```
data/calibration/
  teams.csv                 # 30 teams
  players.csv               # 780 players (390 hitters, 390 pitchers)
  rosters/{TEAM}.csv        # 26 rows each: "<player_id>,ACT"  (headerless)
  rosters/{TEAM}_pitching.csv  # 13 rows each: "<player_id>,<ROLE>" (headerless)
  lineups/{TEAM}_vs_rhp.csv # header: order,player_id,position ; 9 rows
  lineups/{TEAM}_vs_lhp.csv # identical content to _vs_rhp (platoon lineups are S2-01)
```

File formats mirror the loaders exactly: `physics_sim/team_data.py:57-73`
(`load_roster_status`: col0 player_id, col1 status), `:80-98` (`load_pitching_staff`:
col0 player_id, col1 role), `:101-124` (`load_lineup`: DictReader with
`order,player_id,position`).

### 1b. Teams (30, matching MLB shape — dispersion gates are defined per 30 teams)

`teams.csv` header identical to `data/teams.csv`
(`team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id`).
30 teams, `team_id` = `CAL01`…`CAL30`, six divisions (`East/North/South/West/Central/Pacific`,
5 teams each — division content is irrelevant to the harness; `generate_mlb_schedule`
only needs the ID list). `stadium` = a real MLB park name resolvable by
`utils/park_utils.stadium_from_name` (verified: `"Fenway Park"` resolves; unknown names
return `None` → default park). Use these 30 (all present in `data/parks/ParkConfig.csv` —
the generator MUST assert `stadium_from_name(name) is not None` for every team and fail
loudly otherwise): Fenway Park, Yankee Stadium, Oriole Park at Camden Yards, Tropicana
Field, Rogers Centre, Comerica Park, Guaranteed Rate Field, Kauffman Stadium, Progressive
Field, Target Field, Angel Stadium, Daikin Park, Oakland Coliseum, T-Mobile Park, Globe
Life Field, Citi Field, Citizens Bank Park, Nationals Park, Truist Park, LoanDepot Park,
Wrigley Field, Great American Ball Park, American Family Field, PNC Park, Busch Stadium,
Chase Field, Coors Field, Dodger Stadium, Petco Park, Oracle Park. If any name fails the
assertion, substitute the nearest name found in `ParkConfig.csv` (the generator prints the
available candidates on failure).

### 1c. Roster composition (per team: 26 ACT players)

- **13 hitters:** 9 starters (positions C, 1B, 2B, 3B, SS, LF, CF, RF, DH) + 4 bench
  (backup C, backup IF with `primary_position=2B, other_positions="SS,3B"`, backup OF
  with `primary_position=CF, other_positions="LF,RF"`, backup 1B/DH).
- **13 pitchers:** roles in `{TEAM}_pitching.csv`: `SP1,SP2,SP3,SP4,SP5,CL,SU,SU,MR,MR,MR,MR,LR`.
  (Role vocabulary from `physics_sim/team_data.py:152-167` and the engine's role logic
  `physics_sim/engine.py:551-560,622-657`.)

### 1d. Target rating distributions (the NUMBERS)

Engine response curves center on rating 50 (verified):
pitch velocity `= 83 + arm*0.2` (`physics_sim/engine.py:3961`) → arm 55 ⇒ 94.0 mph
(MLB FB avg ≈ 94); bat speed `= 69.3 + (ph-50)*0.35 + (ch-50)*0.15` (config
`bat_speed_base` `physics_sim/config.py:320-322`, applied `physics_sim/physics.py:806-813`);
EV base `= velo*0.48 + bat_speed*0.7` (`physics.py:814-817`) ⇒ ≈92 raw / ≈88 after
quality at all-50 ratings (target 88.5); eye enters swing decisions as
`0.62+(eye-50)/220` / `0.28-(eye-50)/260` (`physics.py:678-679`). Therefore the
**playing population must average ≈50 in each core rating** with realistic spread.

All ratings sampled `int(round(N(mean, sd)))`, clamped to `[25, 95]`, from one
`random.Random(seed)` instance (default seed **20260715**).

**Hitters — starters, by position** (columns are mean; between-player SD = **10** for
ch/ph/eye/sp, **8** for gf/vl/fa/arm, **12** for pl):

| Pos | ch | ph | eye | sp | fa | arm | gf | pl | vl |
|-----|----|----|-----|----|----|-----|----|----|----|
| C   | 47 | 48 | 48  | 42 | 55 | 55  | 50 | 55 | 50 |
| 1B  | 50 | 58 | 52  | 44 | 50 | 48  | 50 | 57 | 50 |
| 2B  | 52 | 45 | 50  | 54 | 53 | 50  | 50 | 53 | 50 |
| SS  | 50 | 45 | 49  | 56 | 54 | 54  | 50 | 53 | 50 |
| 3B  | 50 | 53 | 50  | 47 | 52 | 54  | 50 | 56 | 50 |
| LF  | 50 | 54 | 50  | 51 | 49 | 49  | 50 | 55 | 50 |
| CF  | 50 | 47 | 50  | 60 | 53 | 51  | 50 | 53 | 50 |
| RF  | 50 | 55 | 51  | 50 | 50 | 55  | 50 | 55 | 50 |
| DH  | 51 | 58 | 52  | 42 | 40 | 45  | 50 | 57 | 50 |

League starter means come to ch 49.8 / ph 51.4 / eye 50.2 / sp 49.6 ≈ 50 ✓.
**Bench hitters:** same position row **minus 6** on ch/ph/eye/sp, SD 8.
`sc` = 50 flat. `height` = `int(round(N(73,2)))` clamp [68,79]. `durability` = N(60,10).
`bats`: weighted draw R 55% / L 35% / S 10%. `throws` = bats (unless S → R).
Non-rating columns: `is_pitcher=0`, `role=""`, `injured=0`, `ready=1`, all `pot_*`
equal to the current value, remaining columns empty string.

**Pitchers — by role** (SD in parentheses):

| Role bucket | arm | control | movement | endurance | hold_runner | gf | vl | fa |
|---|---|---|---|---|---|---|---|---|
| SP (SP1-5) | 55 (7) | 52 (8) | 52 (8) | 75 (8) | 50 (10) | 50 (8) | 50 (8) | 50 (8) |
| CL | 65 (6) | 50 (8) | 58 (8) | 30 (6) | 50 (10) | 50 (8) | 50 (8) | 50 (8) |
| SU | 60 (7) | 50 (8) | 55 (8) | 32 (6) | 50 (10) | 50 (8) | 50 (8) | 50 (8) |
| MR | 55 (8) | 50 (9) | 52 (9) | 36 (7) | 50 (10) | 50 (8) | 50 (8) | 50 (8) |
| LR | 52 (8) | 51 (8) | 51 (8) | 55 (8) | 50 (10) | 50 (8) | 50 (8) | 50 (8) |

Pitcher `bats`(=hand): R 72% / L 28%. **Repertoire** (columns fb,sl,si,cb,cu,scb,kn;
`PitcherRatings.from_row` keeps any pitch > 0, `physics_sim/models.py:99`): every
pitcher gets `fb = N(60,10)`; then per-pitcher draw one of three profiles
(power 40% → sl+cu; breaking 35% → sl+cb; sinker 25% → si+cu) with each secondary
`= N(52,8)`; all other pitch columns 0. `preferred_pitching_role`: `SP`/`CL`/`SU`/`MR`/`LR`
per assignment; `role` = `SP` or `RP`.

**players.csv columns** (exact header, in this order — the consumers are DictReaders,
verified tolerant to this subset: `physics_sim/data_loader.py:11-24`,
`physics_sim/models.py:30-116`, harness `_load_player_names:105-116`,
`_load_player_ratings:119-140`):
`player_id,first_name,last_name,birthdate,height,weight,bats,throws,primary_position,other_positions,is_pitcher,role,preferred_pitching_role,ch,ph,sp,eye,gf,pl,vl,sc,fa,arm,endurance,control,movement,hold_runner,fb,cu,cb,sl,si,scb,kn,durability,injured,ready`
`player_id` = `CAL-0001`…`CAL-0780`. Names sampled (seeded) from
`playbalance/FirstNames.txt` / `playbalance/Surnames.txt`. `birthdate` =
`f"{1991 + rng.randint(0, 12)}-0{1 + rng.randint(0, 8)}-15"`. `weight` = N(205,15) int.

### 1e. Lineups

Both `_vs_rhp.csv` and `_vs_lhp.csv` identical (platoon splits are S2-01, out of scope).
Batting order: sort the 9 starters by `(eye + sp)` desc for slot 1, then remaining by
`(ch + ph + eye)` desc for slots 2-9. `position` column = the starter's
`primary_position` (the 9 starters cover C,1B,2B,3B,SS,LF,CF,RF,DH exactly once).

### 1f. Generator CLI + regeneration policy

```
python scripts/generate_calibration_roster.py [--output-dir data/calibration] [--seed 20260715]
```
Deterministic: same seed ⇒ byte-identical output (single `random.Random(seed)`, no
set/dict iteration over unordered ids). The generator ends by printing per-rating
league means/SDs and asserting: |league starter mean − 50| ≤ 1.5 for ch/ph/eye/sp;
every stadium resolves; every team has 26 ACT / 13 pitching rows / 9 lineup rows.
**CI uses the committed artifact only** (no regeneration in CI). Regeneration is a
deliberate local act followed by engine re-verification (Step 2) and a commit of both
the fixture and any retuned knobs together.

## Decision 2 — Harness changes (`scripts/physics_sim_season_kpis.py`)

1. Add `--base-dir` (type=Path, default None). When set:
   - `_team_ids()` and `_team_parks()` gain a `teams_csv: Path | None = None` parameter
     and call `load_teams(teams_csv)` (signature verified `utils/team_loader.py:60`,
     accepts `file_path`); `main()` passes `base_dir / "teams.csv"`.
   - `run_sim()` gains `base_dir: Path | None = None` and passes it through to
     `simulate_matchup_from_files(..., base_dir=base_dir)` (param verified at
     `physics_sim/engine.py:3034`; resolution `:3020-3026` accepts a dir containing
     `rosters/` directly — `data/calibration` qualifies).
   - `--ensure-lineups` is a no-op for the fixture (lineups are committed); CI drops it.
2. `_default_players_path()` (`:64-68`) unchanged (back-compat); CI passes
   `--players data/calibration/players.csv` explicitly.
3. New dispersion metrics (Decision 4) appended to `summary["metrics"]` so the existing
   `evaluate_tolerances` (`:484-513`) gates them with zero plumbing.

## Decision 3 — Engine recalibration procedure (exact, iterative)

Baseline command, run after every knob change (**the** iteration unit, ~3-8 min):

```
python scripts/physics_sim_season_kpis.py --games 162 --seed 1 \
  --base-dir data/calibration --players data/calibration/players.csv \
  --output tmp/kpis_iter.json --strict
python - <<'EOF'
import json; s=json.load(open('tmp/kpis_iter.json'))
for f in s['tolerance_failures']: print(f"{f['metric']:34s} val={f['value']:.4f} tgt={f['target']:.4f} tol={f['tolerance']}")
EOF
```

Knobs are edited in `DEFAULT_TUNING` (`physics_sim/config.py:9-484`) directly — the
calibration IS the new default. One knob group per iteration, in this order (later
steps depend on earlier ones being green; if a later step knocks an earlier gate out,
return to that step):

**Step 1 — zone & swing** (gates: `zone_pct` .49±.03, `swing_pct` .47±.03,
`z_swing_pct` .65±.03, `o_swing_pct` .32±.03, `first_pitch_strike_pct` .60±.04):
- `zone_target_base` 0.36 (↑ raises zone_pct, ~+0.5 zone_pct per +0.01)
- `zone_swing_scale` 0.91 (↑ raises z_swing)
- `chase_scale` 0.69 (↑ raises o_swing)

**Step 2 — contact & strikeouts** (gates: `contact_pct` .76±.03, `z_contact_pct`
.82±.03, `o_contact_pct` .62±.05, `swstr_pct` .11±.015, `csw_pct` .28±.02,
`k_pct` .22±.02, `k_per_team_game` 8.56):
- `contact_prob_scale` 0.97 (↑ more contact, K↓)
- `k_scale` 0.56 (↑ ⇒ contact_prob ÷ k_scale shrinks ⇒ K↑; verified `physics.py:774`)
- `whiff_base` 0.0095 / `whiff_quality_scale` 0.072 (↑ K↑; use for swstr shape)
- `chase_contact_scale` 0.73 (o_contact only)

**Step 3 — walks & pitch economy** (gates: `bb_pct` .080±.01, `pitches_per_pa`
3.86±.05, `foul_pct` implied):
- `walk_scale` 0.8 — CAUTION, inverted: out-of-zone swing prob is **divided** by it
  (`physics.py:701-703`), so ↑walk_scale ⇒ fewer chase swings ⇒ MORE walks.
- `foul_rate` 0.4 (↑ raises pitches_per_pa).

**Step 4 — contact quality / EV / batted-ball shape** (gates: `avg_exit_velocity`
88.5±2.0, `avg_launch_angle` 12.0±2.5, `bip_gb_pct` .44±.05, `bip_fb_pct` .35±.05,
`bip_ld_pct` .21±.04, `hr_per_fb_pct` .11±.02, `hr_per_team_game` 1.17±0.15):
- `bat_speed_base` 69.3, `ev_bat_weight` 0.7 (EV level)
- `exit_velo_softcap` 105.0 / `exit_velo_softcap_scale` 0.55 → **start at 107.0 / 0.70**
  (Decision 5; EV tail — raises both avg EV slightly and HR/FB)
- `hr_scale` 0.965 (HR-specific, via carry distance `physics.py:967`)
- `launch_angle_base` 12.1, `gb_fb_tilt` 0.97, `bip_gb_cutoff` 9.0, `bip_ld_cutoff` 15.7
  (LA/GB/LD/FB shape)

**Step 5 — hits on balls in play** (gates: `babip` .291±.015, `avg` .245±.010,
`hits_per_team_game` 8.2):
- `babip_scale` 0.92.

**Step 6 — extra-base mix** (gates: `slg` .392±.02, `iso` .165±.015, `ops` .705±.025,
`doubles_per_team_game` 1.63±0.25, `triples_per_team_game` 0.14±0.08):
- `double_distance_scale` 0.7, `triple_distance_scale` 1.0, `double_gap_scale` 0.55.

**Step 7 — run environment** (gates: `runs_per_team_game` 4.47±0.25,
`gidp_per_team_game`, `sb_per_team_game`): emergent from steps 1-6; only if runs alone
are out with everything else green, nudge `offense_scale` 1.01 by ±0.01 and re-run
steps 4-6 gates.

**Done criterion:** the baseline command exits 0 (`--strict`, full
`DEFAULT_TOLERANCES` incl. the new rows below) twice in a row with seeds 1 and 2
(`--seed 2` guards against single-seed overfit; both must pass).

**New benchmark rows** to append to
`data/MLB_avg/mlb_league_benchmarks_2025_filled.csv` (derived from
`data/MLB_avg/mlb_avg_boxscore_2020_2024_both_teams.csv`, halved to per-team-game):

```
runs_per_team_game,4.47
hits_per_team_game,8.20
hr_per_team_game,1.17
doubles_per_team_game,1.63
triples_per_team_game,0.14
qualified_avg_sd,0.028
qualified_ops_sd,0.080
qualified_hr40_count,2.5
qualified_hr30_count,5.5
qualified_sub220_count,3.0
qualified_avg300_count,9.0
qualified_era_sd,0.85
qualified_k_pct_sd,0.055
```

**New `DEFAULT_TOLERANCES` entries** (`scripts/physics_sim_season_kpis.py:27-61`):

```python
"runs_per_team_game": 0.25,
"hits_per_team_game": 0.50,
"hr_per_team_game": 0.15,
"doubles_per_team_game": 0.25,
"triples_per_team_game": 0.08,
"qualified_avg_sd": 0.008,
"qualified_ops_sd": 0.025,
"qualified_hr40_count": 2.0,
"qualified_hr30_count": 2.5,
"qualified_sub220_count": 3.0,
"qualified_avg300_count": 5.0,
"qualified_era_sd": 0.30,
"qualified_k_pct_sd": 0.015,
```

## Decision 4 — Player-dispersion metrics (the S2-08 core)

Computed in `run_sim()` immediately after the leaders block
(insert after `scripts/physics_sim_season_kpis.py:825`, before `rating_splits`), from
the existing `batter_totals` / `pitcher_totals`
(`dict[str, Counter]`, keys = `batting_keys` `:547-572` / `pitching_keys` `:573-605`;
note batter strikeouts are `so`, walks `bb`, and pitcher outs are `outs`).

**Qualification — mirror `api/routers/leaders.py:132-133` exactly:**
`min_pa_q = max(1, round(games_per_team * 3.1))`,
`min_ip_q = max(1, round(games_per_team * 1.0))`.
(Replace the current ad-hoc `min_pa = games_per_team * 3` / `min_ip = games_per_team
* 0.5` at `:760-761` with these — one definition, used for both leaders and gates.)

Definitions (`statistics.pstdev`, population SD; guard: if a qualified pool has < 10
players, emit the metric as `None` and have `evaluate_tolerances` skip `None` — add
`if value is None: continue` after `:499-500`):

```python
QB = [s for s in batter_totals.values() if s.get("pa", 0) >= min_pa_q and s.get("ab", 0) > 0]
QP = [s for s in pitcher_totals.values() if s.get("outs", 0) / 3.0 >= min_ip_q]
avg_i  = h/ab ;  obp_i, slg_i, ops_i per _split_batter_metrics (:397-423)
era_i  = er*27/outs ;  kpct_i = so/pa  (batters)

scale_t = 30.0 / teams          # teams = len(_team_ids()); ==1.0 on the fixture
hr_thresh_40 = 40.0 * games_per_team / 162.0
hr_thresh_30 = 30.0 * games_per_team / 162.0

metrics["qualified_avg_sd"]      = pstdev([avg_i])
metrics["qualified_ops_sd"]      = pstdev([ops_i])
metrics["qualified_hr40_count"]  = count(hr_i >= hr_thresh_40) * scale_t
metrics["qualified_hr30_count"]  = count(hr_i >= hr_thresh_30) * scale_t   # note: >=30 incl. >=40
metrics["qualified_sub220_count"]= count(avg_i < 0.220) * scale_t
metrics["qualified_avg300_count"]= count(avg_i >= 0.300) * scale_t
metrics["qualified_era_sd"]      = pstdev([era_i])
metrics["qualified_k_pct_sd"]    = pstdev([kpct_i])
```

**Scaling decisions:** HR thresholds scale linearly with `games_per_team/162` (a
40-HR/162 pace); counts normalize to a 30-team league via `scale_t`. SD gates do NOT
scale — they are defined at the CI configuration (30 teams × 162 games), where
binomial noise matches the MLB targets' own noise (MLB qualified-AVG SD ≈ .028 at
~550 AB ≈ talent SD .021 + noise .018). Short local runs (`--games 50`) inflate the
SD metrics and may trip those gates; that is expected — the strict contract is the
162-game run. Document this in the harness `--help` epilog.

Targets already listed in Decision 3 CSV rows. Interpretation of the count gates at
tolerance: `hr40 ∈ [0.5, 4.5]` ⇒ 1-4 players on a 40-HR/162 pace (the "does a 42-HR
guy exist?" eyeball test, mechanized); `hr30 ∈ [3, 8]`; `sub220 ∈ [0, 6]`;
`avg300 ∈ [4, 14]`.

## Decision 5 — De-compression knob work

Two mechanical wideners, then iterate against the Decision-4 gates:

1. **Eye slopes** (`physics_sim/physics.py:678-679`):
   `zone_base = 0.62 + (eye - 50.0) / 220.0` → **`/ 160.0`**;
   `chase_base = 0.28 - (eye - 50.0) / 260.0` → **`/ 190.0`**.
2. **EV soft cap** (`physics_sim/config.py:326-327`):
   `exit_velo_softcap` 105.0 → **107.0**; `exit_velo_softcap_scale` 0.55 → **0.70**.

Iteration procedure (after the Decision-3 league averages are green):
1. Run the baseline command; read the six `qualified_*` gates.
2. If `qualified_avg_sd` / `qualified_ops_sd` low → widen eye divisors one notch
   (160→140→120 zone; 190→170→150 chase; floor 120/150) and/or raise
   `bat_speed_power_scale` 0.35 → 0.40 → 0.45 (spreads EV by power rating).
3. If `qualified_hr40_count`/`hr30_count` low with SDs green → raise
   `exit_velo_softcap_scale` by +0.05 (cap 0.85), then `hr_scale` +0.005 only if
   `hr_per_fb_pct` is still in gate.
4. Every widening shifts league means: re-check the Step-1..7 gates in the same run;
   recenter with the *global* knob of the affected family (`offense_scale`,
   `k_scale`, `hr_scale`) — never by narrowing the slope you just widened.
5. Stop when the full gate set (old + new) passes seeds 1 and 2.

## Decision 6 — CI workflow repair (`.github/workflows/physics_sim_kpi.yml`)

Replace the whole file (current file verified: 30 lines, triggers on every push/PR,
uses the deleted `data/players_normalized.csv`, `--games 50`) with:

```yaml
name: Physics Sim KPI

on:
  pull_request:
    paths:
      - "physics_sim/**"
      - "playbalance/schedule_generator.py"
      - "scripts/physics_sim_season_kpis.py"
      - "scripts/generate_calibration_roster.py"
      - "data/calibration/**"
      - "data/MLB_avg/**"
      - ".github/workflows/physics_sim_kpi.yml"
  push:
    branches: [main]
    paths:
      - "physics_sim/**"
      - "playbalance/schedule_generator.py"
      - "scripts/physics_sim_season_kpis.py"
      - "scripts/generate_calibration_roster.py"
      - "data/calibration/**"
      - "data/MLB_avg/**"
      - ".github/workflows/physics_sim_kpi.yml"
  workflow_dispatch:

jobs:
  physics-sim-kpis:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: python -m pip install -r requirements.txt
      - name: Run KPI harness (strict, calibration fixture)
        env:
          PYTHONHASHSEED: "0"
        run: |
          mkdir -p tmp
          python scripts/physics_sim_season_kpis.py \
            --games 162 \
            --seed 1 \
            --base-dir data/calibration \
            --players data/calibration/players.csv \
            --output tmp/physics_kpis.json \
            --strict
      - name: Upload KPI report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: physics-kpis
          path: tmp/physics_kpis.json
```

Decisions: 162 games (the strict contract per Decision 4), path-filtered triggers
(the old bare `push:` burned CI on every commit), 45-min timeout (2430 games at
worst-case 0.5 s/game ≈ 21 min + setup), report always uploaded, `--ensure-lineups`
dropped (fixture lineups are committed), `--usage-gates` NOT passed (see S2-12).

## Decision 7 — Test fixes (each verified by execution during spec work)

**Context that corrects the sprint notes:** the 16 `tests/test_physics.py` failures
are **not** caused by QW-13 (a `physics_sim` change). They test the **legacy
`playbalance` engine** (archived; runtime games use physics_sim via
`game_runner._resolve_game_engine` defaulting to `"physics"`; legacy requires
`PB_ALLOW_LEGACY_ENGINE=1` + explicit `engine="legacy"`), and broke from three legacy
drifts: (a) legacy default retunes (`exitVeloSlope` .26476→.275, `exitVeloNormalPct`
85→88 in `playbalance/playbalance_config.py:157-163`), (b) the deterministic-test
fastpath added at `playbalance/simulation.py:1659-1720` that resolves empty-base PAs
as a 3-pitch strikeout **before** the pitch pipeline (`make_cfg` sets
`simDeterministicTestMode=1`, `tests/util/pbini_factory.py:22`), and (c)
`resolve_pitch` now passing `objective=` to `decide_swing`
(`playbalance/pitch_resolution.py:150-171`), which the test's `TrackingBatterAI`
override rejects. **DECISION: fix the tests (do not delete)** — the legacy engine is
still in-tree and importable, and these tests are its only pin.

Every change below in `tests/test_physics.py`:

1. **`test_launch_vector_returns_expected_components` (2 params)** — update the
   parametrize table to the current-default outputs (recomputed and verified):
   `(50, 50, 5.0, 10.0, 107.61, 0.0, 28.84)` and `(80, 80, 5.0, 20.0, 104.98, 53.49, 61.07)`.
2. **`test_landing_point_returns_expected_coordinates` (2 params)** — update to:
   `(50, 50, 5.0, 10.0, 203.53, 0.0, 1.8914)` and `(80, 80, 5.0, 20.0, 403.60, 205.65, 3.8446)`.
3. **`test_runner_advancement_respects_speed`** — replace BOTH
   `MockRandom([0.0, 0.0, 0.9, 0.9, 0.1])` with `MockRandom([0.0, 0.0, 0.0, 0.0])`
   (brute-force-verified: slow case → runner to 2B, 0 outs; fast case → runner to 3B,
   0 outs; the old sequence now lands 0.9 on the swing roll and dies to a caught foul
   via `_attempt_foul_catch`, `playbalance/simulation.py:2762-2826`).
4. **`test_home_run_scores_all_runners`** — replace `MockRandom([0.0, 0.0, 0.9, 0.1])`
   with `MockRandom([0.0, 0.0, 0.0, 0.8])` (verified: HR, batter hr=1 r=1, runs=2,
   bases cleared).
5. **`TrackingBatterAI.decide_swing`** (shared by 10 tests) — change the signature to
   ```python
   def decide_swing(self, batter, pitcher, *, pitch_type, balls=0, strikes=0,
                    dist=0, random_value=0.0, objective=None, dx=None, dy=None, **kwargs):
   ```
   (still records `dist`, still raises `CaptureDist`).
6. **`test_pitch_aim_uses_control_box_dimensions` (7 params)** — add
   `simDeterministicTestMode=0` to the `make_cfg(...)` call; replace the computed
   `expected = int(round(0.8 * max(width, height)))` with an explicit expected column
   in the parametrize table (all verified by execution):
   `fb→4, cb→5, cu→6, sl→7, scb→7, kn→8, si→9`. (`sl` is 7, not the naive 6: the
   default sl break/objective vertical offset pushes `break_dist` past `base_dist`;
   asserting the verified value keeps the test honest about the current pipeline.)
7. **`test_pitch_break_variation_affects_location` (2 params)** — in `_throw_for_dist`'s
   callers, add `simDeterministicTestMode=0` to the `make_cfg(...)` call. Expected
   values unchanged (verified: fb 0; cb 1; scb 1 — formula still holds).
8. **`test_missed_control_expands_box_and_reduces_velocity`** — add
   `simDeterministicTestMode=0` to `make_cfg`; keep the dist assertion (verified: 11);
   DELETE the `sim.last_pitch_speed` assertion (the tracker aborts the PA before the
   sim records pitch speed) and replace with a direct physics assertion (verified 4.75):
   ```python
   reduction = cfg.speedReductionBase + miss_amt * cfg.speedReductionEffMOPct / 100
   assert sim.physics.reduce_pitch_velocity_for_miss(10, miss_amt, rand=0.0) == pytest.approx(10 - reduction)
   ```

**`tests/test_simulation_averages.py`** — rewrite `test_simulated_averages_close_to_mlb`
to run entirely on the committed calibration fixture (kills both the crash and the
active-league pollution; no `auto_fill_lineup_for_team`, no monkeypatched `_team_parks`):

```python
from pathlib import Path
import csv
import scripts.physics_sim_season_kpis as kpis

CAL = Path("data/calibration")

def test_simulated_averages_close_to_mlb(monkeypatch):
    with (CAL / "teams.csv").open() as fh:
        teams = [r["team_id"] for r in csv.DictReader(fh)][:2]
    monkeypatch.setattr(kpis, "_team_ids", lambda *a, **k: [kpis._normalize_team_id(t) for t in teams])
    monkeypatch.setattr(kpis, "_team_parks", lambda *a, **k: {})
    metrics = kpis.run_sim(
        games_per_team=20, seed=1,
        players_path=CAL / "players.csv",
        base_dir=CAL,
    )["metrics"]
    assert 0.20 <= metrics["avg"] <= 0.30
    assert 0.28 <= metrics["obp"] <= 0.36
    assert 0.33 <= metrics["slg"] <= 0.46
    assert 3.5 <= metrics["pitches_per_pa"] <= 4.2
    assert 0.17 <= metrics["k_pct"] <= 0.27
    assert 0.05 <= metrics["bb_pct"] <= 0.11
```
(20 games × 2 teams ≈ 20 games total — same cost as today's 10×2; bands are the old
bands tightened around the now-calibrated engine.)

## Files to change (verified anchors)

| File | Change |
|---|---|
| `scripts/generate_calibration_roster.py` | NEW — Decision 1 |
| `data/calibration/**` | NEW committed fixture (generator output) |
| `scripts/physics_sim_season_kpis.py:27-61` | new tolerance rows (Decision 3) |
| `scripts/physics_sim_season_kpis.py:206-225` | `_team_ids`/`_team_parks` take `teams_csv` |
| `scripts/physics_sim_season_kpis.py:516-521` | `run_sim(..., base_dir=None)` |
| `scripts/physics_sim_season_kpis.py:615-624` | pass `base_dir=` to `simulate_matchup_from_files` |
| `scripts/physics_sim_season_kpis.py:759-762` | qualification thresholds 3.1 PA / 1.0 IP per team-game |
| `scripts/physics_sim_season_kpis.py:825` | insert dispersion metrics block (Decision 4) |
| `scripts/physics_sim_season_kpis.py:499` | skip `None` metrics in `evaluate_tolerances` |
| `scripts/physics_sim_season_kpis.py:836-863` | `--base-dir` arg |
| `data/MLB_avg/mlb_league_benchmarks_2025_filled.csv` | append 13 rows (Decision 3) |
| `physics_sim/config.py:326-327` | softcap 107.0 / 0.70 + Step-1..7 retunes |
| `physics_sim/physics.py:678-679` | eye divisors 160 / 190 |
| `.github/workflows/physics_sim_kpi.yml` | full replacement (Decision 6) |
| `tests/test_physics.py` | 8 itemized fixes (Decision 7) |
| `tests/test_simulation_averages.py` | full rewrite (Decision 7) |
| `docs/deep_review_plan.md` | S2-08 status + changelog entry on completion |

## Edge cases

- `evaluate_tolerances` must skip `None` metric values (small-league qualified pools).
- `qualified_hr30_count` includes the 40+ players by definition (MLB convention).
- `pstdev` on a 1-element list returns 0.0 — covered by the <10-player `None` guard.
- Roster CSVs are headerless; `load_roster_status` treats row[1] as status — the
  generator must not emit a header row in `rosters/*.csv`.
- `PitcherRatings.velocity` derives from `arm` (`models.py:105`) — do not emit a
  `velocity` column.
- Windows line endings: write all fixture CSVs with `newline=""` and UTF-8 (matches
  every loader).
- The fixture league must never be resolvable as the "active league" — it lives under
  `data/calibration`, not `data/leagues/`.

## Test plan (exact)

```
python scripts/generate_calibration_roster.py --output-dir data/calibration --seed 20260715
python scripts/generate_calibration_roster.py --output-dir /tmp/cal2 --seed 20260715  # then diff -r: byte-identical
python scripts/physics_sim_season_kpis.py --games 162 --seed 1 --base-dir data/calibration --players data/calibration/players.csv --output tmp/k1.json --strict
python scripts/physics_sim_season_kpis.py --games 162 --seed 2 --base-dir data/calibration --players data/calibration/players.csv --output tmp/k2.json --strict
python -m pytest tests/test_physics.py tests/test_simulation_averages.py -q   # 50 passed
git status --porcelain data/leagues/   # MUST be empty after the pytest run (no league pollution)
```
New unit tests (add `tests/test_calibration_fixture.py`):
- `test_generator_deterministic` — two runs, same seed, identical SHA256 over all files.
- `test_fixture_shape` — 30 teams, 780 players, 26 ACT/team, 13 pitching rows/team,
  9 lineup slots/team, every stadium resolves via `stadium_from_name`.
- `test_dispersion_metrics_math` — feed `run_sim`-shaped synthetic `batter_totals`
  into the extracted dispersion function (extract it as
  `_dispersion_metrics(batter_totals, pitcher_totals, games_per_team, teams) -> dict`)
  and assert hand-computed SD/count values, incl. the `None` small-pool guard.
CI: push a branch touching `physics_sim/config.py` → workflow runs → green.

## Non-goals

- Platoon lineups (S2-01), TTO bonus (S2-07 — separate spec), usage gates (S2-12 —
  separate spec, opt-in), park-factor realism (S3-01), fixing
  `scripts/normalize_players.py` for live-league use (unchanged; it remains a
  live-roster tool), the pytest league-sandbox fixture (carry-over item — the
  rewritten averages test simply stops polluting), deleting the legacy playbalance
  engine.
