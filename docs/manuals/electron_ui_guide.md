# NexGen-BBPro — Electron UI Guide

This manual documents every screen in the Electron desktop UI. It assumes
you've launched the app and logged in as either an admin or an owner.
The shared `%LOCALAPPDATA%\NexGen-BBPro\data` directory is used by both
the legacy PyQt app and this UI, so you can run them side-by-side while
you're getting familiar with the new flows.

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
   - [Notifications](#notifications)
   - [Finance](#finance)
   - [Settings](#team-settings)
5. [League](#league)
   - [Standings · Leaders · Stats](#standings--leaders--stats)
   - [Players · Teams · Schedule](#players--teams--schedule)
   - [Playoffs · History · Hall of Fame · Records · Ballparks](#playoffs--history--hall-of-fame--records--ballparks)
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
   - [Exhibition Game](#exhibition-game)
   - [League Admin](#league-admin)
   - [Physics Tuning](#physics-tuning)
   - [Users](#users)
   - [New League](#new-league)
   - [Utilities](#utilities)
8. [Validation & autosave](#validation--autosave)
9. [Tips & keyboard shortcuts](#tips--keyboard-shortcuts)
10. [Help & tutorials](#help--tutorials)
11. [Troubleshooting](#troubleshooting)

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

The sidebar shrinks to **seven top-level destinations** plus a pinned
**Help & Tutorials** link at the bottom:

- **Today** – Dashboard, Season, News (always-on quick links).
- **Favorites** – appears only when you've pinned routes (right-click
  any sidebar entry or hub card → *Pin to sidebar*).
- **My Team** *(hub)* – `/hub/my-team`. Card grid of Roster, Pitchers,
  Lineup, Depth Chart, Training, Injuries, Notifications, Finance,
  Team Settings.
- **League** *(hub)* – `/hub/league`. Standings, Leaders, Stats, Players,
  Teams, Schedule, Playoffs, History, Hall of Fame, Records, Ballparks.
- **Transactions** *(hub)* – `/hub/transactions`. Free Agency, Trades,
  Draft, Submit Request, Activity.
- **Admin** *(hub, admin-only)* – `/hub/admin`. Commissioner, Command
  Center, Finance Queue, Change Requests, Exhibition Game, Offseason
  Flow, Reassign Players, Finance Stability, League Admin, Physics
  Tuning, New League, Users, Utilities.
- **Notifications** – top-level because it's how owners pause the sim.
- **Help & Tutorials**.

### Hubs

Click any hub to land on a card grid of every page in that category.
Each card shows the page title, a one-line description, and a pin
indicator if you've favorited it. Capability-gated cards auto-hide
based on your league: Finance pages require finance enabled, Submit
Request requires multi-owner, etc. Right-click any card to **Pin to
sidebar** or **Unpin from sidebar**.

### Breadcrumbs

Every page header now shows a trail like `Home / My Team / Roster`. The
last segment is the current page; earlier segments are clickable links
that jump up one level. Dynamic routes (player profile, team detail,
compare, boxscore) include the parent hub crumb so the trail still reads
naturally.

### Collapse to icons-only

The chevron at the top-left of the sidebar collapses the rail from
256 px to a 56 px icon strip. Hover any icon to see its label; click
the chevron again to expand. The preference is stored per browser
profile (`nexgen:sidebar:rail-collapsed`).

### Favorites

Right-click any sidebar entry or hub card to **Pin to sidebar**.
Pinned routes appear in a Favorites section above the hubs. Right-click
again to unpin. Favorites are stored as `nexgen:sidebar:favorites` in
localStorage. Pin indicators (the small pin icon) show on both the hub
card and the sidebar row when pinned.

### Phase-aware filtering

The Favorites section auto-hides routes that don't apply to the current
season phase:

- **Draft** is hidden outside `AMATEUR_DRAFT` / `PRESEASON`.
- **Offseason Flow** is hidden outside `OFFSEASON` / `PRESEASON`.

Hub cards still show every page so you can pre-explore.

### Section collapse + active route

Each section header has its own chevron — collapse a section to free
up space without losing the others. The section containing your current
route always auto-expands. Section preferences persist as
`nexgen:sidebar:collapsed` in localStorage.

### Team-color stripe

The UI picks up your team's primary color for a thin accent stripe on
every team-specific page (Dashboard, Team Detail, Roster, Lineup, Depth
Chart, Finance, Training, Settings, Injuries) so the app reads as
"this is about *my* team" without repainting the whole chrome.

---

## Today

### Dashboard

The home screen for an owner.

- **Hero banner** – team logo (auto-generated or colored-abbreviation
  fallback), city + name, record, run diff, streak. Record/Run Diff/Streak
  render as a **scoreboard readout** — tabular monospace numerals with an
  amber LED glow, framed in a dark inset.
- **Stat cards** – run differential, streak, active roster size, next
  game. Each card sports a thin team-color left stripe. Click a card to
  jump to the matching screen.
- **Division standings** – your division with your row highlighted using
  a team-color tint + stripe. Rows link to the team detail page.
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
- **Right-click any row** for a context menu: Open profile,
  **Training focus…** (per-player override dialog), Move to Active,
  Send to AAA, Send to Low-A, Place on DL (15), Place on 60-day IR,
  Shift to 45-day DL (DL rows), Release / Cut.
- Or click the three-dot action button at the row's right for the same
  options.
- **Cut** triggers a confirmation dialog and writes a release transaction.
- Click any player's name to open their profile.

**Pitcher SP/RP labeling.** The role column reflects each pitcher's
display role — `preferred_pitching_role` if set, otherwise the stored
`role`, otherwise an endurance-based fallback (>55 = SP). Granular roles
(SP, RP, CL, LR, MR, SU) collapse to the SP/RP bucket here; the
fine-grained value drives the Lineup → Pitching staff editor.

### Lineup

Two tabs — **vs LHP** and **vs RHP** — store separate batting orders,
plus a **Pitching Staff** tab for role assignments.

- **Baseball diamond diagram** shows each position filled with the
  player's name + batting order number on an SVG field (outfield grass,
  clay warning track, chalk lines, bases).
- **Drag-and-drop** the grip handle on any row to reorder the batting
  order, or use the ↑ / ↓ buttons for one-slot moves.
- Assign positions (C/1B/2B/3B/SS/LF/CF/RF/DH) in the grid.
- **Autofill — current side or both.** Two buttons sit above the lineup
  tabs: **Autofill vs RHP / vs LHP** (current side only — useful for
  platoon tweaks) and **Autofill both** (both batting orders in one
  click). Both honor depth-chart priority first, then a contact / power
  / speed / defense score.
- **Live validation** — errors and warnings appear above the table as
  you edit, so you know the moment a lineup slot is invalid.
- **Ctrl+S** (or Cmd+S on macOS) saves. **Autosave** debounces every
  ~1.5 seconds; if you reload mid-edit, a "Restore unsaved changes"
  banner offers to reinstate the draft.

**Pitching Staff tab.** Eleven slots: **SP1–SP5**, **LR**, **MR1–MR3**,
**SU**, **CL**. The **Auto-fill** button seeds all 11 from the active
roster:

1. Rotation goes to the five highest-endurance starters (or relievers
   tagged `preferred_pitching_role="SP"`).
2. Bullpen fills in priority order **LR → CL → SU → MR1 → MR2 → MR3**.
3. LR / MR slots prefer high-endurance arms; CL / SU prefer
   low-endurance arms (closer favors anyone tagged
   `preferred_pitching_role="CL"`).
4. With a thin pool the helper still produces a usable LR / CL / SU
   before MR2 / MR3 get filled, falling back to starters if needed.

### Depth Chart

Ordered priority list per defensive position (up to three per slot for
C/SS/CF/3B/2B/1B/LF/RF/DH).

- Top entry is the primary starter. Entries 2 and 3 back-fill when the
  starter is injured, rested, or promoted.
- Used by **Autofill** in the Lineup editor and by the injury
  replacement engine during sim.
- **Auto-generate** button seeds every position with the best three
  available players from your roster — primary fits first, sorted by
  level (ACT before AAA / LOW) and overall rating. Saves the chart
  immediately on click; use it as a starting point or after a major
  roster shake-up. Tweak from there with the move buttons.
- **Live validation** fires as you edit (eligibility errors + low-depth
  warnings).
- **Ctrl+S** saves; **autosave** covers crashes.

### Training

100% allocator per side (hitters and pitchers).

- Every track has a 5% minimum. Save is disabled until both sides sum to
  exactly 100.
- **Reset to defaults** clears your team override and inherits the
  league-wide mix.
- Budgets (from Finance) scale training-camp intensity.
- **Ctrl+S** saves.

### Injuries

Three sections: DL, IR, day-to-day.

- DL tiers: 15-day and 45-day. Every row shows eligible-to-activate
  date, days remaining, and the minimum required before activation.
- **Activate** returns a player to ACT (blocked until the DL minimum is
  met).
- IR is open-ended — stash long-term injuries there to clear the active
  roster, then manually activate when ready.
- Every event writes to the news feed and transactions log.

### Notifications

Per-team rules engine that fires alerts during multi-day sims and can
optionally pause a Sim Day / Week / Month / To Draft run the moment a
flagged event occurs. Settings are stored at
`data/notifications/<team_id>.json`; history is appended to
`data/notifications/<team_id>.history.jsonl`.

#### Preferences tab

Each rule has three checkboxes plus an optional numeric threshold:

- **Enabled** – log the event to history.
- **Notify** – show a banner on the Season page after the sim batch
  finishes.
- **Stop sim** – break the multi-day sim loop the moment this rule
  fires. The Season page shows a warning banner with the rule title
  (e.g. *"Sim paused: Player on 15-day DL"*).
- **Threshold** – for streak / cash / horizon rules (losing-streak
  length, cash-low dollar floor, days-out window for the trade
  deadline).

Rules are grouped into seven categories:

- **Health & roster** – day-to-day, 15-day DL, 45-day DL, 60-day IR,
  season-ending, returned-from-injury, lineup-invalid, pitching-staff-
  incomplete, roster-cap violation.
- **Performance & milestones** – win/losing streak (configurable
  length), player milestone (no-hitter, perfect game, 50 HR, hitting
  streak — fed by the `special_event` + `record` news categories),
  division clinched, eliminated.
- **Transactions** – trade offer received, trade decided, watched FA
  signed elsewhere, contract expiring.
- **Calendar & deadlines** – trade deadline approaching, phase
  transition, All-Star break.
- **Finance** – cash low, payroll over luxury threshold, projected
  monthly net negative.
- **League & admin** – commissioner action required, schedule
  regenerated.
- **Draft** – draft approaching, draft results posted.

#### Defaults

Out of the box the four serious injury tiers (15-day DL, 45-day DL,
60-day IR, season-ending) all stop the sim — that's the most common
reason owners want to be interrupted. Day-to-day defaults to notify-only
so the AI can keep going. Edit any of these to match your style.

#### Recent events tab

The last ~100 notifications generated for this team, newest first, with
severity badge, sim date, and message. Use it to audit what the engine
has been firing on or to confirm a rule you just enabled is actually
catching events.

#### How it integrates with the sim

When `team_id` is on the bearer token, every `/season/simulate/*`
endpoint snapshots pre-day state, runs the day, then runs the engine.
News-based detectors parse `[injury]`, `[special_event]`, `[record]`,
`[change_request]`, `[trade]` lines emitted during the day. State-based
detectors check standings (streaks), `manager.phase` (transitions), and
`team_financials.json` (cash low). When any event has `stop_sim=true`
the loop breaks early, the response includes
`notifications: [...]` and `sim_stopped_reason: "..."`, and the Season
page surfaces the banner. DL/injury automation still runs the same day,
so the AI has already moved the player to the DL by the time you see
the alert.

### Finance

Team-level finance snapshot.

- **Cash on hand**, **debt**, **preset**, and whether financials are
  enabled for this league.
- **Payroll alerts card** — proactively warns when cash is running out,
  debt exceeds a year of projected revenue, projected monthly net goes
  negative, or financial sim is disabled. Alerts fire inline, before
  you have to run the Finance Stability sandbox.
- Revenue and expense totals by category; projected monthly values drive
  the budgets panel.
- Budget categories: training, scouting, development, facilities.
- Scrollable transactions log with the last N ledger entries.

### Team Settings

Team branding and strategy.

- **Primary / secondary colors** – hex inputs with a live swatch preview
  using your team abbreviation.
- **Stadium** – free-text input with autocomplete from the ballpark
  catalog; click the building icon to open the **full park browser**
  with field-diagram previews. Or visit **League → Ballparks** for a
  standalone browser.
- **Team strategy** – league default or a team-specific profile (Win
  Now, Development Focus, etc.). Steers automation decisions.
- **Auto-reassign** – inherit league default, or explicitly
  enable/disable automatic ACT/AAA/LOW balancing for this team.
- **Ctrl+S** saves.

---

## League

### Standings · Leaders · Stats

- **Standings** – division-grouped. Click a row for team detail.
- **Leaders** – top N per stat using MLB qualifier rules.
- **Stats** – full league hitters + pitchers + team totals.

### Players · Teams · Schedule

- **Players** – league-wide browser with filters.
- **Teams** – directory grouped by division; click for team detail.
- **Schedule** – league-wide calendar; played rows link to boxscores.

### Playoffs · History · Hall of Fame · Records · Ballparks

- **Playoffs** – current year bracket.
- **History** – archive of completed seasons.
- **Hall of Fame** – inductees + candidates. Admins can induct/remove.
- **Records** – league and per-team record book.
- **Ballparks** – standalone park catalog with field diagrams. Use to
  browse before picking a stadium from Team Settings.

---

## Transactions

### Free Agency

Browse unsigned players. Filter by position, role, and free-agents-only.
Click **Sign** and pick destination level (ACT / AAA / LOW) to commit.

### Trades

Three panes: pending offers involving your team, accepted/rejected
history, and the trade composer.

- **Propose Trade** – pick partner team; move players + draft picks
  between give/receive lists.
- **Accept / Reject / Withdraw** — act on any pending offer.
- **Admin controls** (admin-only) appear inline on pending trades:
  - **Veto** opens a modal where you enter a note shown to both owners
    and sets the trade status to `vetoed`.
  - **Force approve** bypasses validator errors (irreversible; use only
    for deliberate overrides).
  - **Approve** runs through the standard validator as an admin accept.

### Draft

- **Now** tab – live state, current pick, draft order.
- **History** tab – completed picks per year.
- **Admin** tab (admin-only):
  - **Initialize** – seeds draft state (worst-first order from season
    stats) for a given year.
  - **Generate pool** – writes a fresh amateur draft pool CSV.
  - **Manual pick** – commissioner override that assigns a player to
    the team on the clock.
  - **Reset** – deletes draft state + results CSV for a year.

### Submit Change Request

Owner-side bundler. After making roster / lineup / pitching / depth
edits, use this page to export a snapshot ZIP for commissioner review.

### Activity

Full transactions ledger — every sign, move, cut, trade, contract event,
finance posting. Filter by team and action type.

---

## Admin

### Commissioner

- **Quick-access grid** at the top surfaces the 10 most-used admin pages
  as card tiles (Command Center, Finance Queue, Change Requests,
  Offseason Flow, Reassign Players, Finance Stability, Exhibition Game,
  League Admin, Physics Tuning, Users).
- **Trade rules** – enabled, draft-pick trading, require commissioner
  approval, CPU cadence, max pick trade years.
- **Injury level** – global injury-frequency setting (consolidates the
  old PyQt injury settings dialog).
- **Finance card** – preset (off / simple / standard / MLB-like /
  custom) + enforcement mode (off / warn / block) + collapsible
  **Module levels** (10 finance modules: Owner Revenue / Market /
  Budgets / Expenses, GM Contracts / Payroll Rules / Arbitration /
  Free Agency / Roster Cost Enforcement / Finance AI) + collapsible
  **CPU finance AI tuning** (19 numeric knobs — star thresholds, salary
  share caps, arbitration raise %, FA avoidance bands). Editing any
  module or AI value flips the preset to **custom**.
- **Scouting card** – fog-of-war enable plus six pacing knobs (base
  monthly credits, finance-off pace multiplier, monthly decay, passive
  gain, max banked credits, auto spend cap). Works whether or not the
  finance system is enabled.
- **Strategy & auto-reassign** – league-default strategy profile and
  auto-reassign behavior, plus a scrollable per-team override table
  (mirrors PyQt's TeamStrategySettingsDialog).

### Command Center

League-wide attention dashboard. Cards by severity: injuries, pending
approvals, roster conflicts, deadlines, finance risks.

### Finance Queue · Change Requests

- **Finance Queue** – admin-approved decisions; "Apply approved" runs
  every approved row in one pass.
- **Change Requests** – owner-submitted ZIPs; approve/reject/requeue
  each with an admin note.

### Offseason Flow

- Overview card (ended → next year, contract counts, arbitration
  candidates, unsigned players).
- Checklist with status + completion timestamps; mark individual stages
  done when handled manually.
- **Run pipeline** executes the full offseason rollover.
- **Review** card with four tabs (matches PyQt's offseason finance
  dialog):
    - **Contracts** – every contract expiring next year (player, team,
      years left, salary, service days, arb-eligible flag).
    - **Arbitration** – filed arbitration awards with old → new salary
      and delta.
    - **Budgets** – year-over-year budget delta per team with category
      breakdown (training / scouting / development / facilities).
    - **GM Queue** – pending owner finance decisions with team / queue /
      status / search filters and inline **Approve** / **Reject**
      buttons for the selected pending row.
- **Finance Queue inline** – pending count + Apply-all button, deep-
  links to the standalone Finance Queue page.

### Reassign Players

Admin bulk auto-assign.

- **Reassign all teams** – league-wide.
- **Single team reassign** – one team via dropdown.

### Finance Stability

Sandboxed multi-season finance tester.

- Inputs: seasons, seed, preset.
- **Run single preset** — full N-season sim against a temp copy of the
  data tree. Shows per-season metrics + guardrails pass/fail.
- **Compare presets** — run the same scenario against multiple presets.

### Exhibition Game

One-off game simulation outside the schedule.

- Pick home + away teams from dropdowns. Teams use their saved rosters
  and lineups.
- **Simulate** runs the game; live boxscore appears below with batting +
  pitching lines for both teams plus a strategy log (collapsed) and
  field positions (collapsed).
- Full HTML boxscore is saved under `data/exhibition_boxscores/`.

### League Admin

Destructive commissioner actions, each double-confirmed:

- **Regenerate schedule** — picks a template, overwrites `schedule.csv`.
- **Reset season stats** — wipes `season_stats.json`.
- **Clear played results** — marks every scheduled game as unplayed
  without regenerating the matchups.
- **Repair lineups** — runs lineup autofill + roster backfill across
  every team.
- **Clone league** — deep-copies the active league into a new registry
  entry. Use before risky experiments.

### Physics Tuning

Every engine knob in five sections (Run Environment, Plate Discipline,
Contact & Batted Ball, Pitching & Fatigue, Defense & Running). Per-knob
reset + global Reset all.

### Users

users.txt manager. Create admin or owner accounts with team assignment.

### New League

Same wizard as first-run. Use to create a second league.

### Utilities

- **AI Renderer Status** — shows whether OpenAI's `gpt-image-1` is
  configured; paste an API key to enable detailed logos/avatars.
- **Logos** — Detailed (AI) or Simple (fallback vector) generators.
- **Avatars** — batch player avatars.
- **Exports** — CSV / HTML reports, almanac, owner snapshot zip.

---

## Validation & autosave

Every edit-heavy page (Lineup, Depth Chart, Roster moves, Trades)
validates via a shared Python validator both at save time (as a hard
422) and live as you edit (inline warning/error lists).

**Lineup checks** — 9 slots filled, no duplicate players, every defensive
position covered once, pitcher-not-in-lineup, position eligibility.

**Depth chart checks** — max 3 per position, no duplicates, no pitchers,
position eligibility, off-roster rejection, low-depth warnings.

**Roster move checks** — level caps (ACT 25 / AAA 15 / LOW 10), LOW age
gate (27+), post-move minimum 11 non-pitchers on ACT, defensive coverage.

**Trade checks** — each side ≥1 asset, draft-pick trading enabled,
picks in tradable pool, post-trade caps, payroll policy.

**Autosave** — any editor with an unsaved-changes state persists to
localStorage every ~1.5 seconds. Reload the app and you'll see a
"Restore unsaved changes from a previous session" banner with
**Restore** / **Dismiss** buttons plus the autosave timestamp.

---

## Tips & keyboard shortcuts

- **Ctrl+S / Cmd+S** — Save (Lineup, Pitching, Depth Chart, Training,
  Team Settings). Disabled when nothing is unsaved.
- **Ctrl+K / Cmd+K** — Open the command palette to jump to any page by
  name without clicking through the sidebar.
- **Alt+/** — Jump to Help & Tutorials from anywhere.
- **Right-click** on roster rows — context menu with Open profile,
  Training focus, move/cut actions.
- **Right-click** on hub cards or sidebar entries — Pin to / unpin from
  Favorites.
- **Grip handle** (⋮⋮) on lineup rows — drag to reorder.
- **Esc** — closes dialogs + the park browser.
- **Ctrl+Shift+I** — opens DevTools in dev mode.
- Click any player name anywhere in the UI to open their profile.
- The **chevron** at the top of the sidebar collapses the rail to a
  56-px icon strip; hover any icon for its label.

---

## Help & tutorials

- **Sidebar footer** and **header question-mark icon** both open the
  Help page.
- **Manual tab** — renders this guide with a sticky table of contents
  and a live keyword search.
- **Tutorials tab** — multi-step walkthroughs covering every major
  flow (Dashboard, Season, Roster & Depth, Lineup, Training, Injuries,
  Free Agency, Trades, Draft, Team Settings, Finance, Submit Change
  Request, League Hub, Command Center, Admin Tools, Exhibition, League
  Admin, Keyboard Shortcuts, Player Avatars, Team Logos,
  **Notifications & Stop-Sim Rules**, **Navigation: Hubs &
  Breadcrumbs**). Click a card to launch the tutorial as a step-through
  dialog.
- **Legacy manuals tab** — the three PyQt-era HTML manuals (game,
  finance system, installer) open in a new window.

---

## Troubleshooting

**Blank screen after login.** Open DevTools (Ctrl+Shift+I) and check the
Console for a red error. The sidecar logs live in the terminal running
`npm run dev`.

**Sidecar exited before handshake.** Your Python environment is missing
a dependency. Check the terminal for the traceback. Set
`NEXGEN_PYTHON=<path to python.exe>` to force a specific interpreter.

**"Admin role required" on an admin page.** Log in as admin, or
elevate via the **Elevate to admin** card on the Utilities page.

**Changes don't persist.** If the server returns 422, you'll see the
validation error list inline. Fix the listed errors and re-save.

**First-run loop.** If `/leagues/first-run` returns `has_leagues: true`
but no league is active, navigate to `/select-league` and pick one.

**PyQt and Electron showing different data.** Both apps read/write the
same data root but cache inside their own process. Restart one after
the other makes a significant change for a fully consistent view.
