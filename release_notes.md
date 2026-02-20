<!-- last_build_ref: ae65adbb6cda66f4afad1ab5532c934c2399f6f6 -->
# 4.5 Release Notes (Since 4.3.41)

## League Setup & Presets
- Added rule presets, schedule templates, and quick-start league presets.
- Quick-start leagues now let admins choose schedule length instead of a locked schedule.
- Enforced league size guardrails (40-team maximum).

## Player Development & Training
- Individual Training Focus (player-level overrides) with clear source hierarchy (Player → Team → League).
- Training focus defaults apply when no per-player focus is set.
- Training focus UI refreshes player profile after save.
- Added Training Focus tutorials.

## Hall of Fame
- New Hall of Fame system with eligibility/scoring rules.
- Admin UI for tuning thresholds and rules, including “Reset to Defaults.”
- Manual add/remove override support.

## Records & Timeline
- Record notifications with pop-ups when season/career records are broken.
- Season Timeline Feed for milestones, awards, records, and special events.
- Timeline feed surfaced in Season Progress view.

## Online League Workflow
- Owner Change Requests export flow (roster/lineup/pitching/depth chart).
- Admin Change Request queue with import, approve/apply, reject, and cancel.
- File validation and team-scoped enforcement for requests.
- Audit log for approvals and applications with file hashes.

## League Syncing
- League Snapshot export (admin) for distributing updated league files.
- League Snapshot import (owners) with automatic backup.
- League ID enforcement to prevent importing the wrong league.

## Commissioner-Only Access (Multi-Owner Mode)
- New league_settings.json with owner_league mode.
- Commissioner password required for admin access in multi-owner leagues.
- Commissioner password set during league creation.
- Enforced in both login and owner dashboard admin access flow.

## Admin Utilities
- Added “Export League Snapshot” action to Admin Utilities.
- Improved admin workflows and wiring for new tools.

## Tutorial Coverage
- Added tutorials for Individual Training Focus and related admin guidance.

# ﻿4.5.9 Release Notes (Since last build 782e316)
Date: 2026-02-12

- No changes since last build and no draft notes were found.

# 4.5.19 Release Notes (Since last build 782e316)
Date: 2026-02-13

- Added an owner tutorial for submitting roster change requests from the Roster page.
- Updated owner_admin_guide with Submit Change Request usage and the new Owner Change Requests tutorial.
- Added league Trade Settings for commissioners: enable/disable all trading, allow/disallow draft-pick trades, and set maximum tradable pick years out.
- Added draft-pick trade support in the Trade Center and admin trade review flows, including persisted pick assets on trade proposals.
- Added draft-pick ownership tracking so traded picks are honored on draft day.
- Added transaction log entries for draft-pick movement on accepted trades (both owner acceptance and commissioner review).
- Added a Trade Settings option to require commissioner approval before owner-accepted trades execute.
- Updated the Trades & Transactions tutorial content to reflect draft-pick trades, commissioner approval mode, and current trade execution behavior.
- Added trade policy prompts to league creation (trading on/off, draft-pick trades, commissioner approval requirement, and tradable pick years window).
- Added Trade Settings as a quick action on the Admin home dashboard.
- Reorganized the Admin dashboard into focused areas: new Transactions and League Settings pages, a Season-focused League page, and an Assets & Exports utilities layout with streamlined Home quick actions.
- Refined Admin dashboard IA and UX: internal page key renamed to Season (with compatibility alias), clearer page labels/tooltips, and improved hub-style navigation for Transactions/Season/Draft/Settings/Assets.
- Updated admin-facing tutorials/docs to match current navigation labels (Season, Transactions, League Settings, Assets & Exports) and renamed Admin Season page code from LeaguePage/league.py to SeasonPage/season.py for clarity.

# 4.5.27 Release Notes (Since last build 782e316)
Date: 2026-02-14

- 4.5.19
- Installer now prompts on existing installs with two modes: upgrade (overwrite) or clean reinstall (auto-uninstall then install).
- Added a detailed 5.0 multi-league upgrade implementation plan document (phased roadmap, data model, migration strategy, testing gates, risks, and resume checklist) in docs/multi_league_upgrade_plan.md.
- Began multi-league Phase 1 foundation work: added league registry service (create/list/update/remove/select active) plus active-league path helpers in path_utils with backward-compatible get_data_dir behavior, and added targeted registry/path tests.
- Continued multi-league implementation: create-league now writes to `leagues/<league_id>/data`, registers/selects the active league, and saves league/trade settings directly into that league scope.
- Added an Admin `League Manager` dialog (League Settings page) to view leagues, set active league, and archive/restore league entries.
- Refactored trade settings and season context persistence to support path-scoped league data, including new targeted tests for explicit-path trade settings and league-scoped season context writes.
- Added startup/login league selection: login now lists available non-archived leagues and switches active league context before authentication.
- Login authentication now reads `users.txt` from the selected active league path (dynamic resolution instead of static module-level path).
- Added `.gitignore` entries for generated runtime artifacts: `data/record_book_snapshot.json` and `data/special_events.json`.
- Added Phase 2 legacy migration engine (`services/league_migration.py`) with one-time detection, automatic backup zip creation, root-level data migration into `leagues/<id>/data`, migration markers, and post-migration validation checks.
- Startup now runs the migration check automatically and surfaces migration completion/failure notices; failures include backup location context.
- Added `scripts/check_league_layout.py` for migration diagnostics (`--migrate` optional) and new migration regression tests in `tests/test_league_migration.py`.
- Updated data-root seeding behavior to stop restoring legacy root-level league files after multi-league registry/folders exist.
- Added Phase 3 lifecycle service (`services/league_lifecycle.py`) for league clone/archive/unarchive/delete operations with safeguards around active-league deletion and last-league protection.
- League Manager now supports clone and delete actions and routes archive/set-active flows through the lifecycle service APIs.
- Added `tests/test_league_lifecycle.py` covering clone data retagging, archive/switch guardrails, and delete safeguards.
- Added Phase 4 admin/owner UI context indicators: active league badge now appears in both Admin and Owner dashboards.
- Admin dashboard now includes a header league switch selector for faster context changes, with guided messaging when already-open windows may need reopening.
- Admin league header now refreshes automatically after create/manage-league actions to keep selector and badge in sync with registry updates.

# ﻿4.5.28 Release Notes (Since last build ae65adb)
Date: 2026-02-14

- Improved installer upgrade/clean-reinstall detection by probing multiple uninstall registry views/keys and adding {app}\\unins000.exe fallback; prompt now appears earlier in setup.

# ﻿4.5.29 Release Notes (Since last build ae65adb)
Date: 2026-02-14

- Fixed installer startup error by removing early {app} expansion and using InstallLocation-based uninstaller fallback for upgrade/clean-reinstall detection.

# ﻿4.5.30 Release Notes (Since last build ae65adb)
Date: 2026-02-14

- Changed installer upgrade/clean-reinstall UX to prompt at Ready-to-Install (Yes=Upgrade, No=Clean reinstall) so the choice appears reliably on existing installs.

# ﻿4.5.31 Release Notes (Since last build ae65adb)
Date: 2026-02-14

- Installer now prompts for upgrade vs clean reinstall as soon as the first wizard page opens, with broader detection for legacy uninstall keys.

# ﻿4.5.31 Release Notes (Since last build ae65adb)
Date: 2026-02-14

- No changes since last build and no draft notes were found.

# 4.5.32 Release Notes (Since last build ae65adb)
Date: 2026-02-14

- Fixed installer runtime crash by removing all early {app} constant expansion from startup prompt logic and using registry-only detection before initialization.

# ﻿4.5.33 Release Notes (Since last build ae65adb)
Date: 2026-02-14

- Installer existing-install detection now checks WizardDirValue for app/uninstaller files, not just uninstall registry entries, so upgrade/clean-reinstall prompt appears on systems with missing legacy registry keys.

# ﻿4.5.33 Release Notes (Since last build ae65adb)
Date: 2026-02-14

- No changes since last build and no draft notes were found.

# 4.5.41 Release Notes (Since last build ae65adb)
Date: 2026-02-16

- Added a top-level Owner Tools menu (between Tutorials and Simulate) with Submit Change Request plus quick access to lineup, pitching staff, reassign players, trade center, and team settings.
- Updated owner tutorials and guide text to reflect the new Owner Tools top menu paths (Submit Change Request, Trade Center, Lineup Editor, Pitching Staff, Reassign Players, Team Settings).
- Start Game now prompts users to either load an existing league or create a new league before login; updated README and owner/admin guide startup docs.
- Began multi-league Phase 5 isolation hardening: replaced module-level cached data paths in draft, transaction, injury/training, news, and special-event services with runtime active-league path resolution; added regression tests to verify no cross-league writes after in-process league switching.
- Continued Phase 5 isolation sweep: converted remaining UI/service module path constants to dynamic active-league proxies (hall of fame, record notifications, physics tuning overrides, league rollover, season progress, schedule/team schedule, team/league stats, and league leaders) and added regression coverage for these services under in-process league switching.
- Extended the Phase 5 sweep into playbalance modules by converting benchmark/config/player-generator data path constants to dynamic active-league proxies and adding cache refresh checks for player-generator name/rating sources when league context changes.
- Hardened remaining cross-league cache boundaries: made playbalance config benchmark/override defaults refresh per active league, keyed injury catalog and rating-distribution caches by resolved league paths, reset game-runner team/usage caches on league switches, and added expanded Phase 5 regression coverage for these scenarios plus player-loader stat/career cache path collisions.
- Added reusable automated release validation script `scripts/smoke_multi_league.py` for multi-league isolation checks (league switching, owner request/trade isolation, draft/sim side effects, and snapshot export scoping) plus a new manual post-installer checklist in `docs/post_installer_ui_checklist.md`.

# 5.0.0 Release Notes (Since last build ae65adb)
Date: 2026-02-16

- Added migration rollback utility support: `services/league_migration.py` now includes a pre-5.0 restore API, and `scripts/check_league_layout.py` now supports `--restore`, optional `--backup-path`, and `--force` overwrite mode for support-driven layout recovery.
- Added restore regression coverage in `tests/test_league_migration.py` for migrate -> restore round-trip validation.
- Updated project tracking/docs to close multi-league workstream: marked multi-league support/management done in `Features-Updates.md` and completed Phase 0-6 checkboxes in `docs/multi_league_upgrade_plan.md`.
- Bumped release versioning to `5.0.0` for the completed multi-league architecture and migration milestone.

# 5.0.75 Release Notes (Section F QA/Release Gate)
Date: 2026-02-19

- Expanded finance release validation defaults to include cross-league lifecycle/isolation suites (`tests/test_smoke_multi_league.py`, `tests/test_phase5_path_isolation.py`, `tests/test_league_registry.py`, `tests/test_season_context_paths.py`) and release-gate regression suites (`tests/test_build_release.py`, `tests/test_archive_ui_checklist.py`).
- Added optional manual-checklist enforcement to `scripts/build_release.py` via `--require-ui-checklist` and `--ui-checklist-artifact`.
- Added manual checklist archival utility `scripts/archive_ui_checklist.py` for versioned release artifacts under `reports/release_validation/checklists/`.
- Updated release workflow docs (`RELEASE.md`, `docs/post_installer_ui_checklist.md`) with archival and enforcement steps.
- Re-ran full validation gate without skips (`scripts/validate_finance_release.py --seasons 8`) with passing tests, multi-league smoke checks, and strict stability guardrails.
