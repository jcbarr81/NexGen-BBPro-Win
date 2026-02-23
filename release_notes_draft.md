## v5.0.109
- Completed backlog item 17 by adding in-app commissioner workflow tutorials in the Admin dashboard.
- Expanded Admin `Tutorials` menu into categorized entries with guided walkthroughs for league setup/manager, user management, season progression, trade/review queues, and exports/utilities.
- Added one-time onboarding behavior for new commissioners by auto-launching the Admin Dashboard Overview tutorial on first launch, with persisted flags in `config/admin_tutorial_flags.json`.
- Updated `docs/owner_admin_guide.md` with the new Admin tutorial map and onboarding behavior.
- Added focused test coverage in `tests/test_admin_tutorials.py`.

## v5.0.108
- Completed backlog item 16 by adding an `Open Folder` shortcut to export completion dialogs.
- Added shared export dialog helper in `ui/export_dialogs.py` plus desktop folder-open utility in `utils/desktop_utils.py`.
- Wired `Open Folder` success actions into owner/admin export flows: change request exports, league snapshot export, report export, playoff summary export, and finance stability JSON/CSV exports.
- Added regression coverage in `tests/test_desktop_utils.py` and `tests/test_export_dialogs.py`.

## v5.0.107
- Fixed `tests/test_season_progress_window.py` collection/runtime failures in headless environments.
- Updated `ui/season_progress_window.py` to lazy-load schedule-template dialog selection with a safe fallback to the default template when UI dialog imports are unavailable.
- Added missing `QProgressBar` stub wiring in `tests/test_season_progress_window.py` so the test harness uses intended widget doubles.
- Fixed end-of-regular-season button-state behavior in single-day simulation flow so controls and Next Phase state align with expected season-complete UI state.

## v5.0.106
- Completed backlog item 14 by enforcing commissioner-only season progression in multi-owner leagues.
- Added shared access policy helper `can_run_season_progression(...)` in `utils/league_settings.py` and wired owner/commissioner role checks through the owner dashboard flow.
- Updated `ui/owner_dashboard.py` so owner accounts in multi-owner leagues no longer get season progression controls from the Owner dashboard menu.
- Added action-level guardrails in `ui/season_progress_window.py` so progression actions (phase advance, free-agency progression, training camp, schedule generation, and simulation) are blocked when progression is not permitted.
- Updated admin team-dashboard handoff to preserve commissioner progression access when opening a team dashboard from Admin (`ui/_admin_dashboard_legacy.py`).
- Added coverage for progression-access policy decisions in `tests/test_league_settings.py`.

## v5.0.105
- Completed backlog item 13 by redesigning the League Finance Settings window for clearer configuration across simple and advanced modes.
- Reworked `ui/financial_settings_dialog.py` into a scroll-safe full-height layout so all controls remain accessible on common screen sizes without clipping.
- Grouped module controls into Owner, GM, and Governance/AI sections with inline descriptions and added live preset/module coverage guidance.
- Reorganized CPU Finance AI tuning fields into a denser two-column layout and updated section labeling for faster scanning.
- Added regression coverage in `tests/test_financial_settings_dialog.py` for module-level summary formatting.

## v5.0.104
- Completed backlog item 12 by adding live visual previews to Team Settings for both stadium selection and team uniform colors.
- Added a stadium preview panel in `ui/team_settings_dialog.py` that updates as the selected park changes and loads/generated park diagrams when available.
- Added a uniform mockup preview in `ui/team_settings_dialog.py` that updates in real time from primary/secondary color inputs.
- Added focused regression coverage in `tests/test_team_settings_dialog.py` for color normalization and park-name matching behavior.

## v5.0.103
- Completed backlog item 10 by redesigning the Trade Center layout for better readability and decision flow.
- Reorganized New Trade assets into side-by-side "You Send" / "You Receive" panels, added a concise offer summary row, and improved incoming-trade detail presentation.
- Added scrollable tab containers in `ui/trade_dialog.py` so controls remain accessible on smaller displays.
- Updated Trade Center sizing to a moderate, screen-aware default with a sensible minimum size to avoid oversized windows on larger screens and cramped layouts on smaller ones.

## v5.0.102
- Completed backlog item 9 by switching owner change request exports from loose JSON files to single ZIP bundles.
- Added bundle payload artifacts in `services/change_requests.py` (`manifest.json`, `request.json`, and per-file content under `files/...`) with filename format `change_request_<league_slug>_<team_slug>_<YYYYMMDD-HHMM>.zip`.
- Updated change-request inbox import to accept both `.zip` bundles and legacy `.json` payloads for backward compatibility.
- Updated owner/admin change-request UI copy to reference ZIP bundle flow (`ui/change_request_export_dialog.py`, `ui/change_requests_window.py`).
- Extended `tests/test_change_requests.py` to cover ZIP naming/contents plus cancel-request ZIP import.

## v5.0.101
- Closed backlog item 6 (Outstanding Test Failures) by validating and clearing the remaining unchecked targets in `docs/failing_tests.md`.
- Fixed legacy test import behavior by deferring `require_legacy_enabled(...)` in `scripts/simulate_season_avg.py` until simulation execution, while keeping helper imports usable in tests.
- Added PyQt test-stub compatibility fallbacks for missing core symbols in `ui/lineup_editor.py`, `ui/pitching_editor.py`, `ui/player_browser_dialog.py`, and `ui/components.py`.
- Marked item 6 complete in `docs/future_work.md`.

## v5.0.100
- Exposed reliever pitch-budget telemetry in owner quick metrics, including per-pitcher `available_pct` and bullpen average budget percentage.
- Updated owner dashboard/readiness UI to surface bullpen budget percentages in header and tooltip detail, plus usage-calibration status context.
- Extended `scripts/usage_calibration.py` to evaluate MLB target bands (CL/SU 60-70 G + 60-70 IP, MR 50-65 G, LR 35-50 G) and emit `data/reports/usage_calibration_summary.json` for dashboard integration.
- Added regression coverage in `tests/test_owner_quick_metrics.py` and `tests/test_usage_calibration_targets.py` for telemetry exposure, summary loading, and role target-band evaluation.
- Marked backlog item 5 (Pitch Budget Telemetry & Tuning) complete in `docs/future_work.md`.

## v5.0.99
- Completed the Unified Data Service Layer migration for standings/transactions by routing finance strategy and owner finance standings reads through `services/standings_repository.py`.
- Added `clear_transactions()` in `services/transaction_log.py` and migrated rollover/admin reset flows to clear logs through the transaction service so cache/events stay in sync.
- Replaced remaining direct roster CSV writes in contract expiry, free agency signing, and admin trade approval paths with shared roster APIs (`utils/roster_loader.save_roster` and `utils.roster_io.read_roster_csv`).
- Updated roster persistence API to accept explicit roster directories (`save_roster(..., roster_dir=...)`) for path-safe service workflows.
- Migrated additional roster consumer paths (`services/report_exporter.py`, `ui/lineup_editor.py`) away from ad-hoc roster file parsing.
- Added regression coverage in `tests/test_transaction_log_service.py` and `tests/test_free_agency.py` for transaction clearing and roster creation flows.

## v5.0.98
- Added `services/players_repository.py` to centralize player load/save operations behind the unified data service.
- Migrated core player-write call sites to use the repository layer (`playbalance/game_runner.py`, `playbalance/league_creator.py`, `services/dl_automation.py`, `ui/season_progress_window.py`, `ui/injury_center_window.py`, `ui/admin_dashboard/actions/league.py`).
- Removed manual `load_players_from_csv.cache_clear()` calls from migrated flows; player cache and `players.updated` events now refresh through repository updates.
- Added coverage in `tests/test_players_repository.py` for cache refresh and event emission on player saves.
