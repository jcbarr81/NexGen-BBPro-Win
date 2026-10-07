# Release 0 design decisions (owner, 2026-10-06)

Decisions on the open design calls in REPORT.md section 6, "Release 0". Each
entry records the choice and what it means for the fix releases.

## 1. How the 2026 alpha-test season counts — KEEP AS-IS

The 710 live games played on since-fixed engines (pre-7.45.0 power,
pre-7.45.6 minor leaguers in MLB games) stand as played. No split
leaderboards, no exhibition tag, no reset. Save a snapshot of the live
`season_stats.json` at the boundary so pre-fix and post-fix can always be told
apart (REPORT M13).

## 2. Absolute vs league-relative ratings — LEAGUE-RELATIVE

The engine reads each rating as 50 + (rating - league mean), with the mean
taken over ACT players, separately for hitters and pitchers, computed once per
season (no mid-season jumps). Displayed ratings are unchanged; only the
engine's internal (rating - 50) terms are re-centred. Fixes alpha's +0.5 R/G
without touching player data (REPORT H3), keeps the run environment stable as
talent drifts over seasons, and makes one knob set valid for every league.
Implication: the calibration fixture must be re-centred the same way, so both
fixtures test the same engine.

## 3. Hitter speed distribution — KEEP ARCHETYPE TIERS

Speed stays tiered (most hitters ~50, "fast" at 70, "burner" at 85) rather
than a continuous N(50,10). Implications: the Release 2 generator-built fixture
must reproduce the tier spikes (alpha has 15.5% at SP >= 70; the calibration
fixture tops out at 67), and the Release 4 steal / extra-base / triple curves
are calibrated around the tiers, not a bell curve. Release 7 does NOT
re-spread speed.

## 4. Contact and balls in play — SMALL BABIP EDGE

Contact gets a small hit-on-ball-in-play channel, about +.010 BABIP per 10 CH
(more line drives / squarer contact), on top of its strikeout effect. Today
contact reaches AVG only through K (BABIP vs CH r ~0; REPORT dead-ratings
table, L6). Power remains the main exit-velocity lever. Gate: `corr_avg_contact`
>= 0.5 and true AVG sd toward ~.021 (Release 5/6).

## 5. Below-average power — STEEPER

Power below the knee gets a real slope so slap hitters (PH 30-40) hit like
MLB's bottom decile (about 4-9 HR/600 PA) and the bottom quintile lands near
0.45-0.65x the median (today 0.87-0.90x; REPORT M3). The league HR level is held
by retuning; `corr_hr_power` must stay >= 0.6. Override A (scale 0.40, knee 0.55)
alone does not lower the floor, so the curve shape below the knee changes too.

## 6. What vl means — PERSONAL PLATOON SPLIT

vl is a hitter's split relative to a normal platoon split: 50 = typical,
higher = handles LHP better than typical. The engine's handedness bonus is the
single source of the normal split (made asymmetric, RHB smaller than LHB, per
REPORT H7). The generator stops adding +4/-4 vl by batting side, and existing
leagues' hitter vl is recentred by bats (a data change -> Release 7, MAJOR).
Switch hitters get the full bonus.

## 7. LHP vs RHP at equal ratings — EQUAL ON AVERAGE

In a typical league, a LHP and a RHP with the same ratings perform the same
(MLB league ERAs by hand are nearly identical). Get there by moving the
generator's batting-side mix toward MLB's, then a small pitcher-side offset if
a gap remains after the H7 platoon fixes (about 0.4 R/9 left over otherwise).
Matchups still matter game to game. Gate: LHP-minus-RHP RA9 within +/-0.15.

## 8. Staff size — MLB 26-MAN ROSTER, 13 PITCHERS / 13 POSITION PLAYERS

Adopt MLB's 26-man active roster (max 13 pitchers). Touches everything keyed
to 25: `ACTIVE_ROSTER_SIZE` (utils/roster_loader.py), roster validation caps and
the season gate, auto-assign (targets 13P / 13H), CPU roster management and
call-ups, the organisation limit, roster UI copy, help/tutorials, and every
existing league's rosters (owners add a player; CPU teams auto-fill). A
user-facing feature change -> its own MINOR release, separate from the engine
work; the bullpen fixes (Release 3) are tuned against 13-man staffs.
Also satisfies the H9 fix's "keep >= 13 position players active".

**Implementation calls (owner, 2026-10-06), for 7.46.0:**
- **Organisation limit 51** (26 + 15 + 10). Nobody is over a cap on deploy
  and nobody has to cut; owners fill spot 26 by promoting from AAA or signing.
- **Max 13 active pitchers: warn on a move, block at the sim.** A move or
  trade that makes a 14th active pitcher warns (owners can promote, then
  demote); the swap check, the sim gate and the compliance banner treat it as
  an error. "CPU handle it" (gaps mode) fixes it by optioning a pitcher. A
  read-only audit of the live leagues found no owner team above 13, so no
  grace period is needed. No two-way exemption (no two-way data);
  injured-but-active pitchers count.
- **September: 28 active, at most 14 pitchers (MLB).** The playoff revert
  already options owners' extra players back to the size cap; it now also
  options the 14th pitcher, logged as a transaction. Optioning, never cutting.
- **Staff slots stay at 11 for now.** The 12th and 13th pitchers are unslotted
  relievers (the Lineups page says so); MR4/MR5 arrive with the Release 3
  bullpen work, together with the engine's relief-role normaliser.
- Taken as recommended: every league switches on deploy (no per-league
  setting; there is no active-roster minimum, so a 25-man roster stays
  legal); the hitter minimum stays 11; CPU clubs converge to 13P/13H through
  the daily upkeep plus a preseason -> regular-season pass, never touching
  owner teams; owners learn of the open spot through a non-blocking
  notification, an action item, a Roster page badge and a news post; one
  shared pitcher check (`utils.roster_rules.counts_as_pitcher`).

## 9. Off days and rest — CALENDAR DAYS

Pitcher and batter rest counts calendar days, so league off days rest players
(today `game_runner.py:55-87` counts game-date indices). The engine's
in-memory rest state (REPORT M18) is persisted or rebuilt from the recovery
tracker by league + calendar date, so one-day and week-long sim batches give
the same bullpen outcomes. Release 3.

## 10. Pitch-type grades — GRADES DRIVE "STUFF"

Pitch quality shifts from 0.4 control / 0.4 movement / 0.2 grade
(`physics.py:767`) toward about 0.15 control / 0.30 movement / 0.55 the pitch's
own grade, and pitch quality gains a chase term (swing decisions read the
pitch). Control's main job becomes command (walks, location) per H4. Gate:
mean pitch grade std beta on K >= 0.35 (Release 6). Ships with the arm/velocity
and fatigue retune (H6 + H10).

## 11. Extra innings — MODERN MLB, PER-LEAGUE OPT-OUT

Ship S3-04: automatic runner on 2nd from the 10th in the regular season only
(`extra_innings_runner`, `config.py:304`, today 0.0), none in the postseason.
No ties ever: replace the 18-inning cap (`engine.py:5560-5589`) with a high
safety guard (~30) and never allow a postseason tie (`playoffs.py:1014-1019`).
A league setting turns the runner off. Release 3 (rules) with a settings UI
toggle + help text.

## 12. Positional value of defense — MLB SPECTRUM AND SIZE

SS and CF are the premium gloves, then 2B/3B, then LF/RF, 1B least. One fa SD
is worth about 5-7 outs above average per 150 G at each position (today 10-28,
outfield > SS; REPORT M22). Range scales the deviation (rating - 50), infield
pairs get per-position weights (e.g. SS .40 / 3B .30 / 2B .35 / 1B .15), CF gets
a wider zone; team DER sd ~0.010-0.012. OVR's defense weights (H8) are derived
from the measured run values after this and the spray fix (M4). Release 6.

## 13. Pitcher HR suppression vs hitter Power — HITTERS OWN HRS, LOG5

A pitcher's HR effect is about half a hitter's (pitcher/hitter HR true-sd ratio
<= 0.5, MLB ~0.4-0.5x; today ~1x) and combines multiplicatively (log5) for every
hitter: aces suppress HRs, sluggers still hit them, average hitters occasionally
homer off aces. Pitch quality feeds exit velocity through ONE path, not three
(REPORT M21). Gate: PH x pitcher-composite HR log5 residual within +/-0.3 logit
over p5-p95. Must ship BEFORE any pitcher-rating re-spread (Release 7).

## 14. Injury replacement — DEPTH CHART FIRST (added by the owner)

When a player is injured, the team's depth chart is consulted BEFORE any
promotion or other roster change:
1. The next healthy player behind him at that position who is already on the
   active roster takes his place in the lineup. No roster move.
2. The open active-roster spot: owner teams leave it open (the owner decides;
   a short ACT roster is legal - the season gate checks maximums and the
   position-player minimum only). CPU teams fill it with a position-appropriate
   call-up: a depth-chart-listed minor leaguer first, never a pitcher for a
   position player.
3. Only if no active player at that position is available does a promotion
   happen, again depth-chart-listed minor leaguers first, then same-position
   minor leaguers from the team's OWN organisation. Never another team's
   players (the H9 root cause), never a pitcher for a hitter.
4. Emergency only: if a team cannot field nine position players, the engine
   promotes from its own AAA/Low-A position players as a recorded transaction,
   owner teams included (the alternative is an unplayable game).
5. Every team without a depth chart (17 of 20 in alpha-test) gets a default one
   generated from its roster and positions; owners can edit it on the Depth
   Chart page.

Today `services/depth_chart_manager.promote_depth_chart_replacement` uses the
chart only to pick a minor leaguer to promote and SKIPS backups already on the
active roster; with no promotion it falls back to `promote_replacements`, which
pops AAA[0] -- often a pitcher. This is part of the Release 1 H9 hotfix.

## Effect on the release plan

- Release 1 (H9 stall hotfix, stat keys, OVR) goes first; the H9 hotfix now
  implements decision 14 (depth chart first, default charts for every team).
- NEW: a separate MINOR release for the 26-man roster (decision 8), before the
  bullpen work so Release 3 is tuned against 13-man staffs.
- Release 2's new fixture: generator-built, league-relative ratings (2),
  archetype speed tiers (3), 26-man / 13-pitcher rosters (8), MLB batting-side
  mix (7).
- Release 3 adds calendar-day rest (9) and the extra-inning rules + league
  toggle (11).
- Release 4 calibrates steals / triples / extra bases around speed tiers (3).
- Release 5 adds the contact BABIP channel (4), the vl split + asymmetric
  platoon bonus (6, 7).
- Release 6 adds the below-knee power slope (5), pitch-grade-driven stuff (10),
  the MLB defensive spectrum (12) and single-path, log5 HR suppression (13).
- Release 7 (MAJOR, needs confirmation) no longer re-spreads speed (3);
  recentres hitter vl by bats (6).
