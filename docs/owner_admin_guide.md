# Team Owner and Admin Guide

This guide explains how to operate the UBL Simulation application as a **team owner** or as an **administrator**. Launch the app with:

```bash
python main.py
```

After signing in, users are presented with dashboards tailored to their role.

## Team Owner Dashboard

Team owners manage their franchise through the Owner Dashboard.

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
- **Submit Change Request**: export roster/lineup/pitching/depth chart updates for commissioner approval.
- **Transactions**: view recent roster moves.
- **Settings**: adjust team colours, logos and other options.

### League Information
- **Standings** and **Schedule** windows give a league-wide overview.
- **Trades**: propose trades with other teams.
- **Free Agents**: automatically sign the first available free agent.
- **News Feed**: display the latest league news.

### Tutorials
- Open the **Tutorials** menu and run **Owner Change Requests** for a step-by-step walkthrough of exporting updates and sending the JSON bundle to the commissioner.
- Run **Trades & Transactions** to review current trade flow behavior, including draft-pick trades and commissioner-approval mode.

Unsaved roster changes are flagged with an asterisk in the window title.

## Admin Dashboard

Administrators control league configuration and high-level operations.

### Dashboard Navigation
- **Dashboard**: league overview metrics, draft timing/status, and priority queues.
- **Transactions**: trade approvals, trade settings, and owner change-request queue.
- **Season**: season progression, exhibition game, playoffs viewer, schedule regeneration, Opening Day reset, and league history.
- **Draft**: draft pool access, draft console, draft settings, and draft results.
- **Teams**: open an owner dashboard for any club and run league-wide roster/lineup automation.
- **Users**: add/edit admin and owner accounts.
- **League Settings**: create league, physics tuning, injury settings, Hall of Fame settings, and league operations hubs.
- **Assets & Exports**: team logos, player avatars, league report exports, and owner snapshot zip exports.

### League Creation and Policy Setup
- **Create League** (League Settings): generate a new league structure (overwrites current data).
  - During creation, commissioners can set baseline trade policy:
    - trading enabled/disabled,
    - draft-pick trading enabled/disabled,
    - commissioner-approval requirement for trade execution,
    - maximum years out for tradable draft picks.

### Trade Oversight (Transactions)
- **Review Pending Trades**: approve or reject pending trades submitted by teams.
- **Open Trade Settings**: configure whether trading is enabled league-wide.
  - Toggle all trading on/off.
  - Allow or disallow draft-pick trades independently.
  - Require commissioner approval before an owner-accepted trade is executed.
  - Set the maximum number of years into the future that draft picks can be traded.

When draft-pick trading is enabled, teams can include picks in offers from the
Trade dialog. Pick ownership is tracked and used on draft day, so the team that
owns the pick makes the selection.

### Operations Highlights
- **Reset to Opening Day** (Season): clear current season results and standings, reset progress to day one, and set the phase to Regular Season (non-destructive to teams/rosters). You will be prompted whether to also purge saved season boxscores (`data/boxscores/season`).
- **Regenerate Season Schedule** (Season): generate a fresh regular-season schedule and clear previous results.
- **Generate Team Logos** (Assets & Exports): create logo images for all teams.
- **Generate Player Avatars** (Assets & Exports): create/rebuild avatar images.

### Amateur Draft
The Amateur Draft introduces new prospects mid-season and pauses the season to conduct the draft.

- Draft Timing: Draft Day is the third Tuesday in July (computed from the schedule).
  - The Draft page shows a status line with the current simulation date and Draft Day.
  - “View Draft Pool” and “Start/Resume Draft” enable only on/after Draft Day and only if the draft hasn’t been completed that year.
  - “Draft Settings” is always available.

- Draft Page Buttons:
  - **Draft Settings**: configure rounds, pool size, and RNG seed for reproducibility. Settings are saved to `data/draft_config.json`.
  - **View Draft Pool**: browse the prospect pool (enabled on/after Draft Day).
  - **Start/Resume Draft**: open the Draft Console to conduct the draft and resume mid-draft if needed (enabled on/after Draft Day).

- Draft Console Overview:
  - Pool table with search filter; pitchers display EN/CO/MV (endurance/control/movement).
  - On-the-clock banner indicating the current team and pick.
  - Recent picks board (last 10); state and results are persisted per pick.
  - Actions:
    - “Make Pick” to select the highlighted prospect.
    - “Auto Pick (This Team)” for an AI pick respecting organizational needs.
    - “Auto Draft All” to finish the remaining rounds automatically.
    - “Commit Draftees to Rosters” appends new players to `data/players.csv` and places them on each team’s `LOW` roster level.
  - Double-click a prospect to open their Player Profile for detailed ratings.

- Files and Persistence:
  - Draft Pool: `data/draft_pool_<year>.csv` and `data/draft_pool_<year>.json`.
  - Draft State: `data/draft_state_<year>.json` (order, current pick, selected ids, seed).
  - Draft Results (log): `data/draft_results_<year>.csv` (round, overall_pick, team_id, player_id).
  - Draft completion is tracked in `data/season_progress.json` under `draft_completed_years`.

Tip: Use a non-empty seed in Draft Settings for deterministic pool generation and draft order.

## Default Administrator Login
When user data is reset, a default administrator account is created. Although
most passwords are stored using `bcrypt` hashes, the fallback administrator
record is saved in plain text so the app remains accessible even if the
`bcrypt` dependency is missing. Use these credentials to access the Admin
Dashboard if no other accounts exist:

```
username: admin
password: pass
```

---
## Dashboard Updates

The dashboards have been reorganized to improve clarity while keeping the
existing visual style and theme.

### Owner
- New Home page with quick metrics (Record, Run Differential, Next Opponent
  and Date) and shortcuts (Lineups, Pitching Staff, Recent Transactions).
- Header shows: “Next: <opponent> <date> | Record W-L RD ±X”.
- Unified **Players** browser with tabs for Position Players and Pitchers.
- Roster page displays a defensive coverage notice when positions are missing.
- Navigation labels: “Moves & Trades” and “League Hub”.

### Admin
- New Home page with overview metrics: Pending Trades, Teams, Players,
  Season Phase; plus Draft Day and status. Priority Queues: Review Trades,
  Review Change Requests, Open Season Hub, Open Draft Hub.
- Transactions page grouped into:
  - Trade Queue: Review Pending Trades, Open Trade Settings.
  - Owner Change Queue: Review Change Requests.
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
  - Exports & Sharing: Export Reports (CSV/PDF), Export Owner Snapshot Zip.
- Draft page now shows "View Draft Results" after the draft is completed.
- Users page shows a searchable list of users alongside Add/Edit actions.
This document will evolve as new features are introduced.

