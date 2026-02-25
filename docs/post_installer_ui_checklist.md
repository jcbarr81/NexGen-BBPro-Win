# Post-Installer UI Checklist

Use this after generating a new installer build to verify installer behavior, first launch flow, and core multi-league workflows.

## 1) Installer Flow
x- [ ] Run installer on a machine with no existing install; confirm install completes with no runtime/setup errors.
x- [ ] Confirm app version shown in installer window matches `VERSION`.
x- [ ] Confirm desktop shortcut option works when checked.
x- [ ] Run installer again on a machine with an existing install.
x- [ ] Confirm upgrade/clean-reinstall choice prompt appears.
x- [ ] Choose `Upgrade`; confirm install completes and app launches.
x- [ ] Run installer again; choose `Clean reinstall`; confirm uninstall executes and reinstall completes.
x- [ ] Confirm app appears correctly in Windows Apps/Programs list after install.

## 2) First Launch + League Entry
x- [ ] Launch app and click `Start Game`.
x- [ ] Confirm choice appears for `Load Existing League` vs `Create New League`.
x- [ ] Create a new league and complete setup.
x- [ ] Return to start and load an existing league.
x- [ ] Confirm login league selector shows expected available leagues.

## 3) Admin Multi-League Behavior
x- [ ] Login as admin and open League Manager.
x- [ ] Create a second league.
x- [ ] Switch active league via header selector.
x- [ ] Confirm active league badge updates.
x- [ ] Confirm key league data differs between leagues (team name/players/schedule).

## 4) Owner Workflow + Owner Tools Menu
x- [ ] Login as owner.
x- [ ] Confirm `Owner Tools` menu appears between `Tutorials` and `Simulate`.
x- [ ] Open `Submit Change Request` from Owner Tools and export a request bundle.
x- [ ] Confirm request file is created in league-scoped exports path.
x- [ ] Confirm lineup/pitching/reassign/trade/team-settings entries in Owner Tools open correctly.

## 5) League Isolation Spot-Checks
x- [ ] In League A, submit a change request and create at least one trade.
x- [ ] Switch to League B and confirm those items are not present.
x- [ ] In League B, simulate/progress draft state.
x- [ ] Switch back to League A and confirm schedule/progress are unchanged.

## 6) Snapshot Export/Import
x- [ ] Export snapshot from League A.
x- [ ] Export snapshot from League B.
x- [ ] Confirm files are separate and contain different league content.
x- [ ] Attempt import of a mismatched snapshot and confirm league-ID protection/validation message appears.
x- [ ] Import a matching snapshot and confirm backup is created before import.

## 7) Tutorials/Docs Surface
- [ ] Confirm updated tutorials are visible from Tutorials menu.
- [ ] Confirm owner/admin guide links/content match current navigation labels.
- [ ] Confirm `reports/release_validation/help_surface_validation.json` shows `"status": "pass"` for this build.

## 8) Theme Family Coverage
- [ ] In Owner dashboard, switch `View -> Theme Family` between `Classic` and `Enhanced Warm`.
- [ ] In Owner dashboard, run `Toggle Light/Dark` in both families and confirm no unreadable text on Home, Roster, Team, Transactions, and League pages.
- [ ] Open Position Players and Pitchers dialogs, toggle theme, and confirm table/header/footer restyle immediately.
- [ ] In Admin dashboard, switch `Theme Family` and `Toggle Light/Dark`, then confirm nav icons and Admin Home action icons update.
- [ ] With both Owner and Admin windows open, toggle theme in one window and confirm the other open window updates without restart.

## 9) Archive Result
- [ ] Archive this checklist into `reports/release_validation/checklists/` using:
  - `.\.venv2\Scripts\python.exe scripts\archive_ui_checklist.py --version <VERSION> --result pass --tester "<name>"`
- [ ] Confirm archived file contains `Checklist Result: PASS`.
