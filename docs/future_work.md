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
1. **Domain model:** Introduce `Owner` → `LeagueProfile` → `Season` entities plus
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
- **Developer-only note:** This tooling remains internal and is not exposed to
  in-game/player UI surfaces.
- **Delivered artifacts:** `scripts/build_ui_handoff.py`,
  `scripts/generate_consistent_graphics.py`,
  `scripts/validate_graphics_consistency.py`,
  `config/graphics_style_manifest.json`,
  `docs/graphics_consistency_pipeline.md`.
- **Status:** Complete.

## 19. In-App Manual Maintenance Cadence
- **Goal:** Keep the in-app searchable manuals current as new features and menu
  paths evolve.
- **Scope:** Add a lightweight release checklist item to verify tutorial text
  and both manuals (Complete Game Manual + Finance System Manual) against the
  current UI labels and workflow order before each release.
- **Status:** Complete (baseline delivered in v5.0.97; automated help-surface
  release gate added in v5.0.110).

## 20. Player Morale System
- **Goal:** Introduce a dedicated morale model that influences development,
  performance variance, and roster-management decisions.
- **Scope:** Add player morale state and lifecycle events (playing time,
  role/promotions, injuries, streaks, team context), connect morale modifiers
  to training/development outcomes and gameplay tuning where appropriate, and
  surface morale in owner/admin UI plus tutorials.
- **Status:** Open.
