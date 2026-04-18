"""Tutorial catalog — pure data, shared by the PyQt dashboard and the
FastAPI sidecar.

Each tutorial is a list of ``TutorialStep`` objects with an HTML body.
The Electron renderer sanitizes with a narrow allowlist before display.
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


TUTORIALS: List[Tutorial] = [
    Tutorial(
        tutorial_id="overview",
        title="Dashboard Overview",
        summary="Take a tour of the owner dashboard and learn what each panel shows.",
        steps=[
            TutorialStep(
                "Hero & Record",
                "<p>The hero banner at the top of <b>Dashboard</b> shows your team name, record, run differential, and current streak. It refreshes whenever the sim date advances.</p>",
            ),
            TutorialStep(
                "Stat Cards",
                "<p>The four stat cards under the hero summarise run differential, streak, active roster size, and the next scheduled game. Click a card to jump to the matching screen.</p>",
            ),
            TutorialStep(
                "Division Standings",
                "<p>The left panel lists every team in your division with win–loss, games-back, streak, and last-10. Your row is highlighted in amber.</p>",
            ),
            TutorialStep(
                "Upcoming & Recent Slices",
                "<p>The right column shows the next five games and the last five results. Played rows link to the full boxscore.</p>",
            ),
            TutorialStep(
                "Sidebar Navigation",
                "<p>The sidebar on the left is grouped into <b>Today</b>, <b>My Team</b>, <b>League</b>, <b>Transactions</b>, and <b>Admin</b>. Click any section header to collapse it; your layout preference persists across launches.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="season",
        title="Simulating Seasons",
        summary="Day-at-a-time sim flows: day, week, month, to-draft, to-playoffs.",
        steps=[
            TutorialStep(
                "Open the Season Page",
                "<p>Use <b>Today → Season</b> in the sidebar. The header shows the current phase (Preseason, Regular Season, Amateur Draft, Playoffs, or Offseason) and progress through the current year.</p>",
            ),
            TutorialStep(
                "Pick a Sim Range",
                "<p>Buttons cover <b>Sim Day</b>, <b>Sim Week</b>, <b>Sim Month</b>, a custom <b>N Days</b> field, <b>Sim to Draft</b>, and <b>Sim to Playoffs</b>. Each advances the shared season state.</p>",
            ),
            TutorialStep(
                "Phase Transitions",
                "<p>When the regular season ends, use <b>Advance Phase</b> to enter the draft or playoffs. The UI blocks sims that would skip required stages.</p>",
            ),
            TutorialStep(
                "Offseason Rollover",
                "<p>After playoffs, admins can run the full offseason flow from <b>Admin → Offseason Flow</b>. It handles contract rollover, arbitration, free agency, and year-end snapshots.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="roster_and_depth",
        title="Roster & Depth Chart",
        summary="Move players between ACT/AAA/LOW, cut, and set depth chart priorities.",
        steps=[
            TutorialStep(
                "Roster Levels",
                "<p>Open <b>My Team → Roster</b>. Players are grouped by level: Active (25), AAA, Low, DL, IR. Each table shows position, role, and ratings.</p>",
            ),
            TutorialStep(
                "Move Between Levels",
                "<p>Right-click or use the level buttons on a row to move a player between ACT, AAA, and LOW. The server enforces level caps and writes a transaction entry.</p>",
            ),
            TutorialStep(
                "Depth Chart",
                "<p>Open <b>My Team → Depth Chart</b> to set up to three players per position (C/SS/CF/3B/2B/1B/LF/RF/DH). The top entry is the primary starter; the rest feed injury replacement + lineup autofill.</p>",
            ),
            TutorialStep(
                "Saving Changes",
                "<p>Changes are staged as dirty until you click <b>Save</b>. The <b>Reset</b> button discards unsaved edits and reloads what's on disk.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="lineup",
        title="Lineup & Pitching Staff",
        summary="Separate lineups vs LHP/RHP and pitching role slots.",
        steps=[
            TutorialStep(
                "Two Lineups",
                "<p>Open <b>My Team → Lineup</b>. Two tabs — <b>vs LHP</b> and <b>vs RHP</b> — store separate batting orders. Edit both so the simulator always has coverage.</p>",
            ),
            TutorialStep(
                "Autofill",
                "<p>Click <b>Autofill</b> to generate lineups from ratings. The generator respects your depth chart priorities where possible; fine-tune from there.</p>",
            ),
            TutorialStep(
                "Pitching Staff Roles",
                "<p>The <b>Pitching</b> tab exposes SP1–SP5, LR, MR1–MR3, SU, and CL slots. Drag or use move buttons to reorder — the simulator schedules starts and calls relievers based on these roles.</p>",
            ),
            TutorialStep(
                "Watch Fatigue",
                "<p>The roster detail shows stamina and rest days. Using fatigued arms risks injuries; rotate in MR slots when the bullpen is taxed.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="training",
        title="Training Focus",
        summary="Allocate 100% training time across hitter and pitcher tracks.",
        steps=[
            TutorialStep(
                "Open Training",
                "<p>Use <b>My Team → Training</b>. Two allocator columns — Hitters and Pitchers — each sum to 100% across their tracks.</p>",
            ),
            TutorialStep(
                "Track Minimums",
                "<p>Every track needs at least 5%. Save is disabled until both columns sum to exactly 100. Use the plus/minus buttons or type a value directly.</p>",
            ),
            TutorialStep(
                "Team vs League Defaults",
                "<p>New teams inherit the league-wide mix. <b>Reset to defaults</b> clears your override and returns to the league baseline.</p>",
            ),
            TutorialStep(
                "When It Applies",
                "<p>Focus allocations feed the preseason training camp and ongoing development deltas. Budgets under Finance (training/development/facilities) scale the camp intensity.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="injuries",
        title="Injury Center",
        summary="Place players on DL/IR, activate when eligible, promote replacements.",
        steps=[
            TutorialStep(
                "Accessing Injuries",
                "<p>Open <b>My Team → Injuries</b>. Players are split into DL, IR, and day-to-day groups. Counts and return dates live at the top of each group.</p>",
            ),
            TutorialStep(
                "DL Tiers",
                "<p>DL supports 15-day and 45-day tiers. Eligible-to-activate date and days remaining are shown on every row; activation is blocked until the DL minimum is met.</p>",
            ),
            TutorialStep(
                "Activate or Rehab",
                "<p>Use <b>Activate</b> to return the player to ACT. If rating confidence is low after a long stint, promote from AAA first to cover the slot.</p>",
            ),
            TutorialStep(
                "News Trail",
                "<p>Every injury event is written to the news feed and transactions log so owners and commissioners can audit the history.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="free_agency",
        title="Free Agency",
        summary="Browse unsigned players and sign them to your roster.",
        steps=[
            TutorialStep(
                "Open Free Agency",
                "<p>Use <b>Transactions → Free Agency</b>. The page lists every unsigned player with ratings, role, and recent stats.</p>",
            ),
            TutorialStep(
                "Sign a Player",
                "<p>Click <b>Sign</b> on a row, pick the destination level (ACT/AAA/LOW), and confirm. The server enforces roster caps and writes a sign transaction.</p>",
            ),
            TutorialStep(
                "After Signing",
                "<p>Update your depth chart or lineup so the new player gets game time. Signings appear in the news feed and transactions log for league visibility.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="trades",
        title="Trades",
        summary="Propose offers, review pending trades, accept or reject.",
        steps=[
            TutorialStep(
                "Open Trades",
                "<p>Use <b>Transactions → Trades</b>. The page lists your pending offers, offers you've received, and recent completed trades.</p>",
            ),
            TutorialStep(
                "Propose a Trade",
                "<p>Click <b>Propose Trade</b>, pick the partner team, and move players + draft picks between give/receive lists. Commissioner-approval and pick-year caps are configured in <b>Admin → Commissioner</b>.</p>",
            ),
            TutorialStep(
                "Respond to Offers",
                "<p>Accept, reject, or withdraw from the pending queue. If the league requires commissioner approval, accepted trades wait for final review before assets move.</p>",
            ),
            TutorialStep(
                "After a Trade",
                "<p>Review depth charts and lineups — the new roster may exceed a level cap. Draft-pick ownership also shifts and is honoured on draft day.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="draft",
        title="Amateur Draft",
        summary="Review the draft pool, make picks, and view results.",
        steps=[
            TutorialStep(
                "When the Draft Runs",
                "<p>The draft fires automatically when the season reaches the amateur draft phase. Use <b>Sim to Draft</b> from the Season page to advance.</p>",
            ),
            TutorialStep(
                "Live Board",
                "<p>Open <b>Transactions → Draft</b>. The state view shows the current round, overall pick, and draft order. Admins can manually select; owners get auto-pick for their slots.</p>",
            ),
            TutorialStep(
                "Prospect Details",
                "<p>Click a prospect to open their profile with ratings, age, and scouting confidence. Use it to compare options before committing.</p>",
            ),
            TutorialStep(
                "Results & History",
                "<p>Completed picks are stored per season and visible from the history screens. Export reports from <b>Admin → Utilities</b> to share with owners.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="team_settings",
        title="Team Settings",
        summary="Colors, stadium, strategy profile, auto-reassign override.",
        steps=[
            TutorialStep(
                "Access",
                "<p>Open <b>My Team → Settings</b>. Here you edit branding, home ballpark, team strategy profile, and roster auto-reassign behavior.</p>",
            ),
            TutorialStep(
                "Colors",
                "<p>Primary and secondary hex colors drive the team badge and accent across the UI. The swatch preview updates live.</p>",
            ),
            TutorialStep(
                "Stadium Browser",
                "<p>Click the building icon next to the stadium field to open the full park catalog. Pick from every ParkConfig entry with live diagram previews.</p>",
            ),
            TutorialStep(
                "Strategy & Auto-Reassign",
                "<p>Strategy profile (Win Now, Development Focus, etc.) steers automation intent. Auto-Reassign lets you inherit the league default or explicitly enable/disable automatic level balancing for this team.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="finance",
        title="Finance Hub",
        summary="Team budget, payroll commitments, projected revenue and expenses.",
        steps=[
            TutorialStep(
                "Open Finance",
                "<p>Use <b>My Team → Finance</b>. The page shows cash on hand, debt, current revenue/expense totals, and projected budgets.</p>",
            ),
            TutorialStep(
                "Budget Categories",
                "<p>Training, scouting, development, and facilities budgets feed the simulation. Training budget scales preseason camp intensity; scouting budget drives scouting confidence.</p>",
            ),
            TutorialStep(
                "Transactions Log",
                "<p>Scroll down for recent ledger entries. Every finance-posting event — ticket revenue, payroll, scouting spend — appears here for auditing.</p>",
            ),
            TutorialStep(
                "Commissioner Controls",
                "<p>Admins set finance preset (simple, standard, MLB-like) and enforcement mode from <b>Admin → Commissioner</b>. The <b>Admin → Finance Stability</b> tool validates guardrails against a multi-season sandbox before changing live settings.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="change_request",
        title="Submit Change Request",
        summary="Owners bundle roster/lineup/pitching/depth changes for commissioner approval.",
        steps=[
            TutorialStep(
                "Open the Page",
                "<p>Use <b>Transactions → Submit Request</b> after making any roster, lineup, pitching, or depth-chart changes you want reviewed.</p>",
            ),
            TutorialStep(
                "Pick Sections",
                "<p>Check the sections to include in the bundle. Add an optional owner note explaining the change.</p>",
            ),
            TutorialStep(
                "Export ZIP",
                "<p>Click <b>Export request</b>. A ZIP containing the current snapshot of the selected files is written and made available for download. Send the ZIP to your commissioner.</p>",
            ),
            TutorialStep(
                "Cancel Before Applied",
                "<p>The page lists your previously exported requests. If you need to withdraw one before the commissioner applies it, click <b>Export cancel</b> and deliver that bundle instead.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="league_hub",
        title="League Hub",
        summary="Standings, leaders, stats, teams, schedule, playoffs, history.",
        steps=[
            TutorialStep(
                "Standings",
                "<p>Use <b>League → Standings</b> for division-grouped standings. Rows link to team detail pages.</p>",
            ),
            TutorialStep(
                "Leaders & Stats",
                "<p><b>League → Leaders</b> ranks the top N hitters/pitchers by every major stat using MLB qualifier rules. <b>League → Stats</b> shows the full league stats table with team totals.</p>",
            ),
            TutorialStep(
                "History & Records",
                "<p><b>League → History</b> archives every completed season — champion, runner-up, MVP, Cy Young, and artifact paths. <b>League → Records</b> surfaces the record book and per-team milestones.</p>",
            ),
            TutorialStep(
                "Hall of Fame",
                "<p><b>League → Hall of Fame</b> shows inducted players plus current-year candidates. Admins can induct or remove from this page.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="command_center",
        title="Admin Command Center",
        summary="League-wide attention cards and workflow shortcuts.",
        steps=[
            TutorialStep(
                "Access",
                "<p>Use <b>Admin → Command Center</b>. The page summarises injuries, pending approvals, roster conflicts, deadlines, and finance risks as severity-ranked cards.</p>",
            ),
            TutorialStep(
                "Refresh After Events",
                "<p>Click <b>Refresh</b> after running sims or reviewing transactions to pull the latest state before making league decisions.</p>",
            ),
            TutorialStep(
                "Action Shortcuts",
                "<p>Each card has links straight to the relevant admin page (commissioner, finance queue, change requests) so you can jump directly into the fix.</p>",
            ),
        ],
    ),
    Tutorial(
        tutorial_id="admin_tools",
        title="Admin Tools Overview",
        summary="Commissioner, finance queue, change requests, users, tuning.",
        steps=[
            TutorialStep(
                "Commissioner",
                "<p><b>Admin → Commissioner</b> controls trade rules, injury level, and finance preset. Injury level affects global injury frequency; finance preset switches budget scaling curves.</p>",
            ),
            TutorialStep(
                "Finance Queue",
                "<p><b>Admin → Finance Queue</b> reviews pending finance decisions (contract extensions, arbitration, etc.) that need commissioner approval before they apply.</p>",
            ),
            TutorialStep(
                "Change Requests",
                "<p><b>Admin → Change Requests</b> lists owner-submitted bundles. Approve, reject, or requeue each one; approved bundles are applied when you click the action.</p>",
            ),
            TutorialStep(
                "Users",
                "<p><b>Admin → Users</b> manages the users.txt roster. Create admin or owner accounts, reset passwords, and assign teams.</p>",
            ),
            TutorialStep(
                "Physics Tuning",
                "<p><b>Admin → Physics Tuning</b> exposes every tunable knob from the physics engine (offense/pitching scales, discipline, fatigue, defense). Overrides are stored separately from defaults so <b>Reset</b> is always safe.</p>",
            ),
            TutorialStep(
                "Utilities",
                "<p><b>Admin → Utilities</b> hosts logos, avatars, reports, almanac, and snapshot exports. Run these before destructive admin actions to keep archival copies.</p>",
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
