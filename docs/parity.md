# PyQt → Electron parity checklist

Tracks which screens/workflows from the legacy PyQt app have been ported
into the Electron desktop shell. Updated as we ship. Both apps share
`%LOCALAPPDATA%\NexGen-BBPro\data`, so you can run them side by side and
cross-check results until we cut over.

## Daily workflow (owner/admin)

| Feature | Electron | PyQt | Notes |
|---|---|---|---|
| Login | ✅ | ✅ | session token + bcrypt |
| League picker | ✅ | ✅ | `/leagues/active` |
| Dashboard (hero, record, division, widgets) | ✅ | ✅ | bullpen, matchup, hot/cold, leaders included |
| Season (sim day/week/month/to-draft/to-playoffs) | ✅ | ✅ | shared `season_state.json` |
| Roster (view + moves + cuts) | ✅ | ✅ | DL tiers preserved |
| Lineup editor (vs L/RHP) + pitching staff | ✅ | ✅ | autofill via `lineup_autofill` |
| Training focus | ✅ | ✅ | per-team override vs league default |
| Injuries (DL / IR / day-to-day) | ✅ | ✅ | return dates + eligibility |
| Free agency (list + sign) | ✅ | ✅ | logs "sign" transaction |
| Team settings (colors, stadium, strategy, auto-reassign) | ✅ | ✅ | full park browser with on-demand diagrams |
| Depth chart editor | ✅ | ✅ | ordered priority list per position, feeds autofill + injury replacement |
| Team stats drill-down | ✅ | ✅ | tabs for batting/pitching/team totals on team detail page |
| Finance (snapshot + transactions) | ✅ | ✅ | per-team |
| Submit change request (owner-side export ZIP) | ✅ | ✅ | `/teams/{id}/change-requests/*` |

## League views

| Feature | Electron | PyQt | Notes |
|---|---|---|---|
| Standings (division grouped) | ✅ | ✅ | linked rows → team detail |
| Leaders (batting + pitching) | ✅ | ✅ | MLB qualifier rules |
| Stats (per-player + team totals) | ✅ | ✅ | sortable tabs |
| Players browser (filter by team/pos/role) | ✅ | ✅ | |
| Teams directory | ✅ | ✅ | grouped by division |
| Schedule | ✅ | ✅ | played row links boxscore |
| Playoffs bracket | ✅ | ✅ | boxscore links per game |
| League history | ✅ | ✅ | champions + MVP + Cy Young + artifact paths |
| Hall of Fame | ✅ | ✅ | admin can induct/remove |
| Record book | ✅ | ✅ | league (batting/pitching/team) + per-team |

## Transactions

| Feature | Electron | PyQt | Notes |
|---|---|---|---|
| Trades (list + propose + accept/reject/withdraw) | ✅ | ✅ | roster swap + pick transfer + log |
| Draft (state + history) | ✅ | ✅ | |
| Activity feed (full ledger) | ✅ | ✅ | |
| News feed | ✅ | ✅ | filter + parse |

## Admin / commissioner

| Feature | Electron | PyQt | Notes |
|---|---|---|---|
| Admin users (CRUD) | ✅ | ✅ | bcrypt, team conflict check |
| Commissioner settings (trade + injury + finance) | ✅ | ✅ | |
| League command center | ✅ | ✅ | |
| Finance queue review + apply | ✅ | ✅ | |
| Change requests queue | ✅ | ✅ | approve/reject/requeue |
| Utilities: logos + avatars + reports + almanac + snapshot | ✅ | ✅ | wired through `/exports/*` |
| Boxscore viewer | ✅ | ✅ | sandboxed iframe |
| Physics tuning editor | ✅ | ✅ | reuses `_TUNING_SECTIONS` spec from PyQt — single source of truth |
| League creation wizard + first-run bootstrap | ✅ | ✅ | multi-step flow, forces admin password when `users.txt` default |
| Offseason finance flow (checklist + pipeline + stage mark) | ✅ | ✅ | admin checklist drives `services.offseason_finance_flow` |
| Roster auto-assign (single + league-wide) | ✅ | ✅ | admin bulk reassign |
| Finance stability scenario tester | ✅ | ✅ | preset comparison + guardrail evaluator |

## Still PyQt-only (accepted debt)

- **Live pitch-by-pitch sim UI** — `LiveGamePage` exists (demo) but hidden
  from nav. Day-at-a-time sim is the real workflow.

## Cutover criteria

1. All "Daily workflow" rows confirmed ✅ by a user running both apps side
   by side for one in-season week.
2. Phase 7 installer builds clean on a fresh Win11 VM.
3. No orphaned Python processes after `npm run dev` exit or installer
   uninstall.
4. `pytest tests/test_api_smoke.py` green on every PR.

When all four hold: tag `pyqt-final`, remove `ui/`, `main.py`, `PyQt6`,
`pygame` from `requirements-dev.txt`, and update
`build_exe.py` / `NexGen-BBPro.spec` to target the sidecar only.
