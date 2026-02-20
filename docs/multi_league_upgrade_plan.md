# Multi-League Upgrade Plan (Target: 5.0.0)

## Purpose
Define a complete, resumable implementation plan for moving NexGen-BBPro from a single-league data model to a multi-league architecture with isolated saves, league switching, and future online/shared workflows.

## Why This Is a Major Version
This change alters core assumptions across storage, path resolution, settings scope, and UI flow. Existing single-league installs must be migrated safely. That is a major-version boundary.

## Scope
- Multiple leagues on one install.
- Per-league data isolation.
- Active league context + league switcher.
- Per-league settings isolation (trade, injury, draft, users, schedule, etc.).
- Backward-compatible migration from existing single-league saves.
- Foundation hooks for future shared-player-pool and online sync work.

## Explicit Non-Goals (5.0.0)
- Real-time multi-user server mode.
- Shared player pools between leagues (optional later milestone).
- Full identity federation across leagues.

## Current Constraints (As-Is)
- Most modules assume one global data root via `utils/path_utils.py:get_data_dir()`.
- Many services and UI flows read/write `data/*.csv|json` directly.
- League creation rewrites the current data folder.
- Export/import tools assume a single active league payload.

## Target Architecture

### 1. Directory Layout
Use a registry + per-league roots under the user data dir:

```text
<data_root>/
  league_registry.json
  active_league.txt
  system/
    app_state.json
    backups/
  leagues/
    <league_id>/
      metadata.json
      data/
        teams.csv
        players.csv
        users.txt
        schedule.csv
        rosters/
        lineups/
        ... (all existing league files)
```

### 2. IDs and Metadata
- `league_id`: stable slug/uuid-like ID (never rename).
- `display_name`: mutable.
- `created_at`, `last_opened_at`, `version_created`, `version_last_opened`.
- `mode`: `single_player` or `owner_league`.
- `status`: `active|archived`.

### 3. Runtime Context
Introduce a league context service:
- Resolve active league root.
- Provide helper paths (`data_path("players.csv")`, etc.).
- Switch active league safely (close/open windows as needed).
- Publish context-change signal/event for UI refresh.

### 4. Path Resolution Strategy
Retain `get_data_dir()` behavior for compatibility, but evolve internals:
- `get_data_root()` returns writable application root.
- `get_active_league_data_dir()` returns `<root>/leagues/<id>/data`.
- `resolve_app_path("data/... ")` maps to active league data dir.

This minimizes churn while allowing phased refactors.

## Migration Strategy

### Migration Trigger
On first launch with 5.0 build:
1. Detect legacy single-league layout (`data/teams.csv`, etc.) and no registry.
2. Create registry.
3. Create default league entry (for existing save).
4. Move/copy legacy league data into `leagues/<generated_id>/data`.
5. Set active league to migrated league.
6. Write migration marker.

### Safety Requirements
- Pre-migration backup zip in `system/backups/`.
- Idempotent migration (safe on restart/crash).
- Validation checks before destructive operations.
- User-facing error + restore path if migration fails.

### Rollback
- Keep migration backup.
- Provide support utility script to restore pre-5.0 layout from migration backup (`scripts/check_league_layout.py --restore --force`).

## Implementation Phases

## Phase 0 - Discovery and Baseline (1 sprint)
### Deliverables
- Dependency inventory of direct `data/...` reads/writes.
- Multi-league technical design finalized.
- Migration test fixtures prepared.

### Tasks
- Generate path-usage report with `rg` for `get_data_dir`, `resolve_app_path`, and hard-coded `"data/`.
- Categorize modules into:
  - Core path providers
  - Services
  - UI pages/dialogs
  - Utilities/scripts
- Define critical-path modules for early conversion.

### Exit Criteria
- Signed-off architecture doc (this file).
- Ordered refactor backlog with owners.

## Phase 1 - Storage Foundation (1-2 sprints)
### Deliverables
- Registry service + active league pointer.
- Path utils extended for active league data dir.
- Backward-compatible compatibility layer.

### Tasks
- Add `services/league_registry.py` with CRUD:
  - list/create/update/archive/delete/select-active
- Extend `utils/path_utils.py`:
  - `get_data_root()`
  - `get_active_league_id()`
  - `get_active_league_dir()`
  - `get_active_league_data_dir()`
- Keep existing callers working by routing `get_data_dir()` to active league data dir.

### Exit Criteria
- App boots unchanged behavior with one migrated league.
- Existing workflows still read/write through active league scope.

## Phase 2 - Migration Engine (1 sprint)
### Deliverables
- One-time migration service + backup/restore support.

### Tasks
- Add `services/league_migration.py`:
  - detect legacy layout
  - create default league from legacy data
  - write migration markers and logs
- Add smoke validation after migration:
  - teams loaded
  - users loaded
  - schedule readable
- Add support script for diagnostics (`scripts/check_league_layout.py`).

### Exit Criteria
- Legacy save migrates with zero data loss on fixture set.
- Re-running migration is a no-op.

## Phase 3 - League Lifecycle Operations (1 sprint)
### Deliverables
- Create, clone, archive, delete league operations.
- Safe league switching API.

### Tasks
- Add `services/league_lifecycle.py`:
  - create from template/current defaults
  - clone existing league
  - archive/unarchive
  - delete with safeguards
- Update create-league flow to target selected/new league ID, not global overwrite.

### Exit Criteria
- Multiple leagues can coexist without file collisions.

## Phase 4 - UI/UX Integration (1-2 sprints)
### Deliverables
- League switcher in login/admin surfaces.
- League management UI in Admin Dashboard.

### Tasks
- Add league selector on startup/login.
- Add Admin "League Manager" page/dialog:
  - switch active league
  - create/clone/archive/delete
  - view metadata and last opened time
- Display active league badge in admin and owner dashboards.

### Exit Criteria
- User can switch leagues without app restart (preferred) or with guided restart fallback.

## Phase 5 - Settings and Service Isolation Audit (2+ sprints)
### Deliverables
- Confirm all stateful services are scoped to active league.

### High-Risk Areas (must verify)
- `users.txt` and auth flow.
- Trade settings and trade ledger files.
- Injury/training settings and reports.
- Draft state/pool/results files.
- Season context/career archives.
- Snapshot/export/import flows.

### Tasks
- Replace remaining hard-coded `data/...` references.
- Add regression checks for cross-league contamination.

### Phase 5 Checklist (Active Audit)
- [x] `users.txt` auth path resolved via active league at login.
- [x] Trade settings + draft-pick ledger persist under active league data path.
- [x] Injury/training settings and history reports resolve paths at call time.
- [x] Draft state/pool/results/assignment helpers resolve paths at call time.
- [x] News + special events writers resolve league-scoped files at call time.
- [x] Season context career/index paths resolve from active league dynamically.
- [x] Snapshot export/import paths resolve from active league at runtime.
- [x] Remove remaining module-level `get_data_dir()` constants from UI/service modules.
- [x] Add cross-league contamination regression tests for each high-risk file group.

### Exit Criteria
- No writes leak across league boundaries.

## Phase 6 - QA Hardening and Release Prep (1 sprint)
### Deliverables
- Full test matrix, migration docs, and operator runbook.

### Tasks
- Add tests:
  - migration unit + integration
  - registry lifecycle
  - path resolution with active league switching
  - smoke tests for admin/owner launch in non-default league
- Update tutorials/docs/release notes for 5.0.

### Exit Criteria
- 5.0.0 RC quality gate met.

## Testing Strategy

### Automated
- Unit tests for registry, migration, path utils.
- Integration tests for create/switch/delete workflows.
- Backward-compat tests loading old fixtures.

### Manual Smoke Checklist
- Create two leagues and switch between them.
- Verify different teams/players/users appear per league.
- Submit a trade/change request in league A; ensure absent in league B.
- Run draft/sim in league B; ensure league A schedule/progress unchanged.
- Export snapshot in each league and verify payload isolation.

## Data Contracts and Compatibility
- Keep legacy file formats inside each league `data/` for 5.0.
- Do not introduce schema breaks unless migration includes explicit converters.
- Include `version_last_opened` in league metadata for future migrations.

## Risks and Mitigations
- Risk: hidden direct file writes bypassing path utils.
  - Mitigation: aggressive grep audit + runtime guard assertions in debug mode.
- Risk: migration data loss.
  - Mitigation: mandatory backup, dry-run validation, idempotency checks.
- Risk: UI state stale after league switch.
  - Mitigation: centralized context-change event and controlled refresh points.

## Release Plan
- `5.0.0-alpha`: Foundation + migration behind guarded entry path.
- `5.0.0-beta`: UI league manager + broad service isolation complete.
- `5.0.0`: stabilization, docs, and support tooling.

## Work Breakdown (Initial Ticket Queue)
1. Add league registry service and tests.
2. Extend path utils with active-league helpers.
3. Implement migration service with backup.
4. Update create league action to create/select league ID.
5. Add admin league manager UI.
6. Add startup/login league selector.
7. Sweep remaining direct `data/` writes.
8. Add integration tests and migration fixtures.
9. Final docs/tutorial updates.

## Resume Checklist (Keep Updated)
- [x] Phase 0 complete
- [x] Phase 1 complete
- [x] Phase 2 complete
- [x] Phase 3 complete
- [x] Phase 4 complete
- [x] Phase 5 complete
- [x] Phase 6 complete

## Session Handoff Template
When pausing work, append:
- Current phase:
- Completed tickets:
- In-progress ticket:
- Blocking issues:
- Next concrete command/module to touch:
- Validation run status:

## Proposed First Execution Slice
Implement Phase 1 ticket #1 and #2 first:
- `services/league_registry.py`
- `utils/path_utils.py` active-league extensions
- Tests for registry/path resolution

That slice gives immediate infrastructure value while keeping behavior stable.

## Progress Notes
- 2026-02-14: Completed the first Phase 1 execution slice:
  - Added `services/league_registry.py` with registry CRUD, active league selection, and per-league data-dir helpers.
  - Extended `utils/path_utils.py` with data-root + active-league helpers while preserving legacy `get_data_dir()` fallback behavior.
  - Added `tests/test_league_registry.py` covering registry operations and active-league path routing behavior.
  - Validation run: `pytest` passed for registry/settings/snapshot/trade-settings/draft-ledger plus trade-utils/draft-console targeted suites.
- 2026-02-14: Continued multi-league wiring toward Phase 1 completion:
  - Updated admin create-league flow to target `leagues/<league_id>/data` instead of global overwrite, then register/select the league via `services/league_registry.py`.
  - Added admin `League Manager` dialog (`ui/league_manager_dialog.py`) and wired it into League Settings for active-league selection and archive/restore controls.
  - Refactored `services/trade_settings.py` to resolve settings paths at call-time with optional explicit `path`/`league_id` overrides for per-league writes.
  - Updated season-context persistence to write career artifacts relative to the selected league data directory and patched `playbalance/league_creator.py` to initialize context at the new league path.
  - Added tests for path-aware trade settings and season-context path scoping; validation run passed targeted multi-league/trade/rollover suites.
- 2026-02-14: Added startup/login active-league selection:
  - Login window now shows available non-archived leagues from the registry and switches the active league before authentication.
  - Login authentication now reads `users.txt` from the currently selected active league path instead of a module-level static path.
  - Added `.gitignore` entries for generated runtime artifacts (`data/record_book_snapshot.json`, `data/special_events.json`).
- 2026-02-14: Executed Phase 2 migration engine slice:
  - Added `services/league_migration.py` with one-time legacy detection, backup zip creation (`system/backups`), root-to-league data move, marker persistence (`system/migrations`), and validation checks for teams/users/schedule readability.
  - Added recovery path that repairs a missing registry from existing `leagues/<id>/data` folders.
  - Wired startup migration trigger in `main.py` and added migration notice dialogs for completed/failed migration outcomes.
  - Added diagnostic script `scripts/check_league_layout.py` for layout inspection and optional migration execution.
  - Added `tests/test_league_migration.py`; validated migration + registry + rollover + trade/user suites with targeted `pytest`.
- 2026-02-14: Executed Phase 3 lifecycle service slice:
  - Added `services/league_lifecycle.py` with guarded APIs for create entry, clone league data, archive/unarchive, delete with active/last-league safeguards, and safe active-league switching.
  - Updated `ui/league_manager_dialog.py` to use lifecycle APIs and added commissioner actions for clone and delete directly from League Manager.
  - Added `tests/test_league_lifecycle.py` covering clone data retagging, archive/switch protections, and delete safeguards.
  - Validation run: targeted lifecycle + migration + registry + trade + rollover + snapshot suites passed.
- 2026-02-14: Executed Phase 4 UI integration slice:
  - Added active-league header controls in Admin Dashboard (`ui/_admin_dashboard_legacy.py`) with quick switch selector, active league badge, and guided stale-window warning after switch.
  - Added active-league badge in Owner Dashboard header (`ui/owner_dashboard.py`) and window title suffix to keep league context visible.
  - Refreshed admin league header after create/manage actions so UI stays aligned with registry state.
  - Preserved login compatibility test override while keeping dynamic league-scoped `users.txt` resolution.
  - Extended `tests/test_login_window.py` stubs for broader headless compatibility and validated owner/login + multi-league suites.
- 2026-02-16: Started Phase 5 service/path isolation hardening:
  - Replaced module-level cached `get_data_dir()` paths with call-time active-league resolution in draft state/pool/assignment, transaction logging, injury/training settings/history, and news/special-events services.
  - Updated season context exports to include dynamic path helpers and a path-like compatibility proxy so legacy imports of `CAREER_DATA_DIR` continue to follow active league context.
  - Added `tests/test_phase5_path_isolation.py` to verify in-process active-league switches do not leak writes across league folders.
  - Validation run: targeted Phase 5/registry/trade/season-context suites passed in `.venv2`.
- 2026-02-16: Continued Phase 5 UI/service path sweep:
  - Added reusable `ActivePath` proxy in `utils/path_utils.py` and replaced remaining module-level path constants in high-traffic UI/service modules (season progress, schedule windows, stats/leaders windows, hall of fame, record notifications, physics tuning, and league rollover).
  - Preserved test monkeypatch compatibility by keeping legacy module constant names while making runtime path resolution active-league aware.
  - Extended `tests/test_phase5_path_isolation.py` with additional service checks for hall-of-fame, record snapshot, and physics tuning override writes after active-league switch.
  - Validation run: targeted rollover/hall-of-fame/record/phase5/stats + registry/trade/login-owner suites passed in `.venv2`.
- 2026-02-16: Extended Phase 5 into remaining playbalance modules:
  - Updated `playbalance/benchmarks.py`, `playbalance/playbalance_config.py`, and `playbalance/player_generator.py` to use active-league-aware dynamic path proxies for runtime data files.
  - Added player-generator runtime cache refresh guards so name pools, position guardrails, and normalized rating distributions re-resolve when active league data paths change.
  - Extended `tests/test_phase5_path_isolation.py` with playbalance benchmark/config/player-generator switch coverage and validated targeted Phase 5 + playbalance config suites in `.venv2`.
- 2026-02-16: Completed cache-isolation hardening pass for remaining high-risk runtime caches:
  - Refactored `playbalance/playbalance_config.py` to rebuild benchmark + override-backed defaults when the active league data paths change, while preserving test monkeypatch compatibility.
  - Updated `services/injury_simulator.py`, `utils/rating_display.py`, `playbalance/game_runner.py`, and `utils/player_loader.py` caches to key on resolved per-league paths/tokens so in-process league switches cannot reuse stale data.
  - Added expanded regression coverage in `tests/test_phase5_path_isolation.py` for playbalance config default refresh, injury catalog/team cache switching, physics-usage context resets, and player-loader stat/career + rating-display cache collisions.
  - Validation run: targeted multi-league Phase 5 + playbalance/injury/player-loader/login-owner suites passed in `.venv2`.
- 2026-02-16: Added rollback/restore support tooling:
  - Added `restore_pre_multi_league_layout(...)` in `services/league_migration.py` to restore legacy root layouts from migration backups with guarded overwrite behavior.
  - Extended `scripts/check_league_layout.py` with `--restore`, `--backup-path`, and `--force` for operator-friendly rollback execution.
  - Added migration regression test coverage for migrate -> restore round-trip in `tests/test_league_migration.py`.
- 2026-02-16: Closed out Phase 6 QA/release prep:
  - Ran automated release smoke matrix via `scripts/smoke_multi_league.py` (all checks passing).
  - Added `docs/post_installer_ui_checklist.md` for post-installer manual validation.
  - Ran targeted multi-league regression suites in `.venv2` and marked Phase 0-6 complete in this plan.
