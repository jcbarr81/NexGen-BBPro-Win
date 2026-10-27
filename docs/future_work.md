# Future Work Ideas

This note captures high-level enhancements identified during the latest review so
they are easy to revisit when planning new milestones.

> **Status (2026-10-25, VERSION 8.4.3):** this file lists open work only. What
> shipped is in `release_notes_draft.md` / `release_notes.md` and `git log`;
> check the code before trusting a status here. The product is the cloud web app
> (FastAPI `api/` + `services/`, React `desktop/src/`, Firebase / Cloud Run);
> the PyQt `ui/` app and the Windows installer are retired. Finance follow-ons:
> `docs/financial_backlog.md`. Engine-audit plan and decisions:
> `docs/audits/2026-10-06-engine-ratings-audit/`.

## 7. Multi-League Ownership & Collaboration Roadmap
These initiatives enable a single owner to juggle multiple leagues, move saves
between offline/online modes, and collaborate with other owners through
messaging, chat, and forums. Tackle them in the order below so shared services
land before channel-specific features.
- **Status:** 7.1 / 7.2 shipped (Firestore multi-tenant + Cloud Run). 7.3
  messaging, 7.4 chat and 7.5 forums / trade block are open: not built.

### 7.3 Direct Owner Messaging
1. **Message model:** Create conversation threads tied to a league, team, or
   generic DM; include participant roles and read receipts.
2. **API layer:** Expose CRUD endpoints and subscription events (WebSocket)
   through the franchise services layer so UI clients stay in sync.
3. **Inbox UI:** Add an in-app mailbox with filters (league, unread, mentions)
   plus quick-reply composer referencing players, trades, or fixtures.
4. **Notifications:** Integrate with the existing notification center (toast,
   email hooks) and allow owners to tune per-thread alerts.
5. **Moderation:** Support blocking/muting, audit logs, and retention policies
   so commissioners can enforce community guidelines.

### 7.4 Built-in Chat Rooms
1. **Transport:** Reuse the WebSocket broker for real-time chat; fallback to
   long-polling in offline/file-sync mode.
2. **Rooms:** Define chat scopes (league lobby, draft room, ad-hoc topic) and
   persist membership + history for late joiners.
3. **Draft integration:** Embed chat alongside draft board/pick clock so owners
   can coordinate, share scouting cards, and auto-post picks.
4. **UX polish:** Add mentions, emoji, attachments (player cards, lineup files),
   and moderation controls (mute, kick, slow mode).
5. **Observability:** Log chat events for diagnostics and expose metrics (active
   users, message volume) to ensure scalability.

### 7.5 Forums, Trade Block & News
1. **Forum taxonomy:** Create categories for Trade Block, League News, Strategy,
   Support; allow commissioners to manage visibility.
2. **Content model:** Support Markdown/Rich Text, tagging of players/teams, and
   linking to sims or stats so posts stay contextual.
3. **Trade block workflows:** Enable owners to flag players, auto-generate post
   templates, and notify other GMs/subscribers.
4. **Automation hooks:** Let the sim engine publish recaps, award announcements,
   or injury reports directly into forum channels.
5. **Moderation & discovery:** Add pinning, reactions, search, and archival
   policies, plus integrate forum notifications with the inbox/chat system.

## 20. Player Morale System
- **Goal:** Introduce a dedicated morale model that influences development,
  performance variance, and roster-management decisions.
- **Scope:** Add player morale state and lifecycle events (playing time,
  role/promotions, injuries, streaks, team context), connect morale modifiers
  to training/development outcomes and gameplay tuning where appropriate, and
  surface morale in owner/admin UI plus tutorials.
- **Status:** Open.

## 24. Team Strategy Profiles for Automation
- **Goal:** Add team strategy profiles so auto-assign and auto-lineup creation
  decisions reflect each team's intended play style and roster philosophy.
- **Scope:** Define league/team strategy presets (for example: Balanced, Win
  Now, Development Focus, Defense First, Power Offense) and feed them into
  auto-assignment, lineup generation, and depth-chart prioritization logic.
- **Scope:** Support league defaults with per-team overrides, plus clear UI
  indicators showing which strategy is active when automation runs.
- **Status:** wired into Team Settings, auto-assign, valuation, draft AI,
  finance AI, prospect rules and the lineup auto-fill. Open: depth-chart
  prioritization, an "active strategy" indicator, in-game use
  (`docs/specs/S3-13_team_strategy.md`; overlaps #62's per-team running
  strategy).

## 26. v5.4 differentiators (deferred)
### v5.4 - Differentiators (Simulation Futures + Narrative + Presentation)
- **Target effort:** 6-10 weeks.
- **Status note (2026-03-08):** What-If Lab work is deferred pending community
  feedback on whether the feature justifies the engineering cost. Do not pull
  What-If-specific prerequisites into the active queue until that feedback is
  reviewed.
- **Primary scope:**
  - What-If Lab v1: fork from any date, run Monte Carlo batch sims (up to 1,000
    futures), compare move outcomes (trade/call-up/lineup/pitching changes).
  - Commissioner-grade online foundation v1: deterministic replay packaging,
    signed action records, and end-to-end audit timeline.
  - Story engine v1: weekly narrative generation from real events (streaks,
    breakouts, collapses, milestones, rivalries).
  - Presentation layer v1: lightweight key-play/highlight recap mode (no full
    3D dependency).
- **Risk level:** High.
- **Key risks:**
  - What-If compute cost and runtime may impact desktop responsiveness.
  - Deterministic replay and signed actions require strict event-model discipline.
  - Story generation can feel repetitive without event diversity controls.
- **Dependencies / gates:**
  - Requires stable deterministic simulation hooks and replayable state snapshots.
  - Requires richer structured event stream from game/season simulation.
  - Requires scalable background-job orchestration for batch simulations.
- **Exit criteria:**
  - Users can run and compare scenario batches from a saved historical date.
  - Audit timeline links actions to deterministic sim outcomes.
  - Weekly story feed and highlight recap are visible and filterable in UI.

#### v5.4 Subtasks (Tracking Checklist)
- [ ] **V5.4-01 Deterministic event log foundation (canonical schema + writers)** (Effort: L, Risk: High, Depends: D3, Deferred pending What-If feedback)
- [ ] **V5.4-02 Season/date snapshot and fork manager** (Effort: M, Risk: High, Depends: V5.4-01, Deferred pending What-If feedback)
- [ ] **V5.4-03 Batch simulation runner (up to 1,000 futures) + job orchestration** (Effort: L, Risk: High, Depends: V5.4-02, Deferred pending What-If feedback)
- [ ] **V5.4-04 What-If comparator UI (baseline vs scenarios + deltas)** (Effort: M, Risk: Medium, Depends: V5.4-03, Deferred pending What-If feedback)
- [ ] **V5.4-05 Signed action records + verification chain** (Effort: L, Risk: High, Depends: V5.4-01)
- [ ] **V5.4-06 Commissioner audit timeline UI + replay links** (Effort: M, Risk: Medium, Depends: V5.4-05)
- [ ] **V5.4-07 Deterministic replay validator tooling** (Effort: M, Risk: High, Depends: V5.4-01, V5.4-05)
- [ ] **V5.4-08 Story event extraction pipeline (weekly signals)** (Effort: M, Risk: Medium, Depends: V5.4-01)
- [ ] **V5.4-09 Story engine generator (breakouts, collapses, milestones, rivalries)** (Effort: M, Risk: Medium, Depends: V5.4-08)
- [ ] **V5.4-10 Highlight recap mode (key plays + summary presentation)** (Effort: M, Risk: Medium, Depends: V5.4-08)
- [ ] **V5.4-11 Performance guardrails for What-If + recap generation** (Effort: M, Risk: High, Depends: V5.4-03, V5.4-10, Deferred pending What-If feedback)
- [ ] **V5.4-12 Release soak tests + deterministic replay sign-off** (Effort: M, Risk: High, Depends: V5.4-04..V5.4-11)
## 35. Pick your team in the league-creation wizard
- The cloud create endpoint accepts a `team_id`
  (`api/routers/league_create.py`), but the wizard never sends one
  (`LeagueCreatePage.tsx`) and lands on My Leagues; a commissioner who
  wants a club has to claim one on the Members page. Offer "pick your
  team" in the wizard.
- **Status:** Open.

## CPU-CPU trade volume tuning (optional)
- **Context:** The S2-10 acceptance gate (2026-07-16) fixed the CPU-CPU lane from
  0 executed trades to a functional ~3-5/season (12-team sandbox; ~8-13 scaled
  to 30 teams). Talent balance is healthy (win% stddev does not grow).
- **Observation:** ~150 near-misses/season land as `counter_dropped` — the
  receiver counters a balanced offer and the proposer declines under the
  single-counter-round rule (S2-10 decision D2).
- **Lever (if more volume is wanted):** allow a second counter round, or let the
  proposer accept slightly more receiver-favorable counters, or widen the
  CPU-CPU value band. **Caution:** don't overshoot into unrealistic roster churn
  — the current lane makes fair, meaningful trades, which is the intent.
- **Verify with:** `python scripts/sim_seasons_with_automations.py --seasons 3`
  (target: volume up, win% stddev still not growing, rosters legal after revert).
- **Status:** Open (optional).

## 46. Make power hit for power (engine calibration)
_Added 2026-10-02 from owner feedback (El_Jayel). Full plan: `docs/specs/S3-power-calibration.md`._

> **Shipped in 7.45.0 (2026-10-03).** Open: Phase 3, widen the generated
> power spread for new leagues (`docs/specs/S3-power-calibration.md`,
> "Deferred: Phase 3").

## 48. Data-root fallback can write into the repo's data/ folder

Found during the H9 hotfix verification (2026-10-06): when `NEXGEN_DATA_ROOT`
points somewhere that can't be resolved (a typo, a missing folder),
`utils/path_utils._resolve_data_root` silently falls back to the repository's
own `data/`, and `get_data_dir()` -> `_seed_data_dir()` then copies the repo's
top-level data files into `data/leagues/<league>/data/` (146 files in one
incident, plus recursive `data/leagues/<x>/data/leagues/...` trees from earlier
runs, some created read-only). In the cloud the root always resolves, but a
misconfigured deploy would read and write the wrong data without a word. Make
an unresolvable configured root an error, not a fallback, and stop
`_seed_data_dir` from copying a tree into itself.

## 51. Retune prospect promotion for the shared overall

7.45.10 introduced one production-weighted overall (`utils/player_overall.py`)
for display, CPU auto-assign and trades, but prospect promotion
(`services/prospect_promotion._player_overall`, also used by in-season
call-ups) deliberately kept its old flat average: the fixed 55 / 65 / 72 bars
were tuned for it, and the shared score is ~1.3x wider (alpha-test LOW->AAA
pass rate 2.4% -> 12.9%; yearly AAA->ACT promotion has no cap check, so
owners' rosters would overflow at rollover). Re-derive the bars as
percentile matches on representative leagues, add a cap check (or demotion)
to yearly promotion, then switch to the shared score.

## 52. Unify the remaining CPU and display scores with the shared overall

> **Shipped in 8.6.4 (2026-10-27):** the draft board / auto-pick, the CPU
> free-agent signing order, CPU trade proposals, retirement and in-season
> call-ups use `utils.player_overall.player_overall_score`
> (`tests/test_shared_overall_consumers.py`). Measured on copies of both
> live leagues: retirements 181 -> 182 with the same bars, trade-proposal
> spread cv .070 -> .076 (bands kept). Still on flat averages, left out on
> purpose:

- **CPU free-agent bidding** (`services/finance_ai._free_agent_quality_score`):
  its bars (`fa_star_quality_threshold`, 78, and the hard-coded 72 / 80 and
  +2..+10 offsets) are in the old average's points, and the threshold is
  stored in each league's `finance_ai_tuning` (both live leagues carry 78)
  and is commissioner-editable. Switching the score needs a matched bar and
  a migration of the stored value.
- **Arbitration** (`offseason_finance_flow._player_talent_score`,
  `gm_finance_queue._player_talent_score`, `star_talent_threshold` 76):
  same stored-tuning problem; do it with #64.
- `services/draft_ai.py` (a need-aware CPU draft score) is not called
  anywhere in production: wire it into the auto-pick (on the shared
  overall) or delete it.
- **The auto-pick leans to pitchers.** The draft-pool generator makes
  pitcher prospects better than hitters (current overall ~42 against ~37.5,
  potential 1-5 points higher, in all three live pools), so ranking by the
  shared overall takes 20-21 pitchers in the top 30 (alpha-test 2027: 9 of
  the top 10; the old flat mean took 15-21). Ranking by potential or a
  blend does not fix it (11-21). Either balance the generator or pick by
  team need (the `draft_ai` item above).

## 52a. Retirement bars retire almost everyone past an age

Found measuring #52 (2026-10-27). The bars in
`services/player_retirement` are in engine points, where big leaguers
average ~52 with a spread of ~3-4 and almost nobody reaches 60: every
big leaguer 38+ (bar 60) and every AAA player 32+ (bar 60) retires
whatever his quality, and the 80-95 bars at 42+ can never be met.
alpha-test's 2027 rollover retired 62 (41 AAA "career minor leaguers",
19 "declining"); stats-test's first rollover would retire ~180 (130 of
them AAA players). Re-derive the bars as percentiles of the engine
overall by level and age (or on the shown 1-99 scale) so a good 39-year-old
can keep playing.

## 53. 2026 fielding rate stats mix two periods

7.45.10 split the fielding counters that collided with batting/pitching keys
into `f_cs`, `f_po`, `f_ci`, `f_pk` (audit H5). 2026 rows keep their merged
values and the f_ keys start at 0 mid-season, while their denominators (sba,
a, e, g) are full-season -- so 2026 cs_pct, fpct and rf9 are biased low. No
screen shows them yet; any future fielding display must hide 2026 rates or
recompute them only for players whose f_ keys cover the whole season.

## 54. Batting and pitching season keys collide if a pitcher bats

Same class of bug as H5: batting and pitching lines share one season_stats
dict, so g / h / r / hr / bb / so / pocs would mix for anyone who both bats
and pitches. The engine plays a universal DH today, so it doesn't happen, but
two-way players or position players pitching in a blowout would expose it.

## 55. Migrate existing leagues' parks to explicit picks (audit L13 follow-up)

7.45.10 applies real-park geometry only for an explicit `park_id`; leagues
created before it have no such column and keep the old name lookup, so
alpha-test's FOR ("Royals Stadium") still plays in Kauffman 1973-93. Needs an
owner call: an opt-in migration that marks generated "{mascot} Stadium"
names generic and keeps deliberate picks, or a commissioner review screen.

## 56. Legacy engine fielding credit differs from the physics engine

`playbalance.simulation.GameSimulation` (archived; physics_sim is live) still
gives the pitcher an assist on every strikeout, which 7.45.10 removed from
the physics engine (audit M9). Align it or retire the legacy engine.

## 57. New leagues get no fast runners (generator ignores speed tiers)

Owner decision 3 (2026-10 engine audit) puts speed in archetype tiers, but
since 7.24.0 `league_creator.create_league` builds hitters through
`player_generator._sample_normalized_hitter`, which bootstraps from
`data/players_normalized.csv` (max SP 67) and applies the speed/elite_speed
floors only when a caller names an archetype. New leagues therefore have no
SP >= 70 runners. `scripts/generate_league_fixture.py` patches this with
`_with_speed_tiers`; move that into the generator (Release 4 or 7 generator
work), delete the shim, and regenerate `data/calibration_league`. Also verify
the cloud data root ships `players_normalized.csv` as the ratings source.

## 58. Promote report-only KPI gates as their engine fixes land

Release 2 (7.45.11) added gates the engine still misses as report-only:
- `hard_hit_pct`, `barrel_pct`, `sweet_spot_pct` -- Release 6 (M2);
- `qualified_hr40_count` (5 +/- 3) once the 40-HR tail is ~5 on several seeds;
- the league-like fixture (`data/calibration_league`) CI step to `--strict`,
  on seeds 1 and 2, once Releases 3-6 bring it inside tolerance (it runs
  4.1 R/G today: decision 2, league-relative ratings, matters more than
  assumed);
- pitcher IL 11-15 per team-season in `scripts/injury_rate_kpi.py` once the
  per-appearance arm-injury hazard ships (engine gives ~1.2 today).
- report-only KPIs in `scripts/kpi_extras.py` (`report_only` in the JSON):
  bullpen usage (`starts_120plus_pct`, `closer_ip_per_app`) with H1; GIDP
  per opportunity with M8 (Release 4); per-count swing rates, first-pitch
  PA endings, BB/K true sd and the K log5 grid (Release 5); fastball fade
  (11.8 mph today vs 1-2), HR sd ratio, HR log5 grid and team DER sd
  (Release 6); LHP-RHP RA9 and per-hand platoon gaps with H7.
`qualified_hr30_count` is strict at 20 +/- 8 with the engine at 15-20; a tail
count, so an RNG-reshuffling change can trip it -- re-check seeds 1 and 2.

## 59. KPI harness housekeeping

- Benchmark CSV rows nothing computes (iffb_pct, pull/oppo, wOBA/xwOBA/wRC+,
  FIP/xFIP/SIERA, DER, OAA/DRS, K-BB%, TTO runs, park/weather/umpire): compute
  or delete them.
- Per-league benchmark copies under `data/leagues/*/data/MLB_avg/` still have
  the old values; nothing reads them -- sync or drop.
- XBT counts batted-ball singles only, not bunt singles.
- `sb_pct` benchmark .78 is a bit under MLB 2023-24 (.79-.80).
- The injury harness re-uses static rosters (injured players keep playing).
- Add MLB in-season total IL per team (~22) to the reference data.
- Regenerate `data/calibration_league` whenever generation code changes;
  `test_committed_fixture_matches_the_current_generator` gives the command.
- Fixture quirks it reproduces: Pitching auto-fill lists 11 of 13 ACT
  pitchers (the other two are never relievers -- audit H1); team ids like
  SAN, SAN1, SAN2 from city initials.
- Multi-seed pooling driver for the noisy extras (true sds via the
  unclipped variance in `tables.dispersion`, team true W% sd, home W%); one
  seed can't resolve a BB true sd below ~.007.
- True OAA in place of the `range_plays_per_fa_sd_*` proxy: the engine must
  log the responsible fielder and neutral out probability per ball in play
  (the audit's fdriver.py shows the method); include 1B.
- Verify the approximate extras references (run probability, inning runs,
  late & close, platoon by hand, closer IP, relief 60+ share, 1st-to-3rd)
  against FanGraphs / Baseball-Reference.
- `tests/conftest.py` teardown runs `git checkout -- data`, silently reverting
  unstaged edits to tracked data files; note it in CODEX_HANDOFF section 5.

## 60. 26-man roster follow-ups (7.46.0)

- Waivers / DFA / outright assignments. Out-of-options surplus CPU pitchers
  are force-optioned today (logged); owners get the generic pitcher-limit
  error -- add "{name} is out of options: trade or release a pitcher".
- Check owner teams on commissioner/scheduler sims and in the postseason
  (playoff sims have no roster gate); gate it behind the deadline flow so the
  auto-run can't stall.
- Two-way player designation (MLB exempts them from the pitcher count).
- Notify every owner of an open active spot in multi-owner leagues (today
  the notification goes to the team that runs the sim; the Season-page action
  item reaches everyone).
- Free Agency offer dialog: show level room ("ACT 25/26 - 13/13 P") and the
  server's signing warnings (the /sign response returns them; the client
  doesn't show them yet).
- Surface owners' yearly-promotion suggestions as an action item / Roster
  hint (news lines only today).
- Opening Day CPU roster pass: optional dry-run admin endpoint.
- Daily CPU upkeep passes no option-limit veto, so its trims ignore option
  limits silently (pre-existing); pass `injury_manager._option_allowed`.
- CPU organisations in existing leagues already exceed today's limits (alpha
  and stats-test CPU orgs hold 53-55 with Low-A at 14-15 vs a cap of 10,
  from draft picks that are never released). Harmless (the gate checks only
  the requesting team) but worth a CPU-only offseason trim policy.
- Client `npm run typecheck` fails on main (24 strict-mode errors in pages
  this release didn't touch: LeagueCreatePage, StandingsPage, ParksPage...).
- The offseason arbitration pass returns `ownership_unknown` when it ran
  with every club treated as an owner's (no CPU raises/non-tenders that
  year); surface it on the offseason checklist so the commissioner knows.
- Lenient ownership reads left (read-only uses): `api/routers/season._human_team_ids`
  (readiness: an unreadable users.txt lists no owner teams, so nothing is
  checked) and `fa_window._human_participation` (display). Switch both to
  `team_ownership.human_owned_team_ids_strict`. (7.46.0 made the mutating
  paths strict: roster automation, the CPU FA market and bid book,
  negotiations, IL auto-activation and the arbitration/non-tender pass.)

## 61. Release 3 follow-ups (7.47.0)

- Admin exhibition games still write real season/career stats and special
  events to the live league (PB_PERSIST_STATS); run exhibitions with stats
  persistence off and test that season_stats.json is unchanged.
- Rest-state bootstrap after deploy replays only the tracker's last 14 days;
  batters start fresh and the appearance caps undercount for that season.
  Optionally rebuild appearances from season_stats.
- Re-simming a day whose usage was already saved double-counts fatigue (the
  tracker has the same exposure); add per-date idempotency markers.
- tests/test_sim_batching_invariance.py takes ~5 min idle (15+ under load);
  mark slow or trim modes if CI time matters.
- Appearance caps are keyed on league-wide game dates; a club's own off days
  loosen its cap. Consider a per-team games-played count or a rolling window.
- Closer IP per appearance is ~0.93 (MLB ~1.0) and the top closer ~65 IP/162
  (MLB ~75) since closers stopped pitching middle innings -- revisit in the
  Release 5 retune.
- Emergency (rested-starter) relief: show "emergency relief" in box scores
  and game logs; consider position-player pitching in blowouts (owner Q6 c).
- Generator: hitters with other_positions (today ~5%) and a 1B backup would
  cut blocked rest days further (regenerated fixture ~1.2k blocked field
  rests vs a <500 target; starters ~142 GS vs 145-155).
- Promote the report-only bench metrics (blocked rests, hitters starting all
  162, backup-C starts, tired-starter share) to strict once stable.
- Measure the fatigue-linked hitter injury on live leagues; add a hitter
  soft-tissue hazard in Release 5/6 (owner Q10).
- Playoff dates can run past New Year on the old long schedules; the IL league
  clock does not advance during dated playoffs.
- Show playoff game dates on the Playoffs page; a box-score note for the
  extra-inning automatic runner.
- A real-game playoff tie (only possible at the 60-inning hard stop) is
  re-simmed after its stats were written; sim without persisting until decisive.
- Several injury news writers log without team_id.
- Owner one-click "slot unslotted arms into MR4/MR5"; a Season-page item for
  a persistent invalid pitching staff; Notifications page "reset to defaults".
- tests/test_team_loader.py::test_load_teams_from_any_cwd needs an untracked
  ui/ dir; scripts/run_tests_isolated.py progress output is block-buffered.
- load_roster writes _placeholder_registry.json into the active data dir from
  tests that load tmp rosters; sandbox it in conftest.
- Test fixtures that set NEXGEN_DATA_ROOT without a players.csv sentinel can
  resolve a stray local league instead of their tmp root (backlog #48); add
  the sentinel in a shared fixture.
- The CPU trade-proposal cycle dominates a one-day sim call (~336 s of 357 s
  on a loaded Windows/OneDrive box: 55k get_current_sim_date calls via
  trade_settings.current_league_year, 191k Path.resolve). Hoist the league
  year/sim date out of cpu_trade_evaluator's per-candidate loops; memoise
  data/base dir resolution per call.
- Injury catalogue: "Grade 2 oblique strain" (25-45 days) is tagged for the
  60-day IL, so a 29-day injury keeps a player out 60 days. Set dl_tier from
  the drawn days (re-check the IL60 share after).
- Production game seeds come from the unseeded global RNG, so re-sims are not
  reproducible; derive per-date seeds from a league seed + date.
- Live-path reliever back-to-back share (~0.11-0.12) and April pitcher IL pace
  (8.0-9.1) sit at the low end of the targets; re-check on a full live season.


## 62. Release 4 follow-ups (7.48.0)

- DONE 7.49.0: 4b is the default (steal base rates x1.05). Follow-ups:
  remove the 7.47.0 code paths behind tag_up_model / ground_out_model 0 and
  scripts/kpi_profiles/r4a_legacy.json after one release; the engine's
  inline tuning.get fallbacks for the hit-advance knobs still carry the
  7.48.0 values (unreachable while the keys are registered).
- platoon_gap_woba sits ~.031 against a .035 ceiling, so about one
  calibration season in eight trips it (4b on or off: seed 2 at steal x1.025,
  seed 8 at x1.05; 4a seeds 3 and 4 in earlier streams), sometimes with
  corr_avg_contact. Release 5 owns the platoon fix and restores the 0.006
  tolerance; until then a noisy-gate miss on a seed other than 1 is not a
  regression signal on its own.
- data/calibration_league GIDP is .62-.64 per team-game (floor .62) under
  4b, so GIDP gates on data/calibration only; revisit when the league
  fixture's offence is in tolerance.
- Live-path check at 7.49.0 (fresh 30-team league, 28 days; 7.48.0 in
  brackets): SB/G .80 (.78), SB% .78 (.81), WP .36 (.37), GIDP/G .61 (.49),
  SF/PA .0078 (.0107), 3B/G .18 (.19). GIDP and SF stop just short of MLB
  (.68, .0068) on a fast-hitter league; re-check with the Release 5 retune.
- Per-team running strategy (owner decision 4): "baserunning aggressiveness"
  (0.6x / 1.0x / 1.5x) and "play the infield in" owner settings on the Game
  Day settings page, with a guide. Today one league-wide rule applies.
- The infield-single subset (infield_single_ev_max, off) took XBT to .35 at
  85 mph; revisit with a lower EV or with the Release 6 batted-ball model. It
  is deliberately separate from the M6 infield-hit ramp (infield_hit_ev_lo/hi).
- RE24: runners on 1st and 3rd with 0 out stays ~9-11% low and 2nd and 3rd
  with 1 out ~10% low under r4b; 3rd only / 0 out is -5.1%. Needs a
  base-out transition-matrix diagnostic; keep the RE cells report-only.
- Tag-ups: r(tag, sp) is weak on data/calibration (no speed tiers); gate it
  on calibration_league only. Refit the tag-up knobs when Release 6 adds
  drag-based carry.
- Rebuild data/calibration with tiered speeds (it tops out at 67) so the
  speed-tier gates can run on the regression fixture too.
- Batter thrown out stretching a hit; bunting for a hit by speed.
- PB-aided runs are unearned only for the dropped-third-strike reach; a run
  that scores because of a passed ball (rule 9.16(a)) is still earned.
- Re-fit passed_ball_rate when catcher fa is re-centred (decision 2 general
  re-centring); PB rises ~22% then.
- K-reach reference (.06/team-game) is approximate; pull an exact MLB rate
  from Retrosheet and consider gating it.
- corr(catcher fa, PB/G) misses -.4 on some calibration seeds; keep it
  report-only or retune passed_ball_fa_k.
- Under r4b the R2 tag to 3rd uses the old roll beyond the short-fly gate;
  a race to 3rd would make it depth- and arm-aware.
- CI runtime: the KPI workflow now runs 3 strict seasons (timeout 90 min);
  trim if it becomes a bottleneck.
- The runner-advance roll on a wild pitch / passed ball (_advance_on_missed_pitch
  -> _advance_prob) still reads the catcher's arm raw, so live leagues (catcher
  arm ~50 vs fixtures ~55) record ~3% more WP/PB (live .36-.38 vs fixtures
  .30-.33; target .33). Centre the arm there only (hit advances stay raw).
- league_rating_centers: a centre whose group is empty (no ACT catcher) is
  retried from the CSVs on every game; cache a per-season "nothing to
  average" marker.

## 63. Commissioner option: amateur draft in the preseason

**Shipped 7.50.0.** The rules are in `docs/season_progress.md` and
`docs/owner_admin_guide.md`.

Follow-ups:

- League creation wizard: offer the timing there (today a new league starts
  on mid-season and the commissioner changes it on the Commissioner page).
- `current_league_year()` falls back to the wall-clock year in the offseason
  (no schedule yet); only the draft router resolves the coming league year
  from the season context. Make the helper itself context-aware.
- Sim-to-milestone: a "To Draft" button still appears for a mid-season
  league only; nothing to change, but the label could say "July draft".
- Forcing the phase past an unfinished preseason draft: spring training
  reopens it; forced past twice, the draft is finished in July. There is no
  "cancel this year's draft" action, by design so far.
- Reset-to-opening-day after a JULY draft deletes the draft files but leaves
  the drafted players on rosters, so a second class is drafted in July
  (older than #63; a preseason draft is now kept).
- Tests still missing: `_simulate_n` crossing the July date end to end, the
  real rollover hook, a human owner on the clock in a preseason draft.

## Release 5 platoon and handedness: follow-ups (2026-10-12)

Built on branch `r5-platoon`, switched off; the switched-on values are in
`scripts/kpi_profiles/r5_platoon.json`.

- The KPI harness's matchup grid (`kpi_extras.matchup_grid_metrics`) gets the
  tuning profile but not the fixture's rating centres, so under a Release 5
  profile its right-handed platoon cells use `handedness_rhb_scale` alone
  (shares unknown) and every centre is 50. Pass `with_rating_centers` to it
  if the grid should describe the fixture rather than a neutral league.
- With `handedness_balance_strength` 1.0 the league fixture's pooled platoon
  gap is about .016 (LHB .023, RHB .012): its hitters are 65% right-handed,
  so the balanced right-handed split is 0.42 of the left-handed one. That is
  owner decision 5 as taken; the 0.006 platoon gate can only be held on a
  league with an MLB-like mix until Release 7 regenerates the fixture.
- `scripts/generate_league_fixture.py` pins the generator's pre-Release-5
  batting-side table (`BATS_THROWS_PRE_R5`) so the committed fixture stays
  reproducible. Drop the pin, and the table, when Release 7 regenerates it.
- `platoon_rhp_counter_scale` (0.35) assumes 26% of PA come against LHP; the
  league fixture runs 31-32%. It could be derived from the league's pitching
  staffs like the batting-side shares.
- The generator still tilts vl by batting side (hitters -4 / +4 for L / R,
  pitchers +4 / -2 for L / R: `player_generator._bootstrap_hitter_ratings`,
  `_bootstrap_pitcher_ratings`, `_sample_normalized_hitter`,
  `_sample_normalized_pitcher`, and the dice ranges in `generate_player`).
  It goes in Release 7 with the data recentring (decision 6).
- `playbalance/archetypes.py::infer_hitter_archetype` reads vl as
  "discipline" (speed_disc needs vl >= 70). It predates "vl is the personal
  platoon split"; the archetype should read Eye. Release 7.
- **Training contradicts the "Platoon vs L" label.**
  `player_development._HITTER_TRACKS["contact"]` is `("ch", "vl", "pl")`, so
  the "Barrel Control" track trains the two of those with the most room, and
  vl is often one of them. The profile now
  tells the owner vl is how a hitter handles left-handed pitching, and that
  more of it gives a little back against right-handers; so a contact drill
  quietly tilts a hitter toward left-handed pitching and costs him against
  right-handers, and nothing on the training page says so. Not changed in
  Release 5 (training is outside it). For Release 7: take vl out of the
  track, or give the split its own track and say what it does.

## Release 5 discipline, contact and situational: follow-ups (2026-10-12)

Raised by the area builders and reviewers; none is fixed in Release 5. The
switched-on values are in `scripts/kpi_profiles/r5_discipline.json`,
`r5_contact.json`, `r5_discipline_contact.json` and `r5_situational.json`.

- **The fresh-arm bonus reaches the pitch only.** `reliever_fresh_bonus` is
  added to the control and movement `simulate_pitch` sees. It does not reach
  the pitcher's share of the batter's eye (`eye_control_blend` in
  `_batter_context`, which reads the raw control) or the wild-pitch and balk
  rolls. Decide whether a fresh arm should also throw fewer wild pitches.
- **A long reliever past nine batters gets the second-pass familiarity
  weight with no fresh edge left.** `tto_pass2_weight` (4.5 in the profile)
  applies to anyone's second trip through the order, and the fresh edge is
  gone by the seventh batter. Check the size against MLB long relief before
  the flip.
- **The league fixture's relievers are rated well above its starters,** so
  its late innings overshoot with the fresh edge on. The fixture is
  regenerated with the Release 7 re-spread; until then read the late-inning
  KPIs on the calibration fixture.
- **An 80 Contact hitter strikes out about 4%, not the owner's 3%** (owner
  decision 1). Under `umpire_model` 1 about 2% of PA end in a called third
  strike whatever the hitter's Contact, and that floor sits under the
  strikeouts the contact model does move. Closing it needs Contact (or Eye)
  in the two-strike take on the edge, not a steeper contact slope.
- **`batter_fatigue_eye_scale` has no effect in the KPI harness.** The
  profile moves it 0.7 -> 0.25 and the harness numbers do not change, so the
  retune is unmeasured. The cause was not run down; find it (or measure
  through the live-path driver) before the flip.
- **Malformed rows are read strictly only once the centred vl is on.** At
  the defaults (kept byte-identical) a batting side that is not L, R or S
  ("B", " l") still takes the platoon edge against both hands, and a stored
  vl of 0 reads as 0 in the engine and as 50 in the lineup auto-fill. With
  `platoon_vl_center_enabled` 1 the side is normalised and a blank or zero
  vl is no personal split, in both. Leftovers: `BatterRatings.from_row` and
  pitch physics (`physics._effective_batter_side`) do not strip the side,
  so " l" still stands in the right-handed box for pitch location and hit
  batters; and a pitcher's own blank vl is untouched (the plan says do not
  fill pitcher vl). A data check at league load would retire all of it.
- **No catcher is "average" for framing only.** `_catcher_context` still
  hands steals, wild pitches and passed balls a flat 50 for a defence with
  no catcher, which reads as below average in a league whose catcher centre
  is above 50 (Release 4 behaviour, live today). Framing under
  `umpire_model` 1 reads the centre instead (`engine._framing_fielding`).
  A real nine always has a catcher (`build_defense_from_lineup` fills an
  open position from whoever is left), so this only shows with a short
  lineup.
- **A live game is reproducible only under a fixed hash seed.**
  `game_runner._apply_bullpen_usage_order` seeds the bullpen's tie-break
  order from `hash((team_id, date, seed))`, and `hash()` of a string changes
  with `PYTHONHASHSEED`; the staff order handed to the engine changes with
  it, and so do some games (at least two of the six in
  `tests/test_r5_live_path.py`, whose digests are pinned under
  `PYTHONHASHSEED=0` and skipped otherwise). `parallel_day` sets it to 0
  for its workers; the Dockerfile does not set it, so a parent process
  started without it does not match them. Seed the order from a stable
  digest (`zlib.crc32` or `hashlib`) instead. Older than Release 5.
- **The hit-batter hand scales are a correction, not a mechanism.**
  `hbp_same_hand_scale` 1.75 / `hbp_opposite_hand_scale` 0.57 put same-hand
  batters at twice the opposite-hand rate with the total unchanged. The
  cause is upstream: pitch targets are side-symmetric and break is added to
  the aim point, so far-inside pitches are mostly glove-side. If Release 6
  gives pitchers arm-side and glove-side aim, re-measure with both scales
  at 1.0 (`hbp_same_over_opposite_hand` in the report-only KPIs).

## Release 5 switch-on mechanism: follow-ups (2026-10-12)

- **Leagues created with a rule preset before this fix.** "High Offense" and
  "Pitcher Friendly" wrote `walk_scale` 1.05 / 0.90 and `k_scale` 0.92 / 1.08
  as if 1.0 were normal; the engine's defaults are 0.83 and 0.51. On the
  legacy engine (calibration fixture, 162 games, seed 1) that is a league
  striking out in 48% (High Offense) or 55% (Pitcher Friendly) of plate
  appearances, against 21.5%, with 5.40 and 0.96 runs per team-game against
  4.43. The other three values were as badly sized: 1% of `offense_scale`
  is about 9% of the runs and 1% of `hr_scale` about 2.6%, so with the
  strikeouts right the old 1.08 / 1.12 / 1.04 gave 11.3 runs a game. The
  presets are fixed for leagues created from now on: they state small
  changes relative to the engine (`physics_tuning_multipliers`), sized to
  about 8-11% more runs for High Offense (4.79 legacy, 4.71 generation 5)
  and 9% fewer for Pitcher Friendly (4.02, 3.84). Those sizes are a first
  calibration on one seed and are the owner's to change. Nothing was
  changed in existing leagues:
  find any whose `physics_tuning_overrides.json` holds those values and
  decide with the commissioner what to do. At such a league's rollover the
  stored values are converted faithfully, so the strikeouts stay until
  someone moves the slider.
- **`utils.roster_loader.load_roster` reads the ACTIVE league for any
  roster.** Observed: `load_roster("ELP", data/calibration_league/rosters)`
  in a checkout whose active league is `cbl` returns six ACT players that
  are not in the fixture's file, in place of six that are, and the
  auto-fill then cannot field nine for that club. The likely cause, not
  confirmed: `_ensure_pitcher_depth` and the placeholder pool decide who is
  a pitcher from the active league's `data/players.csv`. The lineup
  auto-fill's TUNING no longer comes from the active league; its ROSTER and
  depth chart (`lineup_depth_chart`) still do.
- **Help text and tutorial for the rebased sliders** (the labels and
  descriptions marked SWITCH-ON TEXT in `services/physics_tuning_spec.py`)
  are to be reviewed with the news post at the switch-on.

## Release 5 switch-on review fixes: follow-ups (2026-10-12)

- **An image rollback past this release is unsafe once any league is on
  generation 5.** The code before this release does not know engine
  generations: it ignores `engine_generation` in `rating_centers.json` and
  the witness in `season_progress.json`, so rolling the image back puts
  every generation 5 league on the legacy engine in the middle of its
  season (and its converted sliders are read as defaults: the old engine
  does not read the new keys). Rolling forward again returns those leagues
  to generation 5, a second mid-season change. Until every league is past
  its first generation 5 season there is no safe rollback target older than
  this release; fix forward, or hold NEW seasons on the legacy engine with
  `NEXGEN_NEW_SEASON_ENGINE=4` (that does not move a season already on 5).
  A rollback tool would have to refuse while any league records a
  generation above legacy.
- **Left from the lost-`rating_centers.json` case** (closed by the witness
  in `season_progress.json` and the working-copy guard): (a) a season that loses BOTH records
  reads as legacy unless its tuning overrides carry the generation 5
  marker, and a season held back on the legacy engine after a generation 5
  one that loses both reads as 5 from that marker; (b) a
  `rating_centers.json` that exists and cannot be parsed is never
  rewritten, so until someone restores or deletes it each game works its
  rating centres out from that day's rosters (the fault is logged with the
  path); (c) only `rating_centers.json` is pulled again after a failed
  startup pull, every other file that fails to come down is still rebuilt
  by the app and pushed.
- **Creating a league of five teams or fewer through the wizard failed
  under pytest** with the players-file shrink guard ("Refusing to write
  102 player(s) over 600"): the new league's folder is re-seeded with the
  600-player reference `players.csv` after `create_league` has purged it.
  The same call from a plain script succeeded; not investigated.

## Release 5 league-relative ratings: follow-ups (2026-10-12)

`centred_ratings` (generation 5) shifts every rating that feeds a plate
appearance by 50 minus its league centre (RELEASE5_PLAN section 8). What it
leaves, on purpose or because it was out of scope:

- **The pitcher usage centres are a two-weight proxy for innings.** A
  rotation starter counts 2.5 and every other ACT arm 1
  (`pitcher_*_usage_center`). Against the innings-weighted means of a
  played generation 5 season the proxy is within 0.30 of every rating on
  all three test leagues (worst: calibration control, 51.59 against 51.89;
  the plain ACT mean missed by up to 1.79, the league fixture's arm). In
  those seasons a starter threw 164-168 innings and a reliever 75-78
  (closers about 53, long men 91-118), so the measured ratio is nearer
  2.2; any ratio from 2.0 to 2.5 and a weight per relief role all fit
  equally well (rms 0.14-0.17), so the weights were left at two. An
  experiment that pinned the centres to the innings-weighted means
  themselves closed the spread between the leagues a little further than
  the proxy does on the same seeds 1-2 (.13 runs against .16, 0.67 pp of K
  against 0.81, 0.05 pp of BB against 0.18); the BB difference is nearly
  all on calibration (7.72% against 7.81%). Not weighted: the batters a
  pitcher faces by hand, or leverage.
- **The Release 4 running-game terms still read the plain ACT means**
  (`pitcher_control_center`, `pitcher_arm_center`, `pitcher_hold_center`):
  wild pitches, steals and the dropped third strike are centred on every
  ACT pitcher, the pitch itself on the usage centres. Both are right for
  what they were calibrated on; if the running game is retuned, decide
  whether it should follow the usage centres too.
- **Only the mean is centred, not the spread.** Curves that bend still see
  a league's spread: the Power knee (mean bat speed added after the shift:
  calibration 0.70 mph, league fixture 0.83, product league 0.87), the
  one-sided pitch-difficulty terms, the clamps. The Release 7 re-spread is
  the place for it.
- **Read "product-created league" / "product league" in this section as the
  flat-ratings fixture** (`data/calibration_flat`, 7.51.1): it was generated
  without the donor rating file and matches alpha-test's bunched active
  rosters, not a league the product creates today.
- **The product-created league's home runs still trail** (1.10 a team-game
  against 1.21 and 1.21 with the profile as it stands). Not explained by
  a centre. Seen
  and not followed up: its regulars' pull and ground-ball tendencies are
  bunched (sd 1.7 and 1.4, against about 6 and 3 on the fixtures) and its
  average exit velocity is 0.5 to 1.0 mph lower.
- **The regulars are counted by lineup spot, not by plate appearance** (the
  leadoff man bats more than the ninth hitter), pinch hitters and rest-day
  substitutes are left out, and a club with no usable lineup file counts
  its nine best ACT hitters by the auto-fill's base score, with no position
  coverage (the auto-fill would start a weaker catcher or shortstop). The
  centres are fixed when the season's entry is created, from the lineup
  files as they are on disk that day; a CPU club's stale file reads as its
  nine best.
- **A generation 5 season entry that is not whole is recomputed, even
  mid-season.** The entry records which definition its Release 5 centres
  have (`centers_version`). One without the current marker that holds any
  of the seven (an earlier build of this release wrote it; or this build
  recorded the generation and a stale 7.50.3 instance then merged its own
  every-ACT-hitter centres into the entry) has all seven recomputed from
  that day's rosters and lineups; one with the marker that is missing some
  (no ACT pitcher resolved when it was created) has those added. Both are
  reported once (`[engine-generation]` on stdout and in the log). A season
  already under way therefore changes its centres once. That was chosen
  over leaving it: half-shifted, the league fixture played 3.79 runs a
  game with 25.6% strikeouts against 4.56 and 23.2% (one season, measured
  in the review). A LEGACY season's entry is still never touched. What is
  left: (a) the stale 7.50.3 instance of a deploy overlap still plays its
  own games of a generation 5 season on the legacy engine -- that build
  knows no generations; (b) a read-only caller (a page, a
  watched game) gets the recomputed centres without storing them, so until
  a season game runs they follow the day's rosters.
- **A generation 5 game refuses to play without its centres**
  (`physics_sim.centred_ratings.RatingCenterMissing`, raised before a
  workload or a pitch is touched). Every centre defaults to 50.0, and the
  engine used to take that for the league's. Any tool that plays games on
  the generation 5 profile must now hand it the league's centres
  (`with_rating_centers` in the harness, `get_rating_center_overrides` on
  the live path); `utils.lineup_autofill.platoon_tuning` and the other
  readers that only score hitters are unaffected. A league whose pitchers
  carry no pitch grades at all has no grade centre and needs none.
- **Left absolute on purpose:** the pitcher's `vl` (`platoon_pitcher_scale`
  reads it against 50), ground-ball and pull tendencies, speed outside the
  Release 4 terms (the doubles and triples speed terms, the bunt, the
  runner's speed in the pickoff), the lead a runner takes (hold against a
  70 threshold, `_lead_level`), everything about fielding (range, arm,
  double plays, tag-ups, errors), the catcher's glove under the legacy
  umpire model, endurance and durability. The Release 4
  running-game terms keep their own raw-rating-against-the-centre form,
  and under `centred_ratings` the pickoff has joined them: it read the
  pitcher's hold and arm raw against 50 (the one term that made a
  "pitchers +3" season diverge) and now reads both against the plain ACT
  means, like the steals. With the profile as it stands that lowers
  pickoffs (calibration .0071 to .0058 a team-game over four seeds, league
  fixture .0062 to .0042 over two): those leagues' pitchers have arms well
  above 50, which the raw read was crediting. Not retuned.
- **The static guard on centre and rating reads has limits**
  (`tests/test_r5_centred_guard.py`, `test_what_the_guard_cannot_see`): a
  key built with no "center" in any literal or passed in a variable, a
  rating read by `getattr`, a raw rating under a parameter name the guard
  does not list, a read in a module other than `engine.py`, the pitch
  kernel reading an input the engine never shifted, a reader called after
  the raw use. The invariance tests are what catches those.
  The lineup auto-fill and the rest-day replacement rank hitters on raw
  Contact and Power (an order, so a league-wide shift cannot change it).
- **The matchup grid's pitches read 50, not 55, under the switch** (the
  grid pins its grade centre to its own 55, and a cell now goes through
  the engine's own pitcher context). Not re-measured: re-read the log5
  gate with the retune.

## Player development after the aging pause (7.51.2)

- **Training camp can still exceed potential.** `playbalance/player_development._boost_attribute` resets its room to `99 - current` once a rating reaches its potential, so it keeps adding up to 5 points a spring. Mild in practice (Contact sd 5.1 to 7.4 over five springs on a stats-test copy), but it belongs in the same rewrite.

## Release 6a tooling: follow-ups (2026-10-13)

From the tooling step (generation 6 scaffolding, the new rating centres
for the harness, the Release 6 report-only KPIs, the composite matchup
grid). Nothing here changes a game.

- **The fielder-centre fallback is not the lineup a game would build.** A
  club with no usable saved lineup contributes its best hitter by lineup
  value at each PRIMARY position (none where nobody lists the position).
  A game auto-fills a lineup instead. All three fixtures have saved
  lineups, so the fallback is covered by synthetic tests only.
- **The Power fifth ratio in the Release 6 plan reads low.** The design
  prototype sorted hitters tied in Power by their home runs, which puts
  the weak ones of a tie in the lower fifth: on the same season it reads
  .04 to .06 below `hr_power_bottom_quintile_ratio`, which gives tied
  hitters their group's mean (calibration seed 1: prototype .866, KPI
  .928). The plan's .85 / .86 / .80 before and .70 / .67 / .75 after, and
  the .75 target of owner decision 4, were all taken with the prototype's
  order. Re-read the proposal with the KPI before the target is gated.
- **MLB references for the new rows.** None was added to
  `data/MLB_avg/mlb_report_only_reference.csv`: the Statcast per-class
  shares, exit velocities and hit rates, errors by position, the
  ground-ball share by infielder, home run distance and pull / straight /
  opposite by batting side in the plan are from memory. Pull them before
  any of these rows becomes a gate.
- **Not built here, wanted by the design briefs:** per-ball out chances
  (`oaa_per_fa_sd_<pos>`, `team_der_true_sd`, the share of balls with a
  hit chance under .05 or over .95), which need the engine to log the out
  probability and belong with the fielding model; errors by source;
  pitcher chase true sd; hitter GB% and BABIP true sd; foul-outs per
  team-game and per-park home run factors (the ball-flight step).
- **Errors by position are by STARTING position.** The fielding lines
  carry no position, so `e_per_team_game_<pos>` places an error by where
  the fielder started (`GameResult.play_records["starting_positions"]`); a
  substitute's error is in the table as `SUB` and a
  starter moved in a defensive switch keeps his first position. If the
  row is gated, log the position on each error instead (the two places
  an error is charged: the ball in play and `_credit_throw_error`).
- **The 35-80 home run box needs far more than 20,000 PA a cell.** A
  composite-80 pitcher allows about 6 home runs in 20,000 PA on
  generation 5, so the whole pitcher-80 column is skipped as thin
  (`matchup_hr_log5_box_thin_cells` 4) and the maximum residual leaves it
  out. Reading "within .3 logit over the whole box" needs about 100,000
  PA a cell, or a lower `GRID_MIN_EVENTS` with a noise allowance.
- **The batter-adjusted times-through-the-order rows are starters only;**
  the raw `tto_pass2_woba_delta` / `tto_pass3_woba_delta` rows beside
  them are every pitcher. `tables["batter_adjusted_deltas"]` holds the
  starters-only raw value to compare like with like.
- **`power_hr600_p<level>` and the catcher.** The table's hitter faces a
  league-average catcher and carries the fixture's mean pull and
  ground-ball rating; the design prototype used a 50 catcher and 50s.
  Calibration seed 1 agrees with the prototype's table within noise
  (Power 30 / 50 / 80: 11.0 / 15.8 / 69.3 against 10.9 / 15.9 / 68.0).

## Rating scale foundations: follow-ups (2026-10-13)

Found while building the rating-scale foundations (scale 2 is live since
8.0.0):

- **The trade evaluator never sees a hitter's potential.**
  `services/cpu_trade_evaluator._rating_value` reads the `pot_<key>`
  attribute first; `models.player.Player` declares `pot_ch`, `pot_ph`,
  `pot_sp`, `pot_eye`, `pot_fa`, `pot_arm` with a default of 0 and the
  loader fills the `potential` dict instead, so a hitter's potential reads
  as unset and falls back to his current rating: hitters have no upside in
  a trade, pitchers do. Kept as it is here (fixing it reprices trades).
- **The potential rule changes what consumers see for veterans.** Scale 2
  never stores a potential below the current rating, so a veteran whose
  potential was under his rating loses that information at conversion.
  Only the trade evaluator's upside term and the draft AI's
  `development_focus` profile read potentials today.
- **The player generator is not repeatable without a reset.** It
  remembers the names it has handed out, which moves its random stream:
  the same seed gives a different draft class on the second call in one
  process unless `reset_name_cache()` is called (league creation does
  call it). The tests reset it; a draft class generated by a long-running
  server is therefore not reproducible from its seed.
- **`career_arc_analytics` and the report export show flat means of
  stored ratings.** They are displays, left on stored values for the
  display step, but their "overall" mixes moved and unmoved ratings and
  will read differently on scale 2 than the overall everywhere else.
- **Two fixture clubs have eight active hitters.** DEN and ELP in
  `data/calibration_league` cannot field nine through the lineup
  auto-fill (the harness reads their saved lineup files, so no run is
  affected).

## Release 6a fielding: follow-ups (2026-10-13)

Built switched off on branch `r6a-fielding` (the generation 6 values are in
`scripts/kpi_profiles/r6_fielding.json`). Found while building:

- **The engine throws almost no pickoffs.** About 0.1 failed pickoff throws
  per team-game (MLB: a few a game), so `error_pickoff_throw_rate` at a
  believable 2% of throws is .002 errors per team-game. The pitcher's
  errors therefore come almost entirely from comebackers
  (`error_base_p` .0586, which stands in for his bunt and pickoff errors
  too). Re-split when pickoff volume is rebuilt.
- **The catcher's only error is the throw on a stolen base** (about .045
  per team-game). No catcher error on a bunt, a dropped third strike or a
  pop-up, and no first baseman's error on a throw he should have caught
  (every throwing error is the thrower's).
- **Earned runs: a simplified reconstruction.** A runner an `error_model`
  2 error moved up carries a shadow base (where he would be without it)
  that moves on as far as he does, or as far as a hit carries every
  runner; his run is unearned only if the shadow would not have scored.
  Benefit of the doubt to the pitcher, so a runner the error put on third
  who scores on a single is unearned. A pinch runner or an injury
  replacement for such a runner does not inherit the shadow (his run reads
  earned), and an intentional walk or a bunt does not move the shadow
  until the next play. The older errors (an advance or tag-up throw, a
  reach on error) cost the defence an out and keep their old rule. With
  errors at MLB volume the unearned share of runs is 8.9-9.0% on all three
  fixtures (generation 5: 4.5-5.7%; MLB about 7-8%, from memory).
- **No injury roll on the new errors,** nor on a pitcher's error (the old
  roll on a fielder's error is unchanged).
- **`range_scale` under the range model** multiplies the range slopes (a 50
  stays a 50), but still multiplies the catcher's fa and the double
  play's range rating the old way. The commissioner sliders and their help
  text for range, arm and errors need a pass at the generation 6
  integration.
- **Left and centre field sit at the edges of the 5-7 band.** One slope
  cannot put both wide fixtures inside it: the regulars' fa SD is 6.8 (LF)
  and 5.2 (CF) on calibration and 9.4 and 8.3 on the league fixture, a
  wider gap than the band. As built: LF 4.9 / 7.0, CF 4.5 / 7.1 (5.8-6.0
  and 6.8-6.9 per 8 points on both). The rating re-spread fixes the
  spreads, not the slope.
- **A low line drive is an infield play 45% of the time, flat.** Under the
  range model that is now drawn before the out chance (so the infielder
  whose range set it is the one credited), but the share does not depend
  on the ball. The pitcher's band gets liners too and has no range slope.
  The ball-flight step's play model replaces the coin.
- **The pitcher's band is off centre** (-3.4 to 0.0 degrees, toward the
  first-base side): the cut points are the quantiles that give the plan's
  shares, and the ground balls are not centred (more right-handed
  batters, who pull to the left side). The ball-flight step's spray
  widening moves every cut point; re-run
  `scripts/fit_fielding_slopes.py`.
- **The out-of-position table's costs are slope arithmetic.** No season was
  played with starters moved out of position to measure them.
- **OVR defence weights were not changed** (`utils/player_overall.py`;
  owner decision: with the rating scale). Derived from the measured run
  values (runs per fa point per 150 games / 4.8; mean of calibration and
  the league fixture, four seasons each): SS .136, CF .158, LF .136, RF
  .129, 2B .119, 3B .119, 1B .080 (today .15 / .16 / .07 / .06 / .11 /
  .09 / .04). The catcher and every arm weight were not measured.
- **MLB references are from memory:** the split of errors by position and
  by source, the ground-ball share by infielder, centre field's share of
  outfield putouts, the unearned-run share. Pull them before any of the
  new rows becomes a gate.
- **`e_per_team_game_<pos>` is still by starting position;** the exact
  split by the position charged is
  `tables["errors_by_source"]["per_team_game_by_position_charged"]`
  (from `GameResult.play_records["errors"]`). Gate that one.

## Release 6a power and doubles: follow-ups (2026-10-13)

Built on branch `r6a-power`, off by default (`scripts/kpi_profiles/r6_power.json`
over `--engine 6`). Numbers are calibration / league / flat fixture means
(8 / 4 / 2 seasons) unless noted.

- **`corr_avg_contact` is lower** (.59 / .62 / .62 against .63 / .63 /
  .64). A steeper Power curve makes Power matter more to batting average
  through exit velocity, which dilutes Contact's share. The lever is the
  Contact hit edge (`contact_babip_per10`) or the fielding hit table, at
  the joint retune.
- **The top of the Power scale (decision 16).** Stored 99 is set at about
  48 home runs per 650 PA with average Contact and 57 with Contact 80
  (stored 90: 45 and 53), so 90 to 99 is worth about three home runs at
  equal Contact. One anchor serves both Contact levels, so they cannot
  both be hit exactly; `fit_power_table.py` takes the mean of the two
  solves.
- **The double line has a floor** (`physics.DOUBLE_THRESHOLD_FLOOR`, 0.4 of
  the park's double distance) that no shipped setting reaches; a large
  line-drive credit had made it negative. If a commissioner slider ever
  moves `double_gap_scale` or the speed scale, check the floor still
  binds only on nonsense.
- **The line-drive credit reads the rating, not the ball.** A hitter's
  mean launch angle moves 0.1 degree per point of gf and the regulars' gf
  spread is about 3 points, so no rule on launch angle can separate their
  profiles (today's model already gives the fly-ball end 5% more doubles
  and the ground-ball end 5% fewer over 8 points of gf, in a straight
  line). It also sits on that slope, so an extreme ground-ball hitter loses
  more doubles (about 24% at 8 points) than an extreme fly-ball hitter
  (about 15%). The ball-flight release replaces it with hit types from
  landing spots and should delete `double_line_drive_scale` / `_span`.
- **`hitter_gf_center` is the first generation centre**
  (`services.league_rating_centers.GENERATION_CENTER_KEYS`): stored for and
  delivered to a season on generation 6 or later only. The fielding
  centres can join it the same way. `league_rating_centers` now reads the
  season's generation on every call (one more small JSON read per game);
  cache it if it shows in a profile of the season simulator. The stored
  path is tested with a hand-written generation 6 entry, because no league
  can be given generation 6 yet: re-test through `game_runner` at the
  switch-on.
- **A profile cannot add an anchor to `bat_speed_power_table`** (the
  merged-table rule), only change a registered one. The registered table
  therefore carries thirteen anchors on today's curve. A fit that needs a
  new one adds it to `DEFAULT_TUNING` at the knee formula's value.
- **`scripts/fit_power_table.py` re-fits the top anchors only.** The
  weak-bat side and the centre are set with seasons (its docstring). The
  design's population model put the centre at +0.72 to +0.81 mph; seasons
  put it at +0.85. Re-run both after the batted-ball model changes.
- **`pitch_seq_power_avoid_fastball` is a step at Power 60** (stored 80):
  a hitter one point above it sees 8% fewer fastballs. It predates this
  work and was not touched; smooth it when sequencing is next opened.
- **Consumers still assume the old curve:** overall rating, CPU lineup and
  trade scores and salary read Power linearly. Under the table a point of
  Power is worth 0.5 to 0.6 mph below 50, about 0.75 from 52 to 57, about
  1.5 from 57 to 63 and almost nothing above 63.

## Release 6a pitching: follow-ups (2026-10-13)

Built switched off on `r6a-pitching` (stuff weights, velocity model, one
pitch-quality path into exit velocity, additive fatigue; values in
`scripts/kpi_profiles/r6_pitching.json`). Open items:

- **The 91-105 pitch cost and the third-time-through penalty are one
  number read twice.** `starter_woba_delta_91_105_batter_adj` compares a
  starter's pitches 91-105 (all third time through) with his pitches 1-25
  (first time through), so it reads pass-3 familiarity PLUS fatigue: about
  2 wOBA points per unit of `tto_pass3_weight` plus about 10 for the
  owner's moderate fatigue set. The +10 to +20 band, the owner's +11 of
  fatigue and a third pass no easier than the second (`tto_pass2_weight`
  4.5, worth +9 to +11) cannot all hold: the profile's 4.5 reads +22.1 +/-
  2.0 on calibration and +18.6 +/- 1.9 on the league fixture (28 seasons
  each; generation 5 +33.0 and +32.0). DECIDED (coordinator, 2026-10-14):
  accepted as measured, the KPI stays report-only, third-pass weight 4.5
  and the owner's moderate fatigue unchanged. For a later revisit: a set of
  control 1.5 / movement 0.75 / stuff 0.5 / velocity 1.5 costs +5.6 at
  pitches 91-105 and +9.9 at the cap by Monte Carlo, against +9.4 to +11.8
  and +16.3 to +18.2 for the owner's set. One season's value has a
  standard deviation of about 10 points (about 1,700 to 1,950 late plate
  appearances).
- **The corners of the 35-80 matchup boxes** (composite pitcher axis,
  Monte Carlo, 300,000 PA a cell). Home runs: the largest log5 residual is
  +.41 logit at Power 80 x pitcher 80 (generation 5: 2.41); it comes from
  `ev_pq_slope` (.0012 gives .33, .0010 gives .27), not from the chase
  term, at the cost of about a fifth of a good pitcher's home-run
  suppression. Strikeouts: -2.7 points at Contact 80 x pitcher 80
  (generation 5: -1.8); it comes from the chase term (0: -1.7, .01: -2.1).
  Inside 35-65 the strikeout residual is under 1.1 points either way.
  Re-size both with the batted-ball model (accepted for 6a; gates proposed
  on the inner strikeout grid and the p5-p95 home-run grid).
- **League-management pitcher scores still ignore pitch grades.** Only
  the in-game reliever choice (`engine._pitcher_stuff_score`) reads the
  generation's weights. Left on their formulas, to be redone with overall
  rating in the rating-scale pass: `utils/player_overall.py` (control .47 /
  movement .38 / mean grade .15, no arm; generation 6 measures about .23 /
  .27 / .39 / .11 with arm and the usage-weighted grade); the flat mean of
  arm, control, movement and
  endurance in `services/prospect_promotion._player_overall` (its 55 / 65 /
  72 bars are tuned to that score), `inseason_callups._pitcher_score`,
  `player_retirement._player_overall`, `free_agency._quality_score`,
  `finance_ai._free_agent_quality_score`,
  `gm_finance_queue._player_talent_score` and
  `offseason_finance_flow._player_talent_score`;
  `cpu_trade_proposals._player_trade_value`; `api/routers/draft
  ._prospect_overall`; `contracts_service._player_quality_score` (arm .40,
  called "stuff / velocity"); the strategy bonuses in
  `roster_auto_assign`, `finance_ai`, `draft_ai` and `cpu_trade_evaluator`.
  Rotation and bullpen roles (`utils/rotation.py`,
  `utils/pitching_autofill.py`) go by endurance alone: the closer is the
  lowest-endurance arm, whatever his stuff.
- **Re-derive `pitcher_score_weight_*` after the joint retune** (they are
  each rating's FIP per point on the pitching profile alone), and hand the
  same four numbers to the overall-rating work.
- **The legacy fatigue factors are still hard-coded** (`_fatigue_factors`:
  .15 / .30 / .25 with floors .85 / .60 / .65). Only `fatigue_model` 1 has
  registered coefficients. The exit-velocity floor of the pitch-quality
  factor (.75) is hard-coded too; at the generation 6 slope no pitcher
  reaches it.
- **Wild pitches and balks read the pitcher's raw control,** not the
  fresh-arm or tired control the pitch reads (design brief, section 9: not
  worth a mechanism; if touched, hand both rolls the same effective
  control).
- **Generation ownership of the other Release 6a areas' keys.** This area
  makes its own keys mean nothing to a legacy or generation 5 league's
  overrides file (as before they were registered) and owns the ones that
  define its group from generation 6
  (`services/physics_tuning_settings._owned_keys`,
  `R6A_PITCHING_KEYS`). The power and fielding branches register keys too;
  fold them into the same rule at integration, and decide whether the
  generation 6 markers (`_pre_generation_6_r6`,
  `_velocity_slider_rebased_r6`) should count as evidence of a league's
  engine the way `_swing_sliders_rebased_r5` does
  (`league_rating_centers._sliders_rebased`); they do not today.
- **A Velocity Scale set on generation 6 and read back on an earlier
  generation** (a rollback) is kept as the pitch speed it is, not
  reversed; the value set aside at the move comes back only when the
  commissioner had not set one since.
- **Velocity Scale slider range.** On generation 6 the 0.90-1.10 range is
  9 mph either way: 0.95 / 1.05 gave strikeouts of 19.6% / 26.7% against
  23.0% (Monte Carlo). Consider narrowing it, and review the description
  with the help page at the switch-on. Tutorial and owner-guide text for
  the pitching changes is drafted in the build report, not yet in
  `services/tutorials.py`.
- **A take reports the pitch's grade as `pitch_quality`, a swing the
  composite** (unchanged from before; the composite is now worked out on
  every pitch). If the pitch log should carry one number, report the
  composite on takes too -- it changes the pinned game digests.
- **`contact_velo_ref` is a constant 93** (a 50 arm's fastball). The
  Velocity Scale slider moves every pitch against it, which is why the
  slider now helps pitchers; a league whose mean arm is not its
  `pitcher_arm_usage_center` cannot happen under `centred_ratings`, but a
  profile that changes `83 + 0.2 * arm` must move the reference with it.

## Release 6a integration: follow-ups (2026-10-14)

Branch `r6a-int` merges the scale, fielding, power and pitching branches and
builds `engine_6.json` from generation 5 plus the three area files (no key
is set by two of them). Generation 6 is still a development generation.
Measured on 8 / 4 / 2 seasons (calibration / league / flat fixtures):

- **Generation 5's full strikeout-grid gate fails on the composite grid**
  (`matchup_k_log5_max_abs_resid` .027 against .02, calibration seed 1,
  60,000 PA a cell): the Contact 80 x pitcher 80 corner the pitching work
  accepted. The inner grid (.009) and the p5-p95 HR grid (.019) pass.
  Decide at the joint retune whether generation 6 keeps the full-grid gate
  or drops it for the inner one.
- **`hr_scale` is the pitching work's 0.9195**, re-levelled with the power
  table off; the power work held home runs with the table's centre. Each
  alone adds about +.02 / +.00 HR a team-game on calibration and together
  +.02: no double count today, but both levers set the same level.
- **The flat fixture misses three of the new gates** (report-only there;
  bunched ratings): the pull-rating correlations .68 / .70 against .80,
  BB% per +10 control -0.68 against -1.35, and shortstop outs per 8
  points 6.06 against 6.9 +/- .8.

### Joint retune of generation 6 (branch `r8-retune`, 2026-10-14)

`babip_scale` .92 -> .902, and the seven `range_logit_slope_<pos>` scaled by
.92 / .902 so a fielding point is worth the outs it was (the slope fit
divides by `babip_scale`). Recorded in `scripts/kpi_profiles/r6_retune.json`.
Runs 4.38 / 4.63 / 4.42 (calibration 8 / league 4 / flat 2 seasons; were
4.50 / 4.77 / 4.51), doubles 1.57 / 1.70 / 1.66. Open:

- **The calibration strict set is a lottery at about 5-6 clean seasons in
  8, whatever the run level.** Besides the full strikeout grid (still
  .027 on the composite grid; the retune does not touch it), the
  rating-slope gates `bb_pct_per10_control` (mean -1.49 against -1.35 +/-
  .25), `pitcher_fip_per10_arm` (mean -.16, edge -.05) and
  `pitcher_hitter_hr_true_sd_ratio` each miss on roughly one season in ten,
  and the retune does not move their means. Gate them pooled over seeds (as
  the thirty-homer count is), or re-centre `bb_pct_per10_control` on what
  the command model gives.
- **The ISO gate contradicts its neighbours.** The benchmark file says AVG
  .245 and SLG .392 (ISO .147) and ISO .165 +/- .015 (floor .150). Generation
  6 sits at ISO .152 (season minimum .1496), so one calibration season in
  eight or so misses it. Restate ISO from the same years as SLG and AVG.
- **Calibration's BABIP floor (.276) and ISO floor bound the run level
  from below; the league fixture's runs bound it from above.** The league
  fixture scores about .25 a game more than calibration at the same BABIP
  (its speed tier: triples .20, steals .82, doubles +.13 a game, from the
  raw-speed terms `double_speed_scale`, `triple_speed_scale`, the tag-up
  race). A home-run lever cannot help: `hr_scale` .9213 put calibration
  ISO at .1536 but the league fixture at 4.68 (seasons 4.62-4.71).
  The ball-flight step (BABIP .291) needs the run level from somewhere else.
- **League fixture SF/PA still .0078 (fails the running set on 2 of 4).**
  Not the run level: a hit lost to `babip_scale` becomes a fly out, so the
  tag-up chances stay. Generation 6 has 5-7% more runner-on-third fly outs
  than generation 5 (more runners: errors at MLB volume, the fielding
  centring) and scores a little more often on them (fly outs now go to
  centre field, .42 of outfield putouts against .34, whose arms are weaker
  than right field's; slightly longer carry under `hr_scale` .9195, fewer
  short pop-ups). The tag-up race is calibrated to drag-free carry and is
  due its refit with the ball-flight step; tightening `tag_up_send_margin`
  now would push calibration's score rate (.74) below MLB's 72-78%.

## Rating scale 2 display: follow-ups (2026-10-14, branch `r8-display`)

Built: a league whose `players.csv` is on rating scale 2 shows stored
ratings on every page, the overall through a fixed display map and stars
re-anchored (`utils/rating_display.py`, `utils/star_rating.py`); a scale 1
league's payloads are byte-identical (pinned in
`tests/test_rating_scale_display.py`).

- **alpha-test's pitchers read low until the re-spread.** Converted
  without the decision 15 re-spread, alpha's best shown pitcher overall is
  59 and its control, movement and arm top out at 68 / 56 / 52; hitters'
  fielding and arm at 60 / 64. The re-spread fixes it; check the shown
  overalls after it (the map was fitted without alpha's pitchers).
- **The overall display map is fixed, not league-relative.** The best
  shown overall is 90 (stats-clean), 91 (alpha-test hitters), 85 / 88
  (league fixture hitters / pitchers) and 83 / 83 (calibration). Refit
  `FULL_SCALE_OVERALL_MAPS` if the generator's spread changes (Release 7
  generator work) or once development runs.
- **The profile's scouting error is keyed on the player's own club**
  (`_resolve_team_id(player)`), not the viewing owner's club, on both
  scales. Pre-existing; "fog of war on other clubs' players" needs the
  viewer's team passed in.
- **The draft page's overall on scale 2 is the shared overall**, the
  number every other page shows, not the six-rating mean the auto-pick
  ranks by (that stays, in engine terms). The pool list can therefore be
  ordered differently from the auto-pick; on scale 1 nothing changed.
- **Promotion and call-up summaries still carry the promotion score.**
  News lines and transaction notes quote the shown overall on scale 2
  (`utils.rating_display.overall_for_text`), but the `overall` in the
  dicts `run_yearly_promotions` / `run_monthly_callups` return (and the
  sim-day response's `callups`) is still the engine-scale promotion score.
  No page shows it today; convert it if one ever does.
- **The display caches are invalidated by this process's own writes**
  (`utils.players_file_writes.note_players_file_written`, called by the writer,
  the draft append, the injury-date repair tool and the working copy's
  copies). A players.csv written by another process in the same timestamp
  tick with the same size is still only caught by the file's clock.

## 8.0.0 switch: follow-ups (2026-10-14)

Branch `r8-switch` builds the move to generation 6 and rating scale 2
(`services/rating_scale_migration.py`, `docs/rating_scale_switch_runbook.md`)
behind `NEXGEN_GENERATION6_SCALE2`, OFF. Open:

- **An older build can still append a draft pick** to a converted league
  (its draft writes under the file's own header); the row has a blank
  `height_in`, and this build refuses to load the league until it is fixed
  by hand (runbook section 5). Detected, not prevented. A scale 2 draft pool
  in a format older builds refuse would close it.
- **The re-spread maps a whole population onto a whole population.** A
  bunched league's regulars are spread through its population, so their
  spread comes out near, not at, the reference's ACT spread (alpha-test 0.8
  to 1.1x, the flat fixture up to 1.35x for movement). An ACT-only map would
  hit it exactly but cannot keep order between levels.
- **The bunched rule's threshold sits close to stats-clean** (lowest ratio
  .64 against .60). It only matters for a league listed in
  `NEXGEN_RESPREAD_LEAGUES`, but a league created before the donor file
  existed could be picked up if listed.
- **Re-spreading endurance changes roles read from endurance** (alpha-test's
  rotation starters 59-81, median 64; its other active arms 29-58, median
  36; every arm sat at 48-52 before): the
  staff file still decides the rotation, but `role_from_endurance` and the
  CPU's roster logic now see starters and relievers. Measured: starters
  +0.25 innings and +4.3 pitches a start, -0.14 relievers a game.
- **The commissioner is told through the news feed** (`[commissioner]`
  item) and `rating_scale.json`; there is no commissioner inbox.
- **A save of players loaded before a move writes scale 1 rows** into the
  converted file (kept, correct on their own scale); a generation 6
  season repairs them at its next game, but a league moved at its
  rollover is not repaired until its next season's first game. Harmless
  for play; owners could see a few unconverted numbers in between.
- **A refused league is re-offered every season** and stays refused until
  someone changes the blocking ratings (runbook section 3 lists the
  remedies). There is no in-app tool for the commissioner to do it.
- **The generator's draft class depended on whether the data dir had been
  resolved before the first call** in a fresh process (seen while checking
  scale 1 identity against `r6a-int`; both trees behaved the same once it
  was). Not investigated.

## Player development on rating scale 2: follow-ups (2026-10-14)

Branch `r8-develop`: `playbalance/development.py` (the model),
`services/offseason_development.py` (the rollover step),
`scripts/development_population_sim.py` (the 20-season population gate).
Scale 1 is untouched (aging stays paused, camp as in 7.51.2).

- **Generated players are now dated from the league's year (fixed on this
  branch).** `player_generator.reference_datetime`: today moved into the
  league's year (draft classes: into the draft year). A league whose year is
  the real year generates exactly what it did. Other places that still age
  players by the real calendar (`draft_ai._player_age`,
  `roster_auto_assign` line ~532, `player_profile_view_model`,
  `scouting_service`, `dl_automation`, `finance_ai`, `contracts_service`
  fallbacks) are out of this change; they misjudge ages in a league ahead of
  the calendar and should take the sim date.
- **The players file has no declared encoding.** `utils.player_loader` and
  `utils.player_writer` open it in the platform's encoding (UTF-8 on Cloud
  Run, cp1252 on a Windows desktop), so a file moved between the two reads
  accented names wrongly. The development step matches them on purpose
  (`offseason_development._encoding`); the fix is one explicit encoding for
  the whole product, with a migration.
- **Every league converges to what the draft generator produces.** The
  regulars' Contact starts at 62.9 in stats-test and 56.8 in the league
  fixture; both end near 60, so stats-test drifts down about 4 and the
  fixture up about 4-5 over 10-15 seasons. Power, Eye, control and movement
  hold within about 3 in both. A league whose ratings were made by an older
  generator moves toward today's; the model cannot hold two leagues that
  start 6 points apart.
- **alpha-test needs its re-spread (decision 15) before development.** On
  the stretch alone its bunched staff (movement sd 0.9) drifts to the
  generator's level: movement +16, control +10, Eye +9 over 15 seasons.
- **Development marker and the players file are two writes.** A crash
  between writing `players.csv` and `development_last.json` lets a re-run
  develop that season again. Small window; a marker inside the archived
  season record written in the same lock would close it.
- **A growing player's stored potential rises.** The scale 2 potential is
  stored current plus the gap in ENGINE points, so as Contact grows by
  three stored points per engine point the stored potential climbs with
  it. Hidden from owners (decision 14); any future display of potential
  must show `engine_potential` mapped, not the column.
- **Two views of a scale 2 potential.** `engine_row` (the engine, which
  plays no potential) keeps the whole gap; `engine_potential` (CPU
  consumers) leaves out `POTENTIAL_GAP_DISCOUNT` (20.5 engine points).
- **Speed barely declines** (0.1 + 0.06 a year from 28): tuned for the
  regulars' speed to hold. Revisit with the generator's speed tiers (the
  league fixture's archetype tiers are not in draft classes, so its speed
  falls about 6 regardless).
- **The training budget's description** ("Boosts spring-training rating
  gains at preseason camp", `desktop/src/pages/FinancePage.tsx`) is wrong
  for a scale 2 league: there the training and development budgets speed
  offseason growth, and development also slows decline. Same for the
  Training page, which should say the focus shapes offseason development.
- **Population sim simplifications.** Active rosters are 13 + 13 by
  overall with no position balance; free agents never retire (as in a
  league) and are not signed past 35; injuries, trades and playing time are
  ignored; the draft order is random.

## 8.0.0 integration: follow-ups (2026-10-14, branch `r8-int`)

Branch `r8-int` (merged into 8.0.0). Open:

- **CI's generation 6 step is continue-on-error.** Make it blocking once it
  has passed on the runner (it passes locally on calibration seeds 1-8).
- **League fixture SF/PA** fails `--gate-set running` on seeds 1 and 3 (.0081,
  .0079 against .0068 +/- .001), as in the retune; the tag-up race refit
  belongs to the ball-flight step (RELEASE6_PLAN section 8).
- **The move's rollover artifact is not in the archived season record.**
  `artifacts["rating_scale_move"]` is set after `archive_current_season`
  copied the artifacts, so the season record and `metadata.json` do not
  carry it (the development step writes its own through
  `_record_in_archive`). `rating_scale.json` and the news item do record the
  move; route the move's result through `_record_in_archive` too if the
  season history should show it.
- **Encodings.** The move writes `players.csv` in UTF-8; the development
  step reads and writes it in the platform's encoding (cp1252 on a Windows
  desktop, UTF-8 on Cloud Run). Same on the server; on a desktop an accented
  name written by the move would be misread by development. Part of the
  existing "one declared encoding" item above.
- **Scale 2 numbers in the tutorial are worked out, not measured on a
  converted league.** The Contact strikeout rates at stored 65 / 80 / 95
  interpolate the Monte Carlo grid (engine Contact 50 / 65 / 80) in logits;
  the Eye, Control, Arm and catcher figures apply the measured per-10-point
  slopes through each rating's map. Re-measure on a converted league once
  one exists, and after the re-spread of alpha-test.

## 8.0.0 switch-on rehearsal: issues still open (2026-10-14)

The rehearsal drove full copies of alpha-test and stats-test through the
real API with the switch on (`r6/p8/rehearsal/` in the session scratch).
These are 7.51 behaviours it ran into, not 8.0.0 changes:

- **Owner clubs' auto-generated depth charts never picked up arrivals.**
  Fixed in 8.6.1 (`api.routers.season._ensure_depth_charts` refreshes every
  club's auto chart).
- **The 2026 World Series was dated 2027-01-19 to 01-24.** Explained in
  8.6.1: both live leagues' 2026 schedules predate Release 3's dense layout
  (162 game dates from April 1 to December 30). The 2027 schedule runs April 1
  to October 8 (`tests/test_schedule_season_length.py`).

## Contract re-negotiation with your own players (owner request, 2026-10-16)

> **Shipped in 8.5.0 (2026-10-25):** extension talks (`services/extension_talks.py`:
> an ask above a hidden minimum, patience, 7-30 day shutdowns counted in
> free-agency window days during the window, walk-year veterans refusing
> in-season talks, a 1.5x "crazy offer" always accepted), extensions priced
> at the free-agent market, and CPU clubs extending the walk-year players
> they want within their budgets (`services/cpu_extensions.py`). Open:

- **Service time never accrued.** Fixed in 8.5.1 (`services/service_time.py`,
  back-fill `scripts/backfill_service_time.py`). The walk-year refusal still
  falls back to age 27+ for a player with no service; with service tracked,
  it uses six years.
- **CPU extensions in the offseason.** Done in 8.6.0 (the FA window's first
  day and the move into the preseason).
- **Free-agent offers.** Done in 8.6.0 (offer rules 2: an ask above a hidden
  minimum, `extension_talks.fa_terms`; a window opened before 8.6.0 keeps
  rules 1 until it closes).

## Owner feedback on salaries, 2026-10-26 (8.6.2)

- **Existing contracts sit far below the market (left as they are, owner's
  call).** alpha-test's contracts from league creation were priced with no
  service time (age-based pre-arbitration tiers): median $1.2M, about 20% of
  the model's market value, while this offseason's free agents signed at a
  median $8.75M (116% of it). Re-pricing them all (never cutting pay, real
  service time) would take the league median payroll from about $71M to
  $129M. The owner chose to let them re-price as they expire (1-6 seasons),
  so free agency looks expensive next to them until then. A new league seeds
  its opening-day big leaguers' service time by age (8.5.1), so its starting
  contracts would still be priced without it: revisit seeding if this comes
  up again.
- **Pitchers were priced mostly by arm.** Fixed in 8.6.2 (priced by the
  shared overall, after alpha-test's window opened before 8.6.0 closes).
- **"Catchers are fast."** alpha-test's catchers average 52.9 speed (faster
  than 3B and corner outfielders), from the generator used when it was
  created; today's generator makes catchers the slowest hitters (38.6; the
  2027 draft class 30.8). Existing catchers keep their ratings (owner's
  call).

## Release 6b round 2: ball-flight follow-ups (2026-10-15, branch `r7-ballflight`)

Engine generation 7 (RELEASE6_PLAN section 9). Round 2 re-fitted the
kernel, the whole Power curve, decision 19 and the parks, gated the new
model and gave the Home Run and Launch Angle sliders their generation 7
meaning; round 3 made it ready to ship switched OFF behind
`NEXGEN_GENERATION7` (section 9.5, `docs/generation7_switch_runbook.md`).
The owner accepted the misses below as they stand (decisions 21-24,
2026-10-15); they stay here as backlog. Open:

- **The mean home run is 389-390 ft (about 400 asked), 450+ ft .5%**
  (decision 22: accepted for now, gate 395 +/- 10). The kernel re-fit
  (`kfit.py`, Savant 2024 shape: hard-hit, barrels, classes, sweet spot,
  mean exit velocity, 83% of home runs barrels) reaches hard-hit .40, barrel
  .077 and the classes with HR held at 1.14 a team-game, but not the
  distance (Monte Carlo 390.6 ft). Round 1 measured +1.3% exit velocity
  with carry .98-1.0 at 398-401 ft and 2.1-2.8 HR a team-game; round 2's
  fits with carry pinned at 1.0 could not hold home runs (loss 956 against
  the chosen fit's 137). The next lever is the hardest contact's launch
  angle spread (more high, long fly balls that are not home runs) or
  descent-dependent wall clearance; neither was built.
- **HR per barrel .43** (Monte Carlo on the calibration kernel inputs). The
  ".6" asked for is 2017's figure; MLB 2024 is about .47 by arithmetic
  (5,453 HR, 83% barrels, 9,716 barrels) and published figures run .45
  (2022) to about .61 (2017). Not gated.
- **r(pull rating, pull angle) .58-.66** on the wide fixtures (gate .70 +/-
  .20; one league season of four reads .50). Spray widening (sd 40) is the
  cause.
- **Park hit types** (decision 24: left unfitted): Coors singles 102 against
  Savant's 115, Fenway doubles 108 against 120, Chase triples 118 against
  208, Comerica triples 97 against 150, Oracle triples 82 against 141,
  Busch triples 128 against 69, Progressive triples 120 against 63. Fit
  doubles and triples by park (a per-park gap or wall-carom term) if they
  ever matter. The large per-side home-run shifts are accepted (decision
  23).
- **`pitches_per_pa` 3.81-3.82 on calibration** (3.86 +/- .05; 3 of 8
  seasons fail by under .01; seed 1 passes). The foul-out draw ends some
  plate appearances a pitch early; a foul-rate nudge would cover it.
- **The flat fixture** fails runs, HR, doubles, the pull correlations and
  three pooled pitching slopes (pitcher GB% true sd .023 there): it has
  almost no rating spread, so these are report-only for it, as before.
- **The CI step** (`--engine 7 --strict`, calibration seed 1) is not
  blocking; make it blocking once it has passed on the runner (Python 3.12
  there; seed 1 passes locally on 3.11).
- **A per-league engine hold.** Holding a league on generation 6 while
  others move to 7 needs either the service-wide hold or an operator's
  `set_recorded_generation` (the runbook, section 4); a `"hold_generation"`
  in `rating_scale.json` would be cleaner if leagues ever need it.
- **Foul-outs** are caught by the catcher (30%) or the corner infielder on
  the ball's side, never by anyone else, and never drop for an error.
- **Pop-ups and foul-outs in season stats** (round 5, backlog). Box scores
  name the foul-outs (the fielding note); the season stats pages have no
  batted-ball columns at all (a pop-up counts as a fly ball in the box
  lines), so pop-ups and foul-outs per hitter and pitcher need new stat
  keys, their accumulation (`playbalance.stats`) and columns on the stats
  pages. Do it with any batted-ball columns (GB / LD / FB / PU, hard-hit).
- **The live-league copies' pooled pitching gates** (round 5): two seasons
  each of the rehearsal's 2028 rosters miss pitcher GB% true sd (alpha-test
  .049, gate .075 +/- .025) and, on stats-test, three pitching slopes
  (walk rate per 10 control -1.18, pitcher / hitter HR true-sd ratio .71,
  HR per 10 points of pitcher GB rating -21%). Roster-driven (bunched
  ground-ball ratings, a different staff mix); look again after a season of
  generation 7 play.
- **Old park names on generation 7** (round 5): a team whose explicit
  `park_id` was picked under a name the park carried only before 2000
  (KAN06 as "Royals Stadium") plays the generic park on generation 7,
  because the engine reads the park by its name. The generation 7 catalog
  no longer offers such names; carry the park id into the engine if one is
  ever found.

## 8.1 hotfix: one club per player, parallel days (2026-10-16, branch `r81-hotfix`)

Shipped in the 8.1 hotfix: one club per player, and a day with a player in
two of its games plays serially under `PB_PARALLEL_GAMES`. Left open:

- **Placeholder pitchers can be shared in memory.** `load_roster` pads a
  club with fewer than six pitchers from the placeholder pool; with toy test
  rosters two clubs got the same placeholder arm. Real leagues have full
  staffs, and the write guard refuses to save such a roster.
- **Lost 2026 lines.** alpha-test's pitching totals are one start short of
  its team totals (13 batters faced, 5 runs, 5 hits, 1 home run, 1 GS). No
  box score from 2026-05-06 on shows a player in two games of a day, and no
  player's season line is below his box-score sum, so it happened before
  the box scores begin (none exist before 2026-05-06) and cannot be traced
  or repaired from them. stats-test's player and team totals agree, but its
  CHI and WAS show 161 team games each against 162 scheduled; not traced.
- **Parallel and serial differ on a season's first day** (found by the
  branch review, 2026-10-16; the base commit has the same difference). The
  season's `rating_centers.json` entry is fixed from a different league
  state in each mode: the parallel day fixes it in the parent before the
  fan-out (`SeasonSimulator._simulate_day_parallel`, "fix the league's
  rating centres here, once"), the serial day inside its first game. The
  review's copy of alpha-test played 2027-04-09 COL at LAS 5-6 in parallel
  and 6-7 serially; every later day matched. Fix by fixing the centres at
  the same point in both modes (before the day's games, serial too); that
  changes which numbers a serial league records, so it needs its own
  identity check and was left out of the hotfix.

## Playoff stat totals (owner request via an alpha-test owner, 2026-10-16)

> **Shipped in 8.4.0 (2026-10-22):** postseason pages (`services/postseason_stats.py`);
> playoff totals have been kept apart from the regular season since 8.1.1. Open:

- Series-by-series player lines (round, opponent, result) and a series MVP.
- The legacy `GameSimulation` path (disabled in production by
  `legacy_guard`) still adds a playoff game into the season totals.
- Archive with the season at rollover like the regular-season stats; include
  in the almanac / exports.

## 64. Make salary arbitration work like real baseball (owner request, 2026-10-26)

**How it works today** (`services/offseason_finance_flow._apply_arbitration_updates`,
run at the rollover after service time closes, contracts count down and
qualifying offers):
- Eligible: a player still **under contract** going into the last year of
  his deal with 3+ years of service (516 days); Advanced adds a "super two"
  (2 years left, 2 years + 120 days).
- Award: a flat raise on his current salary, +12% (Basic) or +22% (Advanced,
  super two at most 16%). Owners' clubs always get the standard raise; CPU
  clubs' raise is adjusted by `finance_ai.recommend_cpu_arbitration_decision`
  (stars more, underperformers less, a contender on a cautious budget can
  non-tender), and the payroll rules can hold it. The commissioner has a
  per-club review queue (`services/gm_finance_queue.build_arbitration_queue`).
- The talent score is the old flat rating average (`_player_talent_score`,
  arm and endurance in, eye out for pitchers; see #52).
- The level is the finance module `gm_arbitration` (off / basic / advanced),
  set only through the finance preset at league creation: "Simple" turns it
  off (alpha-test), "Standard" basic, "MLB-like" advanced. stats-test is
  Basic and has never rolled over.

**What's wrong with it:** the award ignores the market (alpha-test's
creation contracts sit at ~20% of market value, so +12% barely moves them);
it raises players still under contract instead of players whose contracts
ran out; a player whose deal expires becomes a free agent whatever his
service time (only qualifying offers hold him); owners make no decision.

**Asked for:**
- A league-creation option for arbitration, on its own (not only through
  the finance preset): **Off**, **Automatic** (today's behaviour or a
  hands-off version of the new one: the club tenders and the award is set
  without owner input), or **MLB-like**.
- MLB-like:
  - Players with 3-6 years of service (plus the super-two group) whose
    contract runs out stay under club control instead of becoming free
    agents; 6+ years reach free agency as now.
  - The club decides to **tender** or **non-tender** each one before a
    deadline (non-tender = free agent); owners decide for their clubs, CPU
    clubs with the finance AI (and its payroll ceiling, like
    `services/cpu_extensions.py`).
  - The award is market-based: a share of the free-agent market value
    rising with each arbitration year (`contracts_service`'s stage /
    `arb_year` already model ~ pre-arb / arb 1-3 / FA), driven by
    performance and the shared overall, never below the current salary.
  - Optionally the club and player exchange figures and the "hearing" picks
    one, or the two settle in between; extension talks
    (`services/extension_talks.py`) stay open until the hearing.
  - Dashboard Spotlight + news when arbitration opens, for each owner's
    eligible players and before the tender deadline (owners must not have
    to go looking).
- The commissioner can change the setting for an existing league (takes
  effect at the next rollover).

**Status:** Open. Owner said to leave the current behaviour alone for now
(alpha-test stays off).
