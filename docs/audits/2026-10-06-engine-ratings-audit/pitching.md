# Pitching mechanism map — current engine (7.45.8)

Scope: how pitcher ratings drive outcomes in `physics_sim` (live path: `playbalance/game_runner.py` ->
`physics_sim.engine.simulate_game`), plus fatigue, usage, hooks, bullpen roles, rest/recovery and injury.
All paths are relative to the repo root. Evidence scripts and outputs live in
`scratchpad/audit/work/map-pitching/` (`pitch_sweep.py/.txt`, `season.py`, `analyze.py`, `analyze_out.txt`,
`fatigue_probe.py`, `closer_probe.py`, `roles.py`, `spreads.py`).

Evidence sources:
- **PA kernel sweep** (`pitch_sweep.txt`): 20,000 PAs per row, average batter (all 50), the real
  `simulate_pitch` + `resolve_batted_ball` + `out_probability`, one pitcher rating varied at a time.
- **Season runs** (`analyze_out.txt`): 162 g/team through the `team_data` path (same as the KPI harness) on a
  copy of the calibration fixture (2,430 g) and on a copy of the resim alpha-test league (1,620 g). Pitchers
  >= 40 IP. OLS coefficients are per +10 rating points with arm, control, movement, mean pitch rating together.
- **current_engine_players.json** (910 live-path games on alpha-test).

---------------------------------------------------------------------------------------------------------

## 0. Headline findings (ranked)

| # | Finding | Where | Evidence |
|---|---------|-------|----------|
| 1 | **Arm/velocity is wrong-signed.** Higher arm means a faster pitch, which raises the exit velocity (EV) allowed through `ev_pitch_weight`. The whiff gain is tiny and only above 90 mph. Power pitchers allow more HR. | engine.py:4329; physics.py:773-775, 808, 847-850 | Sweep: arm 30 -> 90 gives OPS .670 -> .750, HR/PA 2.2% -> 3.5%, K 23.9% -> 24.6%. Calib OLS per +10 arm: K +0.09pp, EV +0.70 mph, ERA +0.09 |
| 2 | **Fatigue cuts velocity by up to 15% (about 14 mph).** Because of #1, that loss *helps* the tired pitcher on contact quality. | engine.py:482-486; physics.py:441-443 | Calib FB velocity: 94.3 mph (pitches 0-9), 82.9 (90-99), 79.8 (100+); relievers 91.5 at pitches 20-39 |
| 3 | **Relief roles `MR1/MR2/MR3` and `RP` are not recognized by the engine.** They get starter fatigue limits (start ~80 pitches), no max-outs hook and none of the role bonuses in reliever choice. | engine.py:271, 629-639, 710-742; game_runner.py:1103-1118 passes roles raw; team_data.py:152-156 maps only RP/R->MR | Alpha copy: MR1-3 average 7.3-8.0 outs / 42-46 pitches per relief outing (48-56% go 7+ outs) vs MR 3.96 / 23. Live path: MR1-3 7.1-7.7 outs, `none`/RP 6.5 outs. The calibration fixture uses only "MR", so the KPI harness never sees this |
| 4 | **An unavailable closer is used anyway.** The 9th-inning closer entry falls back to `closer_candidates` when no closer is available, which skips the rest, consecutive-day and appearance-cap gates. | engine.py:3807-3820 | Calib, 600 g: 307 of 523 CL entries (59%) were by a CL flagged unavailable; 174 of those carried a short-rest pregame penalty |
| 5 | **No hook check at the start of an inning.** The hook runs only after a PA with outs < 3, so a reliever who finishes his allotted inning goes back out and faces at least one more batter. | engine.py:5490-5491 (`if outs >= 3: continue`), 608-639 | Calib: CL with exactly 3 outs 67%, 4 outs 12%; MR (cap 4) 4 outs 48%, 5 outs 15% |
| 6 | **When no reliever is available, the tired pitcher stays in indefinitely.** `_select_reliever` returns `team_state.current`. The penalty then saturates at 1.5 (control x0.6, movement x0.65, velocity x0.85). | engine.py:783-784 | Calib, 600 g: 1,450 of 4,681 hook decisions found no reliever. CL relief outings of 7+ outs: 8% calib, 15% alpha (max 26-30 outs) |
| 7 | **Control is effectively the main "stuff" rating.** Through `pitch_quality = 0.4*control + 0.4*movement + 0.2*pitch`, plus command error and the batter-eye blend, control moves K and HR far more than BB. | physics.py:767, 621-622, 446-457; engine.py:3168 | Calib OLS per +10 control: K +2.5pp, BB -0.8pp, HR -0.65pp, EV -2.2 mph, ERA -0.87. Sweep control 30 -> 90: K 18.9% -> 38.3%, BB 10.7% -> 6.8% |
| 8 | **Pitch-type ratings (fb/cu/cb/sl/si/scb/kn) carry only a 20% weight.** Pitch *type* (velocity offset + break) matters as much as rating. | physics.py:586, 767, 59-67 | Sweep: all pitch ratings 30 -> 90 gives K 21.7% -> 29.5%. FB-only repertoire HR/PA 4.1% vs FB+CB 2.5% at equal ratings |
| 9 | **Alpha-test pitching outcomes are almost pure noise.** In the >= 40 IP pool movement is constant 52, pitcher vs_left is blank (so 50), control 50-57, arm 48-57, endurance 48-52. | players.csv | Alpha OLS R^2: K 0.01-0.02, ERA 0.01-0.02. Calib R^2: K 0.31, HR 0.34, ERA 0.35, EV 0.77 |
| 10 | **Fatigue debt is dead in practice.** Daily recovery is 40 + 0.8*durability, at least 56 a day, while the largest debt is 120*0.35*1.25 = 52.5, so debt is always 0 the next day. Durability's recovery role and `fatigue_debt_*` knobs have no effect. | usage.py:77-92, 112-133; config.py:370-375 | Arithmetic; pregame penalty comes only from the short-rest path |
| 11 | **Dead or cosmetic pitcher fields:** gf (gb_tendency), fa (fielding), `PitcherRatings.velocity`, runner "lead" level, and the `movement_scale` knob (shown in the tuning UI but never read). | models.py:114,117,122; engine.py:1231-1281; config.py:363; services/physics_tuning_spec.py:179 | grep |
| 12 | **The tracker's bullpen availability never gates the physics engine.** game_runner only *reorders* resting arms behind rested ones, and the engine picks relievers by score, not order. The physics UsageState is process-global and resets each new process. | game_runner.py:60-87, 255-323; engine.py:768-831 | Code path |

---------------------------------------------------------------------------------------------------------

## 1. Rating scales and spreads

Ratings are a **0-100 scale centred on 50**; formulas use `(r - 50)/k`. Missing or blank values default to 50
(`PitcherRatings.from_row`, physics_sim/models.py:94-98). A pitch with rating 0 is not in the repertoire
(models.py:100).

| Rating | alpha-test live players.csv (494 P) | calibration fixture (390 P) | Notes |
|---|---|---|---|
| arm | 35-57, p10 48 / p90 54, sd **2.7** | 33-75, sd 6.9 | velocity = 83 + 0.2*arm -> alpha sd **0.54 mph** |
| control | 28-58, p10 50 / p90 52, sd 3.6 | 34-65, sd 5.3 | floor-compressed at 50 |
| movement | 30-56, p10 = p90 = **52**, sd 2.5 | 33-69, sd 5.8 | in the >= 40 IP pool movement is **exactly 52 for all** |
| endurance | 20-54, p10 48 / p90 52, sd 5.6 | 25-75, sd 13.0 | alpha starters (>= 10 GS) sd **0.9** |
| hold_runner | 23-66, sd 4.1 | 25-82, sd 9.9 | |
| fb | 38-73, sd 6.8 | 32-88, sd 10.7 | generator floors fb at arm - 0..6 (player_generator) |
| cu / cb / sl | means 60-61, sd 8-9 | means 52, sd 7-8 | alpha breaking pitches rate ~8 pts above its fb |
| si / scb / kn | si 156 P, scb 57 P, kn 0 | si 99, scb 0, kn 0 | |
| vl (pitcher) | **blank for all 494 -> 50** | 29-73, sd 8.1 | dead in alpha |
| gf (pitcher) | sd 4.3 | sd 8.1 | dead in the engine anyway |
| durability | 36-82, p10 = p90 = 50 | 26-92, sd 10.5 | |
| repertoire size | 2: 71, 3: 177, 4: 156, 5: 90 | 3 for all | |
| players.csv `role` | RP 492 / SP 2 | SP 150 / RP 240 | known stale column; staff files are the authority |

---------------------------------------------------------------------------------------------------------

## 2. Per-pitch kernel (physics_sim/physics.py `simulate_pitch`, 564-981)

### 2.1 Inputs the engine builds per PA (engine.py:4320-4381)
```python
"repertoire": pitcher.repertoire or {"fb": 50},
"velocity": 83.0 + (pitcher.arm * 0.2),          # engine.py:4329  (fastball mph)
"control": pitcher.control * command_factor,      # 4379 (fatigue-scaled, per pitch)
"movement": pitcher.movement * movement_factor,   # 4380
"fatigue_factor": velocity_factor,                # 4381
"hand": pitcher.throws, "vs_left": pitcher.vs_left
```
The batter context also reads the pitcher (engine.py:3168): `eye = batter.eye*0.8 + (100 - pitcher.control)*0.2`.
This uses **raw** control, not the fatigue-scaled value.

### 2.2 Pitch objective and pitch type
- Objective (attack/edge/chase/waste/putaway) depends on count and game context only, not on any rating
  (physics.py:235-285).
- Pitch type (physics.py:297-357): `weight = max(1, rating)` times count and objective multipliers. A higher
  pitch rating means **proportionally more usage**: a 70 pitch is thrown 1.4x as often as a 50. That is the
  only usage effect. Knobs: `pitch_seq_*` (config.py:507-517), `pitch_objective_group_bias` (243-249),
  `pitch_seq_repeat_scale` 0.85, floor 0.4.

### 2.3 Velocity (arm)
```python
velocity = base_velo * velocity_scale * fatigue          # physics.py:441-443
velocity += pitch_type_velocity_offset[pitch_type]       # physics.py:592-596
```
Offsets (config.py:59-67): fb 0, si -1, sl -6, cu -8, cb -11, scb -10, kn -18. Fastball velocity runs 89 mph
(arm 30) to 103 mph (arm 100), so **+10 arm = +2.0 mph**. Calibration measured +1.7 mph per 10 for the
all-pitch average (r = 0.60).

Where velocity enters:
1. Whiff: `+ max(0, (v-90)/20) * whiff_velocity_scale(0.062)` (physics.py:773-775). This is +0.0062 whiff
   per 2 mph, **only above 90 mph**, so it is zero for nearly every non-fastball (sl at 87, cb at 82).
2. Contact difficulty: `+ max(0, (v-90)/20)` (physics.py:808). This widens the timing and barrel error SDs.
3. **EV: `ev_base = velocity*ev_pitch_weight(0.48) + bat_speed*0.7`** (physics.py:847-850): **+1 mph pitch
   = +0.48 mph EV before quality scaling.**
4. HBP injury context only (engine.py:4502).

Net effect, **wrong-signed**. Sweep (pitch_sweep.txt):

| arm | FB mph | K | BB | HR/PA | EV | OPS against |
|---|---|---|---|---|---|---|
| 30 | 89 | .239 | .092 | .022 | 86.8 | .670 |
| 50 | 93 | .240 | .094 | .027 | 88.1 | .698 |
| 70 | 97 | .244 | .093 | .031 | 89.2 | .722 |
| 90 | 101 | .246 | .090 | .035 | 89.3 | .750 |

Calibration season OLS per +10 arm: K +0.0009, HR +0.0023, EV +0.70 mph, ERA +0.09, with r(arm, K) = 0.06.
**Velocity is a liability.** Generator archetype `power_sp` uses arm band 0.8-0.98
(playbalance/player_generator.py:570-580), so "power" pitchers are built worse. Real MLB: velocity is one of
the strongest K% predictors, and EV against falls slightly with velocity.

`arm` is also used for: reliever "stuff" score (engine.py:706), steal deterrence and pickoffs (§5).

### 2.4 Location: control and movement -> command error and zone%
```python
zone_target = zone_target_base(0.36) + (control-50)*zone_target_control_scale(0.0009)
              + (strikes-balls)*(-0.02) + objective_zone_adjust          # physics.py:621-627, clamp .15-.85
miss = (100-control)/100
mult = 1 + miss*command_error_scale(3.1) + max(0,(movement-50)/50)*movement_command_penalty(0.4)
sd_x, sd_y = 0.09*mult, 0.12*mult                                            # physics.py:446-457
loc = target + gauss(sd) + break
```
- Command SD (ft) at control 30 / 50 / 70 / 90: x 0.29 / 0.23 / 0.17 / 0.12, y 0.38 / 0.31 / 0.23 / 0.16. The
  plate half-width is 0.708 ft, so command noise is large and the target choice is close to random.
- `zone_target_control_scale` 0.0009 means **+10 control = +0.9 pp intended zone rate**, which is negligible.
  Measured zone% sd across calibration pitchers is only **0.012** (r with control 0.34). MLB pitcher zone%
  sd is about 0.025-0.03.
- Movement adds command error above 50 only (one-sided), +0.08 x-SD per 10 pts at 50+.

### 2.5 Break (movement + pitch rating)
```python
movement_factor = 1 + (movement-50)/100 * break_movement_scale(0.6)
quality_factor  = 1 + (pitch_quality-50)/100 * break_quality_scale(0.4)
break = base_break[type] * break_scale * movement_factor * quality_factor + gauss(0, pitch_break_sd 0.04)
```
(physics.py:113-153). Base magnitudes: fb 0.072, si 0.134, sl 0.277, cb 0.333, cu 0.261, scb 0.269,
kn 0.089 ft (kn sign random). +10 movement = +6% break; +10 pitch rating = +4% break.

Break enters:
- whiff `+ min(1, break/0.4) * whiff_break_scale(0.068)`: fb +0.012, cb +0.057;
- `contact_base -= break*break_contact_penalty(5.0)`: 0.4-1.7 contact points, tiny;
- difficulty `+ min(1, break/0.4)*0.5`.

The noise SD of 0.04 is about half of the fb break, so a fastball's "movement" is mostly noise.

### 2.6 Pitch quality: where control, movement and pitch rating meet
Before the swing: `pitch_quality = repertoire[type]`, plus `(vs_left-50)*platoon_pitcher_scale(0.25)` **only
when the batter hits from the left**, then clamped to 1-100 (physics.py:586, 604-609).
On a swing it is **overwritten** (physics.py:767-768):
```python
pitch_quality = control*0.4 + movement*0.4 + pitch_quality*0.2
pitch_quality *= pitching_dom_scale     # multiplicative, NOT centred on 50
```
`pitch_quality` (pq) then feeds **seven** terms:

| Term | Code | Per +10 pq |
|---|---|---|
| whiff | `+ max(0,(pq-50)/100)*0.072` (769-772) | +0.0072, **zero below 50** (one-sided) |
| contact | `contact_base = contact - (pq-50)*0.4` (783) | -4 contact pts, about -0.07 contact_prob after /k_scale |
| difficulty | `+ max(0,(pq-50)/100)` (807) | widens timing/barrel SD by 6% each |
| EV quality #1 | `(contact_base-50)/250` (859-861) | -1.6% |
| EV quality #2 | `*max(0.75, 1-(pq-50)/250)` (862) | -4% |
| contact_quality (EV, LA noise) | through timing/barrel error | indirect |
| foul rate | `*(1 + max(0,(pq-50)/50)*0.2)` (904-907) | +4% fouls |

pq is counted three times in EV (#1, #2, and difficulty -> contact_quality), so **pitchers control contact
quality strongly**: calibration EV-against sd 2.1 mph, R^2 0.77 on ratings. MLB pitchers have far less
control over EV against (pitcher EV-against sd is about 1 mph; the DIPS principle).

Effective weights on pq: **control 0.4, movement 0.4, the chosen pitch's rating 0.2**. A pitcher's whole
repertoire rating spread is therefore worth half of control's.

### 2.7 Control, the other channels
- Batter eye: `eye = 0.8*eye + 0.2*(100-control)` (engine.py:3168). +10 control means -2 batter eye: zone swing
  -1 pp, chase +0.9 pp (physics.py:701-702). This matches the calibration chase coefficient of +0.0088 per 10.
  It also compresses every batter's eye spread by 20% (a hitter-side side effect).
- HBP: `hbp_rate*(1 + (50-control)/120)*(1+miss)` (physics.py:680-683).
- Wild pitch: `wild_pitch_rate*(1 + (50-control)/120)` (engine.py:2237). Dropped third strike: k-in-dirt
  `*(1 + (50-control)/150)` (engine.py:2275). Balk: `*(1 + (50-control)/200)` (engine.py:5303). All use raw
  control.

### 2.8 Measured marginal effects

PA kernel, average batter (pitch_sweep.txt):

| Scenario | K | BB | HR/PA | EV | OPS |
|---|---|---|---|---|---|
| baseline (all 50) | .240 | .094 | .027 | 88.1 | .698 |
| control 30 / 70 / 90 | .189 / .311 / .383 | .107 / .079 / .068 | .045 / .013 / .004 | 92.2 / 83.6 / 79.1 | .871 / .544 / .425 |
| movement 30 / 70 / 90 | .197 / .289 / .354 | .091 / .102 / .106 | .050 / .012 / .004 | 92.5 / 83.3 / 78.6 | .876 / .570 / .464 |
| all pitch ratings 30 / 70 / 90 | .217 / .266 / .295 | .089 / .096 / .099 | .038 / .018 / .012 | 90.4 / 85.5 / 83.1 | .785 / .629 / .569 |
| fb only 30 / 90 | .238 / .261 | | .029 / .019 | | .713 / .637 |
| repertoire fb only / fb+si / fb+sl / fb+cb / fb+cu / fb+kn (all 50) | .232-.243 | | .041 / .036 / .030 / .025 / .028 / .025 | 91.1 / 90.7 / 89.1 / 87.4 / 88.8 / 87.1 | .795 / .754 / .729 / .689 / .707 / .696 |

Season OLS per +10 pts (calibration; analyze_out.txt):

| Outcome | arm | control | movement | mean pitch rating | R^2 |
|---|---|---|---|---|---|
| K% | +0.09pp | **+2.47pp** | +1.96pp | +1.29pp | 0.31 |
| BB% | -0.04pp | -0.79pp | +0.14pp | +0.25pp | 0.06 |
| HR/PA | +0.23pp | -0.65pp | -0.80pp | -0.38pp | 0.34 |
| BABIP | +.002 | -.008 | -.005 | -.006 | 0.05 |
| ERA | **+0.09** | -0.87 | -0.65 | -0.25 | 0.35 |
| EV against | **+0.70** | -2.20 | -2.12 | -1.03 | 0.77 |
| zone% | 0 | +0.8pp | -0.4pp | 0 | 0.15 |
| velocity (all pitches) | +1.72 | +0.36 | -0.06 | +0.24 | 0.37 |

On alpha (same harness) every R^2 is 0.00-0.05. In the live-path 910-game dataset, K% vs control r = 0.13 and
endurance vs ERA r = +0.18 (wrong sign, noise).

Dispersion (calibration, >= 40 IP): K% sd 0.035 (MLB qualified 0.055), BB% sd 0.017, ERA sd 1.07 (mixed SP/RP).
Alpha: K% sd 0.025, mostly binomial noise (about 0.015-0.02 at these BF counts).

### 2.9 Pitcher vs_left (platoon)
`pitch_quality += (vs_left-50)*0.25` only vs LHB (physics.py:604-608). After the 0.2 swing weight that is
**0.05 pq per vs_left point**; +20 vs_left equals +2.5 control vs lefties. There is no "vs right" counterpart.
It is also used in bullpen matchup scoring: `(vs_left-50)/25` per upcoming LHB (engine.py:763-764), weighted by
`bullpen_platoon_weight` 2.0. **Dead in alpha** (blank for all pitchers, so 50).

---------------------------------------------------------------------------------------------------------

## 3. Fatigue within a game

### 3.1 Limits (endurance) — engine.py:257-284
```python
fatigue_start = 60 + 0.4*endurance                    # fatigue_start_base, _endurance_scale
fatigue_limit = fatigue_start + 14 + 0.05*endurance   # fatigue_limit_base, _endurance_scale
CL/SU/MR: start *= 0.25; limit = start + max(5, limit-start_scaled)*0.20
LR:       start *= 0.50; limit = start + span*0.45
```
| endurance | SP start / limit | MR/SU/CL start / limit | LR start / limit |
|---|---|---|---|
| 25 | 70 / 85 | 17.5 / 31 | 35 / 58 |
| 50 | 80 / 96.5 | 20 / 35 | 40 / 66 |
| 75 | 90 / 108 | 22.5 / 39 | 45 / 73 |

+10 endurance gives +4 pitches before fatigue and +4.5 to the hard pitch cap. Calibration starters: pitches/G
slope **+2.6 per 10 endurance** (r 0.42); 87.0 pitches and 16.0 outs per start (MLB 86 / 15.6). Alpha starters:
endurance sd 0.9, r = 0.05, so **dead**; 83.6 pitches and 14.4 outs.

**Role strings `MR1`, `MR2`, `MR3`, `RP` match neither branch, so they get starter limits** (finding #3).

### 3.2 Penalty — engine.py:471-486
```python
raw = (pitches - fatigue_start)/(limit - start) * fatigue_decay_scale(1.4) * (1 + (50-durability)/200)
penalty = min(1.5, raw) + pregame_penalty (capped 1.5 total, engine.py:4338-4339)
velocity_factor = max(0.85, 1 - 0.15*penalty)   # multiplies MPH
command_factor  = max(0.60, 1 - 0.30*penalty)   # multiplies control
movement_factor = max(0.65, 1 - 0.25*penalty)   # multiplies movement
```
- The ramp spans only 14-19 pitches; the penalty reaches 1.0 about 12 pitches past fatigue_start.
- At penalty 1.0, **control 50 -> 35 and velocity 93 -> 79 mph**. Sweep fatigue rows: penalty 0.5 gives K .205,
  OPS .749; 1.0 gives K .175, OPS .757; 1.5 gives K .164, OPS .829. The velocity loss *lowers* EV (wrong-signed
  §2.3) and offsets some of the command loss.
- Measured (calibration, 600 g; FB only): 0-19 pitches 94.2 mph; 20-39 91.5 (relievers past their 20-pitch
  start); 80-89 90.1; **90-99 82.9; 100+ 79.8**. MLB in-game fade is about 1 mph.
- Multiplying ratings is not centred: `control*0.6` takes a 70-control pitcher down 28 points and a 40-control
  pitcher down 16. Elite command is punished more in absolute terms.
- The durability term is +/-7 to -16% on slope for durability 36-82 (minor).

### 3.3 Hooks — engine.py:608-696, called at 5519 only after a PA with outs < 3
- Reliever outs caps (`closer_max_outs` 3, `setup_max_outs` 3, `middle_reliever_max_outs` 4,
  `long_reliever_max_outs` 6) apply only to the literal roles CL, SU, MR, LR.
- Hard cap: `pitches >= fatigue_limit` (+10 shutout and +8 one-hitter after 7 IP).
- Score: runs >= 5, hits >= 7, walks >= 3.5, consecutive hits >= 3, inning runs >= 2.8, inning walks >= 2.6,
  inning baserunners >= 4; +0.8 if penalty >= 0.8; +0.7 if TTO >= 3 and penalty >= 0.55. Multiplied by
  aggression 1.3 (x1.1 close, x1.2 postseason). Hook when `score - leash >= hook_threshold 1.9`.
- **No ratings enter the hook** except through fatigue_limit (endurance) and the results.
- **No check at the inning boundary**: `if outs >= 3: continue` (5490-5491) skips the check, and a new half-inning
  does not run one. The exception is the 9th-inning closer insertion (3772-3853). Result: a CL/SU with 3 outs
  starts the next inning (CL 4-out outings 12%), and a starter who hit his cap on the final out pitches to
  another batter.

### 3.4 Reliever choice — engine.py:699-831
```python
stuff = (control + movement + arm)/3          # arm is wrong-signed for outcomes; repertoire ignored
high:  stuff*1.1 + endurance*0.1 (+8 CL/SU with lead, +3 MR, -4 LR/SP; tied +4 SU; trailing -6 CL)
long:  endurance*0.7 + stuff*0.3 (+6 LR/SP, -6 CL/SU)
mid:   stuff*0.6 + endurance*0.4 (+2 MR/SU, -4 CL)
score *= freshness (1 - min(0.7, pregame_penalty)); + matchup*2.0
```
- The candidate filter is `available and not used`. If it is empty, **the current pitcher stays in**
  (783-784). This fired on 1,450 of 4,681 hook calls in calibration (finding #6).
- **Closer insertion at the 9th inning** (3792-3830) takes `available_closers`, **else any unused CL even if
  unavailable** (finding #4). The appearance cap (`closer_max_appearances_ratio` 0.45), the third-consecutive-day
  block and the rest table are all bypassed there.

---------------------------------------------------------------------------------------------------------

## 4. Rest and recovery between games

### 4.1 Physics UsageState (physics_sim/usage.py)
- `reliever_rest_days(pitches)` (30-45): <= 12 pitches 0 days, <= 25 1 day, <= 40 2 days, otherwise 3. Knobs
  `reliever_rest_*_max_pitches` 12 / 25 / 40.
- Starters: `starter_rest_days` 4 (engine.py:294-298).
- Gate (engine.py:504-556): not rested means `available=False` plus pregame penalty `0.35*deficit/required`.
  Third consecutive day blocked for all relievers (`reliever_max_consecutive_days` 2). CL appearance cap
  `0.45*(game_day+1)`.
- Debt: `+= pitches*0.35*usage_multiplier(1.0-1.25)` plus `3*(consecutive-1)` (usage.py:112-133). Recovery per
  day is `40 + 0.8*durability` (usage.py:77-92). **The largest possible outing debt (about 52) is below the
  smallest daily recovery (about 56)**, so debt is always 0 the next day. Consequences: `fatigue_debt_penalty_scale`,
  `fatigue_debt_start_reduction`, `fatigue_debt_limit_reduction` and the durability recovery term are inert
  (finding #10).
- The live path keeps this state in a **module global per process** (game_runner.py:55-87). `game_day` is the
  index of the date *within this process*, and the state resets on a new process, league or year. A new cloud
  batch starts with every reliever "rested" in physics. Parallel workers get a payload snapshot
  (game_runner.py:1124-1134).

### 4.2 PitcherRecoveryTracker (utils/pitcher_recovery.py), persisted in pitcher_recovery.json
- Picks the **starter** (`assign_starter` 779-830), which the engine honours as `forced_starter_id`
  (engine.py:388-407). The rotation is the owner's five, then free starters by endurance (`choose_rotation`
  84-137).
- Reliever rest uses the same table through `_rest_days` (140-213). `_role_key` (387-393) **does** map
  MR1->MR and RP->MR, unlike the engine.
- Budget `max_pitches = endurance*pitchBudgetMultiplier` and recovery percentage (427-466) only produce
  `available_pct`. game_runner stores it as `budget_available_pct` on the Pitcher object (game_runner.py:276-278),
  and **physics never reads it**. In the physics path the budget is cosmetic.
- `bullpen_game_status` availability only **reorders** state.pitchers (game_runner.py:290-323); resting arms are
  still passed to the engine. The engine chooses by score (engine.py:824-831), so the tracker's verdict does not
  gate relievers (finding #12).

---------------------------------------------------------------------------------------------------------

## 5. Hold runner, arm and the running game (pitcher side)

| Effect | Formula (engine.py) | +10 hold_runner | +10 pitcher arm |
|---|---|---|---|
| steal attempt rate | `*(1-(hold-50)/180)*(1-(arm-50)/260)` (1956-1961) | -5.6% relative | -3.8% relative |
| steal success | `-(hold-50)/250 - (arm-50)/300` (2009-2014) | -4.0pp | -3.3pp |
| pickoff attempt rate | `*(0.8+(hold-50)/140)` (1810) | +8.9% relative | none |
| pickoff success | `+(hold-50)/240 + (arm-50)/320` (1822-1825) | +4.2pp | +3.1pp |
| runner lead level | hold >= 70 gives lead -1 (1254-1255) | **cosmetic**: only accumulates `BatterLine.lead` (1281), never read by steal or advance logic | |

Knobs: `steal_pitcher_arm_deterrent` / `_success` 1.0, `pickoff_*` (config.py:436-442), `lead_hold_threshold` 70.
Alpha hold sd 4.1 means about +/-1.6pp of steal success across the league.

---------------------------------------------------------------------------------------------------------

## 6. Durability and injury (pitchers)
- In-game fatigue slope `*(1+(50-durability)/200)` (engine.py:477-478): small.
- Daily recovery (usage.py:88): inert (§4.1).
- Overuse injury (engine.py:3060-3100): gate `pitches >= 80` and `penalty >= 0.6`, then per-PA roll
  `injury_rate_scale(0.1)*injury_overuse_scale(0.19)`, then catalog `0.18*(1+0.45*fatigue)`. The catalog trigger
  `pitcher_overuse` has **no durability modifier** (alpha injury_catalog.json and the fallback at
  services/injury_simulator.py:47-51), so **durability does not affect pitcher arm injuries**. Relievers never
  reach 80 pitches unless mislabelled (MR1-3/RP; see #3), so they never get overuse injuries.
- HBP, collision, swing, fielding and throwing triggers use durability for the *victim*. Pitchers are not in the
  defense map (below), so pitcher fielding injuries do not occur.

---------------------------------------------------------------------------------------------------------

## 7. Dead, cosmetic, saturated or one-sided list

| Item | Status | Where |
|---|---|---|
| pitcher `gf` (gb_tendency) | **DEAD**: launch angle uses only the batter's gf | models.py:117; physics.py:880 |
| pitcher `fa` (fielding) | **DEAD**: the defense map is built from batters only, so pitchers never field | models.py:122; fielding.py:12 has "P" but no PitcherRatings ever enter |
| `PitcherRatings.velocity` field | **DEAD**: set from arm, never read; the engine recomputes 83+0.2*arm | models.py:114; engine.py:4329 |
| runner lead / hold >= 70 | **COSMETIC** (stat only) | engine.py:1231-1281 |
| tracker pitch budget (endurance*mult) | **COSMETIC** in the physics path | pitcher_recovery.py:427-466; game_runner.py:276-278 |
| fatigue debt + durability recovery | **SATURATED to zero** | usage.py:77-133 |
| `movement_scale` knob | **DEAD**, though exposed in the tuning editor | config.py:363; services/physics_tuning_spec.py:179 |
| `zone_half_width`, `zone_half_height` knobs | DEAD (never read) | config.py:26-27 |
| whiff pq term, velocity term | **one-sided** (`max(0, ...)`): below-50 pq or <= 90 mph gives no whiff relief | physics.py:770, 773 |
| movement command penalty | one-sided above 50 | physics.py:453 |
| `pitching_dom_scale` | not centred (multiplies pq, so it shifts the league mean too) | physics.py:768 |
| pitcher vs_left | vs LHB only, 0.05 pq/pt effective; blank in alpha | physics.py:604-608 |
| arm / velocity | **WRONG-SIGNED** (EV up more than whiff up) | physics.py:847-850 |
| fatigue velocity | magnitude about 10x real; wrong-signed via EV | engine.py:483 |
| control | double/triple counted (command SD, pq 40%, batter eye, zone target) | physics.py:446-457, 767; engine.py:3168 |
| pq in EV | triple counted | physics.py:859-862, 806-828 |
| endurance (alpha) | effectively constant for starters (sd 0.9) | players.csv |
| movement (alpha) | constant 52 in the >= 40 IP pool | players.csv |
| kn | no pitcher has it; base break sign random each pitch | physics.py:136-138 |

---------------------------------------------------------------------------------------------------------

## 8. Noise terms vs rating signal
- Command SD 0.17-0.38 ft vs a 0.708 ft plate half-width: the target barely matters, and zone% sd across
  pitchers is 0.012.
- `pitch_break_sd` 0.04 ft vs a fastball break of 0.07: the FB break is mostly noise.
- `exit_velo_sd` 5.0 mph per BIP vs about 2 mph per 10 control. This is fine per BIP but averages out over a
  season, which is why EV-against R^2 reaches 0.77 on wide ratings.
- `launch_angle_sd` 10.5: pitchers have **no** rating that moves launch angle (pitcher gf is dead), so GB/FB
  pitcher profiles do not exist.
- Season sampling: K% binomial sd at 600 BF is about 0.017. On alpha the observed K% sd is 0.025, so true talent
  is about 0.018. On calibration, 0.035 observed means about 0.031 true. MLB qualified K% sd is 0.055, so even
  wide ratings under-disperse strikeouts.

---------------------------------------------------------------------------------------------------------

## 9. Tuning knobs in scope (physics_sim/config.py DEFAULT_TUNING)

| Knob | Value | Line | Role |
|---|---|---|---|
| velocity_scale | 1.0 | 362 | multiplies FB mph |
| pitch_type_velocity_offset | fb 0 / si -1 / sl -6 / cu -8 / cb -11 / scb -10 / kn -18 | 59-67 | per-type mph |
| movement_scale | 1.0 | 363 | **unused** |
| command_variance_scale | 1.0 | 364 | multiplies command SD |
| command_error_base_x / _y / _scale | 0.09 / 0.12 / 3.1 | 40-42 | command SD |
| movement_command_penalty | 0.4 | 43 | |
| break_scale / break_movement_scale / break_quality_scale | 1.0 / 0.6 / 0.4 | 44-46 | |
| pitch_break_base, pitch_break_sd | table, 0.04 | 47-55, 68 | |
| break_contact_penalty | 5.0 | 69 | |
| zone_target_base / control_scale / count_scale | 0.36 / 0.0009 / -0.02 | 84-86 | |
| whiff_base / quality / velocity / break / location / chase | 0.0095 / 0.072 / 0.062 / 0.068 / 0.042 / 1.04 | 89-94 | |
| foul_pitch_quality_scale | 0.2 | 96 | |
| ev_pitch_weight | 0.48 | 354 | **velocity -> EV (the wrong-sign source)** |
| pitching_dom_scale | 1.0 | 18 | |
| platoon_pitcher_scale | 0.25 | 505 | |
| hbp_rate, wild_pitch_rate, balk_rate | 0.003, 0.0035, 0.0004 | 99, 300, 471 | |
| fatigue_decay_scale | 1.4 | 365 | |
| fatigue_start_base / _endurance_scale | 60 / 0.4 | 366-367 | |
| fatigue_limit_base / _endurance_scale | 14 / 0.05 | 368-369 | |
| fatigue_debt_scale / penalty / start_red / limit_red | 0.35 / 0.3 / 0.2 / 0.25 | 370-373 | inert (§4.1) |
| daily_recovery_base / durability_scale | 40 / 0.8 | 374-375 | |
| starter_rest_days | 4 | 376 | |
| reliever_rest_b2b / one_day / two_day max pitches | 12 / 25 / 40 | 379-381 | |
| closer_availability_ratio | 1.3 | 382 | |
| short_rest_penalty | 0.35 | 383 | |
| reliever / long_reliever fatigue start, limit scales | 0.25 / 0.2 ; 0.5 / 0.45 | 384-387 | |
| closer / setup / middle / long max outs | 3 / 3 / 4 / 6 | 388, 392-394 | |
| reliever_max_consecutive_days | 2 | 390 | |
| closer_max_appearances_ratio | 0.45 | 391 | bypassed at the 9th-inning entry |
| consecutive_usage_penalty | 3.0 | 407 | |
| hook_threshold, hook_aggression_scale, close/postseason scales | 1.9, 1.3, 1.1 / 1.2 | 523-526 | |
| hook_runs / hits / walks / consecutive / inning runs / inning walks / baserunners | 5 / 7 / 3.5 / 3 / 2.8 / 2.6 / 4 | 535-541 | |
| hook_fatigue_penalty / soft / tto | 0.8 / 0.55 / 0.7 | 542-544 | |
| shutout / one-hit pitch bonus, leash bonuses, nohit / perfect limits | 10 / 8; 0.4 / 0.3 / 0.6 / 0.8; 160 / 170 | 546-553 | |
| bullpen_platoon_weight | 2.0 | 506 | |
| injury_overuse_pitch_min / penalty_threshold / overuse_scale | 80 / 0.6 / 0.19 | 479-486 | |
| steal_pitcher_arm_deterrent / _success, pickoff_* | 1.0, table | 290-291, 436-442 | |

---------------------------------------------------------------------------------------------------------

## 10. Suggested fix directions (not applied)
1. Velocity: drop `ev_pitch_weight` toward about 0.1-0.2 (or centre it: `(v - league_mean)*w`). Raise
   `whiff_velocity_scale` and make it two-sided, relative to the pitch type's own mean, so arm drives K.
2. Fatigue velocity: `velocity_factor = 1 - 0.015*penalty` (a 1-2 mph fade) instead of 15%.
3. Normalize staff roles in the engine: map `MR\d` to MR and RP to MR at engine.py:271/629/709 (or at
   game_runner.py:1103-1118). Add an MR1-3 staff to the calibration fixture so the KPI harness covers it.
4. Closer entry: respect `available` (drop the `elif closer_candidates` fallback at engine.py:3814-3820).
5. Add an inning-start hook check (reliever at its outs cap, starter at the pitch cap).
6. When no reliever is available, pick the least-tired arm rather than leaving an exhausted pitcher in.
7. Re-split control: raise `zone_target_control_scale` (for example 0.004-0.006) and reduce control's weight
   in `pitch_quality` (0.4 -> about 0.15), so control mainly drives BB and called strikes and movement plus pitch
   ratings drive whiffs and contact.
8. Remove the double EV pq term (physics.py:862) or the contact_base pq term, to shrink pitcher EV control
   toward DIPS levels.
9. Give pitcher gf a launch-angle term; read pitcher fa for comebackers and bunts; delete or wire
   `movement_scale`.
10. Make the debt-recovery arithmetic meaningful (lower `daily_recovery_base` to about 15-20) or remove the
    knobs; add durability to the overuse trigger.
11. Alpha data: re-spread the compressed pitcher ratings (movement, control, endurance, arm) and fill the
    pitcher `vl` column, or no pitching mechanism can show up in that league's stats.
