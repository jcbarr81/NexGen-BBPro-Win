# Mechanism map: baserunning and defense (current engine, 7.45.8)

Scope: `sp` (speed), hitter `fa` (fielding) and `arm`, catcher `fa`/`arm`, pitcher `hold_runner`/`arm`/`fa`,
positional adjustments, pinch runners, pinch hitters and defensive subs. All paths are relative to the repo root.
Both the live path (`playbalance/game_runner.py:1052-1161`) and the KPI harness load ratings the same way
(`physics_sim/data_loader.py` -> `BatterRatings.from_row` / `PitcherRatings.from_row`). The alpha-test league has
no `physics_tuning_overrides.json`, so `DEFAULT_TUNING` applies unchanged.

## Evidence used

- Code reading of `physics_sim/engine.py`, `physics_sim/fielding.py`, `physics_sim/physics.py`,
  `physics_sim/models.py`, `physics_sim/config.py`, `playbalance/field_geometry.py`.
- **Instrumented seasons** (my driver, `work/map-running-defense/driver.py`): it wraps `_attempt_steal`,
  `_resolve_ground_out`, `_advance_on_hit`, `_advance_on_air_out` and `_maybe_upgrade_hit` to log every exposure,
  using `simulate_matchup_from_files`, the same physics path the harness uses.
  - Calibration fixture (wide ratings), 2,430 games, seeds 1 and 2: `calib_s1.json`, `calib_s2.json`.
  - A copy of the alpha-test resim league (compressed ratings), 1,620 games, seed 1: `alpha_s1.json`.
- `datasets/current_engine_players.json`: 910 alpha games on today's code; 195 hitters with at least 150 PA.
- Unit probes of the runner functions (`probe_groundout.py`) and a WP/PB check (`wpcheck.py`).
- MLB reference from `data/MLB_avg/Teams_last5years.csv`, 2024 season: SB/G .745, CS/G .198, SB% .790,
  SBA/PA .0252, 3B/G .143, E/G .534, DP/G .759, SF/PA .0069. Advancement figures (1st-to-3rd on a single,
  scoring from 2nd on a single, scoring from 1st on a double) are my approximate recollection of public
  extra-bases-taken data and are flagged "~" wherever they appear.

## Rating scale and spreads

Ratings are on a 0-100 scale centred at 50. Every formula below is linear in `(rating - 50)`. There is no 20-80
mapping.

| rating | alpha-test (live players.csv) | calibration fixture |
|---|---|---|
| hitter `sp` | n=586, 26-93, sd 10.0, **but trimodal**: 453 players at 48-52, 63 at exactly 70, 16 at 85, nothing between 53 and 69 | n=390, 30-67, sd 8.0, continuous |
| hitter `fa` | 28-57, sd **3.0** (p10-p90 48-52) | 25-73, sd 8.9 |
| hitter `arm` | 31-59, sd **2.5** | 29-71, sd 8.6 |
| catcher `fa` / `arm` | sd **1.8 / 2.0** (arm 38-54) | sd 7.9 / 8.0 |
| catcher `sp` (mean) | 52.9, the same as the league | 38.5 |
| positional means of `fa` | all 48.6-50.0 (an SS fields no better than a 1B) | SS 54.7, C 54.7, 2B 53.9 ... DH 41.3 |
| pitcher `hold_runner` | 23-66, sd **4.1** (p10-p90 48-52) | 25-82, sd 9.9 |
| pitcher `arm` (= velocity) | 35-57, sd 2.7 | 33-75, sd 6.9 |
| pitcher `fa` | sd 3.9 | sd 7.5 (**dead**, see below) |
| hitters with `other_positions` | 69 of 586 | 90 of 390 |

What these spreads mean for alpha-test:
- Every defensive rating (`fa`, `arm`, catcher `arm`, `hold_runner`) is effectively constant. Measured in-sim over
  steal exposures: catcher arm sd 1.3, hold sd 1.5. Their effects exist only on the calibration fixture.
- In alpha-test, defense is driven far more by **positional assignment** (the 0.75 out-of-position multiplier
  turns 50 into 37.5) than by the ratings themselves.
- `sp` is the only rating in scope with real spread in alpha-test, but it behaves like three tiers (50 / 70 / 85),
  so any "speed curve" measured on alpha is really a comparison of three groups.

## 1. Speed (`sp`)

Read at `models.py:23,64` (`speed=f("sp")`). Batter fatigue scales it down at `engine.py:3040,3051`
(`speed * (1 - penalty*0.5)`). Speed is used in the places below and nowhere else.

### 1a. Stolen bases: attempt decision

`engine.py:1946-1966` `_steal_attempt_rate`. It runs once **per pitch** after every ball, strike or foul that does
not end the PA (`engine.py:5285, 5410`), and only if no WP/PB or pickoff happened on that pitch.

```python
attempt = base_rate * steal_freq_scale          # 0.045 * 3.0 = 0.135 (R1, 2B open)
attempt *= 0.5 + (speed - 50.0) / 60.0          # 0 at sp 20, 0.5 at 50, 1.0 at 80, 1.32 at 99
attempt *= 1.0 - (pitcher_hold - 50.0) / 180.0
attempt *= 1.0 - (pitcher_arm - 50.0) / 260.0 * steal_pitcher_arm_deterrent
attempt *= 1.0 - (catcher_arm - 50.0) / 220.0
attempt *= 1.0 - (catcher_fielding - 50.0) / 260.0 * steal_catcher_fielding_deterrent
return max(0.001, min(0.25, attempt))
```

- Knobs: `steal_attempt_rate_first` 0.045, `_second` 0.015, `_home` 0.002, `steal_freq_scale` **3.0**,
  `double_steal_rate` 0.003, deterrent scales 1.0.
- A context multiplier (`engine.py:1969-1997`) adjusts for count, outs, inning and score: ×1.25 at 2+ balls ahead,
  ×0.75 at 2+ strikes ahead, ×1.2 when close and late, and so on. It is clamped to 0.1-3.0.
- Per-pitch attempt probability for an average runner (sp 50) on 1st alone: **0.0675**.
- Marginal effect: **+10 sp adds +0.0225 per pitch (+33% relative)**.
  - Measured on calibration: +0.019 per 10 points.
  - Fastest band (65-75) vs slowest (35-45): 0.087 vs 0.039 per pitch, only **2.2x**.
  - Alpha-test: sp 85+ at 0.129 vs sp 48-52 at 0.061, **2.1x**.
- The curve is too flat. Real steal attempts are concentrated in the fastest runners (often more than 10x the
  average runner). Here average and below-average runners steal a lot: alpha runners at sp 40-50 attempt on about
  26% of their times on first.
- Outcome rates:
  - Calibration: SBA/PA **0.052**, which matches the harness benchmark `sba_per_pa=0.050`.
  - Alpha-test resim: SBA/PA **0.0675**, SB/G **2.22**.
  - Alpha 910-game dataset: SBA/PA 0.077, about 29% of times on first.
  - MLB 2024: SBA/PA **0.025**, SB/G 0.745. This confirms the harness benchmark is 2x too high and that the
    engine runs 2-3x MLB.
- Player level, alpha dataset: r(sp, SB/PA) = +0.77 (partial r controlling ch/ph/eye +0.72), n=195,
  sp 38-92, sd 10.4. Speed does drive steals. The problem is the volume and the shape of the curve.

### 1b. Stolen bases: success

`engine.py:2000-2019` `_steal_success_prob`:

```python
base = steal_success_base (0.80) + (speed-50)/150 - (hold-50)/250 - (p_arm-50)/300
       - (c_arm-50)/220 - (c_fa-50)/280 ;  clamp [0.10, 0.95]
```

- Marginal effects per +10 points: **sp +0.067** (measured +0.061 to +0.078), hold -0.040 (measured -0.032 to
  -0.045), pitcher arm -0.033 (measured -0.031), catcher arm -0.045 (measured -0.051 to -0.057), catcher fa -0.036.
- **Saturates at sp ≥ 72.5** when everything else is 50. The alpha 70-tier is right at the cap and the 85-tier is
  capped: measured success 0.923 for sp 65-75 and 0.966 for sp 85+.
- League SB%: calibration 0.745, alpha resim 0.837, alpha dataset 0.718. MLB is 0.790.
- Home steals: success is multiplied by `steal_home_success_scale` 0.6.

### 1c. Double steal (`engine.py:2083-2118`)

`double_rate = 0.003 * steal_freq_scale * context`, which is **0.9% per pitch with R1+R2, independent of speed,
hold and catcher**. A slow pair of runners double-steals as often as a fast pair. Speed only enters through the
two success rolls.

### 1d. Pickoffs (`engine.py:1801-1900`, called at `5338`)

- Attempt rate: `0.004 * (0.7 + (sp-50)/120) * (0.8 + (hold-50)/140)`, clamped [0.0002, 0.05] per pitch. Faster
  runners draw more throws.
- Success: `0.045 + (hold-50)/240 + (p_arm-50)/320` (×`pickoff_arm_scale`) `+ (team_avg_arm-50)/260 - (sp-50)/200`,
  clamped [0.01, 0.5].
- Measured volume is about 0.007 pickoffs per team-game, so this is negligible as a run factor.
- `_pickoff_caught_stealing` (`1903-1943`) re-rolls the steal-attempt rate only to label a successful pickoff as
  POCS. This is cosmetic.

### 1e. Leads: cosmetic only

`_lead_level` (`engine.py:1231-1257`) and `_update_runner_leads` (`1260-1281`, called every pitch at `4345`)
compute a lead level from `sp ≥ lead_speed_threshold` (70), `≥ lead_speed_aggressive` (85) and
`hold ≥ lead_hold_threshold` (70). The level is only **added to the batter's `lead` stat** (`1140`). No steal,
pickoff or advancement formula reads it.
- **Knobs `lead_*` (6 of them) have no gameplay effect.**
- The 70/85 thresholds coincide with the alpha speed tiers at exactly 70 and 85, which suggests a generator or
  normalizer snapped speedsters to these values.

### 1f. Extra bases on hits (`engine.py:1308-1355`, `1356-1540`)

```python
_advance_prob   = clamp(0.05, 0.95, (0.45 + (sp-50)/200 - (arm-50)/250 + extra) * advancement_aggression_scale[1.6])
_out_on_base_prob = clamp(0.01, 0.55, (extra_base_out_base[0.06] + extra + (arm-50)/200 - (sp-50)/240) * 1.0)
```

The arm used is that of the fielder at the batted-ball spray position (`4757-4777`).

| situation | attempt extra / out extra | attempt at sp 50 | saturates (95%) at |
|---|---|---|---|
| R3 on single/double | force=True (always runs) / -0.02 | 100% | n/a |
| R2 on single | +0.15 / +0.05 | 0.96 → **0.95** | **sp ≥ 49** |
| R1 on single, 3B open | +0.05 / +0.08 | 0.80 | sp ≥ 69 |
| R2 on double | force=True / +0.02 | 100% | n/a |
| R1 on double | -0.05 / +0.12 | 0.64 | sp ≥ 89 |
| tag-up R3 (air out, <2 outs) | `tag_up_third_extra` 0.25 | 1.12 → **0.95** | **sp ≥ 19** (all players) |
| tag-up R2 → 3B | 0.05 | 0.80 | sp ≥ 69 |
| WP/PB R3 / R2 / R1 | 0.20 / 0.10 / 0.05 | 0.95 / 0.88 / 0.80 | |

Measured outcomes (calibration seeds 1/2, alpha resim), compared with MLB:

| situation | engine result | MLB (approximate) |
|---|---|---|
| R1 on single, 3B open | to 3B **65-74%**, **thrown out 9-12%** | ~28% to 3B, ~1-2% out |
| R2 on single | scores **81-86%**, **out ~10%** | ~60% scores, ~4% out |
| R1 on double | scores **52-58%**, **out ~11%** | ~40-45% scores, ~3-4% out |
| outs on bases per team-game | **0.40-0.43** | ~0.3 |

- Outfield assists come out at 0.09-0.12 per position-game, about 1.5-2x MLB. This follows from all the throw-outs.
- Speed does work here: in alpha, the sp 70+ group goes 1st-to-3rd 90% vs 69% for sp ~50.
- The base aggression is too high. `advancement_aggression_scale` 1.6 also multiplies the speed and arm terms,
  so it amplifies them by 1.6 before the clamp, and pushes most cases into the 0.95 ceiling.

### 1g. Doubles and triples

There are two separate speed effects.

1. **Distance thresholds** (`physics.py:1044-1075`):
   - `double_threshold = wall * 0.82 * double_distance_scale(0.70) * (1 - speed_norm*0.18) * (1 - gap_norm*0.45)`
   - `triple_threshold = wall * 0.97 * triple_distance_scale(0.96) * (1 - speed_norm*0.28)`
   - `speed_norm = (sp-50)/50` is clamped to ±1. At sp 80 the triple threshold drops 17%.
   - Below sp ~37 the triple threshold exceeds the wall, so those runners cannot triple on distance.
2. **Stretch upgrade** (`engine.py:1543-1572`), LD/FB hits only:
   - `chance = base + max(0,(sp-50)/50)*scale`, then `*= max(0.1, 1 - arm/100*arm_scale)`.
   - Knobs: `stretch_double_base` 0.02, `_speed_scale` 0.18, `_arm_scale` 0.7; triple 0.006 / 0.12 / 0.9.
   - Speed below 50 gives no penalty here (one-sided).
   - Measured single→double: 1.4% (sp<50), 2.1% (50-60), 3.3-3.9% (60-70), 6.7% (alpha 70+).

Outcomes:
- 3B/G is 0.13-0.14 on calibration (MLB 0.143), but **0.238 on alpha resim** (alpha dataset 3B/PA 0.0063 vs MLB
  0.0038). Alpha's 70/85 speed tiers combine with these two stacked speed effects.
- Alpha dataset: r(sp, 3B/PA) = +0.61 (partial +0.60). r(sp, 3B/(2B+3B)) = +0.56.
- r(sp, 2B/PA) = -0.11 (partial +0.17). Speed slightly lowers doubles because it converts them to triples.

### 1h. What speed does NOT affect

- **No infield hits.** `out_probability` (`fielding.py:158-233`) has no batter-speed input. The hit/out roll at
  `engine.py:4727-4741` uses only EV, ball type, spray, pull and team defense.
  - Measured GB hit rate vs batter speed: r = -0.09 (calibration, n=270) and -0.13 (alpha, n=186). The slope per
    +10 sp is -0.002, i.e. none.
  - Alpha dataset: r(sp, BABIP) = -0.03.
  - League GB hit rate is 0.187-0.201 vs MLB ~0.24.
  - In MLB, speed is the main non-contact BABIP skill. Here it is absent.
- **GIDP ignores the batter's speed.** `double_play_probability` (`fielding.py:236-251`) receives
  `runner_speed=bases.first.speed` only (`engine.py:2383-2388`).
  - Measured per GIDP opportunity, per +10 points: batter speed +0.002 / +0.005 / -0.004 (null) vs runner speed
    -0.04.
  - Alpha dataset: r(sp, GIDP/PA) = -0.12.
  - In MLB, batter speed is the main GIDP-avoidance skill.
- **No reached-on-error effect.** Alpha r(sp, ROE/PA) = +0.03.
- **No fielding effect.** Speed is never read on defense. Outfield and infield range come only from `fa`.

### 1i. Bunts (`engine.py:2792-2899`)

- Attempt: per PA in qualifying situations, `bunt_attempt_rate` 0.03, ×1.2 if sp ≥ 60, ×0.6 if ph ≥ 60.
- Bunt-hit chance: `0.03 + (sp-50)/250 + (ch-50)/300 - (team_inf-50)/400`, clamped [0, 0.2].
- Bunt DP: `0.08 + (inf-50)/300 - (R1 sp-50)/350`.
- A bunt hit is advanced with `_advance_on_hit("single")`, so **R1 goes first-to-third on a bunt single about
  80% of the time.**

### 1j. Ground outs and runner speed (`engine.py:2304-2410`)

- Runner on 3rd scores on a ground out with probability `ground_rbi_prob 0.25 + (sp-50)/400`.
- FC force probability: `0.55 + (range-50)/200 + (turn_arm-50)/320 - (R1 sp-50)/220`.
- Triple play: `0.0008 + (range-50)/900 - (sp1-50)/800 - (sp2-50)/800`.

## 2. Catcher `arm` / `fa`, pitcher `hold_runner` / `arm` vs the running game

- `_catcher_context` (`engine.py:1721-1733`) reads the catcher's `fa` (×position scale ×`range_scale`) and `arm`
  (×`arm_strength_scale`). These are recomputed each half-inning (`3758`).
- Catcher `arm` is used for:
  - steal attempt `/220` and success `/220`;
  - WP/PB advancement (`2188-2218`) and dropped-third-strike advancement.
- Catcher `fa` is used for:
  - steal attempt `/260` and success `/280`;
  - passed balls: `pb_rate *= 1 + (50-fa)/100`, so +10 fa gives -10% PB (`2221-2250`). Measured r(fa, PB/G) =
    -0.48 to -0.52 on calibration;
  - K-in-dirt: `*(1+(50-fa)/140)`;
  - **framing** (`physics.py:500-530`): `margin += (fa-50)/100*framing_margin_scale(0.01)`, which is
    **+0.001 ft per +10 fa**, and `prob += (fa-50)/100*framing_prob_scale(0.1)`, which is **+1 point** on
    borderline calls per +10 fa. **Effectively cosmetic.**
- Measured catcher CS% vs arm:
  - calibration: r = +0.57 / +0.72 (n=36, arm 32-68, sd 8.4); league CS% 0.26 vs MLB ~0.21;
  - alpha resim: r = +0.08 (arm 48-52); league CS% 0.164.
- Catcher arm barely deters attempts: r(arm, SBA/G) = -0.11 / -0.17. Its formula weight is `/220`, so +10 arm
  gives only -4.5% relative attempts.
- `hold_runner` (`models.py:119`) is used for:
  - steal attempt `×(1-(h-50)/180)`, so +10 gives -5.6% relative (measured -0.003 to -0.004 per pitch on a base
    of 0.056);
  - steal success -0.04 per 10;
  - pickoff attempts and success;
  - the cosmetic lead stat.
  - Measured r(hold, CS% against) = +0.36 / +0.38 on calibration (n=373, hold sd 10) and +0.15 on alpha
    (hold sd 1.5).
- **Pitcher `arm` is the velocity rating.** `models.py:114,123` reads `velocity=f("arm")` and `arm=f("arm")`.
  The same value sets fastball speed (`engine.py:4329`: `83 + arm*0.2`) and deters steals (`/260`), cuts steal
  success (`/300`) and raises pickoff success (`/320`).
  - This is double use of one rating: hard throwers are automatically better at holding runners.
  - Effect: -0.031 success per +10 arm. Small, but it is wrong semantically. Time to the plate is not velocity.

## 3. Fielding (`fa`), `arm` and positions

### 3a. Defensive alignment and positional adjustment

- `build_defense_from_lineup` / `build_default_defense` (`fielding.py:28-84`) fill unfilled positions with
  `max(fielding)`.
- `adjusted_fielding_rating` (`fielding.py:139-151`) is a **multiplicative** scale on `fa`:
  - primary position ×1.0 (`defense_primary_pos_scale`);
  - listed `other_positions` ×0.9;
  - any other position ×0.75.
- Issues:
  - **No position-difficulty term.** An fa-60 player rates 60 at SS and 60 at 1B. Positional value is not modelled
    at all. Alpha's `fa` means are the same at every position (48.6-50.0).
  - **Multiplicative penalty**: it takes 20 points from an fa-80 player out of position but 10 from an fa-40
    player, so better fielders lose more. A 0.75 rating also implies that a catcher playing SS is "37.5", which in
    alpha is a bigger swing than the whole rating spread (sd 3). Only 69 of 586 alpha hitters list
    `other_positions`.
  - **`arm` gets no positional adjustment** (`adjusted_arm_rating`, `fielding.py:154`, only ×`arm_strength_scale`).
- The defense map and `DefenseRatings` are rebuilt once per half-inning (`engine.py:3744-3760`) after any
  defensive sub.

### 3b. Hit-vs-out (range): `out_probability` (`fielding.py:158-233`)

- Team-zone ratings come from `compute_defense_ratings` (`fielding.py:87-136`):
  - `infield_left` = mean of 3B and SS;
  - `infield_right` = mean of 1B and 2B;
  - LF, CF and RF individually, chosen by spray angle (`spray_center_band_deg` 8°);
  - all ×`range_scale` 1.0.
- Formula:

  ```python
  gb: out = 0.78 + (zone-50)/250 ; ld: 0.38 + (zone-50)/300 ; fb: 0.73 + (zone-50)/230
  out -= (EV-90)/300 ; shift term (pull ≥ 60) ±0.04 gb / ±0.015 ld ; clamp [0.02, 0.98]
  hit_prob = (1-out) * babip_scale(0.925)
  ```

- Marginal effects:
  - **+10 zone rating gives -0.040 GB hit probability, -0.033 LD and -0.043 FB.**
  - One infielder moving +10 shifts his zone by +5, i.e. about -0.02 GB hit probability on his side.
  - An outfielder owns his zone alone, so +10 gives about -0.04 on fly balls hit to him.
- In alpha (fa sd 3), team-zone ratings vary by about ±1-2 points, worth about ±0.005 BABIP. That is **dead in
  practice** and swamped by binomial noise.
- Range is `fa` only. `sp` never enters it.
- Shift: `shift_pull_threshold` 60, `shift_gb_boost` 0.04, `shift_ld_boost` 0.015.

### 3c. Errors (`fielding.py:265-282`, called at `engine.py:4846-4889`)

- An error can only happen on a ball already ruled an out. The fielder is the one at the spray position
  (`_fielder_ratings`, `engine.py:1705-1719`).

  ```python
  prob = (base + (50-fa)/500 + (50-arm)/900) * error_rate_scale ; clamp [0.001, 0.12]
  base: gb 0.018, ld 0.012, fb 0.008
  ```

- **+10 fa gives -0.020 per out-chance**, which is more than the entire GB base rate.
- **Saturates at the floor (0.001)** once fa ≥ 58.5 for grounders, ≥ 55.5 for liners and **≥ 53.5 for fly balls**
  (with arm 50). Every outfielder above about 54 makes the same 0.1% fly-ball errors, so the upper half of the
  scale is clamped flat.
- The rating does work at the low end. Measured r(fa, E/TC) on calibration by position: -0.59 to -0.84, with fa
  sd 7-10.
- **League errors are about 40-50% of MLB**: E/G 0.21-0.22 on calibration and 0.28 on alpha, vs MLB 0.534.
  Causes:
  - **pitchers never field** (pitcher PO/A/E from batted balls = 0);
  - **catchers are never charged errors** (calibration catcher E = 0; no throwing errors on steal attempts);
  - outfielders are floored.
- `select_error_type` (`fielding.py:285-303`) uses arm and fa to choose throwing vs fielding error. **Cosmetic**:
  both branches run the same `_advance_on_error`, and only the `e_throw`/`e_field` totals differ.
- Knobs: `error_rate_gb/ld/fb`, `error_rate_scale` 1.0, `throwing_error_share_*`.

### 3d. Throwing errors on advancement (`engine.py:1324-1329`)

`clamp(0.001, 0.08, (0.015 + (50-arm)/300) * 1.0)`. It is only rolled after a runner is already ruled out, so it
is rare: `e_th` occurred 20-28 times per 2,430 games.

### 3e. Double plays (`fielding.py:236-251`; `engine.py:2304-2410`)

- Inputs:
  - `infield_range` = mean of the adjusted `fa` of the primary fielder and the pivot fielder;
  - `turn_arm` = mean of the arms of the primary fielder, the pivot and the 1B.

  ```python
  dp = 0.32 + (range-50)/230*1.2 + (turn_arm-50)/260*1.2 - (R1 sp-50)/220 ; clamp [0.03, 0.45]
  ```

- Marginal effects per +10 points: range +0.052, arm +0.046, runner speed -0.045. **The batter's speed is absent.**
- The cap of 0.45 is reached by, for example, range 60 + arm 62 + an R1 at sp 40.
- Measured:
  - GIDP per opportunity (ground out, R1, <2 outs): 0.35 on calibration, 0.29 on alpha.
  - GIDP/G: 0.53 calibration, 0.46 alpha, vs MLB ~0.7. It is low partly because R1 is so often gone by steal.
  - r(fa, DP/G) for SS: +0.48 / +0.52 on calibration.

### 3f. Assists and putouts by position

Calibration seeds 1/2 vs approximate MLB:

| position | engine | MLB (approximate) |
|---|---|---|
| 3B | A/G 0.75, PO/G 0.36 | ~1.9 A, ~0.7 PO |
| SS | A/G 3.6 | ~2.9 |
| 2B | A/G 3.1 | ~2.8 |
| CF | PO/G 2.1 | ~2.6 |
| LF / RF | PO/G 2.3 | ~1.9 |

- **3B is under-used.** `_infield_pos_for_spray` (`engine.py:1752-1761`) gives 3B only spray ≥ 25°.
- **CF is under-used relative to the corners**, which is inverted vs MLB. The CF band is ±8° (`1764-1768`).
- Outfield assists track arm well: r(arm, A/G) = +0.55 to +0.72. They come almost entirely from the excessive
  runner throw-outs (§1f).
- **Every strikeout credits the pitcher with an assist.** `engine.py:4598-4603` and `4654-4659`:
  `_fielding_line(..., pitcher).a += outs_added`.
  - In the alpha dataset, pitcher A = 14,080 against SO = 14,377. In calibration, A = 42,231 against K = 43,102.
  - Pitchers have no other PO, A or E.
  - This is a scoring bug. The catcher already gets the PO. It is cosmetic for outcomes but pollutes fielding
    stats.

### 3g. Pitcher `fa`: dead

`PitcherRatings.fielding` (`models.py:122`) is loaded and never read anywhere in `physics_sim/`. Pitchers do not
appear in the defense map. "P" is only a fallback name for 1B in `_find_fielder`, and it resolves against batter
objects.

## 4. Substitutions

- **Pinch runner** (`engine.py:2667-2696`, applied at `2699-2745`):
  - only from inning ≥ 7 (`pinch_run_inning`);
  - only when the runner is the tying or go-ahead run;
  - only when the runner's sp < 55 (`pinch_run_speed_min`);
  - picks the fastest bench player with sp ≥ runner + 8 (`pinch_run_speed_diff`).
  - Measured 0.17-0.21 per team-game.
  - **There is no catcher guard.** `_select_pinch_hitter` protects the last catcher; the pinch-runner logic does
    not. The pinch runner inherits the position (`_apply_substitution`, `2557-2594`), so a speedster can end up
    catching at ×0.75. A defensive sub repairs this only when the team is tied or leading (`2533-2538`).
- **Pinch hitter** (`2596-2648`):
  - inning ≥ 7, within 2 runs;
  - score = `ch*0.55 + ph*0.45 + platoon` (`2444-2445`);
  - needs an advantage of ≥ 6 (`pinch_hit_advantage_min`), with an 8-point penalty if the PH cannot play the
    vacated position.
  - It **ignores eye and speed**.
  - Measured 0.02 per team-game on calibration and 0.31 on alpha (bench composition).
- **Defensive sub** (`2485-2557`):
  - inning ≥ 7, leading or tied by ≤ 2;
  - uses `fa` only (×position scale) and needs a gain ≥ 8 (`defensive_sub_fielding_diff`);
  - **arm is ignored.**
  - Measured 0.36 per team-game on calibration and 0.11 on alpha. In alpha, almost every qualifying gain comes from
    replacing an out-of-position player, because the fa spread is smaller than the 8-point threshold.

## 5. Correctness bugs found (verified by probe or measurement)

1. **Runner on 2nd is erased on a ground out with R1+R2.** At `engine.py:2400-2408`, the non-DP, non-FC branch
   runs `bases.second = bases.first`, which overwrites an occupied 2nd base.
   - Probe (R1+R2, 0 out, all ratings 50): **24.4% of ground outs end with R2 deleted** (not scored, not out).
   - In the FC branch (`2397-2399`), R2 is never forced to 3rd: 38% of the time he stays on 2nd.
   - With bases loaded, R3 is not forced home either; he scores only through `ground_rbi_prob`.
2. **Forced runner "holds" at 1st.** In the same branch, when `_advance_prob` fails (~20%), R1 stays on 1st while
   the batter is retired at 1st. The probe gives 6.1% of R1-only ground outs, which is impossible in baseball.
3. **An R2-only ground out never advances the runner** (probe: 100% stays). There are no productive outs.
4. **Tag-ups on every air out.** `_advance_on_air_out` (`1664-1702`) is called for all flyouts *and* lineouts,
   including infield lineouts (`select_out_type` gives `infield_play` 45% for low liners) and pop-ups.
   - R3 always goes. Attempt success is 0.95 regardless of speed (saturated), and every failure is an out at home.
   - Measured 95.0% scored / 5.0% out on all three runs, flat across speed bins.
   - SF/PA is 0.0087-0.0115 vs MLB 0.0069.
5. **Steals on foul balls.** The steal and pickoff block runs for `outcome == "foul"` (`5285`).
   - **26% of all SB/CS events** (2,523 of 9,664) happen on a foul pitch, where in reality the runner is sent back.
6. **WP/PB with empty bases and on fouls.** `if runner_event is None:` at `5310` sits outside the runners-on guard
   at `5301`.
   - In 600 games, **54% of missed-pitch events occurred with the bases empty**, and **22% were on foul balls**.
   - WP/G is 0.53 and **PB/G 0.37-0.40** vs MLB ~0.35 WP and ~0.07 PB. This inflates catcher `fa`'s PB effect and
     pitcher WP lines.
7. **Pitcher assist on every strikeout** (`4598-4603`, `4654-4659`). See §3f.

## 6. Dead, cosmetic and saturated summary

| item | status | where |
|---|---|---|
| pitcher `fa` | **dead** (loaded, never read) | `models.py:122` |
| `lead_speed_threshold`, `lead_speed_aggressive`, `lead_hold_threshold`, `lead_ball_bonus`, `lead_two_strike_penalty`, `lead_two_out_penalty` | **cosmetic** (feed only the `lead` stat) | `engine.py:1231-1281` |
| `select_error_type` (arm/fa) | cosmetic (label only) | `fielding.py:285-303` |
| catcher framing via `fa` | ~cosmetic (+0.001 ft, +1 pt per 10 fa) | `physics.py:510-527`, `config.py:101-103` |
| `_pickoff_caught_stealing` | label only | `engine.py:1903` |
| `sp` in steal success | saturates at sp ≥ 72.5 (cap 0.95) | `engine.py:2018` |
| `sp` in R2-on-single and tag-from-3rd | saturated for essentially everyone (≥ 49 / ≥ 19) | `engine.py:1308-1311` with `advancement_aggression_scale` 1.6 |
| `fa` in errors | floor 0.001 at fa ≥ 53.5 (FB), 55.5 (LD), 58.5 (GB) | `fielding.py:279-282` |
| DP probability | cap 0.45 | `fielding.py:251` |
| `sp` in stretch upgrades | one-sided (sp < 50 no effect) | `engine.py:1555` |
| `sp` in infield hits, batter GIDP, ROE, fielding range | **absent** | `fielding.py:158-251` |
| `arm` positional adjustment, arm in defensive subs | absent | `fielding.py:154`, `engine.py:2485` |
| pitcher `arm` | double-counted (velocity and holding runners) | `models.py:114,123`; `engine.py:1960,2012,1824` |
| double-steal attempt | ignores speed, hold and catcher | `engine.py:2083-2086` |
| alpha `fa`/`arm`/`hold_runner`/catcher arm | **dead in practice** (sd 1.3-4) | compressed data, not code |
| alpha `sp` | trimodal 50/70/85 | data |

## 7. Noise terms that can drown rating differences

- Steals: per-pitch Bernoulli rolls (~0.06) compounded over 2-4 pitches per time on base. Speed effects are large
  enough to survive this (r = 0.77 at player level).
- Hit/out: one Bernoulli roll per ball in play. A 10-point zone gap is ±0.04 against an SD of ~0.45 per ball. On
  the fixture it needs hundreds of chances per fielder to show. On alpha it is invisible.
- Errors: about 0.5% of out-chances. A season-level E/TC difference needs n ≥ 300 chances. Clamping also removes
  the upper tail.
- `select_out_type`: a 45% random infield/outfield flag for low liners (`fielding.py:261`) decides which fielder's
  rating is used and whether a tag-up happens.
- Exit velocity noise (`exit_velo_sd` 5.0) feeds `quality_adj` (`(EV-90)/300`): ±5 mph is ±0.017 out probability,
  the same order as a 4-point team defense gap.

## 8. Expected-effect cheat sheet (+10 rating points, all else 50)

| rating | effect |
|---|---|
| `sp` (runner) | +0.0225 steal attempts per pitch (+33% relative); +0.067 SB success; 1st-to-3rd on a single +0.08 attempt (to cap at 69); out-on-bases -0.042; GIDP (as R1) -0.045; triple threshold -5.6% distance; stretch double +3.6 pts × arm factor |
| `sp` (batter) | GB/infield hit 0; GIDP 0; ROE 0; bunt hit +0.04 |
| hitter `fa` (zone) | GB out +0.04, LD +0.033, FB +0.043; errors -0.020 per chance (floored); DP +0.052 |
| hitter `arm` | runner attempt -0.064 (×1.6), out-on-bases +0.05; DP turn +0.046; errors -0.011; OF stretch-upgrade penalty |
| catcher `arm` | steal attempt -4.5% relative; success -0.045 |
| catcher `fa` | steal attempt -3.8% relative; success -0.036; PB -10%; framing +1 pt on borderline calls |
| `hold_runner` | steal attempt -5.6% relative; success -0.040; pickoff attempts +7%, success +0.04 |
| pitcher `arm` (velocity) | steal attempt -3.8% relative; success -0.033; pickoff success +0.031 |

## 9. Workspace artifacts

`C:/Users/james/AppData/Local/Temp/claude/c--Users-james-OneDrive-Documents-Baseball-AI-NexGen-BBPro/31cccd52-8c06-46f6-a76c-f8479f51ec29/scratchpad/audit/work/map-running-defense/`:
- `driver.py`: the instrumented season driver.
- `an.py`: analysis of the driver output.
- `ds.py`: analysis of the dataset.
- `probe_groundout.py`: unit probes of the runner functions.
- `wpcheck.py`: the WP/PB check.
- `spreads.py`: rating spreads.
- `calib_s1.json`, `calib_s2.json`, `alpha_s1.json`: raw season output.
