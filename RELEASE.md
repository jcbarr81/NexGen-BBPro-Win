# Release Checklist

1. Update `VERSION` to the new release number.
2. Capture updates while developing (repeat as needed):
```powershell
.\.venv2\Scripts\python.exe scripts\add_release_note.py "Describe the change here"
```
3. Clean previous build outputs (optional but recommended):
```powershell
Remove-Item -Recurse -Force build, dist
```
4. Run reusable finance release validation gate (finance tests, including ledger/contracts/owner-finance suites, + multi-league finance smoke + strict stability sim):
```powershell
.\.venv2\Scripts\python.exe scripts\validate_finance_release.py --seasons 8
```
5. Run help-surface consistency validation (tutorial labels + manuals + owner/admin guide):
```powershell
.\.venv2\Scripts\python.exe scripts\validate_help_surface.py
```
6. Run Almanac export integrity coverage:
```powershell
.\.venv2\Scripts\python.exe -m pytest tests\test_almanac_exporter.py tests\test_admin_almanac_actions.py
```
7. Build the EXE + installer (runs pre-build validation by default, including help-surface validation, updates `packaging/NexGen-BBPro.iss`, and appends `release_notes.md`):
```powershell
.\.venv2\Scripts\python.exe scripts\build_release.py --clean
```
8. (Optional) Re-run full multi-league smoke validation directly:
```powershell
.\.venv2\Scripts\python.exe scripts\smoke_multi_league.py
```
9. Run manual installer/UI checklist:
- Follow `docs/post_installer_ui_checklist.md`
10. Archive checklist result with release artifacts:
```powershell
.\.venv2\Scripts\python.exe scripts\archive_ui_checklist.py --version <VERSION> --result pass --tester "<name>" --notes "<optional notes>"
```
11. (Optional but recommended for release candidates) Require checklist PASS artifact during build:
```powershell
.\.venv2\Scripts\python.exe scripts\build_release.py --clean --require-ui-checklist --ui-checklist-artifact "reports\release_validation\checklists\ui_installer_checklist_v<VERSION>_<timestamp>.md"
```
12. Run targeted tests:
```powershell
.\.venv2\Scripts\python.exe -m pytest tests\test_avatar_generator.py tests\test_avatar_generator_openai.py
```
13. Commit changes, including `VERSION`, `packaging/NexGen-BBPro.iss`, and any code updates for the release.
14. Tag and publish the release using the same version number.

## Migration Rollback (Support)

If a migrated install needs to be reverted to the pre-5.0 layout from backup:

```powershell
.\.venv2\Scripts\python.exe scripts\check_league_layout.py --restore --force
```

Optional: specify a particular backup zip:

```powershell
.\.venv2\Scripts\python.exe scripts\check_league_layout.py --restore --backup-path "C:\path\to\pre_multi_league_v1_YYYYMMDD_HHMMSS.zip" --force
```
