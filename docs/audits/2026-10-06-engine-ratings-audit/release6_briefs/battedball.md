# Release 6 design brief: batted ball, spray and parks

The joint model works as a shape: with the whole prototype patched in, all three fixtures hold the run level (4.44–4.69 runs per team-game) with BABIP about .290 on the two realistic fixtures (.301 on the flat-ratings one) and HR at 1.00–1.13 per team-game, without per-fixture knobs. It is not finished. Home runs are too marginal (mean distance 391 ft, carry leverage about 15x) and tag-ups, triples, park strength and K/BB still need a retune.

The prototype is in memory only; the repo is untouched. With the patch installed but switched off, seed-1 seasons reproduce the generation 5 baseline metrics exactly on all three fixtures. Numbers are labelled season, MC (Monte Carlo over the 126k balls in play logged from each generation 5 season) or arithmetic. "Flat" is the flat-ratings fixture (`r5/fx3/product`), and anything resting on it alone is marked.

**Reference caveat.** `data/MLB_avg/` has only league totals. The per-class references I fitted to are from memory and self-consistent (they reproduce mean EV 88.8, hard-hit .387 and BABIP about .295), but they need a Savant pull before any gate is set on them:

| Class | Share | Mean EV | Hard-hit | BA |
|---|---|---|---|---|
| GB (<10°) | 43.5% | 86.5 | .36 | .245 |
| LD (10–25°) | 25% | 93 | .50 | .64 |
| FB (25–50°) | 24.5% | 91.5 | .42 | .11 excluding HR |
| PU (>50°) | 7% | 79 | .03 | .015 |

## 0. Interfaces for the other three areas

- **Exit velocity** = potential × efficiency.
  - Potential is today's `ev_base` (`physics.py:1283-1287`: pitch speed, bat speed, noise) times the rating part of `quality` (`:1295-1298`). Power and Pitching keep owning it.
  - Efficiency is mine: the loss from one signed barrel offset plus a weak-contact mixture.
- **Launch angle** = centre + additive shifts + slope × barrel offset. The shifts are hitter `gf`, pitch height and timing; pitcher `gf` and a sinker offset belong here (Pitching).
- **Barrel offset sd** is `barrel_sd` (`:1262-1264`). It is the mishit-size lever for both sides: hitter barrel skill, and pitch difficulty via `barrel_error_scale`.
- **Spray** is generated batter-relative (positive = pull) and stored as a physical angle (positive = right-field side) for every consumer.

Sensitivities (MC, neutral defense, average park):

| Change | Effect |
|---|---|
| EV potential +1% (about +1 mph) | HR +15.6%, hard-hit +4.4 pp, BABIP +.006 |
| Offset sd −5.5% (= +10 barrel-skill points) | BABIP +.010, LD +1.3 pp, PU −0.9 pp, HR +4.6% |
| `gf` +10 at 0.40°/pt | GB +6.7 pp, HR −22% |
| `pl` +10 | HR +5% |
| Carry +1% | HR +13–15% |
| Fielder reach +1 ft, per 150 G | Infield +9.7 to +12.6 outs (SS 9.7, 2B 9.8, 3B 11.9, 1B 12.6); outfield +4.6 to +5.0 |

- **Fielding:** 5–7 outs per rating SD at an SD of 10 implies about 0.05–0.07 ft per point in the infield and 0.10–0.15 in the outfield. My placeholder slopes (0.15 / 0.35) are too steep.
- **Power:** `barrel_power_weight` is 1.0 today, so the offset skill is all Power. Under this kernel Power then also owns line-drive rate and BABIP.

## 1. Carry with drag (M2; build first)

**Current.** `estimate_carry_distance` (`physics.py:1442-1462`) is a vacuum range × 0.75 × `hr_scale` (0.925 legacy, 0.91 generation 5) × `offense_scale`, peaking at 45°.

**Problem (season, calibration s1, generation 5).**

| | Generation 5 | Prototype | MLB |
|---|---|---|---|
| Mean HR distance | 424 ft | 391 ft | about 400 |
| HR of 450+ ft | 25.5% | 0.2% | — |
| Longest HR | 629 ft | 460 ft | — |
| HR at launch angle ≥40° | 8.7% | 0.9% | — |

**Proposal.** `carry_model` 1: a point-mass trajectory with drag and lift, precomputed once into a carry / hang-time / descent-angle table (2 mph × 1°, bilinear lookup, no random draw).
- The raw table gives 100 mph at 28° = 404 ft.
- `bb6_carry_scale` 0.94 was fitted to HR per team-game.
- `hr_scale` is unused under the model.

**Evidence.** At 0.94 the HR-to-barrel ratio is about 0.61, matching MLB's roughly 0.6. But leverage is 15.4x per 1% carry (generation 5: about 6x). Widening the potential-EV spread 5% lifted distance to 397 ft and cut leverage to 10.9x, at a hard-hit cost I did not re-fit. The 400 ft target therefore depends on the Power agent's bat-speed spread and soft cap, not on carry.

**Coupled to carry.** The Release 4 tag-up race is fitted to engine carry and drag-free hang (`engine.py:2796`). With realistic distances `tagup_score_rate` went .73 → .99; `tag_up_release` 2.0 → 0.8 brought it to .78–.82 (target .75). It needs a proper refit and should read the table's hang time.

## 2. Exit-velocity / launch-angle kernel, classes, pop-ups (M2)

**Current.** Launch angle is N(12.1 − (gf−50)/10, 10.5) plus location and timing terms, × 0.97, clamped to −20..60 (`physics.py:1316-1331`). Exit velocity gets a small unsigned penalty for barrel and timing error, with a soft cap at 107 (`:1295-1315`). Class cutoffs are 9.0 / 15.7 (`config.py:725-726`).

**Problem.** Release 5 did not move it (season, calibration s1, generation 5): Statcast classes 45 / 42 / 13 / 0.1, sweet-spot .57, hard-hit .32, EV sd 11.7. Exit velocity is flat across classes (88.6–88.8), so there is no coupling of extreme angles to weak contact.

**Proposal** (`batted_ball_model` 1; `u` = barrel_error / `bb6_offset_ref` 0.314):
```
LA  = 13.2 − (gf − hitter_gf_center)·0.40 + vloc·4 + timing·7
      + (u<0 ? 26 : 22)·u + N(0, 0.5)             clamp −75..85
eff = 1 − (du<0 ? .0244 : .059)·du²,  du = u − 0.33
      with prob .147: eff ·= U(.40, .90)           floor .45
EV  = potential · 1.155 · eff                      soft cap 110.2 / .40
```
- Topped balls and pop-ups come from the same offset that costs exit velocity.
- Derivation: Nelder–Mead fit to the class table above over 380k logged contacts (`kern.py`). I then lowered the launch-angle slopes by hand, because foul pop-outs supply about 3 points of the pop-up share.
- Classes become Statcast's 10 / 25 / 50 with a `pu` type. Mechanics should key on a separate route (ground or air), not on the class.
- `hitter_gf_center` and `hitter_pull_center` are new league centres, because `gf` and `pl` are not league-relative today.

**Evidence** (season, prototype, calibration s1; the other two fixtures are within 1 pt):

| | Generation 5 | Prototype | Target |
|---|---|---|---|
| GB / LD / FB / PU | 45.2 / 41.9 / 12.8 / 0.1 | 44.2 / 24.5 / 23.9 / 7.4 | 43 / 25 / 24 / 7 |
| Mean EV / sd | 88.7 / 11.7 | 88.5 / 14.7 | 88.5 / ~15 |
| Hard-hit | .318 | .379 | .38 |
| Barrel | .050 | .066 | .075 |
| Sweet-spot | .569 | .372 | .33 |
| Hitter GB% true sd | .012 | .021 | .06–.07 |

- Sweet-spot trades against pop-up share: steeper slopes gave .344 with 9.9% pop-ups.
- GB% spread needs wider `gf` (Release 7) or a steeper slope.

## 3. Hit table, bimodal difficulty, infield liners (L19, L20)

**Current.** `out_probability` (`fielding.py:165-255`) is a class base of .78 / .38 / .73 plus a zone-rating term minus (EV−90)/300; launch angle is unused. The hit chance is (1 − out) × `babip_scale` plus the Contact edge, clamped to .02–.95 (`engine.py:7057-7061`). `select_out_type` (`fielding.py:290-298`) gives liners to an infielder on a 45% coin flip.

**Problem.** Per-ball variance is 94% of the binomial maximum (audit L19).

| Non-HR hit rate (season) | Generation 5 | Prototype | Reference |
|---|---|---|---|
| Ground balls | .219 | .252 | .245 |
| Line drives | .395 | .632 | ~.63 |
| Fly balls | .238 | .143 | ~.11 |
| Pop-ups | — | .036 | ~.015 |

**Proposal** (`fielding_play_model` 1): one function returns the out probability, the fielder, the out type and whether it was an infield play. Every consumer uses that fielder.
- **Ground route** (carry < 150 ft and launch angle < 15°): each infielder's lateral reach against the gap to the ball's path, then a throw-versus-runner race. Infield hits and batter speed come out of the race.
- **Air route:** an infield-liner check first (ball height at the infielder's depth between 0.3 and 9.5 ft), then a landing-point race on hang time for outfielders and infielders.
- **Ratings** add feet of reach.
- **Hit type** comes from landing distance against the wall and the gap to the nearest outfielder, plus down-the-line ground-ball doubles.
- **Clamp:** relax to about .002–.998.
- **Shift:** the pull-shift term is dropped.

**Evidence.**
- Bimodality (MC): 49% of non-HR balls have a hit chance below .05, 17% above .95, 15% in .25–.75. Variance is 28% of the binomial maximum.
- Ground-ball average by EV (MC, variant-b parameters): .17 / .22 / .22 / .34 / .46 for <70 / 70–85 / 85–95 / 95–105 / 105+ mph (audit reference at 105+: .45–.50).
- Outfield putout split CF/LF/RF (MC): 40 / 30 / 30, against 39 / 29 / 32 in the repo's putout file.
- Team DER sd on calibration (season): .016 → .014.
- Pitcher BABIP true sd on calibration (season): .0147 → .0096.

**Contact.** The prototype removed `contact_babip_per10` and set `barrel_power_weight` 0.5. `corr_avg_contact` then fell from .62–.63 to .50 / .59 on calibration and .42 / .56 on the league fixture, and `r_ch_babip` is about 0. Keep the .005 edge until the offset-skill split is settled with Power.

## 4. Spray (M4)

**Current.** Spray is N((pl−50)/2 + 12·timing, 18), hand-blind (`physics.py:1332-1336`). `engine._spray_dir` (`engine.py:3049-3053`) negates only for right-handed batters, so `_fielder_position_for_ball` (`:3075`) and `_hit_advance_position` (`:3095`) mirror left-handed batters' balls, while `fielding.out_probability` uses the physical side.

**Problem.** Still present after Release 5 (season, calibration s1, generation 5): r(pl, mean pull angle) is −.95 for right-handed batters and +.96 for left-handed; pull / centre / oppo is 21 / 58 / 21; 55% of balls go to the right side.

**Proposal.** `spray_model` 1:
```
mean  = 9 + (pl − hitter_pull_center)·0.5 + 12·timing − 0.35·(clamp(LA, −20, 45) − 12)
spray = truncated normal(mean, sd 40) on ±45, one draw
EV   ·= 1 + 0.035·ramp(LA 5..20)·spray/45
```
- Stored physical: `spray_phys = side == 'L' ? spray : −spray`.
- `_spray_dir` becomes `−angle` for both hands.
- Truncation stops fair balls piling up at the foul lines.

**Evidence** (season, calibration s1): both hands pull to their own side, with r(pl, pull) +.67 and +.70; thirds 35 / 39 / 26 (target 39 / 36 / 25); 65% of home runs pulled (today 22–33%); left / right balance 50 / 50. Fielder credit matches the out roll by construction.

## 5. Parks and foul territory (M5)

**Current.**
- Fence: linear LF–CF–RF (`field_geometry.py:46-57`).
- Altitude: `altitude_ft_scale` 2e-5, +10.4% at Coors.
- Foul territory: scales the foul-strike rate (`physics.py:1354-1362`), off in generation 5; a foul is always a strike (`engine.py:6974`).

**Proposal.**
- **Fence:** five points (LF, LC, CF, RC, RF) from `ParkConfig.csv`. The effective fence is distance plus wall height ÷ tan(descent angle).
- **Generic park:** the average of the 30 real parks, 330 / 386 / 403 / 386 / 330 with 10 ft walls. Today's generic alley is 365 ft, 21 ft short of real. With 375 ft alleys and 8 ft walls the generic-park fixtures hit about 25% more HR than calibration.
- **Altitude:** `bb6_altitude_ft_scale` about 0.9e-5 (+4.7%). The integrator gives +5 to +7%.
- **Park strength:** a `park_geometry_scale` that blends real geometry toward the generic park.
- **Foul-outs:** `foul_out_model` 1, with chance per foul = `foul_out_rate` 0.031 × park foul scale. One extra draw, only when on.

**Evidence.**
- Park HR factors (MC, neutral talent) are too wide:

| Park | Prototype | Generation 5 |
|---|---|---|
| Coors | 1.60 | 1.37 |
| Fenway | 1.40 | 1.28 |
| Great American | 1.43 | 1.04 |
| Kauffman | 1.24 | 1.00 |
| Comerica | 0.75 | 0.84 |
| PNC | 0.97 | 1.16 |

  Coors geometry at sea level is 0.69; a generic park at 5,200 ft with +5.7% carry is 2.04. This is the same leverage problem as item 1.
- Foul-outs alone (season, s1): 0.79–0.86 per team-game, 3% of batted balls.

| | Calibration | League fixture |
|---|---|---|
| Runs per team-game | −0.27 | −0.27 |
| K | −0.6 pp | −0.75 pp |
| BB | −0.2 pp | −0.4 pp |
| BABIP | −.007 | −.011 |

## 6. Whole prototype

Season results, mean of seeds 1–2; generation 5 baseline in brackets.

| | Calibration | League fixture | Flat |
|---|---|---|---|
| Runs / team-game | 4.46 (4.35) | 4.60 (4.45) | 4.68 (4.52) |
| K% | 21.3 (22.0) | 20.5 (21.3) | 21.0 (21.8) |
| BB% | 7.9 (8.2) | 8.0 (8.3) | 8.0 (8.3) |
| BABIP | .290 (.282) | .292 (.278) | .301 (.289) |
| HR / team-game | 1.13 (1.10) | 1.08 (1.09) | 1.00 (1.00) |
| HR / fly ball (incl. pop-ups) | .116 | .109 | .100 |
| Doubles / team-game | 1.63 (1.76) | 1.56 (1.85) | 1.55 (1.82) |
| Triples / team-game | .121 (.147) | .217 (.193) | .197 (.188) |
| Hard-hit | .377 (.319) | .386 (.327) | .355 (.302) |
| Barrel | .066 (.051) | .067 (.053) | .062 (.048) |
| `corr_hr_power` | .59 (.56) | .68 (.59) | .79 (.67) |
| Team DER sd | .014 (.016) | .012 (.016) | .009 (.008) |

- K and BB need a small retune (foul-outs).
- `pitcher_hitter_hr_true_sd_ratio` stays .85–1.2 on the realistic fixtures (Pitching's item).

**Flat-fixture HR gap (flat fixture only; no mechanism designed for it).** It is not bunched `gf` / `pl`: widening its `gf` sd to 2.9–10 moves HR −0.2% to +1.3% (MC), and `pl` cannot matter in a symmetric park. Its balls in play come off pitches 1.15 mph slower (31% vs 38% at 90+ mph; presumably its flat pitch grades shift the mix). Equalising that through `ev_pitch_weight` 0.48 closes 7 points of the 5–10% gap (MC). This is one more reason for Pitching's lower weight.

## 7. KPIs

- **Existing:** `hard_hit_pct`, `barrel_pct`, `sweet_spot_pct`, `avg_exit_velocity`, `babip`, `hr_per_fb_pct`, `doubles_per_team_game`, `triples_per_team_game`, `team_der_sd`, `r_sp_babip`, `r_ch_babip`, `tagup_score_rate`, `sf_per_pa`, `foul_share_of_contact`.
- **To add:**
  - Statcast class shares, with EV and BA by class
  - Mean HR distance and share of 450+ ft
  - Pull / centre / oppo, split by hand
  - r(pl, pull) by hand
  - Hitter and pitcher GB% and BABIP true sd
  - Foul-outs per team-game
  - Outs by fielder
  - Per-park HR factor
  - Share of balls with hit chance below .05 or above .95
- **Redefine:** `hr_per_fb_pct`'s denominator must be fly balls plus pop-ups, or the .11 target cannot coexist with a 24% fly-ball share (arithmetic).

## 8. Decisions for you

1. **Displayed batted-ball splits.** Statcast four-way (43 / 25 / 24 / 7) or FanGraphs three-way (44 / 21 / 35)? I recommend four-way, with HR/FB over fly balls plus pop-ups.
2. **How strongly real parks play.** Recommend half strength, altitude about +4.5%, and the generic park set to the real average.
3. **Foul-outs.** About 0.8 per team-game, with big-foul-territory parks helping pitchers. Recommend yes, with the park effect damped.
4. **Infield shift bonus.** Recommend dropping it (MLB banned the shift).
5. **Home-run distances.** The longest become about 460–470 ft; 600 ft shots disappear. Recommend accepting.
6. **Hitter ground-ball identity.** 0.40°/pt gives a 2 pp spread today. Recommend holding that until Release 7 widens `gf`.

## 9. Risks and "do not do"

- Do not widen launch angle before carry: 2.37 HR per team-game under drag-free carry (REPORT §7).
- Hard-hit is a shape fix, not a level shift.
- Do not flip `_spray_dir` alone.
- Do not use real-feet tag-up thresholds before carry is real.
- HR leverage of 13–15x makes every HR knob touchy; settle the EV top tail with Power before gating HR distance or park factors.
- Prototype shortcuts:
  - Legacy draws are still consumed.
  - Fielding uses zone ratings rather than per-fielder ratings.
  - Pitcher and catcher plays are credited to a neighbouring fielder.
  - A foul-out is faked as a caught pop-up (about 2% leak as hits).
  - The .02–.95 clamp is kept.

## Build order

1. Spray convention (physical angle, one helper), without widening. The audit calls this KPI-neutral in symmetric parks; I did not run it on its own.
2. Carry table, five-point fence and generic park, altitude; tag-up refit.
3. EV / launch-angle kernel, classes, pop-ups.
4. Fielding play model, liners, hit types; relax the clamp.
5. Foul-outs; K/BB retune.
6. Spray widening and pull-EV coupling; `gf` slope.

Steps 2–5 need one joint retune and are not independently shippable. Power, then Pitching, then Fielding sit on top.

## Not verified

- Every Statcast per-class reference, and the foul-out rate (no Retrosheet row in the repo).
- The 105+ mph share (prototype 5.7%; I believe MLB is higher).
- Altitude and park factors in full seasons (MC only).
- Hitter BABIP true sd (not resolvable in one season).
- Triples, tag-ups and sweet-spot are not on target.
- No pytest, no `--strict` gates read, no matchup grid (it calls `physics` directly, bypassing the patch).

Everything is in `...\scratchpad\r6\battedball\`:
- **Model:** `model6.py` (kernel, parks, fielding), `traj.py` (carry table), `kern.py` (fit)
- **Harness patch:** `patchlib.py`, `inst6.py`, `run_h.py`, `runv.sh`
- **Analysis:** `mc6.py`, `parks_mc.py`, `prod_gap.py`, `hand_an.py`, `summ.py`
- **Seasons:** `d\` (final variant), `dnf\` (no foul-outs), `base\` (generation 5 with contact logs)