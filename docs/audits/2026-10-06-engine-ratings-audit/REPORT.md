# Alpha-test audit: do players perform to their ratings, and are the stats realistic?

**What was checked.** The audit covered 11 areas:
- contact and batting average
- power
- plate discipline
- speed and baserunning
- batted-ball profile
- pitching stuff
- pitcher usage
- defense
- league-level realism
- the full rating-to-stat matrix
- live league vs current engine
- team talent

Five follow-up investigations went deeper on specific questions:
- in-game fatigue and the times-through-order penalty
- run expectancy by situation (RE24, run probability, late and close, extra innings)
- how hitter and pitcher ratings combine in a matchup (log5)
- whether results repeat across 15 replicate re-sims, and how well the re-sim represents the live league
- individual fielders' ratings against their outcomes

**Data sources:**
- **Current-engine re-sim:** 910 games on today's code (7.45.8). This is the primary dataset.
- **15 replicate re-sims** of the alpha-test copy (91 games each, real season path `api.routers.season._simulate_n` → `game_runner` → physics engine). They used three batching modes:
  - one persistent process (P1-P6);
  - a fresh process every sim day (C1a-f);
  - a fresh process every 7 days (C7a-c).

  Run through the same pipeline, the original re-sim (R0) reproduces its numbers exactly.
- **Live alpha-test season:** 710 games. It is contaminated by bugs that have since been fixed.
- **Post-power-fix window:** 70 live games, 07-21 to 07-31.
- **162-game harness seasons:** run on the wide-rated calibration fixture, on copies of alpha-test, and on fixtures with deliberately widened ratings. They include:
  - counterfactual fatigue seasons (fatigue channels switched off one at a time);
  - an instrumented engine copy that logs base-out state (game scores identical to the repo engine);
  - a fielding-attribution driver.
- **PA Monte Carlo grids** on the real per-pitch code: Contact × pitcher and Power × pitcher, 40k-100k PA per cell.

**How findings were checked.** Two independent verifiers re-checked every finding. Where they corrected a number or a severity, this report uses the corrected value:
- Three findings were originally rated critical. All three were downgraded to high after verification.
- No finding was thrown out entirely.
- Claims that turned out wrong or overstated are listed in section 7, so nobody chases them.

MLB reference values come from `data/MLB_avg` unless marked "approx." Values marked "approx." are general Statcast or FanGraphs knowledge, not repo data.

**Replicate noise (use as the noise floor when verifying fixes).** Across the 15 alpha replicates:

| Metric | Replicate spread |
|---|---|
| K% | ±0.0025 |
| BB% | ±0.0014 |
| HR/PA | ±0.0008 |
| ERA | ±0.12 |
| R/G | ±0.11 |
| SB per team-game | ±0.04 |
| 120+ pitch starts | ±0.7 pp |
| Save conversion | ±0.015 |

A single seed cannot show a 1 pp change in 120+ pitch starts.

---

## 1. Bottom line

- **The three most important rating links work, and they are stable across 15 replicates.** In the current engine:
  - Contact drives strikeouts: r = -0.805 ± 0.019.
  - Power drives home runs: r(PH, HR/PA) = +0.66 ± 0.05 (PA ≥150; +0.68 at PA ≥282; +0.80 in 162-game alpha sims). The 7.45.0 fix holds. Contact's effect on HR per ball in play is r = -0.007 ± 0.036.
  - Speed drives steals and triples (r = +0.76 and +0.62).
  - On the wide-rated calibration fixture, control and movement explain 57% of pitcher FIP.
  - Outfielders' range follows their own fa at the designed slope. Errors follow the charged fielder's fa.
- **A newly found bug can stop a live league (H9).** In 3 of 15 replicates a sim day aborted with "Player X is not on the active roster". One league could not advance on any retry, and half-played days lose games permanently. Ship this fix first.
- **Many other ratings are dead or weak.**
  - Walks are barely a skill. Pooled over 15 replicates, alpha hitter BB% has a true sd of only 0.16 pp, and a wide-eye fixture gives only 1.0-1.4 pp, against MLB's ~2.5 pp.
  - Pitcher GB/FB tendency (gf) is never read.
  - Pitcher arm is net wrong-signed: more velocity means more hard contact allowed.
  - Pitch-type grades carry only 20% weight.
  - The pull rating is backwards for right-handed batters.
  - Speed adds nothing to batting average or double-play avoidance.
  - The hitter `sc` rating is never loaded by the engine.
  - Outfield arm and runner speed have no effect on tag-ups from third: the roll is capped on 98.5% of chances.
- **In alpha-test, pitcher ratings explain only about 2-5% of ERA/FIP.** This is mostly the old normalize bug, not the engine. Movement is exactly 52 for every pitcher with 40+ IP, and control spans only 50-57. The current generator still floors control at 50 and movement at 52 (`player_generator.py:1018-1019`), so new leagues inherit part of the problem.
- **The league scores too many runs.**
  - Alpha-test runs 4.96 ± 0.11 R/G (15 replicates, about 4.4 sd above MLB's 4.47), and fails 21 KPI gates in 162-game harness runs.
  - The CI calibration fixture passes for two reasons: its hitters are rated about 3 CH / 2 PH lower, and it plays in real MLB parks.
  - On the generic park every alpha team uses, the fixture itself fails 5 gates. CI is certifying an environment owners never see.
- **Pitcher usage is the most visible breakage, and it is not a one-seed fluke.**
  - When every unused reliever is resting, the tired pitcher simply stays in.
  - This produces 150-215-pitch "complete games" and closers averaging 4.1-4.4 outs per appearance. It appears in every replicate that carries usage state across days, weekly batches included.
  - The MR1/MR2/MR3 slots that the product's own Pitching tab and Auto-fill write are not recognised by the engine, so those relievers average about 7 outs per outing.
  - The live league showed milder bullpens only because pre-7.45.6 games had minor-league arms available. Under today's code, owners will see the breakage.
  - Reliever rest also lives only in process memory (M18), so a one-day sim on a fresh process rests no one.
- **The in-game fatigue model is unrealistic (H10).**
  - Fastball velocity falls about 12-14 mph late in a start (MLB about 1-2 mph).
  - Because pitch speed feeds exit velocity, that fade *helps* the tired pitcher. It cancels most of the contact damage that fatigue should cause, so nearly the whole cost arrives as lost strikeouts.
  - The fade, the arm/velocity fix (H6) and the fatigue coefficients must be retuned together. Fixing any one alone roughly quadruples fatigue damage.
- **Matchups mostly follow log5, with two exceptions.** Walks and wOBA combine additively. The two exceptions:
  - Against elite-contact hitters the pitcher's strikeout effect is halved, with a K floor near 10% (M20).
  - Pitcher control+movement suppresses HRs too strongly, and non-multiplicatively (M21).

  Both are mostly hidden today by compressed ratings and will surface when ratings are re-spread.
- **Event volumes are off.**
  - Stolen bases run about 3x MLB (2.20 ± 0.04 SB per team-game), and the harness benchmark is itself 2x too high.
  - Runners take the extra base 67-75% of the time (MLB ~40%).
  - Sac flies run about 1.5-1.8x MLB; GIDP about two-thirds of MLB.
  - A runner on 3rd scores on only ~25% of ground outs and holds on ~75% of 0-out double plays.
  - Errors run about half of MLB. Recorded passed balls run about 7x MLB.
  - Home-field advantage is only about +1 pp (MLB ~+3-4).
- **Some game rules are wrong.**
  - A run can score on an inning-ending double play. It decided 3 walk-offs in 4,860 calibration games.
  - Extra innings use pre-2020 rules: no automatic runner, and an 18-inning tie cap that can also tie a playoff game.
  - Late and close at-bats are no harder than early ones, because relievers carry no edge and a "late & close" modifier adds walks.
- **Some stats owners see are wrong.**
  - Batting and fielding share stat keys, so every caught stealing is stored twice, and catchers show 41-49 "CS" as runners.
  - Line scores drop extra innings.
  - Per-fielder putouts, assists and errors on left-handed batters' balls go to the mirror-image fielder.
  - The live 2026 season totals carry the pre-fix engine: HR vs Contact r = +0.73 in the live data, and minor leaguers hold about 28% of live PA.
- **Several league totals look right only because errors cancel.**
  - BABIP, the GB/LD/FB mix and HR/FB match MLB, while the underlying model is wrong: launch-angle spread is half of MLB's, hit/out ignores launch angle within a ball class, and carry ignores drag.
  - Sac-fly excess hides the runner-on-3rd ground-out deficit.
  - Fatigue's velocity fade hides its contact damage.

  Fixes in these areas must be made together and retuned together, or the totals will break.

---

## 2. What is working

### Rating links that work, current engine unless noted

| Link | Measured | Spread / n |
|---|---|---|
| Contact → K% | r -0.79 (15 replicates: -0.805 ± 0.019, range -0.763 to -0.827); -6.9 pp K per +10 CH (t -18). Wide fixture r -0.90. SwStr r -0.91 to -0.94 | CH sd 5.2, n=187-199 |
| Contact → zone and chase contact | Z-contact r +0.84 to +0.93; O-contact r +0.85 to +0.98 | all runs |
| Power → HR | HR/PA r +0.66 ± 0.05 over 15 replicates (PA ≥150; partial given CH +0.667 ± 0.048); +0.68 ± 0.05 at PA ≥282. +0.0185 ± 0.0017 HR/PA per +10 PH. HR/FB vs PH r +0.66. Alpha 162-game sims +0.75 to +0.81; calibration +0.59/+0.60/+0.60 | PH sd 4.4-4.5, n=187-199 |
| Contact no longer leaks into HR | r(CH, HR/BIP) -0.007 ± 0.036; partial given PH +0.019 ± 0.055 (15 replicates). Pre-fix live: +0.029, t 10.6 | — |
| Speed → steals, success, triples, runs | SB/PA r +0.76 (partial +0.72); SB% +0.53; 3B/PA +0.62; (R-HR) per time on base +0.59 | sp sd 10.4, n=167 |
| Control / movement → run prevention (calibration, wide ratings) | FIP R² 0.57, ERA R² 0.39. Top composite decile ERA 3.02 vs bottom 5.32. Qualified ERA sd 0.76 (MLB 0.85); 4 qualified pitchers under 2.50 | control sd 5.3, movement sd 5.8 |
| Fielding → team defense (calibration) | r(team fa, DER) +0.75 / +0.82. Catcher CS% vs arm r +0.61 to +0.72. OF assists vs arm r +0.57 to +0.72 | fa sd 2.7 team-level |
| Individual OF range (calibration, 3 seeds, 349k BIP) | Fly-ball out-rate slope per 10 own fa: LF +0.044, CF +0.041, RF +0.042 vs +0.040 designed. LD +0.023 to +0.034 vs +0.031. r(fa, OAA rate) LF +0.75, CF +0.75, RF +0.88 | n=90 per position, fa sd 5.2-9.8 |
| Individual IF range (calibration) | Follows the code exactly: each infielder's fa is half of a pair average. Own and partner coefficients are equal (SS +0.017 / 3B +0.019 per 10; 2B +0.017 / 1B +0.018), against +0.0185 designed. r(own fa, OAA rate) +0.42 to +0.62 | n=90 per position |
| Fielder arm → throw-outs (calibration) | r(arm, kills per extra-base attempt) LF +0.77, CF +0.76, RF +0.60, 2B/SS +0.64. OF arm worth +4.3 to +4.8 runs per 10 per 150 G (MLB OF arm runs ~±5) | arm sd ~8 |
| Errors follow the charged fielder | r(fa, E per chance) -0.64 to -0.83 (calibration). Current engine: SS -0.70, 2B -0.56, LF -0.47, RF -0.44, despite alpha's tiny spreads | — |
| Double-play turns | +2.3 to +2.6 runs per 10 fa per 150 G for 2B/SS (calibration and alpha) | — |
| Endurance → starter length (calibration) | +0.56 to +0.74 outs and +2.5 to +3.1 pitches per start per +10 | endurance sd 7.9 |
| Batter gf → launch angle | correct sign: -0.1° per point. At sd 14: GB% true sd 4.5 pp, corr(GB%, HR/BIP) -0.50 | — |
| Offense ratings → team runs | ch+ph+eye+sp give R² 0.90 on seed-averaged team runs scored; out-of-sample r 0.71 | 20 teams |
| Matchups: walks and wOBA | Additive, as log5 predicts. BB Contact × pitcher-composite interaction t +0.06 (calibration) and +1.39 (widened); all 48 BB grid cells within ±0.6 pp of log5. A +1 sd pitcher costs -0.0466 / -0.0464 / -0.0463 wOBA against -1 sd / mean / +1 sd CH hitters | n=367k-380k PA |
| Matchups: pitchers vs weak and average contact | Pitcher quality fully matters: from P35 to P80, K rises +27 pp at CH 35 and CH 50. Power does not distort the pitcher's K effect: the P35→P80 logit shift is +1.31 at every PH level | 100k PA per cell |

### League totals that match MLB in the current engine

| Metric | Engine | MLB |
|---|---|---|
| BABIP | .294 | .291 |
| HR/FB | .109 | .11 |
| GB / FB / LD | .422 / .362 / .216 | .44 / .35 / .21 |
| O-swing / zone% | .32 / .507 | .32 / .49 |
| Saves per team-game | .266 | .25 |
| Qualified AVG sd / ERA sd | .029 / .90 | .028 / .85 |
| Runs per team-game sd | 3.09 | ~3.1 (approx.) |
| One-run games / extra-inning games | 27.0% / 8.5-10.9% | ~27-29% / ~8.5-9% (approx.) |
| Win% per 1 R/G of run differential | 0.099-0.109 | 0.089-0.100 |
| Pythagorean residual sd per 162 | 3.7-5.0 W | 3.1-4.8 W |
| 30+ HR hitters per 30 teams | 15-21 | ~16-25 (approx.; see the benchmark problem in M3) |
| HR leader pace | 57 per 162 | 58 (2024) |
| PA by lineup slot | -0.11 per slot | ~-0.11 |

### Situational run scoring that works (instrumented engine copy; 3 calibration seeds and 3 alpha seeds, 1,620-2,430 games each)

- **RE24 matches MLB on the calibration fixture.** The fixture's 4.28 R/G is close to the 2010-15 environment (~4.24). Most cells fall within ±5% of the FanGraphs 2010-15 table:

  | Base state (0 / 1 / 2 out) | Engine | MLB |
  |---|---|---|
  | Bases empty | 0.476-0.491 / 0.261-0.268 / 0.100-0.109 | 0.481 / 0.254 / 0.098 |
  | Runner on 1st | 0.796-0.844 / 0.483-0.495 / 0.205-0.224 | 0.859 / 0.509 / 0.224 |
  | Runner on 2nd | 1.048-1.091 / 0.633-0.684 / 0.312-0.321 | 1.100 / 0.664 / 0.319 |
  | Loaded, 1 out | 1.538-1.579 | 1.541 |

  Alpha's RE24 is about 1.06-1.24x MLB throughout, consistent with its 1.18x run environment, and its shape matches.
- **Run probability (cal_s1).** P(score), engine vs MLB, at 0 / 1 / 2 out:

  | Base state | Engine | MLB |
  |---|---|---|
  | Bases empty | .277 / .165 / .070 | ~.268 / .155 / .067 |
  | Runner on 1st | .428 / .270 / .119 | .416 / .265 / .127 |
  | Runner on 2nd | .615 / .420 / .221 | .614 / .397 / .218 |
- **Runs per half-inning (innings 1-8).** The live-path box scores (910 games) give P0 .690 / P1 .168 / P2 .080 / P3+ .061, matching the harness.

  | | P0 | P1 | P2 | P3+ | Runs per inning |
  |---|---|---|---|---|---|
  | Calibration | .717-.724 | .157-.162 | .071-.073 | .046-.051 | 0.47-0.49 |
  | Alpha | .687 | .169-.172 | .079-.081 | .062-.063 | 0.56 |
  | MLB (approx.) | ~.73 | ~.15 | ~.065 | ~.055 | ~0.48-0.50 |
- **RISP is composition-neutral.** Observed minus composition-expected wOBA is within ±.005 (se .003). Per-hitter RISP splits do not repeat across seeds (r -0.15 to +0.18) and do not track any rating (|r| ≤ 0.13). They are pure noise, as in MLB.
- **Extra-inning frequency and tactic values.**
  - Extra innings: 8.5-10.9% of games (MLB ~8.5-9%).
  - Stolen-base break-even from the engine's own RE24: .68-.70 (MLB .715).
  - A sacrifice bunt with a runner on 1st and 0 out costs -0.14 to -0.24 runs (MLB -0.195).
  - The automatic extra-inning runner is implemented correctly when switched on (see L17).
- **First-inning hitting premium** (+.02 to +.04 OPS) is fully explained by top-of-order composition.

### Fatigue mechanics that work (counterfactual seasons, calibration and alpha, seeds 1+2)

- **Fatigue is cleanly gated.** Starters through pitch 75 have mean penalty 0.00-0.02 and flat velocity. PAs at penalty 0 are identical across all counterfactual modes.
- **The net sign is right at league level.** Fatigue raises league wOBA by +4.9 points (calibration) and +3.1 (alpha). Deep fatigue (penalty ≥1.4) is punished in the right direction.
- **K% falls steadily with pitch count within each pitcher**, as in MLB, though by too much (see H10).
- **Starter workload is right on the fixture:** 87 pitches per start, and 0.13% of starter PAs begin past 105 pitches.

### Process facts that hold

- **Rotation:** 94.4% of starts come on exactly 5 game-days of rest, and SP1-SP5 start 313-330 times each. The 7.41/7.42 starter fix holds.
- **Decisions:** W = L = 910, and starters get 60% of wins. Save conversion SV/(SV+BS) is 0.598 ± 0.015 over 15 replicates (R0 0.613), against MLB ~0.64 (approx.), so the real gap is about 0.04.
- **Pinch-run fix (7.44.6):** 62 live hitters had 15+ G and 0 GS; in the current engine there are none.
- **Active-roster fix (7.45.6):** players not on the active roster held 36% of live PA and hold 1% of current PA.
- **Same-player HR rate is stable:** for the 140 hitters in all three datasets, HR/PA is .0298 live, .0314 in the window and .0296 current. The league-wide HR drop came from roster composition, not engine change.
- **Ratings do not change during a sim.** Across R0 and four replicates, 0 of 1,080 players changed any rating or potential column; only injury fields changed. Correlations against end-of-run ratings are unbiased. The engine applies no rating penalty to day-to-day injured players.
- **League rate stats are stable to about ±1-2% across replicates:**

  | Metric | Value |
  |---|---|
  | K% | 0.2057 ± 0.0025 |
  | BB% | 0.0926 ± 0.0014 |
  | HR/PA | 0.0264 ± 0.0008 |
  | ERA | 4.78 ± 0.12 |

---

## 3. Problems, prioritised

Severity is the verified severity. Where the two verifiers disagreed, both are shown. Nothing remains critical after verification.

### Summary

| ID | Problem | Severity |
|---|---|---|
| H1 | Bullpen usage: tired pitcher stays in, MR1/MR2/MR3 and RP roles unrecognised, closer rest bypass, no inning-start hook | High |
| H2 | Stolen bases about 3x MLB; harness benchmark 2x too high; flat attempt curve; steals on foul balls | High |
| H3 | Alpha runs ~5.0 R/G and fails 21 gates; the CI fixture does not resemble real leagues | High (medium/high) |
| H4 | Walks are barely a skill: eye barely moves BB%; control acts as "stuff", not command | High |
| H5 | Batting and fielding stats overwrite each other (cs/po/ci/pk) | High (medium/high) |
| H6 | Pitcher ratings barely separate pitchers: arm net wrong-signed, pitch grades weak, K% under-spread | High (medium/high) |
| H7 | LHP give up ~0.7-0.9 more runs per 9 at equal ratings (platoon advantage counted twice) | High |
| H8 | Displayed OVR barely tracks production | High (high/medium) |
| **H9** | **New: sim days abort with "Player X is not on the active roster"; one league stalled permanently; half-played days lose games** | **High** |
| **H10** | **New: in-game fatigue: velocity fade ~10x MLB, which cancels fatigue's contact damage, so the cost lands only on K; must be retuned with H6** | **High** |
| M1 | Contact too easy, K% low, swings ignore the count, K floor ~10-11% | Medium |
| M2 | Batted-ball model: narrow launch angle, no pop-ups or foul outs, hit/out ignores launch angle, drag-free carry | Medium |
| M3 | Power curve flat below PH 52; platoon split jumps at the knee; doubles too high; wrong HR-count benchmarks | Medium |
| M4 | Spray convention: spray is hand-blind, so pull is inverted for RHB and LHB balls are credited to the mirror fielder | Medium |
| M5 | Park foul territory changes K% from 16% to 38%; fences mis-rank real parks | Medium |
| M6 | Batter speed adds no infield hits and no double-play avoidance | Medium |
| M7 | Extra-base aggression 67-75%; tag-ups never hold and ignore arm and speed; sac flies 1.5-1.8x; runner on 3rd rarely scores on ground outs | Medium |
| M8 | GIDP about two-thirds of MLB | Medium |
| M9 | Errors half of MLB; catchers and pitchers never err; fielding chances credited to the wrong positions | Medium |
| M10 | Wild pitches and passed balls rolled with the bases empty and on fouls | Medium |
| M11 | Pitcher gf never read: no groundball pitchers, sinkers not groundball pitches | Medium |
| M12 | Out-of-position penalty (flat x0.75) and autofill cascades dominate alpha defense | Medium |
| M13 | Live 2026 season totals carry the pre-fix engine and minor-league games | Medium |
| M14 | CPU auto-assign and trade "overall" for pitchers is a count of pitches thrown | Medium |
| M15 | Pitcher injuries ~9x below MLB; durability has no effect | Medium |
| M16 | Single-catcher teams; regulars never rest; batter fatigue never builds | Medium |
| M17 | Team true-talent spread about half of MLB's | Medium |
| **M18** | **New: reliever and batter rest state lives only in process memory** | **Medium** |
| **M19** | **New: late innings and late & close at-bats are not harder; the late-close modifier adds walks** | **Medium** |
| **M20** | **New: elite-contact hitters get about half the pitcher K effect; looking-K floor; cap relaxation does not fix it** | **Medium** |
| **M21** | **New: pitcher HR suppression is too strong and non-multiplicative (non-log5)** | **Medium** |
| **M22** | **New: per-fielder range value is 1.5-4x MLB per rating SD, with no positional-difficulty weight** | **Medium** |
| L1-L21 | Weak home-field edge, short starts, HBP, umpire zone, intentional walks, AVG spread, pitch mix, catcher defense, steal mechanics, SVO, line scores, leadoff choice, park-name collision, flat TTO pass 2, run on inning-ending DP, first-base-open modifier, extra-inning rules, missing situational KPIs, no routine balls, infield liners, GB-single arm | Low |

---

### H1. Bullpen usage is broken (High)

**What owners see:**
- 21 of 1,820 starts (1.15%) are "complete games" averaging 153 pitches. 15 of the 21 allowed 5+ runs, and the worst was 203 pitches with 13 runs allowed.
- 1.5% of starts reach 120+ pitches (MLB about 0.2%).
- 8.1% of relief outings reach 60+ pitches and 4.6% reach 80+.
- Relief outings average 4.67 outs and 26.8 pitches, against MLB's ~3.2 outs and ~17 pitches.
- Relievers per team-game are 2.61 (MLB 3.3).
- Closers average 4.36 outs per appearance (live: 3.06). The top closer is on pace for 134 IP.

**This is stable across seeds and batching.** Mean ± sd over replicates:

| Metric | Persistent process (n=6) | Fresh process daily (n=6) | Fresh process weekly (n=3) |
|---|---|---|---|
| 120+ pitch starts | 1.72 ± 0.68% (0.93-2.97%) | 0.01 ± 0.02% | 1.52 ± 0.34% |
| Max start pitches | 183-221 | 113-129 | 178-193 |
| Relief outings 60+ pitches | 9.60 ± 0.69% | 3.80 ± 0.19% | 8.07 ± 0.28% |
| Relief outs per appearance | 4.81 ± 0.08 | 3.86 ± 0.03 | 4.61 ± 0.10 |
| Relievers per team-game | 2.58 | 3.26 | 2.68 |
| CL-role outings of 7+ outs | 12.3 ± 2.6% | 0.9 ± 0.3% | 9.0 ± 2.7% |
| MR1-3/RP outs per appearance | 7.71 | 6.47 | 7.33 |

The original re-sim's figures sit inside the persistent spread. Its 60+ relief share (8.1%) is below every persistent replicate (8.78-10.73%), so it understates relief overwork rather than overstating it. The MR-label bug persists even with daily resets.

**Broken links:** relief role, rest and pitcher stamina do not govern outing length.

**Root causes (all confirmed in code):**
1. **The tired pitcher stays in.** `physics_sim/engine.py:778-784` `_select_reliever` returns the current pitcher when no available, unused reliever exists.
   - On the alpha fixture this happens on about 48% of selection calls, usually while 4-5 unused relievers are only rest-flagged.
   - Every 120+ pitch start traces to it.
   - Relievers at penalty ≥1.4 are mostly stuck: 83-92% of those PAs come from the team's last arm of the game, after only 3-4 of 11-13 pitchers were used.
2. **MR1/MR2/MR3 and RP roles are not recognised.**
   - `engine.py:271` gives reliever fatigue limits only to CL/SU/MR, and `engine.py:628-639` caps outs only for CL/SU/MR/LR. `game_runner.py:1103-1118` passes MR1/MR2/MR3/RP through raw.
   - MR1/MR2/MR3 come from the product's own Auto-fill and Pitching tab (`utils/pitching_autofill.py:139`, `LineupPage.tsx:86`) and are required by `services/roster_validation.py`. "RP" is the role every active pitcher outside the 11 staff slots gets.
   - These pitchers get starter limits (about 80/96 pitches) and starter fatigue windows, and no outs cap: 7.06-7.42 outs and about 41 pitches per outing, with about 50% of outings at 7+ outs. Plain MR averages 4.12 outs and 7.2% at 7+.
   - 7 of 20 teams use these labels (AUS, BAL, CHI, COL, HOU, MIL, SAN1).
3. **The closer ignores rest.** `engine.py:3814-3820` brings in an unavailable closer: 37.3% of closer relief appearances, including 86 on a third straight game-day. This contradicts spec S2-04. Removing it alone makes closer outings longer (1.41 to 1.62 IP per game on alpha), so it must ship with fixes 1 and 2.
4. **No hook at the start of an inning.** `engine.py:5490-5491` skips the hook after the third out. A reliever who hits his cap at an inning's end faces the next leadoff batter. This accounts for about 8 pp of setup-man outings over their cap.
5. **Spot starters can carry the MR role.** Tracker-chosen starters with an MR role get the 4-out MR cap (`engine.py:965-983`, `utils/lineup_loader.py:192-224`).
   - Pinsonnault (AUS) and Ortiz (BAL) average 3.9 and 3.8 outs per start, even in starts allowing 0-1 runs.
   - This happens because the tracker and the lineup loader build rotations separately.

**Contributing:**
- Rest is counted in game-date indices, so league off days never rest anyone (`game_runner.py:55-87`).
- Staffs carry 11-12 pitchers (MLB 13).
- Engine rest state is in-memory only; see M18.

**How much a stuck pitcher is punished.** It is modest and will not self-correct the outings. PAs at penalty ≥1.4 give up more wOBA than the same game states with fatigue off:

| | Extra wOBA allowed |
|---|---|
| Relievers, alpha | +26 ± 15 |
| Relievers, calibration | +50 ± 18 |
| Starters, both leagues | about +42 (CIs ±35/±53; the calibration interval includes 0) |

- 60-100% of that comes through lost strikeouts.
- 16 of 1,820 live-path starts reached 150+ pitches.
- Treat H1 as a usage and realism problem, and re-measure the punishment after the H10/H6 retune, which will change it several-fold.

**Why the live league looked milder.** This is a correction to the earlier draft, which blamed cloud resets. It was not the cloud resetting usage state:
- Live relievers pitched on consecutive game dates at 17%, the same as the persistent replicates (15-19%) and far from the 63-65% that daily resets produce.
- What differed was the pitcher pool. Pre-7.45.6 games let AAA, Low-A and DL arms pitch: 18.0 distinct pitchers per team-month, against 12.5 now. 48% of live relief appearances came from pitchers now off the active roster.
- Restoring the old pool on today's engine reproduces the live signature: 0 of 1,820 starts at 120+, max 116, relief 60+ at 6.4-6.9%, about 3.3 relievers per game. The current pool gives 2.6% at 120+ and a max of 215.
- **Under 7.45.6+ owners will see the 120+ starts and 60+ relief outings.** Re-measure from live box scores once 7.45.6+ games accumulate.

**Verified fix effect:** falling back to the least-fatigued unused reliever, alpha seeds 2 and 3.

| Metric | Before | After |
|---|---|---|
| 120+ pitch starts | 1.70% / 1.17% | 0.00% / 0.03% |
| Relief outings 60+ pitches | 6.4% | 2.4% |
| Closer outings 7+ outs | 17.5% | 0.1% |
| ERA | 4.85 | 4.87 |

**Fix and risks:**
1. Normalise `MR\d+` and RP to MR at the engine boundary.
2. Add the empty-bullpen fallback.
3. Remove the closer bypass.
4. Add an inning-start check of the outs cap and pitch cap.
5. Treat `pitchers[0]` as SP for limits.

Risks:
- An ungated fallback pushes relievers per game to 3.6-3.9, and with all three fixes the top closer appeared in 74 of 91 team-games. Fire the fallback only after the current pitcher passes his cap (or about 110-125 pitches), and exclude or penalise the closer in the empty-bullpen case.
- About 250-300 cases per season still remain once every arm is used, so a mop-up rule is also needed.
- Verify on at least 3 seeds with both persistent and 7-day-batch drivers.
- Expect R/G to fall about 0.1-0.15. Persistent runs score about 0.15 R/G more than daily-reset runs, entirely through relievers (RA9 4.93 vs 4.56), so re-centre offense afterwards.

### H2. Stolen-base volume is about 3x MLB, and the benchmark hides it (High)

**What owners see:**
- 2.20 ± 0.04 SB per team-game across 15 replicates (range 2.12-2.26; live: 2.38), against MLB 2024's 0.745. Batching does not change it (persistent 2.20, daily 2.22, weekly 2.18).
- True attempt rate is .066-.077 per PA against .0252.
- True SB% is .73-.84 against .790.
- 46 qualified hitters are on a 40+ SB pace (MLB about 3-4 per 20 teams). The leader's pace is 91 (MLB leaders: 67-73).
- Even average-speed runners (SP 45-55) steal at about 2.4x MLB's league-average rate and supply about 60% of all steals.

**Broken link:** speed governs who steals, but the overall volume is about 3x too high and the speed curve is too flat.

**Root causes:**
- **Attempt rate.** In `engine.py:1946-1966` the attempt rate is `steal_attempt_rate_first` .045 (`config.py:275`) × `steal_freq_scale` 3.0 (`config.py:428`) × a linear (0.5 + (sp-50)/60). An SP-50 runner attempts on 6.75% of pitches, and SP 85 only 2.17x that.
- **Fouls.** Steals are rolled on foul balls (`engine.py:5285`); 26-27% of steal events happen on a foul.
- **Success curve.** Success is 0.80 + (sp-50)/150 (`config.py:279`, `engine.py:2000-2019`), capped at 0.95 from SP 72.5. Attempts never consider expected success.
- **Double steals.** They ignore speed, hold and catcher, and both runners can be thrown out.
- **Benchmark.** The harness benchmark `sba_per_pa` = 0.050 (`mlb_league_benchmarks_2025_filled.csv:39`, tolerance ±0.01) is about 2x real MLB (0.016-0.025 for 2021-24). Real MLB 2024 would fail it, while the fixture passes at .050. `sb_per_team_game` is computed but not gated.
- **Speed distribution.** Alpha speed is snapped to tiers by the archetype floors at `player_generator.py:780-783`:
  - 63 of 72 "speed" hitters sit at exactly 70.
  - 16 of 19 "elite_speed" hitters sit at exactly 85.
  - In total, 15.5% of hitters are at SP 70 or higher.

  The calibration fixture (and the generator's donor pool) tops out at 67, so CI never exercises fast runners.

**Verified evidence:**
- On calibration, an exponential curve 0.5·exp((sp-50)/12) with freq 1.2 gave SBA/PA .024-.025, SB per team-game .70-.73, SB% .76-.77 and runs 4.28 → 4.36. Every other strict gate stayed green.
- The same settings leave alpha at .050 SBA/PA and 1.71 SB per team-game.
- Mapping alpha's speed onto the fixture's distribution alone brings triples .240 → .154, SBA/PA .068 → .059 and R/G 5.02 → 4.66.
- The engine's own RE24 gives a steal break-even of .68-.70 (MLB .715), so the run value per steal is right; only the volume is wrong.

**Fix and risks:**
1. Set the benchmark to about 0.025 and gate `sb_per_team_game` at about 0.72.
2. Stop steals and WP/PB rolls on fouls.
3. Use a steeper, bounded attempt curve and lower the scale.
4. Use a saturating success curve.
5. Add speed to the double-steal rate, and allow at most one out on a double steal.
6. Decide the canonical speed distribution first (see section 6). One knob set cannot fit both the fixture and alpha.

Risks:
- The tanh success variant dropped calibration SB% to .664 (gate fail), so the intercept needs re-centring.
- When the full running-game package (steals plus extra-base and DP changes) was applied, runs fell to 3.97-3.99, which fails the runs gate. It needs an offense retune.
- **Measure SB% from harness totals or catcher SBA minus SB, never from `season_stats` (see H5).**
- Use ~0.04 SB per team-game as the replicate noise sd.

### H3. Alpha runs hot and the CI fixture is blind to it (High; verifiers medium/high)

**What owners see:**
- Current engine: 4.96 ± 0.11 R/G over 15 replicates (R0 4.94), about 4.4 sd above MLB. Also .251/.329/.413 (OPS .742); 1.89 doubles and .245 triples per team-game; BB% 9.3%.
- MLB: 4.47 R/G, OPS .705, 1.63 doubles, .14 triples, BB% 8.0%.
- Alpha harness seeds 1 and 2: 5.02 and 5.04 R/G, with the same 21 gate failures.
- Calibration: 4.28 R/G with 0 failures.

**Root causes (verified by counterfactual runs):**
- **Hitters out-rate pitchers.** Every rating enters the engine as an absolute (rating - 50) term, with no centring to the league. Alpha's lineup regulars average CH 53.4 / PH 52.2, against the fixture's lineup 50.3 / 50.2.
  - Shifting alpha hitters by exactly that gap gives 4.44 R/G and OPS .698.
  - Shifting fixture hitters up by the same amount gives 4.88.
  - That is about 0.2 R/G per joint rating point.
- **Alpha's pitchers are not the cause.** Giving alpha pitchers fixture-like ratings raises runs to 5.23, because arm is wrong-signed (H6).
- **The fixture passes partly because of its parks.** It plays in the 30 real MLB parks (mean altitude 513 ft, foul scale 0.93). On the generic 330/400/330 park used by 18 of 20 alpha teams, it falls to 4.09 R/G and fails 5 gates (R/G, HR, ISO, BB%, P/PA).
- **About 10 gates fail even after level matching:** BB%, P/PA, steal volume and success, DP%, platoon gap, TTO gap, relievers per game, and HR/ISO (now too low). These are engine problems covered elsewhere.
- **Smaller contributors identified since the draft:**
  - The first-base-open and late-close pitch-objective modifiers add about 0.5-0.6 pp of walks (L16, M19).
  - Bullpen overwork adds up to ~0.15 R/G (H1).

**Fix and risks:**
1. Add a second KPI fixture built by the current generator, with real roster selection, generic parks and MR1-3 labels.
2. Make a design call between two options:
   - (a) The generator centres active rosters on 50, which is the S2-08 design intent.
   - (b) League-relative ratings: rating' = 50 + (rating - league ACT mean).

The verifier warns that under the current absolute-rating engine one knob set cannot pass both fixtures (about 0.13 R/G per CH point against a ±0.25 tolerance). Do not retune league-wide knobs on alpha alone.

### H4. Walks are barely a skill (High)

**What owners see:**
- Hitter walk rates barely follow eye, and pitcher walk rates barely follow control.
- In a single alpha replicate, hitter BB% true-talent spread is 0 within noise: observed sd .0163 against binomial noise .0161, and r(BB%, eye) about .015 in R0.
- Across 15 replicates the per-replicate estimate is clipped to 0 in 8 runs, and one replicate cannot resolve any true sd below ~0.007.
- Pooled over 15 replicates (~4,850 PA per player):

  | | True BB sd | Rating link |
  |---|---|---|
  | Hitters | 0.0016 | r(eye, BB%) +0.37; +1.1 pp per 10 eye, which fully explains the spread given eye sd 1.46 |
  | Pitchers | 0.0045 | control explains only ~0.0013 of it (pooled r -0.20) |
- League BB% is 9.27% (0.0926 ± 0.0014 over replicates) against MLB 2023's unintentional 8.33%.

Alpha's near-zero spread is therefore mostly compressed ratings. The evidence that the engine's eye slope is too shallow comes from the wide fixtures below.

**Mechanism, measured on wide fixtures so compression is excluded:**
- **Eye.** +10 eye adds only +0.75 pp BB (t 15). The worst-to-best eye bins run 7.0% → 10.2% (MLB about 4-17%), and true-talent sd is 1.0-1.4 pp against MLB ~2.5. Eye also cuts K about 1.7 pp per +10, so it acts as a contact rating.
- **Control.** +10 control: BB -0.64 to -0.79 pp, but K +2.5 pp, SwStr +1.1 pp and EV -2.2 mph. Pitcher BB true sd is about 1.0 pp (MLB ~2). Zone% true spread is about 0.4-0.5 pp (MLB ~2-3).

**Root causes:**
- `physics.py:701-702`: zone swing rises +1/200 per eye point while chase falls only 1/230.
  - The shallow chase slope is the main cause: steepening it to /130 alone gives a 2.29 pp true sd.
  - The rising zone-swing slope causes corr(O-swing, Z-swing) = -0.90 (MLB is positive) and flat pitches per PA.
  - Fixing both slopes (experiment A) gives a 2.78 pp sd, bins 5.6% → 12.9%, and P/PA rising with eye.
- `engine.py:3168` dilutes eye to 0.8·eye + 0.2·(100 - control). It uses *raw* control, so fatigue never raises walks either (H10).
- Control mainly works through its 0.4 weight in pitch quality (`physics.py:767`).
  - The zone-target term is tiny: 0.0009 per point (`config.py:85`), of which only about 22% reaches realized zone.
  - Command error (`physics.py:446-457`) is the main walk channel.
- The default generator rebuilds eye as 0.6·ch + 0.4·sc, with sc flat at 50 (`player_generator.py:296`, `:826`). Eye sd is about 2.9-3.1, with r(eye, ch) about 0.6.
- League BB excess has three main sources:
  - too many two-strike fouls (.336 per two-strike pitch against MLB .243), which stretch PAs;
  - the count-blind swing table (M1);
  - the pitch-objective modifiers, about +0.5-0.6 pp combined. The first-base-open modifier fires with the bases empty (L16), and the late-close modifier adds nibbling (M19).
- **Not a cause:** pitcher fatigue is worth only about +0.05-0.07 pp (see section 7).

**Fix and risks:**
1. Steepen chase and flatten or invert zone swing. The probe gives about +2.1 pp BB per +10 eye. Add a floor: the /110 chase term goes negative at effective eye ~81.
2. Generate eye independently (N(50, ~8), corr ~0.3 with ch).
3. Move control from "stuff" into zone targeting and command (e.g. zone_target_control_scale ~0.005, which steepens BB to about -1.3 pp per 10).
4. Add BB-dispersion KPIs for hitters (~.025-.03) and pitchers (~.02). Measure them on the wide fixture or pooled replicates, using the unclipped variance difference. A per-replicate floor on alpha is not a valid gate: per-replicate scatter is ~0.005.
5. Gate the first-base-open modifier on RISP (L16) and neutralise the late-close nibbling (M19). Re-tune the BB% gate afterwards.
6. Re-spread alpha eye by migration; otherwise no engine fix shows up live.

Risks:
- K% and pitches/PA move with these changes.
- Cutting control's pitch-quality weight weakens its K effect.
- Retune walk_scale and chase_scale last.

### H5. Batting and fielding stats overwrite each other (High; verifiers split medium/high)

**What owners see:**
- Every caught stealing is stored twice. League hitter CS is exactly 2x the true count: 1,540 vs 770 in the current engine, 1,053 vs 527 live.
- Displayed league SB% is .718; the true figure is .836.
- Regular catchers show 41-49 "CS" as runners, e.g. Carter 21 SB / 49 CS, Ramos 12 SB / 48 CS.
- A 1B shows 786 "picked off" (Gaines), because putouts land in that key.
- Hitter "ci" mixes reached-on-interference with interference committed.
- Every pitcher pickoff is counted twice (all pitcher pk values are even).
- Catchers' cs_pct is slightly contaminated too.

**Root cause:** `playbalance/game_runner.py:741-790` (batting), `:817-875` (pitching) and `:904-933` (fielding) all add into one `season_stats` dict. The keys `cs`, `po`, `ci` and `pk` collide. `playbalance/stats.py:50` (sb_pct) and `:187` (cs_pct) derive from the merged values, and `services/player_profile_view_model.py:44` displays batting cs.

The engine and KPI harness keep the counters separate, so calibration is unaffected.

**Fix and risks:**
1. Namespace fielding (and pitcher fielding pk) keys, and update every consumer.
2. Add a test: total hitter cs = catcher sba - sb.

Existing data cannot be fully repaired from box scores, which carry no SB/CS/PO/CI columns. Options are to approximate (subtract each catcher's fielding cs) or to accept and document the error.

### H6. Pitcher ratings barely separate pitchers (High; verifiers medium/high)

**What owners see:**
- In alpha, ratings explain about 2% of ERA, and ERA repeats across seeds at r 0.18 (calibration 0.37).
- No qualified pitcher posts a sub-3.00 ERA in a 162-game re-sim (0 on seed 2, 1 on seed 3).
- The best-stuff starter (mean pitch grade 70, best pitch 88) posted 5.20 ERA and 19% K.
- League ERA is about 4.8-4.9 (4.78 ± 0.12 over replicates) against MLB ~4.15. That high run environment is a large part of why sub-3.00 seasons are rare: luck alone would give 3-5 at a normal run level.

**Engine problems, measured on wide fixtures:**
- **Arm is net wrong-signed.**
  - Per +10 arm on calibration: ERA +0.17 to +0.21, FIP +0.11 to +0.16, EV allowed +0.55 to +0.75 mph, HR about +9%, K about 0.
  - Controlled run with all pitchers at arm 40 vs 60: +0.11 to +0.12 R/G per +10 arm.
  - Cause: velocity = 83 + 0.2·arm (`engine.py:4329`) feeds exit velocity at weight 0.48 (`physics.py:847-850`). That sign is physically right (faster pitch, harder collision), but the size is about 2x the collision coefficient.
  - The velocity whiff and difficulty terms that should outweigh it are one-sided, max(0, (v-90)/20) (`physics.py:773`, `808`). They switch off below 90 mph and are inert for most hitters because of the contact cap (below).
  - The same wiring makes in-game velocity loss *help* tired pitchers (H10). **The H6 fix and the fatigue retune must ship together.**
- **Pitch-type grades are weak.**
  - Pitch quality = 0.4·control + 0.4·movement + 0.2·pitch grade (`physics.py:767`).
  - +10 on one pitch: whiff per swing +1.2 to +1.5 pp, chase 0, GB 0, EV -1.2 mph.
  - +10 across the whole arsenal is about -0.30 FIP, roughly 40% of control's effect. Weak, not dead.
  - In alpha, the league's best repertoire is worth only +2.4 pp K over an average one; +10 control and +10 movement on average stuff is worth +5.7 pp.
  - Swing and chase decisions never read the pitch (`physics.py:701-724`), and launch angle never reads the pitcher (`physics.py:880-894`).
- **Whiff terms only act as a ceiling.**
  - P(contact) = min(contact_prob, 1 - whiff) (`physics.py:797-803`). The cap binds on 0% of swings at CH 50, 27% at CH 55 and 67% at CH 60.
  - 68% of current-engine PA come from hitters below CH 54, so for most PA velocity and break do not affect whiffs.
  - Per-type whiff per swing is nearly flat (calibration: fb .206 vs cb .223; MLB gap ~10-13 pp, approx.).
  - See M20 for the matchup consequences and why relaxing the cap alone does not help.
- **Control+movement over-suppress HRs (M21).** Pitch quality enters exit velocity three times, so at the population's extremes the pitcher composite matters more for HR than it does in MLB.
- **K% is under-dispersed even with wide ratings.** Qualified pitcher K% sd is .028-.031 against MLB about .040-.045 (approx.).
  - The harness `qualified_k_pct_sd` (benchmark .055) measures *hitter* K%. No pitcher K% dispersion gate exists.

**Data problem:** in alpha, every pitcher with 40+ IP has movement exactly 52. Other pitcher spreads: control sd 1.53, arm sd 2.0, endurance sd 0.9-1.4. Pitcher vl is blank for 494 of 494.

**Fix and risks:**
1. Take velocity out of the exit-velocity formula, or lower `ev_pitch_weight` toward ~0.2 / centre it on the pitch type's mean. Put velocity relative to type into the contact path as a two-sided term.
   - The EV-only fix as first proposed is too small: -.0025 OPS per +10 arm.
   - Raising the whiff_velocity_scale alone leaves FIP wrong-signed.
   - Applying the EV fix without retuning the fatigue coefficients raises fatigue damage about 4x (H10).
2. Raise the own-pitch weight in pitch quality (e.g. 0.15 control / 0.30 movement / 0.55 pitch), and add a pitch-quality chase term.
3. Replace the contact cap with a log-odds-additive contact model (M20). A cap relaxation (product or soft cap) changes pitcher value by less than 0.11 logit.
4. Retune k_scale and offense, because alpha's mean repertoire (~60) sits above control and movement (~50-52).
5. Re-spread alpha pitcher ratings by migration only *after* both the arm sign and the stacked pitch-quality EV paths (M21) are fixed. Otherwise wider arm makes the wrong-sign effect larger, and wider control and movement produce near-zero HR rates for non-sluggers.

Risk: the fixes raise league offense at arm 50 (HR/PA +10% in one variant). Recalibrate on seeds 1 and 2.

### H7. Left-handed pitchers are ~0.7-0.9 runs worse at equal ratings (High)

**What owners see:**
- At matched control, arm and endurance, LHP allow RA9 5.60 against RHP 4.72.
  - Weighted regression: +0.87 ± 0.19.
  - LHP are worse on 17 of 19 teams.
  - 4-seed direct-engine runs: +0.68 ± 0.07.
- LHP strike out .177 vs .214 and allow HR/BF .0293 vs .0259.
- The RHB platoon split is about 48 wOBA points (MLB approx. 15-20). The league platoon gap is .043, against a harness band of .020-.032.
- The calibration fixture shows no LHP gap, so CI cannot see this.

**Root causes:**
1. The generator adds +4 vl to every RHB and -4 to every LHB (`player_generator.py:826-830`). That stacks on the engine's flat handedness bonus of 1.8 / 2.0 / 1.2 contact / power / eye (`engine.py:3154-3174`, `config.py:491-494`). The bonus is the same for RHB and LHB, where MLB's RHB split is about half the LHB split.
2. Alpha's hitter pool is RHB-heavy (about 66-69% of PA vs LHP).
3. Blank pitcher vl contributes nothing, and backfilling it does not help.

**Verified effects (3-seed alpha runs):**

| Change | LHP gap (R/9) | Other |
|---|---|---|
| None (baseline) | +0.68 | — |
| Recentre hitter vl by bats | +0.57 | — |
| Flat bonus set to 0 | +0.38 | — |
| Recentre + asymmetric bonus (RHB 0.6, LHB 1.0) | +0.41 | RHB split 26, LHB 33, league gap .029 (in band); calibration stays in band |

Team LHP share explains roughly 6-27% of true team run-prevention variance, depending on method. The single-sample r of +0.77 overstates it; 4 seeds give +0.48.

**Fix and risks:**
1. Single source of platoon advantage: drop the generator's ±4 nudge and recentre existing leagues' hitter vl by bats.
2. Make the bonus asymmetric.
3. Give switch hitters a full bonus.
4. Add KPIs: LHP-minus-RHP RA9 within ±0.15, plus per-hand platoon gaps.

Even after these changes about 0.4 R/9 remains, so the hitter handedness mix or a pitcher-side offset is also needed.

### H8. Displayed OVR barely tracks production (High; verifiers high/medium)

**What owners see:**

Hitters:
- r(displayed OVR, OPS+) = 0.31, against 0.65 for a simple (CH+PH)/2.
- Partial r given (CH+PH)/2 is about 0: OVR adds no information.
- OPS+ by OVR quintile is non-monotonic: 90 / 94 / 107 / 101 / 105.

Pitchers in alpha:
- Raw OVR 52-56 is displayed as 44-77 (53 → 46, 54 → 57, 55 → 72, 56 → 77), while FIP-/ERA- stay at about 100 across all of them. Pitchers shown 30 points apart perform the same.

Wide fixtures (OVR vs the best simple proxy):

| | OVR | Proxy |
|---|---|---|
| Hitters, r with OPS+ | 0.34-0.40 | 0.83-0.84 for (CH+PH)/2 |
| Pitchers, r with FIP- | -0.44 | -0.81 for (CO+MO)/2 |

**Root causes:**
- `api/routers/_rating_presentation.py:22-30` hitter keys omit eye (its weight in `config/rating_weights.json` is silently unused) and include:
  - sc, which the engine never loads;
  - pl, which has no measurable effect;
  - vl, which is season-neutral by design;
  - gf, which lowers offense.
- 65% of hitter OVR is the top-4 percentile ratings (`:260-271`).
- Pitcher OVR (`:276-310`) equal-weights arm (wrong-signed), fa and hold_runner (no effect) and endurance. It then percentile-stretches a rounded integer (`utils/rating_display.py:376-396`).

In alpha the pitcher result is mostly compression: even the best proxy reaches only r = -0.12.

**Fix and risks:**
- **Hitters:** weight what the engine rewards, about 0.45·ch + 0.45·ph + 0.07·eye + 0.03·sp, plus a real position-weighted fa/arm defense term. An offense-only formula would sink glove-first players.
  - Do **not** copy today's measured fielding run values into the defense weights. Today, 10 fa is worth 26-29 runs in CF/RF but 17 at SS (M22).
  - Set the defense weights from total runs (range + error + DP) after the M22 and M4 fixes.
- **Pitchers:** about 0.47·control + 0.38·movement + 0.15·mean pitch grade. Use endurance only as a role adjustment.
- Drop the top-N leg. Percentile-scale the continuous score, or show raw when the league sd is below about 3.
- Update `utils/rating_display._overall_from_row` in the same change.

This is display-only except for the depth-chart autofill sort. No engine or KPI impact.

### H9. Sim days abort with "Player X is not on the active roster"; a league can stall permanently (High, new)

**What owners would see:** the sim stops mid-day with an error. Games played before the error keep their results but have no box score, and the rest of that date is never played. In the worst case the league cannot be advanced at all.

**Evidence:** 3 of 15 local 91-day replicates hit a hard error.

| Run | Team | Date | Player in the lineup |
|---|---|---|---|
| P2 | ALB | 2026-11-30 | P7222, a SAN AAA player |
| P3 | PHI | 2026-11-22 | P2838, a FOR AAA player |
| C1b | SEA | 2026-12-24 | D20260053, a COL Low-A draftee |

- **C1b is stuck.** It fails on every retry, including a retry with a different seed.
- **P2 and P3 failed mid-day.**
  - 6 of 10 games kept results with no box score link.
  - The other 4 were skipped forever, because the resume check treats a date as played if any game on it has a result.
  - The 8 teams in those games finished at 161 of 162 (90 of 91 in the window).
- **Every failing team's active roster had filled up with pitchers.** SEA went from 12 position players / 13 pitchers to 8 / 17. All 5 SEA and all 5 ALB call-ups were pitchers.
- Logs: `runs/P2.log`, `runs/P3.log`, `runs/C1b.log`, `runs/C1b.resume.log`.
- Analysis: `stall_check.py`, `sea_moves.py` in `work/followup-replicate-stability-and-resim-representativeness/`.

**Root causes (a chain):**
1. **Injury replacement ignores position.** `models/roster.py:39-43` `promote_replacements` pops `aaa[0]` whenever `injury_manager.py:258-267` finds no depth-chart replacement, and only COL/HOU/MIL have depth charts. The head of the AAA list is a pitcher on 13 of 20 live teams.
   - Those pitchers are never sent back down.
   - A returning hitter who finds the active roster full goes to AAA ("Activated Tommy Hanlon to AAA (SEA)").
   - So the active roster drifts toward pitchers.
2. **The emergency lineup fill picks from the wrong pool.** With fewer than 9 active position players, `utils/lineup_autofill.py:172-183` fills from every player in `players.csv`, shuffled with the seed `'<team>-lineup-fallback'`. It therefore picks other teams' minor leaguers, and the same ones on every retry.
3. **The lineup check then rejects them.** `playbalance/game_runner.py:183-186` `apply_lineup` rejects any player not on the roster (strict since 7.45.6). `_build_state` (`game_runner.py:1403-1425`) sanitizes once with the same autofill and re-raises.
4. **The day stops.** `api/routers/season.py:887-890` records the error and breaks out of the day.
5. **Resume skips the rest of the day.** `season.py:536-546` counts a date as played if *any* row has a result, despite the "fully played" comment.

Before 7.45.6 the engine silently used those minor leaguers. The strict roster check turned that into a hard stop. Nothing prevents this in the live league.

**Fix:**
- (a) Make injury replacement position-aware: hitter for hitter, preferring the injured player's position, then any AAA position player, never a pitcher. Keep at least 13 position players on the active roster.
- (b) Restrict the emergency fill to the team's own AAA/Low-A position players, as an auto-promotion recorded as a transaction. Never draw from another team.
- (c) Require every game on a date to have a result before the date counts as played, or commit a day's games atomically.
- (d) Add a regression test: injure 4 hitters on a team whose AAA list starts with pitchers, then sim a day.
- Check the live league's active rosters for pitcher-heavy drift now, and repair any team with fewer than 10 active position players.

### H10. In-game fatigue: velocity fade ~10x MLB, which cancels fatigue's contact damage, so the cost lands only on strikeouts (High, new)

**What owners see:**
- Late in a start, fastball velocity collapses: 93.9 → 89.1 mph at pitches 76-90 and → 79.6-81.5 mph past 90 pitches.
  - Within the same outing a starter loses 11.8 mph (calibration) or 13.7 mph (alpha) by pitches 91-105.
  - 32-56% of starts get there.
- Relievers fall from about 93.4 mph to 84.4 at pitches 26-50 and to about 80.5 past 50.
- Fatigue lowers the league-average fastball by 1.4 mph (calibration) and 1.8 mph (alpha).
- A tired pitcher allows nearly the same exit velocity and HR rate as a fresh one: +0.2 to +1.1 mph and +0.0 to +0.4 pp HR at penalty 0-1.0. He pays an MLB-sized wOBA cost (+17 to +28), but almost entirely through lost strikeouts.

**Velocity by pitches thrown before the PA, starters (base mode):**

| Pitches before PA | 0-25 | 26-50 | 51-75 | 76-90 | 91-105 | 106-120 | 121+ |
|---|---|---|---|---|---|---|---|
| Calibration s1, mph | 93.87 | 93.87 | 93.85 | 89.12 | 81.48 | 79.62 | 80.09 |
| Calibration s1, n PA | 34,724 | 29,621 | 27,195 | 14,135 | 2,733 | 142 | 92 |
| Alpha, mph | 92.84 | 92.81 | 92.74 | 86.79 | 79.12 | 79.14 | 79.12 |

How many PAs are thrown while fatigued:

| Share of all PAs | Penalty >0 | Penalty ≥1.0 | Penalty ≥1.4 |
|---|---|---|---|
| Calibration | 14.8% | 3.3% | 2.4% |
| Alpha | 20.0% | 5.8% | 4.7% |

**The fade cancels the contact damage.** Calibration starters, PAs at penalty 0.5-1.0 (n ≈ 8.4k per mode):

| Mode | wOBA | EV | Hard% | HR/PA | FB mph |
|---|---|---|---|---|---|
| base | .332 | 88.50 | .300 | .0306 | 82.3 |
| no fatigue | .316 | 87.68 | .291 | .0278 | 93.9 |
| no velocity loss | .388 | 93.31 | .471 | .0543 | 93.9 |
| velocity loss only | .269 | 82.81 | .143 | .0138 | 82.2 |

- Control and movement loss alone add +6-8 mph EV and +86 to +115 wOBA.
- Velocity loss alone *subtracts* 5 mph and 35-52 wOBA.
- Net effect: the fade cancels about 77-93% of the EV damage, 54-89% of the HR damage and 65-87% of the wOBA damage.
- League totals, calibration:

  | Mode | wOBA |
  |---|---|
  | base | .3168 |
  | no fatigue | .3119 |
  | no velocity loss | .3230 |
  | velocity loss only | .3077 |

**The cost arrives through strikeouts only.** Within-pitcher, starters at pitches 91-105 vs 0-25, controlling for batter CH/PH/eye:

| | Calibration s1 | Calibration s2 | Alpha |
|---|---|---|---|
| K | -5.7 pp | -6.2 pp | -7.1 pp |
| BB | +1.1 pp | -0.3 pp | +1.8 pp |
| EV | +1.7 mph | +1.3 mph | +1.7 mph |
| wOBA | +44 | +30 | +58 |

Velocity has no effect on K: in the velocity-loss-only mode, K% is unchanged at every fatigue level.

**Root causes:**
- `engine.py:482-486` `_fatigue_factors` hard-codes three factors:

  | Factor | Formula | Floor reached at penalty |
  |---|---|---|
  | velocity | max(0.85, 1 - 0.15·penalty) | 1.0 |
  | control | 1 - 0.30·penalty | 1.33 |
  | movement | 1 - 0.25·penalty | 1.4 |

- **The penalty ramps fast.** The ramp (`engine.py:471-479`) is (pitches - start)/(limit - start) × `fatigue_decay_scale` 1.4 (`config.py:365`), over a span of only ~14-19 pitches. The full ~14 mph drop arrives 11-15 pitches after fatigue onset for starters and 9-13 for CL/SU/MR.
- **Velocity loss feeds exit velocity in the pitcher's favour.** The velocity factor multiplies the base fastball speed (`physics.py:441-443`), which feeds exit velocity at weight 0.48 (`physics.py:847-850`). The whiff and difficulty velocity terms are inactive below 90 mph (`physics.py:773`, `808`).
- **Control and movement loss feed pitch quality** (`physics.py:767`), which enters EV three times (M21) and drives whiff, so K falls.
- **Walks barely move.** The zone-target control scale is tiny (0.0009/pt, `physics.py:621-627`), and batter eye uses *raw* control (`engine.py:3168`).
- **Side defect:** MR1/MR2/MR3 are not matched by `_pitcher_usage_limits` (`engine.py:270`), so those relievers get starter fatigue windows (H1).

**The retune must be coupled.** PA kernel, average batter, 40k PA per row. Extra wOBA allowed relative to a fresh pitcher:

| Scheme | Average pitcher, penalty 0.5 / 1.0 / 1.5 | Good pitcher, penalty 1.0 | HR/PA at penalty 1.0 |
|---|---|---|---|
| Current | +17 / +20 / +42 | +45 | .026-.028 |
| Fade cut to 0.015 only | +43 / +82 / +106 | +88 | .052 |
| H6 EV fix only, fade unchanged | — / +81 / — | +87 | ~.05 |
| Fade 0.015, control 0.12, movement 0.10 | +16 / +31 / +46 | +31 | — |
| Fade 0.015, control 0.08, movement 0.06 | +9 / +18 / +27 | — | — |

- Fixing either side alone removes the offset and roughly quadruples fatigue damage.
- Under the H6 fix the fade becomes nearly neutral (-3 to -6 wOBA), so the jump comes from losing the offset.
- **Size the coefficients at the penalty actually reached at 91-105 pitches, which is about 1.26-1.5, not 0.5-1.0.** At that penalty:
  - 0.12/0.10 costs about +37 to +53 wOBA, two to three times the MLB target.
  - 0.08/0.06 costs about +25 to +33.
  - To hit the target, use roughly 0.05/0.04, or flatten the ramp.

**What works:** fatigue is gated cleanly, the league-level sign is right, deep fatigue is punished, and K% falls through the order in the MLB direction.

**Fix (ship in the same release as H6):**
1. Move the three coefficients and floors into `DEFAULT_TUNING` knobs (e.g. `fatigue_velocity_loss`).
2. Set the velocity coefficient to about 0.015 (floor ~0.97). That is about 1.4-1.9 mph at penalty 1, and at most ~2.1 mph at the cap.
3. Apply the H6 EV/whiff change, and include a two-sided velocity whiff term so that a real 1-2 mph fade costs a little K.
4. Re-size control and movement to about 0.05/0.04, or flatten the ramp.
5. Feed fatigued control into the zone-target term (and optionally the batter-eye blend), so some cost shows up as command. MLB late-game decline is mostly K and contact, with a modest BB rise.
6. Targets:
   - starter FB fade of 1-2 mph by pitches 91-105;
   - +10 to +20 wOBA within-pitcher at 91-105 pitches;
   - TTO3-TTO1 gap of +20 to +30 wOBA (see L14).
7. Verify with the strict KPI run on calibration seeds 1 and 2, and re-measure H1's stuck-pitcher punishment afterwards.

Scripts: `work/followup-fatigue-performance-sign/` (`season_pa.py`, `cf.py`, `kernel.py`, `kernel_fix.py`; outputs `calib_cf.txt`, `alpha_cf.txt`, `kernel_out.txt`, `kernel_fix_out.txt`).

---

### M1. Contact is too easy, strikeouts too few, and swings ignore the count (Medium)

**Numbers vs MLB:**

| Metric | Engine | MLB |
|---|---|---|
| K% | 20.3-20.6% | 22.2-22.8% |
| Contact per swing | .820 | .763 |
| SwStr | 8.8% | 11.0% |
| Swinging K, % of PA | 14.5% | ~17.5% |
| Looking-K share | .287 | .23 |
| Hitter K% true sd | .037-.041 (15 replicates: .041 ± .0035) | ~.052 |
| Lowest reachable K% | ~10-11.5% (CH ≥ ~70) | elite hitters 3-8% (approx.) |

The entire K shortfall is swinging strikeouts.

**Count-blind swings:**

| Count | Engine swing rate | MLB 2023 |
|---|---|---|
| 0-0, 0-1, 1-0, 1-1, 2-0, 2-1 | ~.41 at all six | .310 (0-0) to .576 (2-1) |
| 3-0 | .235-.245 | .097 |
| 3-1 | .36 | .536 |
| 0-2 chase | .48 | .341 |

16% of PAs end on the first pitch (MLB 11.2%).

**Power has no strikeout cost.** With Contact held fixed, K% does not move with PH (about -0.003 per 10, |t| ≤ 1.4). r(K%, ISO) is -0.19, where MLB is positive (approx. +0.2 to +0.4).

**Root causes:**
- The contact ceiling `min(contact_prob, 1-whiff)` (`physics.py:797-798`) with `k_scale` 0.51 (`config.py:322`). In-zone contact hits the ceiling at about CH 55-58, which is why Contact plateaus near 70.
- **A looking-strikeout floor of about 5.5-8.5% of PA** that does not depend on Contact or Eye (M20). Even a perfect contact model cannot take total K below it.
- `count_swing_bonus` covers only two-strike counts (`config.py:111-116`). The 3-ball scales are `take_on_3_0` 0.5 and `take_on_3_1` 0.8; the latter also applies at 3-2.
- Two-strike chase is inflated by walk_scale and the 0.19 protect swing (`physics.py:706-735`).
- Alpha's Contact mean is about 3.4 points above the fixture's.

The high-contact composition was a deliberate S2-08 compromise, and the harness contact gates are loose.

**Fix and risks (verifiers corrected the proposed fixes):**
- **k_scale and count_contact.** Changing `k_scale` to 0.55 together with setting `count_contact_scale` to 1.0 overshoots, to K 27.5% (alpha) and 29.3% (fixture).
- **whiff_base.** Raising it does nothing below the contact cap.
- **K floor and cap.** Do not just relax the cap: see M20.
  - A product or logistic soft cap changes almost nothing.
  - Setting k_scale to 1 while keeping the 0.95 ceiling at `physics.py:786-790` makes things worse.
  - What is needed: replace the clamp with a log-odds-additive contact model (Contact and pitch quality both in log-odds, two-sided whiff terms), and make looking K depend on Contact or Eye.
- **Count table.** Filling the count table (the `ovr_counts.json` values work) and setting `take_on_3_0` to ~0.25 fixes the per-count shape. It moves K by -1 to -2 pp and P/PA by about +0.07, so it needs a foul-rate trim. 3-2 needs its own compensation.
- **Two-strike chase.** Use either the negative two-strike bonuses or protect 0.08, not both.
- **Power whiff cost.** If added, it must apply to `contact_prob` after the cap. Applying it to `contact_base` also lowers exit velocity, costing PH-80 hitters 13-20% of HR.
- This is a joint retune with H4 and M20, gated on both fixtures and on the log5 matchup grid.

### M2. The batted-ball model is wrong underneath matching totals (Medium)

**Numbers vs MLB:**

| Metric | Engine | MLB |
|---|---|---|
| Launch angle sd | ~12° | ~26° (approx.) |
| GB / LD / FB / PU (Statcast definitions) | 45 / 42 / 13 / 0.05 | ~43 / 25 / 24 / 7 (approx.) |
| Infield flies, % of FB | 0.4% | ~10% |
| Sweet-spot rate | 57% | 33% |
| Hard-hit rate | 29% | 38% |
| Barrel rate | ~4.4% | ~7.5% |
| Exit-velocity sd | 11.8 mph | ~15 (approx.) |
| Pop-outs | 0 | routine |
| Foul outs | 0 (`engine.py:4662`: a foul is always a strike) | routine |

The BIS-style 42/22/36 mix matches MLB only because the class cutoffs are tuned to 9.0° and 15.7° (`config.py:520-521`) instead of 10/25.

**Hit/out ignores launch angle within a ball class.** `fielding.py:191-211` uses class bases of .78 / .38 / .73 and -(EV-90)/300. The launch-angle argument is never read, and neither is batter speed.

| Batted-ball result | Engine | MLB |
|---|---|---|
| Non-HR hit rate, LA 9-15.7° | .57 | — |
| Non-HR hit rate, just above 15.7° | .25, then flat to 60° | — |
| Statcast line-drive band BA | .40 | ~.63-.68 (approx.) |
| Ground-ball hits | .186-.204 | ~.24 |
| Grounders hit 105+ mph | .24-.27 | ~.45-.50 |
| Non-HR flies that fall | .23 | ~.10-.13 |

Hitter BABIP true-talent sd is about 0-.014, against about .015-.020.

**No routine balls (L19).** Per-ball hit probability is never near 0 or 1:

| Ball type | Hit probability, p5-p95 |
|---|---|
| Grounders | 0.11-0.25 |
| Fly balls | 0.17-0.32 |
| Liners | 0.50-0.64 |

No ball exceeds 0.90. Every chance is a coin flip, which adds fielding luck and hitter/pitcher BABIP noise.

**Carry is a drag-free projectile** (`physics.py:1000-1020`), peaking at 45°:
- Mean HR distance 424-427 ft (MLB ~400).
- 7-9% of HRs travel 500+ ft; the longest reach 600-646 ft.
- 8-9% of HRs leave at launch angles of 40° or more.

This is hidden today only because the launch-angle distribution is narrow. Widening launch_angle_sd to 20 alone gives 2.37 HR per team-game.

**No batted-ball identity for hitters.** GB/FB/LD% true-talent spread is 0 (n=195), against MLB GB% sd ~6-7 pp. Batter gf moves launch angle only -0.1° per point, and alpha's gf sd is 1.6 (generator source 2.9).

**Fix and risks:** these are one joint change, not separate fixes.
1. Fix carry/drag first.
2. Replace the launch-angle draw with a mixture that couples extreme angles (pop-ups above 50°, topped balls below -10°) to low exit velocity. Simply raising the sd mostly adds fly balls and HR.
3. Add a pop-up class and a foul-out roll (already specified in S3-03, not implemented).
4. Restore standard cutoffs.
5. Use an xBA-style hit table f(LA, EV, spray, range) plus a speed infield-hit term (M6). Make fielder rating shift a bimodal difficulty threshold (as OAA does), rather than adding a flat probability to every ball (L19, M22).
6. Retune `babip_scale`, `hr_scale` and EV shape: hard-hit needs a heavier weak-contact tail, not a level shift.
7. Add hard-hit, barrel, sweet-spot and IFFB KPIs; the targets are already in the benchmark CSV.

Steepening the EV slope alone raises hitter BABIP spread but also pushes pitcher BABIP spread to about 2x MLB, so it is not sufficient on its own.

### M3. Power curve, platoon knee, doubles and HR benchmarks (Medium)

**Flat below the knee.**
- Below PH 52, +10 PH adds only about +1.7 HR/600 and +1.4 mph mean EV, against +10 to +19 HR/600 per +10 above the knee.
- Below-average hitters therefore sit at 13-15 HR/600, where MLB's bottom decile hits 4-9.
- The bottom quintile hits 0.87-0.90x the median (MLB ~0.4-0.5x).
- Code: `physics.py:43-61`, with `bat_speed_power_scale` 0.15, knee 52, knee_scale 0.8 (`config.py:329/349/350`).
- In alpha, 77% of regulars are PH 48-52, and they still show a gradient (12.2 → 14.2 HR/600). Their sameness is mostly compression (PH sd 1.5).
- Override A (scale 0.40, knee_scale 0.55):
  - Makes HR monotone in PH and raises `corr_hr_power` from .591 to .694 at the same league HR level.
  - Does **not** lower the floor (bottom-quintile ratio ~0.84), so the proposed 0.65x gate would still fail.
  - Still needs `--strict` on seeds 1 and 2.

**Platoon split jumps at the knee.**
- The ±2 handedness power bonus is added to the rating before the knee (`engine.py:3173`).
- The opposite/same-hand HR ratio is about 1.13-1.18 below PH 50, peaks at 1.45-1.50 around PH 54-56, then eases to about 1.3.
- MLB is about 1.1-1.3 and roughly flat (approx.).
- Fix: apply handedness (and vl power) as a constant bat-speed offset after the knee (about ±0.8 mph). Verifiers disagree on how flat this makes the ratio. Retune `platoon_gap_woba` afterwards.

**Doubles.**
- Alpha 1.89 per team-game against MLB 1.60-1.69 (about 15% high); calibration 1.74-1.76.
- `gap_norm` = ((CH+PH)/2 - 50)/50 lowers the double threshold (`physics.py:1059`, `double_gap_scale` 0.45). Power counts twice: through exit velocity and through `gap_norm`.
- Per point, Power still drives doubles and ISO about 2x more than Contact.
- Fix:
  - Use CH only at 0.225, or drop the term.
  - Set the doubles level with `double_distance_scale` (~0.715 hits 1.63 on calibration).
  - Do not use PH-only at 0.45, which overshoots.
  - A PH → launch-angle term would raise HR sharply under drag-free carry, so it must wait for M2.

**HR-count benchmarks are wrong.**
- `mlb_league_benchmarks_2025_filled.csv` sets `qualified_hr30_count` 5.5 and `qualified_hr40_count` 2.5. Real MLB has about 20-25 and about 4-7 (approx.).
- The S3 spec read the engine's realistic 15-21 as an overshoot.
- The hr40 gate (2.5 ± 5.0) can never fail on the low side.
- `hard_hit_pct` and `barrel_pct` are in the CSV but never computed.
- The fixture's 40+ HR tail is actually a little thin (2 per season against ~5).

### M4. Spray is hand-blind: pull inverted for right-handed batters, LHB balls credited to the mirror fielder (Medium)

**The root cause is hand-blind spray.** Raw spray = N((pl-50)/2 + timing·12, 18) (`physics.py:896-899`) has no batter-side term.
- Under the `out_probability` and park convention, positive spray points to the RF/1B side, so **both** hands pull toward RF.
- RHB pull hitters physically hit to the opposite field. The shift term then rewards the defense against LHB pull hitters but penalises it against RHB ones.

**Pull is inverted for RHB.**
- Each pl point moves a RHB 0.5° toward the opposite field: corr -0.96 to -0.99 for RHB, +0.97 for LHB.
- League pull/straight/oppo is about 21/58/21 against MLB's 39/36/25. HRs split about 26/47/27, where MLB HRs are strongly pulled (approx.).
- pl has no HR effect for anyone.
- RF also gets more chances than LF (777 vs 556 per 150 G on calibration), which inflates RF fielding value (M22).

**LHB fielder credit is mirrored.**
- `engine.py:1745-1749` `_spray_dir` negates the angle only for 'R', while `out_probability` (`fielding.py:170-189`) uses the physical side. `_fielder_position_for_ball` (`engine.py:1771`) therefore credits every LHB grounder and every non-CF LHB air ball to the mirror-image fielder. That includes switch hitters batting left.
- On those balls the credited fielder's fa has no effect on the out:

  | Ball / position | Credited fielder's slope per 10 fa | Physical fielder's slope |
  |---|---|---|
  | FB, LF | +0.004 | +0.042 |
  | FB, RF | +0.001 | +0.041 |
  | GB, SS | +0.002 | +0.020 |

  RHB balls agree exactly.
- Everything credited to a fielder uses the mirrored fielder on LHB balls:
  - putout and assist credit (`engine.py:5016`);
  - error rolls and charges (`4853-4889`);
  - the hit-advancement arm (`4750-4777`): 13-23% of extra-base rolls on hits use the wrong outfielder's arm;
  - the tag-up arm (`5180-5205`): 34% of tag-ups from third;
  - GIDP participants (`2322`).
- As a result, a player's displayed range (credited outs per 150 G) correlates with his fa at only r 0.00-0.44 by position, against 0.10-0.79 for physically attributed outs (RF +0.44 vs +0.79; SS +0.00 vs +0.10).
- About 24% of balls in play are misattributed in alpha and about 39% on the fixture. Team outcomes barely move; per-player fielding lines are wrong.

**Fix and risks:**
1. Define spray as batter-relative at generation, and mirror pl and the timing term by side.
2. Convert it once to a physical angle, and use that one physical helper in `out_probability`, `_fielder_position_for_ball`, `spray_to_field_angle` and the shift term.
3. Add tests: for each batter hand, a pulled ball lands on the correct physical side and is credited to the fielder whose rating set its out probability.
4. Then widen spray (sd ~25°, mean pull ~5°) and couple the pull side to exit velocity, so pulled fly balls carry the HR share.

Flipping only `_spray_dir` (always -angle) fixes the credit mismatch but leaves the hand-blind spray bug in place. Mirroring alone is KPI-neutral in symmetric parks. Widening raises HR per BIP about 11% and needs an `hr_scale` retune.

### M5. Park foul territory and geometry (Medium)

**Foul territory.**
- The foul column multiplies the foul-strike rate (`utils/park_utils.py:258-269` → `physics.py:918-926`), and fouls are never outs.
- At identical talent: K% 16.2% at Fenway (scale 0.75), 37.8% at Oakland (1.35), 22.8% in a neutral park. AVG ranges .271 to .179.
- Across the 30 parks, r(foul scale, K%) = 0.97.
- Real foul territory changes K by only a few percent (approx.).

**Geometry.**
- The fence is linear between LF, CF and RF only (`playbalance/field_geometry.py:46-57`). ParkConfig.csv has alley distances and wall heights that are ignored.
- Altitude adds +10.4% carry at Coors (`physics.py:1015-1019`).
- Resulting HR factors mis-rank real parks: Coors 1.36, Fenway 1.26-1.28, PNC 1.14-1.15, Comerica 0.83-0.85.

**Impact today:**
- Alpha is mostly unaffected: 18 of 20 parks resolve to the generic park.
- FOR's "Royals Stadium" exact-matches the 1973-93 Kauffman park (foul scale 0.9). FOR home games show K% about 3 pp lower than its road games (z≈3).
- The main harm is to the calibration fixture: its league K is about 1.4-2 pp below what neutral parks give.

**Fix:** set `foul_territory_scale` to 0, then retune K and BB. Later, add a foul-out roll (S3-03) and alley and wall-height geometry, and cut altitude to about +5%.

### M6. Batter speed adds no infield hits and no double-play avoidance (Medium)

**Numbers:**
- Per +10 speed: BABIP +0.001 (t < 1), AVG +0.002 (n=195, sp sd 10.4).
- BABIP by speed tier: .295 / .292 / .293.
- The 95% upper bound on the speed effect (about +.003 per 10) excludes an MLB-like effect. MLB's fastest regulars run about +.020-.030 BABIP over the slowest (approx.).
- Fast runners only turn singles into doubles and triples: 1B per BIP -.008 per 10, XBH per BIP +.009 per 10.
- Runner speed also has no effect on tag-ups from third (r +0.013; see M7).

**Root causes:**
- `out_probability` (`fielding.py:158-233`) and the call at `engine.py:4730-4742` have no speed input.
- The DP probability (`fielding.py:236-251`, called at `engine.py:2383`) reads only the runner on first's speed.

**Fix and risks:**
1. Add an infield-hit term for weak grounders. It needs about a 0.08-0.10 out-rate cut at SP 100 to reach the MLB gap; the first proposal of 0.05 gives only about +.014.
2. Add a batter-speed DP term.
3. Centre both on the league mean speed (~56 in alpha), or retune `babip_scale` and the DP base. Uncentred, they would lower alpha's already-low GIDP.

### M7. Extra-base aggression, tag-ups, sac flies and the runner on third (Medium)

**Numbers:**
- **Extra bases on hits.** Runners take the extra base 67-69% of the time on calibration and 75% on alpha. MLB is about 40%: the benchmark's `extra_base_advance_rate` 0.40, which is never computed.
- **Thrown out.** Runners are thrown out on about 9-11% of opportunities (MLB ~2-3%, approx.).
- **Tag-ups from third are a single combined attempt-and-success roll** (`engine.py:1308-1311`, `1664-1690`):
  - The formula is (0.45 + (sp-50)/200 - (arm-50)/250 + `tag_up_third_extra` 0.25) × `advancement_aggression_scale` 1.6, clamped to [0.05, 0.95].
  - For a runner around SP 50 it hits the 0.95 cap whenever arm ≤ 76.5. On calibration, 98.5% of chances were capped.
  - Neither the outfielder's arm (r +0.009, arm 30-71) nor the runner's speed (r +0.013, speed 31-67) affects the outcome.
  - The roll ignores depth and launch angle. He scores on 93-95% of air outs under 150 ft, the same as past 300 ft.
  - The runner never holds: a failed roll is always an out at home, with an occasional throwing error that saves him.
  - The roll also runs on infield-caught line drives: 13.5% of chances, and the runner scored 94% of the time anyway.
  - Calibration seed 1 has 1,847 such chances.
- **Sac flies** are 1.5-1.8x MLB: SF/PA .0115 against ~.0065. About 27-29% of sac flies are lineouts.
- **Runner on third on ground outs.**
  - The decision is one flat roll, 0.25 + (speed-50)/400 (`engine.py:2375-2381`, `config.py:273`). It ignores outs and infield depth, and it is rolled *before* the double-play decision.
  - With a runner on 3rd only, he scores on about 24-28% of <2-out ground outs.
  - On 0-out double plays with runners on 1st and 3rd or loaded, he holds about 75% of the time (113/151, 110/138, 86/125 on calibration seeds 1-3). MLB: he nearly always scores.
  - So RE for runners on 1st and 3rd with 0 out is 0.87-0.89x MLB on every calibration seed (1.55-1.59 vs 1.784). P(score) there is .79 vs ~.866.
  - The roll's position also causes the inning-ending-DP run bug (L15).

**Root causes:**
- `_advance_prob` (`engine.py:1308-1311`) multiplies the whole formula, including the speed and arm terms, by `advancement_aggression_scale` 1.6 (`config.py:429`). This saturates at the 0.95 cap.
- Tag-ups have no hold outcome, no depth term, and run on infield liners.
- The ground-out roll is flat and comes before the DP roll.

The excess advances and the excess outs roughly cancel in runs. The sac-fly excess and the ground-out deficit also cancel, so totals look normal.

**Verified fix effects:**
- Hit advances: scale 1.0 plus out chances cut to about 1/3, applied only to hit advances. Result: XBT .45, outs per opportunity .028, R/G 4.26 (vs 4.28), all gates green on seed 1.
- 0-out DP with a runner on 3rd: letting him score ~92% raises RE for runners on 1st and 3rd with 0 out to 0.92-0.95x MLB, and P(score) to MLB level (.85-.86).
  - The remaining ~5-8% shortfall is not explained by this mechanism.
  - Raising the flat ground-out rate to 0.50 adds nothing measurable to that cell.
  - The combined scoring effect is small: about +0.03-0.08 R/G.

**Fix and risks:**
1. Tag-ups:
   - bring the base below the cap (lower `tag_up_third_extra` or drop the ×1.6);
   - add a hold outcome;
   - make depth and hang time part of the roll, and keep the arm and speed terms outside the clamp;
   - do not roll tag-ups on infield-caught liners.
2. Runner on third on ground outs:
   - move the roll after the DP decision;
   - let him score ~90% on 0-out DPs;
   - use an outs- and infield-depth-aware base of ~0.45-0.55 plus speed otherwise.

   Ship this together with the tag-up fix, so the sac-fly reduction and the ground-out increase cancel in total runs.
3. Risks:
   - Lowering the scale globally without a hold option turns 27-30% of tag-up chances into outs at home.
   - Sac-fly distance thresholds must be calibrated to the engine's drag-free carry. Literal real-feet thresholds cut SF/PA to .0033 and runs by about 0.23.
4. Re-check that RE for runners on 1st and 3rd, and on 3rd only, lands within ±5% of the table on seeds 1-2.

### M8. Ground-ball double plays are low (Medium)

**Numbers:**
- GIDP per opportunity: .068 on alpha, .087 on calibration, against MLB about .10-.11.
- GIDP per team-game: .47 on alpha, .55-.58 on calibration, against MLB about .66-.70. MLB total DP is .76-.82 per team-game.
- Alpha fails the `bip_double_play_pct` gate (.017 vs .028).

**Root cause:** only 29-35% of double-play-situation ground outs become DPs (implied MLB about 45-50%), set by `double_play_base` 0.32 (`config.py:432`). The 0.45 cap rarely binds. Steal volume explains only 5-12% of the gap.

Fly-out plus runner-thrown-out-at-home plays happen (about .02 per team-game) but are never scored as DPs.

**Separate bugs:**
- `engine.py:2405-2406` overwrites an occupied second base on a fielder's choice, deleting that runner (about .09 per team-game on alpha).
- A run can score on an inning-ending GIDP (L15).

**Fix and risks:**
- Raising `double_play_base` to 0.38 gives GIDP .654 per team-game on calibration, runs unchanged, gates green.
- Score tag-up throw-outs as DPs.
- Fix the runner deletion at `engine.py:2405-2406`, and the run on an inning-ending DP (L15).
- Applied with the full running-game package, runs drop to about 3.97, so it needs the offense retune.

### M9. Errors and fielding credit (Medium)

**Errors:**
- E per team-game .21-.28 against MLB .52-.54; FPCT .992-.994 against .985.
- Unearned runs are 3.8% of runs against MLB's 7.7-8.9%.
- Catchers and pitchers can never be charged an error.
- There are no errors on hits, pickoffs or steal throws.
- The fa curve is linear and floored (`fielding.py:265-282`). 37.5% of rolls on the wide fixture sit at the 0.001 floor, so top-quartile infielders make almost no errors (worst to best about 28-45x, against roughly 3-6x among MLB regulars, approx.).
- What does work: errors track the charged fielder's fa (r -0.64 to -0.83 on calibration). On LHB balls, though, the charged fielder is the mirror one (M4).

**Chance distribution:**
- Grounders are credited 2B 41% / SS 41% / 3B 9% / 1B 9% / P 0%. MLB is about 25 / 28 / 19 / 12 / 6 (approx.).
- 3B makes about 0.75 assists per game against ~1.8.
- There are no infield flies, so corner outfielders get 25-35% too many putouts.
- 45% of line-drive outs are handed to infielders by a coin flip after the out is decided (L20).
- Pitchers get an assist on every strikeout (`engine.py:4598-4604`, `4654-4660`): about 7.7-8.7 per game.
- Bunt outs all go to SS.
- The DP pivot gets no assist.

**Impact:** mostly bookkeeping. Hit/out uses zone ratings, so KPIs barely move.

**Fix:**
1. Use a multiplicative error curve.
2. Add catcher, pitcher, steal-throw and outfield-on-hit errors.
3. Re-band infield credit on the physical field angle (after the M4 fix), and add a pitcher comebacker zone.
4. Delete the strikeout assist.
5. Target E per game ~.53 and 3B errors per 9 ~.09.

### M10. Wild pitches and passed balls rolled with empty bases (Medium)

**Numbers:** recorded WP .547 and PB .383 per team-game, against MLB about .33 and .05 (approx.).

**Root cause:** the WP/PB roll (`engine.py:5310`) sits outside the runners-on guard (`engine.py:5301`). About 45-60% of WP/PB happen with the bases empty and 18-25% on fouls.

**Impact:** counting only the miscues that can move runners, the volume is about .35-.41 per team-game, close to MLB's ~.35-.38. Run impact is small. The harm is phantom WP on pitcher lines and PB on catcher lines, and a PB-heavy mix.

**Fix:**
1. Gate the roll to runners on and non-foul pitches.
2. Set `passed_ball_rate` to about .0007-.0012.
3. Include the forced WP/PB from the dropped-third-strike path (about .14-.19 per team-game) when retuning; otherwise WP overshoots.

### M11. No groundball pitchers (Medium)

**Numbers:**
- Pitcher gf is loaded (`models.py:117`) and never read; launch angle uses only the batter's gf (`physics.py:880`). Seasons with every pitcher at gf 20 and at gf 80 are byte-identical.
- Pitcher GB% repeats across seeds at r ≈ 0 (MLB YoY ~0.75, approx.).
- Sinkers produce 41-42% GB against four-seamers' 40-41%. MLB is about 50-55% vs 33-35% (approx.).

**Fix and risks:**
1. Add -(pitcher_gf - 50)·k to the launch-angle mean with k ≈ 0.15-0.2. The originally proposed 0.25-0.35 would exceed MLB spread.
2. Add per-type offsets (sinker ~-3.5 to -4°), centred on usage.

Batter gf also moves HR (about -15% per +10), so this interacts with the power gates. Alpha's compressed pitcher gf (sd 3.5) limits the visible effect.

### M12. Out-of-position assignment dominates alpha defense (Medium)

**Numbers:**
- **In-position regulars barely differ.** Excluding one fa-32 RF, adjusted fa runs 41-52 (sd 1.6), worth only about 4 designed runs per 150 G of spread. The best is +7.1.
- **Out-of-position regulars are the worst fielders by far.** A regular at an unlisted position is cut to adjusted fa 36-39 by the flat ×0.75 multiplier (`fielding.py:139-151`, `config.py:445`, duplicated at `engine.py:2461-2471`), costing -15 to -43 designed runs per 150 G.
  - Holding raw fa fixed, being out of position is worth about -25 realized runs per 150 G (se 3.5).
  - The 7 non-1B cases are the league's worst fielders at -31 to -58 realized.
  - Out-of-position 1B cost little (-0 to -10).
  - Examples: an LF (fa 51) in RF at -38 designed; a C in LF -37; a 1B at SS -31; a 2B at SS -28.
- **The multiplier has no adjacency or difficulty term.** LF → RF costs the same as C → LF or 1B → SS.
- In a 4-seed A/B test, each out-of-position starter costs about 0.20 R/G; FOR loses 0.78 R/G. On the live path, out-of-position starts average 0.34 per team-game across 8 teams; FOR has 1.64.
- Alpha team fa explains little because its spread is tiny (lineup fa sd 0.76; CF fa sd 1.6, so r(fa, OAA rate) is -0.07 there).

**Root causes (corrected):**
- **Several ACT rosters lack a SS/1B/2B-eligible hitter.** For example, ALB has no SS on ACT while 5 sit in the minors.
- **Only 69 of 586 hitters list `other_positions`.** 80 store them as list literals ("['CF']") that `physics_sim/models.py:46-50` cannot parse.
- **Lineup auto-fill prefers an eligible player when one exists.** When none exists, its fallback picks the best bat rather than the best fit, and that cascades: for example an RF moves to 1B, then a 3B moves to RF. It even put an RF at catcher (SAN1). The fallback fill (`fielding.py:72-82`) can place any leftover batter, a DH included, at C; 53 of 1,820 live lineups had no labelled catcher.
- **Where the alpha cases came from.** The 12 out-of-position regulars (plus 5 at a listed secondary position, ×0.9) came from lineups that `auto_fill_lineup_for_team` rewrote during the local re-sim. The downloaded live lineups have only the AUS C → LF case.
  - The live game path rewrites lineups the same way whenever a saved lineup becomes invalid, for example after the injuries and roster drift in H9. So this will happen live.
  - Harness magnitudes are an upper bound, because the harness keeps one lineup for a full season.

**Fix:**
1. Replace the flat ×0.75 with an adjacency penalty in rating points, e.g.:

   | Move | Penalty |
   |---|---|
   | LF↔RF | -2 |
   | CF → corner | 0 / -1 |
   | Corner → CF | -6 |
   | 2B↔SS | -5 |
   | 3B → SS | -6 |
   | IF → OF | -8 |
   | Anything → C | -15 |

2. Make the auto-fill fallback choose the best *fit* (glove at the position, adjacency), not the best bat, and never put a non-catcher at C while a catcher is on the roster.
3. Require roster shape in CPU auto-assign (every position covered, 2 catchers) and in injury replacement (H9).
4. Fix the `other_positions` parse, and populate `other_positions` in the generator.
5. Re-spread fa/arm with position-appropriate means.

### M13. Live 2026 season totals are contaminated (Medium)

**Numbers:**
- In live data, HR/PA vs Contact r = +0.73 and vs Power -0.04.
- If the remaining 91 games run on the fixed engine, the full season projects to HR vs CH +0.49 and vs PH +0.54. The current engine alone gives about +0.10 vs CH and +0.66 ± 0.05 vs PH (15 replicates, PA ≥150; +0.68 at PA ≥282).
- Players now in AAA, Low-A or released hold 28.5% of live hitter PA and 28.8% of live IP.
- 62 live hitters have 15+ G and 0 GS (pinch-run specialists).
- 48% of live relief appearances came from pitchers now off the active roster. That is why live bullpens looked milder than today's code will produce (H1).

**Root causes:**
- `game_runner.py:729-801` adds every game into one flat season dict, with no engine-version or level tag.
- Leaderboards (`api/routers/leaders.py:123-160`) filter by PA/IP only.
- At rollover, `league_rollover.py:476-494` copies season totals into career ledgers and deletes the history shards, which makes the contamination permanent.

**It is not permanent yet.**
- In the audit's copy of the live league, `season_stats.json` equals the 07-21 snapshot (the 7.45.6 boundary).
- A 07-08 snapshot marks the 7.45.0 boundary for 304 players.

**Owner action, before more live games are simmed:** save a copy of the current live season stats as the boundary. Then decide: a season split ("since 7/21") or an exhibition tag for 2026 career, award and arbitration purposes.

### M14. CPU "overall" for pitchers counts pitches thrown (Medium)

**Numbers:**
- `services/roster_auto_assign.py:68-115` and `services/cpu_trade_evaluator.py:956-988` average 13 pitcher keys and count each unthrown pitch as 0.
- r(score, pitches thrown) = 0.985 among pitchers with 40+ IP; r(score, FIP-) = -0.03.
- Each extra pitch adds 4.2-4.6 points.
- Alpha ACT staffs average 3.78-3.80 pitches, AAA 3.43-3.44 and LOW 3.16-3.17, at equal control.
- Pitchers score about 12 points below hitters on the same scale (39.0 vs 50.9), so the trade evaluator undervalues pitchers against hitters.
- In new leagues every non-closer pitcher throws 3 pitches, so the bias mostly hits closers there; the dilution remains.
- The hitter score (no eye; includes sc, pl, vl, gf) tracks OPS+ at r 0.24.

**Fix:** skip zero pitch ratings, as `utils/rating_display._overall_from_row` already does. Better: one shared production-weighted overall (H8) for display, auto-assign, trade and prospect promotion. No engine impact.

### M15. Pitcher injuries about 9x below MLB; durability has no effect (Medium)

**Numbers:**
- About 1.2 pitcher IL stints per team per 162 games (alpha 1.25; calibration 1.17-1.23). MLB in-season is about 11.4 per team; 15.3 counting offseason stints.
- Pitchers are about 30% of IL stints against MLB's ~51% in-season.
- Hitter IL is also about 4x low.

**Root causes:**
- The only pitcher injury path, `_maybe_pitcher_overuse_injury` (`engine.py:3060-3100`), is gated at 80+ pitches and fatigue penalty 0.6+.
- In alpha, 6 of 14 pitcher injuries followed 130-203-pitch outings caused by H1.
- Forcing every pitcher's durability to 25 vs 75 changes injury counts by a non-significant 29%.
- This appears to be a regression: commit 0aff8f6c1 reported 24-27 injuries per team with a 50-56% pitcher share on this harness.
- `scripts/injury_rate_kpi.py` compares all injury events against an IL-only target, which hides the shortfall. It also fails at its default `--games 54`.

**Fix:**
1. Add a per-appearance arm-injury hazard for every pitcher, scaled by durability and recent workload. Recent workload needs persisted usage state (M18).
2. Fix the KPI script.
3. Calibrate to about 11-15 pitcher IL stints per team and a ~50% pitcher share.

### M16. Single catchers and regulars who never rest (Medium)

**Numbers:**
- Starting catchers for BAL, CHI, DAL, ELP, FOR, SAN and SEA caught all 91 of 91 games. HOU's caught 89; its backup plays DH every day. MLB's busiest catchers start about 80% of games (approx.).
- In the 162-game harness, 9 of 20 teams' backup catchers made 0 starts. Spec S2-05 targets 35 or more.
- 61 hitters started all 91 games.
- 7.8 hitters per team qualify for batting titles, against MLB's ~4.3 over a full season.

**Root causes:**
- `_best_rest_replacement` (`engine.py:3370-3377`) requires an exact-position bench player, and for C a real catcher.
- CPU auto-assign requires only one C (`roster_auto_assign.py:43`).
- Batter fatigue never builds: daily recovery 6 + 0.05·durability is at least the per-game cost of 6 for durability above ~14 (`usage.py:95-107`, `147-149`). The fatigue-rest path is dead.
- Batter workloads and forced rests also live only in process memory (M18).

**Impact:** no measurable performance cost; this is a realism and usage problem.

**Fix:**
1. Require 2 active catchers in CPU auto-assign and warn human owners.
2. Allow out-of-position rest substitutes at non-catcher positions.
3. Make batter fatigue accrue.
4. Populate `other_positions` in the generator.

### M17. Team talent spread is about half of MLB's (Medium)

**Numbers:**
- Alpha true-talent W% sd is about 0.039-0.042, so talent explains about 50-54% of the standings spread.
- MLB 2021-24: 0.065-0.080, about 75-80% (repo Teams file).
- Team runs scored track ratings well (R² 0.90-0.97). Team runs allowed have a real, repeatable spread (true sd ~0.23-0.25 R/G), but pitcher ratings explain only R² 0.01-0.05 of it.
- The largest repeatable drivers of runs allowed are not ratings: LHP share (H7) and unearned runs and out-of-position defense (M12).
- The calibration fixture's W% sd is only 0.031, from its narrow batting ratings and random team assembly.

**Fix:**
1. The data migration (section 6), plus H6 and H7.
2. A multi-seed harness KPI `team_true_wpct_sd`, gated on a generator-built league.

### M18. Reliever and batter rest state lives only in process memory (Medium, new)

**What happens:**
- The engine's rest state (`physics_sim` `UsageState`, plus the game-day map) lives only in module globals (`playbalance/game_runner.py:48-87`).
- It is rebuilt empty on:
  - a fresh process;
  - a sim of a different league (line 71);
  - a year change;
  - a backwards date (line 75).
- It is never persisted or rebuilt from `pitcher_recovery.json`.
- Engine availability (`engine.py:504-556`) reads only `UsageState`. The recovery tracker is flushed daily (`pitcher_recovery.py:301-318`), but it only reorders the pen (`game_runner.py:255-323`), which matters only for exact score ties.

**So any sim that runs one day per process has no reliever rest gating at all.** Examples: the "Sim day" button, or a scheduled run with n=1, on a cold Cloud Run instance or right after another league's sim.

**Evidence:**

| Metric | Fresh process daily (C1a-f) | Persistent (P1-P6) | Weekly (C7a-c) |
|---|---|---|---|
| Relievers in consecutive team games | 63-65% | 15-19% | 21-23% |
| True calendar back-to-backs | 35-37% | 8-10% | — |
| Third straight day, per team-game | 0.17 | ~0.007 | — |
| Next day after a 30+ pitch outing | 0.22-0.25 | 0.012-0.017 | — |
| Busiest reliever, appearances per 162 | 153-162 | 82-90 | 89-94 |
| Top-20 relievers, appearances per 162 | 141-147 | 74-78 | 82-83 |

The live league ran in roughly weekly-or-longer batches, and its relievers pitched on consecutive game dates 17% of the time, so it was not hit hard. Batter workloads and forced rests (S2-05) sit in the same state and are lost the same way.

**Fix:**
1. Persist `UsageState`, or rebuild it at the start of every sim call from the tracker's recent appearances, keyed by league and calendar date. Then batching cannot change outcomes.
2. Add a test: N one-day calls must match one N-day call on reliever back-to-back share and appearance pace.
3. Use calendar dates for rest, so off days rest pitchers (the H1 contributor).

Scripts: `rest.py`, `rest_metrics.json`, `drive.py` in `work/followup-replicate-stability-and-resim-representativeness/`.

### M19. Late innings and late & close at-bats are not harder; the late-close modifier adds walks (Medium, new)

**Numbers:**
- **Late & close OPS** (MLB definition) runs -.014 to +.002 of overall (mean about -.005, over 3 calibration and 2 alpha seeds). MLB is about -.030 (approx.).
  - Better pitchers are used in late & close spots (composition-expected wOBA .3147 vs league .3196).
  - That edge is erased by an observed-minus-expected residual of +.003 to +.0065.
- **Late-inning scoring.** Runs per half-inning in innings 7-9 are 1-5% *higher* than in innings 3-6 (pooled about +3.5%; live-path box scores +4%). MLB is roughly 5-8% lower.
- **Relievers.**
  - With pitcher ratings controlled, relievers perform the same as starters (coefficient ≈ 0 ± .003).
  - A fresh reliever gets only the same first-time-through edge a starter gets (about -.005 wOBA), and loses it quickly: +.010 at 5-9 batters faced (26% of relief PA on calibration) and +.022 to +.040 past 10.
- **The late-close modifier adds walks.** It raises late & close unintentional BB% by about +0.7 pp (.093/.091 vs .079/.080 otherwise).
- **Neutralising the modifiers fixes about half the gap.** Setting the late-close, RISP and first-base-open modifiers to 1.0 removes that walk excess, brings innings 7-9 vs 3-6 to about 0.99, and late & close OPS to -.006/-.017.

**Root causes:**
- `physics.py:262-266` applies `pitch_objective_late_close_mod` (`config.py:194-200`: attack 0.95, edge 1.1, putaway 1.1) to every pitch from inning 7 with |diff| ≤ 2, making pitchers nibble. That window is broader than the MLB definition of late & close.
- Relievers get no short-stint or freshness advantage: the fatigue model only penalises.
- Already-known usage bugs (H1) add exposure to long and tired relief.

**Fix:**
1. Set `pitch_objective_late_close_mod` close to neutral, especially edge and putaway, or turn it into a small stuff bonus for high-leverage relievers.
2. Add a short-outing reliever effect, e.g. a small velocity/stuff bonus for the first ~6 batters faced.
3. Add late & close OPS delta and innings 7-9 runs per inning as KPI gates (L18).

Scripts: `analyze.py`, `trans.py`, `box_linescore.py` and `calneu_s*` runs in `work/followup-situational-run-expectancy/`.

### M20. Elite-contact hitters get about half the pitcher strikeout effect; the cap relaxation planned under H6/M1 does not fix it (Medium, new)

**Numbers (PA Monte Carlo on the real per-pitch code, 100k PA per cell):**

K% by hitter Contact (rows) and pitcher control = movement (columns):

| | P35 | P50 | P65 | P80 |
|---|---|---|---|---|
| CH35 | .378 | .461 | .558 | .650 |
| CH50 | .181 | .250 | .351 | .450 |
| CH65 | .112 | .143 | .195 | .255 |
| CH80 | .104 | .113 | .143 | .182 |

- **What log5 predicts vs what the engine does.** Under log5 a pitcher shifts K log-odds by the same amount for every hitter. In the engine, the P35 → P80 shift is +1.31 logit at CH 50, +1.00 at CH 65 and about +0.64 at CH 80.
- **Against CH 80, poor and average pitchers are indistinguishable** (K 10.4% vs 11.3%).
- **Largest log5 misses:**

  | Cell | K% observed | K% predicted |
  |---|---|---|
  | CH80 × P80 | 18.2% | 24.0% |
  | CH65 × P80 | — | 3.6 pp below |
  | CH80 × P35 | 10.4% | 7.8% |

- **In season regressions the interaction is real but modest at today's spreads.** A +1 sd pitcher moves K logit by +0.106 / +0.087 against -1 sd / +1 sd CH hitters (calibration), and by +0.195 / +0.153 on a widened fixture.

**Two causes, contributing about equally:**
1. **Per-swing contact saturates.** `contact_prob` is divided by `k_scale` 0.51 (`physics.py:785-798`, `config.py:322-323`). That exceeds 1 once contact_base passes ~58, and it is then clamped to 1 - whiff_prob.
   - The cap binds on 84-100% of CH 80 swings, and on 0% for CH ≤50 against P ≥50.
   - Once capped, the pitcher acts only through the whiff-quality term: 0.072·max(0, pq-50)/100, about 10x smaller than the uncapped contact slope, and **one-sided**. Below-average pitchers lose nothing extra against capped hitters (contact per swing .941 → .945 at CH 80, against .765 → .840 at CH 50).
   - This accounts for about -3.5 pp of the CH80 × P80 residual.
2. **Looking strikeouts form a floor of about 5.5-8.5% of PA.** They do not depend on Contact or Eye, though they rise about 50% from P35 to P80. Total K cannot follow log5 while this component stays fixed.

**Relaxing the cap alone does not help.** Counterfactual grid, k_scale re-centred so 50×50 keeps K = 25%:
- Product cap: the pitcher K effect at CH 50/65/80 is +1.38 / +1.05 / +0.69 logit.
- Logistic soft cap: +1.33 / +0.99 / +0.76.
- The CH80 × P80 residual stays at -6 to -7 pp, and the soft cap over-amplifies the pitcher against weak hitters (CH 35 effect +1.54 vs +1.13).
- Setting k_scale to 1 while keeping the `min(0.95, …)` ceiling at `physics.py:786-790` is worse: CH 80 effect +0.53, residual -8 to -10 pp.
- Removing both the k_scale division and the 0.95 ceiling, or moving to a log-odds-additive contact term, brings the corner residuals within about 1.5-2.5 pp.
- Signing the whiff terms alone closes only 16-19% of the positive residuals.

**Impact today:** small. Calibration CH sd is 3.7, and alpha has only 7 hitters at CH 65+. It will be material in newly generated leagues: the generator centres contact at 52-70, with 4% outliers at 75-92.

**Fix:**
1. Model contact in log-odds with no clamp, e.g. logit P(contact | swing) = a + b_bat·(CH-50) - b_pit·(pq-50) + pitch-type, zone and count terms.
2. Make the whiff-quality and velocity terms two-sided.
3. Let Contact or Eye reduce looking strikeouts (two-strike take decisions).
4. Retune k_scale and contact_prob_scale together.
5. Gate with the CH × pitcher grid: |K log5 residual| ≤ 2 pp in every cell over the 35-80 range (or log5 on swinging K and looking K separately), plus the league K and contact gates on calibration seeds 1 and 2.

Scripts: `grid.py`, `analyze_grid.py` (`log5_report.txt`), `k_split.py`, `counterfactual.py` (`cf_*.txt`), `regress.py` in `work/followup-hitter-pitcher-matchup-interaction/`.

### M21. Pitcher HR suppression is too strong and non-multiplicative (Medium, new)

**Numbers:**

HR/PA by hitter Power (rows) and pitcher control = movement (columns), CH 50, 100k PA per cell:

| | P35 | P50 | P65 | P80 |
|---|---|---|---|---|
| PH35 | .0396 | .0155 | .0039 | .0004 |
| PH50 | .0484 | .0204 | .0058 | .0007 |
| PH65 | .0881 | .0490 | .0185 | .0047 |
| PH80 | .1386 | .0944 | .0495 | .0190 |

- **Too strong relative to hitters.**
  - On the calibration fixture, pitcher HR/PA true-talent sd (.0077-.0084) equals or exceeds hitters' (.0071-.0075). On the widened fixture it is 0.66-0.78x hitters'.
  - Approximate MLB reference (outside repo data): about 0.4-0.5x.
- **Per rating point:**
  - Power (+0.060 logit per point) is a bigger HR lever than control or movement alone (about -0.043 per point each).
  - Only the two-rating composite (-0.085 per point) exceeds it.
- **Non-log5.** The pitcher's logit effect is larger against low-Power hitters.
  - Within the rating population this is moderate: about +0.15 logit log5 residual at PH60 × P58, and a per-sd pitcher effect 35-45% larger against -1 sd than +1 sd hitters.
  - At the extreme corners it is large: +1.4 to +1.7 logit at PH80 × P80. An average hitter falls to ~0.1% HR/PA against a composite-80 pitcher.
  - No current generator or fixture produces such a pitcher (generator composite max ~66, p95 59).
- **Season regression interaction:** +0.00185 (t +3.77) on calibration and +0.00089 (t +9.81) on the widened fixture.

**Root cause:** pitch quality (0.4·control + 0.4·movement + 0.2·pitch grade) cuts exit velocity through three stacked paths:
- contact_base → quality (`physics.py:785`, `853-857`);
- the quality factor max(0.75, 1-(pq-50)/250) (`physics.py:859`);
- timing and barrel error through difficulty (`physics.py:806-828`, `860-866`).

A HR is a tail event at a fixed fence (`physics.py:1000-1020`), so a low-mean hitter's tail collapses much faster in odds terms than a slugger's.

**Why it matters:** today it is hidden by compressed alpha pitchers (movement fixed at 52, control sd ~1.5). Re-spreading control and movement together (Release 7) would make aces allow almost no HRs to non-sluggers.

**Fix (before the pitcher-rating re-spread):**
1. Reduce pitch quality to a single EV path, e.g. keep the quality factor and stop pq feeding contact_base for EV.
2. Consider making pitcher HR suppression an odds multiplier, e.g. on the HR-eligible carry or launch-angle window.
3. Gates:
   - pitcher/hitter HR true-sd ratio ≤ 0.5;
   - PH × pitcher-composite HR log5 residual within ±0.3 logit over the population's p5-p95 range.

Scripts: `talent_sd.py`, `grid_ph.json`, `log5_report.txt` in `work/followup-hitter-pitcher-matchup-interaction/`.

### M22. Per-fielder range value is 1.5-4x MLB per rating SD, with no positional-difficulty weight (Medium, new)

**Numbers (calibration fixture, 3 seeds, 630 regular player-seasons):**
- **Range per +10 adjusted fa per 150 G:**

  | | 1B | 2B | 3B | SS | LF | CF | RF |
  |---|---|---|---|---|---|---|---|
  | Outs | +15.8 | +15.9 | +13.2 | +13.3 | +20.7 | +24.6 | +28.6 |
  | Runs | +11.7 | +11.8 | +9.8 | +9.8 | +17.8 | +20.8 | +24.7 |

- **Per rating SD.** At the fa spreads the generator produces (sd 7.4-9.8):
  - One SD is worth about 10-14 range outs at 2B/3B/SS and 16-28 in the outfield, against an MLB regular OAA SD of roughly 6-8.
  - That is about 2.5-4x MLB in the outfield and 1.5-2x in the infield. 1B is ~4x, because it carries half of the right-side ground-ball zone.
  - A +20 fa CF would be worth about +45 runs (MLB best about +15-20).
- **No positional spectrum.** Every grounder on a half uses the 50/50 average of that half's two infielders, so for range alone 1B = 2B and 3B = SS.
  - Total value per 10 fa (range + error + DP):

    | | 1B | 2B | 3B | SS | LF | CF | RF |
    |---|---|---|---|---|---|---|---|
    | Runs per 150 G | 13 | 20 | 11 | 17 | 23 | 26 | 29 |

  - Every outfield slot outranks SS, and RF glove is worth about 1.75x SS glove. MLB's spectrum has SS and CF at the top and 1B at the bottom.
  - RF > LF is partly an artifact of the hand-blind spray (M4).
- **Alpha today is mostly shielded.** Its fa is compressed (sd 3-5), which puts the infield near MLB and the outfield at ~1.5-2x. The full exaggeration shows up in freshly generated leagues and on the fixture.
- **Team DER sd is 0.016**, against MLB about 0.010-0.012 (approx.).

**Root causes:**
- `fielding.py:197-212` adds (zone-50)/250 (GB), /300 (LD) or /230 (FB) to the out probability of *every* ball in the zone, routine balls included (×`babip_scale` 0.925, `engine.py:4739`).
- `fielding.py:111-112` and `176-198` average the infield pairs 50/50.
- `adjusted_fielding_rating` (`fielding.py:139-151`) has no difficulty weight.

**Fix:**
1. Scale the deviation (rating - 50), not the rating:
   - infield ground balls ~1.5-2x less (GB divisor ~375-500);
   - outfield ~2.5-4x less (FB ~600-900, LD ~750-1100).

   Do **not** use the existing `range_scale` below 1: it multiplies the raw rating, so it would raise league BABIP.
2. Give each infield position its own weight in the half's rating (e.g. SS 0.40 / 3B 0.30 / 2B 0.35 / 1B 0.15), and give CF a wider zone than the corners.
3. Calibrate so that one fa sd gives about 5-7 OAA per 150 G at each position. Re-check team DER sd afterwards.
4. Derive H8's OVR defense weights from the measured runs after this change and the M4 fix.

Scripts: `fdriver.py`, `an.py`, `an2.py`, `an3.py` in `work/followup-individual-fielder-rating-to-outcome/`.

---

### Low-severity problems

| ID | Problem | Numbers | Cause | Fix |
|---|---|---|---|---|
| L1 | Home-field advantage only about +1 pp | Home W% 0.514 ± 0.012 per replicate (binomial noise). Pooled over 14,502 games, a team-strength fit gives a home edge of +1.1 pp (95% CI +0.3 to +1.9), vs MLB ~+3-4 pp (approx.). Home R/G 4.86 vs away 5.05 (the bottom of the 9th is skipped). Playoff "home field" (`playoffs.py:94`) is only a label. | No explicit home term. The edge likely comes from batting last, the home-only tied-9th closer rule (`engine.py:791-797`) and a non-significant innings 1-8 scoring edge (+0.06 ± 0.03 R/G). Park factors off (`park_factor_scale` 0, `config.py:417`). | Zero-sum ±h edge. Needs about +0.36 R/G of home edge for .535, so +1 rating point is likely too small. Add a home W% KPI, using pooled multi-seed estimates. |
| L2 | Short starts | Alpha 4.87 IP, 84.7 pitches/start, QS 23%, 14.3% of starts under 3 IP. 62% of starts end at 90-99 pitches. Fixture is MLB-like (5.33 IP, QS 36-38%). | Hook score fires at about 89-90 pitches for every endurance-50 starter (`engine.py:650-687`). Alpha's high run level does the rest. | Fix the run environment first. Raising `fatigue_limit_base` overshoots the fixture (27% of starts at 100+). Coordinate with H10's ramp change. |
| L3 | HBP on strikes | HBP 1.41% of PA vs MLB 1.11-1.17%. 42-46% of HBPs come on in-zone pitches. No hitter HBP skill. | Flat per-pitch roll before the swing (`physics.py:680-683`). Miss distance has no side. | Allow HBP only on inside misses toward the batter. Retune to ~1.13%. |
| L4 | Umpire never calls an outside pitch a strike | 0.005-0.018% of out-of-zone takes vs MLB at least 2.5-8% by count. Catcher framing is dead. | `umpire_margin_ft` 0.025 equals `called_zone_shrink_ft` 0.025 (`config.py:30`, `100`). | Measure the margin from the rulebook zone, with a distance-decaying probability. |
| L5 | No intentional walks | 2 IBB in 70,739 PA vs ~140-210 expected at MLB rates (approx.). | Absolute threshold 65 (`engine.py:2765-2789`, `config.py:469`); best alpha hitter is 63.6. Spec S3-16 is unimplemented. | Relative trigger (on-deck gap or league top ~5%), firing with first base open and RISP; fold in the pitch-around logic from L16. |
| L6 | Batting-average spread a little narrow; gates loose | True AVG sd .016-.019 vs ~.021. Gates: avg300 9±9, `corr_avg_contact` passes at ≥0.40 (spec says 0.5). .300-hitter counts per 30 teams (6-12) are fine. | Follows from M1/M2 (no BABIP talent channel). | Tighten the gates after the M2 fix. |
| L7 | Too few fastballs | Fastball + sinker ~33% of alpha pitches vs MLB ~47% (approx.; there is no cutter). | Usage proportional to rating (`physics.py:316`). Alpha fastballs rated ~10-12 below other pitches. | Per-type base weights. This raises league HR/BIP 10-20%, so do it with the arm fix and a retune. |
| L8 | Catcher defense partial | Catcher arm drives CS% (+.045-.052 per 10, fine) but cuts attempts only ~4-5% per 10. Catchers never err. | Attempt deterrent /220 (`engine.py:1946-1966`). No error branch on steals. | Stronger deterrent; catcher throwing errors. |
| L9 | Steal mechanics | `lead_*` knobs are cosmetic (`engine.py:1231-1281`). Pickoffs .009 per team-game. Success saturates at SP ≥72.5 (alpha SB% .84, just over the gate). | See H2. | Fold into H2. |
| L10 | SVO counted at every save-situation entry | 0.779 SVO per team-game vs SV+BS .434, so SV/SVO reads .342. No UI consumer yet. | `engine.py:945-950`. | Publish SVO = SV + BS. |
| L11 | Line scores drop extra innings | 77 of 910 games (8.5%) show inning runs that don't add up to R. | `simulation.py:4114-4121` loops 9 innings; the template has 9 fixed columns. | Render all innings; test that the sum equals R. |
| L12 | Speedsters bat leadoff | Leadoff hitter's expected wOBA ranks 7th of 9 in his own lineup (median). Costs ≤ ~4 runs per team-season. | `lineup_autofill.py:355-365`: slot-1 speed weight 0.25; the OBP proxy has no spread. | Engine-calibrated OBP proxy. Cutting the speed weight alone recovers only ~1 run. |
| L13 | Generated stadium names collide with real parks | FOR's "Royals Stadium" gets Kauffman (1973-93) geometry. About 62.5% of new 20-team preset leagues will contain this collision. | Name lookup (`park_utils.py:230-258`); generated names are "{mascot} Stadium". | Apply real-park data only for an explicitly chosen park ID. |
| L14 | Times-through-order pass 2 is flat | Within pitcher, pass 2 adds about 0 ± 2.5 wOBA over pass 1 (cal s1 +2.3, s2 -4.4; alpha +2.0), vs MLB ~+10. Pass 3 (+16-17) is 60-80% fatigue: a no-fatigue counterfactual cuts it to +3 to +9, and with the TTO knobs also zeroed it is +2.4 ± 2.9. | Familiarity knobs (`config.py:497-499`: contact/eye 0.32, power 0.2 per pass; applied `engine.py:3177-3182`) are worth only ~+2 wOBA per pass, far short of their own comment's "~20-30 OPS pts per pass". The harness `tto_ops_gap` gate (`physics_sim_season_kpis.py:1233-1236`) measures only pass 3 minus pass 1. | Front-load or raise the familiarity bonus so pass 2 reaches ~+8-10 wOBA. Re-check pass 3 after the H10 retune. Add a pass-2 gate. |
| L15 | A run scores on an inning-ending double play (rules violation) | With 1 out and runners on 1st and 3rd (or loaded), 22-29% of inning-ending GIDPs still count the runner from 3rd: 0.28-0.40% of all runs, ~2-2.8 per team-season. It decided 3 walk-offs in 4,860 calibration games. The runs are charged unearned, so ERA is unaffected; runs, W-L and results are affected. | `_resolve_ground_out` rolls `ground_rbi_prob` (`engine.py:2375-2381`) before the DP roll (`2389-2393`); the caller records runs unconditionally (`engine.py:5273-5276`). Rule 5.08(a) forbids the run. | Resolve the DP first. When the DP fires with outs==1, return runs=0 and keep the runner on 3rd. Keep the legal 0-out case. Unit tests: runners on 1st and 3rd, 1 out, forced DP gives 0 runs; 0 out allows a run. |
| L16 | "First base open" pitch-around modifier fires with the bases empty | Applied whenever 1st is empty, about 66% of PAs. Alone it adds ~+0.3 pp league BB% (8.16 → 8.48%, 4 calibration seeds), OBP +.003, R/team/G +0.07, K -0.15 pp. With the RISP and late-close modifiers combined: +0.5-0.6 pp BB, OBP +.0045. The first-base-open modifier is ~60% of that. | `physics.py:254-258` checks only `not bases.get("first")` (`config.py:187-193`: chase 1.1, waste 1.1, attack 0.98). | Fire only with a runner in scoring position and first base open (it then stacks with the RISP modifier), or fold it into the IBB decision (L5). Re-tune the BB% gate afterwards. |
| L17 | Extra innings follow pre-2020 rules; playoff games can end tied | The automatic runner is implemented correctly (`engine.py:3763-3770`) but off (`config.py:304`, `extra_innings_runner` 0.0). The 18-inning tie cap (`engine.py:5560-5589`) ties about 1 game in 2,400-2,800, regular season and postseason alike. A tied playoff game uses up a series game with no winner (`playoffs.py:1014-1019`). Without the runner, extra halves score 0.55-0.64 runs, 2.0-3.3% of games reach 12+ innings, and the average is 1.8-2.1 extra innings. With it: ~1.0 run per top half, 1.4 extra innings, no ties. Alpha has no tuning overrides, so it plays these rules. | S3-04 specified runner-on-by-default and no tie cap, but it was never shipped. Runner placement ignores the `postseason` flag. | Ship S3-04: runner on by default in the **regular season only**, with a postseason exemption. Replace the 18-inning cap with a high safety guard (~30), and never allow a postseason tie. Add a per-league opt-out. |
| L18 | No situational KPIs or MLB reference | The harness checks each event's volume in isolation, so inning-ending-DP runs, the runner-on-3rd deficit and late-inning scoring pass every gate. `data/MLB_avg` has no RE24, run-probability, runs-by-inning, RISP, late & close or extras reference. `pitch_log` records no base-out state (`pitch_context` at `engine.py:4362-4378` is not logged). The inning-run distribution is already available in `GameResult.metadata["inning_runs"]` (`engine.py:5727-5730`) and box score line scores, but is ignored. | Tooling gap. | Log base-out state and score on the first pitch_log entry of each PA. Add KPIs: RE24 (±8% per cell at n ≥1000), P0..P3+, innings 7-9 ratio, late & close OPS delta, extra-half runs. Copy the workspace `mlb_situational_reference.csv` into `data/MLB_avg` after checking its approximate values against FanGraphs or Baseball-Reference. |
| L19 | No batted ball is routine, so fielding luck is large | Per-ball hit probability is unimodal: no ball above 0.90, <0.1% below 0.05, maximum 0.72. Mean per-ball variance is 94% of the binomial maximum. A regular's own-zone results carry ~8-10 runs of pure luck a season at 2B/SS/LF/CF/RF, and ~3-4 at 1B/3B. At alpha's compression this matches or exceeds the rating spread at 2B, LF, CF and 3B. | `fielding.py:191-212` uses only ball type, EV and the zone rating, plus a pull-shift term of at most ±0.04. Launch angle is passed in but never used. | Fold into M2's bimodal difficulty model (routine catches, sure hits), with fielder rating shifting the threshold. This would cut OF luck to roughly ~6 runs and infield luck only ~10-15%. The main value is realism. |
| L20 | Infield line-drive outs decided by outfield range, then credited to infielders | Every liner's hit/out roll uses only the outfield zone rating (`fielding.py:196-201`). `select_out_type` then gives exactly 45% of LD outs to an infielder by a coin flip. Its LA ≥18 branch never runs, because LDs span 9-15.7°. That is ~6.1% of all BIP outs; the infielder's range has no effect, and his fa and arm feed only the error roll. | `fielding.py:254-262`, `engine.py:4849`. | Decide infield vs outfield liner from launch angle and EV before the out roll, and use the relevant infielder's rating. Also stop tag-ups on infield-caught liners (M7). |
| L21 | Ground-ball singles use the infielder's arm for runner advancement | Every extra-base roll on a GB hit (runner from third, R2 home, R1 to third) uses the arm of the infielder at the spray bin: 28.4% of extra-base rolls on hits on calibration and 30.7% on alpha. Throw-out assists on these plays go to the infielder (`engine.py:1574-1607`). OF assists are understated and IF assists overstated. One arm sd (~9) moves attempt probability ~3.6 points and out probability ~4.5 points; negligible on alpha today (arm sd 1.6). | `engine.py:4749-4777`: `advance_infield = ball_type == 'gb'`. | Route GB hits that reach the outfield to the outfielder at the spray bin (LF/CF/RF) for the arm, assists and throwing errors. Keep the infielder only for a modelled infield-hit subset. |

---

## 4. Dead and weak ratings

"Masked" means the mechanism works on a wide-rated fixture, but alpha's compressed spread hides it.

### Hitter ratings

| Rating | Measured effect | Spread (alpha / wide) | Verdict |
|---|---|---|---|
| ch | K: r -0.805 ± 0.019, -6.9 pp per 10. AVG via K only. BABIP ≈0. Plateaus at ~CH 70 (K floor ~10-11%, including a contact-blind looking-K floor of 5.5-8.5%). Halves the pitcher's K effect at CH 80 (M20) | sd 5.2 / 9.9 | Works for K; weak for AVG/BABIP; saturates |
| ph | HR r +0.66 ± 0.05. Only +1.7 HR/600 per 10 below PH 52. Per point a bigger HR lever than control or movement alone | sd 4.5 / 9.4 | Works above 52; weak below (by design per S3, floor too high) |
| eye | +0.75 pp BB per 10 (wide). Alpha per-replicate r ≈0; pooled over 15 replicates r +0.37, +1.1 pp per 10 | sd 1.46-1.48 / 10-15.6 | Weak by mechanism + masked |
| sp | Steals r +0.76, triples +0.62. BABIP / AVG / GIDP ≈0. No effect on tag-ups from third (r +0.013; roll capped) | sd 10.4 / 10.7 | Works for steals and extra bases; dead for batting and tag-ups |
| gf | -0.1° LA per point; GB% true sd 0 in alpha | sd 1.6 / 10.4 | Weak + masked |
| pl | Inverted for RHB; no HR effect (max abs r 0.11, wide) | sd 1.9 / 9.4 | Effectively dead (bug, M4) |
| vl | Shifts platoon split; season-neutral by design. Double-counted with handedness | sd 3.8 / 10.4 | Weak by design; harmful via the ±4 generator nudge |
| sc | Never loaded by the engine | sd 3.4 / 10.1 | Dead (still counted in OVR/CPU scores) |
| fa | Individual OF range at the designed slope (r with OAA rate +0.75 to +0.88); IF range through the pair average (+0.42 to +0.62). Too steep: 1.5-4x MLB per SD, no positional spectrum (M22). Displayed lines track it at only r 0.00-0.44 (LHB mirror, M4). Team DER r +0.75/+0.82 (fixture) vs +0.26 (alpha). Errors floored for fa ≥ ~54-59. In alpha, the out-of-position ×0.75 matters more than fa (M12) | sd 1.2-1.5 (in-position adjusted 1.6-2.3) / 8-10 | Works; too steep and mis-weighted by position; mis-credited; masked in alpha |
| arm (hitter) | OF kills per extra-base attempt r +0.60 to +0.77; catcher CS% r +0.61-0.67 (fixture) vs +0.08-0.29 alpha. Dead on tag-ups from third (r +0.009; capped). GB-single advances use the infielder's arm (L21); 13-23% of hit advances and 34% of tag-ups roll against the mirror outfielder's arm on LHB balls (M4) | sd 1.3-1.7 / 7-9 | Works on hit advances; dead on sac flies; partly mis-routed; masked |
| durability (hitter) | Batter fatigue never accrues for durability > ~14 | — | Dead in practice |

### Pitcher ratings

| Rating | Measured effect | Spread (alpha / wide) | Verdict |
|---|---|---|---|
| control | FIP -0.85 per 10 (wide), mostly K and contact quality. BB only -0.64 to -0.79 pp. About -0.043 HR logit per point (with movement, the composite over-suppresses HR: M21) | sd 1.53 / 10 | Works as "stuff"; weak for walks; HR effect too strong in combination; masked |
| movement | FIP -0.68 per 10 (wide) | exactly 52 / 10 | Works; dead in alpha (constant) |
| arm | FIP +0.08 to +0.16 per 10; HR/BF +0.16-0.22 pp; K ≈0. EV weight 0.48 is right-signed but ~2x physical size; offsetting whiff terms inactive below 90 mph. In-game velocity loss *helps* tired pitchers (H10) | sd 2.0 / 10.2 | Net wrong-signed |
| fb, cu, cb, sl, si, scb | Each ~-0.1 FIP per 10; whole arsenal ~-0.30 (~40% of control). fb does not set velocity | sd 7-9 / ~10 | Weak (20% weight) |
| kn | No pitcher has it | — | Untestable |
| gf (pitcher) | Never read; gf 20 vs 80 identical | sd 3.5 / 10.1 | Dead |
| fa (pitcher) | Never read; pitchers never field | sd 3.9 / 7.5 | Dead |
| vl (pitcher) | Only vs LHB, at 0.25 weight; blank in alpha | blank / 8-10 | Weak; dead in alpha |
| endurance | +0.56-0.74 outs/start per 10 (fixture); r ≈0.01 in alpha | sd 0.9-1.4 / 7.9-14.9 | Works; masked |
| hold_runner | CS% r +0.36/+0.38 (fixture) vs +0.15 alpha; no other outcome | sd 1.4-4.1 / 10 | Weak; masked |
| durability (pitcher) | Injury rate 25 vs 75 not significant; recovery saturated | sd 3.8 | Dead |

### Catcher-specific uses

| Rating | Measured effect | Verdict |
|---|---|---|
| Catcher fa (framing) | ≤0.26% out-of-zone strikes even at fa 100 | Dead (L4) |
| Catcher fa (steals, PB) | +0.03-0.05 CS% and -10% PB per 10 | Works (PB volume itself is bugged, M10) |

---

## 5. Data-quality caveats and what they mean for the live season

- **Rating compression (old normalize bug).** Alpha spreads among regulars:
  - Pitchers: movement exactly 52 (461 of 494 pitchers; all with 40+ IP); control 50-57 (sd 1.5); endurance sd 0.9-1.4; arm sd 2.0; vl blank for all 494.
  - Hitters: eye sd 1.48; fa sd ~1.2-1.5; arm sd 1.3-1.7; gf sd 1.6; pl sd 1.9.

  Any correlation in alpha is therefore capped by spread, not mechanism. Every "dead" claim was cross-checked on the wide calibration fixture and two "orthogonal-wide" fixtures (all ratings redrawn at N(50,10)).

  **Implications for owners:**
  - In the live league, pitcher choices barely matter and hitter walks are mostly luck, whatever the engine does, until ratings are re-spread.
  - The current generator still floors control at 50 and movement at 52, and derives eye from contact, so new leagues partly inherit this.
  - Compression also hides the matchup problems (M20, M21) and the steep fielding slopes (M22). Those will surface in newly generated leagues and after any re-spread.
- **Rating level.** Alpha's lineup hitters sit about +3 CH / +2 PH above the calibration fixture. Combined with an engine that reads absolute ratings, that is most of the extra 0.5 runs per game. A generated league needs checking against the fixture before any league-wide retune.
- **Alpha speed tiers.** Archetype floors put 15.5% of hitters at SP ≥70 (spikes at exactly 70 and 85). The fixture tops out at 67. Triples, SB% and steal-success saturation are inflated in alpha for this reason, not only because of engine knobs.
- **Ratings are static during a sim.** Only injury fields change, so correlations against the end-of-run players.csv are unbiased.
- **Live contamination.** The 710 live games include:
  - pre-7.45.0 games where Contact drove HR;
  - pre-7.45.6 games where AAA, Low-A and DL players played MLB games;
  - pre-7.44.6 pinch-run specialists.

  Live correlations must not be used to judge today's engine, and that includes the live bullpen workload: live pens looked milder only because of the pre-7.45.6 pitcher pool (H1). Live totals will keep showing a Contact→HR link after the season ends (projected r +0.49) unless the season is split (M13).
- **Stat-key collision.** Any CS, SB%, catcher CS%, putout or pickoff number read from `season_stats` is corrupted (H5). Use harness totals or SBA minus SB. Per-fielder PO/A/E on LHB balls are also mis-credited (M4).
- **Sample sizes.**
  - The 910-game current-engine data is 91 games per team (about 350 PA per regular, about 70 IP per starter).
  - True-talent spreads were estimated as observed variance minus binomial noise, and several come out at 0 within noise; upper bounds are given where relevant.
  - A single replicate cannot resolve a BB true sd below ~0.007, so walk-skill conclusions on alpha use pooled replicates.
  - Hitters with ≥150 PA (n=195) and pitchers with ≥40 IP (n=218) were the standard filters.
  - Team-level results use only 20 teams.
  - The headline numbers were reproduced over 15 replicates; use the noise floors at the top of this report.
- **Engine path.** Most season experiments ran on the `physics_sim.team_data` harness path, not `playbalance/game_runner.py`. The live-path current-engine data and the 15 live-path replicates agreed on every aggregate and rating link checked. Exceptions:
  - The harness holds lineups fixed, which overstates out-of-position exposure (M12). The live path also rewrites invalid lineups through auto-fill, so the problem is real, just smaller.
  - The live path's rest state lives only in process memory (M18). Sim batching therefore changes bullpen outcomes: daily process resets remove 120+ starts but create back-to-back reliever abuse. Weekly batches behave like a persistent process.
  - Only the live path can hit the lineup stall (H9).
- **MLB references.** Repo data covers league averages, Lahman team totals 2021-24, Statcast counts 2023, position averages and putouts. The following came from memory and should be added to `data/MLB_avg` before being used as gates:
  - BABIP by ball type; launch-angle sd; hit rate by exit velocity
  - platoon ratios; XBT%; infield-hit rate; IBB rate
  - pitcher K%/GB% dispersion and year-to-year reliability; hitter vs pitcher HR true-talent sd
  - per-position assists and errors; OAA and fielding-run spreads; umpire accuracy
  - in-game velocity fade; TTO by pass; late & close splits; save conversion; home W%

  A draft situational reference file (RE24 2010-15 plus approximate run-probability, inning-distribution, RISP, late & close and extras values) is at `work/followup-situational-run-expectancy/mlb_situational_reference.csv`.

  The benchmark CSV itself has errors: `sba_per_pa` 0.050, `qualified_hr30_count` 5.5 and `qualified_hr40_count` 2.5. Its `qualified_k_pct_sd` .055 is a hitter value.

---

## 6. Recommended fix plan

The order is chosen so each release can be verified on its own and the big retunes happen once.

**Standing rules:**
- Every engine change runs `scripts/physics_sim_season_kpis.py --strict` on calibration seeds 1 and 2, plus an alpha-league copy, before it ships.
- Watch `corr_hr_power` / `corr_hr_contact` / `corr_iso_power` so the S3 power fix is not undone.
- For usage changes, verify on ≥3 seeds with both a persistent and a 7-day-batch driver, and compare against the replicate noise floors.
- Per AGENTS.md, a data migration (Release 7) is a MAJOR-version change and needs your explicit confirmation.

### Release 0: owner actions, no code
- **Save the boundary snapshot.** Save a copy of the live league's current season stats as the 7.45.6 boundary before the next sim (M13). Do this from your own tooling; the audit touched no live data.
- **Check live active rosters** for pitcher-heavy drift (fewer than ~10 active position players), and repair them before the next sim, so H9 does not stall the league before the fix ships.
- **Decide how the 2026 alpha season counts:** split leaderboards ("since 7/21"), or tag 2026 as an exhibition season for careers, awards and arbitration.
- **Design calls needed before Releases 3-7:**
  - Absolute vs league-relative ratings (H3).
  - The canonical hitter speed distribution: continuous ~N(50,10), or archetype tiers (H2).
  - Whether Contact should get a small BABIP edge.
  - Whether below-average Power should be steeper.
  - What vl means: an absolute vs-LHP rating, or a hitter-specific split.
  - Whether LHP and RHP should be equal at equal ratings.
  - 11- vs 13-pitcher staffs.
  - Whether off days count as rest.
  - How much pitch-type grades should matter.
  - Extra-inning rules: automatic runner in the regular season (recommended), with a per-league opt-out (L17).
  - The intended positional value of defense (how much SS glove vs RF glove is worth) (M22).
  - How strong a pitcher's HR suppression should be relative to hitter Power (M21).

### Release 1: sim-stall hotfix, stat-keeping and display fixes (patch; no calibration impact)
- **Ship first, as its own patch: the lineup-stall fix (H9).**
  - Position-aware injury replacement.
  - Emergency fill restricted to the team's own organisation, as a recorded promotion.
  - The date-played check requires every game on the date.
  - Regression test.
- Namespace fielding keys (cs/po/ci/sba) and pitcher fielding pk in `_persist_physics_stats`; update readers (H5).
- Render all innings in line scores (L11).
- Publish SVO = SV + BS (L10).
- Delete the pitcher assist on strikeouts; credit bunts by direction; give the DP pivot an assist (M9, bookkeeping parts).
- OVR redesign, plus the matching `_overall_from_row` change (H8). CPU auto-assign and trade scores skip zero pitch ratings, or share the new overall (M14).
- Real-park geometry only for an explicit park ID (L13).
- Fix the `other_positions` list-literal parsing (M12).

**Verify:**
- Unit tests:
  - hitter cs total = catcher sba - sb;
  - line-score sum = R;
  - two pitchers differing only in 2 vs 5 pitches score within about 1 point;
  - a 4-hitter injury day on a pitcher-headed AAA list sims cleanly;
  - a half-played day resumes the missing games.
- Re-run a 91-day replicate and confirm no stall.
- On a wide fixture: r(OVR, OPS+) ≥ 0.6 and r(OVR, FIP-) ≤ -0.6.

### Release 2: harness, benchmarks and a second fixture (tooling only)
- **Benchmark CSV corrections:**
  - `sba_per_pa` → ~0.025; add `sb_per_team_game` ~0.72.
  - hr30 → ~20 (±8); hr40 → ~5, with a low-side check.
  - Relabel K-sd as hitter.
- **Implement unused metrics:** `hard_hit_pct`, `barrel_pct`, `extra_base_advance_rate`.
- **Build a second fixture:** generator-built, real roster selection (ACT = top per organisation), generic parks, MR1-3 labels, a fast-runner tail.
- **Log base-out state** (outs, base mask, score) on the first pitch_log entry of each PA (L18).
- **Add KPIs, report-only first:**
  - Usage: starts ≥120 pitches; relief outings ≥60 pitches; relievers per game; closer IP per game; reliever back-to-back share.
  - Plate discipline: per-count swing rates; first-pitch PA endings.
  - Dispersion and matchups: hitter and pitcher BB% true sd; pitcher K% sd; pitcher/hitter HR true-sd ratio; CH × pitcher K log5 grid and PH × pitcher HR log5 grid.
  - Fatigue: starter FB velocity drop (0-25 vs 91-105 pitches); within-pitcher wOBA at 91-105 pitches; TTO pass 2 and pass 3 separately.
  - Running and defense: XBT%, SF/PA, GIDP per opportunity, E per game, WP/PB per game; per-position OAA per fa SD and team DER sd.
  - Situational: RE24 cells; P0..P3+; innings 7-9 runs ratio; late & close OPS delta; extra-half runs; runs on inning-ending plays (must be 0).
  - League and team: home W% (pooled); per-hand platoon gaps; LHP-minus-RHP RA9; IBB/PA, HBP/PA; backup-catcher starts; `team_true_wpct_sd` (multi-seed).
- **Add a batching-invariance test:** N one-day sims vs one N-day sim (M18).
- **Fix `scripts/injury_rate_kpi.py`** to count IL stints only and to run at its default length (M15).

**Verify:** the current engine reproduces today's numbers on both fixtures (it should fail the new fixture; that is the point).

### Release 3: usage and logic bugs (patch; roughly run-neutral except as noted)
- **Bullpen (H1):**
  - Role normalisation: MR\d+ and RP → MR, in both the outs cap and the fatigue windows.
  - Gated empty-bullpen fallback that excludes the closer.
  - Remove the closer rest bypass.
  - Inning-start outs/pitch-cap hook.
  - Starters always get SP limits; one shared rotation builder.
  - Mop-up rule for fully used bullpens.
- **Persist the engine rest state,** or rebuild it from the recovery tracker by league and calendar date (M18).
- **Bench and fatigue (M16):** 2-catcher requirement in CPU auto-assign; out-of-position rest substitutes at non-catcher spots; batter fatigue that accrues.
- **Auto-fill fallback** chooses the best fit, not the best bat; no non-catcher at C while a catcher is available (M12).
- **Rules and runner bugs:**
  - Fix the runner-on-2nd deletion at `engine.py:2405-2406` (M8).
  - Fix the run on an inning-ending DP (L15).
  - Never allow a postseason tie (L17). The automatic runner in the regular season follows the Release 0 design call.
- **Pitcher baseline injury hazard with durability (M15).**

**Verify** on both fixtures, seeds 1-3, persistent and 7-day drivers:
- starts ≥120 pitches → ~0
- relief outings ≥60 pitches < ~2%
- relievers per game 3.0-3.6
- closer ≤ ~1.15 IP per game and no third-straight-day closer
- reliever back-to-back share ~15-25% under every batching mode
- 0 runs on inning-ending plays
- pitcher IL ~11-15 per team-season
- league ERA within noise. R/G is expected to fall ~0.1-0.15 from the bullpen fix; record it and absorb it in Release 5.

**Side effects:** more relievers per game; closers used less often; slightly lower scoring.

### Release 4: running game, the planned stolen-base work (#5)
Split into run-neutral and run-moving parts.
- **4a (run-neutral):**
  - No steals, WP or PB on fouls.
  - WP/PB only with runners on; retune PB including the dropped-third-strike path (M10).
  - Exponential or logistic attempt curve with a lower scale; saturating success curve; speed in double steals (H2).
  - Route GB-hit advances to the outfielder's arm (L21).
- **4b (moves runs; ship together with Release 5):**
  - XBT scale 1.0 applied to hit advances only, out chances about 1/3.
  - Tag-ups: a hold option, depth and hang time in the roll, arm and speed outside the clamp, no tag-ups on infield-caught liners. Calibrate to engine carry.
  - Runner on 3rd on ground outs: roll after the DP decision, ~90% score on 0-out DPs, and an outs/depth-aware base of ~0.45-0.55 (M7).
  - `double_play_base` ~0.38; tag-up throw-outs scored as DPs.
  - Batter-speed infield-hit and GIDP terms, centred on the league mean speed (M6-M8).

**Verify on both fixtures:**
- SBA/PA ~.025, SB per team-game ~.72, SB% ~.79
- XBT ~.40, SF/PA ~.0068, GIDP per team-game ~.68
- RE for runners on 1st and 3rd with 0 out, and on 3rd only, within ±5% of the RE24 table
- r(arm, tag-up outcome) and r(sp, tag-up outcome) clearly nonzero
- r(sp, BABIP) > 0.15; GIDP rate falls with batter speed
- Measure SB% from harness totals, not `season_stats`.

**Side effects:** 4b lowers runs (about -0.3 R/G with the full package), which Release 5 must absorb.

### Release 5: plate discipline, contact, matchups and platoon (joint retune; likely MINOR)
- Count swing table and 3-ball scales (with separate 3-2 handling); trim two-strike fouls (M1).
- Eye chase/zone slopes with a floor; control moved toward command (H4).
- **Replace the contact cap with a log-odds-additive contact model** (no k_scale<1 division, no 0.95 ceiling), with two-sided whiff terms and a Contact/Eye-dependent looking-K (M1, M20, H6). Do not ship a product or soft-cap relaxation; it does not work.
- Platoon: drop the generator's ±4 vl, asymmetric handedness bonus, power bonus applied after the knee (H7, M3).
- Pitch-objective modifiers:
  - first-base-open gated on RISP (L16);
  - late-close modifier near neutral;
  - a short-stint reliever edge (M19).
- `foul_territory_scale` = 0 (M5).
- HBP gating (L3), umpire margin (L4), relative IBB (L5), home-field term (L1).
- TTO familiarity front-loaded for pass 2 (L14). Re-check pass 3 after Release 6's fatigue retune.

**Verify on both fixtures:**
- K ~22%, BB ~8.2%, SwStr ~11%, contact ~.76, P/PA ~3.88
- per-count swing within ~.05 of MLB 2023
- CH × pitcher K log5 residual ≤ 2 pp in every 35-80 cell
- hitter BB% true sd ≥ .02; pitcher BB true sd ~.02 (wide fixture or pooled replicates)
- platoon gaps in band; LHP-RHP RA9 within ±0.15
- late & close OPS ~.02-.04 below overall; innings 7-9 runs per half below innings 3-6
- TTO pass 2 ≥ +8 wOBA
- home W% .535 ± .015 (pooled)
- R/G 4.47 ± .25 on BOTH fixtures

### Release 6: batted ball, power, pitching stuff, fatigue and fielding (engine overhaul; MINOR)
- **Batted ball (M2):** carry with drag (first); launch-angle mixture with pop-ups and topped balls; pop-up class and foul-out roll (S3-03); standard class cutoffs; xBA-style hit table with a bimodal difficulty model (L19); infield liners decided before the out roll (L20).
- **Spray (M4):** batter-relative spray converted once to a physical angle, used by every consumer (fixes both pull and LHB credit), then widened.
- **Power (M3):** Power below the knee (Override A, or a steeper variant); `gap_norm` CH-only at ~0.225; doubles level via `double_distance_scale`.
- **Pitching stuff and fatigue, as one coupled change (H6 + H10):**
  - Velocity out of exit velocity, or `ev_pitch_weight` ~0.2, with two-sided velocity whiff.
  - Fatigue velocity fade 0.015 and control/movement factors re-sized (~0.05/0.04 or a flatter ramp), all as `DEFAULT_TUNING` knobs.
  - Higher pitch-grade weight; pitch-quality chase term.
- **Pitch quality in exit velocity (M21):** a single path; consider odds-multiplicative HR suppression.
- **Pitcher batted-ball identity (M11, L7):** pitcher gf in launch angle (k ~0.15-0.2), a sinker offset, and per-type fastball usage weights.
- **Fielding (M9, M12, M22):**
  - range terms scaled on the deviation, with per-position weights;
  - multiplicative error curve and the missing error sources;
  - infield chance bands;
  - out-of-position adjacency matrix.
- **Parks (M5):** alley and wall-height geometry; altitude ~+5%.

**Verify on both fixtures, seeds 1 and 2:**
- BABIP .291; HR/FB .11; Statcast GB/LD/FB/PU ~43/25/24/7; hard-hit ~.38; barrel ~.075
- mean HR distance ~400 ft
- arm coefficient on FIP negative; mean pitch grade std beta on K ≥ 0.35
- starter FB fade 1-2 mph by pitches 91-105; within-pitcher +10 to +20 wOBA at 91-105 pitches; TTO3-TTO1 +20 to +30 wOBA
- pitcher/hitter HR true-sd ratio ≤ 0.5; PH × pitcher HR log5 residual within ±0.3 logit over p5-p95
- one fa SD ≈ 5-7 OAA per 150 G at each position; SS/CF glove worth at least as much as corner OF; team DER sd ~0.010-0.012
- pitcher GB% true sd ≥ ~.05 on the wide fixture
- E per game ~.53
- `corr_hr_power` ≥ 0.6; `corr_avg_contact` ≥ 0.5
- re-measure H1's stuck-pitcher punishment

**Side effects:** large. HR, BABIP, K and fatigue costs will all swing during the work. Every `hr_scale` / `babip_scale` / EV / fatigue knob needs a joint retune.

### Release 7: generator and alpha-test data migration (MAJOR; needs your confirmation)
- **Generator changes:**
  - Remove the control floor of 50 and movement floor of 52.
  - Generate eye independently.
  - Widen gf, pl, fa and arm with position-appropriate means.
  - Replace the speed tier floors with a continuous distribution plus a modest archetype offset.
  - Correlate gf negatively with ph.
  - Populate `other_positions`.
- **Alpha migration:**
  - Rank-preserving re-spread of pitcher control, movement, arm and endurance, and of hitter eye, fa, arm and gf. Keep means, so the run level does not move.
  - Fill pitcher vl.
  - Recentre hitter vl by bats.
- Do this **after** Releases 5-6. Re-spreading arm before its sign is fixed would make that effect worse. Re-spreading control and movement before M21 is fixed would make aces near-HR-proof against non-sluggers. Re-spreading fa before M22 would make fielding swings unrealistically large.

**Verify** on the alpha copy:
- r(team fa, DER) > 0.5
- pitcher rating R² on FIP rises toward the fixture's ~0.5
- true W% sd ≥ ~0.055
- hitter and pitcher BB% spread visible
- K and HR log5 grids still within their gates

---

## 7. Claims corrected or refuted during verification (do not chase)

No finding was dropped outright. The following specific claims or proposed fixes were shown wrong or overstated:

### Contact, power and batting average

- **"Power raises AVG more than Contact."** Not within today's rating range: Contact's per-point effect is at least as large (+.029 to +.039 vs +.023 to +.028 per 10). The S3 gate (≥0.40) passes. Only the high-CH plateau and the missing BABIP role are real.
- **"Contact predicts ISO better than Power."** Only on a fixture where CH sd is 2.3x PH sd. Per point, Power drives ISO about 2-3x more.
- **"Too few .300 hitters, too many sub-.220."** Counted per 30 teams (as the harness does), .300 hitters are 6-12 against MLB's 9. The sub-.220 excess is survivorship from no benching.
- **"Contact rate spread scales one-for-one with CH spread."** No: the contact cap halves the slope at high CH.
- **"Raise `whiff_base`" (as a K fix).** It does nothing below the contact cap and compresses the top end.
- **"Two-strike contact lift is unrealistic."** Not shown: MLB contact also rises with two strikes.
- **"`k_scale` 0.55 + `count_contact_scale` 1.0 fixes K."** It overshoots to K 27.5% (alpha) and 29.3% (fixture).
- **"Doubles are slaved to Power."** Per PA, doubles are driven about equally by CH and PH, and the 2B-HR correlation comes from shared ratings.
- **"Platoon HR split grows steadily with Power."** It is a step at the knee, peaking at PH 54-56, then easing.
- **"Hard-hit rate is low because mean exit velocity is low."** It is the shape of the distribution: a level shift to hard-hit .38 would push mean EV to ~90.8.
- **"Widen launch-angle sd" as a stand-alone fix.** It would roughly double HR (2.37 per team-game) under drag-free carry.
- **"HR vs Power is +0.65 in one place and +0.71 in another."** These are the same 910-game data under two filters: PA ≥150 (n=195) and PA ≥282 (n=156).
  - Over 15 replicates the two filters give +0.660 ± 0.047 and +0.683 ± 0.046. The stricter filter is higher by +0.023 ± 0.019 because of less binomial attenuation.
  - R0's +0.056 gap was mostly R0-specific noise.
  - Quote one definition: r(PH, HR/PA) = +0.66 ± 0.05 (PA ≥150; +0.68 at PA ≥282).

### Matchups

- **"Pitcher quality is irrelevant against weak hitters."** False: from P35 to P80, K rises +27 pp at CH 35 and at CH 50, and the cap never binds there. The compression is at the *top* of the contact scale.
- **"Relaxing the contact cap (product or soft cap) will make aces matter against elite-contact hitters."** It changes pitcher value by ≤0.11 logit at CH ≥50, and the CH80 × P80 residual stays at -6 to -7 pp.
- **"Setting k_scale to 1 removes the knee."** Not with the 0.95 ceiling kept: that makes it worse (CH 80 effect +0.53).
- **"A log-odds contact rewrite alone makes K follow log5."** It fixes swinging K, but the contact-blind looking-K floor leaves about a 5 pp miss at CH80 × P80, so looking K must also depend on Contact or Eye.
- **"Signing the whiff terms fixes the bad-pitcher-vs-elite-hitter residual."** It closes only 16-19%. Most of the residual comes from the cap discarding the contact_base pitcher term.
- **"The pitcher composite is a bigger HR lever than Power."** Only the two-rating composite is. Per individual rating point, Power (+0.060 logit) beats control or movement alone (~-0.043). The extreme-corner interaction (+1.4 to +1.7 logit) lies outside the generated rating population; within it the effect is moderate.

### Discipline

- **"Fatigue adds +0.35 pp BB."** This was an artifact of bucketing PAs by their last pitch. The real effect is about +0.05-0.07 pp.
- **"Fixing MR roles would lower league BB."** MR1-3 pitchers are almost never fatigued today.
- **"The positive Z-swing slope is the main cause of missing walk spread."** The shallow chase slope is. The Z-swing sign causes the negative O/Z correlation and flat pitches per PA.
- **"Alpha hitter BB% has exactly zero true-talent spread and eye does nothing."** Per replicate it is indistinguishable from 0, but one replicate cannot detect a true sd below ~0.007. Pooled over 15 replicates there is a small real eye-driven skill (sd 0.0016, r +0.37, +1.1 pp per 10 eye). It is tiny because eye is compressed.
- **"Use ~0.003 BB-sd per replicate as the verification floor."** Not valid: per-replicate scatter is ~0.005. Use pooled or wide-fixture estimates.
- **"The first-base-open modifier adds ~0.6 pp of walks."** It adds ~0.3 pp alone; 0.5-0.6 pp is the combined effect of first-base-open, RISP and late-close.

### Pitching, fatigue and pitcher usage

- **"Pitch-type ratings are cosmetic."** Weak, not dead: +10 across the arsenal is about -0.30 FIP, about 40% of control.
- **"Alpha's compressed pitchers inflate offense."** Reversed: fixture-like pitchers raise alpha R/G to 5.23 because arm is wrong-signed. Repairing pitcher spreads will not move league scoring.
- **"The EV velocity term has the wrong sign."** The sign is physically right; its weight (0.48) is about 2x too large. The *net* arm effect is wrong-signed because the whiff and difficulty terms switch off below 90 mph.
- **"Fatigue velocity loss makes a pitcher worse."** In this engine it makes him better on contact: -21 to -79 wOBA on its own. It cancels most of the control/movement damage.
- **"Fixing only the velocity fade (or only the H6 EV term) fixes fatigue."** Either one alone roughly quadruples fatigue damage (+20 → +82 wOBA at penalty 1.0; HR/PA about 2x).
- **"Control 0.12 / movement 0.10 with a 0.015 fade gives MLB-sized fatigue."** Only at penalty 0.5-1.0. Starters reach penalty 1.26-1.5 by 91-105 pitches, where it costs +37 to +53 wOBA, two to three times the target. Use ~0.05/0.04 or a flatter ramp.
- **"A tired pitcher left in gets shelled."** He gives up only about +26 to +50 wOBA (starter CIs include 0 on calibration), mostly through lost K. Treat it as usage and realism, not a performance swing.
- **"Fatigue explains only 35-45% of the pass-3 TTO penalty; a separate non-fatigue source exists."** The penalty-band regression overstated the non-fatigue share. The no-fatigue counterfactual shows fatigue is 60-80%, and the rest is fully explained by the TTO knobs.
- **"The closer bypass causes high closer innings."** Removing it alone raises IP per appearance (1.41 → 1.62). Long closer outings come from the stay-in rule and missing hooks.
- **"Active-pitcher count predicts reliever overwork."** At season start r = +0.05. The MR1-3/RP label bug and in-season depletion are the drivers.
- **"Live cloud batches reset usage state, so owner-visible bullpens are milder."** Wrong cause. Live relievers' back-to-back rate (17%) matches persistent runs, not reset runs (65%). Live pens were milder because pre-7.45.6 games had a bigger pitcher pool. Under today's code, owners will see the 120+ starts.
- **"The draft's H1 numbers are one lucky seed."** They sit inside the 6-replicate persistent spread. Its 60+ relief share actually understates the persistent mean (9.6%).
- **"14 of 20 teams used exactly 5 starters."** It was 12 of 20.
- **"Injured pitchers average durability 50.0," offered as evidence.** Every alpha pitcher who pitched has durability exactly 50, so the figure carries no information.
- **"`qualified_k_pct_sd` is a pitcher gate."** It measures hitter K%.
- **"In alpha, OVR's pitcher r ≈ 0 is OVR's fault."** Mostly compression: the best possible proxy reaches only r -0.12 there.

### Baserunning, situational and defense

- **"The steep steal curve fits both fixtures."** It leaves alpha at SBA/PA .050.
- **"Alpha's triples and SB% are an engine baserunning problem."** Mainly alpha's speed tiers; the fixture passes both.
- **"Raising the DP cap is needed."** The 0.45 cap binds on ~2.7% of rolls; `double_play_base` is the lever.
- **"Low GIDP comes from steal volume."** Steals explain only 5-12% of the gap.
- **"Sac-fly fix with real-feet distance thresholds."** It cuts SF/PA to .0033 and runs by about 0.23. Thresholds must match engine carry.
- **"Raising the flat runner-on-3rd ground-out rate to 0.50 fixes RE for runners on 1st and 3rd with 0 out."** It adds nothing measurable there. The 0-out DP case is the lever, and about 5-8% of the shortfall remains unexplained.
- **"Runs on inning-ending DPs inflate ERA."** They are charged unearned. Runs, W-L and game results are affected, ERA is not.
- **"5,230 tag-up chances in calibration."** That was 3 seeds; seed 1 has 1,847.
- **"Catcher fa only affects passed balls."** It also moves CS% and steal attempts.
- **"Lineup autofill produces ineligible starters" (refuted in the first pass).** Partly restored:
  - Auto-fill prefers an eligible player when the active roster has one.
  - When it does not, the fallback picks the best bat and cascades players across positions, even to catcher.
  - The live path rewrites invalid lineups this way, and the root cause is ACT rosters missing positions.
- **"Out-of-position starters correlate r +0.81 with unearned runs."** That came from stale fixed lineups. On the live path r is +0.12, though the controlled A/B does confirm about 0.2 R/G per OOP starter.
- **"Per-fielder luck is 7-13 runs a season."** That included attribution-model error. Pure binomial luck is ~8-10 runs at 2B/SS/LF/CF/RF and ~3-4 at 1B/3B.
- **"RF glove is worth 2.5x SS glove."** For range alone. Counting errors and DPs it is about 1.75x. Still every OF slot outranks SS.
- **"Use the existing `range_scale` knob below 1 to fix the range slope."** It multiplies the raw rating, not the deviation, so it would raise league BABIP.
- **"Flipping `_spray_dir` fixes the LHB fielder credit."** It fixes the credit mismatch only; the hand-blind spray (RHB pull inverted, shift term reversed) remains.

### League, team, data and display

- **"Hitter `vl` hurts hitters" (map-batting item).** Within each batting hand, vl lowers K; the pooled slope is a handedness confound.
- **"LHP share is the dominant team run-prevention driver."** It explains about 6-27% of true RA variance, not most of it.
- **"There is no home-field advantage."** There is a small one: +1.1 pp (95% CI +0.3 to +1.9) pooled over 14,502 games, still well below MLB's ~3-4 pp.
- **"Save conversion is 0.027 below MLB."** R0's 0.613 was in the top third of replicates; the mean is 0.598 ± 0.015, about 0.04 below.
- **"Persistent runs score more because tired starters stay in."** Starters allow the same in both modes. The +0.15 R/G comes from relievers (RA9 4.93 vs 4.56).
- **"Rest-day logic lives in `utils/lineup_loader.py`."** It is in `physics_sim/engine.py:3360-3456`.
- **"Live contamination is already permanent."** Not yet: snapshots preserve both boundaries until season rollover.
- **"The eye formula is at `player_generator.py:1763`."** The default generation path uses `:296`/`:826` (0.6·ch + 0.4·sc); `:1763` is the 'arr' / fallback path.
- **"The 9-inning line-score bug affects 9-inning games."** Only extra-inning games are affected (all 77 of them).