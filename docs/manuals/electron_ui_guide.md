# NexGen-BBPro — UI Manual

A full reference for every screen in the NexGen-BBPro web app. The game runs
in your browser — there's nothing to install. Open
**https://nexgen-bbpro.firebaseapp.com**, sign in, and you're playing.

Your role in a league is either **Commissioner** (runs the league — full admin
powers) or **Owner** (runs one team). A small number of platform owners are
**Super-admins**, who can manage every league. Most of this manual applies to
everyone; admin-only sections are marked.

---

## Contents

1. [Accounts, leagues & membership](#accounts-leagues--membership)
2. [Sidebar & navigation](#sidebar--navigation)
3. [Today](#today) — [Dashboard](#dashboard) · [Season](#season) · [News](#news)
4. [My Team](#my-team) — [Roster](#roster) · [Lineup](#lineup) · [Depth Chart](#depth-chart) · [Training](#training) · [Injuries](#injuries) · [Notifications](#notifications) · [Finance](#finance) · [Contracts](#contracts) · [Settings](#team-settings)
5. [League](#league) — Standings · Leaders · Stats · Players · Teams · Schedule · Playoffs · History · Hall of Fame · Records · Ballparks
6. [Transactions](#transactions) — Free Agency · Trades · Draft · Submit Change Request · Activity
7. [Admin (Commissioner)](#admin-commissioner)
8. [Platform admin (Super-admin)](#platform-admin-super-admin)
9. [Logos & avatars](#logos--avatars)
10. [Validation & autosave](#validation--autosave)
11. [Tips & keyboard shortcuts](#tips--keyboard-shortcuts)
12. [Help & tutorials](#help--tutorials)
13. [Troubleshooting](#troubleshooting)

---

## Accounts, leagues & membership

### Creating an account

On first visit you'll land on the sign-in screen. Choose **Sign up** and pick
how you want to play:

- **Commissioner** — create and run leagues, hand out invites, manage members.
  A commissioner can *also* run a team in their own league.
- **Owner** — join leagues and run a single team.

You can register with **email + password** or **Continue with Google**. You also
choose a **display name** (handle) that other members see. Passwords and Google
sign-in are handled by Firebase — the app never stores your password.

### My Leagues

After signing in you land on **My Leagues** — every league you belong to, with
your role and team. From here you can:

- **Create a league** *(commissioners)* — opens the league wizard (below).
- **Find a league** — the discovery screen to join one.
- **Enter** a league — jumps into its Dashboard.
- **Manage** a league *(commissioners)* — the members panel.

You can return to this screen anytime via the **My Leagues** button in the
header.

### Creating a league (commissioner)

The wizard walks a few steps: **Basics** (name, year), **Setup** (a Quick-Start
preset or custom divisions), **Teams** (the random-team generator seeds names —
click *Randomize* for new ones), and **Rules & Review**. You also set the
league's **visibility**:

- **Private** — hidden from discovery; only joinable with an invite code.
- **Public** — listed in *Find a league*; players without a code can request to
  join and you approve them.

On submit the league is created and appears in My Leagues.

### Inviting & admitting members (commissioner)

Open a league's **Manage** (members) panel to:

- **Generate invite codes** — share a code; whoever redeems it is admitted
  automatically. A code can be tied to a specific team or left open (you assign
  the team later).
- **Review join requests** — for public leagues, players who don't have a code
  request to join. **Approve** (and assign a team) or **Deny** each one.
- **Assign / reassign teams** — give a member a team, or move them.

### Joining a league (owner)

From **Find a league**:

- **Enter an invite code** — admits you immediately (private leagues require
  this; they're otherwise hidden).
- **Request to join a public league** — the commissioner approves you and
  assigns a team.

### Claiming a team

When you enter a league where you don't yet have a team, the Dashboard shows a
**"Claim your team"** screen — pick any open team to run it, or choose to keep
running the league as a pure commissioner with no team. You can claim or change
a team later from the members panel.

### Signing out / switching leagues

The header shows your handle and role. Use **My Leagues** to switch leagues and
the **sign-out** icon to log out.

---

## Sidebar & navigation

The sidebar has a handful of top-level destinations plus a pinned
**Help & Tutorials** link:

- **Today** — Dashboard, Season, News.
- **Favorites** — appears once you've pinned routes (right-click any sidebar
  entry or hub card → *Pin to sidebar*).
- **My Team** *(hub)* — Roster, Pitchers, Lineup, Depth Chart, Training,
  Injuries, Notifications, Finance, Team Settings.
- **League** *(hub)* — Standings, Leaders, Stats, Players, Teams, Schedule,
  Playoffs, History, Hall of Fame, Records, Ballparks.
- **Transactions** *(hub)* — Free Agency, Trades, Draft, Submit Request,
  Activity.
- **Admin** *(hub, commissioner-only)* — Commissioner, Command Center, Finance
  Queue, Change Requests, Members, Exhibition Game, Offseason Flow, Reassign
  Players, Finance Stability, League Admin, Physics Tuning, Utilities.
- **Notifications** — top-level because it's how owners pause a sim.

**Hubs** are card grids of every page in a category; capability-gated cards
auto-hide (Finance pages need finance enabled, Submit Request needs multi-owner,
etc.). **Breadcrumbs** in each header (e.g. `Home / My Team / Roster`) jump up a
level. The **chevron** at the top of the sidebar collapses it to an icon strip;
**section chevrons** collapse individual groups. Favorites and collapse states
persist in your browser. A thin **team-color stripe** marks team-specific pages.

---

## Today

### Dashboard

The home screen for a team.

- **Hero banner** — large team logo, city + name, record, run diff, streak as a
  scoreboard readout.
- **Stat cards** — run differential, streak, active roster size, next game; each
  links to the matching screen.
- **Division standings** — your division with your row highlighted; rows link to
  team detail.
- **Upcoming & Recent** — next five games and last five results; played rows
  link to the full boxscore.
- **Widgets** — bullpen readiness, next-game matchup scout, hot/cold performers,
  team batting + pitching leaders.

If you're a commissioner with no team claimed, the Dashboard instead shows the
**Claim your team** screen (or a "browsing as commissioner" banner once you skip
it).

### Season

The most-used sim page.

- Header shows current phase, sim date, days played / total, days remaining.
- **Sim Day / Week / Month** and a custom **N Days** field advance the sim in
  place. (Most leagues sim a whole day at a time.)
- **Sim to Draft / Sim to Playoffs** run to the next phase boundary, stopping
  cleanly if a required step blocks.
- **Advance Phase** is the deliberate step between phases. It's **only enabled
  when the phase is actually ready** to move on (schedule fully played, draft
  committed, or a champion crowned) and tells you why it's disabled.
- The amateur draft is a mid-season interruption: once it commits, the regular
  season **resumes automatically** — you don't advance out of the draft.
- Each new season's **schedule is generated automatically** when you advance
  into the new year; no manual regeneration.
- Simulate the **playoffs** from the Playoffs page (Sim Next Game / Sim Next
  Round / Sim to Champion). When a champion is crowned, Advance Phase unlocks
  the Offseason.
- When the finance system is on, a phase-aware **finance to-do** banner lists
  what your team needs to do this phase (budget, luxury threshold / cash,
  arbitration, qualifying offers).

### News

Chronological in-game events — roster moves, trades, injuries, milestones,
finance postings. Filter by team and category.

---

## My Team

### Roster

Tabular view of your roster, grouped by level (Active / AAA / Low / DL / IR).

- Columns: position, role, bats/throws, ratings (overall stars + role-specific).
- **Right-click any row** (or the three-dot button) for: Open profile, Training
  focus…, Move to Active, Send to AAA / Low-A, Place on DL (15), 60-day IR,
  Shift to 45-day DL, Release / Cut.
- **Cut** confirms, then writes a release transaction.
- Click a player's name to open their profile (which includes a large avatar).

Pitcher SP/RP labeling reflects each pitcher's display role; granular roles
(SP, RP, CL, LR, MR, SU) collapse to SP/RP here and drive the Lineup → Pitching
Staff editor.

### Lineup

Tabs for **vs LHP** and **vs RHP** (separate batting orders) plus a **Pitching
Staff** tab.

- A **baseball diamond diagram** shows each position filled.
- **Drag** the grip handle to reorder, or use ↑ / ↓.
- Assign positions in the grid.
- **Autofill** the current side or both; honors depth-chart priority then a
  contact/power/speed/defense score.
- **Live validation** flags invalid slots as you edit.
- **Ctrl+S** saves; autosave debounces ~1.5s and offers to restore unsaved
  changes after a reload.

**Pitching Staff** has 11 slots (SP1–SP5, LR, MR1–MR3, SU, CL); **Auto-fill**
seeds them from the active roster by endurance and role tags.

### Depth Chart

Ordered priority list per position (up to three each). The top entry starts;
2 and 3 back-fill on injury/rest/promotion. **Auto-generate** seeds the best
three per position. Drives Lineup autofill and the injury-replacement engine.
Live validation + Ctrl+S.

### Training

100% allocator per side (hitters / pitchers), 5% per-track minimum; save is
disabled until both sides total 100. **Reset to defaults** inherits the league
mix. Ctrl+S.

### Injuries

Three sections — DL (15- and 45-day), IR (open-ended), day-to-day. Each DL row
shows the eligible-to-activate date and minimum required. **Activate** returns a
player to ACT once eligible. Every event writes to news + transactions.

### Notifications

Per-team rules engine that fires alerts during multi-day sims and can **pause
the sim** when a flagged event occurs.

- **Preferences tab** — each rule has *Enabled* (log), *Notify* (banner after
  the batch), *Stop sim* (break the loop immediately), and an optional
  *threshold*. Rules are grouped into Health & roster, Performance & milestones,
  Transactions, Calendar & deadlines, Finance, League & admin, and Draft.
- **Defaults** — the serious injury tiers (15-day, 45-day, 60-day IR,
  season-ending) stop the sim; day-to-day is notify-only.
- **Recent events tab** — the last ~100 notifications for your team.

During a sim each day is run, then the engine checks news-based detectors
(injuries, milestones, trades, change requests) and state-based detectors
(streaks, phase transitions, low cash). A stop-rule breaks the loop early and
the Season page shows the reason.

### Finance

Team finance snapshot: cash on hand, debt, preset, whether financials are
enabled. A **payroll alerts** card warns proactively (low cash, high debt,
negative projected net). Revenue/expense by category, budget categories
(training / scouting / development / facilities), and a transactions log.

When payroll rules are on, a **Payroll vs Luxury Threshold** card sits at the
top: a meter of your payroll against the league **floor** and **luxury
threshold** with a zone badge (Safe / Over threshold / Under floor). It shows
your **headroom** before the tax kicks in, the **estimated tax or floor fee**
you'd pay at settlement (same math settlement charges), and whether you're
**solvent for Opening Day** (projected debt within the cap).

The finance system is **modular** — a commissioner enables exactly the pieces a
league wants (revenue, market, budgets, expenses, contracts, payroll rules,
arbitration, free agency, CPU AI) via a preset (Off / Simple / Standard /
MLB-Like) or per-module Custom levels.

- **Set your budgets**: when the **owner budgets** module is on (Simple and up),
  the **Budgets** card is editable — click **Edit**, set each category
  (training / scouting / development / facilities), and **Save budgets**. The
  projected figure is your revenue-based ceiling. On presets where budgets are
  off, the card is read-only.
- **Arbitration** (Standard / MLB-Like — off in Simple): an **Arbitration**
  panel lists your arbitration-eligible players with current vs projected salary;
  choose **Offer raise**, **Hold**, or **Non-tender** for each. Players become
  arbitration-eligible only after ~3 seasons of service, so new leagues show an
  empty panel.
- **Enforcement is On or Off** (no warn/block). When On, the rules behave
  MLB-style: during the season you may exceed the **luxury threshold** but you
  pay the **tax** (and a floor fee for underspending) — nothing is blocked
  mid-season. The hard gate is **Opening Day**: a team must be solvent
  (projected debt within the cap) to start the season.
- **Money actually moves**: draft-pick slot bonuses and free-agent signing
  bonuses debit your cash (and accrue debt if short); declined-option buyouts
  hit cash too. All of it posts to the ledger.
- **Qualifying offers** (offseason): tender a one-year QO to an eligible
  departing free agent, or let him walk, from the Free Agency page. A declined
  QO whose player signs elsewhere earns a **compensation draft pick** (an extra
  end-of-round-1 pick); the signing team forfeits a round-2 pick.
- A phase-aware **finance to-do** on the Season page surfaces what you need to
  do each phase, and finance notifications fire on phase changes (over the
  luxury threshold, projected negative net).

### Contracts

**My Team → Contracts** is the league-wide contract tracker: every active
contract with salary (plus total commitment for multi-year deals), years left,
FA year, and service time (years + days). Scope it to **All / My team /
Expiring**, filter by name/team/position, and sort any column. Hover the
status badges — **Expiring**, **Arb-eligible**, **options**, **Non-gtd** — for
a plain-language explanation of what each means.

On the **advanced** contracts model (Standard / MLB-Like), a player's **profile
page** gains an **Owner actions** section on the Contract card for players you
own: **Exercise / Decline** a pending contract option (a declined option's
buyout hits your cash), and **Renew** a pre-arbitration player's salary for next
year (pre-arb players don't negotiate, so you set the figure, floored at the
league minimum). Contract **extensions** are also negotiated from the profile.
All owner finance actions are **owner-or-commissioner only** (enforced server-side).

### Team Settings

- **Primary / secondary colors** — hex inputs with a live swatch preview.
- **Stadium** — autocomplete from the ballpark catalog; the building icon opens
  the full park browser.
- **Team strategy** — league default or a profile (Win Now, Development Focus…).
- **Auto-reassign** — inherit league default or set per-team. Ctrl+S.

---

## League

- **Standings / Leaders / Stats** — division standings (rows link to team
  detail), top-N leaders by MLB qualifier rules, full league + team stats.
- **Players / Teams / Schedule** — league-wide player browser with filters, team
  directory by division, and the schedule (played rows link to boxscores).
- **Playoffs / History / Hall of Fame / Records / Ballparks** — current bracket,
  completed-season archive, HOF inductees (admins induct/remove), the record
  book, and the standalone park catalog with field diagrams.

---

## Transactions

- **Free Agency** — browse unsigned players; **Sign** and pick a destination
  level (ACT / AAA / LOW). The offer dialog previews fair-market value,
  competing CPU bids, and — with payroll rules on — a live **"Your team's
  books"** panel: payroll before → after vs the luxury threshold, estimated
  tax, cash remaining after the signing bonus, and an Opening Day solvency
  flag.
- **Trades** — pending offers, history, and the composer (move players + picks
  between give/receive). Owners accept/reject/withdraw; commissioners can
  **Veto**, **Force approve**, or **Approve**.
- **Draft** — **Now** (live state/order), **History** (completed picks), and an
  **Admin** tab (Initialize, Generate pool, Manual pick, Reset).
- **Submit Change Request** — bundle your roster/lineup edits into a snapshot for
  commissioner review (multi-owner leagues).
- **Activity** — the full transactions ledger, filterable by team and type.

---

## Admin (Commissioner)

The **Commissioner** is the league's admin. These pages live under the Admin hub
and are hidden from owners.

- **Commissioner** — league rules in one place: trade rules, injury level,
  **Finance** (preset + enforcement + per-module levels — each dropdown
  explains what the selected level changes — + CPU finance-AI knobs),
  **Scouting** (fog-of-war + pacing), and league-default **strategy /
  auto-reassign** with a per-team override table.
- **Members** — invites, join requests, and team assignment (see
  [Accounts, leagues & membership](#accounts-leagues--membership)).
- **Command Center** — league-wide attention dashboard (injuries, pending
  approvals, roster conflicts, deadlines, finance risks).
- **Finance Queue / Change Requests** — review pending GM decisions with player
  names, plain-language actions, and salary movement; **Apply approved** shows
  a confirmation summary of exactly what will be committed (irreversible).
  Change Requests lists owner-submitted bundles with approve/reject/requeue.
- **Offseason Flow** — overview, checklist, **Run pipeline**, and a four-tab
  review (Contracts, Arbitration, Budgets, GM Queue).
- **Reassign Players** — bulk auto-assign, league-wide or single team.
- **Finance Stability** — sandboxed multi-season finance tester (single preset
  or compare presets) against a temp copy of the data.
- **Exhibition Game** — simulate a one-off game outside the schedule with a live
  boxscore.
- **League Admin** — destructive, double-confirmed actions: regenerate schedule,
  reset season stats, clear played results, repair lineups, clone league.
- **Physics Tuning** — every engine knob across five sections, with per-knob and
  global reset.
- **Utilities** — diagnostics, logo/avatar generation, and exports (see
  [Logos & avatars](#logos--avatars)).

---

## Platform admin (Super-admin)

A super-admin is a platform owner (set by the operator). In addition to full
commissioner powers in **every** league, a super-admin sees an **All leagues**
section on My Leagues with **Enter**, **Manage**, and **Delete** for any league.
**Delete** permanently removes a league and all of its data (with a
confirmation). Super-admins also get the per-player **regenerate avatar** button
on profile pages.

---

## Logos & avatars

Team logos and player avatars are generated by Google **Vertex AI Imagen** in
the cloud (no API key needed) — admin-only, under **Utilities**.

- **AI Renderer Status** — shows whether Vertex AI Imagen (cloud) and/or OpenAI
  (local) are ready.
- **Team logos:**
  - **Detailed Logos** — AI mascot logos: a unique, mascot-forward emblem per
    team in the team's colors. (Cheap; the whole league regenerates at once.)
  - **Simple Logos** — built-in vector fallback, no network.
  - **Tighten logo framing** — *no AI*: trims the background margin off existing
    logos so every team's mascot fills the frame consistently.
- **Player avatars:**
  - **Fill missing avatars (AI)** — a unique AI portrait per player (built from
    their ethnicity / skin / hair / facial-hair + team colors), only for players
    without one. Generated once and reused.
  - **Regenerate all avatars (AI)** — wipes and regenerates the whole league
    (slower, bills per image).
  - **Simple avatars (templates)** — free, instant template recolor (faces
    repeat by ethnicity).
  - **Per-player regenerate** *(super-admin)* — a small refresh button on the
    avatar on any player profile, to spot-check the look before a full run.
- **Exports** — CSV / HTML reports, almanac, owner snapshot zip.

Generated images are saved to durable storage, so they persist across sessions.

---

## Validation & autosave

Edit-heavy pages (Lineup, Depth Chart, Roster moves, Trades) validate both at
save time (a hard 422 with an inline error list) and live as you edit:

- **Lineup** — 9 slots filled, no duplicates, every position covered once,
  pitcher-not-in-lineup, position eligibility.
- **Depth chart** — max 3 per position, no duplicates, no pitchers, eligibility,
  off-roster rejection, low-depth warnings.
- **Roster moves** — level caps (ACT 25 / AAA 15 / LOW 10), LOW age gate (27+),
  post-move minimum non-pitchers on ACT, defensive coverage.
- **Trades** — each side ≥1 asset, pick-trading enabled, picks in the tradable
  pool, post-trade caps, payroll policy.

**Autosave** persists unsaved edits to your browser every ~1.5s; after a reload
a "Restore unsaved changes" banner offers to reinstate them.

---

## Tips & keyboard shortcuts

- **Ctrl+S / Cmd+S** — Save (Lineup, Pitching, Depth Chart, Training, Settings).
- **Ctrl+K / Cmd+K** — Command palette to jump to any page by name.
- **Alt+/** — Jump to Help & Tutorials.
- **Right-click** roster rows — context menu (profile, training, move/cut).
- **Right-click** hub cards or sidebar entries — pin/unpin Favorites.
- **Grip handle** on lineup rows — drag to reorder.
- **Esc** — close dialogs and the park browser.
- Click any player name anywhere to open their profile.
- **Ctrl+Shift+R** — hard-refresh (use after an update if something looks stale).

---

## Help & tutorials

- The **header question-mark icon** and the sidebar footer open this Help page.
- **Manual tab** — this guide, with a sticky table of contents and live keyword
  search.
- **Tutorials tab** — step-through walkthroughs for the major flows.
- **Legacy manuals tab** — the older HTML game / finance / installer manuals.

---

## Troubleshooting

**Use the right URL.** The app lives at
**https://nexgen-bbpro.firebaseapp.com**. Sign-in (especially Google) only works
from that address.

**Something looks stale or blank after an update.** Hard-refresh with
**Ctrl+Shift+R**. To see an error, open the browser console (**F12** →
*Console*).

**"Continue with Google" doesn't work.** Allow pop-ups for the site and retry;
make sure you're on the firebaseapp.com URL.

**The first action after a while is slow.** The server may be waking up — give it
a few seconds; subsequent actions are fast.

**"Admin / commissioner required."** That page is limited to the league's
commissioner (and super-admins). Owners won't see it.

**Changes don't persist.** If you see a validation error list, fix the listed
items and re-save — the server rejects invalid lineups/rosters/trades.

**I'm a commissioner but the Dashboard shows "Claim your team."** That's
expected if you haven't taken a team yet — claim one, or skip to run the league
without a team. You can change this later from the Members panel.
