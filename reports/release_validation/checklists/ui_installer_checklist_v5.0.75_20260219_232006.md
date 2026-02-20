# UI/Installer Checklist Archive - v5.0.75
Generated UTC: 2026-02-19T23:20:06Z
Checklist Result: PENDING
Tester: TBD
Notes: Manual installer/UI smoke not executed yet in this environment

Source Checklist: `docs\post_installer_ui_checklist.md`

---

# Post-Installer UI Checklist

Use this after generating a new installer build to verify installer behavior, first launch flow, and core multi-league workflows.

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

## 7) Tutorials/Docs Surface
- [ ] Confirm updated tutorials are visible from Tutorials menu.
- [ ] Confirm owner/admin guide links/content match current navigation labels.

## 8) Archive Result
- [ ] Archive this checklist into `reports/release_validation/checklists/` using:
  - `.\.venv2\Scripts\python.exe scripts\archive_ui_checklist.py --version <VERSION> --result pass --tester "<name>"`
- [ ] Confirm archived file contains `Checklist Result: PASS`.
