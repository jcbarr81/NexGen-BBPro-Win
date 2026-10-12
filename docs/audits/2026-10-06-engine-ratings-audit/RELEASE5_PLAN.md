# Release 5 implementation plan: plate discipline, contact, platoon and situations

Audit: `docs/audits/2026-10-06-engine-ratings-audit` (REPORT.md "Release 5"; H4, H6 (K part), H7, M1, M3 (platoon part), M5 (foul territory), M19, M20, L1, L3, L4, L5, L14, L16; batting.md, pitching.md; DECISIONS.md 2, 4, 6, 7, 10). Code base: 7.50.1 (engine unchanged since 7.49.0). Written 2026-10-12 from four read-only design passes (plate discipline, contact model, platoon, situational); their prototype patches and raw numbers are in the session scratchpad under `r5/`. **Status: built (7.51.0, 2026-10-12). Owner decisions taken 2026-10-12 (section 6); the engine reaches each league at the start of its own next season (section 7); the final measurements, what differs from this plan and the known shortfalls are in section 8.**

Evidence levels used below: **season** = full 162-game KPI run; **300g** = 300-game sample in the real engine (±0.2 pp BB, ±0.3 pp K, ±0.13 R/G); **MC** = per-PA Monte Carlo on the real pitch kernel; **model** = arithmetic from shares and sensitivities.

## 0. What changed from the audit's plan

1. **The calibration fixture's passing K, BB and P/PA are propped up by its real parks.** Its parks cut foul balls about 7% (mean foul scale 0.9285); the league fixture is all generic parks. With `foul_territory_scale` 0 (M5), calibration moves to about K 23.2%, BB 9.1%, P/PA 4.03 (300g) -- where the league fixture already sits. Foul territory goes to 0 first, on the branch, and everything else is tuned against neutral parks.
2. **K 22% and contact .76 are reachable only jointly.** The swing-by-count table plus the two-strike foul trim lowers K to about 19% (300g) while fixing P/PA and per-count swing; the contact model then supplies about +3 to +3.5 pp of swinging K by taking contact from .79 to .76 (SwStr .10 to .11). Neither area hits the targets alone (the audit's `k_scale` wall).
3. **Eye already moves the called third strike; Contact does not** (correction to the audit). Looking K is 5.4-8.3% of PA in every Contact x pitcher cell today, so an 80-Contact hitter cannot go below about 10% K.
4. **The harness shows no home-field edge at all:** .4975 +/- .0032 pooled over 24,300 games (the audit fitted +1.1 pp). The new term must supply the whole +3.75 pp.
5. **Release 3 already closed about half of M19:** late & close OPS delta is -.0155 (audit about -.005; target -.02 to -.04); innings 7-9 / 3-6 runs ratio .969 (audit 1.035; MLB about .935).
6. **The pooled platoon gate cannot pass at the restored 0.006 tolerance today.** Calibration: .0313 with per-season sd .0023 (40 seasons); the sd is binomial, so the mean must move to about .026.
7. **"LHP = RHP" and the size of the RHB split are one quantity.** LHP-minus-RHP balances when RHB split / LHB split = (2l+s)/(2r+s) for batting-side PA shares l/r/s: .61 for an MLB mix, .77 calibration, .42 league fixture, about .38 alpha. A fixed 0.6 over-corrects calibration (-0.12 R/9) and under-corrects RHB-heavy leagues.
8. **Existing leagues do not share one vl convention** (hitter vl means L/R/S: calibration 49.9/49.1/49.4; league fixture 45.0/53.6/49.4; alpha about 50/55/53). A hard-coded "undo +/-4" would be wrong for alpha; read vl against the league's own by-bats mean instead.
9. **Harness bug (not live):** `simulate_matchup_from_files` picks the vs-LHP/vs-RHP lineup from `starters[game_day % n]` while `simulate_game` re-picks the starter by usage; over 900 league-fixture games the lineup hand matched the real starter 67% of the time. Calibration is unaffected (its two lineup files are identical). The live path (`game_runner`) uses the assigned starter and reads correct.
10. **`--tuning-overrides` accepts numbers only,** so dict-valued knobs (count tables, pitch-objective tables) cannot be tuned through the harness. Extend the loader to accept a dict for a dict-valued default.
11. **The BB true-sd targets (>= .02) cannot be met on the committed fixtures:** ACT eye sd is 4.4 / 2.9 and control sd 5.3 / 4.3. Gate the slopes (BB per 10 eye, BB per 10 control) instead; the spread itself arrives with the Release 7 re-spread.
12. **No IBB can ever fire today:** the absolute threat threshold (65) is above every lineup hitter on both fixtures.

## 1. Baseline (7.49.0 engine, seasons; calibration s1-4, league s1-2)

| Metric | Target | Calibration | League | 
|---|---|---|---|
| R/G | 4.47 +/- .25 | 4.42 | 4.11 (fails) |
| K% / BB% | .22 / .082 | .215 / .085 | .237 / .092 |
| SwStr / contact / P/PA | .11 / .76 / 3.88 | .103 / .787 / 3.89 | .103 / .789 / 4.05 |
| Swing rate, the six early counts | varies (.30-.58) | all about .41 | same |
| Swing 3-0 / 3-1 | .10 / .54 | .24 / .36 | same |
| Fouls per two-strike pitch | .243 | .33 | .33 |
| Hitter / pitcher BB% true sd | see 0.11 | .005 / .006 | .002 / .003 |
| K log5 max residual (Contact x pitcher grid) | <= 2 pp | 5.7 pp | |
| Platoon gap pooled / LHB / RHB | .026 / .028 / .018 | .031 / .029 / .029 | .039 / .040 / .039 |
| LHP - RHP RA9 | 0 +/- .15 | +0.04 | +0.40 |
| Home W% | .535 +/- .015 | .493 | .501 |
| Late & close OPS delta | -.02 to -.04 | -.0155 | -.0166 |
| TTO pass 2 wOBA | >= +.008 | +.0013 | +.0048 |
| IBB / HBP per PA | about .0025 / .011 | 0 / .013 | 0 / .0135 |

## 2. Design by area

Every change is behind a switch or a knob whose default reproduces today's output byte for byte, draws no extra random number while off, and is registered in `DEFAULT_TUNING` (`from_overrides` silently drops unregistered keys). Each switched-off path gets a seeded identity test.

### 2.1 Plate discipline (`physics.py` swing decision, command, umpire, HBP; `engine.py` IBB)

- **`swing_model` 0|1.** Log-odds swing decision per count from a 12-count zone/chase table (MLB 2023, `data/MLB_avg/statcast_counts_2023.csv`) with a separate 3-2 row: `x = logit(table[zone|chase][b][s]) +/- e * slope`, `e = eye_ctx - hitter_eye_center`, `swing_eye_chase_logit` 0.035, `swing_eye_zone_logit` -0.005, `swing_platoon_chase_logit` 5.0, clamp .01-.99. No second "protect" roll; `take_on_3_*`, `count_swing_bonus`, `two_strike_*` and `walk_scale` are unread under model 1. Starting table (zone / chase): 0-0 .444/.158, 0-1 .744/.280, 0-2 .871/.341, 1-0 .597/.223, 1-1 .777/.317, 1-2 .886/.386, 2-0 .582/.209, 2-1 .778/.325, 2-2 .893/.425, 3-0 .135/.036, 3-1 .719/.258, 3-2 .890/.449.
- **Foul trim:** `foul_rate` 0.41 -> 0.385, `two_strike_foul_scale` 1.02 -> 1.0, `count_foul_scale` flat (needs the dict loader or a strength key). Assumes `foul_territory_scale` 0.
- **`eye_control_blend`** 0.2 -> 0.0 (new key at the eye blend in `_batter_context`): control acts through location only, so pitcher fatigue produces walks.
- **`command_model` 0|1:** `sd_mult = command_error_ref_mult(2.55) * exp(-c * 0.02)`, `zone_target += c * 0.004`, `c = control_fatigued - pitcher_control_center`. BB per +10 control: -0.76 pp today -> -1.25 pp (MC).
- **`umpire_model` 0|1:** probabilistic edge, `P(strike | take) = 1/(1+exp((d - d0)/0.07))`, `d0 = -0.055 + (catcher_fa - centre)/100 * 0.08 + (balls - strikes) * 0.012`. The offset must be negative (a symmetric edge costs -1.9 pp BB, +2.9 pp K). Replaces shrink/margin/framing keys. Framing: about 0.05 R/G per 10 catcher fa (estimate).
- **`hbp_model` 0|1:** HBP only on pitches far enough inside (`hbp_inside_rate` 0.20, min 0.35 ft, span 0.6 ft); 1.0-1.1% of PA, none in the zone, control-35 about twice control-65. Confirm the +x = RHB-side convention before building.
- **`ibb_model` 0|1:** relative to the on-deck hitter: `gap = offense(batter) - offense(on_deck)` vs this pitcher, ramp from 2.0 to 7.0, x `ibb_chance` 0.35, x 0.1 outside late & close, x 0.3 with no outs. About .25-.30% of PA (extrapolated from a .41-.51% run at chance 0.6), 66-76% late & close.
- **`batter_fatigue_eye_scale`** 0.7 -> about 0.25 (eye becomes about 3x stronger on walks).
- **Slopes (MC, per +10):** eye BB +0.72 -> +2.49 pp, K -1.71 -> -0.84 pp; control BB -0.76 -> -1.25 pp.
- **Result (300g, both fixtures, foul territory 0):** BB .080 / .078, P/PA 3.84 / 3.85, per-count swing within .045 of MLB at all 12 counts, K .190 / .188, contact .794 / .797, R/G +0.1 to +0.2 (unresolved at 300 games).
- **Benchmarks to change:** `o_swing_pct` (.32 +/- .03) conflicts with Statcast (.286 chase, .672 zone); re-benchmark to Statcast.

### 2.2 Contact, whiffs and strikeouts (`physics.py` contact roll, two-strike take; `engine.py` hit probability)

- **`contact_model` 0|1.** One logistic draw, no cap, no `k_scale` division:
  `logit P(contact | swing) = (zone 1.94 | chase 0.68) + 0.090*(CH_ctx - hitter_contact_center) - 0.040*(pq - pq_center) - 0.40*break_ft - 0.0*(velo - v_ref) + 0.22*[two strikes]`. `contact_base` stays computed (exit velocity reads its pitcher part). Unread under model 1: `k_scale`, `contact_prob_scale`, `chase_contact_scale`, `count_contact_scale`, all `whiff_*`.
- **Contact-dependent called third strike:** `logit(protect) = logit(two_strike_zone_protect) + 0.06*(CH_ctx - centre) + 0.0*(eye - centre)` -> protect .41/.63/.81/.91 at CH 35/50/65/80. Under `swing_model` 1 (no protect roll) this term moves to the two-strike zone-swing logit (`swing_two_strike_contact_logit`).
- **Grid (MC, 20k PA per cell):** max log5 residual 5.7 pp -> 1.2 pp; pitcher effect +1.32/1.34/1.35/1.21 logit at CH 35/50/65/80 (today 1.12/1.32/1.01/0.64). Without the looking-K term the residual is still 3.5 pp.
- **Slope trap:** fitting the logistic to today's uncapped surface gives 0.073 / 0.029, which shrinks hitter K sd, AVG sd and pitcher K sd below their gates. Use 0.090 / 0.040.
- **`contact_logit_velo` registered at 0:** two-sided velocity belongs with Release 6's fatigue retune (today +1 mph is wrong-signed, +3.9 wOBA).
- **Contact BABIP edge (decision 4), minimal form:** `hit_prob += contact_babip_per10 * clip(contact - centre, +/-25)/10` on non-HR balls in play, raw rating (not `CH_ctx`), `contact_babip_per10` 0.010. Release 6 replaces it with a mechanistic channel.
- **Retune sensitivities (proxy):** -0.10 on both intercepts = K +1.1 to +1.4 pp, contact -1.4 pp, SwStr +0.7 pp; +0.10 on the two-strike term = K -1.1 pp, contact +0.7 pp. R/G about -0.1 per +1 pp K (rule of thumb).
- **New centres** in `services/league_rating_centers.py`: hitter contact, hitter eye, pitcher movement, pitcher grade (mean of repertoire).

### 2.3 Platoon and handedness (`engine.py` `_batter_context`, `_platoon_bonus`, `_matchup_score`; `utils/lineup_autofill.py`; generator)

- **One helper `platoon_shift(batter, pitcher_hand, tuning) -> (h, d_hand)`** used by all five places that hard-code the constants today.
- **Asymmetric handedness bonus:** `a_L = handedness_lhb_scale` (1.0); `a_R = a_L * clamp((1-w)*rhb_scale + w*rho + bias, .35, 1.0)` with `rho = (2l+s)/(2r+s)` from the league's ACT batting-side shares, `handedness_rhb_scale` 0.6, `handedness_balance_strength` w (owner decision: 1.0 = LHP = RHP in every league; 0.0 = fixed MLB-size split).
- **Switch hitters get the full bonus** (decision 6): `handedness_switch_bonus` 0.5 -> 1.0.
- **Power bonus after the knee:** platoon power no longer shifts the rating through the bat-speed knee (today the HR ratio steps from 1.16 below PH 50 to 1.52 at PH 54); it adds `P * platoon_bat_speed_per_point` (0.30-0.41 mph per point) after the curve. The TTO power bonus shares the path.
- **vl read against the league's by-bats ACT mean** (`platoon_vl_center_enabled`, `hitter_vl_center_l/_r/_s`), a no-op once Release 7 recentres the data. `lineup_autofill` reads the same centred vl.
- **Generator, new leagues:** C/2B/3B/SS batting side from 75/15/10 (R/L/S) to about 60/27/13 (decision 7). The by-bats vl nudge stays for draft classes entering existing leagues until Release 7 (or is replaced by "league centre - 50" at generation).
- **Expected (model):** calibration pooled gap .031 -> .025-.026, LHB .027-.029, RHB .017-.021; league fixture LHP - RHP +0.40 -> -0.03 (balanced) or +0.08 (fixed 0.6); R/G +0.03 to +0.08.
- **Gates:** restore `platoon_gap_woba` tolerance to 0.006; gate LHP - RHP on a 4-seed mean (its single-season sd is 0.095). `tests/test_physics_sim_kpi_harness.py:83-89` and `tests/test_r4_gates.py:79,271` pin the old values.
- Size the three handedness bonuses LAST (the contact model raises the value of a contact point; expect contact bonus x0.85-0.9).

### 2.4 Situations, parks, home field, times through the order

- **`foul_territory_scale` 1.0 -> 0.0** (plumbing kept for Release 6's foul-out roll).
- **`pitch_objective_fbo_requires_risp` 0 -> 1:** the first-base-open modifier fires on 65% of PA today (54% bases empty); gated, BB -0.28 pp.
- **`pitch_objective_late_close_strength` 1.0 -> 0.0:** removes +0.53 pp BB on 18% of PA. The strength-1.0 branch must use the table untouched (bit-identity).
- **Reliever fresh-arm edge:** control and movement `+ reliever_fresh_bonus` (1.0; tune 0.8-1.5) for a reliever's first 4 batters, fading to 0 by the 7th. Not velocity (wrong-signed), not a negative fatigue penalty.
- **Home field, zero-sum:** `home_field_edge` 0.8 added to the home side's contact/eye (x0.6 power) and subtracted from the road side's, in `_batter_context`. Read `home_wpct` pooled over >= 6 seeds (per-season SE .010); tune on a new `home_minus_away_woba` (target about +.011).
- **TTO per-pass weights:** `tto_pass2_weight` 1.0 -> 4.5 (tune 3.5-5), `tto_pass3_weight` held at 2.0 until Release 6. Redefine the strict `tto_ops_gap` as starters-only (pass 1 is 64% relief PA, so the reliever edge alone would trip it).
- **Expected (model, +/-50%):** late & close delta about -.025, innings 7-9 ratio about .94, TTO pass 2 about +.010, home W% about .535; this area alone is R/G -0.18 calibration / -0.07 league, which the contact/discipline retune and run-level knobs must give back.

### 2.5 Harness and gates (tooling)

- Dict-valued `--tuning-overrides`; fix the harness lineup-hand bug and re-baseline the league fixture; `scripts/kpi_profiles/r5.json` holds the switched-on profile while it is tuned.
- New report-only KPIs: `foul_per_two_strike_pitch`, `foul_share_of_contact`, `looking_k_per_pa`, per-count zone and chase swing, BB per 10 eye, BB per 10 control, hitter O/Z-swing correlation, pitcher zone% true sd, `hbp_in_zone_share`, out-of-zone called-strike rate, IBB late-and-close share, grid K split (swinging/looking), `hitter_avg_true_sd`, `babip_contact_slope_per10`, `r_ch_babip`, platoon HR-ratio grid and K/BB/ISO gaps, `lineup_hand_match_rate`, rating-adjusted LHP - RHP, `late_close_ubb_pct_delta`, `relief_bf1_6_minus_starter_pass1_woba`, `save_conversion`, `home_minus_away_woba`.
- Gates to promote when green: per-count swing within .05, `matchup_k_log5_max_abs_resid` <= .02, TTO pass 2 (pooled), home W% (pooled), LHP - RHP (4-seed mean), platoon at 0.006.

## 3. Build order

1. **5a, tooling only (PATCH, ships at once):** 2.5, all new keys registered with their off values, identity tests, the new rating centres and batting-side shares.
2. On the branch: `foul_territory_scale` 0; re-baseline.
3. Build the four areas behind their switches, in parallel worktrees, each with an adversarial review: discipline (2.1), contact (2.2), platoon (2.3), situational (2.4).
4. Integrate; tune through `r5.json` in this order: swing table + foul trim -> contact intercepts and two-strike term -> command/umpire (BB level) -> first-base-open and late-close -> TTO and reliever edge -> platoon bonuses -> home field -> run level (`offense_scale` / `babip_scale`) last.
5. Verify: strict KPI on calibration seeds 1-8 and league seeds 1-4, the matchup grid at 20k PA, the live-path driver across batching modes, the full suite.
6. **5b, the flip (MINOR):** defaults switched on, sliders rebased, gates promoted, legacy profile kept for one release, help text and news post.

## 4. Verify targets (both fixtures unless noted)

K .22, BB .082 (unintentional about .0795), SwStr .11, contact .76, P/PA 3.88, per-count swing within .05; K log5 residual <= 2 pp in every 35-80 cell; BB per 10 eye +2.3 to +2.8 pp, per 10 control -1.2 to -1.5 pp; platoon pooled .026 +/- .006, LHP - RHP within +/-0.15 (4-seed mean); late & close OPS .02-.04 below overall; innings 7-9 runs per half below 3-6; TTO pass 2 >= +.008 (pooled); home W% .535 +/- .015 (pooled); IBB about .0025; `corr_avg_contact` >= 0.5 (not worse; final gate Release 6); R/G 4.47 +/- .25 on BOTH fixtures.

## 5. Risks and do-not-do

- From REPORT section 7: no product or soft cap; no `k_scale` 1 with the .95 ceiling kept; no `whiff_base` raise; no `k_scale` .55 + `count_contact_scale` 1.0; keep a positive two-strike contact term; never route a new batter term through `contact_base` (it lowers exit velocity); do not scale the platoon bonus with Power; do not re-sign vl.
- Do not change `close_game_run_diff` (hook aggression shares it); do not touch `hook_tto_penalty` or fatigue knobs; do not fill pitcher vl; do not edit the calibration fixture or regenerate the league fixture (Release 7).
- Until Release 6 moves the 0.4 control weight out of pitch quality, control is both +2.7 pp K and -1.25 pp BB per 10: watch `qualified_era_sd`.
- Live leagues see little of the eye/control spread until the Release 7 re-spread (eye and control are compressed in generated data).
- The whole random stream changes at the flip: seed-pinned tests need the legacy profile, and noisy gates must be judged on 8 seeds.
- Commissioner sliders (Walk Rate, Zone Swing, Chase, Two-Strike Aggression, Two-Strike Protect) stop working under `swing_model` 1 unless rebased. `config/rule_presets.json` sets `walk_scale` 1.05 / `k_scale` 0.92 against defaults of 0.83 / 0.51: check whether presets are in use before the flip.

## 6. Owner decisions

Taken 2026-10-12; see DECISIONS.md "Release 5 owner decisions". The one that changes this plan: **the switch-on (5b) waits for alpha-test's next season** rather than going live mid-season, so step 6 of the build order is held after it is green. Open technical choice for the build: one global default flip at that point, or a per-league, per-season engine profile (next to `rating_centers.json`) so every league switches at its own rollover.

## 7. The switch-on mechanism (built: per-league, per-season engine generation)

The second option was built. `DEFAULT_TUNING` does not change; the switch-on is a profile laid over it.

- **Generations.** Legacy (today's engine) is generation 4; Release 5 is generation 5. `physics_sim/engine_generation.py` reads a generation's profile from `physics_sim/profiles/engine_<N>.json`: one plain data file per generation, in the package, so the backend image ships it. `scripts/kpi_profiles/r5.json` is the harness-facing copy and a test fails if the two differ. To retune: overwrite `engine_5.json` and copy it over `r5.json`.
- **A season's generation** is stored in the season's entry of `<league>/rating_centers.json` as `engine_generation` (`services/league_rating_centers.py`). An entry with one plays it all season. An entry without one is legacy (it was written before generations existed, or the season started legacy; legacy is never written down, so a legacy league's file is unchanged). A season with no entry gets generation 5 only if no regular-season game of it has been played (no played schedule row, schedule cursor at 0, no wins or losses in the standings); otherwise it keeps the engine it has been on. So nothing changes for a league at deploy, it moves at its own rollover, and a new league starts on generation 5.
- **Tuning order**, everywhere a league's games get their tuning (`services/league_tuning.py`): engine defaults, the generation's profile, the stored commissioner overrides, the rating centres.
- **Sliders** follow the generation, not a key in the overrides file: generation 5 leagues get the rebased sliders and their stored legacy values are converted (and replaced) the first time the file is loaded or saved under generation 5.
- **Holding the rollout.** `NEXGEN_NEW_SEASON_ENGINE=4` in the service's environment starts every new season on the legacy engine; a season that already has a generation is not moved by it. The test suite sets it, so existing tests run on the legacy engine.
- **Harness.** `scripts/physics_sim_season_kpis.py --engine 5` applies the profile before `--tuning-overrides`; with no `--engine` the run is the legacy engine. `--gate-set r5` is a small set the profile already holds; the CI step that runs it is not blocking.
- **Done at the switch-on (7.51.0):** the final profile numbers (section 8); the CI step runs the full strict set with `--engine 5`; help text and the tutorial ("The Updated Game Engine") for the rebased sliders; the VERSION bump and release notes. **Still open:** that CI step is `continue-on-error` until it has passed once on the CI runner; drop it then, so a miss fails the job.

## 8. As built (2026-10-12)

**Switch-on.** Each league season records the engine it is played on: a season already under way finishes on the legacy engine, and a season with no regular-season game played starts on the Release 5 profile, so every league moves at its own rollover and a new league starts on it (section 7). The legacy engine is the engine defaults with no profile laid over them, and its results are unchanged to the last digit.

**Final measurements** (`--engine 5`; calibration fixture seeds 1-18, league fixture seeds 1-6; means):

| Metric | Target | Calibration (18 seasons) | League (6 seasons) |
|---|---|---|---|
| Runs per team-game | 4.47 +/- .25 | 4.39 | 4.13 (short) |
| K% | .22 | .220 | .226 |
| BB% | .082 | .082 | .082 |
| Contact | .76 | .763 | .757 |
| Pitches per PA | 3.88 | 3.87 | 3.88 |
| Home runs per team-game | 1.17 +/- .15 | 1.08 | 0.94 (short) |
| Platoon gap, pooled (wOBA) | .026 +/- .006 | .026 | .020 |
| LHB gap | .028 | .025 | .031 |
| RHB gap | .018 | .023 | .012 |
| LHP minus RHP, RA9 | 0 +/- .15 | +0.02 | -0.10 |
| Home W% | .535 +/- .015 (pooled) | .529 | .546 |
| Home minus road wOBA | +.012 +/- .009 | +.011 | +.015 |
| TTO pass 2 wOBA | >= +.008 (pooled) | +.012 | +.010 |
| Late and close OPS delta | -.02 to -.04 | -.024 | -.033 |
| Innings 7-9 over 3-6, runs ratio | MLB about .935 | .915 | .866 |
| IBB per PA | about .0025 | .0024 | .0024 |
| HBP per PA | about .011 | .0105 | .0108 |
| HBP, same-hand over opposite-hand | about 2 | 2.1 | 1.9 |
| BB% per 10 Eye | +2.3 to +2.8 pp | +2.5 | +2.9 |
| BB% per 10 Control | -1.2 to -1.5 pp | -1.26 | -1.30 |
| Contact-to-AVG correlation | >= .5 | .62 | .65 |
| Power-to-HR correlation | floor .45 (>= .60 from Release 6) | .58 | .66 |
| K matchup grid, worst log5 error | <= 2 pp | 1.5 pp (one seed) | |

Calibration seeds 1-18 pass the full strict set; league seeds 1-6 pass the running-game set. The product's own game path (a product-created 30-team league, 420 games per engine; sampling error about +/-0.11 runs) reads runs per team-game about 4.9 legacy and about 4.3 on the profile, K 20.8% to 23.2%, BB 9.5% to 7.9%, HBP 1.4% to 1.0% of PA, IBB none to about 15 per team-season, home W% 49% to about 53%.

**What differs from the plan:**

- **Contact hit edge:** `contact_babip_per10` 0.005, not 0.010 (2.2; owner decision 4). At .010 too many hitters batted .300. At .005 the Contact-to-AVG correlation is .62 / .65, above its .5 floor.
- **Handedness bonuses** were sized last, as planned, and then re-sized after the hit-by-pitch handedness fix, because hit batters count in wOBA: contact 1.85, eye 1.35, power 2.0 (defaults 1.8 / 1.2 / 2.0), with `hbp_same_hand_scale` 1.75 and `hbp_opposite_hand_scale` 0.57. The plan expected the contact bonus to shrink (x0.85-0.9); it did not.
- **Home field:** `home_field_edge` finished at 0.80, the plan's starting value (an interim tune used 0.72), for a pooled home W% of .529 / .546 against the .535 target.
- **Power is not centred on the league.** Contact and Eye are read against the league's own averages; Power still is not, which is why home runs and scoring run low on the league fixture. Left for Release 6.
- **BB spread is gated as slopes** (BB% per 10 Eye, per 10 Control), not as the true-sd targets, which the committed fixtures cannot meet (0.11).
- **Single-season home W% and TTO pass 2 are read pooled, not gated.** One season's home W% has a standard error of about .011. The gates are home-minus-road wOBA (+.012 +/- .009) and the starters-only times-through-the-order OPS gap (`tto_ops_gap_starters`), which replaces `tto_ops_gap`.
- **Switch-on per league** rather than at one league's rollover (section 7), and the generator's new batting-side mix also applies to future draft classes in existing leagues (DECISIONS.md, "As built").
- **Tuned values that moved from the starting numbers in section 2** (the tuning order of section 3): contact intercepts 1.49 zone / 0.23 chase (1.94 / 0.68), two-strike term 0.20 (0.22), `foul_rate` 0.395 (0.385), `swing_eye_chase_logit` 0.039 (0.035), command slope 0.023 (0.02), `ibb_chance` 0.44 (0.35), `zone_target_base` 0.34 (default 0.36), and the run-level knobs `hr_scale` 0.93 and `babip_scale` 0.941 (defaults 0.925 / 0.925). The profile itself is `physics_sim/profiles/engine_5.json`.

**Known shortfalls:**

- **Scoring on league-like rosters.** The league fixture is 0.34 runs per team-game under the target (4.13; the gate floor is 4.22) because home runs run low (0.94 against 1.17), as it was before Release 5 (4.11 in section 1). The live-path sample lands about 0.2 under. Release 6 (Power read against the league) is the fix.
- **An 80 Contact hitter strikes out about 4%, not the owner's 3%** (decision 1): about 2% of PA end in a called third strike on the edge whatever the hitter's Contact (`docs/future_work.md`).
- **Home W%** reads .529 on calibration against the owner's .535, inside the pooled tolerance.
- **The league fixture's late innings overshoot** (innings ratio .866, late and close -.033): its relievers are rated well above its starters. Read the late-inning measurements on the calibration fixture until the Release 7 regeneration.
- **Live leagues see little of the Eye and Control spread** until the Release 7 re-spread; the slopes are right, the ratings are bunched.
- **Catcher framing (about 5 runs a season per 10 points)** is an estimate from the size of the effect, not a measured season total.
- **The matchup grid** was measured on one seed.
- **The rule presets** (High Offense, Pitcher Friendly) were re-sized on one seed each and await the owner's confirmation.
