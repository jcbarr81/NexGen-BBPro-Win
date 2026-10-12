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

**Switch-on.** Each league season records the engine it is played on: a season already under way finishes on the legacy engine, and a season with no regular-season game played starts on the Release 5 profile, so every league moves at its own rollover and a new league starts on it (section 7). The generation is written down twice, in the season's entry of `rating_centers.json` and as a witness in `season_progress.json`; if one record is lost or the two disagree, the higher generation is played and both are repaired, so a season never changes engine. The legacy engine is the engine defaults with no profile laid over them, and its results are unchanged to the last digit.

**Owner decision 13: every rating that feeds a plate appearance is league-relative** (DECISIONS.md; built after the first tune, and the profile was retuned for it). What was built:

- **Hitter centres on the lineup regulars, Power included.** `hitter_contact_center`, `hitter_eye_center` and the new `hitter_power_center` are means over the hitters in the clubs' lineups (the hitters who actually bat), not over every active hitter.
- **Workload-weighted pitcher centres.** Control, movement, pitch grade and arm are centred on the active staffs with each rotation starter counted 2.5 times a reliever (`pitcher_*_usage_center`). The plain means stay as they were for the Release 4 running-game terms.
- **One switch, `centred_ratings`, shifts each rating once at its source** (50 minus its league centre, where the rating enters the pitch), so everything downstream reads a league-relative number; the models that used to subtract a centre themselves compare against 50.
- **Completeness check.** A generation 5 season needs all seven centres on one definition (`centers_version`); an entry that is not whole is recomputed and reported, and the engine refuses to start a game whose centres were not delivered (`RatingCenterMissing`) instead of reading 50.
- **Acceptance test:** adding one constant to every hitter's Contact, Power and Eye, or to every pitcher's control, movement, arm and pitch grades, gives the identical game to the last bit. The centres are fixed when the season starts.

**Final measurements** (`--engine 5`, final profile; calibration fixture seeds 1-18, league fixture seeds 1-6, a product-created league seeds 1-6; means):

| Metric | Reference | Calibration (18 seasons) | League fixture (6) | Product-created league (6) |
|---|---|---|---|---|
| Runs per team-game | 4.47 +/- .25 | 4.35 | 4.45 | 4.52 |
| K% | .22 | .220 | .213 | .218 |
| BB% | .082 | .082 | .083 | .083 |
| Contact | .76 | .762 | .770 | .764 |
| Pitches per PA | 3.88 | 3.85 | 3.85 | 3.85 |
| Home runs per team-game | 1.17 +/- .15 | 1.10 | 1.09 | 1.00 |
| AVG | | .247 | .246 | .250 |
| OPS | | .719 | .723 | .719 |
| Platoon gap, pooled (wOBA) | .026 +/- .006 | .026 | .020 | .023 |
| LHP minus RHP, RA9 | 0 +/- .15 | -0.01 | -0.10 | -0.10 |
| Home W% | .535 +/- .015 (pooled) | .531 | .540 | .536 |
| TTO pass 2 wOBA | >= +.008 (pooled) | +.012 | +.009 | +.011 |
| Late and close OPS delta | -.02 to -.04 | -.027 | -.039 | +.002 |
| Innings 7-9 over 3-6, runs ratio | MLB about .935 | .92 | .87 | .97 |
| BB% per 10 Eye | +2.3 to +2.8 pp | +2.5 | +2.7 | +2.6 |
| BB% per 10 Control | -1.2 to -1.5 pp | -1.3 | -1.3 | -1.4 |
| Contact-to-AVG correlation | >= .5 | .62 | .63 | .62 |
| Power-to-HR correlation | floor .45 | .56 | .59 | .67 |
| IBB per PA | about .0025 | .0024 | .0024 | .0019 |
| HBP per PA | about .011 | .0103 | .0103 | .0096 |

Runs per team-game are inside the target on all three leagues and within 0.17 of each other; before the league-relative change they were 4.39 / 4.13 / 4.37. Strikeout matchup grid (one seed): worst log5 error 1.4 points (target <= 2); against an average pitcher an 80 Contact hitter strikes out 4.0%, a 65 Contact 9.4%, a 50 Contact 23.7% and a 35 Contact 49%.

Gates: 29 of the 30 seasons pass their checks. The calibration fixture passes every calibration check on 17 of 18 seasons; the one miss is a platoon gap of .0199 against a .020 floor, which will happen to about one season in thirty by chance at the +/- .006 tolerance the owner asked for. The league fixture is no longer short on scoring.

The product's own game path (a product-created 30-team league, 420 games per engine; sampling error about +/-0.11 runs and +/-.024 of home W%; serial and parallel play gave identical results): runs per team-game 4.95 legacy to 4.40 on the profile, K 20.8% to 22.0%, BB 9.5% to 8.2%, home runs per team-game 1.03 to 0.99, IBB per PA 0 to .0020 (about 12 per team-season), HBP 1.4% to 0.9% of PA, home W% .490 to .529.

**What differs from the plan:**

- **League-relative ratings** (above) were not in the plan, which read a few ratings against plain active-roster averages, term by term (2.2).
- **Contact hit edge:** `contact_babip_per10` 0.005, not 0.010 (2.2; owner decision 4). At .010 too many hitters batted .300. At .005 the Contact-to-AVG correlation is .62 / .63 / .62, above its .5 floor.
- **Handedness bonuses** finished at contact 1.8, eye 1.3, power 1.95 (defaults 1.8 / 1.2 / 2.0), with `hbp_same_hand_scale` 1.75 and `hbp_opposite_hand_scale` 0.57 for the hit-by-pitch handedness fix (hit batters count in wOBA). The plan expected the contact bonus to shrink (x0.85-0.9); it did not.
- **Home field:** `home_field_edge` finished at 0.80, the plan's starting value, for a pooled home W% of .531 / .540 / .536 against the .535 target.
- **BB spread is gated as slopes** (BB% per 10 Eye, per 10 Control), not as the true-sd targets, which the committed fixtures cannot meet (0.11).
- **Single-season home W% and TTO pass 2 are read pooled, not gated.** One season's home W% has a standard error of about .011. The gates are home-minus-road wOBA and the starters-only times-through-the-order OPS gap (`tto_ops_gap_starters`), which replaces `tto_ops_gap`.
- **Switch-on per league** rather than at one league's rollover (section 7), and the generator's new batting-side mix also applies to future draft classes in existing leagues (DECISIONS.md, "As built"; both confirmed by the owner).

**Final tuned values** (`physics_sim/profiles/engine_5.json`; section 2's starting number or the engine default in brackets): `centred_ratings` 1; contact intercepts 1.63 zone / 0.37 chase (1.94 / 0.68), contact slope 0.09 and pitch-quality slope 0.04 (as planned), two-strike term 0.20 (0.22), two-strike Contact term 0.06; `contact_babip_per10` 0.005 (0.010); `foul_rate` 0.395 (0.385); `swing_eye_chase_logit` 0.039 (0.035); command slope 0.023 (0.02); `zone_target_base` 0.32 (default 0.36); framing offset 0.045 ft; `ibb_chance` 0.44 (0.35); `home_field_edge` 0.80; `tto_pass2_weight` 4.5; `reliever_fresh_bonus` 1.0; handedness bonuses 1.8 / 1.3 / 1.95; and the run-level knobs `hr_scale` 0.91 and `babip_scale` 0.92 (defaults 0.925 / 0.925).

**League-relative ratings in detail (`centred_ratings`).** Decision 2 ("the engine reads each rating as 50 + (rating - league mean)") is now applied to every rating that feeds a plate appearance, not term by term. With `centred_ratings` 1 (in the generation 5 profile; 0, the default, is the legacy engine, whose results are unchanged to the last digit) each rating is shifted once, where it enters the pitch, by 50 minus its league centre: the hitter's Contact, Power and Eye in `engine._batter_context`, before the handedness, times-through-the-order, home-field and platoon shifts and the clamp; the pitcher's control and movement (before the fresh-arm bonus and the fatigue factors), every pitch grade and the arm rating behind his velocity in `engine._pitcher_context`. So bat speed and its knee, barrel accuracy, pitch velocity, the pitch-quality factor on exit velocity, foul rate and pitch selection all read league-relative numbers. The formulas that subtracted a centre themselves (contact model, swing model, command model, the two-strike terms) now compare against 50 through one accessor, `physics_sim.centred_ratings.rating_center`, and a test fails if a centre is read any other way. The few terms around the pitch that read the same ratings straight off the player (the doubles gap, the bunt, the balk, a tired hitter's penalty, the manager's offence and reliever scores) read them through `engine._league_relative`. The Contact hit edge and the Release 4 running-game terms still read the raw rating against the real centre. The hitter centres changed with it: `hitter_contact_center`, `hitter_eye_center` and the new `hitter_power_center` are means over the lineup REGULARS (the hitters in each club's saved lineup files, a hitter in both counting twice; the club's nine best ACT hitters for a file that is missing or that a game would not play), because the regulars are who bats and how far they sit above the bench differs by league (calibration +1.5 to +2.2, the others about +0.5). The pitcher's four ratings are shifted by workload-weighted centres of their own (`pitcher_control_usage_center`, `pitcher_movement_usage_center`, `pitcher_grade_usage_center`, `pitcher_arm_usage_center`): each ACT pitcher in his club's five-man rotation counts 2.5 and every other arm 1, the rotation being the one a game builds (`utils.rotation.staff_rotation` on the club's ACT arms and its staff file; the stored `role` column is not read). A plain ACT mean missed the pitchers who throw the innings by a different amount in each league (league fixture: arm +1.8, movement +0.8, pitch grade +0.7; calibration: control -0.6, arm +0.7; product: about 0); the weighted centres land within 0.3 of the innings-weighted means of a played season on every rating in all three. The plain means (`pitcher_control_center`, `pitcher_arm_center`, `pitcher_hold_center`, ...) are not redefined: the Release 4 running-game terms read them, as do stored season files. A LEGACY season's entry is never recomputed and, once it holds its Contact or Eye centre, never gains the Power centre or the usage centres (its file keeps its bytes). A generation 5 season needs all seven on one definition, so its entry records which (`centers_version`); an entry of such a season that holds any of them without the current marker (written by an earlier build, or merged with a stale 7.50.3 instance's centres during a deploy) has all seven recomputed and stored, one that is missing some has those added, and both are reported once, even mid-season: half-shifted, the league fixture played 3.79 runs a game against 4.56. The engine is the last line of defence: with the switch on it refuses to shift a rating by a centre that was not delivered with the tuning (`RatingCenterMissing`) instead of reading the 50.0 default. A game with no date (an exhibition) fixes no centres. The shifted rating is rounded to nine decimal places where it is made, so two leagues a constant apart read the identical number (without it one game in thirty picked a different reliever on the last bit of a float), a manager's score is rounded and a tie between candidates goes to the lower player id; all of that only under the switch. Under the switch the pickoff reads the pitcher's hold and arm against the plain ACT means through the Release 4 reader (it read them raw against 50); measured before the retune, that lowered pickoffs by about a fifth on calibration and a third on the league fixture, and nothing else moved beyond seed noise (calibration seeds 1-4 and league fixture seeds 1-2 against the same code without these fixes: runs -0.002 / -0.008 a team-game, K -0.04 / +0.08 pp, BB +0.04 / -0.04 pp, home runs -0.008 / -0.005). Acceptance test: add one constant to every hitter's Contact, Power and Eye and their centres, or to every pitcher's control, movement, arm and pitch grades and theirs, and a seeded game is the same game to the last bit, on the engine's own entry point and through the live game path (`tests/test_r5_centred_ratings.py`, `tests/test_r5_centred_entries.py`; `tests/test_r5_centred_guard.py` is the static guard on how the source reads centres and raw ratings). Measured before the retune, with the profile otherwise untouched (calibration seeds 1-4, league fixture seeds 1-2, a product-created league seeds 1-2; before -> after): runs per team-game 4.39 / 4.13 / 4.37 -> 4.43 / 4.57 / 4.60; K% .220 / .225 / .232 -> .240 / .232 / .237; BB% .082 / .081 / .080 -> .077 / .079 / .079; home runs per team-game 1.08 / 0.94 / 0.97 -> 1.21 / 1.21 / 1.10. The spread between the three leagues closed by about a third on runs and K (.26 -> .17 runs, 1.17 -> 0.81 pp K), a quarter on home runs (.15 -> .11) and a tenth on BB (0.25 -> 0.22 pp); the league fixture's home-run shortfall against calibration is gone, and what is left of the home-run spread is the product league trailing both. See `docs/future_work.md`, "Release 5 league-relative ratings". The run level and K / BB moved, so the profile was retuned afterwards; the final table above is measured with the retuned profile.

**Known differences and shortfalls:**

- **The product-created league hits about 10% fewer home runs than the two fixtures** (1.00 a team-game against 1.10 and 1.09). League averages do not remove it: its hitters' pull and ground-ball tendencies are bunched. Release 6 reworks batted balls.
- **The product-created league's late innings show almost no extra difficulty** (late and close +.002 of OPS, innings ratio .97), because its relievers are not rated above its starters and the fresh-arm edge by itself is small. On the two fixtures late-and-close hitting runs .027 and .039 of OPS below normal; the league fixture's relievers are rated well above its starters, so it sits at the strong end.
- **An 80 Contact hitter strikes out 4.0%, not the owner's 3%** (decision 1): about 2% of PA end in a called third strike on the edge whatever the hitter's Contact (`docs/future_work.md`).
- **Home W%** reads .531 to .540 on the three leagues against the owner's .535, inside the pooled tolerance.
- **Live leagues see little of the Eye and Control spread** until the Release 7 re-spread; the slopes are right, the ratings are bunched.
- **Only the mean is league-relative, not the spread** (`docs/future_work.md`, "Release 5 league-relative ratings").
- **Catcher framing (about 5 runs a season per 10 points)** is an estimate from the size of the effect, not a measured season total.
- **The matchup grid** was measured on one seed.
- **Parks.** The KPI harness finds park data through the ambient active league rather than the fixture, so a harness run started while something else in the checkout has switched the active league can play a whole season with no altitude (home runs about 5% lower, nothing else changed); this explained the one odd season seen during review. Live leagues are not affected: their park files sit at the top of the cloud data folder, which the lookup also searches (`docs/future_work.md`).
- **The rule presets** (High Offense, Pitcher Friendly) were re-sized on one seed each, before the retune; the owner confirmed the sizes.
