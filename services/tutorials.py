"""Tutorial catalog — pure data, shared by the PyQt dashboard and the
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
                "<p>The sidebar is grouped into <b>Today</b>, <b>My Team</b>, <b>League</b>, <b>Transactions</b>, and <b>Admin</b>. Click any section header to collapse it; your layout preference persists across launches.</p>",
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
                "<p>When the regular season ends, use <b>Advance Phase</b> to enter the draft or playoffs. The UI blocks sims that would skip required stages.</p>",
            ),
            TutorialStep(
                "Offseason rollover",
                "<p>After playoffs, admins can run the full offseason flow from <b>Admin → Offseason Flow</b>. It handles contract rollover, arbitration, free agency, and year-end snapshots.</p>",
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
                "<p><b>Right-click any player row</b> for a quick menu with Open profile, Move to Active, Send to AAA, Send to Low-A, Place on DL (15), Place on 60-day IR, Shift to 45-day DL, and Release / Cut. The three-dot button at the end of the row opens the same menu.</p>",
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
                "Autofill",
                "<p>Click <b>Autofill</b> to generate lineups from ratings. The generator respects your depth chart priorities where possible; fine-tune from there.</p>",
            ),
            TutorialStep(
                "Live validation",
                "<p>As you edit, a validation card appears above the table with any errors (duplicate player, uncovered position, pitcher-in-lineup) and warnings (position eligibility). The Save button stays disabled until errors are resolved.</p>",
            ),
            TutorialStep(
                "Pitching staff roles",
                "<p>The <b>Pitching</b> tab exposes SP1–SP5, LR, MR1–MR3, SU, CL slots. Drag or use move buttons to reorder — the simulator schedules starts and calls relievers based on these roles. Low-rating warnings appear for starters or closers without the right ratings.</p>",
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
                "<p>Click <b>Sign</b> on a row, pick the destination level (ACT/AAA/LOW), and confirm. The server enforces roster caps and writes a sign transaction.</p>",
            ),
            TutorialStep(
                "After signing",
                "<p>Update your depth chart or lineup so the new player gets game time. Signings appear in the news feed and transactions log for league visibility.</p>",
            ),
            TutorialStep(
                "Watch Finance alerts",
                "<p>After a sign, check <b>My Team → Finance</b>. The Payroll Alerts card warns if the signing pushed you into cash-burn territory.</p>",
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
                "<p>The draft fires when the season reaches the amateur draft phase. Use <b>Sim to Draft</b> from the Season page to advance.</p>",
            ),
            TutorialStep(
                "Live board",
                "<p>Open <b>Transactions → Draft</b>. The Now tab shows current round, overall pick, draft order, and most recent picks. The History tab archives completed picks by year.</p>",
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
        title="Finance Hub",
        summary="Snapshot, payroll alerts, budget projections, transactions log.",
        route="/finance",
        steps=[
            TutorialStep(
                "Open Finance",
                "<p>Use <b>My Team → Finance</b>. The page shows cash on hand, debt, current revenue/expense totals, and projected budgets.</p>",
            ),
            TutorialStep(
                "Payroll alerts",
                "<p>The Payroll Alerts card warns proactively when cash is running out, debt exceeds a year of projected revenue, projected monthly net is negative, or the league has financials disabled. These show inline before you have to run the Finance Stability sandbox.</p>",
            ),
            TutorialStep(
                "Budget categories",
                "<p>Training, scouting, development, and facilities budgets feed the simulation. Training budget scales preseason camp intensity; scouting budget drives scouting confidence.</p>",
            ),
            TutorialStep(
                "Transactions log",
                "<p>Scroll down for recent ledger entries. Every finance-posting event — ticket revenue, payroll, scouting spend — appears here for auditing.</p>",
            ),
            TutorialStep(
                "Commissioner tools",
                "<p>Admins set finance preset (simple, standard, MLB-like) and enforcement mode from <b>Admin → Commissioner</b>. The <b>Admin → Finance Stability</b> tool validates guardrails against a multi-season sandbox before changing live settings.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="change_request",
        title="Submit Change Request",
        summary="Owners bundle edits into a ZIP for commissioner approval.",
        route="/submit-change-request",
        steps=[
            TutorialStep(
                "Open the page",
                "<p>Use <b>Transactions → Submit Request</b> after making any roster, lineup, pitching, or depth-chart changes you want reviewed.</p>",
            ),
            TutorialStep(
                "Pick sections",
                "<p>Check the sections to include in the bundle. Add an optional owner note explaining the change.</p>",
            ),
            TutorialStep(
                "Export ZIP",
                "<p>Click <b>Export request</b>. A ZIP containing the current snapshot of the selected files is written and made available for download. Send the ZIP to your commissioner.</p>",
            ),
            TutorialStep(
                "Cancel before applied",
                "<p>The page lists your previously exported requests. If you need to withdraw one before the commissioner applies it, click <b>Export cancel</b> and deliver that bundle instead.</p>",
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
                "<p>Each card has links straight to the relevant admin page (commissioner, finance queue, change requests) so you can jump directly into the fix.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="admin_tools",
        title="Admin Tools Overview",
        summary="Commissioner, finance queue, change requests, users, tuning, league admin, exhibition.",
        route="/commissioner",
        steps=[
            TutorialStep(
                "Quick-access grid",
                "<p>The top of <b>Admin → Commissioner</b> has a 10-card quick-access grid linking to every major admin surface: Command Center, Finance Queue, Change Requests, Offseason Flow, Reassign Players, Finance Stability, Exhibition Game, League Admin, Physics Tuning, Users.</p>",
            ),
            TutorialStep(
                "Commissioner settings",
                "<p><b>Admin → Commissioner</b> controls trade rules, global injury level, and finance preset. The old injury-settings dialog is consolidated here.</p>",
            ),
            TutorialStep(
                "Finance queue & change requests",
                "<p><b>Admin → Finance Queue</b> reviews pending GM decisions (contracts, arbitration) that need commissioner approval. <b>Admin → Change Requests</b> lists owner-submitted bundles with approve/reject/requeue.</p>",
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
