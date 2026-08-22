"""Tutorial catalog — pure data, served to the React/Electron client by the
FastAPI sidecar.

Each tutorial is a list of ``TutorialStep`` objects with an HTML body.
The Electron renderer sanitizes with a narrow allowlist before display,
so only a small set of tags (p, b, i, em, strong, ul, ol, li, br, code,
a, span) is supported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class TutorialStep:
    title: str
    body_html: str


@dataclass(frozen=True)
class Tutorial:
    tutorial_id: str
    title: str
    summary: str
    steps: List[TutorialStep]
    # Route path this tutorial pairs with. Used by the first-visit
    # launcher in the Electron UI to auto-open a tutorial when the user
    # lands on the relevant page. ``None`` means "not route-linked"
    # (library-only tutorial).
    route: str | None = None


TUTORIALS: List[Tutorial] = [
    Tutorial(
        tutorial_id="overview",
        title="Dashboard Overview",
        summary="Tour the owner dashboard — hero, scoreboard stats, division, widgets.",
        route="/home",
        steps=[
            TutorialStep(
                "Hero & team logo",
                "<p>The hero banner at the top of <b>Dashboard</b> shows your team name, record, run differential, and current streak. The team logo is auto-generated or falls back to a colored square with your abbreviation. Record / Run Diff / Streak render as a stadium scoreboard readout — tabular monospace with an amber LED glow.</p>",
            ),
            TutorialStep(
                "Stat cards",
                "<p>Four cards sit under the hero: Run Diff, Streak, Next Game, Injuries. Each has a thin team-color stripe on the left, and scoreboard numerals for the value. Click a card to jump to the matching screen.</p>",
            ),
            TutorialStep(
                "Division standings",
                "<p>The left panel lists every team in your division with win–loss, games-back, streak, and last-10. Your row is highlighted with a soft team-color tint and stripe. Rows link to the team detail page.</p>",
            ),
            TutorialStep(
                "Upcoming & recent",
                "<p>The right column shows the next five games and last five results. Played rows link to the full HTML boxscore.</p>",
            ),
            TutorialStep(
                "Dashboard widgets",
                "<p>Below the fold: bullpen readiness, next-game matchup scout, hot/cold performers, and batting + pitching team leaders. All refresh as the sim date advances.</p>",
            ),
            TutorialStep(
                "Sidebar navigation",
                "<p>The sidebar shrinks to seven top-level destinations: <b>Today</b> (Dashboard / Season / News), four hub links (<b>My Team</b>, <b>League</b>, <b>Transactions</b>, <b>Admin</b>), <b>Notifications</b>, and <b>Help</b>. Click a hub to land on a card grid of every page in that category — capability-gated cards auto-hide. Right-click any sidebar entry or hub card to <b>Pin</b> it to a Favorites section, and use the chevron at the very top of the rail to collapse the sidebar to icons-only. See the <b>Navigation</b> tutorial for a full tour.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="season",
        title="Simulating Seasons",
        summary="Day-at-a-time sim flows: day, week, month, to-draft, to-playoffs.",
        route="/season",
        steps=[
            TutorialStep(
                "Open the Season page",
                "<p>Use <b>Today → Season</b> in the sidebar. The header shows the current phase (Preseason, Regular Season, Amateur Draft, Playoffs, or Offseason) and progress through the current year.</p>",
            ),
            TutorialStep(
                "Pick a sim range",
                "<p>Buttons cover <b>Sim Day</b>, <b>Sim Week</b>, <b>Sim Month</b>, a custom <b>N Days</b> field, <b>Sim to Draft</b>, and <b>Sim to Playoffs</b>. Each advances the shared season state.</p>",
            ),
            TutorialStep(
                "Phase transitions",
                "<p>Click <b>Advance Phase</b> to move on (Preseason → Regular Season → Amateur Draft mid-season → finish the schedule → Playoffs → Offseason). The button is only enabled when the phase is actually ready — the schedule is fully played, the draft is committed, or a champion has been crowned — so it never skips a stage. After the amateur draft commits, the regular season resumes automatically; you don't have to advance out of it.</p>",
            ),
            TutorialStep(
                "Schedules generate automatically",
                "<p>Each new season's schedule is created for you when you advance into the new year — no manual regeneration needed. The Season page shows the upcoming Draft Day and the next date to play.</p>",
            ),
            TutorialStep(
                "Simulating the playoffs",
                "<p>In the Playoffs phase, open the <b>Playoffs</b> page and use <b>Sim Next Game</b>, <b>Sim Next Round</b>, or <b>Sim to Champion</b>. When a champion is crowned, <b>Advance Phase</b> unlocks to move into the Offseason.</p>",
            ),
            TutorialStep(
                "Your finance to-do",
                "<p>When the finance system is on, a phase-aware <b>finance to-do</b> banner appears here listing what your team needs to do this phase — set a budget in preseason, watch the luxury threshold / cash in-season, and handle arbitration and qualifying offers in the offseason.</p>",
            ),
            TutorialStep(
                "Offseason rollover",
                "<p>Entering the Offseason runs the rollover automatically: contracts advance, expired deals become free agents, arbitration and qualifying offers are processed, finances roll over, and players age. Admins can review/run pieces from <b>Admin → Offseason Flow</b>.</p>",
            ),
            TutorialStep(
                "One-off what-if games",
                "<p>Admins can run a single exhibition game outside the schedule via <b>Admin → Exhibition Game</b> — no schedule or stats are affected.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="roster_and_depth",
        title="Roster & Depth Chart",
        summary="Move players between ACT/AAA/LOW, right-click actions, set depth chart priorities.",
        route="/roster",
        steps=[
            TutorialStep(
                "Roster levels",
                "<p>Open <b>My Team → Roster</b>. Players are grouped by level: Active (25), AAA, Low, DL, IR. Each table shows position, role, and ratings.</p>",
            ),
            TutorialStep(
                "Right-click context menu",
                "<p><b>Right-click any player row</b> for a quick menu with Open profile, <b>Training focus…</b> (opens the per-player override dialog), Move to Active, Send to AAA, Send to Low-A, Place on DL (15), Place on 60-day IR, Shift to 45-day DL, and Release / Cut. The three-dot button at the end of the row opens the same menu.</p>",
            ),
            TutorialStep(
                "Move validation",
                "<p>Every move runs the shared validator — level caps (ACT 25 / AAA 15 / LOW 10), LOW age gate (27+), post-move minimum 11 non-pitchers on ACT, and defensive coverage. If a move would break a rule, the server returns a 422 with the specific error.</p>",
            ),
            TutorialStep(
                "Depth chart",
                "<p>Open <b>My Team → Depth Chart</b> to set up to three players per position (C/SS/CF/3B/2B/1B/LF/RF/DH). The top entry is the primary starter; the rest feed injury replacement + lineup autofill. Errors and warnings appear inline as you edit.</p>",
            ),
            TutorialStep(
                "Auto-generate depth chart",
                "<p>Click <b>Auto-generate</b> to seed every position with the best three available players from your roster — primary fits first, sorted by level (ACT before AAA / LOW) and overall rating. The button overwrites the current chart and saves immediately, so use it as a starting point or after a roster shake-up. Tweak from there with the move buttons.</p>",
            ),
            TutorialStep(
                "Saving with Ctrl+S",
                "<p>Press <b>Ctrl+S</b> (Cmd+S on macOS) to save any editor. An autosave kicks in every ~1.5 seconds while you're editing; if you reload mid-edit, a <b>Restore / Dismiss</b> banner offers to reinstate the draft.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="lineup",
        title="Lineup & Diamond View",
        summary="Two lineups, pitching roles, baseball diamond visualization, drag-and-drop.",
        route="/lineup",
        steps=[
            TutorialStep(
                "Two lineups",
                "<p>Open <b>My Team → Lineup</b>. Two tabs — <b>vs LHP</b> and <b>vs RHP</b> — store separate batting orders. Edit both so the simulator always has coverage.</p>",
            ),
            TutorialStep(
                "Baseball diamond",
                "<p>To the left of the batting table is an SVG diamond showing every position filled with the player's initial + last name and their batting order number. The field renders as ballpark grass + clay warning track + chalk lines, not a static image.</p>",
            ),
            TutorialStep(
                "Drag to reorder",
                "<p>Grab the <b>⋮⋮</b> handle on any row and drag to reorder the batting order. The ↑ / ↓ buttons still work for one-slot moves.</p>",
            ),
            TutorialStep(
                "Autofill — current side or both",
                "<p>Two autofill buttons sit above the lineup tabs:</p>"
                "<ul>"
                "<li><b>Autofill vs RHP / vs LHP</b> — fills only the side you're viewing, useful for tweaking platoon splits.</li>"
                "<li><b>Autofill both</b> — fills both batting orders in one click (the original behavior).</li>"
                "</ul>"
                "<p>Both buttons honour your depth chart priorities first, then fall back to a contact/power/speed/defense score.</p>",
            ),
            TutorialStep(
                "Live validation",
                "<p>As you edit, a validation card appears above the table with any errors (duplicate player, uncovered position, pitcher-in-lineup) and warnings (position eligibility). The Save button stays disabled until errors are resolved.</p>",
            ),
            TutorialStep(
                "Pitching staff roles",
                "<p>The <b>Pitching</b> tab exposes 11 slots: <b>SP1–SP5</b>, <b>LR</b>, <b>MR1–MR3</b>, <b>SU</b>, <b>CL</b>. Drag or use move buttons to reorder — the simulator schedules starts and calls relievers based on these roles. Low-rating warnings appear for starters or closers without the right ratings.</p>",
            ),
            TutorialStep(
                "Pitching staff Auto-fill",
                "<p>The <b>Auto-fill</b> button on the Pitching tab seeds all 11 slots from the active roster. Priority order: rotation goes to the five highest-endurance starters (or relievers preferring SP), then bullpen fills as <b>LR → CL → SU → MR1 → MR2 → MR3</b>. Long relief gets a high-endurance arm, closer gets the lowest-endurance arm (preferring anyone whose preferred role is CL), setup gets the next-lowest. The thinning order means a 9-pitcher staff still gets a usable LR/CL/SU before MR2/MR3 get filled.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="training",
        title="Training Focus",
        summary="Allocate 100% training time across hitter and pitcher tracks.",
        route="/training",
        steps=[
            TutorialStep(
                "Open Training",
                "<p>Use <b>My Team → Training</b>. Two allocator columns — Hitters and Pitchers — each sum to 100% across their tracks.</p>",
            ),
            TutorialStep(
                "Track minimums",
                "<p>Every track needs at least 5%. Save is disabled until both columns sum to exactly 100. Use the plus/minus buttons or type a value directly.</p>",
            ),
            TutorialStep(
                "Team vs league defaults",
                "<p>New teams inherit the league-wide mix. <b>Reset to defaults</b> clears your team override and returns to the league baseline.</p>",
            ),
            TutorialStep(
                "When it applies",
                "<p>Focus allocations feed the preseason training camp and ongoing development deltas. Budgets under Finance (training/development/facilities) scale the camp intensity.</p>",
            ),
            TutorialStep(
                "Save keyboard shortcut",
                "<p><b>Ctrl+S</b> saves. The hitters + pitchers summaries read as scoreboard-style numerals on the way in.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="injuries",
        title="Injury Center",
        summary="Place players on DL/IR, activate when eligible, promote replacements.",
        route="/injuries",
        steps=[
            TutorialStep(
                "Accessing injuries",
                "<p>Open <b>My Team → Injuries</b>. Players are split into DL, IR, and day-to-day groups. Counts and return dates live at the top of each group.</p>",
            ),
            TutorialStep(
                "DL tiers",
                "<p>DL supports 15-day and 45-day tiers. Eligible-to-activate date and days remaining are shown on every row; activation is blocked until the DL minimum is met.</p>",
            ),
            TutorialStep(
                "Activate or rehab",
                "<p>Use <b>Activate</b> to return the player to ACT. If rating confidence is low after a long stint, promote from AAA first to cover the slot.</p>",
            ),
            TutorialStep(
                "News trail",
                "<p>Every injury event is written to the news feed and transactions log so owners and commissioners can audit the history.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="free_agency",
        title="Free Agency",
        summary="Browse unsigned players and sign them to your roster.",
        route="/free-agency",
        steps=[
            TutorialStep(
                "Open Free Agency",
                "<p>Use <b>Transactions → Free Agency</b>. The page lists every unsigned player with ratings, role, and recent stats.</p>",
            ),
            TutorialStep(
                "Sign a player",
                "<p>Click <b>Sign</b> on a row, pick the destination level (ACT/AAA/LOW), set the salary/years, and optionally a <b>signing bonus</b> (which debits your cash now). The dialog previews the player's <b>fair-market value</b>, likely response, and the top <b>competing CPU bids</b> so you know who you're up against. Confirm — the server enforces roster caps and writes a sign transaction.</p>",
            ),
            TutorialStep(
                "Qualifying offers",
                "<p>In the offseason, a <b>Qualifying offers</b> card appears for your team's eligible departing free agents. Choose <b>Tender QO</b> (a one-year offer the player may accept or decline) or <b>Let walk</b>. A declined QO whose player signs elsewhere earns you a compensation draft pick.</p>",
            ),
            TutorialStep(
                "After signing",
                "<p>Update your depth chart or lineup so the new player gets game time. Signings appear in the news feed and transactions log for league visibility.</p>",
            ),
            TutorialStep(
                "Finance impact",
                "<p>With payroll rules on, the offer dialog shows a live <b>Your team's books</b> panel as you type: payroll before → after the signing vs the luxury threshold, the <b>estimated tax</b> if the offer crosses it, <b>cash remaining after the signing bonus</b> (with a debt warning if it goes negative), and an <b>Opening Day risk</b> flag if the move would leave you insolvent. Going over the threshold isn't blocked — you just pay the tax at settlement; the only hard limit is staying solvent for Opening Day.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="trades",
        title="Trades",
        summary="Propose, respond, withdraw — and admin veto/approve flow.",
        route="/trades",
        steps=[
            TutorialStep(
                "Open Trades",
                "<p>Use <b>Transactions → Trades</b>. The page lists your pending offers, offers you've received, and recent completed trades.</p>",
            ),
            TutorialStep(
                "Propose a trade",
                "<p>Click <b>Propose Trade</b>, pick the partner team, and move players + draft picks between give/receive lists. Commissioner-approval and pick-year caps are set in <b>Admin → Commissioner</b>.</p>",
            ),
            TutorialStep(
                "Respond to offers",
                "<p>Accept, reject, or withdraw from the pending queue. If the league requires commissioner approval, accepted trades wait for final review before assets move.</p>",
            ),
            TutorialStep(
                "Admin controls",
                "<p>When signed in as admin, pending trade rows show extra buttons: <b>Veto</b> (opens a modal to enter an owner-facing note), <b>Force approve</b> (bypasses validator errors — use sparingly), and <b>Approve</b> (standard admin accept).</p>",
            ),
            TutorialStep(
                "After a trade",
                "<p>Review depth charts and lineups — the new roster may exceed a level cap. Draft-pick ownership also shifts and is honoured on draft day.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="draft",
        title="Amateur Draft",
        summary="Live board, results history, and commissioner draft controls.",
        route="/draft",
        steps=[
            TutorialStep(
                "When the draft runs",
                "<p>The amateur draft fires mid-season when the calendar reaches Draft Day — use <b>Sim to Draft</b> from the Season page to fast-forward to it. Once every pick is committed, the regular season resumes <b>automatically</b>; you don't advance out of the draft manually.</p>",
            ),
            TutorialStep(
                "Live board",
                "<p>Open <b>Transactions → Draft</b>. The Now tab shows the current round, overall pick, the team on the clock, draft order, and recent picks. The History tab archives completed picks by year.</p>",
            ),
            TutorialStep(
                "Signing bonuses & compensation picks",
                "<p>With the finance system on, each pick signs an entry-level contract and its <b>slot signing bonus debits the team's cash</b>. If your league runs <b>qualifying offers</b>, a team that lost a QO'd free agent gets an extra <b>compensation pick</b> at the end of round 1, and the team that signed him forfeits a round-2 pick — the board handles the uneven round automatically.</p>",
            ),
            TutorialStep(
                "Admin controls",
                "<p>Admins see a third <b>Admin</b> tab with four commissioner tools:</p>"
                "<ul>"
                "<li><b>Initialize</b> — seed draft state with worst-first order from season stats.</li>"
                "<li><b>Generate pool</b> — write a fresh amateur draft pool for the year.</li>"
                "<li><b>Manual pick</b> — commissioner override to enter a pick by hand.</li>"
                "<li><b>Reset draft</b> — delete state + results CSV for a year.</li>"
                "</ul>",
            ),
            TutorialStep(
                "Results & history",
                "<p>Completed picks are stored per season and visible from the History tab or <b>League → History</b>. Export via <b>Admin → Utilities → Reports</b> to share.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="team_settings",
        title="Team Settings & Ballparks",
        summary="Colors, stadium, strategy profile, auto-reassign — plus park browser.",
        route="/settings",
        steps=[
            TutorialStep(
                "Access",
                "<p>Open <b>My Team → Settings</b>. Here you edit branding, home ballpark, team strategy profile, and roster auto-reassign behavior.</p>",
            ),
            TutorialStep(
                "Colors",
                "<p>Primary and secondary hex colors drive the team badge and accent across the UI. The swatch preview updates live. These colors power the team-color stripe on every team-specific page.</p>",
            ),
            TutorialStep(
                "Stadium browser",
                "<p>Click the building icon next to the stadium field to open the full park catalog as a modal. For a standalone browser without committing, use <b>League → Ballparks</b> — same catalog, same diagrams, no dialog.</p>",
            ),
            TutorialStep(
                "Strategy & auto-reassign",
                "<p>Strategy profile (Win Now, Development Focus, etc.) steers automation intent. Auto-Reassign lets you inherit the league default or explicitly enable/disable automatic level balancing for this team.</p>",
            ),
            TutorialStep(
                "Save with Ctrl+S",
                "<p><b>Ctrl+S</b> saves. Team settings changes are immediately reflected across the UI — next page load picks up the new colors.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="finance",
        title="Finance",
        summary="Snapshot, payroll headroom, budgets, arbitration, contracts, signing bonuses, qualifying offers.",
        route="/finance",
        steps=[
            TutorialStep(
                "Open Finance",
                "<p>Use <b>My Team → Finance</b>. The page shows cash on hand, debt, current revenue/expense totals, projected budgets, and the transactions ledger. The finance system is <b>modular</b> — a commissioner enables exactly the pieces a league wants (revenue, budgets, contracts, arbitration, free agency, payroll rules, CPU AI) or turns it off entirely — so the exact controls you see depend on the league's <b>preset</b> (Off / Simple / Standard / MLB-Like / Custom).</p>",
            ),
            TutorialStep(
                "Set your budgets",
                "<p>When the <b>owner budgets</b> module is on (Simple and up), the <b>Budgets</b> card is editable. Click <b>Edit</b>, set your allocation for each category — <b>training</b>, <b>scouting</b>, <b>development</b>, <b>facilities</b> — and click <b>Save budgets</b>. The projected figure next to each is your revenue-based ceiling. If your league is on a preset where budgets are off, the card stays read-only.</p>",
            ),
            TutorialStep(
                "Payroll vs Luxury Threshold",
                "<p>When payroll rules are on, a <b>Payroll vs Luxury Threshold</b> card shows a meter of your payroll against the league's <b>floor</b> and <b>luxury threshold</b>, with a zone badge (Safe / Over threshold / Under floor). It answers the big questions at a glance: how much <b>headroom</b> you have before the tax kicks in, the <b>estimated tax or floor fee</b> you'd pay at settlement, and whether you're <b>solvent for Opening Day</b> (projected debt within the cap). The numbers use the exact same math settlement charges.</p>",
            ),
            TutorialStep(
                "Track contracts league-wide",
                "<p><b>My Team → Contracts</b> is the league-wide contract tracker: salary (with total commitment for multi-year deals), years left, FA year, and service time. Hover the status badges — <b>Expiring</b>, <b>Arb-eligible</b>, <b>options</b>, <b>Non-gtd</b> — for a plain-language explanation of what each means for your planning.</p>",
            ),
            TutorialStep(
                "Arbitration decisions",
                "<p>When the league runs arbitration (<b>Standard</b> and <b>MLB-Like</b> presets — it's off in Simple), an <b>Arbitration</b> panel appears on the Finance page listing your arbitration-eligible players with their current and projected salary. For each, choose <b>Offer raise</b> (agree to the projected raise), <b>Hold</b>, or <b>Non-tender</b> (release him to free agency). Players only become arbitration-eligible after roughly three seasons of service, so a brand-new league shows an empty panel.</p>",
            ),
            TutorialStep(
                "Contract options & pre-arb renewals",
                "<p>On the <b>advanced</b> contracts model (Standard / MLB-Like), a player's profile page gets an <b>Owner actions</b> section on the Contract card for players you own. There you can <b>Exercise</b> or <b>Decline</b> a pending contract option (a declined option's buyout is charged to your cash), and <b>Renew</b> a pre-arbitration player's salary for the coming year — pre-arb players don't negotiate, so you set the figure (floored at the league minimum).</p>",
            ),
            TutorialStep(
                "Your finance to-do",
                "<p>When finance is on, the <b>Season</b> page shows a phase-aware <b>finance to-do</b> for your team: set your budget in preseason, watch for cash-low / over-the-luxury-threshold alerts in-season, and handle expiring contracts, arbitration, and qualifying offers in the offseason. Each item links straight to where you act.</p>",
            ),
            TutorialStep(
                "Enforcement: On or Off (hybrid)",
                "<p>Enforcement is simply <b>On</b> or <b>Off</b> — there's no warn/block middle ground. When On, the rules have teeth MLB-style: during the season you <i>can</i> exceed the luxury threshold, but you <b>pay the tax</b> (and a floor fee if you underspend) — nothing is blocked mid-season. The one hard gate is <b>Opening Day</b>: your team must be solvent (projected debt within the cap) to start the season, or the phase advance is blocked until you fix it.</p>",
            ),
            TutorialStep(
                "Money actually moves",
                "<p>Signing bonuses really cost cash: a draft pick's slot bonus and any free-agent signing bonus are <b>debited from your cash on hand</b> (going into debt if you can't cover it), and declined-option buyouts hit cash too. Everything posts to the transactions ledger so you can audit it.</p>",
            ),
            TutorialStep(
                "Qualifying offers",
                "<p>In the offseason, a departing free agent who reached full free agency may be eligible for a one-year <b>qualifying offer</b>. On the <b>Free Agency</b> page you choose <b>Tender QO</b> or <b>Let walk</b>. If a QO'd player declines and signs elsewhere, you receive a <b>compensation draft pick</b> (an extra end-of-round-1 pick) and the signing team forfeits a pick.</p>",
            ),
            TutorialStep(
                "Commissioner tools",
                "<p>Admins set the finance <b>preset</b> (Off / Simple / Standard / MLB-Like) and per-module levels from <b>Admin → Commissioner → Finance</b>. Picking a preset fills in every module level (MLB-Like turns it all on); choose <b>Custom</b> to fine-tune individual modules. <b>Admin → Finance Stability</b> validates guardrails against a multi-season sandbox before changing live settings.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="league_hub",
        title="League Hub",
        summary="Standings, leaders, stats, teams, schedule, playoffs, history, ballparks.",
        route="/league",
        steps=[
            TutorialStep(
                "Standings",
                "<p>Use <b>League → Standings</b> for division-grouped standings. Rows link to team detail pages.</p>",
            ),
            TutorialStep(
                "Leaders & stats",
                "<p><b>League → Leaders</b> ranks the top N hitters/pitchers by every major stat using MLB qualifier rules. <b>League → Stats</b> shows the full league stats table with team totals.</p>",
            ),
            TutorialStep(
                "History & records",
                "<p><b>League → History</b> archives every completed season — champion, runner-up, MVP, Cy Young, and artifact paths. <b>League → Records</b> surfaces the record book and per-team milestones.</p>",
            ),
            TutorialStep(
                "Hall of Fame",
                "<p><b>League → Hall of Fame</b> shows inducted players plus current-year candidates. Admins can induct or remove from this page.</p>",
            ),
            TutorialStep(
                "Ballparks",
                "<p><b>League → Ballparks</b> is a standalone browser of every park in the catalog with its field-diagram preview. Use it to scout parks before assigning one from Team Settings.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="command_center",
        title="Admin Command Center",
        summary="League-wide attention cards and workflow shortcuts.",
        route="/command-center",
        steps=[
            TutorialStep(
                "Access",
                "<p>Use <b>Admin → Command Center</b>. The page summarises injuries, pending approvals, roster conflicts, deadlines, and finance risks as severity-ranked cards.</p>",
            ),
            TutorialStep(
                "Refresh after events",
                "<p>Click <b>Refresh</b> after running sims or reviewing transactions to pull the latest state before making league decisions.</p>",
            ),
            TutorialStep(
                "Action shortcuts",
                "<p>Each card has links straight to the relevant admin page (commissioner, finance queue) so you can jump directly into the fix.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="admin_tools",
        title="Admin Tools Overview",
        summary="Commissioner, finance queue, users, tuning, league admin, exhibition.",
        route="/commissioner",
        steps=[
            TutorialStep(
                "Quick-access grid",
                "<p>The top of <b>Admin → Commissioner</b> has a quick-access grid linking to every major admin surface: Command Center, Finance Queue, Offseason Flow, Reassign Players, Finance Stability, Exhibition Game, League Admin, Physics Tuning, Users.</p>",
            ),
            TutorialStep(
                "Commissioner settings",
                "<p><b>Admin → Commissioner</b> controls trade rules, global injury level, finance preset + enforcement, the new <b>module-level finance toggles</b> (10 modules from Owner Revenue to GM Finance AI), <b>CPU finance AI tuning</b> (19 numeric knobs — star thresholds, salary share caps, arbitration raise %, FA avoidance bands), and a separate <b>Scouting fog-of-war</b> card with its own enable + 6 pacing knobs. Each module's level dropdown shows a <b>plain-language description of the selected level</b> so you know what Basic vs Advanced vs MLB-Like actually changes. Module / AI sections are collapsed by default; expand them in Custom mode for fine-grained edits.</p>",
            ),
            TutorialStep(
                "Strategy &amp; auto-reassign",
                "<p>The <b>Strategy &amp; auto-reassign</b> card on the Commissioner page sets the league-default strategy profile and auto-reassign behavior, plus per-team overrides in a scrollable table.</p>",
            ),
            TutorialStep(
                "Finance queue",
                "<p><b>Admin → Finance Queue</b> reviews pending GM decisions (contracts, arbitration) that need commissioner approval. Rows show the <b>player's name</b>, a plain-language decision (e.g. <i>Non-tender — release to free agency</i>), and the <b>salary movement</b>. <b>Apply approved</b> lists exactly which decisions will be committed before you confirm — the write is irreversible.</p>",
            ),
            TutorialStep(
                "Offseason review tabs",
                "<p><b>Admin → Offseason Flow</b> now has a Review section with four tabs: <b>Contracts</b> (expirations next year), <b>Arbitration</b> (filed awards + delta), <b>Budgets</b> (per-team year-over-year delta with category breakdown), and <b>GM Queue</b> (pending owner decisions with team / queue / status filters and inline Approve / Reject buttons for the row in focus).</p>",
            ),
            TutorialStep(
                "Users",
                "<p><b>Admin → Users</b> manages the users.txt roster. Create admin or owner accounts, reset passwords, and assign teams.</p>",
            ),
            TutorialStep(
                "Physics tuning",
                "<p><b>Admin → Physics Tuning</b> exposes every tunable knob from the physics engine (offense/pitching scales, discipline, fatigue, defense). Overrides are stored separately from defaults so Reset is always safe.</p>",
            ),
            TutorialStep(
                "Utilities",
                "<p><b>Admin → Utilities</b> hosts logos, avatars, reports, almanac, and snapshot exports. Run these before destructive admin actions to keep archival copies.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="exhibition",
        title="Exhibition Game",
        summary="Run a one-off simulation outside the schedule.",
        route="/exhibition",
        steps=[
            TutorialStep(
                "When to use it",
                "<p>Exhibition games are 'what-if' tools — they don't touch the schedule, stats, or transactions log. Great for testing a new roster, trying a matchup, or demoing the sim.</p>",
            ),
            TutorialStep(
                "Open the page",
                "<p>Admins: <b>Admin → Exhibition Game</b>. Pick an away team and a home team from the dropdowns. The <b>Simulate</b> button enables once both are chosen and different.</p>",
            ),
            TutorialStep(
                "What the sim uses",
                "<p>Each team plays with its current saved roster, lineups (vs LHP/RHP), and pitching staff. If either team has missing lineups, the server returns a 400 with the specific data that's missing.</p>",
            ),
            TutorialStep(
                "Result view",
                "<p>On finish you get an inline boxscore with batting + pitching lines per side. The full HTML boxscore is saved under <code>data/exhibition_boxscores/</code> and linked in the result panel. Expand <b>Strategy log</b> or <b>Field positions</b> for deeper detail.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="league_admin",
        title="League Admin",
        summary="Schedule regen, stat/result reset, repair lineups, clone league.",
        route="/league-admin",
        steps=[
            TutorialStep(
                "Open the page",
                "<p>Admins: <b>Admin → League Admin</b>. Every action here is destructive and double-confirms before running.</p>",
            ),
            TutorialStep(
                "Regenerate schedule",
                "<p>Picks a schedule template (MLB-162, etc.) and overwrites <code>schedule.csv</code>. All played results are cleared. Use this after major structural changes (division realignment, team count change).</p>",
            ),
            TutorialStep(
                "Reset stats / clear results",
                "<p><b>Reset season stats</b> wipes <code>season_stats.json</code> without touching the schedule. <b>Clear played results</b> keeps the matchups but marks every game unplayed — faster to re-run a season without regenerating the whole schedule.</p>",
            ),
            TutorialStep(
                "Repair lineups",
                "<p>Runs lineup autofill + roster backfill across every team. Use after a roster import or when the season progress page reports lineup validation failures.</p>",
            ),
            TutorialStep(
                "Clone league",
                "<p>Deep-copies the active league into a new registry entry. Use before risky experiments so you can always roll back to the cloned baseline.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="player_avatars",
        title="Player Avatars",
        summary="Auto-generate avatars from team templates or override per player.",
        steps=[
            TutorialStep(
                "Auto-generate avatars",
                "<p>Open <b>Admin → Utilities → Generate Player Avatars</b>.</p>"
                "<ul>"
                "<li>Choose <b>Yes</b> on initial creation to rebuild every avatar (keeps only <code>Template</code> and <code>default.png</code>).</li>"
                "<li>Choose <b>No</b> to fill only missing avatars.</li>"
                "<li>Output PNGs land at <code>images/avatars/&lt;player_id&gt;.png</code>.</li>"
                "<li>Templates live in <code>images/avatars/Template</code> and are recolored from the team's primary/secondary colors.</li>"
                "</ul>",
            ),
            TutorialStep(
                "Manual overrides",
                "<p>Drop a custom PNG into <code>images/avatars/</code> to override the generated image.</p>"
                "<ul>"
                "<li>Name the file <code>&lt;player_id&gt;.png</code>; player IDs come from <code>data/players.csv</code>.</li>"
                "<li>Square images work best — 256×256 or 512×512.</li>"
                "<li>Profiles fall back to <code>images/avatars/default.png</code> if no file matches.</li>"
                "<li>Reopen the player profile after replacing an avatar to refresh the cached image.</li>"
                "</ul>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="team_logos",
        title="Team Logos",
        summary="Auto-generate team logos or drop in your own square PNG.",
        steps=[
            TutorialStep(
                "Auto-generate logos",
                "<p>Open <b>Admin → Utilities → Generate Team Logos</b>.</p>"
                "<ul>"
                "<li>Output PNGs land at <code>logo/teams/&lt;team_id&gt;.png</code> (team_id is lower-case).</li>"
                "<li>Running the generator replaces existing logos in <code>logo/teams</code>.</li>"
                "<li>If the OpenAI client is not configured, the legacy auto-logo generator is used.</li>"
                "</ul>",
            ),
            TutorialStep(
                "Manual overrides",
                "<p>Drop a custom PNG into <code>logo/teams/</code> to override the generated logo.</p>"
                "<ul>"
                "<li>Name the file <code>&lt;team_id&gt;.png</code>; team IDs come from <code>data/teams.csv</code>.</li>"
                "<li>Square images work best — 512×512 or 1024×1024.</li>"
                "<li>Reopen the team screen after replacing a logo to refresh the view.</li>"
                "</ul>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="shortcuts",
        title="Keyboard Shortcuts",
        summary="Save with Ctrl+S, open Help with Alt+/, right-click rosters.",
        steps=[
            TutorialStep(
                "Save from anywhere",
                "<p><b>Ctrl+S</b> (or <b>Cmd+S</b> on macOS) saves the active editor from:</p>"
                "<ul>"
                "<li>Lineup (vs LHP, vs RHP, Pitching Staff)</li>"
                "<li>Depth Chart</li>"
                "<li>Training Focus</li>"
                "<li>Team Settings</li>"
                "</ul>"
                "<p>The shortcut is gated on having something to save, so you can hit it repeatedly without risk.</p>",
            ),
            TutorialStep(
                "Open Help",
                "<p><b>Alt+/</b> from anywhere jumps to the Help & Tutorials page. The sidebar footer and header question-mark icon are also one-click entry points.</p>",
            ),
            TutorialStep(
                "Autosave rescue",
                "<p>Every edit-heavy page debounces your unsaved state to localStorage every ~1.5 seconds. If you reload mid-edit, a <b>Restore unsaved changes</b> banner offers to reinstate the draft.</p>",
            ),
            TutorialStep(
                "Right-click rosters",
                "<p>On the <b>Roster</b> page, right-click any row for the quick context menu (promote, demote, DL/IR, cut, open profile). The three-dot button gives the same actions for keyboard users.</p>",
            ),
            TutorialStep(
                "Escape closes dialogs",
                "<p><b>Esc</b> closes any open dialog — park browser, propose-trade, veto-note, tutorial step-through. The diamond diagram stays open because it's a panel, not a dialog.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="notifications",
        title="Notifications & Stop-Sim Rules",
        summary="Pick which league events fire alerts and which pause a multi-day sim.",
        route="/notifications",
        steps=[
            TutorialStep(
                "Why this page exists",
                "<p>The notification engine runs after each simulated day. When something you care about happens — a player goes on the DL, the trade deadline approaches, cash runs low — a banner appears on the <b>Season</b> page and the event is logged here. Optionally, multi-day sims pause the second a flagged event fires so you can react before any more days tick over.</p>",
            ),
            TutorialStep(
                "Three checkboxes per rule",
                "<p>Each rule has three knobs:</p>"
                "<ul>"
                "<li><b>Enabled</b> — log the event to history at all.</li>"
                "<li><b>Notify</b> — show a banner on the Season page after the sim batch finishes.</li>"
                "<li><b>Stop sim</b> — pause a Sim Day / Week / Month / To Draft run the moment this rule fires.</li>"
                "</ul>"
                "<p>Some rules carry a <b>Threshold</b> too — e.g. losing-streak length, cash-low dollar floor, days-out horizon for the trade deadline.</p>",
            ),
            TutorialStep(
                "Default safety net",
                "<p>Out of the box, <b>15-day DL / 45-day DL / 60-day IR / season-ending injuries</b> all stop the sim — that's the most common reason owners want to be interrupted. Day-to-day injuries notify-only by default so the AI can keep going and you only see them in the banner. Edit any of these on this page if you'd rather have the AI auto-handle a tier or be paused for a different one.</p>",
            ),
            TutorialStep(
                "Categories at a glance",
                "<p>Rules are grouped into seven categories: <b>Health & roster</b>, <b>Performance & milestones</b>, <b>Transactions</b>, <b>Calendar & deadlines</b>, <b>Finance</b>, <b>League & admin</b>, and <b>Draft</b>. Saving writes to <code>data/notifications/&lt;team_id&gt;.json</code>; the engine reads it on every <b>/season/simulate/*</b> call.</p>",
            ),
            TutorialStep(
                "Recent events tab",
                "<p>The <b>Recent events</b> tab shows the last ~100 notifications generated for this team — newest first, with severity badge, sim date, and message. Use it to audit what the engine has been firing on or to confirm a rule you just enabled is actually catching events.</p>",
            ),
            TutorialStep(
                "Resuming after a stop",
                "<p>When a sim stops early, a warning banner above the Season page tells you which rule fired (e.g. <i>Sim paused: Player on 15-day DL</i>). Fix what needs fixing — adjust the lineup, claim a free agent, place the player on the DL — then re-click your sim button to keep going. Existing DL automation already moved the player, so the AI has done its part.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="navigation",
        title="Navigation: Hubs, Breadcrumbs & Favorites",
        summary="The sidebar shrunk from 30 entries to 8 — here's how to find anything fast.",
        route="/hub/my-team",
        steps=[
            TutorialStep(
                "Top-level destinations",
                "<p>The sidebar collapses into seven top-level items: <b>Today</b> (Dashboard, Season, News), four <b>hubs</b> (My Team, League, Transactions, Admin — admin-only), <b>Notifications</b>, and <b>Help</b>. Every other page lives behind a hub click.</p>",
            ),
            TutorialStep(
                "Hubs are landing pages",
                "<p>Click a hub (e.g. <b>My Team</b>) to land on a card grid of every page in that category — Roster, Pitchers, Lineup, Depth Chart, Training, Injuries, Notifications, Finance, Settings. Capability-gated cards (Finance when finance is off, Submit Request in single-player) auto-hide based on your league.</p>",
            ),
            TutorialStep(
                "Breadcrumbs above every page",
                "<p>The header shows a trail like <code>Home / My Team / Roster</code>. Earlier segments are links — click <b>My Team</b> to jump back to the hub without using the sidebar.</p>",
            ),
            TutorialStep(
                "Pin to favorites",
                "<p>Right-click any sidebar entry or hub card → <b>Pin to sidebar</b>. Pinned items show in a <b>Favorites</b> section above the hubs. Right-click again to <b>Unpin</b>. Pins are per browser profile and persist across launches.</p>",
            ),
            TutorialStep(
                "Collapse to icons-only",
                "<p>The chevron at the very top of the sidebar collapses the rail to a 56-px icon strip. Hover any icon for its label. Click the chevron again to expand. The preference persists across sessions.</p>",
            ),
            TutorialStep(
                "Phase-aware filtering",
                "<p>The sidebar's Favorites section auto-hides routes that don't apply to the current phase — e.g. <b>Draft</b> outside <code>AMATEUR_DRAFT</code> / <code>PRESEASON</code>, <b>Offseason Flow</b> outside <code>OFFSEASON</code> / <code>PRESEASON</code>. The hubs still show every card so you can pre-explore.</p>",
            ),
            TutorialStep(
                "Command palette",
                "<p>Power users can press <b>Cmd+K</b> / <b>Ctrl+K</b> to open the command palette and jump straight to any page by name without clicking a hub. The palette is the fastest path when you know exactly where you want to go.</p>",
            ),
        ],
    ),
]


def tutorial_catalog() -> Dict[str, Dict[str, object]]:
    """Return the catalog as a dict keyed by tutorial_id for API serving."""

    out: Dict[str, Dict[str, object]] = {}
    for t in TUTORIALS:
        out[t.tutorial_id] = {
            "tutorial_id": t.tutorial_id,
            "title": t.title,
            "summary": t.summary,
            "route": t.route,
            "steps": [{"title": s.title, "body_html": s.body_html} for s in t.steps],
        }
    return out


def tutorial_list() -> List[Dict[str, object]]:
    return list(tutorial_catalog().values())


__all__ = [
    "Tutorial",
    "TutorialStep",
    "TUTORIALS",
    "tutorial_catalog",
    "tutorial_list",
]
