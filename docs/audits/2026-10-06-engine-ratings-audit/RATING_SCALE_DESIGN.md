# Rating scale design: stored ratings on the full 1-99 scale

Design pass 2026-10-13, read-only, on 7.51.1 (prototypes in memory; the session scratch folder `r6/respread/` holds the code and outputs). It follows the owner's decision that ratings must use the full scale (`DECISIONS.md`, "Release 6 owner decisions", items 5, 6 and 12 to 15). Nothing here is built except the aging pause (7.51.2).

**Owner decisions taken on this design (2026-10-13):** yearly aging paused now (shipped 7.51.2); screens show the stored number everywhere and the percentile blend goes away, with overall rating stretched the same way; potentials stay hidden; alpha-test's bunched ratings are spread at the same switch, announced separately. Taken as recommended without a question: an average regular is 50; the top of the Power curve is lifted so Power 90 with average Contact hits 45 home runs and Power 99 with Contact 80 hits 55; gloves and arms are stretched modestly and tendencies are left alone; no age shape is imposed at the switch. Decision 3 below ("start showing potential") was declined. The league-wide yearly correction in section 3 is not agreed: tune the development model until it is stationary instead.

The brief as delivered follows.

---


**Verdict:** the idea works, and the scale change is provably play-neutral. Five leagues were stretched and un-stretched at the engine's row loader; every one reproduced its generation 5 season byte for byte. Three things need attention before it ships:

- **Aging is broken today and has never run in a live league.** `playbalance/aging.py` adds an uncapped table at every rollover (Contact +18 at age 18, Power +11 at 25, one pitch ×1.35). Simulated on a stats-test copy, one rollover takes Contact sd from 5.1 to 10.0 and puts 95 fastballs at 99. This is independent of the scale work and should be disabled now.
- **Owners do not see stored ratings today.** `utils/rating_display.py:300-380` shows `0.5*raw + 0.5*(35 + percentile*64)`, clamped 35-99, so a stored 65 already displays as about 82 (arithmetic).
- **Leaving consumers alone reshuffles the economy.** Running the salary curve on stretched ratings moves hitters' market value +35% and sends 70 players to the $0.8M floor (arithmetic, stats-clean).

All scratch work is in `...\scratchpad\r6\respread\`. The repo was not touched.

## 1. The mapping

**Recommendation:** a fixed, piecewise-linear map per rating with integer slopes, the same constants for every league. It is a refinement of "linear about 50".

- **Why not rank-to-quantile.** It cannot be inverted by constants, cannot separate ties (alpha's movement is 52 for every active arm), and makes a development point worth a league-dependent amount.
- **Why integer slopes.** Every integer engine rating maps to an integer and back exactly. Slopes of 2.5 or 2.75 leave up to 0.2 engine points of rounding error; the season is then statistically the same but not identical, and the byte-identity test is lost.
- **Why a different slope on each side of the pivot.** One slope per rating cannot hold today's tails. Eye at ×5 clips 12 stats-clean hitters at 1; fielding at ×2 cannot fit 23-76 into 1-99. Draft-scaled prospects create the long low tail.
- **Why a top knee on Contact, control and movement.** Slope 3 all the way clips alpha's Contact 67-73 and stats-clean's control 69 and movement 72. Two clipped regulars on the flat fixture were enough to change the season (see section 2).

`stored = 50 + k*(engine - pivot)`, with `k` chosen by segment:

| Rating | Pivot | Slope below / above pivot | Top knee (slope 1 above) | 99 means engine | New league today (sd, range) | After (sd, p99, max) |
|---|---|---|---|---|---|---|
| Contact | 50 | 2 / 3 | engine 63 (stored 89) | 73 | 4.1-5.1, 36-66 | 10-13, 77-90, 86-92 |
| Power | 50 | 2 / 3 | none | 66.33 | 5.7, 31-65 | 13.5, 83, 95 |
| Eye | 50 | 3 / 5 | none | 59.8 | 2.9-3.5, 37-58 | 11-13, 80, 90 |
| Hitter fielding, arm | 52 | 1 / 2 | none | 76.5 | 8.7-9.1, 23-76 | 13, 86-88, 92-98 |
| Control | 52 | 2 / 3 | engine 66 (stored 92) | 73 | 5.2-6.0, 31-69 | 13-14.5, 85-89, 94-95 |
| Movement | 54 | 2 / 3 | engine 68 (stored 92) | 75 | 6.3-6.7, 30-72 | 15-16, 82-83, 92-96 |
| Pitcher arm | 56 | 1 / 2 | none | 80.5 | 8.0-8.3, 30-77 | 13, 85-86, 88-92 |

All figures are arithmetic on the league fixture and stats-clean. A pivot above 50 for pitchers keeps an average active arm near 50.

**Not moved:** speed, endurance, hold runner, all pitch grades, pitcher fielding, vs-left, ground-ball and pull tendency, `sc`, durability. They are already wide or are tendencies. Leaving endurance alone also keeps the role threshold (55) and the pitch budget (`endurance * 3.5`, `utils/pitcher_recovery.py:333-367`) valid.

**Clipping:** zero on all three fixtures and stats-clean. Alpha has two values, both on one LOW-level draft pick (Power 23, Eye 33).

**alpha-test before its re-spread:** the bunching stays visible. Eye tops out at 60, control at 68, movement at 56, and active arms read about 46 because alpha's staff sits below the new-league pivots.

**Rounding:** the engine already runs on fractional ratings, because the league-relative shift subtracts two-decimal centres. I found no `int()` or table lookup on a moved rating in `physics_sim/`. Do not round after un-stretching; that would hide development until three stored points accumulate.

**One stored point of development** is worth:
- 1/3 engine point for Contact, Power, control and movement in the main band (1/2 below the pivot, 1 above a knee).
- 1/5 for Eye above 50.
- 1/2 for gloves and arms above the pivot.
- At Power 90 that is about +0.7 HR per 650 PA (Monte Carlo).

**Before and after, stats-clean.** Hitters show Contact / Power / Eye / fielding / arm, with potentials for Contact / Power / Eye. Pitchers show control / movement / arm, with potentials for control / movement. Potentials use the rule in section 3.

| Player (age, position, level) | Before | After | Potential before → after |
|---|---|---|---|
| Rafael Ramos (22 LF ACT), best Power | 54/65/50/43/49 | 62/95/50/41/47 | 64/73/59 → 72/99/59 |
| Quincy Defrates (21 2B AAA), best Contact | 66/39/55/48/58 | 92/28/75/46/62 | 88/52/71 → 99/41/91 |
| James Sidney (24 RF AAA), best Eye | 58/53/58/55/52 | 74/59/90/56/50 | 71/66/67 → 87/72/99 |
| Sung Wang (18 CF ACT), average regular | 50/50/50/43/47 | 50/50/50/41/45 | 65/75/67 → same |
| Fernando Cruz (20 RF LOW), prospect | 53/61/50/42/63 | 59/83/50/40/72 | 77/91/74 → 83/99/74 |
| Sean Laurenceau (19 P LOW), best control | 69/55/60 | 95/53/58 | 86/66 → 99/64 |
| Sonny Marcinkowski (26 P AAA), best movement | 62/72/50 | 80/96/44 | 66/82 → 84/99 |
| Darnell Jefferson (21 P ACT), best arm | 54/57/77 | 56/59/92 | 80/87 → 82/89 |
| Manuel Garcia (27 P ACT), average arm | 52/54/58 | 50/50/54 | 60/64 → 58/60 |
| Roberto Hernandez (21 P LOW), prospect | 68/57/49 | 94/59/43 | 97/82 → 99/84 |

**Before and after, alpha-test** (scale change only, before any re-spread):

| Player (age, position, level) | Before | After | Potential before → after |
|---|---|---|---|
| Filiberto Ambrosia (31 3B AAA), best Power | 51/63/50/52/48 | 53/89/50/50/46 | 53/66/48 → 55/92/50 |
| Leroy Harris (19 CF DL15), best Contact | 73/52/50/52/49 | 99/56/50/50/47 | 97/68/73 → 99/72/73 |
| Jorge Sanchez (28 SS AAA), best Eye | 51/50/52/49/49 | 53/50/60/47/47 | 50/49/47 → 53/50/60 |
| Sung Huang (29 RF ACT), average regular | 50/51/50/52/51 | 50/53/50/50/49 | 50/49/53 → 50/53/53 |
| Clayton Bakko (20 LF LOW), prospect | 57/62/52/50/51 | 71/86/60/48/49 | 81/91/74 → 95/99/82 |
| Henry Schnebly (21 P LOW), best control | 58/48/52 | 68/38/46 | 83/63 → 93/53 |
| Antonio Torres (18 P LOW), best movement | 50/56/49 | 46/56/43 | 74/76 → 70/76 |
| Sung Li (21 P ACT), best arm | 50/52/57 | 46/46/52 | 60/67 → 56/61 |
| Miguel Ramos (24 P ACT), average arm | 52/52/56 | 50/46/50 | 62/65 → 60/59 |
| Young Facchine (17 P LOW), prospect | 40/48/42 | 26/38/36 | 79/88 → 65/78 |

## 2. Proof of play-neutrality

**Where the un-stretch goes:** at the row boundary, not at each read. Rows become `BatterRatings` / `PitcherRatings` in one place, and the rating centres read rows in one place. Everything downstream sees today's engine scale. This matters because fatigue multiplies a rating (`engine.py:4893-4905`) and the fielding, arm and tendency reads are never centred; un-stretching only at `source_shift` would miss them.

Method: stretched copies of each league, the un-stretch patched in memory at every players.csv parse on the harness path (the engine loader, the rating centres, the harness's own readers), 162 games, seed 1, generation 5.

| Run (season) | Result against the stored baseline |
|---|---|
| calibration | identical: 10,007 values, only `runtime_s` differs |
| league fixture | identical: 10,049 values |
| flat fixture | identical: 10,026 values |
| stats-clean | identical (baseline was run without `--gate-set`, so that block is extra) |
| alpha-test | identical (same note) |
| flat, earlier map without the Contact knee (10 values clipped, 2 of them regulars at Contact 67) | not identical: runs 4.521 → 4.528, K .2179 → .2192, HR 1.007 → 1.015. With clipping switched off it is identical again, so clipping is the only cause |
| calibration, engine and centres un-stretched but the harness's own readers not | play identical; 4 gated correlations and 49 report-only values move (for example `bb_pct_per10_eye` 2.46 → 0.59) |
| calibration, no un-stretch at all | runs 4.36 → 4.60, K .219 → .247, HR 1.09 → 1.35 |

The rating centres also came out identical, so there is no ordering constraint between conversion and freezing centres. The last row shows a missed engine reader cannot hide.

**Boundary points (the only engine-side code that changes):**

| Where | What |
|---|---|
| `physics_sim/models.py:49`, `:118` via `data_loader.py:11-24` | Row to engine ratings. Callers: `engine.py:5188`, `playbalance/game_runner.py:1231`, `playbalance/usage_store.py:306` |
| `services/league_rating_centers.py:1523` (`_rating`), `:1530` (`_eye_rating`), `:1463` (`_lineup_value`) | Centres and the "nine best hitters" fallback |
| `scripts/physics_sim_season_kpis.py:475`, `scripts/kpi_extras.py:306`, `:2579` | Harness slope and correlation KPIs |

**Reads behind the boundary (no change needed, listed for coverage):**

| Group | Lines in `physics_sim/engine.py` unless noted |
|---|---|
| Centred by generation 5 | 5022-5028, 5089-5104, 915-917, 4192-4193, 5343-5344, 4596, 4617, 6681-6685, 6986-6990, 7781, 4895-4902 |
| Centred by the Release 4 reader | 3146 (Contact hit edge), 6913 and 7802 (control), 6647, 7832 and 7854 (hold), 7833 and 7905 (arm), speed terms from 2506 |
| Not centred: fielding | 4215, 4732, 4904; `fielding.py:44`, `:151` |
| Not centred: fielder arm | 3014, 4050, 4635, 7026, 7105, 7241, 7597; `fielding.py:102`, `:162` |
| Not centred: tendencies, vs-left | 5064-5065, 7052, 976, 5108; `platoon.py:182` |
| Not centred, unmoved rating | endurance 300, 919, 5212, 5219; baserunning speed 1990-7962 |

**Lineup and roster management outside the engine.** These read stored ratings through `Player` objects and mix moved with unmoved ratings, so they would pick different players unless they read the engine view:
- `utils/lineup_autofill.py:295-299`, `:548-551`, `:627-633`
- `utils/position_fit.py:128-138`
- `utils/depth_chart_autofill.py:117`
- `utils/roster_backfill.py:122`
- `services/roster_fill.py:159`
- `services/inseason_callups.py:105-120`
- `services/roster_auto_assign.py:59-60`, `:161-275`

Rotation and role logic read endurance only and are unaffected.

## 3. Potentials and development

**How it works today:**
- **Potentials** are set once: current plus 10-30 under age 22, plus 5-15 under 28, ±5 under 32, minus 0-10 after (`player_generator.py:1261-1270`). They are on the engine scale and are computed before the draft markdown. The client shows them nowhere.
- **Aging** (`aging.py:13-46`, called from `league_rollover.py:229`) ignores potentials and has no cap except 99.
- **Training camp** (`player_development.py:323-358`) adds 1-5 points to one or two ratings each spring. It keeps adding one point after potential is reached. Pitch Lab reuses the ×1.35 pitch boost.

**A typical prospect on today's code (arithmetic):** a 20-year-old with Contact 48 gains +12, +10, +8, +6, +4 from aging alone and reaches 88 by 25. Power gains 5, 5, 5, 7, 9, 11 over the same span.

**Whole league, closed cohort, real code in memory (stats-clean):**

| | Today | 1 rollover | 5 | 10 |
|---|---|---|---|---|
| Contact sd / hitters at 99 | 5.1 / 0 | 10.0 / 0 | 26.5 / 44 | 32.1 / 65 |
| Power mean / at 99 | 48.1 / 0 | 51.6 / 0 | 62.1 / 9 | 64.8 / 182 |
| Control mean / at 99 | 51.2 / 0 | 54.6 / 0 | 66.8 / 22 | 65.2 / 214 |
| Fastball median / at 99 | 63 / 15 | 74 / 95 | 99 / 367 | 99 / 486 |

Training alone is mild for core ratings (Contact sd 5.1 → 7.4 after five springs) but still drives pitch grades to 99 (164 fastballs).

**Proposal:**
1. **Disable `_apply_yearly_aging` and the pitch boost now**, on every generation.
2. **Potentials at migration:** `new potential = min(99, new current + max(0, old potential - old current))`. The gap is kept in points, so it is worth about a third of what it is today in engine terms, and potential is never below current. On stats-clean, hitters aged 21 or under average Contact 55 with potential 73, and 4-8 players per rating sit at 99 (arithmetic). Unmoved ratings keep their potential, floored at current.
3. **A new development model on the stored scale.** Each offseason a player under 30 closes 20-50% of his gap, rising with age, plus small noise. From 30 he loses 1-6 points a year and potential follows current. Training redistributes the year's growth; it does not add to it. A 20-year-old at 35 with potential 65 goes 41, 47, 52, 56, 60, 62, 63 (arithmetic).
4. **No age shape imposed at migration.** It would change play. It emerges over about five seasons.

**Stationarity is a build gate.** Today's 19-year-olds are already as good as veterans, so any growth model produces a wave. In my 20-season check (my own entrant model, arithmetic) the regulars' mean rose 10 stored points by year 10 and fell below the start by year 20. Spread stayed at 12-13 and at most 4 players reached 99. A league-wide yearly correction capped at 2 points held the mean flat. Either ship that correction or tune the model until the wave is under about 3 points.

## 4. Consumers outside the engine

**Recommendation:** neither a per-league "scale version" on each constant nor a league-relative rewrite as the first step. Give every backend consumer one accessor that returns the engine-scale value (the exact inverse map). Salaries, CPU moves and trade values are then identical to today on a migrated league, and that can be tested the same way as the engine. Rewrite individual consumers to be league-relative later, where it adds value; salary is the best candidate.

**If nothing is done (arithmetic, same formulas on stretched ratings):**

| | stats-clean | alpha-test |
|---|---|---|
| Hitter OVR sd / max | 4.4 → 10.5 / 61 → 82 | 4.6 → 10.9 / 62 → 83 |
| Pitcher OVR sd / max | 4.9 → 10.5 / 64 → 82 | 2.9 → 5.5 / 55 → 57 |
| Hitters' total market value | +35% | +50% |
| Pitchers' total market value | +1% | -43% |
| Top single value | $12.7M → $40M (the curve's ceiling) | $12.7M → $37.8M |
| Players at the $0.8M floor | 0 → 70 | 3 → 60 |

| Consumer | Where | Class | Needs |
|---|---|---|---|
| Overall rating | `utils/player_overall.py:36-47`, `:80-145` | constants in rating units (`fa-50`, endurance ±3 cap) | engine view internally; a display OVR is an owner decision |
| Flat-mean "talent" (five copies) | `player_retirement.py:129`, `prospect_promotion.py:60`, `gm_finance_queue.py:1405`, `offseason_finance_flow.py:1043`, `finance_ai.py:617` | constants, clamps 20-95 | engine view |
| Salary curve and everything priced from it | `contracts_service.py:59-61`, `:630-683`; `contract_negotiator.py:295-296`, `:306`, `:394` | non-linear (floor 35, ceiling 75, power 2.2; 55 / 60 length cuts) | engine view |
| Arbitration, CPU bids, GM queue | `finance_ai.py:190-313`, `:443-455`, `:739-799`; `gm_finance_queue.py:278-280` | thresholds 58-80 | engine view |
| Trade value and acceptance | `cpu_trade_evaluator.py:431-441`, `:464-517`; `cpu_trade_proposals.py:524-527`, `:1222-1245` | constants against fixed pick values; ratio band | engine view; re-tune `0.04*(potential - current)`, since gaps shrink about threefold |
| Promotion and retirement bars | `prospect_promotion.py:52-57`; `player_retirement.py:40-65` | constants (55 / 65 / 72; age tables) | engine view |
| Roster auto-assign, lineup auto-fill, call-ups | section 2 list | mixes moved and unmoved ratings | engine view |
| Draft AI | `draft_ai.py:189-216` | non-linear, uses potentials | engine view; re-check need against talent |
| Draft markdown, potential roll, floors | `player_generator.py:1261-1351`, `:768-810`, `:1018-1021` | multiplies about zero | stays in engine scale (section 5) |
| Aging, training | `aging.py`, `player_development.py:265-358` | constants (75, 80, cap 5) | rewrite (section 3) |
| Role from endurance, pitch budget | `utils/pitcher_role.py:20`, `:41-48`; `pitcher_recovery.py:333-367` | constants | nothing (endurance is not moved) |
| Display and stars | `utils/rating_display.py:300-380`; `utils/star_rating.py`; `api/routers/_rating_presentation.py:147-150` | league percentile blend | show the stored value on new-scale rows; re-anchor stars |
| Scouting noise | `scouting_service.py:310-370` | ±1-9 display points | about ×2 |
| Awards, All-Star, Hall of Fame, injuries | stats or durability only | scale-free | nothing |
| Tutorials | `services/tutorials.py:571-614` | quotes rating numbers | rewrite |

**Client (`desktop/src`):**
- **Colour bands:** 85 / 70 / 50 in `RosterPage.tsx:1361`, `FreeAgencyPage.tsx:1089`, `PlayersBrowserPage.tsx:463`, `PitchersPage.tsx:526-530`. These start working as intended. `PlayersBrowserPage.tsx:444-448` uses 90 / 75 / 60 for OVR and should be unified.
- **Role tabs:** `PitchersPage.tsx:84-86` splits on `endurance > 55` of the display-scaled value and already disagrees with the server. Use the server's role.
- **Draft page:** shows raw ratings (`DraftPage.tsx:993-1003`) while every other page shows blended ones. Showing stored values everywhere on the new scale removes that mismatch.
- **Nothing else depends on absolute values:** no filters, bars, grades or potential displays exist.

The legacy-engine modules behind `PB_ALLOW_LEGACY_ENGINE` hold more thresholds and were not inventoried.

## 5. The generator

**Recommendation:** transform at draw time. Leave `data/players_normalized.csv` and every generator constant in engine scale, and call the stretch once at the end of `generate_player` and of any other fabricator (the draft pool, the placeholder pool at `utils/roster_loader.py:128-137`). The potential is then rolled in stored points.

- New leagues play exactly as generation 5 new leagues do.
- The audit's Release 7 generator fixes stay separate work, in engine scale.
- Re-spreading the donor file instead would mean re-expressing every jitter, floor and markdown, for no gain.

**Fixtures and tests:**
- Keep the three fixtures as they are.
- Add a test that stretches each one in a temp directory and requires the harness output to be identical.
- Give the harness's own rating readers the same row conversion.

## 6. The migration

**The marker is a `rating_scale` column on each row** (blank means 1). The engine loader, the centres, the consumer accessor and the display key off the row itself.

- A stale `players.csv` pushed back by an old instance, a restored backup or an archived snapshot is self-consistent and plays correctly on its own scale.
- Conversion is idempotent per row.
- A sidecar file alone cannot give this: the working copy syncs file by file (`api/working_copy.py`), and a crash between two writes would double-stretch.
- It needs the field on the player models, `utils/player_loader.py` and `utils/player_writer.py` (fixed field list), plus the direct writers: `services/draft_assignment.py:204`, `playbalance/league_creator.py:609`, `playbalance/draft_pool.py:380`, `api/routers/admin_league.py:176`, `:297`.
- The writer refuses a mixed-scale list.

**The map constants live in code**, in a small module beside `engine_generation.py`, versioned by scale number. Do not put them in the generation profile. The scale belongs to the data, and generation 5 played stretched data identically, which lets this ship and be tested before generation 6 exists.

**When:**
- At rollover, after the season archive, when the next season will be generation 6. The offseason, draft and free agency then already show the new numbers.
- For a league sitting between seasons at deploy: where `_new_season_generation` (`league_rating_centers.py:984`) first records generation 6.
- New leagues are created on scale 2.
- Always under the sim lock and a background-writer guard.

**How:**
1. Read every row as raw CSV; do not round-trip through the models.
2. Transform rows whose scale is 1.
3. Check row count and id set are unchanged.
4. Copy the original to `players.scale1.<season>.csv`.
5. Write the whole file atomically. Never a subset (`save_players` replaces the file).
6. Log the conversion in a small `rating_scale.json` and post one news item.

**Also convert:** an open `draft_pool_<year>.json` / `.csv`.

**Do not convert:**
- `rating_centers.json` (engine scale by construction)
- the per-league or root `players_normalized.csv`
- season archives, stats, records, awards, contracts
- `training_history` deltas, news text

**Undo:** the inverse map is exact until the first development change. After that, rounding loses at most half an engine point. The backup is the fallback.

**alpha-test re-spread:** a separate, optional step that runs before the stretch, in engine scale, with its own flag and log entry. Each bunched rating is mapped by rank onto the new-league reference distribution. It changes how alpha plays; the scale change does not. Ties need a rule.

## 7. Home-run anchors

Monte Carlo: generation 5 kernel, calibration pitchers by workload, generic park, 100,000 PA per cell. A full season is taken as 650 PA. Rows and columns are stored ratings, Eye average.

| HR per 650 PA, today's curve | Contact 50 | Contact 70 | Contact 80 | Contact 89 |
|---|---|---|---|---|
| Power 70 (engine 56.7) | 25.5 | 28.5 | 29.4 | 30.9 |
| Power 80 (60) | 31.3 | 35.7 | 36.6 | 38.7 |
| Power 90 (63.3) | 38.1 | 42.9 | 44.8 | 46.1 |
| Power 95 (65) | 41.4 | 46.6 | 48.3 | 50.4 |
| Power 99 (66.3) | 44.3 | 49.8 | 50.9 | 54.5 |

- **Eye** does not move home runs (at most -4% at Eye 80); it adds 1.7 points of walk rate.
- **The league's best slugger today** (Power 65) becomes stored 95 and hits about 41 per 650 PA with average Contact.
- **The cap at 99 bounds the engine at Power 66.3**, so the "Power 80 projects to 68" region can never be reached.
- **Doubles:** stored Power 70 with Contact 80 gives 43 per 600 PA, and Power 80 with Contact 89 gives 52, before the Power agent's doubles change.

**To put 45 at Power 90 with average Contact and 55 at Power 99 with Contact 80**, the bat-speed anchors need to be (Monte Carlo response at forced bat speed, interpolated):

| Engine Power (stored) | Bat-speed offset today | Needed | HR per 650 PA at Contact 50 |
|---|---|---|---|
| 63.33 (90) | 11.1 mph | about 14.5 | 45 |
| 65 (95) | 12.65 | about 15.0 | about 46.5 |
| 66.33 (99) | 13.9 | about 15.5 | about 48 |

- Contact 80 then gives about 53 at Power 90 and 55 at Power 99 (arithmetic from the Contact ratios above).
- Power 99 with Contact 89 gives about 59. No such hitter exists in any league today, which is what keeps 60 rare.
- Stored 80 and 85 should rise to about 35 and 40 (offsets about 9.8 and 12.0) so there is no cliff. That lifts league home runs a few percent and needs the Power agent's re-level.
- Re-fit all of this after the batted-ball model is frozen.

## 8. Owner decisions

1. **How spread out ratings look.** Recommended: an average regular is 50; about 1 hitter in 40 is 80 or better; the best one to seven players per rating are in the 90s; weak prospects read 15-30.
2. **Where 45 home runs starts.** Today's curve already gives 45-55 for Power in the 90s with Contact 80 or better, and 38-44 with average Contact. Recommended: lift the top so Power 90 with average Contact is 45. The alternative is to leave it.
3. **Potentials.** Recommended: keep each player's gap in points, never below current, and start showing potential in the client (it is hidden today).
4. **Age shape.** Recommended: do not mark young players down at the switch. Let development create the curve over about five seasons, and accept a small yearly league-wide correction that keeps the average regular at 50.
5. **Overall rating.** Recommended: CPU logic and salaries keep today's numbers internally. Owners see an overall stretched about 50 (hitters) and 53 (pitchers) so the best players land at 88-92. Salaries do not shift.
6. **What owners see.** Recommended: the stored number, on every page including the draft. The percentile blend goes away, so some displayed numbers drop (a stored 50 shows as about 58 today).
7. **alpha-test's bunched ratings.** Recommended: spread them at the same switch, announced separately as a change to how that league plays. Tied ratings (movement) are ordered by pitch grades, then a seeded draw.
8. **Fielding, arms and tendencies.** Recommended: stretch gloves and arms modestly (best in the 90s); leave ground-ball, pull and vs-left alone.

## 9. Risks, build order, not verified

**Risks:**
- **A missed consumer misbehaves silently.** Mitigate with a test that walks the code for direct rating reads outside an allow-list, plus identity tests for OVR, market value, trade value, auto-assign and lineup auto-fill on a stretched twin league.
- **A writer that drops the `rating_scale` column makes a stretched file read as scale 1.** Enumerate writers in a test and refuse mixed lists.
- **The 99 cap becomes a real ceiling once development runs.** It bounds Power at engine 66.3 and Eye at 59.8.
- **Fixed pivots.** A league whose staff sits off the reference (alpha) displays off 50 until it is re-spread.
- **Kinked maps.** A stored point is worth different engine amounts in different bands.
- **The development wave** (section 3).
- **Harness KPIs.** Slope and correlation metrics change meaning unless their readers convert.

**Build order:**
1. **Now, any version:** switch off yearly aging and the ×1.35 pitch boost.
2. **Dark, no visible change:** the scale module, the row column in loaders and writers, the engine and centre boundary, harness readers, the byte-identity test.
3. **Dark:** the consumer accessor with its identity tests; the generator's final stretch; draft pool handling.
4. **Dark, behind the scale:** the development model and its 20-season gate; display, stars, client bands, tutorials.
5. **Together, 8.0.0:** conversion at rollover into generation 6, the generation 6 profile with the Power anchors, the alpha re-spread, the news items.

**Not verified:**
- The live `game_runner` path. Only the harness path was run.
- The inventories in section 4 came from two search passes. I checked the aging, generator, display and salary formulas myself, not every line reference.
- Whether any live league has ever rolled over. The copies show no age curve, which suggests not.
- Working-copy behaviour beyond reading the module header.
- The legacy-engine modules.
- The development proposal and its population check use my own entrant model.
- Home-run anchors use the generation 5 kernel and a generic park.
- The alpha re-spread itself was not prototyped.
- Fractional ratings were not run in a season of their own.
