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
5. [League](#league) — Standings · Leaders · Stats · Players · Awards · Teams · Schedule · Playoffs · History · Hall of Fame · Records · Ballparks
6. [Transactions](#transactions) — Free Agency · Trades · Draft · Activity
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
- **Manage** a league *(commissioners)* — the Members & Email page.

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

On the Review step, **Your team** picks the club you will run yourself, or
*None* to run the league without one (you can claim or change a club later on
the Members & Email page).

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
- **My Team** *(hub)* — Roster, Pitchers, Position Players, Lineup, Depth
  Chart, Training, Injuries, Notifications, Team Stats, Finance, Contracts,
  Schedule, Team Settings.
- **League** *(hub)* — Standings, Leaders, Stats, Players, Teams, Schedule,
  Playoffs, History, Hall of Fame, Awards, All-Star Game, Records, Ballparks,
  Contracts.
- **Transactions** *(hub)* — Free Agency, Trades, Draft, Activity.
- **Admin** *(hub, commissioner-only)* — Commissioner, Members & Email, Command
  Center, Finance Queue, Exhibition Game, Offseason Flow, Reassign Players,
  Finance Stability, League Admin, Physics Tuning, New League, Users,
  Utilities.
- **Notifications** — top-level because it's how owners pause a sim.
- **Utilities** — top-level too, so owners can reach the avatar, logo and
  export tools.

**Hubs** are card grids of every page in a category; capability-gated cards
auto-hide (Finance pages need finance enabled, some pages need multi-owner,
etc.). **Breadcrumbs** in each header (e.g. `Home / My Team / Roster`) jump up a
level. The **chevron** at the top of the sidebar collapses it to an icon strip;
**section chevrons** collapse individual groups. Favorites and collapse states
persist in your browser. A thin **team-color stripe** marks team-specific pages.

---

## Today

### Dashboard

The home screen for a team.

- **Spotlight** — first by default: what needs your club this phase.
  Free-agent bidding (when bids are due, the players you lead and the ones
  you've been outbid on), the amateur draft (when it opens, your next pick,
  when you're on the clock), players in the final year of their contracts
  (and who has broken off talks or won't negotiate), qualifying-offer
  decisions, who left your club at the rollover and the spots still to
  fill, trade offers, injured-list returns, a club with no healthy catcher
  on its active roster, and lineup or depth-chart players who are no longer
  on the active roster. Each item has a button to the page that fixes it.
  When nothing needs you it shrinks to one line ("Spotlight: nothing needs
  you right now.").
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
- If the commissioner sets the league to draft in the **preseason**
  (Commissioner → Amateur draft timing), the draft opens when you advance out
  of the Offseason instead, before spring training. Spring training (**Run
  Training Camp**) follows the last pick, and that season has no draft pause
  in July. A new league that drafts in the preseason has no draft in its
  first season; its first draft opens the following preseason.
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
- **Columns** menu (8.10.0): tick a rating to show it, untick to hide it;
  pitchers can show every pitch (fastball, slider, changeup, curveball,
  sinker, screwball, knuckleball). Each table remembers your choice on this
  device, hitters and pitchers separately, and **Reset to default** brings
  back the standard set. The same menu is on the Free Agency, Players,
  Position Players, Pitchers and Lineup tables.
- **Right-click any row** (or the three-dot button) for: Open profile, Training
  focus…, Move to Active, Send to AAA / Low-A, Release / Cut. Injured-list moves
  live on the Injury Center page (see below), which starts the stint properly
  and promotes a replacement.
- **Cut** confirms, then writes a release transaction.
- Click a player's name to open their profile (which includes a large avatar).

Pitcher SP/RP labeling reflects each pitcher's display role; granular roles
(SP, RP, CL, LR, MR, SU) collapse to SP/RP here and drive the Lineup → Pitching
Staff editor.

#### Roster limits

- **Active roster: up to 26 players, at most 13 of them pitchers.** From
  September 1 to the end of the regular season the limits are 28 and 14. When
  the playoffs begin, extra players and pitchers above 13 are optioned to AAA
  automatically (owner teams included, logged in Transactions; nobody is
  released).
- **AAA 15, Low-A 10.** The organisation (active + AAA + Low-A) holds up to
  51; injured-list players don't count.
- There is no minimum. An active roster of 25 is legal; the page shows a
  **spot is open** badge next to the active count (for example 25/26), and
  the Season page lists it under *Needs your attention*. Fill it by promoting
  from AAA or signing a free agent, or leave it open. Nothing is moved for
  you.
- Moving into a full level, or adding a 14th active pitcher, is allowed with a
  warning toast. The **compliance banner** then shows the counts (ACT, AAA,
  LOW, P n/13, H n) and the season check won't sim until the roster is legal.
  **Auto-assign → Fill gaps only** fixes an extra pitcher by optioning one to
  AAA; **Full reassign** targets 13 pitchers and 13 position players.
- CPU clubs fill and balance their own rosters (13 pitchers / 13 position
  players). The CPU never rearranges an owner's team except for the September
  cut-back and emergency call-ups from your own minor leaguers when you can't
  field nine position players.
- **Before Opening Day.** In the offseason and preseason a banner at the top
  of the page shows what to fill: the counts (ACT, P, position players, Org),
  any position nobody plays, and anything that must be fixed before the
  season can start ("Roster not ready for Opening Day"). An open spot alone
  is optional. The banner also lists who left your club at the rollover:
  who retired, and whose contract expired (each links to his page, where you
  can make him an offer). The CPU never signs players for your club.

The **26-Man Active Roster** tutorial (Help → Tutorials) walks through the same
rules.

#### Retirements

Players retire at the season rollover, and owners' players can retire too.
The page lists who left your club at the rollover (the banner above), and the
dashboard Spotlight and your rollover notice name them as well.

- **Age comes first.** Hardly anyone retires before 31. The yearly chance
  climbs from there to about half at 39 and nearly everyone by 45.
- **Better players last longer.** Each player is compared with the others at
  his level in your league. A top player is far less likely to retire than an
  average one, and a fringe player far more. A star can still play into his
  40s, and a fading bench player usually goes in his mid-30s.
- **The minors age faster.** A 30-year-old still in AAA is treated like a
  34-year-old big leaguer, and a Low-A player past 25 is near the end.
- **A longer contract helps a little.** A big leaguer with more than the
  coming season left on his deal is a bit less likely to walk away.
- **Unsigned free agents retire too.** A veteran nobody signs usually hangs it
  up. A player who went a whole season unsigned often quits at any age. A
  player whose contract has only just run out is judged by his age alone.
- The outcome for each player is fixed for that season, so running the same
  rollover again gives the same retirements.
- **You get a warning (8.7.1).** A player with a real chance of retiring at the
  coming rollover shows a **May retire** badge on the Roster page (about a 30%
  chance or more) or **Retiring?** (50% or more), and the same note on his
  player page. It is a likelihood, never the decision itself: a player marked
  "likely" can play on, and one with no badge can still retire. A walk-year
  player is judged as if he re-signs; if he reaches free agency his chance is
  higher.

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

**Pitching Staff** has 11 required slots (SP1–SP5, LR, MR1–MR3, SU, CL) and
two optional ones, **MR4** and **MR5**, for the 12th and 13th active arms. The
badge reads *Filled 11/11 + N optional*. **Auto-fill** seeds the staff from
the active roster by endurance and role tags, filling MR4/MR5 while pitchers
remain. An active pitcher without a slot is listed as an **unslotted
reliever**: he still pitches out of the bullpen as an extra middle reliever.
Older staffs are left as they are; a label that is not a slot (a plain "MR")
or a slot listed twice only warns.

**Drag and drop (8.10.0).** Drag a pitcher by his handle onto another role,
or from the **Eligible pitchers** list below the staff; dropping on a filled
role swaps the two. The pitcher dropdown swaps too: a pitcher who already
holds a role is not greyed out but marked, for example, "(swap with SP2)".
The Eligible hitters / Eligible pitchers lists have the **Columns** menu.

**When a player leaves your club** (traded, released, contract expired,
retired) he is taken off its lineups, depth chart and pitching staff at once.
His lineup spot goes to the best active player who can play the position
(the rest of the batting order is kept; if nobody can, that lineup is
rebuilt by auto-fill), his staff role is left open, and you get a news item
naming who took each spot. Moves within your organization (sent down,
injured list) change nothing.

### Depth Chart

Ordered priority list per position (up to three each). The top entry starts;
2 and 3 back-fill on injury/rest/promotion. **Auto-generate** seeds the best
three per position. Drives Lineup autofill and the injury-replacement engine.
A depth chart the sim generated is rebuilt each sim day, so signings, trades
and call-ups reach it; a depth chart you saved is never changed for you.
Each player shows his key ratings, and clicking his name opens a card with
every rating and a link to his player page (8.7.3). Live validation + Ctrl+S.

### Training

100% allocator per side (hitters / pitchers), 5% per-track minimum; save is
disabled until both sides total 100. **Reset to defaults** inherits the league
mix. Ctrl+S.

### Injuries

Three sections — the injured list, the 60-day injured list, and day-to-day
players who are still on the active roster.

The lists follow MLB: **10 days** for position players, **15 days** for pitchers,
and a **60-day** list for long-term injuries. A minimum is a floor, not a
recovery time — a six-week hamstring keeps a player out six weeks even on the
10-day list.

Stints are counted in **league days, not real-world days**: the clock advances as
you play games, so simulating a month moves an injured player a month closer to
returning, and leaving the league idle for a week moves nobody.

Each row shows the eligible-to-activate date and days remaining. **Place on IL**
moves an injured active-roster player onto a list and opens a roster spot;
**Activate** brings him back once his stint is up, and if your depth chart lists
him first at his position he goes straight back into the lineup there. If the
active roster is full, option someone down on the Roster page first.

By default the sim activates players automatically the moment they are eligible.
A commissioner can hand that decision to the owners from the Season page; the
CPU still runs its own clubs either way, and anyone left waiting is activated
when the owner deadline passes. Every event writes to news + transactions.

### Notifications

Per-team rules engine that fires alerts during multi-day sims and can **pause
the sim** when a flagged event occurs.

- **Preferences tab** — each rule has *Enabled* (log), *Notify* (banner after
  the batch), *Stop sim* (break the loop immediately), and an optional
  *threshold*. Rules are grouped into Health & roster, Performance & milestones,
  Transactions, Calendar & deadlines, Finance, League & admin, and Draft.
- **Defaults** — only serious events stop the sim: 60-day IL placements,
  season-ending injuries, an invalid lineup and a roster over the limit.
  Day-to-day knocks, 10/15-day IL placements and a pitching staff with an
  empty slot are notify-only. Owners who changed a rule keep their choice.
- **Recent events tab** — the last ~100 notifications for your team.
- **Private to your club** (8.8.2). A club's notification history and alert
  settings can be read only by its owner and the commissioner (the history
  names the free agents you bid on and your offers). The page always shows
  an owner their own club's, even after browsing to another team.

During a sim each day is run, then the engine checks news-based detectors
(injuries, milestones, trades) and state-based detectors
(streaks, phase transitions, low cash). The lineup, pitching-staff and
roster-limit checks run on the first day of a sim, on a phase change and on
days with injury or roster news for the team; each problem is reported once.
A stop-rule breaks the loop early and the Season page shows the reason.

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
  arbitration-eligible after about 3 seasons of big-league service.
  **Service time** (8.5.1) belongs to the player: every played regular-season
  date credits everyone on an active roster or injured list, and the rollover
  turns the season into days (a full season is 172). A new league credits its
  opening-day big leaguers for the careers they had before the league.
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
FA year, and service time (years + days). **My team** and **Expiring** are
separate toggles (turn both on to find your walk-year players); filter by
name/team/position, and sort any column. Hover the
status badges — **Expiring**, **Arb-eligible**, **options**, **Non-gtd** — for
a plain-language explanation of what each means.

On the **advanced** contracts model (Standard / MLB-Like), a player's **profile
page** gains an **Owner actions** section on the Contract card for players you
own: **Exercise / Decline** a pending contract option (a declined option's
buyout hits your cash), and **Renew** a pre-arbitration player's salary for next
year (pre-arb players don't negotiate, so you set the figure, floored at the
league minimum). Contract **extensions** are also negotiated from the profile.
All owner finance actions are **owner-or-commissioner only** (enforced server-side).

**Extension talks (8.5.0).** On a player you own, the Contract card's
**Negotiate** button opens the talks. He names an asking price for the years
you offer (his free-agent market value, less a little for a long deal), and
that ask sits above what he will really take; the dialog never says how he
would answer a figure. An offer he accepts signs him. Below that he comes down
a little and loses patience, and a lowball costs more and doesn't move him.
Out of patience, he breaks off talks for a while (counted in window days during
the offseason free-agency window), and you get a news item and a notification.
In the season a walk-year veteran may refuse to negotiate and plan to test free
agency. The dialog also says when his big-league record raises or lowers his
price (8.9.0). CPU clubs extend the walk-year players they want to keep under
the same rules, and each extension is a news item.

### Team Settings

- **Primary / secondary colors** — hex inputs with a live swatch preview.
- **Stadium** — autocomplete from the ballpark catalog; the building icon opens
  the full park browser.
- **Team strategy** — league default or a profile (Win Now, Development Focus…).
- **Auto-reassign** — inherit league default or set per-team. Ctrl+S.
- **Game day** — four owner choices, each Default / On / Off, applied from
  the next game: **Auto rest days** (default on; the sim sits worn-down
  regulars at game time without changing the saved lineup), **Rest
  substitutes at similar positions** (default on; at most one per game),
  **Activate automatically from the 10/15-day IL** (default follows the
  league's IL setting) and **from the 60-day IL** (default off). A returner
  with no room goes to AAA with a "ready, make room" item; nobody else is
  moved. CPU-run clubs ignore these choices.

---

## League

- **Standings / Leaders / Stats** — division standings (rows link to team
  detail), top-N leaders by MLB qualifier rules, full league + team stats.
  Leaders has a **Regular season / Postseason** switch with a year picker once
  a postseason has been played.
- **Players / Teams / Schedule** — league-wide player browser with filters, team
  directory by division, and the schedule (played rows link to boxscores).
  The Players browser has the **Columns** menu; retired players show as
  **Retired** (with **Hide retired**), a player under contract with no roster
  spot shows under his club as **No spot**, and **Free agents only** lists
  exactly the players on the Free Agency page.
- **Awards** — each season's winners, chosen when the regular season ends;
  a league split into two leagues gives one of each per league. **MVP** (best
  OPS) and **Cy Young** (best ERA) among qualified players; a **Gold Glove**
  at each position (P, C, 1B, 2B, 3B, SS, LF, CF, RF), mostly by fielding
  ratings and adjusted by the season's fielding numbers (fielding pct; range
  factor except catchers and pitchers; passed balls for catchers; outfield
  assists), with games in half the club's games; a **Silver Slugger** for
  the best OPS at each position (three outfielders and a DH), with 2 plate
  appearances per team game. A player is judged at the position he started
  at most. Each award also shows on the winner's page (Career ledger → Awards).
- **Postseason stats.** A player's profile has a **Postseason** table under
  his regular stats, and a club's page shows its postseason history (record,
  each series, its best hitters and pitchers of the run). Playoff games never
  count in the regular-season totals.
- **Playoffs / History / Hall of Fame / Records / Ballparks** — current bracket,
  completed-season archive, HOF inductees (admins induct/remove), the record
  book, and the standalone park catalog with field diagrams.

---

## Transactions

- **Free Agency** — browse unsigned players; **Sign** and pick a destination
  level (ACT / AAA / LOW). The offer dialog shows **His position** (his
  asking price for the years you enter, and the length he **Wants**; on the
  older rules a **Market estimate**), competing bids, and — with payroll
  rules on — a live **"Your team's books"** panel: payroll before → after vs
  the luxury threshold, estimated tax, cash remaining after the signing
  bonus, and an Opening Day solvency flag.
  - **The list.** A **Ratings / Stats** switch (remembered per browser):
    Stats shows each player's most recent season. The list has an **Age**
    column, every column sorts, the **Columns** menu picks the ratings shown
    (every pitch included), and an injured free agent carries an **Injured**
    badge with the injury and expected return. Qualifying-offer decisions
    waiting on you appear at the top of the page.
  - **What he asks for (8.9.0).** His ratings and his big-league record
    (last three seasons, the latest counting most: OPS+ for hitters, ERA
    and FIP for pitchers, each against that season's league). For a
    full-time regular the record counts as much as the ratings, less for a
    part-timer, not at all without big-league time. The offer and
    extension dialogs say when his record moves his price by 5% or more.
  - **How a player decides (8.8.0).** On his decision day he signs the biggest
    total (salary × years + bonus) among the offers he would take; an offer at
    or above his ask for that length is one he takes, below it may not be, and
    a player 33 or older won't sign for more than a year past the length he
    wants. Outside the bidding window the offer dialog says which of those
    your terms are; while bidding is open it doesn't (8.8.1): he answers on
    his decision day, and other clubs can still beat an offer he'd take.
  - **Your negotiations** shows each bid's position, where it stands
    (**Leading**, **Outbid**, **Below his ask**, **Too long**, **He won't
    sign**), his ask for your length, the best other offer he'd take and the
    day he decides. A CPU offer that takes the lead can't sign him the same
    day (you get a day to answer), and CPU clubs don't bid on the day that
    decides him. Owners who bid get a notification when he signs, with whom
    and for what. **Still need** chips list the positions nobody on your
    active roster plays (with your open bids there) and filter the list.
  - **Every negotiation settles inside the bidding window (8.9.1).** On the
    window's last day each player still being negotiated signs the best
    offer he would take, or takes no deal and stays a free agent. If one
    can't be settled yet, bidding stays open on the last day (the day's news
    says how many players are left) and the next advance settles them; the
    league can't leave the offseason while one is still open. An offer made
    after the window closes is an ordinary negotiation, decided as in the
    season.
- **Trades** — pending offers, history, and the composer. Both sides are
  searchable lists of the real rosters (position, name, overall stars, age,
  injury flag), with draft picks in a multi-select below — no player ids to look
  up. Against a CPU team a red→orange→yellow→green bar shows how likely they are
  to accept, with the reasons, and updates live as you change the offer;
  **Compare** puts the two sides side by side. Owners accept/reject/withdraw;
  commissioners can **Veto**, **Force approve**, or **Approve**.
- **Draft** — **Now** (live state/order), **History** (completed picks), **My
  Board** (owners), and an **Admin** tab (Initialize, Generate pool, Manual pick,
  Reset).
  - **My Board** (8.7.0) is the owner's private draft board: who to take when a
    pick is made for the club (the pick clock ran out, the commissioner
    auto-picked or finished the draft, or the owner's own Auto-pick). Star a
    prospect in the draft class list to add him; drag to rank. Each row shows
    his key ratings, and clicking a name (on the board or in the draft class
    list) opens a card with every rating (8.7.2). Per player a
    private note, *not before round N* and a group (only one of a group is
    taken). Rules: *at most N* per position (IF, OF and P cover families),
    *at least N at a position by round R*, optional tiers (equal players: the
    one filling a need, then the best overall), and what to take when nobody on
    the list can be taken. **Auto-draft** can pick the moment the club is up,
    from the list only or for every remaining pick. The top of the tab shows what
    the board would take right now and why; picks it made are listed with their
    reasons, and the owner gets a notification. Nobody else can see a board, the
    commissioner included; picks it makes show a **board** tag.
  - **No board? The CPU picks by need (8.11.0).** When a pick is made for an
    owner's club that has no board (its clock ran out, the commissioner
    picked or finished the draft for it, or the owner pressed **Auto-pick**), it is made the way CPU clubs draft: the best player
    available, with a little extra weight on a position where the
    organization is thin until the club drafts one, so a needed player close
    to the best one left is taken, never one far down the class. No position
    piles up in one draft. The owner's notification says why (for example
    "your organization is short at C"), and a commissioner's Auto-pick for an
    owner's club always notifies the owner. A pick the clock made shows an
    **auto** tag. A board, when the club has one, still decides.
  - **Discord (8.6.6).** The "on the clock" post and every pick (round, pick,
    club, player and position) go to the Discord draft channel (the main
    channel when no draft channel is set up). A run of CPU picks is one
    combined post, and the last pick says the draft is over. A post only says
    that a pick came from a draft board, never what is on it.
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
- **Members & Email** — invites, emailing the league's owners, join requests
  and team assignment; also linked from the Commissioner page's quick links
  and from **Utilities** (see
  [Accounts, leagues & membership](#accounts-leagues--membership)).
- **Command Center** — league-wide attention dashboard (injuries, pending
  approvals, roster conflicts, deadlines, finance risks).
- **Finance Queue** — review pending GM decisions with player
  names, plain-language actions, and salary movement; **Apply approved** shows
  a confirmation summary of exactly what will be committed (irreversible).
- **Offseason Flow** — overview, checklist, **Run pipeline**, and a four-tab
  review (Contracts, Arbitration, Budgets, GM Queue). The overview's **Arb
  candidates** count is exactly who the rollover will take to arbitration; it
  reads **Off** when the league doesn't run arbitration and drops to 0 once
  the offseason workflow has run (8.7.4).
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

Commissioners have a **Refresh picture** button on the player profile's
avatar (8.3.0): it redoes the picture in his current club's colors, keeping
the same face. This also happens on its own when a player is traded or signs
with a new club, and when a club changes its colors in Team Settings.

---

## Logos & avatars

Team logos and player avatars are generated by Google **Vertex AI** in the
cloud (no API key needed) —
admin-only, under **Utilities**.

- **AI Renderer Status** — shows whether Vertex AI (cloud) and/or OpenAI
  (local) are ready.
- **Team logos:**
  - **Detailed Logos** — AI mascot logos: a unique, mascot-forward emblem per
    team in the team's colors. (Cheap; the whole league regenerates at once.)
  - **Simple Logos** — built-in vector fallback, no network.
  - **Tighten logo framing** — *no AI*: trims the background margin off existing
    logos so every team's mascot fills the frame consistently.
- **Player avatars:**
  - **Fill missing / template avatars (AI)** — a unique AI portrait per player
    (built from their ethnicity / skin / hair / facial-hair + team colors), only
    for players without one or still showing a template. Generated once and
    reused.
  - **Fill one team's avatars (AI)** — the same for a single team (about 25-30
    players, a few minutes, saved as it goes); safest for large leagues.
  - **Regenerate all avatars (AI)** — wipes and regenerates the whole league
    (slower, bills per image).
  - **Simple avatars (templates)** — free, instant template recolor (faces
    repeat by ethnicity).
  - **Per-player regenerate** *(super-admin)* — a small refresh button on the
    avatar on any player profile, to spot-check the look before a full run.
- **Exports** — **Export Reports (HTML)**, **Export Reports (CSV)** and
  **Export Almanac**.

Generated images are saved to durable storage, so they persist across sessions.

---

## Validation & autosave

Edit-heavy pages (Lineup, Depth Chart, Roster moves, Trades) validate both at
save time (a hard 422 with an inline error list) and live as you edit:

- **Lineup** — 9 slots filled, no duplicates, every position covered once,
  pitcher-not-in-lineup, position eligibility.
- **Depth chart** — max 3 per position, no duplicates, no pitchers, eligibility,
  off-roster rejection, low-depth warnings.
- **Roster moves** — level caps (ACT 26, or 28 from September 1; AAA 15; LOW
  10) and at most 13 active pitchers (14 in September) are warnings on a single
  move and errors at the season check; LOW age gate (27+) is a hard error;
  minimum 11 position players on ACT and defensive coverage are checked before
  every game.
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
- **Grip handle** on lineup rows — drag to reorder; on pitching-staff rows —
  drag onto another role to move or swap.
- **Esc** — close dialogs and the park browser.
- Click any player name anywhere to open their profile.
- **Ctrl+Shift+R** — hard-refresh (use after an update if something looks stale).

---

## Help & tutorials

- The **header question-mark icon** and the sidebar footer open this Help page.
- **Manual tab** — this guide, with a sticky table of contents and live keyword
  search.
- **Tutorials tab** — step-through walkthroughs for the major flows.
- **Legacy manuals tab** — the older HTML game and finance manuals. These
  describe the retired desktop build and are kept for reference only.

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
without a team. You can change this later from the Members & Email page.
