# Release 6 design brief: fielding, errors and positional value

Scratch: `...\scratchpad\r6\fielding\` (`fdriver.py` logs every ball in play, `proto.py` is the in-memory prototype, `ev.py`/`ev3.py`/`derive.py` are the evaluators, `cfg_F.json` the prototype settings).

**Incident:** my first driver wrote six log pickles into the repo root (a `chdir` bug). I moved them to scratch at once. `git status` now shows only `t_cal_c50.json`, which is not mine and which I left alone.

## Headline findings

- **Product league's low DER spread is rating spread, not the model.** Its lineup regulars have `fa` sd 1.1-1.6 (arm 1.1-1.5), against 5-10 on the fixtures. Its team DER sd (.0081) is binomial noise (.0072) plus pitchers (.0027). Most of its designed defence spread (.0034) comes from the ×0.9 listed-secondary multiplier, which touches 11.6% of fielder-slots.
- **Uncentred fielding ratings explain the cross-fixture BABIP gap.** They move BABIP by -.0034 / -.0091 / +.0031 (calibration / league / product; log arithmetic). With per-position centring, prototype seasons give BABIP .287 / .287 / .286, against .282 / .278 / .289 at baseline.
- **The two size targets conflict.** At 5-7 outs per SD per position, independent fielders give a team sd of 15-17 outs per 150 G, so observed team DER sd is about .009, below the .010-.012 band. Reaching the band needs 9-13 outs per SD, or more pitcher BABIP spread.

## 1. Range and positional value (M22, decision 12)

**Current mechanism**
- `compute_defense_ratings` (`fielding.py:94-143`) averages the infield pairs 50/50 (3B+SS, 1B+2B) and reads LF/CF/RF alone.
- `out_probability` (`fielding.py:165-255`) is `base + (zone-50)/D - (EV-90)/300`, with base .78/.38/.73 and D 250/300/230 for GB/LD/FB.
- The hit roll at `engine.py:7046-7061` multiplies by `babip_scale` (.925 legacy, .92 generation 5).
- The CF band is `spray_center_band_deg` 8 (`config.py:277`). `range_scale` is 1.0.
- `fa` and `arm` are not league-relative; only catcher `fa` is.

**Measured today** (generation 5, designed range outs per 150 G, one logged season per fixture)

| | 1B | 2B | 3B | SS | LF | CF | RF |
|---|---|---|---|---|---|---|---|
| Outs per `fa` point | 1.59 | 1.58 | 1.31 | 1.38 | 2.09 | 2.56 | 2.85 |
| Per SD, calibration | 14.7 | 12.7 | 10.9 | 10.8 | 14.3 | 13.4 | 27.8 |
| Per SD, league | 14.6 | 12.4 | 10.8 | 10.7 | 20.5 | 20.0 | 27.4 |
| Per SD, product | 2.8 | 2.5 | 1.7 | 2.2 | 3.8 | 4.1 | 3.9 |

- Release 5 did not move any of this.
- Team DER sd baseline is .0160 / .0155 / .0081 (18 / 6 / 6 seasons).
- Calibration decomposition (seed 1): noise .0072, range .0111, reached-on-error .0052, pitchers and opponents .0026.
- The existing `range_plays_per_fa_sd_*` KPIs are unusable as gates. They read 28 at 2B on calibration and 58 at SS on the league fixture, because they count plays rather than expected outs.

**Proposal** (switch `range_model`, 0 = today)

1. **Centre the ratings.** New keys `fielder_fa_center_<pos>` and `fielder_arm_center_<pos>` (seven each, default 50), the mean over lineup regulars by lineup position. Build them in `services/league_rating_centers.py` the way `_REGULARS_CENTER_SPECS` does and freeze them for the season. Effective rating: `eff = fa - center[pos] + 50 - move_penalty` (section 3).
2. **One responsible fielder per ball.** Grounders go to the infield band owner (section 2); air balls to LF/CF/RF with `spray_center_band_deg` 10. That gives CF 41% of air balls against 34% today (rule: half-width = 0.54 × spray sd).
3. **Shift in log-odds.** `logit(out) = logit(out0) + range_logit_slope[pos] * (eff - 50) * (range_ld_ratio if liner)`, where `out0` is today's function with a neutral defence. Routine balls and sure hits barely move; coin-flip balls move most. This is the difficulty shape REPORT M2/L19 asks for.
4. **Slopes.** `range_logit_slope` = SS .0064, 3B .0081, 2B .0050, 1B .0078, LF .0068, CF .0060, RF .0066; `range_ld_ratio` 0.6.

**Re-fit procedure** (run after the spray fix; this is `derive.py`): `slope[pos] = T[pos] / (babip_scale × Σ out0(1-out0))`, summed over that position's balls per 150 team-games.
- T is the range budget in outs per point: SS .44, 3B .40, 2B .41, 1B .30, CF .825, LF/RF .64.
- The slopes agreed within 2% across the three fixtures.
- Equivalent additive divisors on the owner's own balls are about 700-1,200, against 230-250 today.

**Prototype evidence** (six seasons, two seeds per fixture; outs per 150 G, range plus errors, designed)

| | 1B | 2B | 3B | SS | LF | CF | RF | Team DER sd (KPI) |
|---|---|---|---|---|---|---|---|---|
| Per 8 `fa` points | 4.2 | 6.0 | 6.0-6.6 | 7.2-7.5 | 5.7 | 6.6-6.8 | 5.3-5.6 | |
| Per SD, calibration | 4.8 | 6.1 | 6.2 | 7.4 | 5.0 | 4.5 | 6.5 | .0086 (.0076, .0095) |
| Per SD, league | 5.0 | 5.7 | 6.3 | 7.1 | 6.7 | 6.9 | 6.9 | .0081 (.0074, .0088) |
| Per SD, product | 0.9 | 0.8 | 1.0 | 1.2 | 0.9 | 1.3 | 0.9 | .0072 (.0076, .0067) |

- CF on calibration is 4.5 only because its `fa` sd there is 5.2.
- The DP term adds about 0.7 outs per SD at SS and 2B (arithmetic).
- In runs per 8 points: SS 6.1, CF 5.9, LF 5.1, 2B 5.0, RF 4.8, 3B 4.7, 1B 3.2. SS and CF sit above the corners.
- League level is neutral: mean `out - out0` is under .0003 on all three, and neutral out probability is .677 / .677 / .678.
- The designed (noise-free) team sd implies an observed DER sd of .0091 / .0090 / .0076.

**Double plays.** The DP chance reads the same `fa` at .0052 per pair-point over 240 rolls per 150 G. That is about 4 outs per SD at SS and 2B today (arithmetic). Generation 6 should set existing knobs `double_play_range_scale` 0.2, `double_play_arm_scale` 0.4 and `double_play_base` 0.42, and centre the turn arm. Prototype GIDP per team-game is .68 / .62 / .64 (baseline .65 / .63 / .58).

## 2. Errors and fielding credit (M9)

**Current mechanism**
- `error_probability` (`fielding.py:301-318`) is `(base + (50-fa)/500 + (50-arm)/900) × error_rate_scale`, clamped to [.001, .12], with bases .018/.012/.008 (`config.py:263-265`).
- It is rolled only on would-be outs (`engine.py:7211-7251`).
- Bands at `engine.py:3056-3072` give 3B and 1B only |spray| ≥ 25°.

**Measured today**
- Errors per team-game: .215 / .182 / .264. All are reached-on-error.
- 39% / 47% / 0% of rolls sit at the .001 floor.
- Outfielders make 46% of calibration errors, 3B 5%, catchers and pitchers none.
- Grounder credit is 3B 9 / SS 41 / 2B 41 / 1B 9 on all three fixtures.
- Outfield out-chances are 7.6 per game against MLB's roughly 6.5, because there are no pop-ups.

**Proposal: `error_model` 1** (same number of draws as today)
- `p = error_base_by_pos[pos] × exp(-error_fa_log_slope × (eff-50) - error_arm_log_slope × (arm - arm_center[pos]))`, clamped to [.0005, .15].
- Infield liners take `error_infield_liner_scale` .25.
- Bases: 3B .049, SS .036, 2B .020, 1B .029, LF .0069, CF .0037, RF .0068. Slopes .025 (fa) and .02 (arm), which gives roughly 3x worst-to-best across ±2 SD.
- Prototype (seasons, all three fixtures): .33-.35 errors per team-game. By position: SS .100, 3B .088, 2B .060, 1B .038, LF .016, CF .013, RF .017.

**Proposal: `error_model` 2** (new draws; arithmetic only, not prototyped)

| Source | Rate | Errors per team-game |
|---|---|---|
| Pitcher comebacker band (reads pitcher `fa`, dead today) | .045 | .025 |
| Catcher throw on a steal (.89 attempts per game) | .04 | .036 |
| Outfielder on a hit (extra base) | .009 | .058 |
| Pickoff throw | .01 | about .015 |
| Relay or advance throw | | about .03 |

Total is about .50-.53.

**Proposal: `infield_band_model` 1**
- Lower bounds on spray direction: 3B 16°, SS 1.5°, P -1.5°, 2B -19.5°, otherwise 1B.
- Shares under today's symmetric spray (sd 18.5°): .19 / .27 / .06 / .32 / .15.
- After the spray fix, set the cut points at the quantiles for .20 / .29 / .07 / .27 / .14.
- Prototype grounder chances per game: 3B 1.7, SS 2.7, 2B 3.1, 1B 1.3.

## 3. Out-of-position penalty (M12)

**Current mechanism**
- ×1.0 primary, ×0.9 listed secondary, ×0.75 otherwise (`fielding.py:146-158`, `config.py:554-556`), duplicated at `engine.py:4212-4222`.

**Measured today**
- Unlisted positions are only 0.3% / 1.3% / 0.6% of fielder-slots. Listed-secondary play is 3% / 8% / 12%.
- A CF playing a listed corner loses 5 points, which is 10-14 outs per 150 G today. A true out-of-position player at `fa` 50 loses 12.5 points, or 17-45 outs (arithmetic from the measured slopes).

**Proposal** (`position_fit_model` 1)
- Subtract points from a table `position_move_penalty[from][to]`.
- Listed secondary costs `position_secondary_penalty_scale` 0.25 of the table value.
- Otherwise take the cheapest route from any position the player lists.
- Keep the table in `utils/position_fit.py`, so `fielding_fit` and the engine read the same one.

| Move | Points | Outs per 150 G |
|---|---|---|
| CF → corner | 0 | 0 |
| RF → LF / LF → RF | 1 / 2 | about 1 |
| SS → 2B / SS → 3B | 1 / 2 | 1-2 |
| Any infielder → 1B | 2 | 1 |
| 2B ↔ 3B | 4 | 3 |
| 2B → SS / 3B → SS | 6 / 7 | 6-7 |
| Corner → CF | 7 | 6 |
| Infielder → corner OF | 6-8 | 4-6 |
| Outfielder → 2B or 3B | 10 | 8 |
| 1B or outfielder → SS | 14 | 14 (about 10 runs) |
| C → 1B / corner OF / SS | 5 / 9 / 16 | |
| Anyone → C | 25 | framing about 12 runs, plus passed balls and steals |

Every `REST_SIMILAR_SOURCES` move costs 2 points or less. Every `FILL_FAMILY` move costs 7 or less.

## 4. OVR defence weights (`utils/player_overall.py:35-46`)

Offence is worth 4.6-5.0 runs per OVR point per 600 PA (regression on one generation 5 season per fixture, n 270-295). Weight = defence runs per point ÷ 4.8.

| | SS | CF | 2B | LF | RF | 3B | C | 1B |
|---|---|---|---|---|---|---|---|---|
| `fa` today | .15 | .16 | .11 | .07 | .06 | .09 | .06 | .04 |
| `fa` derived | .16 | .155 | .13 | .13 | .125 | .12 | ≥.10 | .08 |
| `arm` derived | .06 | n/m | .045 | n/m | n/m | .04 | n/m | .035 |

- The catcher figure uses Release 5's framing value only.
- Outfield and catcher arm values come from the Release 4 running game, which I did not measure.
- Re-derive after the Power and spray work.

## Interface with the other Release 6 areas

- **Batted ball.** That agent owns `out0(ball)`, the class and the responsible position (pop-ups and infield liners included), and the .291 level. Fielding adds only the log-odds shift. League-level neutrality is measured above.
- **Spray.** Band cut points, the CF band and every slope are re-fitted by the procedure in section 1. Measurable before the fix: per-ball slopes, class totals, DER, errors, the BABIP convergence. Not measurable: the left/right and LF/RF splits.
- **Power and pitching.** No direct coupling. Pitcher ground-ball spread and contact suppression are the missing part of team DER sd.

## Expected movement (prototype seasons, generation 5 otherwise unchanged)

| | Calibration | League | Product |
|---|---|---|---|
| Runs per team-game | 4.36 → 4.49 | 4.45 → 4.72 | 4.52 → 4.44 |
| BABIP | .284 → .287 | .279 → .287 | .290 → .286 |
| Errors per team-game | .22 → .33 | .18 → .34 | .26 → .33 |

- K, BB and HR do not move.
- The league fixture's good gloves were masking a hotter offence, so the runs spread across fixtures widens from .17 to about .28. That needs the joint retune.
- Errors at .53 add roughly a further .05 runs.

## How to measure

- Existing: `e_per_team_game`, `team_der_sd`, `team_der_mean`, `gidp_per_opp`, `babip`.
- To add (the engine logs `resp_pos`, `out_prob` and the neutral `out_prob` per ball when the model is on):
  - `oaa_per_fa_sd_<pos>` and per 8 points, from logged probabilities;
  - `team_der_true_sd`;
  - `e_per_team_game_<pos>` and by source;
  - `unearned_run_share`;
  - grounder assist share by position, and CF putout share;
  - `off_primary_slot_share`.
- Gate the designed numbers. Realised single-season r(`fa`, range) was only -.2 to .67 in the prototype, since binomial luck is 9-12 outs.

## Decisions for the owner

1. **Size versus spread.** Keep 5-7 outs per SD (team DER sd about .009), or raise to 9-13 to reach .010-.012? I recommend 5-7.
2. **1B.** It lands at 4.2-5.0, below "5-7 at each position". I recommend accepting that as "1B least".
3. **Infield split.** At SS, about half the value is errors (3-3.8 outs), with 3.5 from range. Confirm that split is acceptable.
4. **League-relative fielding by position.** A 55 SS is average in a league whose shortstops average 55. I recommend yes.
5. **The penalty table.** The worst non-catcher move costs about 10 runs per 150 G, and listed secondaries are near-free. I recommend adopting it.
6. **Errors at MLB volume.** This means more unearned runs and new error types in box scores (E2 on steals, E1, outfield errors on hits). I recommend yes.
7. **OVR weights.** Corner outfield, 1B, 3B and C rise. Also decide whether OVR's `fa` term should be position-relative.
8. **Flat fielding in product-created leagues** (`fa` sd about 1.4). Until Release 7 widens it, owners will feel only the position penalties. Decide whether to bring the `fa`/`arm` re-spread forward.

## Risks and do-not-do items

- Do not use `range_scale` below 1 (REPORT section 7).
- Do not flip `_spray_dir` here; that belongs to the spray fix.
- Do not gate on the r +0.81 out-of-position/unearned-runs claim or on single-season per-fielder values.
- Centres depend on saved lineups; they need a fallback to primary positions.
- Release 4 arm reads (tag-ups, extra bases) stay uncentred.
- The defensive-substitution scorer (`_defense_rating_for_pos`) must use the new function.
- The `infield` average in `compute_defense_ratings` includes the catcher.

## Build order

1. Logging and KPIs. Ships alone, no behaviour change.
2. Centres plus the penalty table. Independent of spray.
3. `error_model` 1, then 2.
4. After the spray fix: bands, `range_model`, slope re-fit, DP knobs.
5. Joint BABIP and run retune.
6. OVR weights.

## Not verified

- MLB per-position error and grounder shares (from memory).
- Unearned-run share (the harness does not expose it).
- The `error_model` 2 sources and the pitcher band (arithmetic only).
- Pickoff attempt volume.
- Outfield and catcher arm run values.
- Anything after the spray fix.
- The legacy engine and the live alpha-test league.
- A season A/B of out-of-position starters (table costs are slope arithmetic).
- A byte-identity test of the off state.