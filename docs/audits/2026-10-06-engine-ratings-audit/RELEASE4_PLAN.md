# Release 4 implementation plan: the running game

Audit: `docs/audits/2026-10-06-engine-ratings-audit` (REPORT.md "Release 4", H2, M6, M7, M8, M10, L21; running_defense.md; DECISIONS.md 1-3). Code base: 7.47.0. Every file:line below was re-located in the current code. The audit's line numbers predate 7.45.9 and no longer apply.

## 0. What changed from the audit's plan

1. **4b does not cost -0.3 R/G.** That figure came from a proxy that lowered `advancement_aggression_scale` 1.6 to 1.0 for every runner movement. This plan does not do that. Measured designs: XBT package +0.08 on calibration and -0.02 on calibration_league; tag-ups + ground outs + DP + productive outs +0.03 / +0.02; batter-speed terms +0.03 / +0.06. **4b as designed is about +0.05 to +0.15 R/G on calibration and about 0 on the league fixture.** Release 5 no longer has to absorb a large drop.
2. **Speed centring (decision 2) lets one steal curve fit both fixtures.** The attempt curve reads speed relative to the season's mean speed of active-roster (ACT) hitters: 47.7 on calibration, 54.4 on calibration_league, about 55 on alpha. With it, both fixtures land inside MLB's .73 ± .12 SB per team-game (.634-.639 and .753-.769). The harness scout's conflict over which fixture should carry the steal-volume gate goes away.
3. **Three bugs the audit did not list (M10 area):**
   - A batter reaches on a dropped third strike even when first base was occupied with fewer than 2 outs, because eligibility is checked after the runners move: .019-.023 illegal reaches per team-game.
   - A swinging-K reach never registers `runner_pitchers`, so if that batter later scores after a pitching change, the run is charged to the reliever.
   - Every missed pitch is recorded as a WP or PB, even when nobody moves.
4. **Two more rules bugs:**
   - 24-27% of all SB/CS events happen on foul balls.
   - A double steal can produce two outs (81-107 per season).
5. **calibration_league already fails the strict triples gate** (.224 / .216 against a .22 ceiling). The triples reshape (4a) fixes it without moving runs.

## 1. Baseline (7.47.0, PYTHONHASHSEED=0, 162 games × 30 teams)

Sources: the orchestrator's baseline JSONs plus instrumented drivers that draw no extra random numbers and reproduce those JSONs exactly.

| Metric | MLB target | cal s1 | cal s2 | league s1 | league s2 | Gate today |
|---|---|---|---|---|---|---|
| R/G | 4.47 ± .25 | 4.308 | 4.348 | 4.105 | 4.057 | strict (league fails) |
| SBA/PA | .025 | .0500 | .0496 | .0602 | .0596 | report-only |
| SB per team-game | .73 (2024: .745) | 1.419 | 1.400 | 1.755 | 1.729 | report-only |
| SB% | .78 ± .05 (2024: .790) | .751 | .746 | .776 | .775 | strict |
| CS per team-game | .198 | .470 | .477 | .506 | .503 | none |
| Share of SB/CS events on foul pitches | 0 | 24-27% | | | | none |
| Double-steal outs per season | ≤1 per play | 81-107 | | | | none |
| WP per team-game | ~.33 | .492 | .491 | .543 | .518 | none |
| PB per team-game | ~.05 | .335 | .333 | .344 | .345 | none |
| K reaches (dropped 3rd strike) per team-game | ~.06 (approx.) | .153 | .153 | .163 | .171 | none |
| XBT | .40 | .688 | .688 | .734 | .734 | report-only |
| Thrown out per XBT opportunity | ~.025 | .113 | .108 | .095 | .094 | none |
| 1st to 3rd on a single | ~.28 | .748 | .748 | .787 | .783 | none |
| SF/PA | .0067 | .0098 | .0100 | .0097 | .0096 | none |
| Tag-up from 3rd: score / out / hold | ~.75-.80 / .02-.04 / rest | .95 / .05 / 0 at every speed and arm | | | | none |
| GIDP per team-game | ~.68 | .569 | .546 | .486 | .486 | none |
| GIDP per opportunity | ~.105 | .0735 | .0712 | .0653 | .0659 | none |
| DP per ball in play (`bip_double_play_pct`) | .028 ± .01 | .0222 | .0213 | .0199 | .0200 | strict |
| GIDP/opp, fastest ÷ slowest quintile | ~.5 | 1.09 | 1.06 | 1.01 | .99 | none |
| 3B per team-game | .14 ± .08 | .142 | .145 | **.224** | .216 | strict |
| 2B per team-game | 1.63 ± .25 | 1.712 | 1.710 | 1.628 | 1.591 | strict |
| BABIP | .291 ± .015 | .2803 | .2783 | .2752 | .2725 | strict |
| r(sp, BABIP), hitters with 300+ PA | > 0 (fast +.02-.03) | -.156 | -.124 | -.068 | -.074 | none |
| RE24 runners on 1st and 3rd, 0 out | 1.784 | 1.583 | 1.549 | 1.581 | 1.605 | report-only |
| P(score) runners on 1st and 3rd, 0 out | .866 | .806 | .790 | .786 | .804 | report-only |
| Strict failures | | 0 | 0 | 11 | 13 | |

The calibration_league failures are all offence or platoon/TTO gates (P/PA, BABIP, AVG, ISO, R/G, H, HR, 3B, HR30, platoon, TTO). None come from the running game except triples.

Speed populations:

| Population | Mean sp | Share at 70+ | Share at 85+ | Max |
|---|---|---|---|---|
| calibration ACT | 47.7 | 0 | 0 | 67 |
| calibration_league ACT | 54.4 | 19% (24% of PA) | 3.8% (5% of PA) | — |
| alpha ACT | ~55 | 22% | — | — |

**data/calibration cannot test the 70/85 tiers.** It is the regression fixture. calibration_league is the tier fixture.

## 2. Rules that resolve the conflicts between scouts

1. **One speed centre.** A new `services/league_rating_centers.py` is the single source:
   - `active_hitter_mean_speed(base)` and `league_hitter_speed_center(data_dir, season)`;
   - the mean is over ACT non-pitchers (`utils.roster_rules.counts_as_pitcher`), computed once per season;
   - it is cached in `<league>/rating_centers.json` plus a process cache, following the `services/injury_settings.py:142` durability-centre pattern;
   - `get_rating_center_overrides()` exposes it.
   
   One tuning key, `hitter_speed_center` (default 50.0), replaces the scouts' `steal_speed_center`, `batter_speed_center` and the DP "centre 55". The two scouts' module names (`rating_means.py`, `league_rating_centers.py`) are merged into this one module.
2. **Which speed terms are centred.** The audit plan makes the new frequency terms league-relative, and decision 2 sets the direction:
   - **Centred:** terms added to a league-calibrated rate whose league mean must not move. These are the steal attempt factor, the infield-hit term, the batter-speed DP term and the new ground-out R3 speed term.
   - **Raw (`sp - 50`), for now:** terms that model a race against a throw. These are steal success, tag-up timing, `_advance_prob` (XBT and WP advances), the triple threshold and the D3K reach chance.
   - When the general decision-2 re-centring lands, the raw terms move together with arm, fa and hold, and their tier tables are re-checked.
   - This is an implementation scope choice, not an owner question.
3. **`_advance_prob` keeps its global meaning.**
   - It gets an optional `scale: float | None = None`. With None it uses `advancement_aggression_scale` 1.6, as today.
   - Hit advances pass `hit_advance_aggression_scale`. The R2 tag-up passes `tag_up_second_scale` (1.6).
   - WP/PB advances and the ground-out fielder's-choice branch are never edited.
   - The global scale is never cut. That cut was the source of the -0.3 R/G.
4. **One DP function and one owner (W3).**
   - Use M6's multiplicative batter-speed factor `exp(-k·(sp_batter - centre)/10)` with k 0.20 and the cap as a knob (`double_play_max` 0.60).
   - The centre is `hitter_speed_center`, the league ACT mean per decision 2. The tag-up scout's additive term centred at 55 is dropped.
   - `double_play_base` 0.38, not 0.40. The 4a steal cut adds about +.04 GIDP per team-game: the tag-up/DP package measured .668 at 0.40 without the cut and .705-.717 with it. The base is finalised after 4a lands, with GIDP per team-game .68 as the target.
5. **One owner for the per-pitch runner block (W1).**
   - Order: balk → missed pitch → pickoff → steal.
   - A shared `live_pitch = res.outcome != "foul"` flag gates the missed pitch and the steal. Balk and pickoff may still roll after a foul.
   - The read-only `event_bases` logging goes into the same edit.
6. **One "infield hit" concept, owned by W2.** The M6 infield-hit term and the L21 infield-single subset (runners move one base, infielder's arm, infielder gets the credit) share one EV threshold knob.
7. **4b lands as knobs with legacy defaults plus two structural switches** (`tag_up_model`, `ground_out_model`; 0 = 7.47.0 code path).
   - The 4b values live in a checked-in profile, `scripts/kpi_profiles/r4b.json`.
   - Flipping 4b means copying the profile into DEFAULT_TUNING.
   - There is no master switch threaded through every function.
8. **Gate edits belong only to W4.** Items add metrics and reference rows (report-only). Only W4 edits `DEFAULT_TOLERANCES`, `STRICT_EXTRAS_TARGETS`, `REPORT_ONLY_TOLERANCES` and `.github/workflows/physics_sim_kpi.yml`.
9. **Every new knob is registered in `physics_sim/config.py` DEFAULT_TUNING.** Each item adds a `from_overrides` round-trip test. `--tuning-overrides` rejects unknown keys, because `TuningConfig.from_overrides` silently drops unregistered keys.
10. **4a changes the RNG draw stream** (fewer steal and WP rolls). Seeded tests pinned to exact box scores get re-baselined, not "fixed".

## 3. Areas

### A. Stolen bases (H2): 4a

**Current code (engine.py):**
- `_steal_attempt_rate` 2686-2706: speed term `0.5+(sp-50)/60` with linear deterrents.
- `_steal_context_multiplier` 2709-2737.
- `_steal_success_prob` 2740-2759: `0.80+(sp-50)/150 - …`, clamped to [.10, .95], so it saturates at sp 72.5.
- `_attempt_steal` 2762-2927. Home 2788-2821; double steal 2823-2862 (rate .003 × freq with no speed, hold or catcher term, and two independent throws); R2 to 3rd 2864-2893; R1 to 2nd 2895-2927.
- `_pickoff_caught_stealing` 2643-2683 calls the attempt rate only to label a pickoff as POCS.
- Call site: the `else:` steal branch at ~6500 inside the `res.outcome in {ball, strike, swinging_strike, foul}` block that starts at 6376.

**Current knobs (config.py):** 275-293 (first .045, second .015, home .002, double_steal_rate .003, success .80, deterrent scales); 508 `steal_freq_scale` 3.0. The `lead_*` knobs (294-299) are cosmetic and only feed the `lead` stat.

**Slider:** `services/physics_tuning_spec.py:264-272` (range 1.0-5.0). No in-game steal strategy exists for CPU or owner clubs; the legacy OffensiveManager is dead code for the physics engine.

**Design, "E1":**
1. **No steals on fouls.** The steal `else:` becomes `elif live_pitch:`.
2. **Attempt curve.**
   - `_steal_speed_factor(sp, tuning)` uses `x = sp - hitter_speed_center + 50` and `c(x) = 1/(1+e^{-(x-mid)/width})`, with mid 75 and width 12. It returns `c(x)/c(50)`, which is 1.0 at the centre.
   - Values: 0.46 at 40, 1.0 at 50, 2.0 at 60, 3.6 at 70, 6.3 at 85, 7.95 at 99.
   - It replaces the linear speed term. The deterrents and the context multiplier are unchanged.
   - Rebase so that 1.0 = MLB:
     - `steal_freq_scale` 3.0 → **1.0**;
     - first .045 → **.0315**;
     - second .015 → **.0070**;
     - home .002 → **.0007**;
     - `double_steal_rate` .003 → **.0021**.
   - Slider range becomes 0.25-3.0.
3. **Saturating success (raw speed).** p = sigmoid of a logit:

   ```
   logit = 1.50 + .30·(sp-50)/10 − .21·(hold-50)/10
           − .17·(p_arm-50)/10 − .24·(c_arm-50)/10 − .19·(c_fa-50)/10
   ```

   - Clamp to [.05, .97]. The existing pitcher-arm and catcher-fielding success scales stay as multipliers on their slopes.
   - With neutral defence: .82 at sp 50, .89 at 70, .93 at 85.
   - `steal_home_success_scale` .6 is kept. `steal_success_base` is retired but stays registered so stored overrides are not rejected.
4. **Double steal.**
   - The attempt uses `_steal_attempt_rate(speed=R2.speed, base_rate=double_steal_rate)` × context.
   - There is one throw, to 3rd, using R2's success probability.
     - Safe: `sb3` + `sb2`.
     - Out: `cs3`, and R1 takes 2nd as `adv2` with no SB credited (rule 9.07(d)).
   - At most one out.
5. **Unchanged:** pickoffs (about .007 per team-game), the POCS label, the `lead_*` knobs (documented as cosmetic), and pitcher arm as a hold factor.
6. **Slider migration.**
   - Divide any stored `steal_freq_scale` override in `physics_tuning_overrides.json` by 3, once, with an idempotent marker key.
   - Update the slider's help text.

**Per-tier results (E1, seeds 1-2).** att/opp = attempts per time on first (1B+BB+HBP). On calibration_league, centred speed = raw − 4.4.

| Raw speed tier | league att/opp | league SB% | cal att/opp | cal SB% | league qualified SB per season |
|---|---|---|---|---|---|
| <40 | .020 | .58-.68 | .033 | .64-.66 | 2.8 (<45) |
| 40-46 | .031-.034 | .68 | .051-.055 | .72-.75 | |
| 47-53 ("50") | .055 | .72-.74 | .086-.092 | .75-.76 | 6.0 (45-55) |
| 54-61 | .103 | .77-.80 | .14-.15 | .76-.78 | 14.2 (56-67) |
| 62-67 | .148 | .80-.81 | .17-.20 | .79-.82 | |
| 68-77 ("fast 70") | .20-.21 | .82-.84 | — | — | 23.8 (9-42), 5.0 CS |
| 78-89 ("burner 85") | .353 | .87-.88 | — | — | 44.7 (30-64) |
| 90+ | .42 | .89-.90 | — | — | 52.6 |

Season shape on calibration_league:
- Leader 67-68.
- 11-13 players with 40+ SB, 23-24 with 30+.

For comparison, MLB:
- League att/opp .099-.107.
- Elite base stealers .35-.50 att/opp at 85-90% success.
- Leaders 59-73.
- 4-8 players with 40+ SB.

Legacy engine: a "50" attempted .21 per time on first, leaders reached 71-77, and 46-56 players had 40+ SB.

**Verification.**

Unit tests, in a new `tests/test_physics_sim_steals_r4.py`:
- Speed factor:
  - equals 1.0 at the centre and is strictly increasing;
  - f(70)/f(50) is in [3, 4.2] and f(85)/f(50) in [5.5, 7];
  - f(99) < 8.5;
  - with centre 54, f(54) = 1.
- Success probability:
  - monotone in speed;
  - p(85)−p(70) < p(70)−p(50);
  - never above the cap;
  - each deterrent lowers it;
  - all ratings at 50 gives .80-.84.
- Double steal, with forced draws: `[(R2,"cs3"),(R1,"adv2")]`, 1 out, old R1 on 2nd; success gives sb3+sb2 with 0 outs.
- A seeded 20-game run has no foul pitch with an sb/cs event.
- Knob registration.
- Slider spec includes 1.0.
- Migration divides once.
- `adv2` is never counted as an SB by the box score, season_stats or the play-by-play text.

KPI targets (E1 measured in brackets):

| Metric | Target | calibration s1/s2 | calibration_league s1/s2 |
|---|---|---|---|
| sba_per_pa | .025 ± .005 | .0221 / .0220 | .0253 / .0249 |
| sb_per_team_game | .73 ± .12 | .639 / .634 | .769 / .753 |
| sb_pct | .78 ± .05 | .759 / .758 | .805 / .802 |
| CS per team-game | ~.20 | .203 / .202 | .187 / .186 |
| steal-of-3rd share | ~.11 | .12 | .12 |
| r(sp, att/opp) at player level | ≥ .6 | | |

Margin note: calibration's SB/G margin is only .024. Scaling all four base rates by ×1.04 (first .033) centres both fixtures: cal ≈ .66, league ≈ .80. W1 confirms this on seeds 1-4.

Effect: R/G +.03 to +.08 (CS/G falls from .48 to .20).

### B. Wild pitches, passed balls, dropped third strike (M10): 4a

**Current code (engine.py):**
- `_advance_on_missed_pitch` 2928-2958. It returns no "did anyone move" flag.
- `_missed_pitch_type` 2961-2993.
- `_resolve_dropped_third_strike` 2996-3041. Eligibility is checked after the runners move (bug a). An eligible batter always reaches.
- Called-K branch 5647-5714 and swinging-K branch 5715-5768. They duplicate the bookkeeping, and the swinging-K branch is missing the `runner_pitchers` registration (bug b).
- Per-pitch block 6376-6420. The balk is inside the runners-on guard (6391); the missed-pitch roll at 6401-6420 is outside it, so it fires with the bases empty and on fouls.

**Current knobs:** config.py 300-303.

**Design, "F" with WP base .0097:**
1. **Gate the per-pitch roll.** Move it inside the runners-on guard and require `live_pitch`.
2. **Shared rate helper.** `_missed_pitch_rates(ctl, cfa, miss, tuning) -> (wp, pb)`:

   ```
   wp = wild_pitch_rate · e^((50-ctl)/40) · e^((50-cfa)/80) · (1+miss)
   pb = passed_ball_rate · e^((50-cfa)/25) · (1+miss)
   ```

   - Ratings clipped to [20, 95]; each rate capped at .05.
   - New values: `wild_pitch_rate` .0035 → **.0097**, `passed_ball_rate` .0025 → **.00155**.
   - New knobs: `wild_pitch_control_k` 40, `wild_pitch_block_k` 80, `passed_ball_fa_k` 25, `missed_pitch_rate_cap` .05.
3. **Record only when something advances (MLB rule 9.13).** `_advance_on_missed_pitch` also returns the bases advanced. When nothing moves, the ball counts as blocked: no stat, no runner_event, and the pickoff and steal rolls proceed as normal.
4. **Dropped third strike.**
   - `eligible = first is None or outs >= 2`, evaluated before runners move.
   - `k_rate = k_in_dirt_rate (.02 → .0112) · (1+miss) · e^((50-ctl)/40) · e^((50-cfa)/60)`.
   - WP vs PB is chosen in proportion to the shared rates.
   - An eligible batter reaches with `clamp(.85 + (sp-50)/200 − (c_arm-50)/300, .5, .98)`.
   - Record a WP/PB only if the batter reached or a runner moved.
5. **Fold the called-K and swinging-K branches into one strikeout-finisher closure.** Both paths then run `_reconcile_runner_pitchers` and `runner_pitchers[batter] = line` on a reach (fixes bug b).
6. **Logging.** Stamp `k_reached` on D3K reaches. Add `event_bases`, the bases captured before the event, on every entry with a runner_event.

**Rating tiers (pooled, per 1000 live pitches with runners on):**

| Rating | Tier | New | 7.47.0 |
|---|---|---|---|
| Pitcher control (WP) | ≤45 | 9.58 | — |
| | 46-50 | 7.84 | — |
| | 51-55 | 7.25 | — |
| | 56+ | 6.60 | — |
| | ratio ≤45 / 56+ | 1.45x | 1.09x |
| Catcher fa (PB) | ≤47 | 2.06 | — |
| | 48-55 | 1.28 | — |
| | 56-62 | 0.98 | — |
| | 63+ | 0.73 | — |
| | ratio ≤47 / 63+ | 2.8x | 1.2x |

D3K batter reach when eligible: .83 at sp 50, .93 at 70, .98 at 85. K reaches per 600-PA regular fall from ~2.5 at every speed to ~0.75-0.9.

**Verification.** Unit tests in a new `tests/test_missed_pitch_wp_pb.py`:
- Bases empty, and a foul with runners on: no event and no RNG drawn.
- Blocked ball: no stat, and pickoff/steal still evaluated.
- D3K with R1 and 1 out: never reaches. With 2 outs or 1st base open: reaches with probability p.
- K-reach probability is monotone in speed.
- Rate helper: wp(ctl 30)/wp(ctl 70) = e and pb(fa 30)/pb(fa 70) = e^1.6.
- Swinging-K reach: the run is charged to the original pitcher.
- Knob registration.

KPI targets (F measured on calibration seeds 1-3):

| Metric | Target | Measured |
|---|---|---|
| WP per team-game | .33 ± .04 | .298 / .330 / .317 at wp_base .0093; the .0097 default adds ~4% |
| PB per team-game | .05 ± .02 | .052 / .044 / .053 |
| K reach per team-game | .045-.08 | .053-.059 |
| WP/PB with bases empty, on fouls, illegal K reaches | 0 | 0 |
| Bases advanced on missed pitches | within ±10% of baseline | .401 vs .383 |
| corr(pitcher control, WP/9) | < -.15 | |
| corr(catcher fa, PB/G) | < -.4 | |

Effect: R/G -0.02 to -0.04, all of it from about 0.10 fewer K reaches per team-game. The rest is neutral.

### C. Runner advancement on hits, L21, triples, XBT: 4a (L21, plumbing, triples) and 4b (XBT constants, infield singles)

**Current code:**
- engine.py:
  - `_advance_prob` 1958-1961 (W0 adds `scale=`).
  - `_out_on_base_prob` 1964-1971: forced runners still face the out roll, 5-8% thrown out.
  - `_attempt_extra_base` 1982-2003.
  - `_advance_on_hit` 2006-2190: hard-coded situation extras and no `outs` input. Also called from HR 5812, bunt hit 3605 and `_advance_on_error` 2388-2401.
  - `_maybe_upgrade_hit` 2193-2221.
  - `_credit_outs_on_base` 2224-2257 and `_credit_throw_error` 2363-2386: both re-derive "gb means infielder".
- **L21 is still present:** the hit path sets `advance_infield = ball_type == "gb"` at 5855-5895, and `apply_advance_errors(infield_play=…)` at 5945 (closure at 5072). 37-38% of hit-advance rolls use an infielder's arm.
- physics.py 1060-1084: the triple threshold is linear and symmetric in speed. It is impossible to triple below sp ~37, and the threshold is 0.75 × wall at sp 85.

**4a design:**
- **A1, L21 routing.**
  - `_hit_advance_position(spray, side, tuning, infield_hit=False)` returns the outfielder from `_outfield_pos_for_spray(_spray_dir(...))`. It returns an infielder only when `infield_hit` is set.
  - The hit path passes the resolved position into `_credit_outs_on_base` and `apply_advance_errors` through a new optional `fielder_pos` kwarg. The default re-derives as today, so the ROE call site (6082) and the bunt-hit call sites (5359, 5368) are not edited.
- **A2, knob plumbing at legacy defaults.**

  | Knob | 4a default (= 7.47.0) | 4b value |
  |---|---|---|
  | `hit_advance_aggression_scale` | 1.6 | **1.0** |
  | `hit_advance_out_scale` | 1.0 | **0.45** |
  | `xbt_single_r1_extra` | .05 | **−.17** |
  | `xbt_single_r2_extra` | .15 | **.06** |
  | `xbt_double_r1_extra` | −.05 | **−.13** |
  | `xbt_two_out_extra` | 0 | **.22** |
  | `forced_runner_out_scale` | 1.0 | **.25** |

  `_advance_on_hit` gains `outs` and `infield_hit` kwargs.
- **A3, triples by tier, "T3".** Split the slope:
  - `triple_speed_scale` .28 → **.15**, now the slow side only;
  - new `triple_speed_scale_fast` **.12**; its default −1 means "inherit";
  - `stretch_triple_speed_scale` .12 → **.10**.
- **M6 hook, owned here.** `fielding.out_probability(…, batter_speed=None)`, at 165-240, adds an EV-ramped ground-ball infield-hit term:

  ```
  out_prob -= infield_hit_speed_scale · w · (sp − hitter_speed_center)/10
  w = clamp((ev_hi − EV)/(ev_hi − ev_lo), 0, 1)   # ev_lo 80, ev_hi 100
  ```

  - The scale is 0 in 4a.
  - The call site at 5836-5847 passes the fatigue-scaled `batter.speed`.
  - No new random draws, so seeded games stay byte-identical at scale 0.

**4b design:**
- The XBT constants in the A2 table.
- `infield_hit_speed_scale` .04 ("candC").
- An infield-single subset: `infield_single_ev_max`, default 0 = off, candidate 85 mph. Runners move exactly one base, using the infielder's arm and credit. The bunt-hit path passes `infield_hit=True`. **This piece is unmeasured**, and it lowers XBT further below F3's .38-.43. Measure it with the profile; drop it from the profile if XBT falls below .37.

**Per-tier results, calibration_league:**

| SP tier | XBT 7.47.0 → 4b | Thrown out per opportunity | 3B/PA 7.47.0 → T3 | MLB 3B/PA |
|---|---|---|---|---|
| <40 | .54 → .30 | .13 → .043 | .0001 → .0013 | ~.001 |
| 40-49 | .64 → .36 | | .0024 → .0029 | |
| 50-59 | .73 → .42 | .10 → .020 | .0046 → .0041 | ~.0035 |
| 60-69 | .80 → .47 | | .0078 → .0056 | |
| 70-84 | .85 → .51 | .058 → .013 | .0113 → .0066 | ~.007 |
| 85+ | .93 → .61 | .017 → .012 | .0185 → .0100 | .012-.016 |

By situation under 4b:

| Situation | 4b | MLB |
|---|---|---|
| 1st to 3rd on a single | .29 | ~.28 |
| R2 scores on a single | .62 (0-1 out .54, 2 out .74) | ~.60 |
| R1 scores on a double | .40 | ~.40-.45 |
| Forced R3 on a single / R2 on a double | .995 / .993 | ~.99 |

Other effects:
- OF arm: r(arm, taken) about −.08, and r(arm, out | attempt) about +.08.
- League 3B per team-game .22 → .17. League 2B per team-game 1.61 → 1.69.

**Verification.** Unit tests in a new `tests/test_hit_advancement_r4.py`:
- A GB single uses the outfielder's arm (infield arms 90, OF arms 20), and the oobH assist and e_th error go to that outfielder.
- Default knobs reproduce a frozen copy of the 7.47.0 `_advance_on_hit` over 2,000 random base states.
- 4b Monte Carlo bands:
  - 1st-to-3rd .25-.33;
  - R2 scores .55-.66, with the 2-out rate at least .15 above the 0-out rate;
  - R1 scores on a double .36-.46;
  - thrown out per opportunity .01-.04;
  - forced R3 scores ≥ .99.
- Monotone in speed and arm, and no saturation at sp 50.
- Triple-threshold tier ratios: SP70/SP50 ≤ 2.0 and SP85/SP50 ≤ 2.6.
- `out_probability` is unchanged at the centre or with speed None, and 0.12 lower at EV 80 with sp centre+30 and scale .04.
- Knob registration.

KPI targets:
- 4a: XBT .688 ± .01; cal 3B/G .12-.16 (T3 .140 / .149); league 3B/G ≤ .19 (T3 .169 / .170).
- 4b: XBT .40 ± .05 (F3 cal .381-.388, league .426-.432); thrown-out rate .015-.035.

Effects:

| Change | R/G | Note |
|---|---|---|
| L21 | cal +.017 / +.010; league +.020 / +.076 | noise |
| T3 | ~0 | |
| 4b XBT package (F3) | cal +.077 (4 seeds); league −.022 | the outs saved on the bases offset the extra bases not taken |

### D. Batter speed: infield hits and GIDP (M6): 4a plumbing, 4b values

The infield-hit half belongs to area C (W2) and the DP half to area E (W3). This section only carries M6's targets.

**Today:**
- `out_probability` and `double_play_probability` (fielding.py 243-258) take no batter speed.
- The DP call is at engine.py 3124-3129 and passes only R1's speed.
- Speed has no effect on outcomes: partial BABIP is ≈ −.003 to 0 per 10 sp, and the GIDP quintile ratio is ~1.0.

**Values ("candC", 4b):**
- infield-hit scale .04 with the EV ramp 80-100;
- `double_play_batter_speed_k` .20;
- `double_play_max` .60;
- `double_play_base` .38.

**Per-tier results, calibration_league (3 seeds pooled; DP base .38 alone → candC):**

| Batter speed | BABIP | GB-hit rate | GIDP/opp |
|---|---|---|---|
| <40 | .288 → .265 | .180 → .138 | .072 → .109 |
| 48-52 ("50") | .288 → .285 | .183 → .178 | .079 → .086 |
| 70-79 ("70") | .284 → .296 | .180 → .214 | .075 → .051 |
| 80+ ("85") | .283 → .312 | .186 → .255 | .072 → .033 |
| League | .2850 → .2862 | | .0752 → .0758 |

Across quintiles: fastest minus slowest BABIP +.026 (MLB +.020-.030), and fastest ÷ slowest GIDP/opp .46 (MLB ~.5).

**Targets:**
- calibration_league:
  - r(sp, BABIP) ≥ .20 (.25-.41 measured);
  - BABIP slope +.006 to +.010 per 10 sp;
  - fastest ÷ slowest GIDP/opp .40-.60.
- calibration:
  - BABIP slope ≥ +.003 per 10 sp (+.0045 measured);
  - fastest ÷ slowest GIDP/opp ≤ .80 (.67).
- Neutrality: BABIP change ≤ +.003, and GIDP per team-game within ±.02.

**Audit verify item not met:** "r(sp, BABIP) > .15 on both fixtures" is not reachable on calibration (.06-.15 across seeds). That fixture has a built-in speed-power confound (r = −.26 among regulars) and no tiers. Gate the slope instead. Give the calibration fixture tiered speeds at its next rebuild (future_work).

Effect: R/G +.03 cal / +.06 league from the speed terms alone. This is because the ACT-hitter mean sits 1.6-2.4 sp below the PA-weighted mean speed. Release 5 absorbs it.

### E. Tag-ups, runner on 3rd on ground outs, double plays (M7, M8): 4b

**Current code:**
- `_advance_on_air_out` (engine.py 2404-2442):
  - one combined attempt-and-success roll at extra .25 × 1.6, which saturates at .95;
  - no hold outcome, so a failed roll is an out at home;
  - no distance, hang time or infield flag;
  - 12% of chances are infield-caught liners, which still score 92-97% of the time.
- Air-out call site 6270-6366: e_th at 6309-6331, OF assist plus C putout at 6343-6352, SF at 6353-6361.
- `_resolve_ground_out` 3044-3160:
  - R3 rolls a flat .25 before the DP decision, so R3 scores only 26-33% on 0-out DPs;
  - with the bases loaded, R3 is not forced home;
  - a forced R1 can hold;
  - R2 never advances on a ground out.
- Ground-out call site ~6114.
- The L15 fix (no run on an inning-ending DP) is intact at 3115-3140.

**Design, "rec" with the DP changes from rule 4 above:**

1. **Tag-up from 3rd.**
   - New signature: `_advance_on_air_out(…, distance, exit_velo, launch_angle, ball_type, infield_play)`.
   - Infield-caught liners: R3 and R2 hold, and no random number is drawn.
   - Time race, using drag-free hang time:

     ```
     t_run   = 3.55 − (sp−50)·.012
     v       = 110 + (arm−50)·1.0
     t_throw = 2.0 + dist·1.2/v − .15·max(0, 3.0 − hang)
     margin  = t_throw − t_run
     p_send  = Φ((margin − .20 − .10·[outs==0]) / .25)
     p_out | send = max(.005, Φ(−margin/.30))
     ```

   - The R2 tag to 3rd keeps its roll but uses `tag_up_second_scale` 1.6, and skips infield liners.
   - All of this sits behind `tag_up_model`.
2. **Tag-up throw-outs are DPs.**
   - New runner_event token `tag_dp`, not `dp`, so GIDP-per-opportunity is unaffected.
   - `totals["dp_air"]`; the fielder gets a+dp, the catcher po+dp; no batter GIDP.
3. **Ground outs (`ground_out_model`).** Order: triple play, then DP, then R3.
   - **DP turned:**
     - 0 out: R3 scores .90 + (sp−50)/400.
     - 1 out: no run (L15).
   - **No DP, bases loaded:** R3 is forced and scores, unless the defence plays at home. That happens with .50 when the infield is in and .05 when it is back; a play at home is a fielder's choice with a C putout and an assist.
   - **No DP, otherwise:** R3 scores with .45 (0 out) or .55 (1 out), −.25 with the infield in, + .004 × (centred sp − 50).
   - **Infield in** means inning ≥ 7, fewer than 2 outs, and the fielding team tied or ahead by up to 2 (`infield_in_min_inning`, `infield_in_max_lead`).
   - **Forced runners always advance.** The `_advance_prob` roll for R1 is deleted.
   - **Productive out:** an unforced R2 with 3rd open advances with .75 on balls fielded by 1B/2B and .35 on balls to the left side, + (sp−50)/250.
4. **DP.** `double_play_probability(…, batter_speed=None)` uses the multiplicative factor, `double_play_max` .60 and `double_play_base` .38 (rule 4 in section 2).
5. **Logging.**
   - `tag3`/`tag2` records: runner, fielder, position, arm, infield flag, result.
   - `go3` record: runner, scored, dp.

**Tag-up results ("rec", calibration_league seed 1; score / hold / out):**

| SP tier | 4b | 7.47.0 |
|---|---|---|
| <45 | .66 / .30 / .04 | .92-.95 / 0 / .05-.08 |
| 45-59 | .74 / .24 / .03 | same |
| 60-74 | .78 / .19 / .03 | same |
| 75+ | .84 / .13 / .03 | same |

- By arm: <45 scores .83, 45-55 .77, 55+ .68.
- By depth (sp 50, arm 50): sent .33 at 150 ft engine carry, .74 at 175, .96 at 200, about 1.0 at 225+.

**Share of R3 scoring on ground outs (cal):** 3rd only, 0 out .31 → .46; 1st and 3rd, 0 out .28 → .59; bases loaded, 0 out .16 → .92; bases loaded, 1 out .16 → .48.

**Verification.**

Unit tests: new `tests/test_r4_tagups_ground_outs.py`, plus a rewrite of `tests/test_physics_sim_rules.py` at 102-118 (draw order) and 132-140 (R1 holds). The conservation test at 142-163 and the L15 tests must pass unchanged.
- An infield liner holds and consumes no draw.
- Hold, score and out outcomes by stubbed draws.
- p_send rises with depth: ≤ .15 at 120 ft, score ≥ .99 at 300 ft.
- At 175 ft: p_send(sp 85) − p_send(sp 50) ≥ .20, and p_send(arm 65) ≤ p_send(arm 50) − .25.
- `tag_dp` credits; kpi_extras does not count it as a GIDP.
- 0-out DP scores and 1-out DP does not.
- Draw order: triple play, DP, R3.
- Bases loaded: R3 forced home; the infield-in fielder's choice at home.
- R1 is never left on 1st.
- R2 advances at .75 / .35.
- `batter_speed=None` reproduces the old DP value.
- With both switches at 0, seeded games are byte-identical to main before W3.

KPI targets on calibration seeds 1-4 (measured in brackets):

| Metric | Target | Measured |
|---|---|---|
| SF/PA | .0068 ± .0010 | .0067-.0071 |
| GIDP per team-game | .68 ± .06 | recsteal at base .40: .705-.717, so .38 is expected to give ~.68 |
| Tag-up score rate | .72-.78 | |
| Thrown out per send | .02-.04 | |
| r(tag, arm) | ≤ −.08 | |
| r(tag, sp) | ≥ +.07 | |
| RE24 3rd only, 0 out / 1 out; 1st and 3rd, 1 out (pooled over 4 seeds) | within ±5% | met |

**Audit verify item not met:** RE24 for runners on 1st and 3rd with 0 out stays about 9-11% low. Nothing in this area explains it. It needs a transition-matrix diagnostic (future_work) and stays report-only.

Effect, per component on calibration:

| Component | R/G |
|---|---|
| Tag-up model | −.085 |
| Ground-out rewrite | +.088 |
| DP base | −.05 |
| Productive outs | +.07 |
| Package | +.03 cal / +.02 league |

### F. Measurement, logging and gates (cross-cutting)

The harness work itself draws no random numbers.
- `scripts/physics_sim_season_kpis.py`:
  - `run_sim` (~1093) computes the fixture centre from its ACT hitters (cal 47.72, league 54.41), passes it as `hitter_speed_center`, and writes it to the JSON `meta`.
  - New `--tuning-overrides PATH`, which rejects keys that are not in DEFAULT_TUNING.
  - New `--gate-set NAME`, which limits `--strict` to a named key list. `GATE_SETS["running"]` lets calibration_league gate the running game while its offence gates stay report-only.
  - `_running_metrics` adds cs_per_team_game, pickoffs_per_team_game, sba_per_tof, per-tier SBA/TOF and SB%, steal_tier_ratio, sb40_count and sb_leader.
- `scripts/kpi_extras.py`: `_load_players` also loads sp. Each item adds its own metrics: W1 the steal/WP rows, W2 the XBT/triples tier tables and the BABIP-speed coefficient, W3 the tag-up rows, GIDP by speed quintile and runprob for 3rd with fewer than 2 outs.

## 4. Parallel work split

Five items: W0 first, then W1, W2 and W3 in parallel worktrees, and W4 last.

| Item | Ships in | Owns (7.47.0 lines) | Provides / consumes |
|---|---|---|---|
| **W0 Foundation** (small; sequential, merges first) | 4a, run-neutral | `services/league_rating_centers.py` (new); `hitter_speed_center` key; engine.py `_advance_prob` 1958-1961 (optional `scale=`) plus a `_centred_speed(sp, tuning)` helper; game_runner.py 1287-1301 (write the centre last, like `extra_innings_runner`); api/ws/sim.py ~126 (route through `get_physics_tuning_overrides` + `get_injury_tuning_overrides` + `get_rating_center_overrides`); harness `run_sim` centre + meta, `--tuning-overrides`, `--gate-set` scaffolding; sp in `kpi_extras._load_players`; empty `scripts/kpi_profiles/r4b.json` | Provides the centre, `scale=`, the flags and sp. Tests: ACT-only mean, cached per season and stable across a batched/parallel day (compute in the parent before fan-out), None with no ACT hitters, the harness passes ≈47.7, unknown override key rejected, byte-identical games |
| **W1 Pitch events** (steals + WP/PB + K finisher) | 4a | engine.py 2541-2927 (pickoffs read-only; steal functions), 2928-3043 (missed pitch, D3K), 5647-5768 (K finisher fold), 6376-6575 (per-pitch block, `live_pitch`, `event_bases`); totals counters (4580-4600 area) for k_reach; config.py 275-303, 508, 516-522; physics_tuning_spec.py 264-272; physics_tuning_settings.py (migration); W1 kpi_extras metrics | Consumes the centre. Two commits in order: WP/PB + K finisher, then steals |
| **W2 Balls that fall for hits** | 4a (L21, plumbing, T3, M6 hook at 0) + 4b profile values | engine.py 1964-2257, 2363-2401, new `_hit_advance_position` next to 2504, bunt 3578-3615 + 5330-5372 (pass `infield_hit`), `apply_advance_errors` closure 5072-5100 (`fielder_pos` kwarg), HR and hit path 5800-5960 including the `out_probability` call 5836-5850; fielding.py `out_probability` 165-240; physics.py 1044-1084; config.py 316-327 + the new hit-advance block near 509; W2 kpi_extras tier tables | Consumes `scale=` and the centre. Fills the W2 part of the r4b profile |
| **W3 Outs in play** | 4b (switches default 0) | engine.py `_advance_on_air_out` 2404-2460 + new tag-up helpers, `_resolve_ground_out` 3044-3160, `dp_air` in totals, ground-out and air-out branches 6100-6366; fielding.py `double_play_probability` 243-258; config.py 271-274 + 509-515 (`double_play_base` stays .32 by default); tests/test_physics_sim_rules.py; optional `tag_dp` label in desktop/src/pages/LiveGamePage.tsx | Consumes the centre (DP and R3 terms) and `scale=` (R2 tag). Fills the W3 part of the r4b profile |
| **W4 Integration** (sequential, last) | 4a ship, then the 4b flip | `DEFAULT_TOLERANCES`, `STRICT_EXTRAS_TARGETS`, `REPORT_ONLY_TOLERANCES`, `GATE_SETS`; data/MLB_avg reference rows; `.github/workflows/physics_sim_kpi.yml`; VERSION + `.iss`; release_notes_draft; news post; docs/future_work.md; help text for the slider | Bundle KPI runs, then gate promotion |

**Not touched by anyone:**
- `_pa_start_context` 1777;
- `_tally_extra_bases_taken` 1819 (read-only);
- the lead functions 1881-1957;
- `_credit_ground_double_play` 2260 (reused by W3);
- `_catcher_context` 2461;
- the `select_out_type` call 5965;
- the error (ROE) branch 6030-6100, which relies on W2's backward-compatible defaults.

**Shared files:**
- `config.py`: each item appends its own knob block under a `# Release 4 (Wn)` header.
- `kpi_extras.py` and the harness: each item adds separate functions and keys in its own block. Conflicts are textual only.

**Merge order:** W0 → W2 → W1 → **4a bundle measurement and tuning (W4a)** → ship 4a → W3 → **4b profile measurement** → W4b (flip or hold).

Why the order is sequential:
- W0 must land first: W1, W2 and W3 all import its centre helper, and W2 and W3 call the `scale=` parameter.
- W2 goes before W1 because it adds no draws, so its legacy-equivalence tests run on an unchanged random stream.
- W3's final `double_play_base` depends on W1's steal volume (GIDP).
- The r4b profile has to be measured on top of W1 + W2.

W3 can be developed in parallel from W0 and rebased last.

## 5. Strict gate predictions (data/calibration seeds 1 and 2)

**4a** is W0 + W1 + W2 at 4a defaults. **4a+4b** adds the r4b profile. The pieces were measured separately (E1, F, L21, T3, F3, rec / recsteal, candC). **The combined bundle has not been run**; W4 must run it on seeds 1-4 before shipping.

| Gate (pass band) | Baseline s1 / s2 | 4a predicted | 4a+4b predicted | Basis and risk |
|---|---|---|---|---|
| runs_per_team_game (4.22-4.72) | 4.308 / 4.348 | 4.33-4.45 (mean +.04 to +.08) | 4.42-4.56 | E1 4.459 / 4.358; F 4.249 / 4.343; L21 +.01; T3 ~0; F3 +.08; rec +.03; candC ~0 vs base .40. Pass. Seed noise ±.05 |
| sb_pct (.73-.83) | .751 / .746 | .759 / .758 | same | Pass |
| **sba_per_pa** (new strict, .020-.030) | .050 / .0496 | .0221 / .0220 (≈.023 with ×1.04) | same | Pass. Thin margin without ×1.04 |
| **sb_per_team_game** (new strict, .61-.85) | 1.42 / 1.40 | .639 / .634 (≈.66 with ×1.04) | same | Pass. Apply ×1.04 |
| bip_double_play_pct (.018-.038) | .0222 / .0213 | ~.023-.024 (more runners stay on 1st) | .026-.028 | recsteal .0274-.0279 at base .40; candC .024-.026. Pass |
| babip (.276-.306) | .2803 / .2783 | .278-.281 | .280-.283 | Seed 2 margin .002 in 4a (RNG); 4b +.0017 helps. Watch |
| avg / obp / slg / hits | in band | ~unchanged | avg +.001 | Pass |
| iso (≥ .150) | .1542 / .1566 | ~same (cal triples barely move) | ~same | Seed 1 margin .004. Watch |
| ops (≤ .730) | .7187 / .7205 | .719-.727 (E1 .7273 / .7219) | .720-.731 | **Risk in 4b**: F3 s3 read .7306 |
| doubles (1.38-1.88) / triples (.06-.22) | 1.71 / .14 | 1.70-1.72 / .140-.149 | same | Pass |
| corr_avg_contact (≥ .40) | .441 / .430 | .43-.55 on measured pieces | .40-.51 | **Risk**: recsteal s2 read .397. Random-stream only |
| platoon_gap_woba (.017-.035) | .0334 / .0310 | .028-.033 | .025-.035 | **Risk**: recsteal s2 read .0350. Random-stream only |
| tto_ops_gap (.025-.075) | .0567 / .0529 | .044-.062 (E1) | similar | Pass. Seed-fragile |
| qualified dispersion and count gates; corr_hr_* | in band | unchanged | avg_sd .0255-.0269 | Pass |
| Plate-discipline, batted-ball and usage gates | in band | unchanged (no mechanism) | unchanged | Pass |
| runs_on_inning_ending_plays = 0 | 0 | 0 | 0 | W3 must keep L15 (tests) |
| **New zero gates**: steal_events_on_foul, wp_pb_on_foul, wp_pb_bases_empty (pitch path only, D3K excluded), double_steal_two_out_plays, illegal_k_reach | (2,227+, ~870, ~2,200, 81-107, ~46) | 0 by construction | 0 | STRICT_EXTRAS: a gate that was not computed fails |
| **wp_per_team_game** (new strict, .25-.41) | .49 | .31-.34 | same | |
| **pb_per_team_game** (new strict, .02-.08) | .33 | .045-.055 | same | |
| **sf_per_pa** (4b strict, .0058-.0078) | .0098 / .0100 | unchanged | .0065-.0071 | Pass |
| **gidp_per_team_game** (4b strict, .62-.74) | .569 / .546 | ~.60 | .66-.70 at base .38 | Pass |
| **extra_base_advance_rate** (4b strict, .35-.45) | .688 | .688 | .381-.388 (F3) | Infield singles may lower it. Measure |

**calibration_league in CI.** Add a strict `--gate-set running` step that checks:
- sb_pct, sba_per_pa, sb_per_team_game;
- the zero gates;
- wp and pb;
- triples_per_team_game.

E1 and T3 values: .805 / .802; .0253 / .0249; .769 / .753; 3B .169 / .170. All pass. The offence step stays report-only.

**If a gate fails:**
- **Runs**, 4-seed mean change > ±.05 in 4a: the lever is `k_in_dirt_rate` (D3K reaches cost about .04), then the steal base rates. Do not touch offence knobs.
- **Steal volume** near an edge: scale the four base rates together. sb_pct moves only with the success logit base.
- **corr_avg_contact, platoon_gap_woba, tto_ops_gap**, which move only with the random stream:
  1. Confirm on seeds 3-6 that the paired mean is unchanged from baseline.
  2. Confirm the item touches no contact or platoon code.
  3. If 4a still trips seed 1 or 2, ask the owner for a documented temporary widening that expires in Release 5, as Release 3 did for platoon. Decision 4 targets corr_avg_contact ≥ .5 there anyway.
  4. For 4b, a trip means holding the flip to Release 5.
- **OPS above .730 with 4b:** this is a run-level problem for Release 5. Hold the 4b flip; never widen the OPS gate.
- **A zero gate above 0:** a code bug. Fix it.

## 6. Shipping and version

**4a → 7.48.0 (MINOR, recommended).**
- It changes stats owners see at once: about 3x fewer steals, about a third as many WP/PB, fewer K reaches, fewer triples for burners.
- It rebases an existing admin setting: the Steal Frequency slider's default 3.0 becomes 1.0, with a new range.
- It needs a news post.
- Precedent: 7.45.0 "Power hits for power" and 7.41.0 were MINOR engine-behaviour releases.

AGENTS.md says to ask when PATCH vs MINOR is uncertain, so this is in the owner questions. Deliverables:
- `.iss` version matching VERSION;
- release_notes_draft entry;
- updated slider help text;
- news post;
- docs/future_work.md entries.

**4b: option A mechanics with a conditional flip.**
- The code lands now behind legacy-default knobs and two switches. A CI step runs `--tuning-overrides scripts/kpi_profiles/r4b.json` on calibration seed 1 as report-only, so the 4b path cannot rot.
- The audit tied 4b to Release 5 because of a -0.3 R/G cost that the measured design does not have.
- Recommendation: flip 4b as **7.49.0 (MINOR)** once the profile is strict-green on calibration seeds 1-4 and the league running gate set. If corr_avg_contact or platoon flake on any of seeds 1-4, or OPS exceeds .730, hold the flip into Release 5 as originally planned.
- Option B (ship 4b now with a compensating offence knob or a widened runs gate) is unnecessary because runs do not drop.
- Option C (a long-lived branch) is rejected. engine.py is 6.9k lines and Release 5/6 conflicts would be severe.

## 7. Owner questions

Merged and deduplicated. Decisions 2 and 3 settle centring, tier calibration and the centre population, so those are not asked.

1. **When should 4b (fewer extra bases, tag-up holds, more GIDP, speed-driven infield hits) become the default?**
   - (a) As its own release (7.49.0) as soon as it passes the strict gates on 4 seeds. The measured run effect is about 0 to +0.1, not the -0.3 the audit assumed.
   - (b) With Release 5, as originally planned.
   - (c) Keep it on a branch until then.
   
   Recommendation: (a), falling back to (b) automatically if the random-stream-sensitive gates flake.
2. **Should the steal cut reach the live alpha league mid-season?** Alpha goes from about 2.2-2.4 to about 0.8-0.9 SB per team-game from the deploy date. Leaders' paces drop, and the 2026 stats stand as played (decision 1).
   - (a) On at deploy with a news post, as for the Release 3 automatic runner.
   - (b) Ship the rule fixes everywhere (no steals or WP/PB on fouls or with the bases empty, one throw on double steals) but hold the new curve for existing leagues until next season through a league-level override.
   
   Recommendation: (a). It is run-neutral, and today's volume is about 3x MLB.
3. **What should an 85 "burner" be?** With E1, a 50 steals about 6 a season, a 70 about 24 and an 85 about 45 (best seasons 60-68). Because the tiered league has about 16 burner regulars, 11-13 players reach 40+ SB (MLB 4-8). Under the triples reshape, burners also hit about 10 triples per 600 PA instead of 18 (MLB elite 7-10).
   - (a) Accept: this is what the tiers mean.
   - (b) Flatten the top of the curve (mid 70) so burners average about 38 and fewer reach 40, at the cost of a smaller gap between 70 and 85.
   - (c) Steepen it so burners steal like league leaders (55-65).
   
   Recommendation: (a).
4. **Steal Frequency slider rebase.**
   - (a) 1.0 = MLB (default 3.0 → 1.0, range 0.25-3.0), and divide any stored override by 3 once.
   - (b) Rebase and reset stored overrides to the default.
   - (c) Keep 3.0 as "normal" and change only the base rates.
   
   Recommendation: (a).
5. **Version for 4a.**
   - (a) MINOR 7.48.0: visible stat-model change, a slider rebase and a news post.
   - (b) PATCH 7.47.1: bug fixes and calibration, no new settings.
   
   Recommendation: (a).
6. **Team strategy settings for steal aggressiveness and playing the infield in.** Today there is none for CPU or owner clubs; the engine uses one league-wide rule.
   - (a) Keep league-wide in Release 4 (infield in during the 7th inning or later, fewer than 2 outs, fielding team tied or ahead by up to 2), and log a per-team "baserunning aggressiveness" (0.6x / 1.0x / 1.5x) and "infield in" setting in docs/future_work.md as a later MINOR feature with a guide.
   - (b) Build the per-team settings now.
   
   Recommendation: (a).

**Taken as recommended (technical, no owner call needed):**
- The D3K volume fix ships in 4a (−.04 R/G, within noise).
- WP/PB are recorded only when someone advances (rule 9.13).
- Making runs aided by a passed ball unearned (rule 9.16): backlog.
- Two-out "running on contact" is included.
- Thrown-out scale ×0.45. A "batter thrown out stretching a hit" outcome goes to the backlog.
- Productive outs are included.
- On calibration, gate the BABIP-speed slope, not r.
- Bunt-hit term unchanged; bunting for a hit goes to the backlog.
- The triples reshape ships in 4a with `triple_distance_scale` .96.
- The K-reach gate stays a wide report-only band. Pulling Retrosheet data for an exact row is queued.

## 8. Risks and verification drivers

**Risks:**
1. **A caller misses the speed centre.** Without it the curve is absolute and calibration falls to about .39 SB/G. Every path must go through `get_rating_center_overrides()`: game_runner, the parallel-day worker, watch-a-game and the KPI harness. Tests cover the harness and game_runner, and the JSON meta logs the centre.
2. **Gates near their edges and random-stream sensitivity:** runs on seed 1, babip on seed 2, iso on seed 1, OPS with 4b, corr_avg_contact, platoon, tto. Judge neutrality on the 4-seed mean. Treat the counters (bases advanced, runs on WP/PB, K reaches, CS) as the primary neutrality evidence rather than R/G.
3. **Stored `steal_freq_scale` overrides** run about 3x hot without the migration. Alpha has none per the audit, but check cloud leagues' `physics_tuning_overrides.json`. The same check covers `triple_speed_scale`, whose meaning changes to the slow side only.
4. **The `adv2` and `tag_dp` tokens** must not be credited as SB or GIDP by the box score, season_stats, play-by-play or kpi_extras. LiveGamePage shows raw tokens, which is cosmetic.
5. **The 4b knobs are calibrated to engine carry** (drag-free × .75). Release 6 must refit the tag-up knobs (`tagup_dp/fit.py`) and re-check WP/G, because recording only on an advance ties WP volume to `_advance_prob`.
6. **The raw-speed race terms and fielder ratings move when the general decision-2 re-centring lands.** Re-fit `passed_ball_rate`: PB rises about 22% when catcher fa is re-centred from 55. Re-check the tier tables then.
7. **Dual code paths until the 4b flip.** Each W3 test pins both switch settings. A byte-identity test guards "switches off = old behaviour". A commissioner could opt in early only through a stored override of a switch key; document this.
8. **Live-league feel:** steal leaders' paces collapse mid-season (news post), and burners steal less in 40+ SB terms than today.
9. **The calibration fixture cannot express tiers.** Tier-shape gates live only on calibration_league. Add tiered speeds when calibration is next rebuilt (future_work).

**Verification drivers.** All are under `C:/Users/james/AppData/Local/Temp/claude/c--Users-james-OneDrive-Documents-Baseball-AI-NexGen-BBPro/31cccd52-8c06-46f6-a76c-f8479f51ec29/scratchpad/r4/`.

| Area | Driver | Results |
|---|---|---|
| Baseline | `baseline/{calibration,calibration_league}.s{1,2}.json` + `.log` | — |
| Steals | `sb/patch_engine.py` (knobs, curve, success, double steal, foul guard), `sb/driver.py`, `sb/run_variant.sh E1`, `sb/summarize.py`, `sb/variants/E1.*.json` | `sb/runs/` |
| WP/PB | `wppb/wppb_exp.py` (observer draws no extra random numbers; configs A, B, F) | `wppb/F.*.json` |
| XBT, L21, triples | `xbt/driver.py`, `xbt/pkg/physics_sim/` (patched copy with every knob) | `xbt/out/{base,v1l21,t3,f3,…}.*.json` |
| Tag-ups, ground outs, DP | `tagup_dp/exp.py`, `fit.py` (offline tag-up refit), `an.py`, `pool.py`, `v/rec.json` | `tagup_dp/runs/{rec,recsteal}.*.json` |
| Batter speed | `speed_bip/exp.py`, `run.sh NAME FIXTURE SEED '<cfg>'`, `summ.py` | `candC`, `base38` |
| Measurement | `measure/driver.py`, `analyze.py`, `exp.py`, `cmp_exp.py`, `speed_dist.py`, `edge.py` | — |

**Acceptance procedure (W4):**
1. After the merges, run `PYTHONHASHSEED=0 python scripts/physics_sim_season_kpis.py --games 162 --seed N --base-dir data/<fixture> --players data/<fixture>/players.csv --strict --output …` for N = 1-4 on both fixtures. Add `--gate-set running` for calibration_league, and `--tuning-overrides scripts/kpi_profiles/r4b.json` for the 4b check. About 12 minutes per 4 runs on 32 cores.
2. Run `python scripts/run_tests_isolated.py`.
3. Never point any of this at `data/leagues`.