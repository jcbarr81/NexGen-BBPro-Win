# Future Work Ideas

This note captures high-level enhancements identified during the latest review so
they are easy to revisit when planning new milestones.

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
- **Status:** Open (roadmap).

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
- **Status:** Open.

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
- **Status:** Open.

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
- **Status:** Open.

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
- [ ] **V5.3-01 CPU trade evaluator refactor (value + roster fit + timeline)** (Effort: M, Risk: Medium, Depends: V5.2-17, V5.2-18)
- [ ] **V5.3-02 CPU incoming-offer response logic (accept/reject/counter)** (Effort: M, Risk: Medium, Depends: V5.3-01)
- [ ] **V5.3-03 CPU proactive trade proposal generator + cadence controls** (Effort: M, Risk: Medium, Depends: V5.3-01)
- [ ] **V5.3-04 Proposal quality guardrails + anti-spam filters** (Effort: S, Risk: Medium, Depends: V5.3-03)
- [ ] **V5.3-05 Promotion/options/protection event model + persistence** (Effort: M, Risk: High, Depends: D1)
- [ ] **V5.3-06 Prospect protection/eligibility rules enforcement** (Effort: M, Risk: High, Depends: V5.3-05)
- [ ] **V5.3-07 Late-bloomer variance model tied to scouting uncertainty** (Effort: M, Risk: Medium, Depends: V5.2-15)
- [ ] **V5.3-08 Strategy profiles v2 hooks for draft + FA + promotions** (Effort: M, Risk: Medium, Depends: V5.2-17, V5.3-05)
- [ ] **V5.3-09 Analytics/Career Arc v2 (similarity, aging buckets, filters, export)** (Effort: M, Risk: Medium, Depends: V5.2-19)
- [ ] **V5.3-10 Transparency v2 for trade/prospect decisions** (Effort: S, Risk: Low, Depends: V5.3-01, V5.3-05)
- [ ] **V5.3-11 Acceptance tests for CPU trade quality + prospect workflow regression** (Effort: M, Risk: Medium, Depends: V5.3-02..V5.3-10)

### v5.4 - Differentiators (Simulation Futures + Narrative + Presentation)
- **Target effort:** 6-10 weeks.
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
- [ ] **V5.4-01 Deterministic event log foundation (canonical schema + writers)** (Effort: L, Risk: High, Depends: D3)
- [ ] **V5.4-02 Season/date snapshot and fork manager** (Effort: M, Risk: High, Depends: V5.4-01)
- [ ] **V5.4-03 Batch simulation runner (up to 1,000 futures) + job orchestration** (Effort: L, Risk: High, Depends: V5.4-02)
- [ ] **V5.4-04 What-If comparator UI (baseline vs scenarios + deltas)** (Effort: M, Risk: Medium, Depends: V5.4-03)
- [ ] **V5.4-05 Signed action records + verification chain** (Effort: L, Risk: High, Depends: V5.4-01)
- [ ] **V5.4-06 Commissioner audit timeline UI + replay links** (Effort: M, Risk: Medium, Depends: V5.4-05)
- [ ] **V5.4-07 Deterministic replay validator tooling** (Effort: M, Risk: High, Depends: V5.4-01, V5.4-05)
- [ ] **V5.4-08 Story event extraction pipeline (weekly signals)** (Effort: M, Risk: Medium, Depends: V5.4-01)
- [ ] **V5.4-09 Story engine generator (breakouts, collapses, milestones, rivalries)** (Effort: M, Risk: Medium, Depends: V5.4-08)
- [ ] **V5.4-10 Highlight recap mode (key plays + summary presentation)** (Effort: M, Risk: Medium, Depends: V5.4-08)
- [ ] **V5.4-11 Performance guardrails for What-If + recap generation** (Effort: M, Risk: High, Depends: V5.4-03, V5.4-10)
- [ ] **V5.4-12 Release soak tests + deterministic replay sign-off** (Effort: M, Risk: High, Depends: V5.4-04..V5.4-11)

### Implementation Start Queue
- **Now:** `V5.3-01 CPU trade evaluator refactor (value + roster fit + timeline)`
- **Next:** `V5.3-02 CPU incoming-offer response logic (accept/reject/counter)`
- **Then:** `V5.3-03 CPU proactive trade proposal generator + cadence controls`

### Cross-Milestone Dependency Map
- **D1: Decision Explanation Schema** -> required by v5.2 AI transparency, v5.3
  trade/prospect rationale, and v5.4 audit/story output.
- **D2: Scouted vs True Rating Model** -> required by v5.2 scouting, v5.3
  prospect/trade valuation, and v5.4 story context quality.
- **D3: Deterministic Event Log** -> required by v5.4 What-If Lab and online/audit
  foundation.
- **D4: Command Center Aggregation Layer** -> provides operational visibility for
  all subsequent roadmap systems.

