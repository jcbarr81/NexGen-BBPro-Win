# Post-Installer UI Checklist

Use this after generating a new installer build to verify installer behavior, first launch flow, and core multi-league workflows.

## Current Regression Focus: 5.2.28 -> 5.2.30

Run this focused pass first for the changes shipped since the last build.

### A) Installer-Time Admin Password Setup (`#29`)
- [ ] Run the installer on a clean machine or VM and confirm the wizard now includes an administrator password step.
- [ ] Leave the password blank and confirm the installer blocks continuation.
- [ ] Enter mismatched password/confirmation values and confirm the installer blocks continuation with a validation message.
- [ ] Complete install with a known administrator password.
- [ ] Launch the app, click `Start Game`, create a new league, and return to login.
- [ ] Login as `admin` using the installer password and confirm access succeeds.
- [ ] Attempt login with the old default password and confirm it fails.
- [ ] Run the installer again over an existing install and choose `Upgrade`.
- [ ] Confirm the installer asks whether to keep the current administrator password or reset existing admin passwords.
- [ ] Choose `Keep existing admin passwords` and confirm the old admin password still works after upgrade.
- [ ] Run upgrade again and choose `Reset existing admin passwords`.
- [ ] Enter a new installer admin password and confirm the old admin password fails while the new one works for the existing league(s).

### B) Almanac Export (`#27`)
- [ ] Login as admin and open `Assets & Exports`.
- [ ] Run `Export Almanac (HTML)` and confirm the export completes without an error dialog.
- [ ] Confirm the export folder contains `almanac/index.html`.
- [ ] Confirm the export includes browsable section folders/pages for `seasons`, `teams`, `players`, `awards`, `postseason`, `leaders`, and `records`.
- [ ] If the active league has transaction and finance history, confirm `transactions/index.html` and `finance/index.html` also exist.
- [ ] Open `almanac/index.html` and confirm the landing page loads with working navigation links.
- [ ] Open at least one team page and confirm year-by-year history is present with links back to season pages.
- [ ] Open at least one player page and confirm career totals and season logs are present.
- [ ] Open awards, postseason, and leaders pages and confirm each renders without broken styling or missing-page errors.

### C) Season Progress Window Cleanup (`#31`)
- [ ] Open the Season Progress window.
- [ ] Confirm the window shows a single `Season Timeline` list and does not show a separate `Timeline Feed` section.
- [ ] Confirm the main simulation controls still appear and align correctly after the feed removal.
- [ ] Run at least one simulation action (`Simulate Day`, `Simulate Week`, or equivalent for the current phase).
- [ ] Confirm status text, notes, and timeline milestones still update without layout gaps or overlapping controls.

## 1) Installer Flow
- [ ] Run installer on a machine with no existing install; confirm install completes with no runtime/setup errors.
- [ ] Confirm app version shown in installer window matches `VERSION`.
- [ ] Confirm desktop shortcut option works when checked.
- [ ] Run installer again on a machine with an existing install.
- [ ] Confirm upgrade/clean-reinstall choice prompt appears.
- [ ] Choose `Upgrade`; confirm install completes and app launches.
- [ ] Run installer again; choose `Clean reinstall`; confirm uninstall executes and reinstall completes.
- [ ] Confirm app appears correctly in Windows Apps/Programs list after install.

## 2) First Launch + League Entry
- [ ] Launch app and click `Start Game`.
- [ ] Confirm choice appears for `Load Existing League` vs `Create New League`.
- [ ] Create a new league and complete setup.
- [ ] Return to start and load an existing league.
- [ ] Confirm login league selector shows expected available leagues.

## 3) Admin Multi-League Behavior
- [ ] Login as admin and open League Manager.
- [ ] Create a second league.
- [ ] Switch active league via header selector.
- [ ] Confirm active league badge updates.
- [ ] Confirm key league data differs between leagues (team name/players/schedule).

## 4) Owner Workflow + Owner Tools Menu
- [ ] Login as owner.
- [ ] Confirm `Owner Tools` menu appears between `Tutorials` and `Simulate`.
- [ ] Open `Submit Change Request` from Owner Tools and export a request bundle.
- [ ] Confirm request file is created in league-scoped exports path.
- [ ] Confirm lineup/pitching/reassign/trade/team-settings entries in Owner Tools open correctly.

## 5) League Isolation Spot-Checks
- [ ] In League A, submit a change request and create at least one trade.
- [ ] Switch to League B and confirm those items are not present.
- [ ] In League B, simulate/progress draft state.
- [ ] Switch back to League A and confirm schedule/progress are unchanged.

## 6) Snapshot Export/Import
- [ ] Export snapshot from League A.
- [ ] Export snapshot from League B.
- [ ] Confirm files are separate and contain different league content.
- [ ] Attempt import of a mismatched snapshot and confirm league-ID protection/validation message appears.
- [ ] Import a matching snapshot and confirm backup is created before import.

## 7) Almanac Export
- [ ] Login as admin and open `Assets & Exports`.
- [ ] Run `Export Almanac (HTML)`.
- [ ] Confirm the export folder contains `almanac/index.html` plus section folders for seasons, teams, players, awards, postseason, leaders, records, and `transactions` / `finance` when the active league has that data.
- [ ] Open the Almanac landing page and confirm section links resolve without broken pages.

## 8) Tutorials/Docs Surface
- [ ] Confirm updated tutorials are visible from Tutorials menu.
- [ ] Confirm owner/admin guide links/content match current navigation labels.
- [ ] Confirm `reports/release_validation/help_surface_validation.json` shows `"status": "pass"` for this build.

## 9) Theme Family Coverage
- [ ] In Owner dashboard, switch `View -> Theme Family` between `Classic` and `Enhanced Warm`.
- [ ] In Owner dashboard, run `Toggle Light/Dark` in both families and confirm no unreadable text on Home, Roster, Team, Transactions, and League pages.
- [ ] Open Position Players and Pitchers dialogs, toggle theme, and confirm table/header/footer restyle immediately.
- [ ] In Admin dashboard, switch `Theme Family` and `Toggle Light/Dark`, then confirm nav icons and Admin Home action icons update.
- [ ] With both Owner and Admin windows open, toggle theme in one window and confirm the other open window updates without restart.

## 10) Archive Result
- [ ] Archive this checklist into `reports/release_validation/checklists/` using:
  - `.\.venv2\Scripts\python.exe scripts\archive_ui_checklist.py --version <VERSION> --result pass --tester "<name>"`
- [ ] Confirm archived file contains `Checklist Result: PASS`.

