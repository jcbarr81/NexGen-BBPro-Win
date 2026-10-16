# Future Work Ideas

This note captures high-level enhancements identified during the latest review so
they are easy to revisit when planning new milestones.

> ## ⚠️ Reconciliation banner — updated 2026-07-13 (app at VERSION 7.0.11)
>
> **This backlog drifted badly out of date and was reconciled against the actual
> code on 2026-07-13.** The item numbering below still uses "v5.x" milestone
> language, but the product has since shipped a full **Electron + React client,
> a FastAPI backend (~60 routers), and a Firebase / Firestore / Cloud Run
> multi-tenant cloud deployment.** The legacy **PyQt `ui/` app is retired.**
>
> **Source of truth for what shipped is `release_notes.md` + `git log`, not this
> file.** When an item below conflicts with this banner, the banner wins.
>
> ### Verified status corrections (checked in code 2026-07-13)
> | Item | Old status here | Verified reality |
> |---|---|---|
> | #7.1 multi-league / #7.2 online path | Open | **Done** — Firestore multi-tenant + Cloud Run |
> | #7.3–7.5 messaging / chat / forums | Open | **Still open** — genuinely not built (real gap) |
> | #20 Player Morale | Open | **Still open** — zero code (real gap) |
> | #32 Simulation speed | Open | **Done** — ~5× faster shipped in 7.0 |
> | #34 Overwrite-league admin pw | Open | **Fixed** — `playbalance/league_creator.py` purge+reseed |
> | #37 Star rating for elite players | Open | **Fixed** — top-N blend in `api/routers/_rating_presentation.py` |
> | #38 Contract details + contracts page | Open | **Done** — `ContractsPage.tsx`, `ContractCard` |
> | #39 In-season renegotiation | Open | **Done** — `services/contract_negotiator.py` |
> | #43 Draft-day crash | Open | **Fixed** — phase-resume guard in `api/routers/draft.py` |
> | v5.4 What-If / story / highlight-recap | Planned | **Mostly unbuilt** (What-If deferred; live game viewing exists) |
>
> ### Superseded by the React/cloud rebuild
> All **PyQt-desktop-UI** items (#18 handoff export, #21 theme-asset expansion,
> #36 player-profile redesign, #41 season-progress layout, #42 owner-dashboard
> readability) targeted the retired PyQt app. Re-scope against `desktop/` (React)
> before actioning — several are already addressed by the new client.
>
> ### Sim engine note
> Games run on `physics_sim/` (the `playbalance/` engine is archived behind
> `PB_ALLOW_LEGACY_ENGINE=1`). Target all realism tuning at `physics_sim/`. The
> one remaining sim gap is the disabled empirical park-factor multiplier
> (`park_factor_scale=0.0` in `physics_sim/config.py`).
>
> ### Not independently re-verified on 2026-07-13
> Items not in the tables above (e.g. #23 CPU trade AI, #24 strategy profiles,
> #35 single-user onboarding) keep their prior status and should be confirmed
> against code before planning.
>
> ### Active improvement program (2026-07-14)
> The current sprint-planned work (efficiency, UI, sim realism) lives in
> **`docs/deep_review_plan.md`** — the truth document for the deep-review
> program. Check there before picking up any performance/realism/UI task.

## 1. Unified Data Service Layer
- **Goal:** Stop re-opening CSV/JSON files in every module by introducing a
  repository/service layer (see `docs/Architecture.md`). This would centralize
  persistence, reduce I/O contention, and unlock alternative backends (SQLite,
  cloud sync).
- **Scope:** Wrap common loaders (players, rosters, standings, transactions) in
  shared query/update APIs and expose an event bus so UI widgets can subscribe to
  changes instead of issuing file operations directly.
- **Status:** Complete.

## 2. League History & Archive UI
- **Goal:** Surface the new season archives produced by
  `SeasonContext`/`LeagueRolloverService` inside the Admin dashboard.
- **Ideas:** Add a "League History" page showing champions, awards, standings,
  and playoff brackets per season; extend player/team profile dialogs with a
  season selector that reads from `data/careers/<season_id>/`.
- **Status:** Complete.

## 3. Contracts & Financial Systems
- **Goal:** Expand the simple free-agency helpers into a richer contract model
  with budgets, multi-year deals, arbitration, and salary impact on trades.
- **Scope:** Extend `services/contract_negotiator`, add organization finances,
  and build UI (owner + admin) to review commitments, payroll, and cap space.
- **Status:** Complete.
- **Follow-on enhancements:** Tracked in `docs/financial_backlog.md`
  (FIN-BL-001 through FIN-BL-007).

## 4. Deepened Player Development
- **Goal:** Turn the current "training camp marks everyone ready" flow into a
  meaningful development phase with focus tracks and aging effects.
- **Ideas:** Add training plans per player, hook into `playbalance/aging_model`,
  and reflect outcomes in ratings plus new tutorial/UX messaging.
- **Status:** Complete.
- **Follow-on enhancements:** Morale-specific systems are tracked separately in
  item 20 below.

## 5. Pitch Budget Telemetry & Tuning
- **Goal:** Finish the `docs/pitch_budget_model.md` roadmap by pushing budget
  metrics to the UI so commissioners can validate reliever workloads.
- **Scope:** Expose `available_pct`/rest info on dashboards, integrate
  `scripts/usage_calibration.py` summaries, and add tests to lock in MLB-like
  appearance/IP targets.
- **Status:** Complete.

## 6. Outstanding Test Failures
- **Reminder:** `docs/failing_tests.md` still lists unchecked pytest targets
  (e.g., simulation averages, foul balls, stadium dimensions, stats windows).
  Clearing these before new features will keep regression risk low.
- **Status:** Complete.

## 7. Multi-League Ownership & Collaboration Roadmap
These initiatives enable a single owner to juggle multiple leagues, move saves
between offline/online modes, and collaborate with other owners through
messaging, chat, and forums. Tackle them in the order below so shared services
land before channel-specific features.
- **Status:** Partially complete (reconciled 2026-07-13). 7.1 (multi-league per
  owner) and 7.2 (online league path) shipped via Firestore multi-tenant +
  Cloud Run. 7.3 messaging, 7.4 chat rooms, and 7.5 forums/trade-block remain
  **Open** — genuinely not built.

### 7.1 Multiple Offline Leagues per Owner
1. **Domain model:** Introduce `Owner` -> `LeagueProfile` -> `Season` entities plus
   ownership/role tables so one owner can switch contexts safely.
2. **Storage:** Centralize persistence in a franchise service layer (SQLite or
   repo abstraction) that keeps per-league saves isolated yet linked to an owner.
3. **Config templates:** Allow each league to define rule sets, schedules, AI
   levels, and presentation settings; expose template cloning for quick setups.
4. **Owner dashboard:** Build a cross-league hub showing active leagues, alerts,
   save health, and shortcuts (resume sim, manage roster, pending trades).
5. **Portability:** Ship export/import for leagues (JSON or SQLite bundle) so a
   user can share leagues across machines while staying offline.

### 7.2 Online League Path
1. **File-sync phase:** Define canonical export format (manifest + hashes) so
   commissioners can exchange updates via shared storage and detect conflicts.
2. **Deterministic sims:** Ensure simulation steps remain reproducible by
   locking PRNG seeds and logging state transitions.
3. **Client/server prototype:** Spin up a FastAPI (or similar) service exposing
   REST for admin actions plus WebSocket for live events; add token auth.
4. **Hosted persistence:** Move authoritative league state to the server and run
   sims in background jobs/queues; clients issue signed commands only.
5. **Migration tooling:** Provide upgrade scripts that ingest existing offline
   saves and register owners/teams on the server without data loss.

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

## 8. League Settings/Manager Reorganization
- **Goal:** Reorganize the Admin `League Settings` and `League Manager` UX so
  high-frequency tasks (create, clone, switch, archive, delete) are faster and
  less error-prone.
- **Ideas:** Consolidate league lifecycle actions into one guided operations
  surface, add clearer destructive-action guardrails, and improve active-league
  context visibility (header state, confirmations, post-switch refresh prompts).
- **Status:** Complete.

## 9. Owner Change Request Packaging
- **Goal:** Export owner change requests as a single `.zip` bundle instead of
  loose files so submissions are cleaner and easier for commissioners to review.
- **Scope:** Bundle all request artifacts (manifest + roster/lineup/pitching/
  depth-chart files) into one archive at export time.
- **File naming:** Include league identifier, team identifier, and date in the
  filename so commissioners can identify the source without opening it.
  Suggested format:
  `change_request_<league_slug>_<team_slug>_<YYYYMMDD-HHMM>.zip`
- **Status:** Complete.

## 10. Trade Window UX Redesign
- **Goal:** Redesign the Trade window to improve readability and decision flow
  for both owners and commissioners.
- **Scope:** Clean up layout hierarchy, spacing, and labeling so offered assets,
  requested assets, and validation/status messages are easier to scan.
- **Sizing:** Rework default/minimum window dimensions and responsive behavior
  so controls are not crowded on smaller displays and there is less wasted space
  on larger displays.
- **Status:** Complete.

## 11. Owner Finance Page Layout/Sizing Fix
- **Goal:** Ensure all Owner Finance page content is accessible without clipping.
- **Scope:** Resize the page/layout containers and add scrollable regions where
  needed so bottom sections are always reachable on common screen sizes.
- **UX requirement:** No critical controls or summary rows should be hidden
  below the fold without an obvious scrollbar.
- **Status:** Complete.

## 12. Team Settings Visual Preview Upgrade
- **Goal:** Improve Team Settings with clearer visual feedback for venue and
  branding selections.
- **Scope:** Show a live preview graphic of the currently selected stadium/park
  in the Team Settings dialog.
- **Scope:** Add a uniform preview graphic that reflects selected team primary
  and secondary colors so owners can confirm color combinations before saving.
- **Status:** Complete.

## 13. League Finance Settings Window Redesign
- **Goal:** Redesign the League Finance Settings window for clarity and easier
  configuration across simple and advanced finance modes.
- **Scope:** Resize and restructure the layout so all controls are visible on
  common screen sizes without clipping.
- **Scope:** Improve grouping/labels for finance modules and level toggles so
  commissioners can understand and change settings faster.
- **Status:** Complete.

## 14. Commissioner-Only Season Progression (Multi-Owner Leagues)
- **Goal:** In multi-owner leagues, restrict all simulation/season progression
  actions to commissioner accounts only.
- **Scope:** Disable or hide simulate/progress controls for owner accounts in
  owner dashboards and related menus when league mode is multi-owner.
- **Scope:** Enforce server-side/action-level guardrails so progression cannot
  be triggered through alternate UI paths or direct action calls.
- **Status:** Complete.

## 15. Performance Pass: Auto-Assign + League Creation
- **Goal:** Reduce long waits in two high-friction workflows: auto-assigning
  players for all teams and creating a new league.
- **Scope:** Profile both flows to identify hotspots (I/O, repeated CSV loads,
  synchronous UI work, expensive recalculations), then optimize with caching
  and batched/background processing where appropriate.
- **UX:** Add clearer progress feedback and elapsed-step messaging so users can
  tell the app is still working during longer operations.
- **Execution Plan:** `docs/performance_pass_plan.md`
- **Status:** Complete (closed in v5.0.94). See sign-off metrics in
  `docs/performance_pass_plan.md`.

## 16. Post-Export "Open Folder" Shortcut
- **Goal:** After any export action completes, let users open the containing
  folder directly from the success dialog.
- **Scope:** Add an `Open Folder` button/action to export completion dialogs
  (owner change requests, league snapshot export, and similar export flows).
- **UX:** Keep current success messaging but include one-click access to the
  export location to reduce manual file navigation.
- **Status:** Complete.

## 17. Admin In-App Tutorials
- **Goal:** Add tutorial coverage for commissioner workflows directly inside the
  Admin console/dashboard.
- **Scope:** Provide an Admin `Tutorials` menu (or equivalent entry point) with
  guided walkthroughs for core admin tasks (league setup, user management,
  season progression, trade/review queues, exports/utilities).
- **UX:** Match owner tutorial behavior so admins can launch tutorials on
  demand and new commissioners get a clear onboarding path.
- **Status:** Complete.

## 18. UI Graphics Handoff Export Utility
- **Goal:** Make UI redesign handoff one-click by exporting a package per screen
  for screenshot-plus-code workflows with ChatGPT.
- **Scope:** Add a dev tool/script that collects each top-level `QDialog`/
  `QMainWindow`/`QWidget` class, grabs source context, and writes structured
  handoff bundles to `reports/ui_handoff/`.
- **Output idea:** For each screen, generate:
  - class metadata (file, class name, line ranges),
  - optional screenshot placeholder path,
  - prompt-ready markdown block with constraints and style tokens.
- **Status:** Open.

## 19. In-App Manual Maintenance Cadence
- **Goal:** Keep the in-app searchable manuals current as new features and menu
  paths evolve.
- **Scope:** Add a lightweight release checklist item to verify tutorial text
  and both manuals (Complete Game Manual + Finance System Manual) against the
  current UI labels and workflow order before each release.
- **Status:** Complete (baseline implementation delivered in v5.0.97).

## 20. Player Morale System
- **Goal:** Introduce a dedicated morale model that influences development,
  performance variance, and roster-management decisions.
- **Scope:** Add player morale state and lifecycle events (playing time,
  role/promotions, injuries, streaks, team context), connect morale modifiers
  to training/development outcomes and gameplay tuning where appropriate, and
  surface morale in owner/admin UI plus tutorials.
- **Status:** Open.

## 21. Theme Asset Coverage Expansion
- **Goal:** Extend the new `Enhanced Warm` icon/divider integration beyond the
  Owner/Admin dashboard home surfaces.
- **Scope:** Apply themed action/icon treatments to additional high-traffic
  windows and dialogs (lineup, pitching, trades, standings, schedule) while
  preserving stable layout behavior and accessibility.
- **Scope:** Add a lightweight visual regression checklist for theme-family
  parity (Classic vs Enhanced Warm) across major navigation and action points.
- **Progress:** v5.1.1 added live theme refresh broadcasting across open
  windows and mode-aware styling hooks for Position Players/Pitchers dialogs.
- **Status:** In Progress.

## 22. Optional Team Auto-Assign for Player Reassignment
- **Goal:** Let teams opt into automatic player reassignment so owners who
  prefer automation do not need to manually move players after roster changes.
- **Scope:** Add a per-team setting (or league default + per-team override) to
  enable automatic reassignment behavior for common triggers (injury moves,
  activations, promotions/demotions, and transaction-driven roster updates).
- **Scope:** Keep manual reassignment fully available for teams that leave the
  option disabled, with clear UI messaging about when auto-assign is active.
- **Progress:** v5.2.2 delivered league default + per-team override settings,
  owner/admin configuration UI, trigger hooks for injury/trade/transaction
  roster updates, and Reassign dialog auto-mode status messaging.
- **Status:** Complete.

## 23. CPU Team Trade AI (Respond + Propose)
- **Goal:** Add trade-decision AI for CPU-owned teams so they can evaluate and
  respond to incoming human trade offers, and optionally initiate trade offers
  to human-owned teams.
- **Scope:** Implement CPU-side trade valuation using roster needs, player
  value/contract context, competitive window, and league settings so responses
  are believable and consistent.
- **Scope:** Add proactive CPU trade proposals with configurable frequency,
  guardrails against spam/low-quality offers, and clear inbox/notification UX
  for human teams.
- **Progress:** v5.2.9 delivered `V5.3-01` CPU trade evaluator foundations
  (value + roster fit + timeline) and wired owner-to-CPU offer auto-response
  handling for accept/reject outcomes in Trade Center; v5.2.10 completed CPU
  counter-offer responses for close offers so owners now receive immediate
  accept/reject/counter behavior when proposing to CPU teams; v5.2.11 added a
  league trade-setting toggle to enable/disable CPU-initiated offers; v5.2.12
  completed `V5.3-03` with proactive CPU proposal generation and cadence
  controls integrated into season simulation; v5.2.13 completed `V5.3-04` with
  stronger proposal quality guardrails and anti-spam filters (target cooldown,
  pending-offer caps, repeat-package suppression, and cycle diagnostics).
- **Status:** In Progress.

## 24. Team Strategy Profiles for Automation
- **Goal:** Add team strategy profiles so auto-assign and auto-lineup creation
  decisions reflect each team's intended play style and roster philosophy.
- **Scope:** Define league/team strategy presets (for example: Balanced, Win
  Now, Development Focus, Defense First, Power Offense) and feed them into
  auto-assignment, lineup generation, and depth-chart prioritization logic.
- **Scope:** Support league defaults with per-team overrides, plus clear UI
  indicators showing which strategy is active when automation runs.
- **Progress:** v5.1.18 delivered domain/settings UI (`V5.2-17`); v5.1.19
  delivered auto-assign and valuation hooks (`V5.2-18`).
- **Status:** In Progress.

## 25. Finance Setup During League Creation
- **Goal:** Require or strongly guide finance configuration during new league
  creation so leagues start with intentional economic rules instead of defaults.
- **Scope:** Add a finance settings step to the league creation wizard that
  lets commissioners choose presets or customize key options before league
  creation completes.
- **Scope:** Persist the selected finance configuration as part of the initial
  league bootstrap and surface a confirmation summary before finalizing setup.
- **Status:** Complete.

## 26. Milestone Roadmap (v5.2-v5.4)
- **Goal:** Turn the current strategic priorities into a concrete release plan
  with explicit sequencing, effort, risks, and dependency gates.
- **Progress:** v5.2 execution complete (`V5.2-01`..`V5.2-21` complete).
- **Status:** In Progress.

### v5.2 - Foundation Polish + Depth Systems
- **Target effort:** 4-6 weeks.
- **Primary scope:**
  - Ship-ready UI polish pass on core windows: Lineups, Pitching Staff, Trades,
    Standings, and Schedule (layout, spacing, readability, consistent actions).
  - League Command Center v1 (injuries, pending approvals, roster conflicts,
    draft/free-agency deadlines, finance risk alerts).
  - AI transparency v1 (reason tags on lineup/bullpen/trade decisions).
  - Scouting v1 (fog-of-war ratings, confidence bands, scouting budget controls).
  - Team strategy identities v1 (rebuild/contend/prospect-hoard/balanced)
    influencing roster automation and valuation.
  - Analytics/Career Arc v1 (year-over-year comps, trend lines, team-era views).
  - Documentation/backlog hygiene pass to reconcile `Open` vs `Complete` status.
- **Risk level:** Medium.
- **Key risks:**
  - UI polish scope creep across many windows.
  - Scouting and strategy logic can destabilize current balance if over-tuned.
- **Dependencies / gates:**
  - Shared player evaluation output (true rating + scouted estimate + confidence)
    available to UI and AI services.
  - Command Center data cards depend on stable alert sources from injuries,
    finance, transactions, and schedule/phase state.
  - Decision-reason schema defined once and reused across lineup/bullpen/trade.
- **Exit criteria:**
  - Core-window UX checklist passes for all five targeted windows.
  - Command Center is owner/admin accessible with live summary cards.
  - At least three AI decision surfaces show clear "why" output.

#### v5.2 Subtasks (Tracking Checklist)
- [x] **V5.2-01 UI polish rubric + baseline screenshots** (Effort: S, Risk: Low, Depends: None)
- [x] **V5.2-02 Lineup window polish pass** (Effort: M, Risk: Medium, Depends: V5.2-01)
- [x] **V5.2-03 Pitching staff window polish pass** (Effort: M, Risk: Medium, Depends: V5.2-01)
- [x] **V5.2-04 Trade window polish pass** (Effort: M, Risk: Medium, Depends: V5.2-01)
- [x] **V5.2-05 Standings window polish pass** (Effort: S, Risk: Low, Depends: V5.2-01)
- [x] **V5.2-06 Schedule window polish pass** (Effort: S, Risk: Low, Depends: V5.2-01)
- [x] **V5.2-07 League Command Center data contract/service layer** (Effort: M, Risk: Medium, Depends: D4)
- [x] **V5.2-08 League Command Center UI shell + navigation** (Effort: M, Risk: Medium, Depends: V5.2-07)
- [x] **V5.2-09 Command Center cards: injuries + approvals + roster conflicts** (Effort: M, Risk: Medium, Depends: V5.2-08)
- [x] **V5.2-10 Command Center cards: deadlines + finance risk alerts** (Effort: M, Risk: Medium, Depends: V5.2-08)
- [x] **V5.2-11 AI decision explanation schema (reason tags + payload)** (Effort: M, Risk: Medium, Depends: D1)
- [x] **V5.2-12 Surface lineup decision reasons in UI** (Effort: S, Risk: Low, Depends: V5.2-11)
- [x] **V5.2-13 Surface bullpen usage reasons in UI** (Effort: S, Risk: Low, Depends: V5.2-11)
- [x] **V5.2-14 Surface trade rejection reasons in UI** (Effort: M, Risk: Medium, Depends: V5.2-11)
- [x] **V5.2-15 Scouting fog-of-war model (true vs observed ratings + confidence)** (Effort: L, Risk: High, Depends: D2)
- [x] **V5.2-16 Scouting budget settings + persistence + UI controls** (Effort: M, Risk: Medium, Depends: V5.2-15)
- [x] **V5.2-17 Team strategy profiles v1 domain + settings UI** (Effort: M, Risk: Medium, Depends: None)
- [x] **V5.2-18 Strategy profile hooks in auto-assign + valuation paths** (Effort: M, Risk: Medium, Depends: V5.2-17)
- [x] **V5.2-19 Analytics/Career Arc v1 (YoY, trends, team-era view)** (Effort: M, Risk: Medium, Depends: None)
- [x] **V5.2-20 Backlog/doc status reconciliation pass** (Effort: S, Risk: Low, Depends: None)
- [x] **V5.2-21 Release gates: targeted tests + multi-league smoke + UI checklist sign-off** (Effort: M, Risk: Medium, Depends: V5.2-02..V5.2-20)
- **V5.2-21 progress (2026-03-02):** release gates complete (`73` targeted tests, multi-league smoke pass, help-surface validation pass, and archived UI/installer checklist sign-off); see `reports/release_validation/v5_2_21_gate_summary.md`.

### v5.3 - Roster Intelligence + Competitive AI
- **Target effort:** 5-7 weeks.
- **Primary scope:**
  - CPU Trade AI v1.5 (respond + proactive proposals with quality guardrails).
  - Prospect management layer (protection/options/promotion rules and late-bloom
    variance tied to development/scouting uncertainty).
  - Strategy profiles v2 integrated into trades, draft, promotions, and free
    agency posture.
  - Analytics/Career Arc v2 (player similarity, aging buckets, comparative
    history filters, export-ready views).
  - Sim transparency v2 (explain rejected trades and promotion/option decisions).
- **Risk level:** Medium-High.
- **Key risks:**
  - AI proposal quality can produce spammy or repetitive trade offers.
  - Prospect rules may conflict with existing roster cap and injury workflows.
- **Dependencies / gates:**
  - Requires v5.2 scouting and strategy profile foundations.
  - Requires explicit transaction/audit events for promotions/options.
  - Requires acceptance-quality tests for CPU trade proposals.
- **Exit criteria:**
  - CPU teams both evaluate and initiate trade offers with configurable cadence.
  - Prospect lifecycle rules are enforced consistently across sim phases.
  - Trade/prospect decisions include user-facing rationale in UI.

#### v5.3 Subtasks (Tracking Checklist)
- [x] **V5.3-01 CPU trade evaluator refactor (value + roster fit + timeline)** (Effort: M, Risk: Medium, Depends: V5.2-17, V5.2-18)
- [x] **V5.3-02 CPU incoming-offer response logic (accept/reject/counter)** (Effort: M, Risk: Medium, Depends: V5.3-01)
- [x] **V5.3-03 CPU proactive trade proposal generator + cadence controls** (Effort: M, Risk: Medium, Depends: V5.3-01)
- [x] **V5.3-04 Proposal quality guardrails + anti-spam filters** (Effort: S, Risk: Medium, Depends: V5.3-03)
- [x] **V5.3-05 Promotion/options/protection event model + persistence** (Effort: M, Risk: High, Depends: D1)
- [x] **V5.3-06 Prospect protection/eligibility rules enforcement** (Effort: M, Risk: High, Depends: V5.3-05)
- [x] **V5.3-07 Late-bloomer variance model tied to scouting uncertainty** (Effort: M, Risk: Medium, Depends: V5.2-15)
- [x] **V5.3-08 Strategy profiles v2 hooks for draft + FA + promotions** (Effort: M, Risk: Medium, Depends: V5.2-17, V5.3-05)
- [x] **V5.3-09 Analytics/Career Arc v2 (similarity, aging buckets, filters, export)** (Effort: M, Risk: Medium, Depends: V5.2-19)
- [x] **V5.3-10 Transparency v2 for trade/prospect decisions** (Effort: S, Risk: Low, Depends: V5.3-01, V5.3-05)
- [x] **V5.3-11 Acceptance tests for CPU trade quality + prospect workflow regression** (Effort: M, Risk: Medium, Depends: V5.3-02..V5.3-10)
- **V5.3-02 progress (2026-03-03):** owner-to-CPU Trade Center offers now get
  immediate CPU accept/reject/counter responses.
- **V5.3-03 progress (2026-03-03):** added CPU proactive trade proposal cycle,
  league cadence controls (`off/low/normal/high`), persisted per-team cooldown
  state, and sim-day/week/month integration so Trade Center receives generated
  CPU offers during season progression.
- **V5.3-04 progress (2026-03-03):** added stricter proactive trade quality and
  anti-spam controls: per-target cooldown windows, pending-offer caps, repeated
  package suppression via proposal history signatures, and cycle filter metrics.
- **V5.3-05 progress (2026-03-03):** added shared promotion/options/protection
  lifecycle event persistence in `services/prospect_event_log.py`, wired
  promotion/demotion event recording into injury and manual reassign flows,
  wired option decision events into contracts workflows (manual + rollover),
  and added targeted regression coverage.
- **V5.3-06 progress (2026-03-03):** added `services/prospect_rules.py` with
  league-scoped protection + option-limit rule enforcement, wired move checks
  into manual reassign and injury replacement promotion paths, and added
  targeted rule/integration regression coverage.
- **V5.3-07 progress (2026-03-03):** added deterministic late-bloomer
  development variance in `services/late_bloomer_variance.py` using
  scouting-uncertainty signals, integrated adjusted development multipliers
  into offseason aging flow in `ui/season_progress_window.py`, and added
  targeted regression coverage.
- **V5.3-08 progress (2026-03-03):** expanded strategy profile v2 hooks across
  draft scoring (`services/draft_ai.py` + `ui/draft_console.py`), CPU
  free-agency bid shaping (`services/finance_ai.py`), and promotion protection
  decisions (`services/prospect_rules.py`) with targeted regression coverage.
- **V5.3-09 progress (2026-03-03):** expanded `services/career_arc_analytics.py`
  with player-similarity rows, aging-bucket summaries, and comparative filters;
  extended report exports with HTML report-bundle generation (landing page +
  section pages) and optional CSV mode in `services/report_exporter.py`; wired
  Admin Utilities report actions so HTML opens by default with explicit CSV
  export option in UI/actions; added targeted regression coverage.
- **V5.3-10 progress (2026-03-03):** completed transparency v2 by extending
  prospect move decisions with structured reason tags/context payloads in
  `services/prospect_rules.py`, surfacing rationale summaries in manual
  reassignment and injury-center promotion flows, and adding targeted
  regression coverage (`tests/test_prospect_rules.py`,
  `tests/test_injury_manager.py`, `tests/test_reassign_players_dialog.py`).
- **V5.3-11 progress (2026-03-03):** added acceptance/regression coverage in
  `tests/test_v53_acceptance.py` for CPU trade quality matrix scenarios,
  proactive CPU proposal quality-gate behavior, prospect protection/option-limit
  workflow progression, and injury-replacement interactions with prospect rules.
  Verified with targeted suite run across acceptance + CPU/prospect tests.

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

### Implementation Start Queue
- **Now:** `#32 Simulation Speed Review and Optimization Pass`
- **Next:** `V5.4-01 Deterministic event log foundation`
- **Then:** `V5.4-05 Commissioner-grade audit timeline UI`

### Cross-Milestone Dependency Map
- **D1: Decision Explanation Schema** -> required by v5.2 AI transparency, v5.3
  trade/prospect rationale, and v5.4 audit/story output.
- **D2: Scouted vs True Rating Model** -> required by v5.2 scouting, v5.3
  prospect/trade valuation, and v5.4 story context quality.
- **D3: Deterministic Event Log** -> required by v5.4 What-If Lab and online/audit
  foundation.
- **D4: Command Center Aggregation Layer** -> provides operational visibility for
  all subsequent roadmap systems.

## 27. Almanac Export (Baseball-Reference Style)
- **Goal:** Provide a full-history league almanac export as a multi-page HTML
  site so owners/commissioners can browse historical and current league data in
  one organized reference package.
- **Scope:** Add an export workflow that generates an Almanac folder with a
  landing page (`index.html`) that links to all major sections (league summary,
  standings by season, teams, players, awards, postseason, records, leaders,
  transactions/finance summaries where applicable).
- **Scope:** Organize outputs year-by-year so each season has a dedicated page
  (or page set) showing that year's key data with links to prior/next seasons
  and cumulative context.
- **Scope:** Use a consistent baseball-reference-inspired presentation style:
  clean tables, section navigation, sortable/indexed views where feasible, and
  cross-links between related entities (team pages, player pages, season pages).
- **Dependencies / inputs:**
  - Season archives and metadata from `SeasonContext` / career snapshots.
  - Current-league CSV/JSON sources (teams, players, standings, playoffs,
    leaders, transactions, finance summaries).
  - Stable export location and file naming convention under the active league.
- **Exit criteria:**
  - One-click export produces a browsable multi-page HTML almanac.
  - Landing page links every major section and each season page.
  - Year-by-year navigation works with prior/next season links.
  - Cross-links between seasons, teams, and players resolve without broken links.
- **Progress:** v5.2.21 delivered an initial Almanac export foundation:
  data contract/source map doc (`docs/almanac_data_contract.md`), exporter
  scaffold (`services/almanac_exporter.py`), landing page + section shell
  (Seasons, Teams, Players, Records), per-season pages with year-by-year
  navigation, and Admin Utilities action wiring (`Export Almanac (HTML)`);
  v5.2.22 completed `ALM-05` with franchise pages under `teams/<team_id>.html`,
  year-by-year team history tables, cumulative team summaries, and cross-links
  between season standings and franchise pages; v5.2.23 completed `ALM-06`
  with player career pages under `players/<player_id>.html`, current-team
  links, season-log navigation back to season/team pages, and player record-book
  summaries; v5.2.24 completed `ALM-07` with dedicated Awards, Postseason, and
  Leaders sections plus richer Records linking and season pages that now
  surface awards/postseason data inline; v5.2.25 completed `ALM-08` with
  transaction history and finance summary sections, including archived/current
  data ingestion, season/team/player cross-links, and current finance ledger
  output when present; v5.2.26 completed `ALM-09` with a baseball-reference-
  inspired style pass: richer navigation cards, stat cards, wrapped/sticky
  tables, numeric alignment, and print-friendly stylesheet defaults; v5.2.27
  completed `ALM-11` with Almanac export validation helpers plus regression
  coverage for required page presence and local link integrity; v5.2.28
  completed `ALM-12` by updating owner/admin guides, shipped manuals, in-app
  admin export tutorial text, and release/manual checklist steps for Almanac
  export validation.
- **Status:** Complete.

#### Almanac Subtasks (Tracking Checklist)
- [x] **ALM-01 Almanac data contract + source map** (Effort: S, Risk: Low, Depends: None)
- [x] **ALM-02 Export pipeline scaffold (folder structure, writer utilities, templating)** (Effort: M, Risk: Medium, Depends: ALM-01)
- [x] **ALM-03 Landing page (`index.html`) + global navigation shell** (Effort: S, Risk: Low, Depends: ALM-02)
- [x] **ALM-04 Season index and per-year league summary pages** (Effort: M, Risk: Medium, Depends: ALM-02)
- [x] **ALM-05 Team franchise pages (history + year splits + links)** (Effort: M, Risk: Medium, Depends: ALM-04)
- [x] **ALM-06 Player pages (career totals + year logs + team history links)** (Effort: M, Risk: Medium, Depends: ALM-04)
- [x] **ALM-07 Awards/postseason/records/leaders sections** (Effort: M, Risk: Medium, Depends: ALM-04)
- [x] **ALM-08 Transaction and finance history sections (when data exists)** (Effort: S, Risk: Medium, Depends: ALM-04)
- [x] **ALM-09 Style pass (baseball-reference-inspired tables, readability, print-friendly defaults)** (Effort: S, Risk: Low, Depends: ALM-03..ALM-08)
- [x] **ALM-10 Export entry point in UI + progress feedback + open-folder shortcut** (Effort: S, Risk: Low, Depends: ALM-02)
- [x] **ALM-11 Validation/tests (link integrity, required pages, sample league snapshot checks)** (Effort: M, Risk: Medium, Depends: ALM-03..ALM-10)
- [x] **ALM-12 Docs/tutorial updates + release checklist coverage** (Effort: S, Risk: Low, Depends: ALM-11)

#### Suggested Execution Order
1. `ALM-01` -> `ALM-03` for a minimal but browsable skeleton.
2. `ALM-04` -> `ALM-08` to fill out season/team/player and history content.
3. `ALM-09` -> `ALM-12` to polish, integrate, validate, and document.

#### Current Almanac Queue
- **Completed:** `ALM-01` -> `ALM-12`
- **Next Suggested Milestone:** `V5.4-01 Deterministic event log foundation`
- **Then:** `V5.4-02 Season/date snapshot and fork manager`

## 28. Hide Change-Request Submission in Single-Player Leagues
- **Goal:** Remove the Owner "Submit Change Request" workflow in local
  single-player leagues where commissioner approval is not part of gameplay.
- **Scope:** Hide or disable all "Submit Change Request" entry points (Owner
  Tools menu, roster/home shortcuts, and related prompts/tutorial references)
  when league mode is single-player.
- **Scope:** Preserve full change-request functionality in multi-owner leagues,
  including exports, cancellation flow, and commissioner import/review tooling.
- **Scope:** Ensure league-mode transitions (for example when switching active
  leagues) refresh visibility state correctly without requiring app restart.
- **Progress:** v5.2.4 hides owner change-request menu/tutorial/roster entry
  points in single-player leagues, adds runtime guards on change-request launch
  paths, and keeps full export workflow behavior for multi-owner leagues.
- **Status:** Complete.

## 29. Installer-Time Admin Password Setup
- **Goal:** Prompt for and set the initial administrator password during app
  installation so deployments do not rely on default credentials.
- **Scope:** Add an installer step to capture an admin password (with confirm
  entry and basic validation) and persist it to the initial auth/user store in
  a secure hashed form.
- **Scope:** Define fallback behavior for unattended/silent installs (for
  example: require post-install first-run password setup before admin access).
- **Scope:** Update installer documentation, first-run guidance, and recovery
  instructions to reflect the new password initialization flow.
- **Progress:** v5.2.29 added an installer admin-password page with confirm
  validation for interactive installs, persistent bootstrap config for new
  league/user-store seeding, automatic replacement of placeholder admin
  credentials from installer bootstrap data, and silent-install first-run admin
  password setup enforcement in the login flow.
- **Status:** Complete.

## 30. Action Button Layout Cleanup (Width + Multi-Column)
- **Goal:** Improve UI readability by preventing action buttons from stretching
  across full page width in dashboards and dialogs.
- **Scope:** Replace single full-width button stacks with responsive multi-column
  button layouts (for example 2-3 columns depending on window width) so action
  panels look cleaner and use space more efficiently.
- **Scope:** Standardize button width constraints and spacing tokens so action
  groups are visually consistent across owner/admin screens.
- **Scope:** Verify desktop and smaller-window behavior to ensure no clipping or
  overlap when columns reflow.
- **Progress:** v5.2.5 added shared `ActionButtonPanel` responsive layout
  helpers and migrated owner core action stacks (Roster, Team, Transactions,
  League Hub, and Season Progress) to constrained multi-column button panels;
  v5.2.6 extended the same pattern to admin core pages (Home, League Settings,
  Season, Transactions, Utilities, Draft, and Teams); v5.2.7 applied the same
  constrained action-layout treatment to high-traffic editor/dialog workflows
  (Lineup Editor, Pitching Staff Editor, Trade Center actions, and Injury
  Center action controls); v5.2.8 completed the cleanup pass across remaining
  settings and setup dialogs (financial settings, league-creation finance,
  team strategy settings, hall of fame settings, injury settings, trade
  settings, playbalance editor, change requests, and league setup choice).
- **Status:** Complete.

## 31. Remove Timeline Feed from Season Progress Window
- **Goal:** Simplify the Season Progress UI by removing the timeline feed panel
  and reducing visual clutter during simulation operations.
- **Scope:** Remove timeline feed rendering and related controls/messages from
  the Season Progress window while preserving core simulation controls, status,
  and progress feedback.
- **Scope:** Clean up any dependent layout spacing or placeholder containers so
  the window remains balanced after the feed is removed.
- **Scope:** Update tutorials/manual references that mention the Season Progress
  timeline feed.
- **Progress:** v5.2.30 removed the separate Timeline Feed list from
  `ui/season_progress_window.py`, kept the Season Timeline milestone view,
  added a regression test to prevent the feed widgets from returning, and
  updated `docs/season_progress.md`.
- **Status:** Complete.

## 32. Simulation Speed Review and Optimization Pass
- **Goal:** Evaluate current simulation runtime and improve speed in the most
  common progression paths without sacrificing deterministic behavior or
  simulation accuracy.
- **Scope:** Profile key simulation workflows (single-day sim, weekly/monthly
  jumps, playoffs, and offseason transitions) to identify top CPU/I/O
  bottlenecks.
- **Scope:** Implement targeted optimizations (caching, batch writes, reduced
  repeated loads, and background execution improvements where safe), then
  validate output parity against baseline runs.
- **Scope:** Add/refresh speed benchmark reporting so release validation tracks
  runtime trends over time.
- **Status:** Complete (reconciled 2026-07-13). Game simulation is ~5× faster
  per game as of 7.0 (cached park/player/recovery parses; results unchanged).

## 33. Owner Dashboard Minimize/Focus-Loss Hang
- **Goal:** Fix a stability issue where minimizing the Owner Dashboard and then
  interacting with another application/window can cause the dashboard to
  disappear and the app to hang.
- **Scope:** Reproduce and isolate the minimize/focus transition path
  (window-state changes, raise/activate logic, modal/non-modal interactions,
  and event-loop callbacks) that leads to the freeze condition.
- **Scope:** Implement a safe window lifecycle/state-handling fix so minimized
  owner windows can be restored reliably without UI deadlock.
- **Scope:** Add regression coverage for minimize/restore/focus workflows (as
  feasible in headless tests) and a manual validation checklist for desktop
  environments.
- **Progress:** v5.2.3 updated top-most window handling so main dashboards are
  no longer forced into `WindowStaysOnTopHint`, preventing the minimize/focus
  restore hang path for Owner Dashboard windows.
- **Status:** Complete.

## 34. Overwrite Existing League Should Refresh Admin Password
- **Goal:** Ensure overwriting an existing league with the same name during
  league creation resets that league's admin credential to the current
  installer/bootstrap password instead of retaining the previous one.
- **Scope:** Reproduce the overwrite path for same-name league creation after a
  clean app install and identify why the prior league `users.txt` admin entry
  survives instead of being reseeded.
- **Scope:** Update the overwrite/create-league flow so replacing an existing
  league also replaces or reseeds the admin account consistently with the
  current installer bootstrap choice.
- **Scope:** Add regression coverage for same-name overwrite flows and document
  expected password behavior in installer/setup guidance if needed.
- **Status:** Fixed (reconciled 2026-07-13). Same-name overwrite purges the old
  league dir (dropping stale `users.txt`) and reseeds the admin credential from
  the installer/bootstrap password — see `playbalance/league_creator.py`
  (`_purge_old_league` + `clear_users`).

## 35. Single-User League Owner Setup Prompt
- **Goal:** Improve first-run usability for single-user leagues by prompting
  the player to create an owner username and choose a team immediately after
  league creation.
- **Scope:** Add a post-creation setup step for single-user league mode that
  captures the owner username and managed team before the user lands in the
  normal login/dashboard flow.
- **Scope:** Seed the selected owner account/team assignment automatically and
  avoid leaving newly created single-user leagues in an unclaimed/default
  state.
- **Scope:** Update related league-creation docs/tutorials and add regression
  coverage for the new single-user onboarding path.
- **Status:** Open.

## 36. Player Profile Presentation Redesign
- **Goal:** Improve the Player Profile page so key information is aligned more
  clearly and the overall presentation feels more polished and readable.
- **Scope:** Review the current Player Profile layout for alignment issues,
  spacing inconsistencies, weak grouping, and visual hierarchy problems across
  ratings, bio, stats, and action areas.
- **Scope:** Redesign the page structure and presentation so core player info,
  ratings, history, and related actions are easier to scan on desktop-sized
  windows without feeling cramped or uneven.
- **Scope:** Preserve existing functionality while improving layout quality,
  then add/update visual regression or targeted UI tests where feasible.
- **Status:** Open.

## 37. Audit Player Star Rating Calculation
- **Goal:** Revisit player star-rating calculation and presentation to verify
  that displayed star values match the intended evaluation model and user
  expectations.
- **Scope:** Review the current star-rating formula, weighting inputs, role and
  position adjustments, normalization ranges, and any separation between true,
  displayed, or scouted values.
- **Scope:** Reproduce cases where players with obviously elite component
  ratings (for example 90+ contact and power) still display unexpectedly low
  star ratings, and determine whether the issue is calculation logic,
  defensive/positional balancing, or UI explanation clarity.
- **Scope:** Fix incorrect rating behavior if found, or improve star-rating
  transparency/tooltips/tests so the outcome is understandable and consistent.
- **Status:** Superseded in 7.45.10 (audit H8/M14). The top-N blend is gone;
  one production-weighted overall, `utils/player_overall.py`, now drives the
  displayed OVR/stars and the plain-mean `overall_rating` alike (a 90/90 bat
  shows ~92 and 4.5 stars). Its defense weights are provisional until
  Release 6 (decision 12).

## 38. Contract Details on Player Profile + Team Contracts Page
- **Goal:** Make contract status easier to manage by showing full contract
  details on each player profile and adding a dedicated contracts page for team
  owners.
- **Scope:** Extend the Player Profile view to display the player's current
  contract details clearly, including core terms/status owners need when making
  roster and finance decisions.
- **Scope:** Add a dedicated contracts page or window where owners can review
  the contract status of all players on their team in one place.
- **Scope:** Ensure the contracts view supports practical owner workflows such
  as spotting expiring deals, option decisions, arbitration/extension risk, and
  other contract-related status at a glance.
- **Scope:** Preserve existing contract functionality while improving
  discoverability/presentation, then add targeted UI and data regression
  coverage where feasible.
- **Status:** Complete (reconciled 2026-07-13). Per-player contract details show
  on the profile (`desktop/src/pages/PlayerProfilePage.tsx` → `ContractCard`) and
  a dedicated league-wide contracts page exists (`ContractsPage.tsx` backed by
  `api/routers/contracts.py`).

## 39. In-Season Contract Renegotiation for Final-Year Players
- **Goal:** Let owners renegotiate contracts during the season for players who
  are in the final year of their current deal.
- **Scope:** Define eligibility rules for in-season renegotiation, including
  limiting the feature to players with exactly one year remaining and honoring
  any existing finance/contract-system constraints.
- **Scope:** Add owner-facing workflow/UI to initiate and review renegotiation
  offers from roster/player-profile/contracts surfaces.
- **Scope:** Persist renegotiated terms safely, update contract/finance status
  views accordingly, and prevent invalid duplicate or conflicting negotiations.
- **Scope:** Add targeted coverage for eligibility, negotiation flow, and
  contract-state updates.
- **Status:** Complete (reconciled 2026-07-13). Mid-season extension/renegotiation
  is wired end to end — `services/contract_negotiator.py`
  (`check_extension_eligibility`, `evaluate_extension_offer`, final-year gate via
  `MAX_YEARS_LEFT_FOR_EXTENSION`), `POST /{player_id}/evaluate-extension` in
  `api/routers/contracts.py`, and the ContractCard "Negotiate extension" UI.

## 40. Backfill Player Contracts When Finance Is Enabled Mid-League
- **Goal:** Ensure that turning on the financial system for an already-created
  league also creates and applies valid player contracts instead of leaving the
  league in a finance-enabled but contract-empty state.
- **Note:** Inaugural-season finance enablement now seeds default contracts for
  rostered players automatically; remaining work here is the historical or
  mid-league migration path where prior service time and term history must be
  inferred.
- **Scope:** Define the migration/backfill behavior when finance is enabled for
  an existing league, including how initial contracts are generated for current
  players and how terms are seeded.
- **Scope:** Apply generated contracts to all relevant players and ensure
  downstream finance/roster systems see a consistent contract state
  immediately after the setting change.
- **Scope:** Add safeguards, messaging, and regression coverage for the
  finance-enable transition so commissioners understand what was generated and
  leagues do not end up partially migrated.
- **Status:** Complete (mid-league backfill flow delivered in v5.2.37).

## 41. Season Progress Window Layout Simplification
- **Goal:** Improve the Season Progress window layout so controls feel more
  balanced, simpler, and easier to use during simulation.
- **Scope:** Rework button alignment and spacing so the primary controls are
  centered and visually organized instead of feeling uneven or overly stretched.
- **Scope:** Simplify the dialog layout by reviewing labels, grouping,
  whitespace, and control hierarchy to reduce clutter while preserving
  important season-status information.
- **Scope:** Keep all existing simulation functionality intact, then add/update
- targeted UI regression coverage where feasible.
- **Status:** Open.

## 42. Owner Dashboard Readability and Layout Cleanup
- **Goal:** Make the Owner Dashboard cleaner, easier to read, and less visually
  noisy during normal team-management workflows.
- **Scope:** Review the current owner dashboard layout for overcrowded sections,
  weak visual hierarchy, inconsistent spacing, and readability issues across
  the main dashboard surfaces.
- **Scope:** Simplify and reorganize key owner-facing panels, labels, summary
  areas, and action groupings so the most important information is easier to
  scan quickly.
- **Scope:** Preserve owner workflow functionality while improving presentation,
  then add/update targeted UI regression coverage where feasible.
- **Status:** Open.

## 43. Research Draft Day Crash
- **Goal:** Reproduce and isolate the draft day crash so the root cause can be
  identified and fixed safely.
- **Scope:** Investigate the draft-day flow across season progression, Draft
  Console launch, roster/state persistence, and related UI/service handoffs to
  determine where the crash occurs.
- **Scope:** Capture any relevant error conditions, state prerequisites, and
  reproduction steps so the failure can be consistently triggered in testing.
- **Scope:** Add targeted regression coverage or diagnostic logging as needed to
  support a later fix once the crash path is understood.
- **Status:** Fixed (reconciled 2026-07-13). The draft-day dead-lock/crash path
  was resolved when the draft moved to guarded FastAPI endpoints: on the final
  pick `_resume_regular_season_after_draft()` flips the phase back to
  REGULAR_SEASON and roster commit is wrapped defensively — see
  `api/routers/draft.py` (and the 7.0 "season flow hardening" notes). Re-confirm
  against the live React draft flow if any crash recurs.

## 44. Player Profile V2 Preview Parity and Rollout
- **Goal:** Finish the Player Profile V2 preview so it reaches functional parity
  with the current player profile before any default-dialog swap occurs.
- **Scope:** Compare the preview dialog against the current player profile
  across hitters, pitchers, injury/training states, scouting-adjusted ratings,
  and season/career stat history to identify missing or misleading behavior.
- **Scope:** Bring over high-value legacy features that are deferred in the
  first preview build, prioritizing areas owners rely on most when evaluating
  players from roster, browser, and league views.
- **Scope:** Keep the legacy player profile stable until parity, tests, and
  manual validation are strong enough to justify routing normal entry points to
  V2.
- **Status:** Complete (Player Profile V2 reached rollout/default-launch parity in v5.2.38, with legacy still available as an explicit fallback).

## 45. Finance Module Level Help Text and Tooltips
- **Goal:** Make finance setup easier to understand by explaining what each
  module level means directly in the UI.
- **Scope:** Add tooltips, inline help text, or a small explainer affordance
  for finance module controls in league creation and related finance settings
  dialogs so users can quickly understand the difference between Off, Basic,
  Advanced, MLB-Like, Warn, Block, and similar level choices.
- **Scope:** Cover the key finance modules shown during setup, including Owner
  Budgets, GM Contracts, Payroll Rules, Arbitration, Free Agency, and Roster
  Cost Enforcement.
- **Scope:** Keep the explanations concise and practical, focusing on gameplay
  impact, unlocked workflows, and what changes at each level rather than
  internal implementation details.
- **Status:** Complete (baseline tooltip coverage delivered in v5.2.36).


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

> **Shipped in 7.45.0 (2026-10-03)** except Phase 3 (widen the generated power spread for new leagues) and the
> stolen-base recalibration, both still open. HR vs Power is now ~0.6 on the fixture (was 0.08).

The Power rating has almost no effect on home runs (HR rate vs PH r = -0.06 on
alpha-test) while Contact drives them (r = +0.77), so high-contact,
average-power hitters post sluggers' numbers (Leroy Harris, SAN1: contact 73 /
power 52, .394 with 20 HR in 198 AB). S2-08 cut `bat_speed_power_scale` to 0.09
and compressed the power spread to keep league HR totals on target; its own
open follow-up, a nonlinear power-to-exit-velocity curve, was never built.
The plan gates the rating-to-outcome relationship first, then adds the curve,
takes contact out of the exit-velocity ceiling, restores the power spread for
new leagues, and re-gates. Rollout timing is the commissioner's call.

Same investigation: stolen-base volume runs at ~3x MLB (2.31 SB per team-game),
and the harness's `sba_per_pa` benchmark of 0.050 looks about double the real
rate -- verify and recalibrate alongside the power work.

## 47. Trades leave the old team's pitching staff file stale

> **Shipped in 7.45.6 (2026-10-05)** as a read-side fix: the staff endpoint returns only active pitchers and lists the rest as vacancies with a reason; the file is left alone until the owner saves. Investigating it found the bigger bug that games used the whole organisation (fixed in the same release).

Found with the 7.45.4 minor-leaguer trade fix: `commit_trade` moves players
between roster files but never touches `{team}_pitching.csv`, so a traded
pitcher stays in his old team's staff assignments (HOU still listed Erich Zenk
as closer after trading him). Harmless in games -- the lineup loader and the
rotation only honour staff entries for pitchers on the roster -- but the old
team's role slot (closer, SP1...) silently points at a departed player until
the owner or the CPU re-sets the staff. Drop traded players from the old
team's staff file in the trade commit, and consider surfacing "your closer was
traded" to an owner.

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

## 49. Day-to-day injuries never clear

Seen in every H9 stress season (pre- and post-fix): 66-91 players end a season
flagged `injured=True` with no injury list and no return date, and 35-44 of the
50 such flags present at the start are still set 91 days later. They stay on
active rosters and in lineups (the engine plays them), but every tool that
filters on `injured` -- injury coverage, call-up candidates, the depth chart
coverage check -- treats them as unavailable. Day-to-day injuries need an
expiry.

## 50. Tell owners when a roster spot is left open

Decision 14 leaves an owner's active-roster spot open after an injury the depth
chart covers. Owners currently learn about it only from the injury news line.
Consider a notification ("CHI: active roster at 24 -- a spot is open") and a
roster-page badge.

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

Still on their own flat averages (which count arm -- wrong-signed today --
and endurance, and leave out eye): `api/routers/draft._prospect_overall`
(draft-board OVR column and CPU best-available autopick, so a prospect's OVR
changes scale once drafted), `services/cpu_trade_proposals._player_trade_value`,
`services/free_agency._quality_score` (CPU FA signing order),
`services/player_retirement._player_overall`, and
`services/inseason_callups._hitter_score/_pitcher_score`. Route them through
`utils.player_overall.player_overall_score` (each needs its own check of what
it ranks).

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
- steal volume (`sba_per_pa` 0.025, `sb_per_team_game` 0.73) and XBT
  (`extra_base_advance_rate` .40; consider `extra_base_out_rate` ~.025) --
  Release 4;
- `hard_hit_pct`, `barrel_pct`, `sweet_spot_pct` -- Release 6 (M2);
- `qualified_hr40_count` (5 +/- 3) once the 40-HR tail is ~5 on several seeds;
- the league-like fixture (`data/calibration_league`) CI step to `--strict`,
  on seeds 1 and 2, once Releases 3-6 bring it inside tolerance (it runs
  4.1 R/G today: decision 2, league-relative ratings, matters more than
  assumed);
- pitcher IL 11-15 per team-season in `scripts/injury_rate_kpi.py` once the
  per-appearance arm-injury hazard ships (engine gives ~1.2 today).
- report-only KPIs in `scripts/kpi_extras.py` (`report_only` in the JSON):
  `runs_on_inning_ending_plays` == 0 with L15 (Release 3; 79/55 today);
  bullpen usage (`starts_120plus_pct`, `relief_60plus_pct`,
  `closer_ip_per_app`) with H1; SF/PA and GIDP per opportunity with M7/M8
  (Release 4); per-count swing rates, first-pitch PA endings, BB/K true sd
  and the K log5 grid (Release 5); fastball fade (11.8 mph today vs 1-2),
  HR sd ratio, HR log5 grid and team DER sd (Release 6); LHP-RHP RA9 and
  per-hand platoon gaps with H7.
Remove the xfail from `tests/test_sim_batching_invariance.py` when Release 3
persists reliever rest by league + calendar date (M18).
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

- MR4/MR5 staff slots plus the engine relief-role normaliser (MR1-3, RP and
  unlisted pitchers recognised as relievers) -- Release 3, tuned against
  13-man staffs. New leagues' 12th/13th pitchers and MR1-3 rows are not yet
  engine-recognised relievers.
- Waivers / DFA / outright assignments. Out-of-options surplus CPU pitchers
  are force-optioned today (logged); owners get the generic pitcher-limit
  error -- add "{name} is out of options: trade or release a pitcher".
- Check owner teams on commissioner/scheduler sims and in the postseason
  (playoff sims have no roster gate); gate it behind the deadline flow so the
  auto-run can't stall.
- Two-way player designation (MLB exempts them from the pitcher count).
- Wire the dormant lineup/roster notification validators
  (`run_lineup_validators` is never passed) together with the
  `pitching_staff_invalid` kwarg bug (`roster_ids` vs `active_ids`).
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
- `api/routers/lineups.py` Pitching auto-fill still picks pitchers from the
  stale stored role column; use `counts_as_pitcher`.
- CPU organisations in existing leagues already exceed today's limits (alpha
  and stats-test CPU orgs hold 53-55 with Low-A at 14-15 vs a cap of 10,
  from draft picks that are never released). Harmless (the gate checks only
  the requesting team) but worth a CPU-only offseason trim policy.
- Client `npm run typecheck` fails on main (24 strict-mode errors in pages
  this release didn't touch: LeagueCreatePage, StandingsPage, ParksPage...).
- Post a league news item announcing the 26-man roster at deploy.
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
- Lineup validation does not check that lineup players are on the ACTIVE
  roster; several injury news writers log without team_id.
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
- Live-path check (fresh 30-team league, 28 days) before the speed-centred
  steal success: SB/G .83, SB% .83, WP .365, PB .050. Re-measure on alpha
  after deploy.

## 63. Commissioner option: amateur draft in the preseason

**SHIPPED 7.50.0.** Kept for the decisions and the follow-ups at the end.

Requested by the owner, 2026-10-11.

Today the amateur draft is fixed at the third Tuesday in July
(`api/routers/season.py::_compute_draft_date`). The season switches to the
AMATEUR_DRAFT phase on that date and every sim stops until the draft is
finished, so a league with human owners stalls in mid-season.

Add a league setting, changeable by the commissioner at any time from the
league admin functions, that chooses when the draft runs:

- **Mid-season** (today's behaviour, the default so nothing changes on
  deploy).
- **Preseason**: the draft runs in the preseason, so no regular-season sim
  ever waits on it.

Owner decisions (2026-10-11):

1. **The preseason draft runs BEFORE spring training,** so the drafted
   players get a training camp before their debut.
2. **A change applies to the next draft.** If the commissioner changes the
   setting while the regular season is being simulated, that season's draft
   is not affected; the new timing takes effect on the following draft. A
   season never gets two drafts or none.
3. **Draft order is the reverse of the records of the last simulated
   season.**
4. **Drafted players go to LOW on every team.** CPU clubs then make their
   own automated decisions if that puts them over a limit. Owner clubs must
   make themselves compliant before the regular season begins (the existing
   Opening Day readiness check); the CPU does not fix an owner's roster.
   Existing policy still holds: no draft pick is released just for room.
5. **Update the documentation:** the commissioner tutorial, the Draft guide
   and the league admin help text.
6. **A new league's first amateur draft comes after its first simulated
   season.** With the preseason setting there is no draft in the first
   preseason (there are no records to order by); the first one runs in the
   second preseason.
7. **The preseason draft keeps today's draft tools:** the pick clock and
   auto-draft work exactly as they do for the mid-season draft ("Advance to
   next owner", the commissioner's "Pick for TEAM" and "Auto-finish draft",
   and the CPU picking for an owner whose clock runs out).

Planned approach (owner approved, 2026-10-11):

- **Reuse the AMATEUR_DRAFT phase** for the preseason draft, with a
  remembered return phase (PRESEASON instead of REGULAR_SEASON). Everything
  that keys off that phase then works unchanged: sims are blocked, the
  auto-run tick only runs the pick clock, the Draft page unlocks, Discord
  gets the on-the-clock posts, and the season resumes after the last pick.
- **Flow:** OFFSEASON -> PRESEASON opens the draft automatically (setting is
  "preseason" and the league has a completed season) -> draft -> back to
  PRESEASON -> spring training -> Opening Day readiness check.
- **While the draft runs,** auto-run does nothing but the pick clock; with
  the clock at 0 the commissioner drives, as today.
- **Guard 1:** spring training cannot run until the draft is finished (same
  pattern as the "Run Spring Training first" block on Opening Day).
- **Guard 2:** the Opening Day owner deadline cannot fire during the draft,
  so the CPU never sets an owner's roster before the owner has his draftees.
- **Pool and order in two steps.** At season rollover (start of the
  offseason): generate the pool and lock the base order from the
  just-finished season's records, so owners can scout all offseason. When
  the draft opens: apply free-agent compensation and forfeited picks, which
  depend on offseason signings.
- **One draft per league year** is the "never two, never none" test. Drafts
  are already filed by league year: a league switching to preseason holds
  its July draft under this year and its first preseason draft under next
  year; switching back, the July draft is skipped if that year's preseason
  draft already happened.

As built (7.50.0):

- `services/draft_settings.py` `timing` ("midseason" | "preseason");
  `SeasonManager.begin_draft / resume_after_draft` and `draft_return_phase`
  in `season_state.json`; `api/routers/season.py`
  `_maybe_open_preseason_draft` (called when the league enters the preseason,
  when the setting is saved, and by the training-camp guard).
- The July draft-day intercept (`_draft_day_pause_due`) fires whenever the
  year's draft has not been completed. That alone gives "a regular season in
  progress keeps its July draft", "no July draft after a preseason one" and
  "a preseason draft that could not be held still happens in July".
- **Decision 6 in full:** a new preseason-draft league has no draft at all in
  its first season. The year is recorded at Opening Day
  (`draft_skipped_years.json`, `_skip_first_season_draft_if_preseason`) and
  the July intercept honours it only while the setting is still preseason,
  so switching back to mid-season before July restores that July draft. A
  league that switches to preseason during its first season keeps its July
  draft (decision 2). This is the one case where a season has no draft.
- A finished draft is stamped `completed` in its state, so a later change to
  the round count cannot reopen it; a draft opened in the preseason is
  stamped `timing: preseason`, which is what the Season page, the calendar
  and the Command Center read in July.
- Reset-to-opening-day keeps a draft held in the preseason (it came before
  Opening Day) and is refused while one is open.
- The coming year's draft cannot be initialized in the offseason, and the
  draft does not open without a schedule (no league year to file it under).
- The order is computed when the draft opens, from the last archived season
  (the archive is immutable, so this equals locking it at rollover);
  compensation picks are applied then too. The pool is generated at
  rollover (`_seed_next_draft_pool_if_preseason`).
- Training camp runs for every player in players.csv, so the draft class
  gets its camp with no extra work (tested).
- The scheduled run (`_run_schedule`) refuses to act during any amateur
  draft. A one-shot deadline is left alone and fires after the last pick,
  never in the same tick that made it. A recurring deadline that comes due
  is rolled to its next future slot without running, so a long draft is not
  followed by a burst of runs. The Opening Day readiness gate cannot be
  reached while the phase is AMATEUR_DRAFT.

Follow-ups:

- League creation wizard: offer the timing there (today a new league starts
  on mid-season and the commissioner changes it on the Commissioner page).
- `current_league_year()` falls back to the wall-clock year in the offseason
  (no schedule yet); only the draft router resolves the coming league year
  from the season context. Make the helper itself context-aware.
- Sim-to-milestone: a "To Draft" button still appears for a mid-season
  league only; nothing to change, but the label could say "July draft".
- **DONE 7.50.1 (owner decision 2026-10-11: the commissioner sets it):**
  `post_draft_wait_hours` in `draft_settings.json` (default 24, 0 = none),
  edited in Draft configuration. The draft state records `completed_at` at
  the last pick; `season._post_draft_hold_until` holds the AUTOMATIC tick
  until then (the deadline is kept and fires after the wait). The
  commissioner's Run now and manual sims are not held.
- **DECIDED 2026-10-11, no change:** free-agent signings and extensions stay
  blocked for the whole of any draft, preseason included
  (`free_agency.py`, `contract_negotiator.py`).
- **CONFIRMED 2026-10-11:** a new preseason-draft league has no draft in its
  first season (decision 6 as built).
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
- At the Release 5b flip the lineup auto-fill starts reading the centred vl
  for the league fixture's own generation, so
  `test_committed_fixture_matches_the_current_generator` will ask for a
  regenerated fixture (or a pinned tuning) at that point.

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
  regenerated fixture (or a pinned tuning) at that point. (Pinned with the
  switch-on mechanism: the generator now passes the engine defaults to the
  auto-fill, so the fixture does not depend on the active league.)

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
- **A lost `rating_centers.json` mid-season.** The season's engine
  generation lives only there. A generation 5 league that loses the file
  after games have been played reads as legacy from then on (a running
  process keeps what it last read, a fresh one does not). A league copy and
  a backup both carry the file. A second record of the generation (the
  season context, say) would close it.
- **The KPI harness is not always repeatable when several seasons run at
  once on one machine.** Two of thirteen identical `--engine 5` /
  `--tuning-overrides r5.json` calibration seed-1 seasons, launched eight at
  a time on Windows, came out as a second season (K .2131, R/G 4.20, HR/G
  .99 against .2138, 4.23, 1.17), the same alternative both times. Runs
  launched one to three at a time agreed. The harness writes nothing in the
  repository, so the cause is not a shared output file; a loader that
  swallows a read error and falls back (park data?) is the first suspect.
  (Cause established since: the park altitude file, found only through the
  active league. See "The KPI harness finds park data through the ambient
  active league" below.)
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
- **Live-path tools on a new scratch league now run generation 5**
  (`scripts/run_long_term_physics_sim.py` and the like). Set
  `NEXGEN_NEW_SEASON_ENGINE=4` to run them on the legacy engine.

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
- **FIXED 7.51.1** (the harness pins the lookup to the repository's
  `data/parks` through `NEXGEN_PARK_DATA_ROOT`, `Parks.csv` is tracked
  there, and a missing park file stops the run; kept for the diagnosis):
  **the KPI harness found park data through the ambient active league,
  not the fixture.** `utils/park_utils._park_data_roots` starts with
  `get_data_dir()`, the active league's folder, then the data root.
  `data/parks/Parks.csv` (the altitudes) is git-ignored and exists only in
  a developer's main checkout; the copies that are tracked sit in three
  league folders (`data/leagues/cbl`, `usabl` and `test-league`, each
  `/data/parks/Parks.csv`). So in a clean checkout or a worktree a harness
  run finds altitude only while the active league is one of those (`cbl`
  by default), and a run that starts while something in the same checkout
  has switched the active league to one without park files -- a test, a
  scratch league -- plays the whole season with no altitude. Measured on
  calibration seed 1, `--engine 5`, same code, only `active_league.txt`
  changed: home runs per team-game 1.121 with altitude and 1.060 without,
  home runs per fly ball .119 and .112, runs 4.40 and 4.34; K and BB move
  only as much as two different random streams do (22.06% / 22.08%, 8.10%
  / 8.17%). That is the "season with home runs per fly ball about 7% low"
  seen in agent worktrees and the "second season" of the repeatability
  item above. LIVE leagues are not affected: the production image
  excludes `/data/` (`.dockerignore`) and a league's own cloud folder has
  no `parks/` folder, but the three park files sit at the top of the data
  bucket (`gs://nexgen-bbpro-data/parks/`, checked 2026-10-12), which is
  the data root, the second place the lookup searches. So a live team with
  a park chosen plays with its dimensions and altitude. (An earlier note
  here said live leagues had no park data; that came from checking only
  the per-league folders and was wrong.) Proposed fix
  for a later release: the harness resolves park data from the fixture's
  own folder (`--base-dir`), and a park file it cannot find is an error in
  the harness, not a silent fallback to the generic park.
- **The lost-`rating_centers.json` item above is closed** by the second
  record of the generation (the witness in `season_progress.json`) and the
  working-copy guard. What is left: (a) a season that loses BOTH records
  reads as legacy unless its tuning overrides carry the generation 5
  marker, and a season held back on the legacy engine after a generation 5
  one that loses both reads as 5 from that marker; (b) a
  `rating_centers.json` that exists and cannot be parsed is never
  rewritten, so until someone restores or deletes it each game works its
  rating centres out from that day's rosters (the fault is logged with the
  path); (c) only `rating_centers.json` is pulled again after a failed
  startup pull, every other file that fails to come down is still rebuilt
  by the app and pushed.
- **An exhibition played in the preseason fixes the season's engine
  generation** (it creates the season's entry). It no longer converts the
  stored sliders, and since the league-relative ratings review it no longer
  fixes the rating centres either: a game with no date reads the stored
  centres, or works them out for itself, and stores nothing
  (`playbalance.game_runner._run_physics_game`: `store=False` when the
  game has no date). One played
  before the clubs' lineups were saved used to pin the season's hitter
  centres to that day's nine-best stand-ins (Contact 51.38 against 51.13
  on Opening Day, league fixture). The generation is still recorded by an
  exhibition; it is the same answer a season game would get.
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
- **Not retuned.** The generation 5 profile was tuned with Contact and Eye
  centred on the ACT mean (so calibration's regulars read about 1.5 points
  above the centre) and Power, velocity and pitch quality absolute. With
  the profile untouched the run level rose (4.39 / 4.13 / 4.37 to 4.43 /
  4.57 / 4.60), K rose (calibration 22.0% to 24.0%) and BB fell (8.2% to
  7.7%). The retune, the gates and the release notes follow it (the
  7.51.0 draft still carries the measurements taken before this change).
- **The matchup grid's pitches read 50, not 55, under the switch** (the
  grid pins its grade centre to its own 55, and a cell now goes through
  the engine's own pitcher context). Not re-measured: re-read the log5
  gate with the retune.

## Player development after the aging pause (7.51.2)

- **Yearly aging is paused** (`services/league_rollover.YEARLY_AGING_PAUSED`). Replace it with the development model designed for the rating re-spread: each offseason a player under 30 closes part of his gap to potential, older players decline, training redistributes the year's growth and does not add to it, and a 20-season population check must show the league average holding steady.
- **Training camp can still exceed potential.** `playbalance/player_development._boost_attribute` resets its room to `99 - current` once a rating reaches its potential, so it keeps adding up to 5 points a spring. Mild in practice (Contact sd 5.1 to 7.4 over five springs on a stats-test copy), but it belongs in the same rewrite.
- **Owner development budgets** fed the paused aging step's multiplier (`playbalance/aging_model.age_and_retire`); the new model needs the same input.
- **`_apply_yearly_aging` swallows a failed load or save** and returns silently; the replacement should report it in the rollover artifacts.

## Release 6a tooling: follow-ups (2026-10-13)

From the tooling step (generation 6 scaffolding, the new rating centres
for the harness, the Release 6 report-only KPIs, the composite matchup
grid). Nothing here changes a game.

- **Store the new centres at the switch-on.** `fielder_fa_center_<pos>`,
  `fielder_arm_center_<pos>`, `pitcher_gf_usage_center`, `hitter_gf_center`
  and `hitter_pull_center` are worked out for the KPI harness only
  (`services.league_rating_centers.unstored_rating_centers`). When
  generation 6 reads them a league must store them per season like the
  Release 5 centres (a season rule, a `centers_version` step, the "refuse
  to play without it" list if a model needs one) and
  `tests/test_r6a_tools_centers.py` must change with it: today it pins
  that no league game is given them.
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
- **CI does not run `--engine 6`.** Add a step when generation 6 has
  values of its own (it is a copy of generation 5 until then).

## Rating scale foundations: follow-ups (2026-10-13)

The scale module (`utils/rating_scale.py`), the `rating_scale` row column,
the engine and centre boundary, the consumer accessor and the generator's
final stretch are built and dark: no league is on scale 2. Found while
building them:

- **MIGRATION REQUIREMENT: no older build may touch a scale 2 file.** A
  server on 7.51.3 or before loads a scale 2 `players.csv` as scale 1 (it
  ignores the column) and its writer saves it back WITHOUT the column, so
  every stretched value silently becomes an "engine" value (measured by the
  review: one load-and-save on the 7.51.3 loader and writer turns a twin of
  the league fixture into a scale 1 file). Cloud Run's deploy overlap (two
  revisions serving at once) makes this realistic, and so does a rollback.
  The migration must not run until this is impossible. Options, not
  exclusive: (a) a fleet-wide minimum-version gate: the converter refuses
  to run unless the league records that every serving revision is at or
  above the first build that knows the column (written by each instance at
  start-up, checked under the sim lock; pause the scheduler as in the
  GCS-restore recipe); (b) a scale 2 file format an older build REFUSES to
  load: rename a required column (say `height` -> `height_in`, which the
  7.51.3 loader's `_required_int(row, "height")` rejects) or write scale 2
  leagues to `players_v2.csv` with `players.csv` kept as a tripwire, so an
  old build fails loudly instead of playing stretched numbers; (c) never
  roll back past the column build once any league has converted. (b) is the
  only one that also protects against a restored old binary.
  **Built (branch `r8-switch`): option (b).** A file holding any scale 2 row
  names its height column `height_in`; a 7.51.3 export refuses it
  (`ValueError: Missing required field: height` from both loaders). Its
  draft append still writes a row (blank `height_in`), which this build's
  loader then refuses by name. See "8.0.0 switch: follow-ups" below.
- **MIGRATION REQUIREMENT: check a league for clipping before converting
  it.** The maps were fitted to today's generated leagues; older rating
  distributions do not fit. The repo's `data/players.csv` (600 players)
  clips 211 Eye, 50 Power, 38 Contact, 52 hitter arm, 13 fielding, 27
  movement and 14 control values (and cuts 307 potential gaps at 99); the
  tracked sample leagues under `data/leagues/{usabl,cbl,test-league}` hold
  Contact and Power up to 99 (review figures; not re-measured here, those
  leagues are not to be touched). A clipped value no longer plays as it
  did. The converter must run `stretch_rows` dry first and refuse (or hand
  the decision to the owner, e.g. a league re-spread before the stretch)
  when any ACTIVE player's rating would clip; clips on minor leaguers and
  potential cuts are reported with it.
  **Built (`r8-switch`):** refuse on an ACT clip (every player counts in a
  league with no rosters), allow and log the rest. alpha-test: 2 clips,
  both LOW draft picks; stats-clean: none; repo `data/players.csv`: refused
  (405).
- **Draft classes must fit scale 2: raise the draft floors (decided).**
  The draft markdown (`_apply_draft_rating_scale`, floor 20) produces
  engine ratings below what scale 2 can store: Eye under 33.67, Contact or
  Power under 25.5, control under 27.5, movement under 29.5. 6 to 8
  prospects in a class of 240 (three seeds) have one such rating, almost
  always Eye; today they are clipped to stored 1 (and logged), so those
  prospects play slightly better than on scale 1. Decision: raise the draft
  floors, per rating and in engine points, to the lowest value scale 2 can
  store, so every prospect fits. Do it in the generator step, when draft
  classes are first generated on scale 2, NOT now: it would change scale 1
  generation.
  **Built (`r8-switch`):** floors Contact/Power 26, Eye 34, control 28,
  movement 30 (engine points) when generating for scale 2 only; scale 1
  classes are byte-identical to `r6a-int` (3 seeds x 240).
- **Mixed files are written, not refused (review fix).** Each row carries
  its own scale and reads correctly, so `save_players_to_csv` writes every
  row's own `rating_scale` and logs a warning naming the rows off the
  majority scale; `players_file_rating_scale` answers `"mixed"`. Code that
  needs ONE scale for a league (a new draft class, a pick appended to
  `players.csv`) takes the MAJORITY scale and refuses a file split evenly.
  The migration should still treat a mixed league as unfinished work and
  convert its stray rows.
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
- **Aging and training must be rebuilt before scale 2.**
  `playbalance/aging.py` and `playbalance/player_development.py` add
  points to the stored attributes with constants in engine points (caps
  of 5, thresholds of 75 and 80). On a scale 2 league a "+3" would be one
  engine point of Contact and three of speed. The development model on the
  stored scale (design section 3) replaces them. Until then training camp
  REFUSES a scale 2 player (`require_engine_scale_players`, before anyone
  is touched); yearly aging is paused at rollover (7.51.2) and has no
  tripwire of its own.
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
- **The runs level moves and was left to the joint retune:** against
  generation 5, +.21 runs per team-game on calibration, +.41 on the
  league fixture and +.02 on the flat fixture (four, four and two
  seasons). Split on two seasons each: the range, centring and table work
  without the error models is +.05 / +.25 / -.13 (the league fixture's
  gloves no longer mask its offence; the flat fixture's no longer cost it
  outs), and the errors at MLB volume add +.07 / +.16 / +.21. The league
  fixture fails its runs, SLG, OPS, hits and doubles gates until then.

## Release 6a power and doubles: follow-ups (2026-10-13)

Built on branch `r6a-power`, off by default (`scripts/kpi_profiles/r6_power.json`
over `--engine 6`). Numbers are calibration / league / flat fixture means
(8 / 4 / 2 seasons) unless noted.

- **Thirty-homer hitters.** Weak bats lose home runs and the league total
  is held, so home runs move up the order; decisions 6 and 16 lift stored
  Power 80 to 99, and the middle of the curve no longer has a flat spot.
  `qualified_hr30_count` reads 24.5 / 21.5 / 20.0 (generation 5: 19.4 /
  15.5 / 9.5) and one season's count has a spread of about 4 (a first-round
  table read 20.5, 24.4 and 20.6 on the same eight calibration seeds, one
  season at 33). The strict gate (20 +/- 8) is a per-season gate and will
  fail now and then. Gate it pooled over seeds, as the bottom-fifth ratio
  (seasons 9-13 of the first table read .797 / .765 / .755 / .675 / .751),
  before generation 6 is gated in CI.
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
- **Runs fall about .03 per team-game** with league doubles down to 1.61 /
  1.68 / 1.69: for the joint retune.
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
- **CI:** add `--engine 6 --tuning-overrides
  scripts/kpi_profiles/r6_pitching.json --strict` on calibration until the
  values are folded into `engine_6.json`.

## Release 6a integration: follow-ups (2026-10-14)

Branch `r6a-int` merges the scale, fielding, power and pitching branches and
builds `engine_6.json` from generation 5 plus the three area files (no key
is set by two of them). Generation 6 is still a development generation.
Measured on 8 / 4 / 2 seasons (calibration / league / flat fixtures):

- **CI now has a generation 6 to run.** The pitching item above is done
  by the profile itself: add `--engine 6 --strict` on calibration (seeds
  2-8 passed every strict gate here) and `--engine 6 --gate-set running`
  on the league fixture.
- **Pooled gates have no checker.** `ENGINE_GATES[6]["pooled"]` records
  the thirty-homer count (20 +/- 8) and the bottom-fifth HR ratio (at most
  .75) as means over seeds; one harness run cannot express that, so both
  are report-only and the per-season thirty-homer gate is dropped for
  generation 6. A small pooled check over a directory of season JSONs
  would close it (calibration .715 / 25.4, league .697 / 20.8 here: both
  pass pooled).
- **Generation 5's full strikeout-grid gate fails on the composite grid**
  (`matchup_k_log5_max_abs_resid` .027 against .02, calibration seed 1,
  60,000 PA a cell): the Contact 80 x pitcher 80 corner the pitching work
  accepted. The inner grid (.009) and the p5-p95 HR grid (.019) pass.
  Decide at the joint retune whether generation 6 keeps the full-grid gate
  or drops it for the inner one.
- **The league fixture's offence is high on generation 6** (the joint
  retune): runs 4.77 (+.32 on generation 5), SLG .414, OPS .733, doubles
  1.75, and SF/PA .0079 (fails the running set on 2 of 4 seasons). Almost
  all of it is fielding's (+.41 runs alone on seeds 1-4); the three areas
  together give .13 runs less than the sum of each alone.
- **`hr_scale` is the pitching work's 0.9195**, re-levelled with the power
  table off; the power work held home runs with the table's centre. Each
  alone adds about +.02 / +.00 HR a team-game on calibration and together
  +.02: no double count today, but both levers set the same level.
- **The flat fixture misses three of the new gates** (report-only there;
  bunched ratings): the pull-rating correlations .68 / .70 against .80,
  BB% per +10 control -0.68 against -1.35, and shortstop outs per 8
  points 6.06 against 6.9 +/- .8.
- **`hitter_gf_center` is required in a generation 6 game** with the
  doubles credit on (`centred_ratings.require_batted_ball_centers`), as
  the fielder centres are under `fielder_centred_ratings`. The live path
  supplies both for a generation 6 season
  (`tests/test_r6a_fielding_centers.py`, live games on the full profile).

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

- **Tutorial steps quote engine-scale ratings.** "Contact", "Eye and
  Control" and "Catcher fielding" in *The Updated Game Engine*
  (`services/tutorials.py`) give examples on today's stored scale (an 80
  Contact hitter, a 60 Eye hitter, 10 points of catcher Fielding). On a
  scale 2 league those numbers mean something else (engine Contact 60 is
  stored 80; engine Contact 80 cannot be stored). Rewrite them for scale 2
  (`TutorialStep(rating_scale=2)` shows a step to scale 2 leagues only,
  `rating_scale=1` to scale 1 only) together with the generation 6
  numbers. The new scale 2 step says the examples are on the earlier scale.
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

- **Switch-on depends on two other 8.0.0 pieces.** Training camp refuses a
  scale 2 player (`require_engine_scale_players`) until the development
  model replaces it, so every converted league's next spring would stop;
  and screens still show the percentile blend of stored values until the
  display step lands. Do not turn the switch on before both. (Both are
  merged on `r8-int`: camp reports a scale 2 player's development instead
  of refusing him, and the pages show stored ratings.)
- **Turning the switch off breaks a season already on generation 6** (the
  build no longer knows it, by the existing rule that a recorded generation
  is never played on a guess). The runbook says to hold with
  `NEXGEN_NEW_SEASON_ENGINE=5` instead. Owner/lead call: let a recorded
  generation 6 play with the switch off.
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
- **Integration with r8-develop.** The move runs at the rollover in
  `LeagueRolloverService.archive_season`, after `next_year` is worked out
  and BEFORE `_apply_yearly_aging`; r8-develop's
  `_apply_yearly_development` must sit right after it (move, development,
  aging, retirements). `services/offseason_development.py` writes
  `players.csv`: it must write through `save_players` / `update_players`
  or take `utils.players_file_lock` itself. Both branches change
  `utils/rating_scale.py` (`engine_potential`): merge by hand.
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
- **Eye's spread (addressed).** A scale 2 draft class now takes a quarter of
  the age markdown on Eye, without jitter
  (`player_generator.SCALE2_DRAFT_EYE_MARKDOWN`); the regulars' Eye sd ends
  about 13-14.5 (start 11.2-11.7) instead of about 18. Scale 1 generation is
  unchanged.
- **Order at the switch-on rollover (decided).** The conversion runs at the
  rollover before the development step (r8-switch), so a league's first
  offseason on the new scale is developed.
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

Branch `r8-int` (from the joint retune, 38ed1900b) merges `r8-display`,
`r8-switch` and `r8-develop`, gates generation 6 for the release and writes
its help. VERSION is NOT bumped (a major version needs the owner's
confirmation). Built here: the rollover order (archive, contracts, finances,
move, development, aging, retirements, promotions, Hall of Fame, reset;
`tests/test_r8_integration.py` on a real `archive_season`), every
players-file writer both locked and counted (a code walk keeps it so), the
8.0.0 gate set, CI's generation 6 step, the scale 2 tutorial steps, the
owner guide section, the release-note entry and RELEASE6_PLAN section 8.
Open:

- **Pooled gates still have no checker**, and the group is now five keys
  (the bottom-fifth HR ratio, the thirty-homer count, FIP per +10 arm, BB%
  per +10 control, the pitcher / hitter HR sd ratio). All five pass pooled
  on calibration (8 seasons) and the league fixture (4) as measured for
  8.0.0. A small script that reads a directory of season JSONs and applies
  `ENGINE_GATES[6]["pooled"]` would let CI gate them over seeds.
- **CI's generation 6 step is continue-on-error.** Make it blocking once it
  has passed on the runner (it passes locally on calibration seeds 1-8).
- **League fixture SF/PA** fails `--gate-set running` on seeds 1 and 3 (.0081,
  .0079 against .0068 +/- .001), as in the retune; the tag-up race refit
  belongs to the ball-flight step (RELEASE6_PLAN section 8).
- **The tutorial filters by rating scale, not by engine generation.** The
  8.0.0 steps show to a scale 2 league. A league converted and then held on
  generation 5 (`NEXGEN_NEW_SEASON_ENGINE=5` after its move; the runbook
  allows it) would read the generation 6 steps while playing generation 5.
  A `TutorialStep(engine_generation=...)` filter would close it.
- **The move's rollover artifact is not in the archived season record.**
  `artifacts["rating_scale_move"]` is set after `archive_current_season`
  copied the artifacts, so the season record and `metadata.json` do not
  carry it (the development step writes its own through
  `_record_in_archive`). `rating_scale.json` and the news item do record the
  move; route the move's result through `_record_in_archive` too if the
  season history should show it.
- **The working copy's push could copy a transient players-file lock**
  (`.players.csv.lock`) to the remote mirror. FIXED in the fix-up round:
  `*.lock`, `*.tmp` and the pull's own temporaries never travel either way
  (`api.working_copy._transient`).
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

## 8.0.0 switch-on rehearsal: pre-existing issues seen (2026-10-14, not fixed)

The rehearsal drove full copies of alpha-test and stats-test through the
real API with the switch on (`r6/p8/rehearsal/` in the session scratch).
These are 7.51 behaviours it ran into, not 8.0.0 changes:

- **Contract expirations leave owner teams unready.** After the rollover's
  contract step (alpha-test: 134 of its 509 active players became free
  agents) owners' clubs were not ready for the preseason until they, or the
  CPU fill, refilled their rosters. Not investigated beyond that.
- **A single-owner league started its season without a catcher**
  in the rehearsal. Not investigated.
- **The Players browser lists retired players as free agents.**
- **Free-agent rows do not show injuries.**
- **The sign endpoint's default salary is countered** (a signing with no
  salary given was answered with a counter-offer).
- **The 2026 World Series was dated 2027-01-19 to 01-24** on a copied
  league in the rehearsal. Not investigated.
- **An allowed bottom clip reached a major-league roster in the same
  offseason.** alpha-test's one allowed clip (a Low-A draft pick's Power,
  engine 23, stored as 1) is a minor leaguer at the move, so the clip rule
  allows it; the CPU's roster fill then moved him up within the same
  offseason. Harmless in play (he plays about a point better than his
  engine rating), but the rule's premise (bottom clips only on minor
  leaguers) does not hold for long. Note it if the rule is revisited.
- **8.0.0 tutorial filter (still open, above):** steps are filtered by
  rating scale, not engine generation.

## Contract re-negotiation with your own players (owner request, 2026-10-16)

Today a rejected extension offer locks the player out for a fixed 30 sim days
(`services/contract_negotiator.py`, `REJECTION_COOLDOWN_DAYS = 30`, rule 4 of
`check_extension_eligibility`), so an owner gets one try a month. The owner
wants a negotiation instead:

- **The player's own club can keep making offers** (counter after counter)
  until the player either accepts or definitively rejects. No fixed 30-day
  wait between offers.
- **Some players refuse to sign during the season at all** and go to free
  agency when the deal ends (a per-player, per-season decision, presumably
  more likely for players near free agency, players who expect a big market,
  or players unhappy with the club; to be designed).
- **Repeated tries can frustrate a player:** after several offers he may
  shut down talks for a period between 1 week and 30 days (length and the
  chance of it depending on how many offers, how far below his asking price
  they were, his personality / mood if the app models one). He tells the
  owner, and the club can try again when the period ends.
- Design questions for when this is built: how "definitively rejects" is
  decided and shown (a clear final no that ends talks for the season vs. the
  frustration shutdown); whether each counter-offer shows the owner how close
  he is (today's evaluation preview); how CPU clubs negotiate under the same
  rules; how the rules interact with the existing ones (phase gating during
  the draft and playoffs, the walk-year lockout, the years-remaining cap,
  pre-arb renewals, the FA bidding window); news / notifications when a
  player refuses to negotiate or heads to free agency; tests and the
  tutorial / help text for contracts.

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
- **Thirty-homer hitters** (decision 21, done in round 3): gated as the
  pooled SHARE of qualified hitters, .18 +/- .07 (MLB 2023-2025: .184).
  Calibration reads .128 (31 a season: it qualifies about 240 regulars),
  the league fixture .119, the flat fixture .079. The Power curve is kept.
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

Fixed on the branch: a player on any level of a club's roster (the injured
lists included) or under contract with a club is no longer a free agent;
`save_roster` refuses a second club for a player; a day with a player in
two of its games plays serially under `PB_PARALLEL_GAMES`. Left open:

- **Repair the production doubles (owner's decision).** alpha-test has two
  players on two clubs (P2739 BAL 15-day IL + COL active; P4720 COL + OKL
  active), stats-test none (backup of 2026-10-14 21:49). Run
  `scripts/find_double_rostered_players.py <league data>` on the live files
  first; it proposes keeping each with the club that held him before the
  void free-agent signing. Both void signings overwrote the contract (COL
  $8.69M x 5, OKL $8.25M x 5); the original terms are only in an older
  copy of `contracts.json` (GCS object versioning). Until repaired, P2739
  becomes active for BAL and COL when his injury clears, and a game day on
  which a shared player's two clubs both play runs serially.
- **Trades do not move the contract's club.** 23 alpha-test contracts name
  the club that traded the player away (the web app's `commit_trade` never
  calls `transfer_contracts`; the old desktop dialog did). Check what reads
  `contracts.json` `team_id` (payroll, the contracts page) before fixing.
- **Pitching-staff files list players the club no longer has** (6 in
  alpha-test; P7902 is on WAS's and COL's). A staff file only labels roles;
  clean them when a player leaves.
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
- **Do not repair a double by cutting the player.** A cut releases his
  contract (`release_contracts_to_free_agency`), which takes him off every
  club's roster file (`contracts_service._release_players_from_rosters`)
  and deletes the contract. Use the diagnostic's `--repair PLAYER=CLUB
  --contracts-from <older contracts.json> --output <folder>` (writes only
  the changed files into a separate folder) and upload them with the league
  idle.
