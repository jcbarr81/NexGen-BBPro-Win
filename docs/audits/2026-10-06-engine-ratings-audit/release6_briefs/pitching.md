# Release 6 design brief: pitching stuff, HR suppression, fatigue

The coupled change works on today's batted-ball model and is level-neutral: on 13 seasons it holds runs, K and HR on all three fixtures and passes the arm, pitch-grade, velocity-fade, ground-ball and TTO3 targets. Three targets are not met: the pitcher/hitter HR spread ratio on calibration (.70 against ≤ .5), the 91-105 pitch wOBA cost on the league fixture, and the K log5 grid at the CH80 × P80 corner on a composite grid.

Evidence labels: **season** = 162-game KPI run, `--engine 5` plus overrides on a patched in-memory kernel; **MC** = 30-40k PA per cell on the real kernel (average hitter, R/R, generic park); **arith** = arithmetic. "Flat" is the product fixture, labelled a flat-ratings stress case per the coordinator's correction; † marks anything that depends on it.

With every new key at its default, the patched kernel reproduced a 116-game calibration season exactly (harness metrics, report-only metrics and pitching lines), on both legacy and generation 5.

## 1. Current mechanism (generation 5 = legacy unless noted)

| Item | Code today | Keys |
|---|---|---|
| Pitch quality | `pq = .4·control + .4·movement + .2·grade` (`physics.py:1186`), computed only on a swing; swing decision never reads it (`:714-753`) | weights hard-coded; `contact_logit_pq` .040 (`:817`) |
| Velocity | `83 + .2·arm` (`engine.py:5099`) × fatigue factor + type offset; `ev_base = v·.48 + bat·.7` (`physics.py:1283`); `difficulty += max(0,(v-90)/20)` (`:1244`) | `ev_pitch_weight` .48; `contact_logit_velo` 0 |
| pq in exit velocity, three paths | `contact_base = CH − .4(pq−50)` into `quality` (`:1190`, `:1295`); `quality *= max(.75, 1−(pq−50)/250)` (`:1298`); `difficulty += max(0,(pq−50)/100)` (`:1243`) | none |
| Fatigue | `_fatigue_factors` hard-coded: velocity ×max(.85, 1−.15p), control ×max(.60, 1−.30p), movement ×max(.65, 1−.25p) (`engine.py:537-541`), applied to the league-relative rating (`:6687-6696`); grades untouched | `fatigue_decay_scale` 1.4 |
| TTO | `_tto_pass_weight` (`engine.py:679`) | pass 2 = 4.5, pass 3 = 2.0 (gen 5) |
| Launch angle | batter gf only (`physics.py:1316`); pitcher `gf` loaded, never read | — |
| Pitch usage | weight = grade (`physics.py:358`) | `pitch_seq_fastball_bias` 1.0 |

## 2. Where generation 5 stands (season; base = 2 seeds per fixture with my collector, plus the z2 baselines)

Release 5 moved none of these except walks when tired.

| Target | Cal | League | Flat† |
|---|---|---|---|
| FIP per +10 arm (want < 0) | +.06 ± .05 | +.06 ± .04 | +.20 ± .14 |
| Mean grade std beta on K (≥ .35) | .11 | .20 | .27 |
| Starter FB fade at 91-105 (1-2 mph) | 11.1 | 11.5 | 13.8 |
| TTO3 − TTO1 wOBA (+20-30) | +22 | +21 | +23 |
| Within-pitcher wOBA at 91-105 (+10-20) | +23 | +23 | +54 (n≈150) |
| Pitcher/hitter HR true-sd ratio (≤ .5) | 1.13 | .97 | .48 |
| Pitcher GB% true sd (≥ .05) | .001 | .003 | .005 |
| HR log5 residual, p5-p95 (±.3 logit) | .09 | — | — |
| Pitcher K true sd | .021 | .019 | .008 |
| FB + SI share of pitches | .43 | .43 | .335 |

- **TTO3 and the 91-105 cost already read in band,** but through the wrong mechanism: K −5.8 / −4.3 pp and EV −0.5 / −0.25 mph at 91-105 (season, cal / league), because the velocity collapse still cancels contact damage.
- **The HR log5 gate already passes on the generated population.** The defect is at the corners (MC, composite = control = movement = grade): pitcher effect P35→P80 is −5.9 logit at PH35 and −2.7 at PH80; an average hitter homers .04% of PA off a composite-80 pitcher.
- **Mean penalty on pitches 91-105 is .83 / .88 / 1.11†,** not the audit's 1.26-1.5. Coefficients are sized at about .85.
- **Fastballs are much the hardest-hit pitch:** EV 91.0 against 87.9 slider and 84.9 curve. More of that gap comes from the break-difficulty term than from velocity (MC: at type weight .25 a fastball-only pitcher still allows EV 91.1 against 88.3 for fb/sl/cu).

## 3. Proposal (generation 6 starting values; every key registered, defaults reproduce today)

```
# A. stuff (decision 10)
pq = wc·control + wm·movement + wg·grade − stuff_loss     # .15/.30/.55 (default .4/.4/.2)
chase: swing_logit(out of zone) += swing_pq_chase_logit·(pq−50)   # .02 (default 0); pq computed before the swing, no extra draw
contact_logit_pq stays .040

# B. velocity (H6)
v_ref = contact_velo_ref + offset[type]
ev_base = ev_pitch_weight·v_ref + ev_velo_dev_weight·(v − v_ref) + ev_base_offset_mph + bat·ev_bat_weight
          # ev_velocity_model 1: .25 / .10 / +20.0 (default: .48·v)
contact_logit_velo = .06                                  # two-sided, existing key
difficulty_velocity_scale = 0

# C. one pq path into exit velocity (decision 13)
quality *= max(.75, 1 − ev_pq_slope·(pq−50))              # .0015 (default .004 = 1/250)
ev_pq_contact_base_weight = 0, difficulty_pq_scale = 0
          # the build needs a separate EV-only contact_base: legacy contact_model 0 rolls contact on it

# D. fatigue (H10), additive, fatigue_model 1
control −= 3.0·p;  movement −= 1.5·p;  stuff_loss = 1.0·p;  velocity −= 1.5 mph·p
tto_pass3_weight = 6.0;  reliever_fresh_bonus = 1.7       # +1 control/movement is worth .45 pq now, was .8

# E. batted-ball identity (M11, L7)
shift° = pitcher_gb_launch_scale·(gf − pitcher_gf_usage_center) − pitch_type_launch_offset[type]
LA −= shift·(air + (1−air)·clip((30−LA)/20, 0, 1))        # k .20, air .30, si −4.0, fb +1.5
launch_angle_base 12.1 → 11.8;  pitch_type_usage_weight fb, si = 1.25

# level retune used in the prototype
contact_logit_zone / chase 1.63 / .37 → 1.66 / .40;  hr_scale .91 → .905
```

How the values were derived:
- **Velocity terms:** a `contact_logit_velo` × `ev_velo_dev_weight` scan (MC), then seasons. `ev_velo_dev_weight` 0 with slope .05 gives FIP −.11 per 10 arm; .10 / .06 gives −.10; .2 on actual velocity leaves it near 0.
- **`ev_base_offset_mph`** (MC): +20.0 holds the 50 × 50 cell's EV and HR at type weight .25.
- **`ev_pq_slope`** (MC, then season): .002 gives HR −.032 logit per composite point; .0015 gives −.027. The HR ratio on one calibration seed was .51 at .002 with no ground-ball term.
- **Fatigue** (MC ramp): chosen for about +11 wOBA and −1.3 mph at penalty .85.
- **Ground-ball k** (MC): ±6.3 pp GB per 10 gf, so gf sd 8 gives sd .05.
- **`tto_pass3_weight`** (season): each weight unit is worth 2.7 wOBA. Weight 7 read +27 to +35 on the KPI; 6 reads +22 to +25.

**Not expressible through `--tuning-overrides` today:** everything except `contact_logit_velo`, `tto_pass3_weight`, `reliever_fresh_bonus`, `launch_angle_base`, the contact intercepts and `hr_scale`.

**`pitcher_gf` is not league-relative.** It needs a new centre, `pitcher_gf_usage_center`. The prototype read it against 50; fixture means are 49.7 / 50.0 / 50.5.

## 4. Evidence

Final candidate `ov/s3.json`: calibration seeds 1-4, league fixture 1-6, flat 1-3 (season).

| Metric | Target | Cal | League | Flat† |
|---|---|---|---|---|
| Runs per team-game | 4.47 ± .25 | 4.35 | 4.41 | 4.53 |
| K / BB | .22 / .082 | .2215 / .079 | .218 / .080 | .220 / .0805 |
| HR per team-game / BABIP | hold | 1.10 / .284 | 1.085 / .278 | 1.01 / .291 |
| Strict gates | — | 4 of 4 seasons clean | 3 of 6 clean (5 metric misses in total; base 2 a season) | 0 of 3 clean (2.3 misses a season; base 3) |
| FIP per +10 arm | < 0 | −.18 ± .05 | −.21 ± .04 | −.20 ± .14 |
| Grade std beta on K | ≥ .35 | .44 | .52 | .61 |
| FB fade at 91-105, mph | 1-2 | 1.26 | 1.29 | 1.62 |
| TTO3 − TTO1 (batter-adjusted) | +20-30 | +25 (+18) | +23 (+16) | +22 (+15) |
| TTO2 − TTO1 | ≥ +8 | +12 | +12 | +10 |
| wOBA at 91-105 (batter-adjusted) | +10-20 | +19 (+31 ± 6) | −3 (+8 ± 5) | −5 (n = 171) |
| Pitcher/hitter HR sd ratio | ≤ .5 | **.70** (.0055 / .0078) | .53 (.0040 / .0075) | .18 |
| Pitcher GB% true sd; r(gf, GB%) | ≥ .05 | .051; .80 | .055; .82 | .024; .51 (gf sd 3.0) |
| Pitcher K true sd | not lower | .027 | .031 | .018 |
| Qualified ERA sd / FIP sd | sensible | .76 / .59 | .71 / .53 | .54 / .42 |
| Qualified EV-against sd, mph | — | .88 (was 1.93) | .92 (was 1.64) | .80 (was 1.06) |
| GB% fastball / sinker / curve | — | .37 / .54 / .45 | .38 / .53 / .45 | .37 / .54 / .45 |

- **Rating values per +10 on calibration (season, weighted OLS on pitchers ≥ 40 IP), today → S3.** FIP: control −.87 → −.38, movement −.80 → −.40, grade −.25 → −.62, arm +.06 → −.18. K: grade +0.8 → +3.4 pp, arm +0.5 → +1.8 pp, control +2.4 → +1.2 pp. HR per BF: control −.78 → −.04 pp, movement −1.00 → −.33 pp. BB per 10 grade: +.10 → −.60 pp (chase).
- **Power × pitcher composite grid, 35-80 (MC, 40k per cell), PH50 row:**

  | | P35 | P50 | P65 | P80 |
  |---|---|---|---|---|
  | HR/PA today | .0600 | .0239 | .0040 | .0004 |
  | HR/PA S3 | .0350 | .0230 | .0145 | .0082 |
  | wOBA S3 | .374 | .297 | .231 | .160 |
  | K S3 | .145 | .230 | .360 | .521 |

  Pitcher HR effect P35→P80 goes from −5.9 / −5.1 / −3.8 / −2.7 logit (PH 35/50/65/80) to −1.6 / −1.5 / −1.2 / −1.0. Maximum HR log5 residual over the whole box is .28 logit (today 1.94). The harness grid on p5-p95 reads .03 logit. PH80 × P80 is .055 (today .013).
- **K grid.** The harness grid (control = movement only) reads 1.97 pp against the 2 pp gate. On a composite grid the CH80 × P80 corner is 2.6 pp (today 2.2; 1.8 without the chase term). Everything inside 35-65 is ≤ 1.3 pp.
- **Fatigue ramp, average pitcher (MC), penalty .5 / .85 / 1.0 / 1.5:**

  | | wOBA | FB mph | K | BB |
  |---|---|---|---|---|
  | Today | +18 / +24 / +29 / +62 | −7 / −12 / −14 / −14 | −5.1 pp at .85 | +1.7 pp at .85 |
  | S3 | +8 / +11 / +13 / +18 | −.75 / −1.3 / −1.5 / −2.25 | −2.2 pp at .85 | +0.7 pp at .85 |
  | S3 kernel, old fatigue | +29 / +41 / +48 / +60 | as today | −9.7 pp at .85 | — |

  The third row confirms the two must ship together. Additive loss treats pitchers alike at .85 (good-60 +8, poor-40 +14); today it is +39 against +8.
- **Stuck-pitcher punishment (H1), penalty cap 1.5 (MC):** +62 → +18 wOBA.
- **What an owner sees (MC).** A 70-grade arsenal with average control and movement strikes out 32% (today 26%). A 70 / 60 / 60 ace: K 36%, BB 5.1%, wOBA .232 (today 33%, 7.1%, .223). He is about as valuable as now, through strikeouts and walks rather than through near-zero home runs.
- **Ground-ball term (MC), per 10 gf:** GB ±6.3 pp, HR ±12%, wOBA ±12. As a plain mean shift the same GB spread costs HR ±28%.
- **Per-type grade centring** (each pitch read against its own type's league mean; season, 1 seed)†: FB + SI share .377 → .437 on the flat fixture and .475 → .477 on calibration, with runs and HR level. The need is shown only on the flat fixture; the audit reports the same pattern in alpha.

## 5. Expected movement and interfaces

- **League level:** run-, K- and HR-neutral after the two-knob retune. BB reads −0.2 to −0.3 pp, and BB per 10 control −1.6 (Release 5 band −1.2 to −1.5). Trim `command_error_control_log_slope` to about .021 and re-level `zone_target_base`.
- **Batted-ball agent, interface I need:**
  1. One multiplicative pitcher term on EV, `1 − ev_pq_slope·(pq−50)`, plus an additive pre-quality velocity term. No pq or velocity in timing or barrel difficulty.
  2. A pitcher launch-angle shift in degrees that acts fully at the grounder/liner boundary and at about 30% on fly balls. In a mixture, that is a log-odds shift of the ground component's weight.
  
  The break-difficulty term is theirs, and it drives most of the fastball-against-breaking EV gap. `ev_pq_slope`, `air` and `ev_base_offset_mph` must be re-sized after drag carry and the LA mixture land, because HR leverage on EV changes.
- **Power agent:** the HR ratio gate needs hitters' HR true sd to rise from about .0078 to about .011, or a smaller pitcher term.
- **Fielding agent:** a +10 gf pitcher is −12 wOBA through GB out rates, so new infield chance bands re-size it.
- **Buildable and measurable on today's model first:** A, B, C, D. E is buildable but must be re-sized afterwards.

## 6. Measurement

- **Existing:** `starter_fb_velo_drop_91_105`, `starter_woba_delta_91_105`, `tto_pass2_woba_delta`, `tto_pass3_woba_delta`, `pitcher_hitter_hr_true_sd_ratio`, `pitcher_k_pct_true_sd`, `matchup_hr_log5_max_abs_resid_logit`, `matchup_k_log5_max_abs_resid`, `qualified_era_sd`, `relief_bf1_6_minus_starter_pass1_woba`, `bb_pct_per10_control`.
- **Not in `kpi_extras` today; prototypes are in my `run_kpi.py` and `ana.py`:**
  - FIP and K per 10 arm / control / movement / grade, and the grade std beta;
  - pitcher GB% true sd and r(gf, GB%);
  - GB% and EV by pitch type;
  - FB + SI share;
  - pitcher chase true sd;
  - qualified FIP and EV sd;
  - within-pitcher K / BB / EV at 91-105;
  - batter-adjusted 91-105 and TTO deltas.
- **Harness grid:** it must vary grade with control and movement, or it understates the pitcher at the new weights.
- **The 91-105 and TTO KPIs carry lineup-slot bias.** Pitches 91-105 fall on the bottom of the order, so the raw 91-105 delta reads about 11 low; pass 3 is top-heavy, so raw TTO3 reads about 7 high. Gate the batter-adjusted forms.

## 7. Owner decisions

1. **Arm becomes a strikeout rating.** +10 arm is about +1.5 to +1.8 pp K and −.2 FIP (today slightly harmful), roughly a third of a pitch-grade point's worth. Recommend yes at slope .06; .05 if it should stay minor.
2. **The ace's strikeout edge per quality point stays at .040.** The re-weighting alone triples the grade effect and lifts pitcher K true sd about 30-50% on the two fixtures. Recommend holding; reaching MLB's roughly .04 is the Release 7 re-spread's job.
3. **Control becomes mostly command.** K per 10 control halves, the BB effect is kept, and its HR effect goes to nil. This is decision 10 as written; an owner with control-heavy pitchers will see them lose value. Recommend accept.
4. **Ground-ball pitchers allow fewer home runs.** Recommend modest (12% per 10 gf), accepting an HR ratio of about .6-.7 on calibration until Power is steepened. The alternative, air share .1, measured .61 on calibration seeds 1-3 (candidate .69 on the same seeds).
5. **Fatigue size.** The candidate costs about +11 wOBA at 91-105 pitches and +18 if left in to the cap. A stronger set (control 4, movement 2, stuff 2) costs +19 at penalty 1.0 (MC). Recommend the candidate, re-read on adjusted KPIs.
6. **Third time through the order becomes mostly familiarity** (weight 6, above pass 2's 4.5). Recommend yes.
7. **Fastball share about 47%** via usage weights, and whether each pitch type is graded against its own league mean†. Recommend the weights now and per-type centring only if alpha's data confirms the need.
8. **Commissioner "Velocity" slider flips meaning** (more velocity is now more strikeouts, not more offence). It needs help text.

## 8. Risks and do-not-do

- **REPORT section 7:**
  - never ship the fade cut or the EV fix alone (measured above);
  - do not size fatigue at penalty .5-1.0 only;
  - `whiff_velocity_scale` alone leaves FIP wrong-signed (hence the type-reference EV term);
  - do not re-spread pitcher ratings before C ships.
- **Manager and rating consumers still rank pitchers on the old formula.** The reliever score reads (control + movement + arm) / 3 (`engine.py:914`). OVR, CPU scores and the generator archetypes need the new weights, or CPU clubs deploy by an outdated formula.
- **League fixture reads −3 at 91-105 (adjusted +8 ± 5).** Good starters lost +39 when tired under the old multiplicative factors and lose +8 now.
- **Chase term adds 0.8 pp to the K log5 corner residual.**
- **Qualified ERA sd falls about .03-.05 on the fixtures,** because pitchers control less contact quality.

## 9. Release 5 leftovers

- **Long reliever past nine batters:** 1.1-1.4% of relief PA (season). Recommend no change.
- **Fresh-arm bonus to wild pitches and balks (arith):** +1.7 control is about −4% wild pitches for a few batters, under 2% of the league total. Not worth a mechanism. If touched, pass the same effective control (fresh and fatigued) to both rolls.
- **Fresh bonus:** re-sized to 1.7; `relief_bf1_6_minus_starter_pass1_woba` reads −.0075 / −.026 against −.010 / −.026 before.

## Build order

1. **Tooling, safe to ship alone:** the new KPIs, the composite harness grid, the batter-adjusted deltas, `pitcher_gf_usage_center`, all keys registered at their off values, identity tests.
2. **A + B + C + D as one switch group, never separately.** Retune the contact intercepts, `hr_scale`, BB, the fresh bonus and `tto_pass3_weight`.
3. **E,** after the batted-ball model's launch-angle interface exists.
4. **Manager and OVR weights.**
5. **Per-type centring,** only if confirmed on alpha.

## Not verified

- The HR ratio ≤ .5 on calibration. The slope .001 + air .1 combination was not run; air .1 alone gave .61.
- The 91-105 target on the league fixture, and the stronger fatigue set in seasons.
- Per-type centring beyond one seed, and not on the league fixture.
- Legacy-engine behaviour with the knobs on. All seasons were generation 5.
- Anything on the future batted-ball model.
- The arm slope against a real MLB reference; the sizes used are approximate.
- The seasons used a multi-key stand-in for one `ev_pq_single_path` switch.

Everything is in `C:\Users\james\AppData\Local\Temp\claude\c--Users-james-OneDrive-Documents-Baseball-AI-NexGen-BBPro\31cccd52-8c06-46f6-a76c-f8479f51ec29\scratchpad\r6\pitching\`: `r6p.py` (the gated patches), `run_kpi.py` and `ana.py` (collector and summary), `mc.py` and `exp1.py`-`exp6.py` with their `exp*.txt` outputs, `ov\s3.json` (the candidate), and `runs\` (base, s1a, s1b, s2, s2t, s3, s3t, s3g).