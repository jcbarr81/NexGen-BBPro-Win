# Team Owner and Admin Guide

> **Note — legacy reference.** This guide was written for an earlier desktop
> (PyQt) build and its menus/dialogs. NexGen-BBPro now runs as a web/Electron app
> with hub-based navigation and is served in the cloud. The **features** described
> here (budget editor, arbitration decisions, contract options/renew, offseason
> checklist, single-player auto-approve vs. multi-owner commissioner queue) are
> current, but the **access paths** (menus like "Owner Tools", "Financial System
> Settings" dialogs, `python main.py` launch) no longer match the app. For
> current instructions use the in-app **Help → Manual** (Electron UI Guide), the
> **Finance System Manual**, and the in-app tutorials.

This guide explains how to operate the application as a **team owner** or as an
**administrator**.

After signing in, users are presented with dashboards tailored to their role.

## Startup Flow

From the splash screen, click **Start Game** and choose:
- **Load Existing League** to open login for leagues already saved on the device.
- **Create New League** to run guided league setup before logging in.

## Team Owner Dashboard

Team owners manage their franchise through the Owner Dashboard.

### Home Dashboard Finance Summary
- The Home page now includes a **Finance Summary** card showing cash, debt, projected monthly net, and budget targets.
- Use **Open Finance Hub** from that card for full financial detail and transaction history.

### Roster Management
- View Active, AAA and Low rosters.
- Move players between levels using the dropdown and movement buttons.
- Cut players from a roster.
- Save the roster. Validation enforces:
  - Maximum 25 players and at least 11 position players on the Active roster.
  - Maximum 15 players on the AAA roster.
  - Maximum 10 players on the Low roster.

### Player and Lineup Tools
- **Position Players / Pitchers**: open detailed windows to inspect players by role.
- **Lineups**: launch the lineup editor to set batting orders.
- **Pitching Staff**: manage pitching roles and rotations.
  - Roster, lineup, pitching, and depth-chart edits apply directly to the shared league data — there is no export/approval step.
- **Finance page**: now split into **Owner Ops** (cash/debt, projections, budgets, ledger history) and **GM/Coach Ops** (module status, payroll/contracts, arbitration/free-agency queues, and quick actions).
  - Owner Ops now includes editable budget fields for training, scouting, development, and facilities when the Owner Budgets module is enabled.
  - Owner Ops now includes a **Scouting Controls** card where owners can set scouting intensity (Low/Normal/High) and review current scouting confidence, estimated error band, and monthly scouting-credit pace.
  - GM/Coach Ops now includes queue actions to **Queue Recommended Arbitration** and **Queue Recommended FA Targets** for tracking front-office decisions.
  - GM/Coach Ops now includes a **Next Finance Actions** panel that summarizes what to do next based on current season phase, queue state, and league mode.
  - GM/Coach Ops contract list supports inline contract-term actions. **Extend Contract** is available whenever GM Contracts are enabled; advanced terms (**Edit Guarantees**, **Add/Edit/Remove Option**, **Add/Edit/Remove Incentive**, **Exercise Option**, **Decline Option**) require GM Contracts set to **Advanced** or **MLB-Like**.
  - Owner budget levels for **training/development/facilities** now feed into preseason training-camp development intensity (higher budget support improves camp gains; lower support reduces them).
  - Owner **development** budgets also influence offseason player aging/development progression (better support improves positive development and softens decline).
  - Owner **scouting** budgets now drive scouting confidence in player profiles; lower scouting investment increases estimated rating uncertainty, while higher investment improves report precision.
  - Commissioners can enable/disable scouting fog-of-war from **Admin -> League Settings -> Financial System Settings** using **Enable Scouting Fog-of-War**. Existing leagues default to disabled until the commissioner turns it on.
  - Commissioners can tune league scouting pacing in the same dialog using **Scouting Fog-of-War Tuning** (base monthly credits, finance-off pace multiplier, decay/passive gain, bank cap, and auto-spend cap).
  - In single-player leagues, recommended finance decisions are auto-approved locally; in multi-owner leagues they are queued for commissioner review.
- **Transactions**: view recent roster moves.
- **Settings**: adjust team colours, logos and other options.
  - Team Settings now includes a **Team Strategy** profile selector with **Use League Default** and per-team override options.
  - Team Settings now includes a **Roster Auto-Reassign** override so each team can inherit league default automation or opt in/out directly.

### League Information
- **Standings** and **Schedule** windows give a league-wide overview.
- **League Command Center** provides one place to triage injuries, pending approvals, roster conflicts, deadlines, and finance-risk alerts.
- **Trades**: propose trades with other teams.
- **Free Agency Hub**: browse unsigned players and submit signings.
- **News Feed**: display the latest league news.

### Tutorials
- Run **Trades & Transactions** to review current trade flow behavior, including draft-pick trades and commissioner-approval mode.
- Run **Finance Hub Overview** to walk through the new Owner Ops + GM/Coach Ops finance hub and the related queue/actions workflow.
- Run **League Command Center** to review league-wide operational alerts and suggested next actions.
- Run **Appearance & Themes** for a guided walkthrough of theme-family selection and light/dark toggling.
- Run **Dashboard Overview** to review top-bar navigation, including the new **Owner Tools** menu shortcuts.
- Open **Tutorials -> Reference Manuals** for two searchable in-app documents:
  - **Complete Game Manual**
  - **Finance System Manual**

### Appearance & Theme Selection
- Open **View -> Theme Family** to choose between **Classic** and **Enhanced Warm**.
- Use **View -> Toggle Light/Dark** (or sidebar **Toggle Light/Dark**) to switch brightness within the selected family.
- Theme preferences are saved globally and restored automatically on next launch.

### Owner Tools Menu
- Use the top-bar **Owner Tools** menu for direct access to core workflows:
  - **Lineup Editor**
  - **Pitching Staff**
  - **Reassign Players**
  - **Trade Center**
  - **Free Agency Hub**
  - **Open Finance Hub**
  - **Team Settings**

Unsaved roster changes are flagged with an asterisk in the window title.

## Admin Dashboard

Administrators control league configuration and high-level operations.

### Admin Tutorials
- Open the Admin **Tutorials -> Commissioner Workflows** menu for guided walkthroughs:
  - **Admin Dashboard Overview**
  - **Appearance & Themes**
  - **League Setup & Manager**
  - **User Management & Roles**
  - **Season Progression Flow**
  - **League Command Center**
  - **Trade & Review Queues**
  - **Exports & Utilities**
- Open **Tutorials -> Asset Guides** for:
  - **Team Logo Tutorial**
  - **Player Avatar Tutorial**
- Open **Tutorials -> Reference Manuals** for:
  - **Complete Game Manual**
  - **Finance System Manual**
- New commissioner onboarding runs the **Admin Dashboard Overview** tutorial automatically on first launch.

### Admin Appearance Controls
- Open **View -> Theme Family** to choose between **Classic** and **Enhanced Warm**.
- Use **View -> Toggle Light/Dark** to change brightness for the active family.
- The selected theme family/mode persists across restarts.

### Dashboard Navigation
- **Dashboard**: league overview metrics, draft timing/status, and priority queues.
- **Transactions**: trade approvals, trade settings, and owner change-request queue.
- **Season**: season progression, exhibition game, playoffs viewer, schedule regeneration, Opening Day reset, and league history.
- **Draft**: draft pool access, draft console, draft settings, and draft results.
- **Teams**: open an owner dashboard for any club and run league-wide roster/lineup automation.
- **Users**: add/edit admin and owner accounts.
- **League Settings**: create league, physics tuning, team strategy profiles, injury settings, Hall of Fame settings, and league operations hubs.
- **Assets & Exports**: team logos, player avatars, league report exports, league almanac exports, and owner snapshot zip exports.

### League Creation and Policy Setup
- **Create League** (League Settings): generate a new league structure (overwrites current data).
  - During creation, commissioners can set baseline trade policy:
    - trading enabled/disabled,
    - draft-pick trading enabled/disabled,
    - commissioner-approval requirement for trade execution,
    - maximum years out for tradable draft picks.
  - During creation, commissioners now complete a required **Finance Setup** step:
    - choose a preset (**Off**, **Simple**, **Standard**, **MLB-Like**) or
      switch to **Custom** for key module choices,
    - review a finance summary in the final confirmation before league files are generated,
    - persist the selected finance settings as the league's initial bootstrap state.
- **Financial System Settings** (League Settings): configure global finance on/off, presets, grouped module levels (Owner, GM, Governance/AI), and AI tuning.
  - The window uses a full-height scrollable layout so all controls remain reachable on smaller displays.
  - The dialog includes a **Commissioner Projection Preview** snapshot (cash/debt/net/payroll risk summary).
  - The dialog includes prioritized **Finance Alerts** with explicit next-step guidance (cash risk, payroll threshold/floor risk, offseason checklist deadlines, and GM queue pressure).
  - The guidance panel in this dialog reflects the current saved workflow state and the next checklist stage.
- **Team Strategy Profiles** (League Settings): set league defaults and per-team overrides for both team strategy intent and roster auto-reassign automation.

### Trade Oversight (Transactions)
- **Review Pending Trades**: approve or reject pending trades submitted by teams.
- **Open Trade Settings**: configure whether trading is enabled league-wide.
  - Toggle all trading on/off.
  - Allow or disallow draft-pick trades independently.
  - Require commissioner approval before an owner-accepted trade is executed.
  - Set the maximum number of years into the future that draft picks can be traded.
- **Review GM Finance Queue**: in multi-owner leagues, approve/reject pending owner GM finance decisions (arbitration/free-agency queue items) from a single queue view.

When draft-pick trading is enabled, teams can include picks in offers from the
Trade dialog. Pick ownership is tracked and used on draft day, so the team that
owns the pick makes the selection.

### Operations Highlights
- **Reset to Opening Day** (Season): clear current season results and standings, reset progress to day one, and set the phase to Regular Season (non-destructive to teams/rosters). You will be prompted whether to also purge saved season boxscores (`data/boxscores/season`).
- **Regenerate Season Schedule** (Season): generate a fresh regular-season schedule and clear previous results.
- **Open League Command Center** (Season): monitor injuries, approvals, roster conflicts, deadlines, and finance risk alerts in a unified operations view.
- **Open Offseason Finance Workflow** (Season): during Offseason/Preseason, use the guided checklist to run the finance pipeline (snapshot, arbitration, reset) and complete finance review stages in order (contracts, arbitration, budgets, free-agency kickoff, finalize).
  - The workflow now includes dedicated in-dialog review tabs for **Contract Expirations**, **Arbitration Details**, and **Budget Deltas** before each stage is marked complete.
  - An **Action Readiness** panel now shows the next required stage and explicit blocker reasons when an action is not available (for example, missing prerequisite checklist stage).
  - A **Finance Alerts** panel now surfaces actionable risk/deadline messages tied to the same league state (cash risk, payroll threshold/floor pressure, queue/deadline follow-ups).
  - CPU/non-owner teams are included in the same offseason pipeline. Arbitration logic now applies team-aware CPU decisions (retain stars more aggressively and non-tender expensive underperformers when appropriate), with outcomes visible in the review tabs.
- **Generate Team Logos** (Assets & Exports): create logo images for all teams.
- **Generate Player Avatars** (Assets & Exports): create/rebuild avatar images.
- **Export Almanac (HTML)** (Assets & Exports): generate a multi-page historical league reference site.
  - The export writes a browsable `almanac/index.html` landing page with sections for seasons, teams, players, awards, postseason, leaders, transactions, finance, and records.
  - Use it when you want a shareable baseball-reference-style archive of the current league history, especially before releases, major sim runs, or offseason rollovers.

### Amateur Draft
The Amateur Draft introduces new prospects mid-season and pauses the season to conduct the draft.

- Draft Timing: Draft Day is the third Tuesday in July (computed from the schedule).
  - The Draft page shows a status line with the current simulation date and Draft Day.
  - "View Draft Pool" and "Start/Resume Draft" enable only on/after Draft Day and only if the draft has not been completed that year.
  - "Draft Settings" is always available.

- Draft Page Buttons:
  - **Draft Settings**: configure rounds, pool size, and RNG seed for reproducibility. Settings are saved to `data/draft_config.json`.
  - **View Draft Pool**: browse the prospect pool (enabled on/after Draft Day).
  - **Start/Resume Draft**: open the Draft Console to conduct the draft and resume mid-draft if needed (enabled on/after Draft Day).

- Draft Console Overview:
  - Pool table with search filter; pitchers display EN/CO/MV (endurance/control/movement).
  - On-the-clock banner indicating the current team and pick.
  - Recent picks board (last 10); state and results are persisted per pick.
  - Actions:
    - "Make Pick" to select the highlighted prospect.
    - "Auto Pick (This Team)" for an AI pick respecting organizational needs.
    - "Auto Draft All" to finish the remaining rounds automatically.
    - "Commit Draftees to Rosters" appends new players to `data/players.csv` and places them on each team's `LOW` roster level.
  - Double-click a prospect to open their Player Profile for detailed ratings.

- Files and Persistence:
  - Draft Pool: `data/draft_pool_<year>.csv` and `data/draft_pool_<year>.json`.
  - Draft State: `data/draft_state_<year>.json` (order, current pick, selected ids, seed).
  - Draft Results (log): `data/draft_results_<year>.csv` (round, overall_pick, team_id, player_id).
  - Draft completion is tracked in `data/season_progress.json` under `draft_completed_years`.

Tip: Use a non-empty seed in Draft Settings for deterministic pool generation and draft order.

## Administrator Login Bootstrap
New installs now prompt for the initial administrator password during setup.
That password becomes the bootstrap credential for freshly created leagues and
fresh runtime data roots.

- Interactive installer runs: enter and confirm the administrator password in
  the installer wizard.
- Upgrade installs: choose whether to keep existing admin passwords or reset
  all existing league admin accounts to the installer password you enter.
- Silent/unattended installs: the app requires administrator password setup on
  the first admin login before admin access is granted.
- Existing leagues keep their current `users.txt` credentials unless you
  explicitly reset or replace them.

---
## Dashboard Updates

The dashboards have been reorganized to improve clarity while keeping the
existing visual style and theme.

### Owner
- New Home page with quick metrics (Record, Run Differential, Next Opponent
  and Date) and shortcuts (Lineups, Pitching Staff, Recent Transactions).
- Header shows: "Next: <opponent> <date> | Record W-L RD +/-X".
- Unified **Players** browser with tabs for Position Players and Pitchers.
- Roster page displays a defensive coverage notice when positions are missing.
- Navigation labels: "Moves & Trades" and "League Hub".
- In multi-owner leagues, season progression/simulation actions are
  commissioner-only; owner dashboards hide season progression controls.

### Admin
- New Home page with overview metrics: Pending Trades, Teams, Players,
  Season Phase; plus Draft Day and status. Priority Queues: Review Trades,
  Open Season Hub, Open Draft Hub.
- Transactions page grouped into:
  - Trade Queue: Review Pending Trades, Open Trade Settings.
- Season page grouped into:
  - Season Flow: Open Season Progress, Run Exhibition Game, Open Playoffs Viewer.
    - Season Progress: supports milestone actions - Simulate to Midseason,
      Simulate to Draft, and Simulate to Playoffs. On Draft Day the
      application switches to the Amateur Draft phase and pauses to conduct
      the draft via the Draft Console. After committing results, the season
      resumes in the Regular Season phase. See also: `docs/season_progress.md`.
  - Schedule Control: Regenerate Season Schedule, Reset to Opening Day.
  - Archives: League History.
- League Settings page grouped into:
  - League Configuration: Create League.
  - Rules & Balancing: Physics Tuning, Injury Settings, Hall of Fame Settings.
  - Operations Hubs: Free Agency Hub, Injury Center.
- Teams page grouped into:
  - Team Access: searchable team selector + Open Team Dashboard.
  - Bulk Actions: Set All Lineups, Set All Pitching Roles, Auto Reassign
    All Rosters, with roster size constraints noted.
- Assets & Exports page grouped into:
  - Assets: Generate Team Logos, Generate Player Avatars (+ tutorials).
  - Exports & Sharing:
    - Export Reports (HTML default, optional CSV) for current analytical bundles.
    - Export Almanac (HTML) for full historical league reference pages.
    - Export Owner Snapshot Zip for rollback/import safety.
- Draft page now shows "View Draft Results" after the draft is completed.
- Users page shows a searchable list of users alongside Add/Edit actions.
This document will evolve as new features are introduced.


