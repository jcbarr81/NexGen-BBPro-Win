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
- **Status:** Fixed (reconciled 2026-07-13). Hitter overall/star now blends a
  top-N leg (default 65%) with the position-weighted leg so elite specialists
  earn credit — see `api/routers/_rating_presentation.py:_compute_hitter_overall`.
  Note: a legacy plain-mean `overall_rating` still exists in
  `utils/rating_display.py`; verify no surface still uses it as a star source.

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

