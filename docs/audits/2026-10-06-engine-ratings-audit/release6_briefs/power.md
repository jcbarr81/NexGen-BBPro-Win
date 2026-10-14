# Release 6 design brief: Power and extra-base hits

All prototype work is in `...\scratchpad\r6\power\`; the repo is clean. One slip to report: three Monte Carlo output files were briefly written to the repo root and moved out straight away; `git status` is empty.

"Flat fixture" below means the product fixture, treated as a flat-ratings stress case per the coordinator's correction. Findings that depend on it are marked.

## 1. Current mechanism (7.51.0; legacy and generation 5 values are the same unless noted)

- **Bat speed from Power** (`physics_sim/physics.py:44-62`): `delta = (P-50)*bat_speed_power_scale + max(0, P-knee)*knee_scale`, with 0.15 / 52 / 0.8 (`config.py:363, 383, 384`). That is 0.15 mph per point below 52 and 0.95 above.
- **Situational bonuses** (`physics.py:65-86`): generation 5 reads the hitter's own `power_base` on the curve and adds `(power - power_base) * 0.35` mph (`platoon_power_after_knee` 1; legacy 0).
- **League-relative Power**: `P` is shifted at source (`engine.py:5023`).
- **Exit velocity** (`physics.py:1277-1315`): `bat = 68.8 + delta`; `ev = (velo*0.48 + bat*0.7 + N(0,5)) * quality * 1.075 * 1.0175`, soft cap 107.
- **Barrel accuracy** (`physics.py:1253-1264`, `barrel_power_weight` 1.0): `barrel_sd` scales with `0.8 + (1 - P/100)*0.6`.
- **Home run** (`physics.py:1442-1484`): drag-free carry times `hr_scale` (0.925 legacy, 0.91 generation 5), HR when carry exceeds the wall.
- **Doubles** (`physics.py:1493-1532`, called from `engine.py:6979-6992`): `gap_norm = ((C+P)/2 - 50)/50`; threshold is `double_distance * 0.70 * (1 - speed*0.18) * (1 - gap_norm*0.45)`.

Measured sensitivities (Monte Carlo on the real kernel, calibration pitchers by workload, generic park, 60,000 PA per cell):

- 1 mph of bat speed is 0.67 mph of mean exit velocity and about +12% HR near average (log slope 0.116 per mph, rising to 0.15 at -10 mph).
- At fixed bat speed, +10 Power through barrel accuracy is worth only +3-4% HR, so the bat-speed curve is the home-run curve.
- `gap_norm` alone adds about +5.4 doubles per 600 PA per +10 Power.

## 2. Where generation 5 stands

Power of the lineup regulars:

| Fixture | n | mean | sd | min | p10 | p50 | p90 | max |
|---|---|---|---|---|---|---|---|---|
| calibration | 270 | 50.2 | 4.4 | 38 | 45 | 51 | 56 | 64 |
| league | 330 | 50.7 | 4.9 | 34 | 45 | 51 | 57 | 65 |
| flat | 270 | 52.2 | 4.1 | 48 | 48 | 51 | 60 | 64 |

- No regular is at Power 30, so the decision's "Power 30-40" band can only be checked by Monte Carlo.
- Potentials reach 91 (league fixture, 83 hitters at 70 or more) and 94 (flat, 111), so the top of the curve may matter later.
- Release 5 did not move the floor. Today's Power 30-45 hitter hits 11-14.5 HR per 600 PA (Monte Carlo); the decision asks for 4-9 at Power 30-40.
- The bottom Power quintile hits 0.85 / 0.86 / 0.80x the middle quintile (two seasons each). The audit's 0.87-0.90 uses this by-Power definition.
- `corr_hr_power` is .561 / .589 / .668 over 18 / 6 / 6 seasons, so the first two fixtures fail the 0.6 target on average.
- Doubles are 1.76 / 1.85 / 1.82 per team-game against a 1.63 benchmark.
- Per rating point, Contact already drives doubles 1.2-1.7x more than Power (per 600 PA per +10: Power 6.0 / 6.1 / 5.8, Contact 9.9 / 8.9 / 6.8). Release 5's sharper strikeout effect did this; the audit's "about equally" is out of date.
- r(K%, ISO) is -0.37 / -0.42 / -0.31 on generation 5, not the -0.19 in the brief. Release 5 made it more negative.
- `qualified_hr30_count` is 19.6 / 14.8 / 12.5 and `qualified_hr40_count` 4.6 / 1.3 / 1.0.

## 3. Proposed changes

**A. Power curve as a table (the main item).** New keys:

- `power_curve_model` (default 0).
- `bat_speed_power_table` (default `{"30":-3,"50":0,"52":0.3,"65":12.65,"80":26.9}`, which is today's curve and is unused while the switch is off).

With the switch on, `_power_bat_speed` returns the piecewise-linear interpolation of the table, with the end segments extrapolated. With it off, today's code path runs untouched. It is deterministic and draws no random number.

Generation 6 starting table: `{"30":-10.3, "50":0.7, "52":1.0, "65":12.65, "80":20.15}`.

- Slope is 0.55 mph per point below 50 (was 0.15). This is the slope that puts Power 30-40 at 4-9 HR per 600 PA on the response table.
- Today's values hold from 52 to 65.
- Slope is 0.50 above 65 (was 0.95).
- The +0.7 at the centre is the re-level that holds league home runs, so `hr_scale` stays 0.91.

**B. Doubles.** New key `double_gap_power_weight` (default 0.5, which is today's `(C+P)/2`; keep the legacy expression on that branch). The formula becomes `gap_norm = (C*(1-w) + P*w - 50)/50`. Generation 6: `w = 0`, `double_gap_scale` 0.225, `double_distance_scale` 0.72.

**C. Benchmarks and gates.** See section 6.

**D. Sluggers striking out more.** New key `contact_logit_power` (default 0): `logit -= (power_base - 50) * k` in `_contact_probability`. Build the knob, but leave it at 0 in generation 6 (reasons in section 4).

### Fitting procedure for the table

Re-run this after the batted-ball model changes.

1. Freeze the new exit-velocity and carry model and its home-run level.
2. Build the response table R(P, d): HR per PA for a hitter at league-relative Power P, average Contact and Eye, with bat-speed offset d forced, against a fixture's workload-weighted pitchers. `table.py` does this: 55 cells of 60,000 PA in about 110 s.
3. For each anchor, solve R(P, d) = ratio(P) * R(50, d50) by log-linear interpolation. Target ratios to the Power 50 hitter:

   | Power | 30 | 35 | 40 | 45 | 55 | 60 | 65 | 70 | 80 |
   |---|---|---|---|---|---|---|---|---|---|
   | Target ratio | .29 | .42 | .57 | .75 | 1.33 | 1.8 | 2.3 | 2.6 | 3.3 |
   | Today | .69 | .79 | .84 | .91 | 1.35 | 1.86 | 2.44 | 3.0 | 4.3 |

4. Choose d50 so the population's mean HR is unchanged (`pop.py`), then confirm with seasons.

If the batted-ball agent replaces bat speed with a direct exit-velocity mean, multiply the anchors by 0.67: -6.9 / +0.5 / +0.7 / +8.5 / +13.5 mph.

## 4. Evidence

### Monte Carlo, calibration fixture, 100,000 PA per cell

"Proposed" is the full proposal (A plus B).

| HR per 600 PA | P30 | P35 | P40 | P45 | P50 | P55 | P60 | P65 | P70 | P80 |
|---|---|---|---|---|---|---|---|---|---|---|
| Today, Contact 50 | 10.9 | 12.5 | 13.3 | 14.5 | 15.9 | 21.5 | 29.5 | 38.8 | 47.7 | 68.0 |
| Proposed, Contact 50 | 4.8 | 7.1 | 9.6 | 12.6 | 16.8 | 22.4 | 30.1 | 38.8 | 43.5 | 54.9 |
| Today, Contact 40 | 8.5 | 9.1 | 9.9 | 11.1 | 11.4 | 15.7 | 21.3 | 28.9 | 35.6 | 51.1 |
| Proposed, Contact 40 | 3.7 | 5.3 | 7.4 | 9.8 | 12.1 | 16.3 | 21.7 | 28.9 | 32.5 | 41.0 |
| Today, Contact 60 | 13.6 | 14.8 | 16.4 | 17.3 | 18.4 | 25.0 | 34.2 | 45.1 | 57.4 | 79.4 |
| Proposed, Contact 60 | 5.9 | 8.7 | 11.9 | 15.1 | 19.6 | 26.0 | 34.8 | 45.1 | 52.1 | 64.1 |

| ISO | P30 | P35 | P40 | P45 | P50 | P55 | P60 | P65 | P70 | P80 |
|---|---|---|---|---|---|---|---|---|---|---|
| Today, Contact 50 | .099 | .111 | .121 | .131 | .144 | .184 | .241 | .305 | .367 | .498 |
| Proposed, Contact 50 | .059 | .077 | .096 | .119 | .146 | .183 | .233 | .289 | .320 | .390 |
| Today, Contact 40 | .073 | .079 | .086 | .096 | .101 | .131 | .172 | .223 | .270 | .371 |
| Proposed, Contact 40 | .042 | .054 | .069 | .086 | .103 | .130 | .167 | .210 | .234 | .287 |
| Today, Contact 60 | .128 | .139 | .153 | .165 | .177 | .225 | .292 | .366 | .448 | .592 |
| Proposed, Contact 60 | .078 | .099 | .124 | .149 | .180 | .222 | .280 | .346 | .391 | .467 |

Other Monte Carlo readings at Contact 50:

- Doubles per 600 PA go from 17.6 / 21.8 / 26.3 / 36.4 / 48.4 at Power 30 / 40 / 50 / 60 / 70 to 15.9 / 20.3 / 24.8 / 30.3 / 35.9.
- Mean exit velocity at Power 30 is 80.6 mph (today 85.5).
- Batting average per +10 Power is +.018 below the centre and +.028 above; per +10 Contact it is +.052.
- The league and flat fixtures give the same shape in a 50,000 PA variant run that re-levels with `hr_scale` instead of the centre offset. Power 30 / 40 is 4.7 / 8.7 (league) and 3.9 / 8.2 (flat).

### Seasons, same seeds as the generation 5 baseline

In-memory patch; "after" is the full proposal.

| Metric | Calibration (8 seeds) | League (2) | Flat (2) |
|---|---|---|---|
| `corr_hr_power` | .578 → .680 (min .639; base min .522) | .542 → .694 | .647 → .696 |
| `corr_iso_power` | .582 → .654 | .549 → .638 | .641 → .645 |
| Bottom Power quintile ÷ middle | .85 → .70 | .86 → .67 | .80 → .75 |
| Qualified HR/600, bottom quintile / median / top quintile | 10.5 / 17.0 / 27.3 → 10.3 / 17.4 / 28.0 | 10.7 / 17.2 / 26.3 → 10.4 / 17.5 / 27.0 | 9.2 / 14.8 / 24.2 → 8.8 / 15.1 / 25.7 |
| `qualified_hr30_count` | 19.4 → 22.8 (max 27) | 13.5 → 16.5 | 9.5 → 15.5 |
| `qualified_hr40_count` | 4.6 → 5.0 | 1.0 → 0.5 | 0.5 → 1.5 |
| HR per team-game | 1.102 → 1.097 | 1.085 → 1.095 | .997 → 1.014 |
| Doubles per team-game | 1.758 → 1.623 | 1.853 → 1.715 | 1.822 → 1.680 |
| ISO | .157 → .153 | .162 → .159 | .151 → .149 |
| Runs per team-game | 4.348 → 4.311 | 4.441 → 4.465 | 4.521 → 4.492 |
| Doubles/600 per +10 Power; per +10 Contact | 6.0; 9.9 → 3.5; 9.0 | 6.1; 8.9 → 2.3; 9.0 | 5.8; 6.8 → 2.4; 6.8 |
| r(2B rate, HR rate) | .40 → .32 | .31 → .21 | .25 → .14 |
| r(K%, ISO) | -.37 → -.39 | -.42 → -.40 | -.31 → -.31 |

The "before" figures for the quintile, per-hitter and distribution rows come from seeds 1-2 only, because the stored baselines hold no per-hitter data.

- K, BB, BABIP, exit velocity and hard-hit are unchanged (K .2196, BABIP .2818, EV 88.63 against 88.75).
- `hitter_hr_rate_true_sd` rises from .0078 to .0087 on calibration.
- No strict failures on the 8 calibration seeds.

### Variants measured

- **Re-level with `hr_scale` 0.918 instead of the +0.7 centre offset** (calibration 8 seeds, league 5, flat 5): `corr_hr_power` .701 / .709 / .738. It costs more runs (-0.08 / -0.045 / -0.09), drops exit velocity 0.5 mph and hard-hit by .017, and put one calibration seed at 29 thirty-homer hitters, which fails the gate. I prefer the centre offset.
- **Also steepening 50-65** (2 seeds, not re-levelled): `corr_hr_power` .76 / .71 / .77, but calibration reaches 30.5 thirty-homer hitters and fails the gate. Do not do this.
- **Slope 0.70 below 50** (2 seeds, not re-levelled): quintile ratio .61 / .57 / .73 and `corr_hr_power` .78 / .75 / .78, but Power 30 falls to 2.6 HR.
- **Override A** (arithmetic, population model): Power 30 / 40 at 6.1 / 10.3, quintile ratio .78 / .72, expected correlation about .67 / .70.

### Sluggers and strikeouts (Monte Carlo plus arithmetic, no seasons)

The population model reproduces today's r(K%, ISO) on all three fixtures, so I trust its direction.

| Scenario | Season r(K%, ISO), calibration / league |
|---|---|
| Today's curve | -.37 / -.40 |
| Proposed curve | -.32 / -.37 |
| Plus K term 0.03 logit per point (+3.8 pp K per +10 Power; a Power 60 hitter at .259 instead of .277) | -.08 / -.14 |
| Plus K term 0.06 | +.10 / +.05 |
| Proposed curve with Contact-Power correlation -0.4 in the ratings, no K term | -.02 / -.04 |
| K term 0.03 and correlation -0.4 together | +.14 / +.12 |

The cause is Contact: it both lowers K and raises ISO per at-bat, and the ratings pair Contact and Power almost independently (r +.07 / +.13). No sane engine term fixes this alone.

## 5. Expected movement and interactions

- **League totals:** K, BB, BABIP and exit velocity do not move. HR is held. Doubles drop 0.14 per team-game to the benchmark. Runs move -0.04 to +0.02, to be recovered in the joint retune. ISO falls about .004 and returns to about .160 only if league HR is lifted toward the 1.17 benchmark (today 1.10).
- **Batted ball:** drag carry and a launch-angle mixture change HR sensitivity to exit velocity, so the table must be re-fitted with the procedure above. A, B and D can all be built and measured on today's model first; only the anchor values are provisional.
- **Pitching (M21):** the pitcher-to-hitter HR spread ratio falls from 1.09 to .96 (calibration) and .95 to .88 (league) from the hitter side alone. Low-Power cells of the Power-by-pitcher HR grid will have few home runs, so raise `--matchup-grid-pa`.
- **Fielding:** a hit table with a stronger exit-velocity term would enlarge Power's effect on batting average. Re-check `corr_avg_contact` (.61 after, .63 before on calibration).
- **Platoon:** unchanged mechanism. `platoon_gap_woba` .0246 against .0255 (calibration, the `hr_scale` variant).

## 6. How to measure

Existing: `corr_hr_power`, `corr_iso_power`, `corr_hr_contact`, `qualified_hr30_count`, `qualified_hr40_count`, `doubles_per_team_game`, `iso`, `hr_per_team_game`, `hitter_hr_rate_true_sd`, `pitcher_hitter_hr_true_sd_ratio`, `platoon_gap_iso`.

To add:

- `power_hr600_p30` through `p80`, from the matchup-grid Monte Carlo. Gate Power 30-40 inside 4-10. This is the only fixture-independent test of decision 5.
- A `hr600_by_power_band` table.
- `hr_power_bottom_quintile_ratio`, by Power quintile. Gate at 0.75 or less on calibration and league; report-only on the flat fixture.
- `qualified_hr600_q1`, `_median`, `_q5`, and `hr30_share_of_qualified`.
- `doubles_per10_power`, `doubles_per10_contact`, `corr_2b_hr`, `corr_k_iso`.

## 7. Owner decisions

1. **How weak is a weak bat?** The two halves of decision 5 cannot both hold on leagues whose regulars' Power sd is 4-5.
   - Slope 0.55 gives Power 30-40 at 5-10 HR and a quintile ratio of .67-.70.
   - Slope 0.70 gives a ratio of .57-.61 but Power 30 at about 3 HR.
   - Recommend 0.55, and restate the quintile target as 0.75 or less.
2. **Ceiling for elite Power.** Today Power 70 / 80 projects to 48 / 68 HR per 600 PA. Recommend the taper, giving 43 / 55. This rests on Monte Carlo only; no fixture has a regular above 65.
3. **More 30-homer hitters.** Holding league HR while weakening slap hitters moves home runs up the order: about 23 per 30 teams on calibration (was 19), 16 on league. Recommend accepting it (benchmark 20 ± 8).
4. **Doubles belong to contact hitters.** A Power 60 hitter drops from 36 to 30 doubles per 600 PA, and league doubles fall about 8%. Recommend yes.
5. **Sluggers strike out more.** Recommend not switching it on in Release 6. Build the knob at 0, and enable about 0.03 together with a negative Contact-Power correlation in the Release 7 generator. The term alone only reaches about -0.1.
6. **For Release 7:** the observed spread stays narrow. The bottom quintile by HR total is .59x the median after the change (my recollection of MLB is about .43), because Power ratings are bunched. Only wider Power ratings close this.

## 8. Risks and "do not do"

- The quintile ratio is a property of the rating spread, not only the curve. The flat fixture's regulars floor at 48 and cannot go below about .75; do not tune to it.
- About 242 of 270 regulars qualify here; my recollection is that MLB has about 135-140 qualifiers. Count gates therefore read about 1.8x high for the same distribution shape; prefer the share.
- `hr_scale` leverage is confirmed: +0.9% gave +4.5% HR.
- From REPORT section 7, still valid: do not use Power-only `gap_norm` at 0.45; do not add a Power-to-launch-angle term before drag carry; do not expect Override A alone to deliver the floor.
- "Power raises AVG more than Contact" stays false after the change.

## Build order

1. KPIs from section 6. Tooling only; safe to ship alone.
2. The three switches (`power_curve_model` with its table, `double_gap_power_weight`, `contact_logit_power`), all off by default. Safe to ship alone.
3. After the batted-ball model is frozen: re-fit the table, then set `double_distance_scale`, then the joint retune.

## Not verified

- MLB distribution figures (quintile ratios, r(K%, ISO) positive, qualifier count) are from memory; the repo has no player-level MLB data.
- Whether player development actually moves Power toward the 70-94 potentials.
- Byte-identity of the eventual code. The prototype patches in memory; the off path is the untouched function, and the wrapper reproduced the stored baseline exactly on calibration seed 1.
- The full proposal on the league and flat fixtures has 2 seeds each.
- The K term was not run in seasons.
- Real-park effects in the Monte Carlo, which uses the generic park.

Scratch files: `mc.py`, `table.py`, `grid.py`, `pop.py`, `kiso.py`, `kpow.py`, `season.py`, `launch.py`, `rows.py`, `cmp.py`. Season outputs are in `runs\`; `P4` is the proposal, `P2` the `hr_scale` variant, and `T55`, `T70`, `T55k`, `P3` the other variants.