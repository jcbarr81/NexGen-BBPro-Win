# NexGen-BBPro — Electron UI Guide

This manual documents every screen in the new Electron desktop UI. It
assumes you've launched the app and logged in as either an admin or an
owner. The shared `%LOCALAPPDATA%\NexGen-BBPro\data` directory is used by
both the legacy PyQt app and this UI, so you can run them side-by-side
while you're getting familiar with the new flows.

---

## Contents

1. [Getting started](#getting-started)
2. [Sidebar layout](#sidebar-layout)
3. [Today](#today)
   - [Dashboard](#dashboard)
   - [Season](#season)
   - [News](#news)
4. [My Team](#my-team)
   - [Roster](#roster)
   - [Lineup](#lineup)
   - [Depth Chart](#depth-chart)
   - [Training](#training)
   - [Injuries](#injuries)
   - [Finance](#finance)
   - [Settings](#team-settings)
5. [League](#league)
   - [Standings · Leaders · Stats](#standings--leaders--stats)
   - [Players · Teams · Schedule](#players--teams--schedule)
   - [Playoffs · History · Hall of Fame · Records](#playoffs--history--hall-of-fame--records)
6. [Transactions](#transactions)
   - [Free Agency](#free-agency)
   - [Trades](#trades)
   - [Draft](#draft)
   - [Submit Change Request](#submit-change-request)
   - [Activity](#activity)
7. [Admin](#admin)
   - [Commissioner](#commissioner)
   - [Command Center](#command-center)
   - [Finance Queue · Change Requests](#finance-queue--change-requests)
   - [Offseason Flow](#offseason-flow)
   - [Reassign Players](#reassign-players)
   - [Finance Stability](#finance-stability)
   - [Physics Tuning](#physics-tuning)
   - [Users](#users)
   - [New League](#new-league)
   - [Utilities](#utilities)
8. [Tips & keyboard shortcuts](#tips--keyboard-shortcuts)
9. [Troubleshooting](#troubleshooting)

---

## Getting started

### First run

If you have no leagues yet, login bounces to **Leagues → New**
(`/leagues/new?first-run=1`). The wizard walks five steps:

1. **Admin** – set the admin password (required because the shipped
   default is `pass`).
2. **Basics** – league name, year, mode (single-player, multi-owner).
3. **Setup** – choose a Quick-Start preset OR custom divisions.
4. **Teams** – the random-team generator seeds team names; click
   **Randomize** for new choices.
5. **Rules & Review** – rule preset, schedule template, confirm.

On submit, the league is created and made active, and you're logged in.

### Returning users

Login goes to **Leagues** to pick an active league, then **Dashboard**.
The sidebar league selector at the top of the Brand panel lets you
switch leagues without logging out.

---

## Sidebar layout

The sidebar is grouped into five collapsible sections:

- **Today** – Dashboard, Season, News
- **My Team** – Roster, Lineup, Depth Chart, Training, Injuries, Finance,
  Settings
- **League** – Standings, Leaders, Stats, Players, Teams, Schedule,
  Playoffs, History, Hall of Fame, Records
- **Transactions** – Free Agency, Trades, Draft, Submit Request, Activity
- **Admin** (admin-only) – Commissioner, Command Center, Finance Queue,
  Change Requests, Offseason Flow, Reassign Players, Finance Stability,
  Physics Tuning, New League, Users, Utilities

Click a section header to collapse/expand. The section containing your
current route always auto-expands. Preferences are stored in
`localStorage` and persist across launches.

---

## Today

### Dashboard

The home screen for an owner.

- **Hero banner** – team badge, city + name, record, run diff, streak.
- **Stat cards** – run differential, streak, active roster size, next
  game. Click a card to jump to the matching screen.
- **Division standings** – your division with your row highlighted. Rows
  link to the team detail page.
- **Upcoming & Recent** – next five games and last five results. Played
  rows link to the full HTML boxscore.
- **Widgets** – bullpen readiness, matchup scout for the next game,
  hot/cold performers, batting + pitching team leaders.

### Season

The single most-used admin/owner page.

- Header shows current phase, sim date, days played / total, days
  remaining in phase.
- **Sim Day**, **Sim Week**, **Sim Month**, and a custom **N Days** field
  advance the sim in place.
- **Sim to Draft** / **Sim to Playoffs** run until the next phase
  boundary. Both stop cleanly if any required step blocks.
- **Advance Phase** is the deliberate step between phases — for example,
  from Regular Season to Amateur Draft, or Playoffs to Offseason.
- The page blocks any sim command that would skip required preseason /
  offseason steps; if blocked, it tells you which admin page to visit.

### News

Chronological in-game events — roster moves, trades, injuries, sim
milestones, finance postings. Filter by team and category. The Dashboard
widget shows a trimmed preview.

---

## My Team

### Roster

Tabular view of your whole roster, grouped by level (Active / AAA / Low
/ DL / IR).

- Columns: position, role, bats, ratings (overall + role-specific).
- Move a player between levels by clicking the level badge or using the
  row actions. The server enforces level caps (e.g. 25 active) and
  writes a transaction entry.
- **Cut** releases a player to free agency. The news feed picks this up.
- Click any player's name to open their profile.

### Lineup

Two tabs — **vs LHP** and **vs RHP** — store separate batting orders.

- Drag-free UX: use ↑ / ↓ buttons to reorder; delete with the trash
  icon.
- Assign position in the grid (C, 1B, 2B, 3B, SS, LF, CF, RF, DH).
- **Autofill** rebuilds both lineups from ratings while respecting your
  depth chart. Use it as a starting point, then fine-tune.
- The **Pitching** tab exposes SP1–SP5, LR, MR1–MR3, SU, CL role slots.
  Order drives start scheduling and reliever call-ups.

Save after any edit — the CSVs feed the sim engine immediately.

### Depth Chart

Ordered priority list per defensive position (up to three per slot for
C/SS/CF/3B/2B/1B/LF/RF/DH).

- Top entry is the primary starter. Entries 2 and 3 back-fill when the
  starter is injured, rested, or promoted.
- Used by **Autofill** in the Lineup editor and by the injury
  replacement engine during sim.
- Stage changes are marked dirty; **Save** persists, **Reset** discards.

### Training

100% allocator per side (hitters and pitchers).

- Every track has a 5% minimum. Save is disabled until both sides sum to
  exactly 100.
- **Reset to defaults** clears your team override and inherits the
  league-wide mix.
- Budgets (from Finance) scale training-camp intensity.

### Injuries

Three sections: DL, IR, day-to-day.

- DL tiers: 15-day and 45-day. Every row shows eligible-to-activate
  date, days remaining, and the minimum required before activation.
- **Activate** returns a player to ACT (blocked until the DL minimum is
  met).
- IR is open-ended — stash long-term injuries there to clear the active
  roster, then manually activate when ready.
- Every event writes to the news feed and transactions log.

### Finance

Team-level finance snapshot.

- **Cash on hand**, **debt**, **preset** (simple / standard / MLB-like),
  and whether financials are enabled for this league.
- Revenue and expense totals by category; projected monthly values drive
  the budgets panel.
- Budget categories: training, scouting, development, facilities. These
  directly influence sim outcomes (camp intensity, scouting confidence,
  aging/development).
- Scrollable transactions log with the last N ledger entries.

### Team Settings

Team branding and strategy.

- **Primary / secondary colors** – hex inputs with a live swatch preview
  using your team abbreviation.
- **Stadium** – free-text input with autocomplete from the ballpark
  catalog; click the building icon to open the **full park browser**
  with field-diagram previews.
- **Team strategy** – league default or a team-specific profile (Win
  Now, Development Focus, etc.). Steers automation decisions.
- **Auto-reassign** – inherit league default, or explicitly
  enable/disable automatic ACT/AAA/LOW balancing for this team.

---

## League

### Standings · Leaders · Stats

- **Standings** (`/league`) – division-grouped. Rows show team badge,
  W–L, pct, GB, last-10, streak, runs for/against, run diff. Click a
  row to open team detail.
- **Leaders** (`/leaders`) – top N per stat using MLB qualifier rules.
  Batting: AVG, OBP, SLG, OPS, HR, RBI, SB, R, H. Pitching: ERA, WHIP,
  W, SV, SO, IP, K/9, BB/9. Click a name to open the profile.
- **Stats** (`/stats`) – full league hitters and pitchers table plus
  team totals. Use the tabs to switch.

### Players · Teams · Schedule

- **Players** (`/players`) – league-wide browser with team, position,
  role, and free-agent filters. Click for profile.
- **Teams** (`/teams`) – directory grouped by division. Click any team
  for its detail page (hero + standings slice + upcoming/recent +
  stats drill-down).
- **Schedule** (`/schedule`) – league-wide calendar with played/unplayed
  flags. Played rows link to the boxscore.

### Playoffs · History · Hall of Fame · Records

- **Playoffs** (`/playoffs`) – current year bracket with seeds,
  matchups, and game results. Each game row links to the boxscore.
- **History** (`/history`) – archive of completed seasons: champion,
  runner-up, series result, MVP, Cy Young, artifact paths.
- **Hall of Fame** (`/hall-of-fame`) – inductees plus current-year
  candidates. Admins can induct or remove.
- **Records** (`/records`) – league and per-team record book entries.

---

## Transactions

### Free Agency

Browse unsigned players. Filter by position, role, and free-agents-only.
Ratings and role shown inline. Click **Sign** and pick destination level
(ACT / AAA / LOW) to commit. Level caps are enforced server-side.

### Trades

Three panes: pending offers involving your team, accepted/rejected
history, and the trade composer.

- **Propose Trade** – pick partner team; move players + draft picks
  between give/receive lists. Commissioner-approval and pick-year caps
  are set in **Admin → Commissioner**.
- **Accept / Reject / Withdraw** — act on any pending offer in your
  inbox.
- CPU-initiated offers appear alongside owner-initiated ones and can be
  accepted, rejected, or ignored.

### Draft

Draft state + results. The draft fires automatically when the season
reaches the amateur draft phase (use **Sim to Draft** to reach it).

- State view: current round, overall pick, draft order, most recent
  picks. Admins can manually select; auto-pick handles any slot that
  doesn't act in time.
- Pick history is stored per season and viewable from the history
  screens. Export via **Admin → Utilities → Reports** to share.

### Submit Change Request

Owner-side bundler. After making roster / lineup / pitching / depth
edits, use this page to export a snapshot ZIP for commissioner review.

- Check which sections to include. Add an optional owner note.
- **Export request** writes a ZIP to the change-request outbox;
  **Download ZIP** saves it locally so you can send it to the admin.
- Previously exported requests appear below. **Export cancel** produces
  a cancel bundle if you need to withdraw before the commissioner
  applies the original.

### Activity

Full transactions ledger — every sign, move, cut, trade, contract event,
finance posting. Filter by team and action type.

---

## Admin

Everything in this section is admin-only and hidden from owner sidebars.

### Commissioner

- **Trade rules** – enabled, draft-pick trading, require commissioner
  approval, CPU-initiated trades, CPU proposal cadence, max pick trade
  years.
- **Injury level** – global injury-frequency setting.
- **Finance preset** – simple, standard, MLB-like; plus enforcement
  mode and per-module enablement.

Tweaks here ripple into every team's simulation immediately.

### Command Center

League-wide attention dashboard. Cards by severity:

- **Injuries** – teams with critical injury counts.
- **Pending approvals** – trades, change requests, finance queue.
- **Roster conflicts** – teams over a level cap.
- **Deadlines** – upcoming phase transitions.
- **Finance risks** – cash or payroll flags.

Each card links to the relevant admin page. Click **Refresh** after any
sim step or transaction review.

### Finance Queue · Change Requests

- **Finance Queue** – decisions that need commissioner approval
  (contract extensions, arbitration, etc.). Filter by queue type.
  **Apply approved** runs every approved row in one pass.
- **Change Requests** – owner-submitted ZIPs. For each request, set
  status (approved / rejected / requeue) and add a note. Approved
  requests apply the bundled files to disk.

### Offseason Flow

Stage checklist + pipeline runner.

- Overview card shows ended season → next season year, contract count,
  expiring contracts, arbitration candidates, unsigned players.
- Checklist lists every stage with status and completion timestamp.
- **Run pipeline** executes the full offseason rollover (contracts →
  arbitration → FA → snapshot) based on the current year.
- **Mark done** on individual stages is available for when you handle a
  step manually.

### Reassign Players

Admin bulk auto-assign.

- **Reassign all teams** runs the auto-assign engine league-wide — each
  team's ACT/AAA/LOW is recomputed from ratings and role. Does not
  release players.
- **Single team reassign** does the same for one team via dropdown.

### Finance Stability

Sandboxed multi-season finance tester.

- Inputs: number of seasons, optional seed, preset.
- **Run single preset** – full N-season simulation against a temp copy
  of the data tree. Result shows per-season metrics (distressed-debt,
  negative-cash, unsigned, payroll-spread, star-retention ratios) and
  a guardrails pass/fail badge.
- **Compare presets** – run the same scenario against multiple presets
  side-by-side.
- Use this to validate preset changes before applying them to the live
  league.

### Physics Tuning

Every engine knob from the PyQt Physics Tuning editor, in five sections:

- **Run Environment** – offense/pitching scale, HR, BABIP, walk, K.
- **Plate Discipline** – zone swing, chase, two-strike behavior.
- **Contact & Batted Ball** – contact rate, contact quality, foul rate,
  launch angle baseline.
- **Pitching & Fatigue** – velocity, movement, command variance,
  fatigue decay, fatigue start/limit pitch counts.
- **Defense & Running** – range, arm strength, error rate, speed,
  steal frequency.

Each knob has slider + precise numeric input. Per-knob **Reset** clears
just that override; **Reset all** clears every override back to
defaults. Overrides are stored separately from defaults so reset is
always safe.

### Users

users.txt manager.

- Create admin or owner accounts. Admin accounts have full access;
  owner accounts see only their team's My Team section (plus league
  pages).
- Team is picked from a dropdown that flags which teams already have an
  owner.
- Edit a user to change password, role, or team.

### New League

Same wizard as first-run. Use this to create a second league without
deleting the current one.

### Utilities

- **Logos** – regenerate team logos.
- **Avatars** – regenerate player avatars.
- **Reports** – CSV / HTML exports (standings, team stats, leaders,
  records).
- **Almanac** – league almanac export.
- **Snapshot** – full data-dir snapshot. Run before destructive admin
  actions.

---

## Tips & keyboard shortcuts

- **Sidebar section headers** toggle collapse/expand — handy when the
  list gets long.
- **Esc** closes dialogs and the park browser.
- **Ctrl+Shift+I** opens DevTools in dev mode (for debugging).
- Click any player name anywhere in the UI — rosters, lineups, depth
  charts, leaders, standings drill-downs — to open that player's
  profile.
- The team badge on the dashboard uses your team colors; they're set
  from **My Team → Settings**.
- The **Help** link (sidebar or header) opens this manual in-app; you
  can also launch any tutorial from there.

---

## Troubleshooting

**Blank screen after login.** Open DevTools (Ctrl+Shift+I) and check the
Console for a red error. Most often it's a data-shape mismatch; copy
the stack and report it. The sidecar logs live in the terminal tab
running `npm run dev`.

**Sidecar exited before handshake.** Your Python environment is
missing a dependency. Check the terminal for the traceback —
`ModuleNotFoundError: No module named 'xxx'` tells you what to install.
Set `NEXGEN_PYTHON=<path to python.exe>` to force a specific interpreter.

**"Admin role required" on an admin page.** You're logged in as an
owner. Log out and back in as admin, or ask the admin to elevate your
account from **Admin → Users**.

**Changes don't persist.** Watch for toast errors at the bottom of the
screen. If the server returns 400/500 the save didn't land; the error
message contains the reason (level cap, validation, etc.).

**First-run loop.** If `/leagues/first-run` returns `has_leagues: true`
but no league is active, navigate directly to `/select-league` and pick
one.

**Legacy PyQt app shows different data.** Both apps read/write the same
data root but cache inside their own process. Restart one of them after
the other makes a significant change to see a fully consistent view.
