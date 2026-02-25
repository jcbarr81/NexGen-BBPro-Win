<!-- last_build_ref: b22da7bb8efc722314c9cfeb80a9a97f4e9c6980 -->
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

# 5.0.75 Release Notes (Since last build ae65adb)
Date: 2026-02-20

- 5.0.75
- Owner page navigation now renders the selected page before showing the related tutorial dialog, so users can see the screen context first.
- Added `tests/test_owner_dashboard_tutorial_order.py` to lock navigation-vs-tutorial ordering behavior.
- Added detailed two-layer financial system implementation plan in `docs/financial_system_plan.md`, including global on/off controls, per-module level toggles, presets/custom behavior, data model, service/UI architecture, phased rollout, migration, and testing strategy.
- Started financial system implementation Phase A: added `services/finance_settings.py` with league-scoped global on/off controls, preset application (`off/simple/standard/mlb_like/custom`), per-module level normalization, and enforcement-mode persistence.
- Added `tests/test_finance_settings.py` to cover defaults, preset application, custom module updates, global-off behavior, and per-league isolation for financial settings.
- Added admin UI wiring for finance controls: new `Financial System Settings` action on Admin -> League Settings and a `ui/financial_settings_dialog.py` editor supporting global on/off, preset selection, enforcement mode, and per-module level configuration.
- Added `tests/test_financial_settings_dialog.py` headless import coverage for the new finance dialog.
- Added finance baseline file seeding for each league (`league_financial_settings.json`, `team_financials.json`, `contracts.json`, `financial_transactions.csv`) with safe defaults and team-aware initialization.
- New startup maintenance pass now ensures finance baseline files across registered leagues, and league creation now seeds financial files immediately for newly created leagues.
- Expanded `tests/test_finance_settings.py` with baseline seeding coverage (missing-file bootstrap, existing-data preservation, and multi-league seeding).
- Added `services/payroll_engine.py` for league-scoped annual/monthly payroll rollups from `contracts.json`.
- Added `services/owner_finance_engine.py` with owner-finance projections and idempotent monthly finance cycle application (ledger-guarded per period).
- Added owner-facing `Owner Tools -> Finance Snapshot` readout showing current cash/debt plus projected monthly revenue, expenses, budgets, and net impact.
- Added a new owner tutorial entry: `Tutorials -> Finance Snapshot`, and updated dashboard/tutorial text to include the new Owner Tools finance action.
- Updated owner documentation (`docs/owner_admin_guide.md`) with Finance Snapshot workflow and tutorial references.
- Added `tests/test_owner_finance_engine.py` covering payroll totals, finance-off behavior, and monthly finance cycle idempotency.
- Added monthly finance period helpers in `services/owner_finance_engine.py` (`period_keys_from_dates` and `apply_monthly_owner_finance_for_dates`) to resolve unique `YYYY-MM` cycles from simulated dates.
- Season simulation now auto-applies owner finance cycles for months covered during each simulation span (`ui/season_progress_window.py`), with idempotent ledger guarding to prevent duplicate postings.
- Expanded owner finance tests to cover monthly period extraction and multi-month cycle idempotency when applying finance from simulated date ranges.
- Added a dedicated owner Finance dashboard page (`ui/owner_finance_page.py`) with current finance status, monthly projections, and recent transaction history.
- Owner dashboard now includes a sidebar `Finance` navigation tab and `Owner Tools -> Open Finance Page` shortcut for direct access to finance workflows.
- Added finance ledger query helper `list_team_financial_transactions(...)` in `services/owner_finance_engine.py` for owner-facing history views.
- Updated Finance tutorial content and owner documentation to reflect the dedicated Finance page experience.
- Added `tests/test_owner_finance_page.py` headless import coverage and expanded owner finance tests for ledger history ordering.
- Added a Home dashboard Finance Summary card with cash/debt/net monthly projection highlights, budget targets, and one-click actions to open the Finance page or launch the finance tutorial.
- Updated Owner Home responsive card layout to include the new Finance Summary section across wide/medium/narrow breakpoints.
- Enhanced the Home Finance Summary card with color-coded monthly net status (green positive, red negative, gold neutral) for faster at-a-glance financial health checks.
- Added `services/contracts_service.py` for contract lifecycle operations (load/save, create/update, free-agent signing defaults, transfer across teams, and removal).
- Owner free-agent signing now persists roster changes and writes a contract entry automatically for the signed player.
- Owner and admin trade acceptance flows now transfer player contract ownership between teams alongside roster movement, keeping payroll data aligned with transactions.
- Added `tests/test_contracts_service.py` to cover contract creation, transfer behavior, default salary estimation, and removal.
- Added `services/payroll_policy.py` with payroll rule evaluation helpers for free-agent signings and trade execution (`warn`/`block`) based on league financial settings.
- Owner free-agent signing now runs payroll policy checks before committing roster/contract updates, including override prompts when policy mode is warning.
- Owner and admin trade acceptance now run payroll policy checks before execution and block or prompt based on configured enforcement mode.
- Added `tests/test_payroll_policy.py` covering block/warn behavior, rules-off bypass, and trade payroll delta enforcement.
- Added trade preflight payroll indicators in both owner and admin trade dialogs so users can see pass/warn/block status before submitting or approving trades.
- Owner free-agent signing now shows a preflight confirmation with estimated salary and payroll policy summary before finalizing the signing action.
- Added offseason contract rollover in `services/contracts_service.py`: contract years now decrement when a season rolls over, and expired contracts are removed from payroll commitments.
- Wired contract rollover into `services/league_rollover.py` so offseason transitions automatically carry forward active deals and expire one-year contracts.
- Season rollover completion messaging now includes a contract summary (carried vs expired) for better visibility in the Season Progress flow.
- Owner Finance page now shows annual payroll commitments and active/expiring contract counts in the status panel.
- Expanded regression coverage in `tests/test_contracts_service.py` and `tests/test_league_rollover.py` for contract year decrement/expiration and rollover integration behavior.
- Offseason contract rollover now also releases expired-contract players from team roster CSVs, records `contract_expired` transactions, and reports how many players were moved to free agency.
- Added `services.free_agency.list_unsigned_players_from_files(...)` to compute unsigned players directly from `players.csv` + roster files, and updated Free Agency views to use league data instead of empty in-memory placeholders.
- Expanded free-agency regression coverage in `tests/test_free_agency.py` and added roster-release assertions in rollover/contract tests.
- Added `services/offseason_finance_flow.py` to run an offseason finance pipeline on season rollover: year-end finance snapshot generation, arbitration salary updates, and team finance ledger reset for the next season year.
- League rollover now executes the offseason finance pipeline and returns structured `finance_rollover` summary data alongside contract rollover metadata.
- Season rollover completion messaging now includes offseason finance results (arbitration awards, payroll delta, and number of team ledgers reset).
- Added `tests/test_offseason_finance_flow.py` and expanded `tests/test_league_rollover.py` to cover snapshot creation, arbitration processing, and next-year finance reset behavior.
- Added idempotent offseason finance state tracking (`offseason_finance_state.json`) so rerunning the offseason workflow for the same ended season does not double-apply arbitration or finance resets.
- Added `collect_offseason_finance_overview(...)` in `services/offseason_finance_flow.py` for admin workflow status reporting (phase, snapshot presence, contract/arb candidates, and unsigned-player counts).
- Added an Admin Season action: `Open Offseason Finance Workflow`, with a new `ui/offseason_finance_dialog.py` that provides refresh, run-workflow, and free-agency access controls for offseason finance operations.
- Expanded `tests/test_offseason_finance_flow.py` to cover idempotent reruns and overview reporting for contract/arbitration/free-agency counts.
- Added staged offseason finance checklist support in `services/offseason_finance_flow.py` via `get_offseason_checklist(...)` and `mark_offseason_stage(...)` with ordered gates: pipeline run, contract review, arbitration review, budget review, free-agency kickoff, and finalize.
- Offseason finance state now preserves per-stage completion flags and exposes the next required stage so admin workflows can enforce step-by-step progression instead of ad-hoc execution.
- Updated `ui/offseason_finance_dialog.py` to display checklist status, run the pipeline only when required, and complete the next stage in order with clear action labels/tooltips.
- Added `tests/test_offseason_finance_dialog.py` headless import coverage and expanded offseason-flow tests for checklist ordering and stage gating.
- Updated `docs/owner_admin_guide.md` with admin instructions for the new Season -> Offseason Finance Workflow checklist flow.
- Added `get_offseason_stage_details(...)` in `services/offseason_finance_flow.py` to provide stage-level review datasets: contract expirations, arbitration award details, and budget deltas by team/category.
- `ui/offseason_finance_dialog.py` now renders stage-specific review panes (tabs/tables) for Contract Expirations, Arbitration Details, and Budget Deltas so admins can validate each finance stage before marking it complete.
- Expanded offseason finance tests to assert stage-detail payloads (arbitration detail rows and budget delta rows) and retained checklist stage-order enforcement coverage.
- Updated admin guide text to document the new in-dialog offseason finance review tabs.
- Added an in-dialog **Action Readiness** blocker panel in `ui/offseason_finance_dialog.py` that explicitly shows the next required stage and why run/complete actions are blocked when prerequisites are not met.
- Expanded offseason finance dialog tests to validate blocker text generation and stage-precondition messaging.
- Enhanced CPU arbitration decisions so AI teams better retain stars and avoid escalating salary commitments for weak performers.
- Added CPU non-tender handling for very high-cost underperformers during offseason arbitration, including automatic contract removal and roster release to free agency.
- Expanded offseason finance regression tests for CPU decisioning (`tests/test_offseason_finance_flow.py`) to lock non-tender/release behavior.
- Added `services/finance_ai.py` with team strategy profiles (`contend`/`balanced`/`rebuild`) and budget tone modeling to drive CPU financial decisioning.
- Offseason arbitration now uses finance-AI strategy decisions for CPU teams, including profile-aware raise targets and non-tender behavior with decision metadata.
- Added `tests/test_finance_ai.py` to cover strategy classification, star retention logic, high-cost underperformer non-tendering, and free-agent salary-band guidance.
- Added strategy-aware CPU free-agency bid generation in `services/finance_ai.py` (`build_cpu_free_agent_bid_book`) so AI offers now reflect team profile, budget tone, payroll limits, and player quality.
- Updated `ui/free_agency_window.py` to load teams from the active league path and simulate bids with finance-AI behavior (with fallback legacy random bids when no AI bids are produced).
- Updated `services/contract_negotiator.py` to accept team-id keyed bid maps in addition to team objects, improving compatibility with strategy-generated bid books.
- Added `tests/test_contract_negotiator.py` and expanded `tests/test_finance_ai.py` to validate strategy-aware bid behavior and team-id keyed bid evaluation.
- Added non-UI automated CPU free-agency execution via `services/free_agency.py::run_cpu_free_agency_round(...)`, including roster placement, contract creation, and transaction logging for AI signings.
- Updated preseason Free Agency step in `ui/season_progress_window.py` to run the CPU free-agency round before presenting remaining unsigned players.
- Expanded `tests/test_free_agency.py` with an integration-style CPU signing test and retained passing coverage across free-agency/finance arbitration flows.
- Added market-sized multi-round CPU free-agency orchestration in `services/free_agency.py` (`estimate_cpu_free_agency_rounds` + `run_cpu_free_agency_market`) so round count scales with unsigned-player volume and available CPU teams.
- Updated preseason free-agency workflow (`ui/season_progress_window.py`) to use the multi-round market runner and report signed-player totals with rounds executed.
- Expanded free-agency tests to validate round-scaling behavior and multi-round market execution for large unsigned-player pools.
- Added league-scoped CPU finance AI tuning in `services/finance_settings.py` (`finance_ai_tuning`) with normalized defaults/persistence so arbitration and free-agency thresholds are commissioner-configurable.
- Refactored `services/finance_ai.py` to consume per-league tuning values (star/underperformer/high-cost thresholds, max arbitration raise cap, and free-agency salary/quality thresholds) instead of fixed hard-coded constants.
- Updated offseason arbitration (`services/offseason_finance_flow.py`) and financial settings UI (`ui/financial_settings_dialog.py`) to pass/edit CPU finance AI tuning values.
- Expanded regression coverage in `tests/test_finance_settings.py` and `tests/test_finance_ai.py` for tuning persistence, normalization/clamping, and decision-behavior overrides.
- Added `services/finance_stability.py` with multi-season finance stability simulation, season-level metric collection, and guardrail evaluation (debt/cash/unsigned/payroll spread/star-retention checks).
- Added `scripts/sim_finance_stability.py` command-line runner to execute headless 5+ season stability sims and export JSON/CSV reports for calibration.
- Updated free-agency and offseason financial simulation paths to support stability-cycle orchestration and deterministic seeded CPU market runs.
- Added `tests/test_finance_stability.py` for guardrail-failure detection and end-to-end stability simulation metric generation.
- Added admin-facing Finance Stability Simulation dialog (`ui/finance_stability_dialog.py`) with run controls, guardrail threshold inputs, and JSON/CSV export actions.
- Added League Settings action wiring for the new simulation dialog (`ui/admin_dashboard/pages/league_settings.py` and `ui/_admin_dashboard_legacy.py`).
- Added headless import coverage in `tests/test_finance_stability_dialog.py`.
- Enhanced Finance Stability dialog with a one-click preset comparison workflow (`Compare Core Presets`) that runs `simple`, `standard`, and `mlb_like` in one pass.
- Added a `Current League Preset (Recommended)` profile selector for single-run simulations and an option to include current league settings in comparison runs.
- Added isolated preset-comparison execution in `services/finance_stability.py` (`run_finance_stability_preset_comparison`) so profile comparisons use cloned data and do not mutate the active league.
- Expanded stability tests (`tests/test_finance_stability.py`) to cover multi-profile comparison output.
- Added reusable finance release validation command `scripts/validate_finance_release.py` to run the targeted finance test suite plus strict multi-season stability simulation with JSON/CSV artifacts.
- Updated `scripts/build_release.py` to run finance release validation as a pre-build quality gate by default (with `--skip-validation` and validation tuning flags for controlled overrides).
- Updated `RELEASE.md` with the new validation step and clarified that the release build command now runs pre-build finance validation automatically.
- Updated `README.md` with a release-validation quick commands section covering finance gate execution, standard build flow, and troubleshooting `--skip-validation` usage.
- Reorganized the owner in-game `Tutorials` menu into category submenus (`Getting Started`, `Roster & Team`, `Development`, `Transactions & Finance`, `Commissioner`) for cleaner navigation.
- Expanded `scripts/smoke_multi_league.py` with a new finance isolation check that validates league-scoped financial settings and monthly finance-cycle writes do not leak across leagues.
- Added `tests/test_smoke_multi_league.py` to assert the smoke runner includes and passes the `finance_data_isolation` check.
- Updated `scripts/validate_finance_release.py` to run `scripts/smoke_multi_league.py` as part of the default finance release validation gate and emit `reports/release_validation/multi_league_smoke_release.json`.
- Added `--skip-smoke` to `scripts/validate_finance_release.py` for controlled troubleshooting bypasses.
- Added `tests/test_validate_finance_release.py` to verify smoke-check invocation/default behavior in the release validator.
- Updated release docs (`README.md` and `RELEASE.md`) to reflect that multi-league finance smoke validation is now included in the finance validation gate.
- Upgraded the owner Finance page to a two-tab hub: `Owner Ops` (cashflow/projections/ledger) and `GM/Coach Ops` (module status, payroll/contracts, arbitration/free-agency queue visibility, quick actions).
- Added `Owner Tools -> Free Agency Hub...` and wired owner dashboard support for opening Free Agency directly from finance workflows.
- Updated owner Finance tutorial copy and owner guide documentation to match the new Owner Ops + GM/Coach Ops layout and Free Agency Hub entry point.
- Expanded `tests/test_owner_finance_page.py` with arbitration-threshold and level-label helper coverage for the new finance hub behavior.
- Renamed owner finance entry points from `Open Finance Page` to `Open Finance Hub` in both the Owner Tools menu and Home dashboard quick action.
- Renamed the Tutorials menu finance item to `Finance Hub Overview` and updated finance tutorial wording to consistently reference Owner Ops/GM-Coach Ops tabs.
- Added admin-side finance tutorial guidance (Admin Tools Overview) to align commissioner workflow language with Owner Ops + GM/Coach Ops terminology.
- Updated admin Season page tooltip and owner/admin guide wording to use `Finance Hub` naming consistently.
- Added `services/gm_finance_queue.py` with league-scoped arbitration and free-agency queue builders, persisted team decision storage, and helpers to queue recommended actions.
- Upgraded the Owner Finance `GM/Coach Ops` tab with actionable controls to queue recommended arbitration and free-agency decisions, plus queued-state visibility in the queue panel.
- Updated Finance Hub tutorial and owner guide docs to explain recommended queue actions alongside Trade Center and Free Agency Hub execution workflows.
- Added `tests/test_gm_finance_queue.py` covering arbitration queue generation, free-agency target queue generation, recommended decision persistence, and disabled-module behavior.
- Added league-mode-aware review status in GM finance decision persistence: single-player decisions default to `approved_local`, while multi-owner (`owner_league`) decisions default to `pending_commissioner`.
- Updated GM/Coach Ops UI to reflect league mode, show pending vs approved queue counts, and auto-switch action button wording between queue vs apply language.
- Expanded GM finance queue tests with multi-owner review-status coverage and updated docs/tutorial messaging for single-player auto-approval vs multi-owner commissioner review.
- Added commissioner review tooling for owner GM finance decisions: new pending-queue listing and review-status update helpers in `services/gm_finance_queue.py` (`list_pending_queue_decisions`, `set_queue_review_status`).
- Added `ui/gm_finance_queue_dialog.py` and wired Admin `Transactions -> Review GM Finance Queue` for approve/reject handling of pending multi-owner finance decisions.
- Updated GM/Coach queue status handling to surface commissioner-approved/rejected states, including owner-facing pending/approved/rejected counters.
- Added `tests/test_gm_finance_queue_dialog.py` and expanded queue tests to cover pending-listing and commissioner approval transitions.
- Completed GM finance queue execution pass: approved arbitration/free-agency decisions can now be applied in bulk (including admin dialog `Apply Approved Decisions` action), with persisted execution outcomes and applied timestamps per queue item.
- Fixed contract-state consistency when mixing approved salary updates, non-tenders, and free-agent target signings in one apply pass to prevent stale contract payload overwrites.
- Expanded `tests/test_gm_finance_queue.py` with execution-path coverage for mixed arbitration apply flows and commissioner-approved free-agency target signing.
- Added offseason workflow integration for owner leagues: new checklist stage `Resolve GM Finance Queue` now requires commissioner queue resolution before moving past finance reviews.
- Offseason stage execution now applies approved GM queue decisions in bulk and blocks stage completion until pending commissioner items and approved-not-applied items are fully cleared.
- Added GM queue visibility to offseason overview/status payloads (pending/approved/applied/rejected counts) and surfaced those counts in the Offseason Finance dialog for multi-owner leagues.
- Expanded offseason finance regression coverage with owner-league checklist tests that validate GM queue stage blocking and approved-decision application behavior.
- Added reusable GM finance queue summary helper (`summarize_queue_decisions`) in `services/gm_finance_queue.py` so admin/offseason workflows can consume consistent pending/approved/applied/rejected totals.
- Updated Admin `Transactions` page GM Finance card to show live multi-owner queue status counts (pending, approved-not-applied, applied, rejected) and auto-refresh after closing the GM Queue review dialog.
- Refactored offseason finance overview/checklist to reuse shared GM queue summary logic instead of maintaining duplicate queue-state parsing.
- Added regression coverage in `tests/test_gm_finance_queue.py` for queue summary counting and new `tests/test_admin_transactions_page.py` helper-format tests for admin GM queue status messaging.
- Added Admin Home dashboard visibility for GM finance queue state: new `Pending GM Queue` league metric plus a queue status summary line in Priority Queues.
- Added a one-click `Review GM Finance Queue` shortcut button to the Admin Home Priority Queues card.
- Updated admin metrics gathering to read teams/players from the active league data path and include GM queue metrics (`gm_queue_pending`, `gm_queue_approved_unapplied`, owner-league requirement flag).
- Added `tests/test_admin_home_page.py` coverage for home-page metric/status formatting helpers.
- Updated Offseason Finance dialog with a direct `Open GM Finance Queue` action to keep commissioner workflow in one place during offseason checklist execution.
- Added GM queue hint logic in the offseason dialog so button enablement/tooltip reflects multi-owner requirement and current pending vs approved-not-applied queue state.
- Improved `gm_finance_review` stage completion messaging to report applied/skipped decision counts when the stage resolves queue actions.
- Expanded `tests/test_offseason_finance_dialog.py` with GM queue hint coverage (single-player disabled state, pending state, and clear state).
- Added reusable cross-team GM queue listing API (`list_queue_decisions`) in `services/gm_finance_queue.py`, with optional filters and pending-first ordering for commissioner workflows.
- Extended offseason stage-details payload to include GM queue rows (`gm_finance_queue`) so the Offseason Finance dialog can show queue state in-line without leaving the workflow.
- Added a new `GM Queue` review tab in `ui/offseason_finance_dialog.py` with team/queue/item/action/status/applied/updated columns for at-a-glance commissioner validation during offseason execution.
- Expanded regression coverage in `tests/test_gm_finance_queue.py` and `tests/test_offseason_finance_flow.py` for cross-team queue listing behavior and offseason detail payload inclusion of GM queue rows.
- Added inline GM queue controls directly in the Offseason Finance dialog (`Approve Selected`, `Reject Selected`, `Apply Approved`) so commissioners can resolve queue items without opening a separate dialog.
- Added queue-action enable/tooltip state logic (`_gm_inline_action_state`) tied to league mode, selected row status, and approved-not-applied counts.
- Added offseason GM queue selection handlers for inline commissioner status updates and in-dialog bulk apply feedback (applied/skipped summary).
- Expanded `tests/test_offseason_finance_dialog.py` with inline-action state coverage for pending multi-owner and single-player-disabled scenarios.
- Added GM Queue filter/search controls in the Offseason Finance dialog tab (team, queue type, status, and text query) with a clear-filters action for faster commissioner triage on large queues.
- Added reusable GM queue row filtering helper (`_filter_gm_queue_rows`) and wired the tab to show filtered count vs total count (`GM Queue (visible/total)`).
- Updated GM queue row-selection behavior to operate on filtered rows so inline approve/reject/apply actions target the correct decision after filtering.
- Expanded `tests/test_offseason_finance_dialog.py` with GM queue filter coverage (team/status filtering and text search).
- Enhanced MLB-like payroll policy behavior with estimated CBT tax tiers on over-threshold payrolls and surfaced those estimates in payroll warning/block messages.
- Added MLB-like payroll floor enforcement for payroll-dump moves (negative payroll deltas that push a team below the configured floor) under warn/block policy modes.
- Added reusable `estimate_mlb_like_cbt_tax(...)` helper in `services/payroll_policy.py` and expanded policy violation metadata (`kind`, `estimated_tax`) for richer commissioner/owner feedback.
- Expanded `tests/test_payroll_policy.py` with MLB-like tax/floor coverage and tiered tax helper assertions.
- Added advanced contract-service groundwork in `services/contracts_service.py`: support for normalized option/incentive terms, contract extensions, option decision updates, and payroll-value calculation that includes expected incentives.
- Enhanced contract rollover to process option outcomes: exercised options now carry contracts forward with option salary, declined options can expire with buyout tracking, and rollover summary now reports exercised/declined/buyout totals.
- Added financial ledger posting for option buyouts (`contract_buyout`) and incentive reset behavior on offseason rollover.
- Updated payroll calculations to include expected incentive value in annual/monthly payroll totals.
- Expanded contract/payroll tests (`tests/test_contracts_service.py`, `tests/test_owner_finance_engine.py`) for extension flow, option exercise/decline rollover behavior, buyout ledger output, and incentive-aware payroll totals.
- Expanded Finance Hub tutorial guidance to cover the new GM/Coach Ops advanced contract actions (extend, option, incentive, and option-decision workflows).
- Updated Owner Finance contract action state logic so `Exercise Option`/`Decline Option` only enable when the selected contract includes option terms.
- Expanded `tests/test_owner_finance_page.py` with option-term detection coverage for contract action enablement rules.
- Added GM Contracts level-gating in `ui/owner_finance_page.py` so advanced term actions (option/incentive add and option decision updates) are enabled only when GM Contracts is `advanced` or `mlb_like`; basic mode keeps only core extension actions.
- Updated Finance Hub tutorial copy and owner/admin guide finance docs to clarify that advanced contract actions require GM Contracts set to Advanced/MLB-Like.
- Expanded owner finance page helper coverage with advanced-contract-level detection assertions.
- Added shared finance ledger service `services/finance_ledger.py` with canonical append/list/existence-check helpers for `financial_transactions.csv`.
- Refactored owner monthly finance cycles, contract buyout posting, and offseason arbitration award posting to use the shared ledger service instead of module-local CSV writers.
- Added `tests/test_finance_ledger.py` and retained passing finance workflow coverage to validate canonical ledger write/read behavior.
- Expanded `services/finance_ledger.py` with typed ledger event APIs and shared constants: `post_finance_cycle_marker`, `post_contract_buyout`, and `post_arb_award`.
- Refactored owner monthly cycle markers, contract buyout postings, and offseason arbitration postings to call typed ledger event helpers instead of ad-hoc category/memo row construction.
- Expanded `tests/test_finance_ledger.py` with typed-event assertions for system cycle markers, contract-buyout rows, and arbitration-award rows.
- Added finance-ledger usage guard tests in `tests/test_finance_ledger_usage.py` to prevent raw `finance_cycle`, `contract_buyout`, and `arb_award` category literals from reappearing in core finance writer services.
- Updated finance workflow regression tests to consume shared finance-ledger constants instead of hard-coded category/team tokens (`tests/test_owner_finance_engine.py`, `tests/test_contracts_service.py`, `tests/test_offseason_finance_flow.py`).
- Expanded `services/finance_ledger.py` with typed team revenue/expense helpers (`build_team_revenue_row`, `build_team_expense_row`, `post_team_revenue`, `post_team_expense`) and canonical category-key normalization.
- Refactored owner monthly finance cycle ledger writes to use typed team revenue/expense row builders and a typed cycle-marker row builder, removing ad-hoc `revenue_*`/`expense_*` category string construction from `services/owner_finance_engine.py`.
- Expanded finance-ledger tests (`tests/test_finance_ledger.py`) for typed revenue/expense row generation and posting behavior, and tightened usage guards (`tests/test_finance_ledger_usage.py`) to prevent raw `revenue_` / `expense_` category literals in owner finance writer logic.
- Expanded the finance release validation gate test set in `scripts/validate_finance_release.py` to include ledger/usage coverage (`tests/test_finance_ledger.py`, `tests/test_finance_ledger_usage.py`) plus core contract and owner-finance suites (`tests/test_contracts_service.py`, `tests/test_owner_finance_engine.py`).
- Added validation regression coverage in `tests/test_validate_finance_release.py` to assert that ledger/contracts/owner-finance suites remain part of the default release gate.
- Updated release documentation (`README.md`, `RELEASE.md`) to clarify the broader finance test coverage now enforced before release builds.
- Extended GM/Coach Ops advanced contract management with new inline actions in `ui/owner_finance_page.py`: **Edit Guarantees**, **Edit/Remove Option**, and **Edit/Remove Incentive**, alongside existing extend/add/exercise/decline actions.
- Added support in `services/contracts_service.py::extend_contract(...)` for updating `guaranteed` and `buyout_guarantee` terms without forcing contract-length changes.
- Updated contract list rows in Owner Finance to surface guarantee status and guaranteed buyout amounts for quicker contract-risk review.
- Updated Finance Hub tutorial and owner/admin guide finance documentation to include the expanded advanced contract action set.
- Expanded regression coverage in `tests/test_contracts_service.py` and `tests/test_owner_finance_page.py` for guarantee-term updates and incentive-term detection.
- Added payroll-policy audit ledger event support in `services/finance_ledger.py` via `CATEGORY_PAYROLL_POLICY` and `post_payroll_policy_event(...)`.
- Added `record_payroll_policy_result(...)` in `services/payroll_policy.py` and wired owner/admin trade and owner free-agent execution flows to persist payroll-policy warning/block audit entries to `financial_transactions.csv`.
- Expanded payroll and ledger regression coverage (`tests/test_payroll_policy.py`, `tests/test_finance_ledger.py`) for policy-audit row writing and memo payload validation.
- Expanded finance release validation defaults to include `tests/test_payroll_policy.py` and updated `tests/test_validate_finance_release.py` accordingly.
- Added new budget-to-gameplay bridge service `services/finance_budget_effects.py` to derive per-team multipliers from owner budgets (training/scouting/development/facilities) and expose player-level training-camp intensity mappings.
- Integrated owner budget effects into preseason development flow: `ui/season_progress_window.py` now resolves per-player training intensity from finance budget effects and passes it into `playbalance/training_camp.py`.
- Extended training development pipeline to accept intensity scaling (`playbalance/player_development.py` and `playbalance/training_camp.py`) so training-camp gains are budget-sensitive while preserving neutral defaults when finance/budgets are off.
- Updated Owner Finance Hub projections to show the effective training-camp development multiplier and updated owner tutorial/docs messaging to explain budget impact on camp gains.
- Added regression coverage for budget-effect multipliers and intensity scaling (`tests/test_finance_budget_effects.py`, `tests/test_training_camp.py`, `tests/test_player_development.py`) and expanded release validation defaults to include the new budget-effects suite.
- Expanded budget-effects integration with development progression: added `development_multiplier_by_player(...)` in `services/finance_budget_effects.py` and wired offseason aging to consume team development-budget multipliers via `ui/season_progress_window.py`.
- Updated aging pipeline (`playbalance/aging.py`, `playbalance/aging_model.py`) to support development-aware scaling: stronger development budgets amplify positive growth and soften decline, while weaker budgets reduce growth and increase decline pressure.
- Extended finance release validation defaults with development-related regression suites (`tests/test_aging_model.py`, `tests/test_training_camp.py`, `tests/test_player_development.py`) and updated `tests/test_validate_finance_release.py` expectations.
- Added new regression coverage for development-budget behavior (`tests/test_aging.py`, `tests/test_aging_model.py`, and expanded `tests/test_finance_budget_effects.py`).
- Updated Owner Finance tutorial/docs wording to clarify that development budgets now influence both preseason camp gains and offseason aging/development outcomes.
- Added scouting-confidence budget effects in `services/finance_budget_effects.py` with deterministic display uncertainty helpers (`scouting_display_profile_for_team(...)` and `scouting_display_value(...)`), including a finance-off exact-mode fallback.
- Integrated scouting-confidence output into player profiles (`ui/player_profile_dialog.py`): ratings now use scouting-adjusted display values and the scouting summary panel shows confidence tier plus estimated uncertainty range.
- Expanded regression coverage (`tests/test_finance_budget_effects.py`, `tests/test_player_profile_dialog.py`) and re-ran finance release validation (`scripts/validate_finance_release.py --skip-stability --seasons 2`) with passing smoke + test gates.
- Added a detailed financial-system closeout checklist to `docs/financial_system_plan.md`, including phase-by-phase completion items, acceptance criteria, and final go/no-go release gates.
- Started checklist execution for Owner Finance realism by making advanced owner ticket/concessions projections schedule-driven: `services/owner_finance_engine.py` now reads home-game cadence from `schedule.csv` and applies attendance demand multipliers using home-game volume + home-record form.
- Added owner-finance regression coverage (`tests/test_owner_finance_engine.py`) for schedule-volume impact, home-record attendance impact, and confirmation that simple/basic revenue mode remains fixed-income style.
- Re-ran finance release validation (`scripts/validate_finance_release.py --skip-stability --seasons 2`) with passing tests and multi-league smoke checks.
- Added owner-editable budget workflow for checklist item A3: Owner Ops now includes budget input fields and a `Save Budget Targets` action (`ui/owner_finance_page.py`) for training/scouting/development/facilities when Owner Budgets is enabled.
- Added `update_team_budget_targets(...)` in `services/owner_finance_engine.py` to persist league-scoped team budget targets with module-enabled guardrails and safe normalization.
- Expanded regression coverage in `tests/test_owner_finance_engine.py` and `tests/test_owner_finance_page.py` for budget target persistence, disabled-module guard behavior, and currency input parsing.
- Updated owner finance tutorial/docs to reflect editable budget controls (`ui/owner_dashboard.py`, `docs/owner_admin_guide.md`).
- Continued checklist item A1 realism work in `services/owner_finance_engine.py`: advanced owner revenue now applies fan-interest multipliers to media/sponsorship based on standings performance (win rate, run differential, home form), and advanced expenses now scale operations/facilities from schedule-derived away/home game cadence.
- Expanded owner-finance tests (`tests/test_owner_finance_engine.py`) to cover fan-interest revenue deltas and travel/facility expense scaling while preserving basic-mode stability.
- Re-ran finance release validation (`scripts/validate_finance_release.py --skip-stability --seasons 2`) with passing tests and multi-league smoke checks.
- Implemented checklist item A2 finance cadence orchestration in `services/owner_finance_engine.py` via `apply_owner_finance_cadence_for_dates(...)`, adding idempotent daily (tickets/concessions) and weekly (training/scouting/facilities) postings alongside monthly settlement.
- Updated monthly settlement logic to avoid double-counting advanced categories when daily/weekly cadence markers exist for the period.
- Wired Season Progress simulation to run the full cadence on both single-day and multi-day simulations (`ui/season_progress_window.py`) and surface daily/weekly/monthly finance update messaging.
- Expanded owner-finance tests for cadence behavior and marker-based monthly skip handling (`tests/test_owner_finance_engine.py`).
- Added a dedicated finance backlog notes file at `docs/financial_backlog.md` to capture nice-to-haves/suggested upgrades while keeping implementation checklist-driven.
- Completed checklist item A4 by expanding owner-finance module-level behavior tests (`tests/test_owner_finance_engine.py`) for `off/basic/advanced` enforcement across revenue, expenses, budgets, and cadence gating.
- Re-ran finance release validation (`scripts/validate_finance_release.py --skip-stability --seasons 2`) with passing tests and multi-league smoke checks.
- Completed checklist item A5 by expanding owner-finance realism/cadence tests in `tests/test_owner_finance_engine.py`, including cadence idempotency, invalid-date handling, and finance-cycle marker assertions for daily/weekly/monthly application.
- Updated checklist status in `docs/financial_system_plan.md` to mark owner-finance test coverage and release-validation pass criteria as complete.
- Extended finance backlog tracking in `docs/financial_backlog.md` with a QA integration-test follow-up item for Season Progress cadence execution paths.
- Completed remaining Owner Finance checklist acceptance items in `docs/financial_system_plan.md` section A: verified visible projection movement from outcomes/attendance and league-scoped budget-edit downstream effects.
- Expanded `tests/test_owner_finance_engine.py` with two new regressions: (1) advanced owner revenue shifts after standings/schedule changes for the same team, and (2) budget target edits remain league-scoped while changing downstream training-camp multipliers.
- Re-ran targeted owner-finance tests and full finance release validation gate (`scripts/validate_finance_release.py --skip-stability --seasons 2`) with passing results.
- Completed Section B (GM/Coach Economics Completion) checklist items in `docs/financial_system_plan.md`, including acceptance criteria for offseason consistency, auditable payroll accounting, and single-player/multi-owner test coverage.
- Expanded arbitration depth for advanced mode: super-two eligibility support (service-time aware) in both offseason arbitration processing and GM queue arbitration candidate selection.
- Added payroll-rule accounting effects service (`apply_payroll_rule_accounting_effects`) in `services/payroll_policy.py` with deterministic, idempotent ledger + financial-state updates: basic overage fee, MLB-like CBT tax, and MLB-like floor shortfall fee.
- Wired offseason rollover to execute payroll accounting effects and persist payroll-accounting summary/details in offseason state/summary payloads.
- Updated CPU free-agency execution to honor payroll-policy checks during bid resolution (blocked signings are skipped; warnings are audited), improving standard vs MLB-like behavior.
- Updated GM free-agency queue candidate evaluation to include payroll-policy affordability gating and policy metadata for recommendation quality.
- Expanded tests:
- `tests/test_gm_finance_queue.py`: advanced super-two arbitration eligibility coverage.
- `tests/test_free_agency.py`: standard warn-mode signing vs MLB-like block-mode signing behavior.
- `tests/test_payroll_policy.py`: payroll accounting penalties (tax/floor) and idempotency coverage.
- `tests/test_offseason_finance_flow.py`: advanced super-two arbitration and full offseason sequence integration tests for both single-player and multi-owner queue-approval flows.
- `tests/test_contracts_service.py`: retained-contract incentive reset lifecycle coverage.
- Re-ran targeted suites and full finance validation gate (`scripts/validate_finance_release.py --skip-stability --seasons 2`) with passing results.
- Added backlog item `FIN-BL-006` to `docs/financial_backlog.md` for future MLB-like repeat-offender CBT and compensation-pick enhancements.
- Completed Section C (Enforcement and Policy Hardening) checklist items and acceptance criteria in `docs/financial_system_plan.md`.
- Hardened policy enforcement across additional write paths:
- GM queue arbitration apply now enforces payroll policy on raises and non-tenders.
- GM queue free-agency target signing now enforces payroll policy before signing.
- Offseason arbitration processing now enforces payroll policy with block/warn handling and audit logging.
- Added direct payroll-delta policy evaluator in `services/payroll_policy.py` (`evaluate_payroll_delta(...)`) to support consistent checks outside of trade/FA entry points.
- Finalized debt guardrail model in policy service:
- Added debt-cap checks for discretionary payroll actions (`kind=debt` violations).
- Added preset-based debt cap defaults and documented them in the financial plan.
- Updated payroll accounting cashflow handling so penalties floor cash at zero and carry deficit into debt.
- Expanded policy edge-case coverage:
- Mixed max/floor violation trade scenarios.
- Debt-cap block scenarios.
- Queue-apply blocked arbitration/FA actions.
- Offseason arbitration block-policy hold behavior.
- Added `tests/test_gm_finance_queue.py` to release validation defaults in `scripts/validate_finance_release.py` and updated `tests/test_validate_finance_release.py` expectations.
- Re-ran targeted policy/queue/offseason tests plus full finance release validation gate (`scripts/validate_finance_release.py --skip-stability --seasons 2`) with passing results.
- Added backlog item `FIN-BL-007` to `docs/financial_backlog.md` for editable debt-cap controls in finance settings UI.
- Completed Section D (CPU Finance AI and Balance) checklist items and acceptance criteria in `docs/financial_system_plan.md`.
- Extended CPU finance strategy modeling with multi-year contract commitments (`next_year_commitment`, `two_year_commitment`) and integrated commitment-aware cap targeting and bid gating in `services/finance_ai.py`.
- Added/expanded deterministic CPU finance AI coverage in `tests/test_finance_ai.py` for strategy profile differences, multi-year commitment loading, and commitment-tuning bid boundaries.
- Extended finance AI tuning defaults/range normalization for commitment controls in `services/finance_settings.py` and `tests/test_finance_settings.py`.
- Fixed finance settings league-id fallback behavior so single-league settings files preserve the existing league key (prevents unintended `league` alias entries during defaults/projection reads).
- Re-ran targeted CPU/policy suites, full finance validation tests + smoke (`scripts/validate_finance_release.py --skip-stability --seasons 2`), and strict stability sim (`scripts/validate_finance_release.py --skip-tests --skip-smoke --seasons 8`) with passing guardrails.
- Completed Section E (UX, Alerts, and Tutorials) checklist items and acceptance criteria in `docs/financial_system_plan.md`.
- Added commissioner-facing finance reporting service `services/finance_reporting.py` with saved-config projection snapshots and prioritized actionable finance alerts (cash risk, payroll threshold/floor pressure, offseason checklist/deadline signals, GM queue pressure).
- Added payroll limit context API `build_payroll_limit_context(...)` in `services/payroll_policy.py` for reusable threshold/floor reporting.
- Enhanced `ui/financial_settings_dialog.py` with:
- Commissioner Workflow Guidance panel,
- Commissioner Projection Preview panel,
- Finance Alerts panel,
- refresh-preview action and expanded AI tuning controls (including commitment settings).
- Enhanced `ui/offseason_finance_dialog.py` with an in-dialog Finance Alerts surface tied to current league workflow state.
- Enhanced `ui/owner_finance_page.py` with a `Next Finance Actions` panel to keep owner GM/Coach workflows phase-aware and linear.
- Updated finance tutorial content in `ui/owner_dashboard.py` and admin/owner guide documentation in `docs/owner_admin_guide.md` to reflect projection preview, alerts, and updated workflow sequencing.
- Added/expanded tests:
- `tests/test_finance_reporting.py`
- `tests/test_financial_settings_dialog.py`
- `tests/test_offseason_finance_dialog.py`
- `tests/test_owner_finance_page.py`
- `tests/test_payroll_policy.py`
- Expanded release validation defaults in `scripts/validate_finance_release.py` to include new UX/reporting suites (`tests/test_finance_reporting.py`, `tests/test_offseason_finance_dialog.py`, `tests/test_owner_finance_page.py`) and updated `tests/test_validate_finance_release.py` expectations.
- Re-ran full finance release validation gate (`scripts/validate_finance_release.py --skip-stability --seasons 2`) with passing tests and multi-league smoke checks.
- Completed Section F QA/release-gate automation items in `docs/financial_system_plan.md` except the final manual installer smoke execution step.
- Expanded finance release validation matrix in `scripts/validate_finance_release.py` to include cross-league lifecycle/isolation suites: `tests/test_smoke_multi_league.py`, `tests/test_phase5_path_isolation.py`, `tests/test_league_registry.py`, `tests/test_season_context_paths.py`, plus release-gate coverage tests (`tests/test_build_release.py`, `tests/test_archive_ui_checklist.py`).
- Added release build regression tests in `tests/test_build_release.py` to lock pre-build validation behavior and optional manual-checklist gating.
- Added manual checklist archival utility `scripts/archive_ui_checklist.py` (version-tagged PASS/FAIL/PENDING artifacts in `reports/release_validation/checklists/`).
- Added optional build gate flags in `scripts/build_release.py`: `--require-ui-checklist` and `--ui-checklist-artifact` to enforce manual checklist PASS before building.
- Updated release workflow docs (`RELEASE.md`, `docs/post_installer_ui_checklist.md`) to include checklist archival and optional enforcement flow.
- Re-ran full release validation command without skips (`scripts/validate_finance_release.py --seasons 8`) with passing finance tests, multi-league smoke checks, and strict stability guardrails.
- Archived a placeholder checklist artifact for v5.0.75 at `reports/release_validation/checklists/ui_installer_checklist_v5.0.75_20260219_232006.md` with `Checklist Result: PENDING` (manual installer/UI smoke execution still required before release sign-off).

# 5.0.76 Release Notes (Since last build 46612d2)
Date: 2026-02-20

- Fixed a league-creation hang caused by unique-name exhaustion/duplicates in playbalance/player_generator.py::generate_name(...); generation now builds a deduplicated available-name set each call and falls back safely when exhausted instead of looping indefinitely.
- Added regression tests in 	ests/test_player_generator.py for duplicate-name exhaustion and remaining-unique-name selection behavior.

# 5.0.77 Release Notes (Since last build 46612d2)
Date: 2026-02-20

- Fixed a league-creation hang caused by unique-name exhaustion/duplicates in `playbalance/player_generator.py::generate_name(...)`; generation now builds a deduplicated available-name set each call and falls back safely when exhausted instead of looping indefinitely.
- Added regression tests in `tests/test_player_generator.py` for duplicate-name exhaustion and remaining-unique-name selection behavior.
- Installer clean-reinstall flow now handles missing uninstall registry entries by deleting the detected existing install folder directly (after explicit clean-reinstall selection) instead of silently skipping uninstall.
- Installer clean-reinstall now parses and reuses uninstall-command parameters, enforces `/NORESTART`, and uses visible uninstall execution (`SW_SHOW`) so cleanup is observable while setup waits for completion.

# 5.0.78 Release Notes (Since last build 46612d2)
Date: 2026-02-20

- Fixed a perceived new-league creation hang by running league generation in a background worker with a visible progress dialog.
- Updated the splash-screen Start Game "Create New League" flow to use threaded background work instead of synchronous execution.

# 5.0.79 Release Notes (Since last build 46612d2)
Date: 2026-02-21

- Fixed a perceived new-league creation hang by running league generation in a background worker with a visible progress dialog.
- Updated the splash-screen Start Game "Create New League" flow to use threaded background work instead of synchronous execution.
- Updated Start Game league creation flow to skip the draft settings reminder before login.
- Draft settings reminder still appears when league creation is launched from admin flows.

# 5.0.81 Release Notes (Since last build 46612d2)
Date: 2026-02-21

- Docs: added a future-work backlog entry for reorganizing the Admin League Settings/League Manager experience to streamline create/clone/switch/archive/delete workflows and improve guardrails.
- Build: added `ui.owner_finance_page` as an explicit PyInstaller hidden import so owner login in multi-league installs no longer fails with `ModuleNotFoundError` after packaging.

# 5.0.86 Release Notes (Since last build 46612d2)
Date: 2026-02-21

- Backlog: added a future-work item to package owner change requests into a single `.zip` export with clear naming that includes league, team, and timestamp.
- Backlog: added a future-work item to redesign and properly size the Trade window for cleaner layout and better usability.
- Backlog: added a future-work item to fix Owner Finance page sizing/scroll behavior so bottom sections are not cut off.
- Fixed Team Settings failure in packaged builds by removing `data.ballparks` imports and loading stadium names from `ParkConfig.csv` via `utils.park_utils`.
- Docs: added explicit SemVer version-bump policy to `AGENTS.md` (patch/minor/major rules and escalation guidance).

# 5.0.87 Release Notes (Since last build 46612d2)
Date: 2026-02-21

- Fixed empty stadium selector in Team Settings by adding bundled park reference data (`data/parks/ParkConfig.csv`, `ParkFactors.csv`, `Parks.csv`) and robust park-data fallback loading.
- Added legacy `ballparks.py` fallback parsing for stadium name lists when ParkConfig data is unavailable.

# 5.0.89 Release Notes (Since last build 46612d2)
Date: 2026-02-21

- Backlog: added a Team Settings visual upgrade item to show current park graphic and a uniform preview that reflects selected team colors.
- Docs: updated `AGENTS.md` to require adding backlog requests/items to `docs/future_work.md`.
- Fixed dashboard lifecycle handling so dashboard close cleanup still runs and splash is restored correctly (including Start Game button state).
- Improved Owner Finance page layout robustness by adding scrollable tab content and reducing oversized button-row width pressure that could trigger window geometry failures.

# 5.0.91 Release Notes (Since last build 46612d2)
Date: 2026-02-21

- Backlog: added a future-work item to resize and redesign the League Finance Settings window for clearer layout and visibility.
- Fixed admin login/splash lifecycle regression by restoring splash visibility behavior while preserving dashboard close cleanup.
- Moved "Auto Reassign All Rosters" to background execution with progress feedback to prevent UI hangs during full-league reassignment.

# 5.0.92 Release Notes (Since last build 46612d2)
Date: 2026-02-21

- Fixed simulation `Permission denied: 'data/players.csv'` by resolving game simulation file paths against the active league data directory instead of relative working-directory paths.
- Updated season simulation entry points to pass explicit active-league `players/rosters/lineups` paths into game simulation.
- Added regression tests for runtime path resolution in `simulate_game_scores` and default `SeasonSimulator` behavior.

# 5.0.94 Release Notes (Since last build 46612d2)
Date: 2026-02-21

- Added `scripts/benchmark_workflows.py` to benchmark `create_league` and `auto_assign_all_teams` runtimes across typical and max-size scenarios, with CSV/JSON reports and optional cProfile output.
- Optimized path resolution caching in `utils/path_utils.py` to avoid repeated writable-root probing during long-running generation/assignment loops.
- Optimized roster auto-assign performance by reusing loaded players, caching age lookups, and resolving sim date once per run in `services/roster_auto_assign.py`.
- Added phased progress callbacks to league creation (`Loading`, `Processing`, `Saving`, `Validating`) in `playbalance/league_creator.py`.
- Updated Admin league creation progress dialog to show live phase updates plus elapsed time while long operations run.
- Updated Admin auto-reassign rosters progress dialog to show phase/teams-completed status and elapsed time.
- Added regression coverage for workflow progress callbacks in `tests/test_league_creator.py` and `tests/test_roster_auto_assign.py`.

# 5.0.95 Release Notes (Since last build 46612d2)
Date: 2026-02-22

- Fixed Admin auto-reassign progress dialog so the progress bar becomes determinate during team processing and no longer keeps animating at `Complete (N/N)`.
- Fixed auto-reassign completion handling to marshal worker completion callbacks back onto the UI thread reliably before closing the dialog.

# 5.0.96 Release Notes (Since last build 46612d2)
Date: 2026-02-22

- Fixed league snapshot export completion handling in `ui/admin_dashboard/actions/league_snapshot.py` so the progress dialog closes reliably after the background export finishes.
- Added a GUI-thread dispatcher for snapshot export completion callbacks to avoid stalls when worker callbacks fire off the UI thread.
- Added regression tests in `tests/test_admin_league_snapshot_actions.py` covering both async-future and synchronous worker execution paths.

# 5.0.96 Release Notes (Since last build 46612d2)
Date: 2026-02-22

- No changes since last build and no draft notes were found.

# 5.0.97 Release Notes (Since last build 46612d2)
Date: 2026-02-22

- 5.0.97
- 5.0.96
- Added a reusable in-app searchable HTML manual viewer (`ui/manual_viewer_dialog.py`) with find-next/find-previous and per-manual selection.
- Added two detailed in-app manuals under `docs/manuals/`:
- `game_manual.html` (complete game operations guide)
- `finance_system_manual.html` (full finance system explanation with flow/timing/modules)
- Wired manuals into the Owner dashboard via `Tutorials -> Reference Manuals` with direct actions for both manuals.
- Wired manuals into the Admin dashboard via a new `Tutorials` menu that includes logo/avatar tutorials plus both manuals.
- Added a direct `Finance Manual` button on the Owner Finance page header for one-click access while managing finance workflows.
- Updated owner tutorial copy to match current menu labels/paths (Open Finance Hub, Admin Dashboard season path, Free Agency Hub wording, and schedule regeneration path).
- Fixed tutorial step heading punctuation rendering in `ui/tutorial_dialog.py` for clean ASCII output.
- Updated owner/admin guide documentation to include manual access paths and corrected free-agency guidance.
- Updated PyInstaller build inputs to bundle `docs/manuals` in release builds (`build_exe.py` and `NexGen-BBPro.spec`).
- Added targeted tests for manual viewer loading/fallback behavior (`tests/test_manual_viewer_dialog.py`).

# 5.0.109 Release Notes (Since last build 1c467bd)
Date: 2026-02-23

- 5.0.109
- Completed backlog item 17 by adding in-app commissioner workflow tutorials in the Admin dashboard.
- Expanded Admin `Tutorials` menu into categorized entries with guided walkthroughs for league setup/manager, user management, season progression, trade/review queues, and exports/utilities.
- Added one-time onboarding behavior for new commissioners by auto-launching the Admin Dashboard Overview tutorial on first launch, with persisted flags in `config/admin_tutorial_flags.json`.
- Updated `docs/owner_admin_guide.md` with the new Admin tutorial map and onboarding behavior.
- Added focused test coverage in `tests/test_admin_tutorials.py`.
- Completed backlog item 16 by adding an `Open Folder` shortcut to export completion dialogs.
- Added shared export dialog helper in `ui/export_dialogs.py` plus desktop folder-open utility in `utils/desktop_utils.py`.
- Wired `Open Folder` success actions into owner/admin export flows: change request exports, league snapshot export, report export, playoff summary export, and finance stability JSON/CSV exports.
- Added regression coverage in `tests/test_desktop_utils.py` and `tests/test_export_dialogs.py`.
- Fixed `tests/test_season_progress_window.py` collection/runtime failures in headless environments.
- Updated `ui/season_progress_window.py` to lazy-load schedule-template dialog selection with a safe fallback to the default template when UI dialog imports are unavailable.
- Added missing `QProgressBar` stub wiring in `tests/test_season_progress_window.py` so the test harness uses intended widget doubles.
- Fixed end-of-regular-season button-state behavior in single-day simulation flow so controls and Next Phase state align with expected season-complete UI state.
- Completed backlog item 14 by enforcing commissioner-only season progression in multi-owner leagues.
- Added shared access policy helper `can_run_season_progression(...)` in `utils/league_settings.py` and wired owner/commissioner role checks through the owner dashboard flow.
- Updated `ui/owner_dashboard.py` so owner accounts in multi-owner leagues no longer get season progression controls from the Owner dashboard menu.
- Added action-level guardrails in `ui/season_progress_window.py` so progression actions (phase advance, free-agency progression, training camp, schedule generation, and simulation) are blocked when progression is not permitted.
- Updated admin team-dashboard handoff to preserve commissioner progression access when opening a team dashboard from Admin (`ui/_admin_dashboard_legacy.py`).
- Added coverage for progression-access policy decisions in `tests/test_league_settings.py`.
- Completed backlog item 13 by redesigning the League Finance Settings window for clearer configuration across simple and advanced modes.
- Reworked `ui/financial_settings_dialog.py` into a scroll-safe full-height layout so all controls remain accessible on common screen sizes without clipping.
- Grouped module controls into Owner, GM, and Governance/AI sections with inline descriptions and added live preset/module coverage guidance.
- Reorganized CPU Finance AI tuning fields into a denser two-column layout and updated section labeling for faster scanning.
- Added regression coverage in `tests/test_financial_settings_dialog.py` for module-level summary formatting.
- Completed backlog item 12 by adding live visual previews to Team Settings for both stadium selection and team uniform colors.
- Added a stadium preview panel in `ui/team_settings_dialog.py` that updates as the selected park changes and loads/generated park diagrams when available.
- Added a uniform mockup preview in `ui/team_settings_dialog.py` that updates in real time from primary/secondary color inputs.
- Added focused regression coverage in `tests/test_team_settings_dialog.py` for color normalization and park-name matching behavior.
- Completed backlog item 10 by redesigning the Trade Center layout for better readability and decision flow.
- Reorganized New Trade assets into side-by-side "You Send" / "You Receive" panels, added a concise offer summary row, and improved incoming-trade detail presentation.
- Added scrollable tab containers in `ui/trade_dialog.py` so controls remain accessible on smaller displays.
- Updated Trade Center sizing to a moderate, screen-aware default with a sensible minimum size to avoid oversized windows on larger screens and cramped layouts on smaller ones.
- Completed backlog item 9 by switching owner change request exports from loose JSON files to single ZIP bundles.
- Added bundle payload artifacts in `services/change_requests.py` (`manifest.json`, `request.json`, and per-file content under `files/...`) with filename format `change_request_<league_slug>_<team_slug>_<YYYYMMDD-HHMM>.zip`.
- Updated change-request inbox import to accept both `.zip` bundles and legacy `.json` payloads for backward compatibility.
- Updated owner/admin change-request UI copy to reference ZIP bundle flow (`ui/change_request_export_dialog.py`, `ui/change_requests_window.py`).
- Extended `tests/test_change_requests.py` to cover ZIP naming/contents plus cancel-request ZIP import.
- Closed backlog item 6 (Outstanding Test Failures) by validating and clearing the remaining unchecked targets in `docs/failing_tests.md`.
- Fixed legacy test import behavior by deferring `require_legacy_enabled(...)` in `scripts/simulate_season_avg.py` until simulation execution, while keeping helper imports usable in tests.
- Added PyQt test-stub compatibility fallbacks for missing core symbols in `ui/lineup_editor.py`, `ui/pitching_editor.py`, `ui/player_browser_dialog.py`, and `ui/components.py`.
- Marked item 6 complete in `docs/future_work.md`.
- Exposed reliever pitch-budget telemetry in owner quick metrics, including per-pitcher `available_pct` and bullpen average budget percentage.
- Updated owner dashboard/readiness UI to surface bullpen budget percentages in header and tooltip detail, plus usage-calibration status context.
- Extended `scripts/usage_calibration.py` to evaluate MLB target bands (CL/SU 60-70 G + 60-70 IP, MR 50-65 G, LR 35-50 G) and emit `data/reports/usage_calibration_summary.json` for dashboard integration.
- Added regression coverage in `tests/test_owner_quick_metrics.py` and `tests/test_usage_calibration_targets.py` for telemetry exposure, summary loading, and role target-band evaluation.
- Marked backlog item 5 (Pitch Budget Telemetry & Tuning) complete in `docs/future_work.md`.
- Completed the Unified Data Service Layer migration for standings/transactions by routing finance strategy and owner finance standings reads through `services/standings_repository.py`.
- Added `clear_transactions()` in `services/transaction_log.py` and migrated rollover/admin reset flows to clear logs through the transaction service so cache/events stay in sync.
- Replaced remaining direct roster CSV writes in contract expiry, free agency signing, and admin trade approval paths with shared roster APIs (`utils/roster_loader.save_roster` and `utils.roster_io.read_roster_csv`).
- Updated roster persistence API to accept explicit roster directories (`save_roster(..., roster_dir=...)`) for path-safe service workflows.
- Migrated additional roster consumer paths (`services/report_exporter.py`, `ui/lineup_editor.py`) away from ad-hoc roster file parsing.
- Added regression coverage in `tests/test_transaction_log_service.py` and `tests/test_free_agency.py` for transaction clearing and roster creation flows.
- Added `services/players_repository.py` to centralize player load/save operations behind the unified data service.
- Migrated core player-write call sites to use the repository layer (`playbalance/game_runner.py`, `playbalance/league_creator.py`, `services/dl_automation.py`, `ui/season_progress_window.py`, `ui/injury_center_window.py`, `ui/admin_dashboard/actions/league.py`).
- Removed manual `load_players_from_csv.cache_clear()` calls from migrated flows; player cache and `players.updated` events now refresh through repository updates.
- Added coverage in `tests/test_players_repository.py` for cache refresh and event emission on player saves.
