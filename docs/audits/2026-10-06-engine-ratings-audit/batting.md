# Batting mechanism map: how ratings drive the plate appearance (engine 7.45.8)

Scope: pitch selection and location, swing decision, contact, foul and whiff, exit velocity and launch angle,
spray, hit/out resolution, home runs and parks, platoon, times through the order (TTO), batting order.
Code is quoted from `physics_sim/` unless another path is given. All tuning values are `DEFAULT_TUNING`
(`physics_sim/config.py`). alpha-test has no `physics_tuning_overrides.json`, so the live league runs on the defaults.

Evidence used (all in `scratchpad/audit/work/map-batting/`):
- `pa_harness.py` + `sweep.py` -> `sweep_out.txt`: an isolated plate-appearance Monte Carlo. It calls the real
  `_batter_context`, `simulate_pitch`, `resolve_batted_ball` and `out_probability`. Bases are empty, defense is
  all 50, the park is neutral 330/400/330, and each rating point is 12,000 PA. Baseline is an all-50 R batter
  vs an R pitcher with fb/sl/cu/cb 55.
- `contact_curve.py` -> `contact_curve.txt`: contact rate per swing vs CH, by count and zone.
- `bb_profile.py` -> `bb_profile.txt`: EV/LA distribution and HR rate by LA and EV.
- `spray_test.py`, `park_test.py`: pull direction by batter side, and park HR effects.
- `empirical.py` -> `empirical_out.txt`: `current_engine_players.json`, 195 hitters with at least 150 PA.
- `kpi_cal_seed1.json`: calibration harness, `data/calibration`, 162 games, seed 1 (all tolerances green).

---------------------------------------------------------------------------------------------------

## 0. Rating scale and the spreads actually present

The engine treats every rating as a 0-100 number with 50 as league average. Almost every formula is
`(x - 50) / k`, and nothing rescales the ratings. The generator samples percentile bands of an MLB-derived
distribution and clamps the results to 10-99.

| rating (hitters) | alpha-test ACT (n=265) min-max, sd | calibration fixture (n=390) min-max, sd |
|---|---|---|
| ch | 37-73, **4.9** | 44-59, **3.7** |
| ph | 36-63, 4.2 | 33-64, 5.5 |
| eye | 37-52, **1.4** | 36-58, 4.4 |
| gf | 38-52, **1.6** | 41-58, 2.9 |
| pl | 43-56, **1.9** | 34-71, 6.0 |
| vl | 36-60, 3.6 (median 55, not 50) | 28-70, 7.9 |
| sp | 38-92, 9.9 | 30-67, 8.0 |
| fa / arm | 1.9 / 1.5 | 8.9 / 8.6 |
| height (in) | 68-78, 3.1 | 68-79, 2.0 |

| rating (pitchers) | alpha-test ACT (n=235) | fixture (n=390) |
|---|---|---|
| arm (= velocity) | 48-57, 2.0 | 33-75, 6.9 |
| control | 50-57, **1.5** | 34-65, 5.3 |
| movement | **52 for every pitcher, sd 0.0** | 33-69, 5.8 |
| gf | 17-66, 3.5 | 30-72, 8.1 |
| vl | **column empty, so it reads as 50** | 29-73, 8.1 |
| fb / sl / cu / cb | sd 7-9 (nonzero values) | sd 7-11 |

**Correction to the brief:** the calibration fixture is *not* wide for batting ratings. Its CH spread
(sd 3.7) is narrower than alpha-test's (4.9). It is wide only for pitcher ratings, defense, vl and pl.
Fixture checks of CH, PH or GF therefore do not test a decompressed league.

In alpha-test, only **ch, ph, sp, vl** for hitters and the **pitch ratings** for pitchers carry real
variance. eye, gf, pl, fa, arm, control and movement are effectively constant, so their mechanisms below are
real but inert in the live league.

---------------------------------------------------------------------------------------------------

## 1. Pre-PA: batter context (platoon, TTO, eye blend)

`engine.py:3162-3205 _batter_context`, computed once per PA (`engine.py:4320`):

```python
eye = batter.eye * 0.8 + (100.0 - pitcher.control) * 0.2          # 3168
contact += handedness * handedness_contact_bonus   # 1.8
power   += handedness * handedness_power_bonus     # 2.0
eye     += handedness * handedness_eye_bonus       # 1.2
# handedness: opposite hand +1, same hand -1, switch +0.5 (handedness_switch_bonus)
tto_extra = max(0, min(tto, tto_max_passes(3)) - 1)
contact += tto_extra*0.32; eye += tto_extra*0.32; power += tto_extra*0.20
vs_left_diff = _platoon_vl_delta(batter, pitcher_hand)   # 2424: d=vl-50 vs LHP; -0.35*d vs RHP
contact += d*0.25; power += d*0.20; eye += d*0.30; platoon_chase -= d*0.0015
clamp each to [1,100]
```

- **eye** is diluted to 80%, so each eye point is worth 0.8 point in every formula downstream. The other 20%
  comes from the *pitcher's* control: a wild pitcher (control 30) adds +8 eye to every batter, and a
  control-70 pitcher subtracts 4. The pitcher's control enters a second time through the zone target and
  command error (section 2).
- **Platoon**, measured with the harness (OPS / K%): L vs R .710 / 19.6%, R vs R .661 / 25.1%, R vs L .726 /
  19.8%, L vs L .650 / 25.3%. The split is about 50-65 OPS points, and almost all of it comes through **K%**
  (via contact). HR moves only 0.020 to 0.023 per PA. Fixture `platoon_gap_woba` is 0.030 (target band 20-32).
- **vl** is a zero-sum swap: vl 70 for an R batter gives OPS .859 vs LHP but .612 vs RHP, and vl 30 gives
  .608 / .692. Because the contact curve is convex and saturates (section 4), the points lost vs RHP cost more
  than the points gained vs LHP buy. Empirically, a higher vl is **net negative over a season**: on the current
  engine, K% rises 1.9 pp per +10 vl (t=3.5) and ISO falls 1.9 pts per +10 vl (t=-2.3). alpha-test's median vl
  is 55, so most hitters carry a small penalty vs RHP.
- **TTO** bonuses are negligible. The harness shows tto 1/2/3 OPS of .661/.655/.664, all within noise. On the
  fixture the realized TTO OPS is .710/.718/.761. Pass 2 is +8 OPS (MLB is about +15-20) and pass 3 is +51,
  almost all of it from pitcher fatigue. The 0.32-point bonus is about 1/40 of what it would take to matter.
- The handedness bonuses used for lineup building (`utils/lineup_autofill.py:305-347`: 2.0 for ch, ph and eye)
  do not match the engine's (1.8 / 2.0 / 1.2).

---------------------------------------------------------------------------------------------------

## 2. Pitch selection, location and command (pitcher side)

**Velocity:** `engine.py:4329` sets `"velocity": 83.0 + arm*0.2`. arm 50 throws 93 mph, and alpha's arm range
48-57 covers only 92.6-94.4 mph. The fb pitch rating does **not** set velocity. Per-type offsets come from
`pitch_type_velocity_offset` (si -1, sl -6, cu -8, cb -11, scb -10, kn -18). Fatigue applies
`velocity *= max(0.85, 1-0.15*penalty)` (`engine.py:482`). `PitcherRatings.velocity` (`models.py:114`) is
loaded but never read.

**Objective** (`physics.py:235-285`): a weighted draw over attack/edge/chase/waste/putaway, using count tables,
RISP / first-base-open / late-close mods, and the batter's in-game swing and chase rates after 6 pitches.
No rating enters here directly.

**Pitch type** (`physics.py:297-357`): the weight is the pitch's rating, `max(1, rating)`, times count and
objective biases. Batter ratings enter only through thresholds:
- `batter_power >= 60` multiplies fastball weight by 0.92 (`pitch_seq_power_avoid_fastball`).
- `batter_eye >= 60` multiplies breaking-ball weight by 0.95.

Both use the context values (after platoon and TTO). In alpha-test, eye never reaches 60 and power rarely
does, so both are dead there. A pitch rated 70 is thrown 70/50 = 1.4x as often as one rated 50.

**Platoon on the pitch** (`physics.py:604-609`): vs an L-side batter, `pitch_quality += (vs_left-50)*0.25`.
Inside the swing branch, `pitch_quality` is overwritten by `control*0.4 + movement*0.4 + pq*0.2`
(`physics.py:767`), so the pitcher's vl reaches contact at only 0.05 per point. Harness: vl 30 to 70 against an
L batter moves OPS .729 to .709. alpha-test pitchers have an empty vl column, so this is **dead in the live
league**.

**Zone target** (`physics.py:621-628`): `0.36 + (control-50)*0.0009 + (strikes-balls)*(-0.02) + objective adjust`,
clamped to 0.15-0.85. Control 30 to 70 moves the target only 0.342 to 0.378.

**Command error** (`physics.py:446-457`): the sd is `base_x 0.09 / base_y 0.12 ft *
(1 + (100-control)/100*3.1 + max(0,(movement-50)/50)*0.4)`. Control 50 gives 2.55x the base and control 70
gives 1.93x.

**Break** (`physics.py:113-153`): `base * (1+(movement-50)/100*0.6) * (1+(pq-50)/100*0.4) + N(0, 0.04)`.

**Measured pitcher effects** (harness, per +10 points around 50, average batter):

| rating | K% | BB% | HR/PA | EV (mph) | notes |
|---|---|---|---|---|---|
| control | **+3.4 pp** | -0.6 pp | **-0.7 pp** | **-2.2** | acts mainly as "stuff" through the pq composite, not as walk prevention |
| movement | +2.7 pp | +0.2 pp (wrong way) | -0.7 pp | -2.4 | same composite weight as control; the command penalty adds walks |
| pitch ratings (all, 40 to 70) | +1.5 pp | -0.1 pp | -0.4 pp | -1.2 | 0.2 weight in the composite, plus break |
| **arm / velocity** | **0.0** | 0 | **+0.2 pp (wrong sign)** | **+0.7** | see S-1 |
| gf (pitcher) | 0 | 0 | 0 | 0 | **dead**: identical RNG streams |

Fixture rating split by control (bottom vs top): K 18.1% vs 23.1%, BB 9.0% vs 7.4%, HR/BF 3.7% vs 2.2%.

---------------------------------------------------------------------------------------------------

## 3. Swing decision (eye / discipline)

`physics.py:699-736`:

```python
zone_base  = 0.62 + (eye - 50.0) / 200.0
chase_base = 0.28 - (eye - 50.0) / 230.0 + platoon_chase
base_swing = (zone_base * zone_swing_scale 0.91) if in_zone else (chase_base * chase_scale 0.69)
if strikes >= 2: base_swing += 0.10*1.05 (zone) / 0.08*1.05 (chase)
base_swing += count_swing_bonus[count]            # e.g. 0-2: +0.10 zone, +0.02 chase
if balls == 3: base_swing *= 0.5 (3-0) / 0.8 (3-1)
if not in_zone: base_swing /= walk_scale (0.83)   # chase x1.205
clamp 0.02-0.98; then if no swing and strikes>=2: forced swing with p=0.63 (zone) / 0.19 (chase)
```

- Each +10 eye (0.8 x 10 = 8 context points) gives about +3.6 pp zone swing and -2.9 pp chase. Harness
  per +10 eye: **BB +0.8 pp, K -1.7 pp**, OBP +1.0 pt. Z-swing rises with eye. In MLB, discipline shows up
  mainly as a lower O-swing, with Z-swing about flat.
- **The walk mechanism is too weak to give BB% any spread.** On the current engine (167 hitters with at
  least 250 PA), the observed BB% sd is 1.51 pp against binomial noise of 1.55 pp, so **true-talent BB% sd is
  about 0**, and the regression of BB on all seven ratings has R2 = 0.02. Even at the fixture's eye sd of 4.4,
  the slope gives only about 0.35 pp of true BB spread. Reaching MLB's roughly 2.5 pp would take about 3x the
  slope *and* decompressed eye. Contact and power have no BB effect (fixture contact top/bottom BB 8.7% vs
  8.6%).
- The pitcher's control enters the batter's eye, the zone target and command error, which together give
  about -0.6 pp BB per +10 control.
- The forced 2-strike protect swing (`two_strike_zone_protect` 0.63) applies the same to every batter. Called
  third strikes are 25.8% of K on the fixture (MLB 23%).
- `strike_zone_bounds` (`physics.py:83-106`) moves the zone with height (+0.10 / +0.15 ft per 10 in at
  bottom / top). The harness shows no outcome effect from height 68 to 78.
- Framing (`physics.py:500-536`): the margin is `0.025 + (C_fa-50)/100*0.01` ft (about 0.0024 in per point) and
  the probability is `0.18 + (C_fa-50)/100*0.1`. This is cosmetic.

---------------------------------------------------------------------------------------------------

## 4. Contact vs whiff vs foul

`physics.py:767-803`:

```python
pitch_quality = control*0.4 + movement*0.4 + pq*0.2            # composite ("pq_c")
whiff = 0.0095 + 0.072*max(0,(pq_c-50)/100) + 0.062*max(0,(velo-90)/20)
        + 0.068*min(1, break_mag/0.4) + 0.042*min(1, loc_miss);  x1.04 out of zone; cap 0.6
contact_base = ch - (pq_c-50)*0.4 - break_mag*5.0
contact_prob = clamp((contact_base/100)*0.885, 0.05, 0.95)
contact_prob *= 0.73 if out of zone; *= count_contact_scale (x1.10 at 0-2/1-2, x1.08 at 2-2/3-2)
contact_prob /= k_scale (0.51)                      # nearly doubles it
contact_prob = min(contact_prob, 1 - whiff)
if rand < whiff: miss  else: contact = rand < contact_prob/(1-whiff)   ->  P(contact) = contact_prob
```

**Key structural facts**

1. **Whiff is only a ceiling.** Because `P(contact) = min(contact_prob, 1-whiff)`, the velocity, break and
   location whiff terms change nothing until the hitter's contact_prob exceeds `1-whiff`. For an average or
   weak hitter, pitcher velocity has *no* effect on swinging strikes. Measured zone contact at CH 50 is .837 at
   89 mph and .840 at 99 mph.
2. **The CH curve is steep below 50 and saturated above about 56** (`contact_curve.txt`):

   | CH | Z-contact 0-0 | O-contact 0-0 | Z-contact 2-strike | O-contact 2-strike |
   |---|---|---|---|---|
   | 30 | .488 | .358 | .545 | .398 |
   | 40 | .667 | .483 | .731 | .535 |
   | 50 | .838 | .613 | .925 | .678 |
   | 55 | .924 | .682 | .944 | .749 |
   | 60 | .944 | .740 | .940 | .815 |
   | 70 | .947 | .873 | .942 | .932 |
   | 80+ | .945 | .932 | .942 | .933 |

   Above CH 56 (or 51 with two strikes), Contact improves only out-of-zone contact, and above about 75 it does
   nothing. With two strikes, an elite hitter's O-contact (.93) equals his Z-contact (MLB is .62 vs .82).
   `k_scale` 0.51 is the knob that pushes most hitters into this ceiling.
3. **K% vs CH** (harness): 30: 52.6%, 40: 38.5%, 50: 25.1%, 60: 16.3%, 70: 12.0%, 80: 11.5%. A CH-37 alpha
   hitter strikes out 43.2% of the time; CH 61 strikes out 15.9%. Each point is worth -1.35 pp of K between
   40 and 50 but only -0.05 pp between 70 and 80. On the current engine, CH explains most of K% (r=-0.79,
   -7.0 pp per 10, t=-17). K% true-talent sd is about 3.9 pp.
4. Each pitcher composite point costs 0.4 contact points, so control or movement +10 costs CH -1.6. Break costs
   5 points per foot (sliders about -1.4, curveballs about -1.7, fastballs about -0.5).

**Foul** (`physics.py:901-935`), given contact:
`foul = 0.41 * (1+(1-contact_quality)*0.35) * (1+max(0,(pq_c-50)/50)*0.2) * (1+edge*0.25) * 1.02 if chase *
two_strike 1.02 * foul territory * count_foul_scale (1.2 at 0-2)`, clamped 0.05-0.9. The batter reaches this
only through contact_quality (timing uses CH, barrel uses PH). The fixture foul share is 20.6% of pitches.

---------------------------------------------------------------------------------------------------

## 5. Contact quality, exit velocity and launch angle

`physics.py:804-895`:

```python
difficulty = max(0,(pq_c-50)/100) + max(0,(velo-90)/20) + 0.5*min(1, break/0.4)
timing_sd = 0.22*(1+difficulty*0.6) * (0.8 + (1-CH/100)*0.6)        # skill_contact_scale 0.6
barrel_sd = 0.24*(1+difficulty*0.6) * (0.8 + (1-PH/100)*0.6)        # barrel_power_weight 1.0 -> Power
contact_quality = 0.6*(1-|N(0,timing_sd)|) + 0.4*(1-|N(0,barrel_sd)|)
bat_speed = 68.8 + (PH-50)*0.15 + max(0, PH-52)*0.8                 # _power_bat_speed, physics.py:43-61
            + (CH-50)*0.0                                           # bat_speed_contact_scale 0
ev_base = velo*0.48 + bat_speed*0.7 + N(0, 5.0)
quality = 0.85 + (contact_base - 50 + (CH-50)*(0-1))/250            # = 0.85 + (-(pq_c-50)*0.4 - 5*break)/250
quality *= max(0.75, 1-(pq_c-50)/250)                               # pitch quality a 2nd time
quality *= 0.7 + 0.6*contact_quality
quality *= max(0.65, 1-|timing_err|*0.19) * max(0.65, 1-|barrel_err|*0.215)
EV = max(50, ev_base*clamp(quality,0.5,1.2)) * 1.075 (contact_quality_scale) * 1.0175 (offense_scale)
if EV > 107: EV = 107 + (EV-107)*0.44
LA = N(12.1 - (GF-50)/10, 10.5) + vloc*8 + timing_err*7 + N(0, |barrel_err|*3.5);  *0.97;  clamp [-20, 60]
```

Measured marginal effects (harness, per 10 points):

| rating | EV | LA | other |
|---|---|---|---|
| PH below 52 | about +1.0 mph | 0 | knee: 0.15 vs 0.95 mph of bat speed per point |
| **PH above 52** | **about +6 mph** (60: 91.0, 70: 97.2, 80: 102.8) | 0 | HR/PA 50: .020, 60: .035, 70: .066, 80: .098 |
| CH | +0.5 mph | 0 | through timing error only (EV quality weight 0) |
| GF | 0 | **-1.0 deg** (30: 13.1, 70: 9.3) | GB% 36 to 49, HR/PA .027 to .014 |
| pitcher control/movement | -2.2 / -2.4 mph | 0 | the composite enters EV twice (lines 859-862) |
| pitcher arm | **+0.7 mph** | 0 | velo*0.48 makes harder throwers easier to drive (S-1) |

- **PH is the HR rating, and it is very steep above the knee.** On the current engine, HR~PH r=0.65
  (+2.1 pp HR/PA per 10, t=11.7) and HR~CH r=0.11 (partial +0.5 pp, t=3.2). On the fixture,
  corr_hr_power=.59 and corr_hr_contact=.19. The flat slope below 52 means PH 30-52 hitters barely differ
  (HR/PA .014 to .020). The steep slope above it means any decompression is dangerous: the generator's
  "power" archetype draws from the top percentile bands, and PH 80 already projects to about 59 HR per
  600 PA.
- **Noise scale:** EV sd within a hitter is about 12 mph (p10 72, p90 103). Below the knee, 10 PH points
  (1 mph) is about 0.1 sd. Above it, 10 points is about 0.5 sd.
- **LA noise swamps GF:** the LA sd is about 12 deg, and GF moves the mean 1 deg per 10 points. GF needs a
  ±50 spread to move the mean 5 deg. With alpha's GF sd of 1.6, that is ±0.3 deg, which is dead.
- **The LA distribution is far too narrow:** p10 -4.2, p50 11.2, p90 26.6 (MLB is about -20 / 12 / 50).
  0.05% of balls in play have LA of at least 50 deg, while MLB has roughly 10% infield flies among fly balls.
  The mean (11.2 deg) and the GB/LD/FB shares (42/22/36) hit MLB only because the class cutoffs were tuned:
  `bip_gb_cutoff` 9.0 and `bip_ld_cutoff` 15.7 (MLB uses 10 and 25). "FB" therefore includes 16-25 deg
  liners, and popups are absent.
- Mean EV is 86.4 in the harness and 87.75 on the fixture (MLB 88.5).

---------------------------------------------------------------------------------------------------

## 6. Spray / pull

`physics.py:896-900`:

```python
pull_bias = (pull_tendency - 50.0) / 2.0
spray_angle = random.gauss(pull_bias + timing_error * 12.0, 18.0)
```

Field mapping: `spray_to_field_angle = 45 - spray` (`physics.py:994-997`). **Positive raw spray points toward
the RF line for every batter.** The engine's fielding code uses `spray_dir = -spray if batter_side == "R"`
(`engine.py:1745`, `fielding.py:169`), so a positive spray_dir means the batter's pull side.

- **S-2, Pull is inverted for right-handed batters.** `simulate_pitch` never mirrors by batter side, so a
  high-PL RHB sprays toward RF, his opposite field. `spray_test.txt`, in a 300/400/360 park:

  | batter | PL 20 | PL 50 | PL 80 |
  |---|---|---|---|
  | RHB | **HR/PA .042** (sprays to LF, "pulls") | .033 | .030 (sprays to RF) |
  | LHB | .060 | .048 | .046 |

  A "spray" RHB (PL 20) therefore behaves like a pull hitter.

- The shift (`fielding.py:213-232`) adds `0.04*intensity*align` to GB out probability (0.015 for LD), with
  `align = spray_dir/25`. Because of the inversion, a PL-80 RHB's balls go away from the shift and the shift
  slightly *helps* him. For LHB it works as intended.
- **S-3, Fielder credit is mirrored for LHB.** `_infield_pos_for_spray` / `_outfield_pos_for_spray`
  (`engine.py:1752-1768`) map spray_dir >= 25 to 3B and spray_dir > center band to LF for *both* sides, while
  out_probability maps a positive LHB spray_dir to 1B/2B/RF. A PL-80 LHB's pulled grounders go 78% to 3B/SS
  and his flies 66% to LF. This affects fielding stats, the fielder whose arm is used for advancement
  (`engine.py:4750-4778`), and error attribution. The hit/out probability itself uses the correct side.
- Pull and HR in a symmetric park form a U-shape. The wall is *linearly* interpolated by angle (330 to 400,
  `playbalance/field_geometry.py:46-57`), so any off-center spray meets a shorter fence. PL 30 and PL 70 give
  the same HR rate (.021 / .022 in the harness), while in MLB pull rate is one of the strongest HR correlates.
- With a spray sd of 18 deg against 10 deg per ±20 PL, and alpha's PL sd of 1.9 (about ±1 deg), PL is dead
  in alpha-test. 1.3% of balls fall outside ±45 deg and are clamped onto the foul line as fair balls; there are
  no foul flies from spray.
- MLB pull/straight/oppo benchmark (39/36/25) is not modelled.

---------------------------------------------------------------------------------------------------

## 7. Hit vs out (fielding interaction) and hit type

**HR test first** (`physics.py:1023-1042`): `dist > wall(angle) * park_size_scale` makes it a HR.

**Non-HR hit vs out** (`engine.py:4730-4742` -> `fielding.py:158-233`):

```python
base = 0.78 (gb) / 0.38 (ld) / 0.73 (fb)
def_adj = (range-50)/250 (gb) | /300 (ld) | /230 (fb)    # range = fielder fa (x0.9 secondary, x0.75 out of position)
out_prob = base + def_adj - (EV-90)/300  (+ shift term)  -> clamp .02-.98
hit_prob = (1-out_prob) * babip_scale 0.925
```

- **Batter inputs are only ball type (3 bins) and EV.** Within a bin, launch angle, distance and spray do not
  matter. +10 mph EV is only -3.3 pp out probability. A 105-mph grounder is a hit 26% of the time (MLB about
  50%), and a 75-mph grounder 18%. That is why BABIP barely tracks ratings: R2 = 0.06; PH +1.0 pt per 10
  (t=2.0); CH +0.5 (n.s.).
- **Speed has no effect on BABIP or AVG.** There are no infield hits and no beat-the-throw logic (`grep`
  confirms that `batter.speed` is read only for extra-base thresholds, stretches, DP and bunts). Harness:
  SP 30 and SP 70 give identical AVG (.230). On the current engine, SP gives BABIP +0.09 pt per 10 (t=0.4) but
  3B +0.37 pp per 10 (t=10.5).
- A fly ball that stays in the park, at 16 deg or at 50 deg, has the same 0.73 base out probability. No popup
  class exists, so there is no near-automatic out.
- Defense: fielder fa 70 vs 50 is +8 pp GB out probability, which is large. But alpha's fa sd is 1.9, so team
  defense is effectively uniform there.

**Hit type** (`physics.py:1043-1084`): doubles happen when distance is at least `wall*0.82*0.70*(1-speed_norm*0.18)*(1-gap_norm*0.45)`,
where `gap_norm = ((CH+PH)/2-50)/50`, and triples when distance is at least `wall*0.97*0.96*(1-speed_norm*0.28)`.
Then `_maybe_upgrade_hit` (`engine.py:1543-1571`) gives 0.02 + speed bonus (0.18) for single to double and
0.006 + 0.12 for double to triple, both scaled by the fielder's arm. Effects:
- CH and PH also lower the double threshold, so **PH is double-counted** for doubles (through EV and through
  gap). `resolve_batted_ball` receives the raw `batter.contact/power` (`engine.py:4673-4675`), not the
  platoon-adjusted context values.
- SP 30 to 70: SLG +0.028 (XBH only).

---------------------------------------------------------------------------------------------------

## 8. Home-run physics and parks

`physics.py:1000-1020`:

```python
dist = (EV*1.467)^2 / 32.17 * sin(2*theta) * 0.75 * hr_scale 0.925 * offense_scale 1.0175
       * altitude_scale * (1 + (park_factor-1)*park_factor_scale[0.0]) * clamp(1 + alt_ft*2e-5, 0.9, 1.25)
```

- **S-4, Vacuum projectile.** Carry peaks at **45 deg** with no drag or backspin. Distance table (ft):

  | EV | 25 deg | 30 deg | 45 deg | 55 deg |
  |---|---|---|---|---|
  | 90 | 293 | 331 | 383 | 359 |
  | 100 | 362 | 409 | **472** | 444 |
  | 105 | 399 | 451 | **521** | 489 |

  The 25-30 deg values are realistic. At 40 deg and above they are hugely inflated (a real 100-mph ball at
  45 deg travels about 340 ft). HR rate by LA bucket: 25-30 deg 17%, 30-35 deg 30%, 40-45 deg **50%**,
  50-60 deg **64%** (MLB is about 0% above 50 deg). It is masked only because the LA distribution rarely
  reaches 40 deg (section 5): 10% of HR come at 40 deg or more. Mean HR LA is 31.3 and mean HR EV 102.1 (MLB
  about 28 / 103.5). The minimum HR EV is 86.9 mph.
- **`offense_scale` is double-counted:** it multiplies EV (`physics.py:875`) *and* carry (`physics.py:1009`), so
  distance scales as offense_scale^3. That is why the config comment notes "+0.01 is about +0.39 runs".
  `hr_scale` and `contact_quality_scale` are similarly redundant.
- **Park factors are switched off:** `park_factor_scale` = 0.0, so `ParkFactors.csv` is ignored. Some of its
  values are suspect anyway (Chase 0.77, Petco 1.117, Great American 1.309). Park effects therefore come only
  from geometry (LF/CF/RF corners, linearly interpolated, no wall height, no alleys), altitude and foul
  territory.
- **Altitude is too strong:** `altitude_ft_scale` 2e-5 makes Coors carry +10.4% (about +40 ft at 400 ft). HR/PA
  for a PH-56 hitter: neutral .027/.038 (R/L), Coors .037/.053 (**+38%**), Fenway .033/.049 (+26%, real
  Fenway suppresses LHB HR), Oracle +4-8% for LHB (real Oracle strongly suppresses them), Comerica -15%.
  Linear corner-to-center fences make the Pesky-pole 302 and Oracle-RF 309 apply across the whole field.
- **alpha-test parks** are mostly unknown names, so they get the default 330/400/330 at altitude 0. The
  exceptions are FOR "Royals Stadium", which matches Kauffman (330/410/330, 886 ft, carry +1.8%), and SAN1
  "Petco Park". Park effects are nearly absent in the live league, and the platoon-handedness HR split is the
  only side asymmetry.

---------------------------------------------------------------------------------------------------

## 9. Batting order and other PA-level rules

- **The engine has no batting-order effects** (no protection or lineup-slot terms). The slot only changes PA
  volume and base-out context.
- The default fallback order (`utils/lineup_loader.py:152`) sorts by **PH descending**, so the leadoff hitter is
  the biggest slugger. The autofill (`utils/lineup_autofill.py:325-412`) uses an "obp" proxy of `0.6*eye + 0.4*ch`,
  but eye has almost no effect on OBP in practice (section 3), while CH drives AVG and OBP (r .50 / .43). The
  leadoff choice therefore leans on a near-inert rating.
- **IBB is effectively dead:** `engine.py:2765-2789` requires `ch*0.55 + ph*0.45 + platoon >= 65`, inning 7 or
  later, and a close game. Compressed ratings almost never reach 65, giving **2 IBB in 70,739 PA** on the current
  engine (MLB about 0.5% of PA).
- Bunts (`engine.py:2792-2819`): 3% of eligible PA (runners on, fewer than 2 outs, inning 8 or earlier, close
  game) for every hitter, times 0.6 if PH is 60 or more. The bunt hit/success chance uses CH and SP
  (`engine.py:2837, 2862`).
- HBP is checked before the swing at `hbp_rate 0.003 * (1+(50-control)/120) * (1+loc_miss)` per pitch.
- Batter fatigue (`engine.py:2999-3057`) multiplies the *whole* rating (`contact*(1-penalty*0.8)`, penalty up to
  0.35, so up to -28%). On a compressed 50-centred scale, a 10% penalty takes CH 50 to 46, worth about +5 pp
  K. With a game cost of 6 against daily recovery of about 8.5, it rarely triggers, but it is a cliff when it
  does.

---------------------------------------------------------------------------------------------------

## 10. Inventory: dead, cosmetic, saturated, wrong-signed, double-counted

**Dead (loaded or present, never affects the PA):**
- Pitcher **gf / gb_tendency** (`models.py:117`): never read. Pitchers have no effect on GB/FB mix, and
  harness gf 20 and 80 give identical results.
- Batter **sc**: not loaded into `BatterRatings` at all. It counts in OVR (`docs/PROJECT_CONTEXT.md:25`) and
  does nothing.
- `PitcherRatings.velocity` (`models.py:114`): unused; the engine uses `arm` (`engine.py:4329`).
- The **fb** pitch rating does not affect velocity; it only sets usage weight and the 0.2 composite share.
- **`park_factor_scale` = 0.0**: ParkFactors.csv is ignored.
- `bat_speed_contact_scale` = 0.0 and `ev_contact_quality_weight` = 0.0 are intentional (S3).
- Pitcher **vl** in alpha-test: the column is empty, so every pitcher reads 50.

**Inert because alpha-test is compressed (the mechanism exists):** eye (sd 1.4), batter gf (1.6), pl (1.9),
fa/arm (1.9/1.5), control (1.5), movement (0.0), endurance. Thresholds at 60 (eye >= 60 pitch mix, power >= 60
bunt and fastball avoid) and the IBB threshold of 65 are almost never reached.

**Saturated or clamped:**
- CH above about 56 (in zone), about 51 (two strikes) and about 75 (chase): contact is capped at `1-whiff`
  (`physics.py:798`).
- Whiff terms (velocity, break, location) bind only above that ceiling, so they are inert against
  average and weak hitters.
- The EV soft cap above 107 (×0.44) trims the elite tail; with PH 80 the mean EV is 102.8, so the cap bites.
- LA is clamped to [-20, 60] and spray to [0, 90] deg field angle.

**Wrong-signed:**
- **S-1 Pitcher arm (velocity):** no K effect, but +0.7 mph EV per 10 and +0.2 pp HR/PA, so harder throwers
  are *worse* (`engine.py:4329`, `physics.py:773-776, 848`). Fatigue velocity loss likewise *lowers*
  batter EV.
- **S-2 PL for RHB:** inverted direction (`physics.py:896-900`), so the shift helps high-PL RHB.
- **S-3 LHB fielder credit** is mirrored (`engine.py:1752-1768`).
- **Movement raises BB** (+0.2 pp per 10) through `movement_command_penalty`: defensible, but it also makes
  movement nearly indistinguishable from control.
- **vl is net negative** over a season (K +1.9 pp per 10 vl, t=3.5), from the RHP counter-shift
  (`engine.py:2424-2429`) combined with contact convexity and alpha's median vl of 55.

**Double-counted:**
- Pitch-quality composite in EV: `contact_base` term plus the `max(0.75, 1-(pq_c-50)/250)` term
  (`physics.py:859-862`), plus `difficulty`.
- `offense_scale` in EV and carry (`physics.py:875, 1009`), giving a distance^3 effect.
- PH in doubles, through EV and through `gap_norm` (`physics.py:1059`).
- Pitcher control in the batter's eye blend (`engine.py:3168`), the zone target and command error.

**Noise that swamps rating differences:**
- `launch_angle_sd` 10.5, plus location ×8, timing ×7 and barrel noise: total LA sd about 12 deg against GF's
  1 deg per 10.
- `exit_velo_sd` 5, plus quality noise: total EV sd about 12 mph against PH's 1 mph per 10 below the knee.
- Spray sd 18 deg against PL's 5 deg per 10.
- At alpha spreads, **BB% true-talent sd is 0**: the observed BB spread equals binomial noise.

**Realism gaps (vs `data/MLB_avg` 2025):**
- No popups; LA p90 26.6 (MLB about 50).
- HR is possible up to 60 deg (vacuum carry).
- Hit/out ignores LA within class, and EV→BABIP is about 1/3 to 1/4 of MLB.
- No infield hits.
- TTO pass-2 effect is about half of MLB.
- Platoon acts through K only.
- Velocity does not create whiffs.
- 2-strike O-contact equals Z-contact for good hitters.
