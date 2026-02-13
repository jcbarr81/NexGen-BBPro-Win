# Career Flow & Season Rollover Plan

## Context
Season phases are tracked through `playbalance/season_manager.py`, which currently only serializes the active `SeasonPhase` into `data/season_state.json`. In-season statistics are streamed into `data/season_stats.json` with per-day shards under `data/season_history/` via `utils/stats_persistence.py`. The admin dashboard and player profile rely on `season_stats.json` for live data, but there is no archived view once a new year begins. As a result, postseason completion does not automatically create the next season or preserve season-scoped records for browsers or player cards.

## Goals
- Detect the moment a season completes and trigger a repeatable rollover pipeline.
- Freeze the just-completed season into immutable artifacts (stats, standings, playoffs, awards) keyed by season identifier.
- Reset active-season state (stats, schedules, rosters) without losing career totals.
- Expose historical season data to UI surfaces, especially player cards and league browsing tools.
- Provide scripts and tests to validate rollover integrity.

## Proposed Flow
Season completion is confirmed when the simulation sets `SeasonPhase` to `OFFSEASON` or when the playoffs champion is produced by `playbalance/playoffs.py`. The rollover service will run once, guarded by a season idempotency flag written to `data/career_index.json`. The service merges daily shards into the canonical stats file, snapshots critical tables, archives them under a season-specific directory, updates career aggregates, then resets in-season state for the upcoming year while incrementing the active season pointer.

## Implementation Steps
1. Season metadata model. Introduce a lightweight `SeasonContext` (new module, for example `playbalance/season_context.py`) responsible for tracking `season_id`, `year`, `start_date`, `end_date`, and upgrade status. Persist it in `data/career_index.json` with a schema that also lists archived seasons.
2. Rollover trigger integration. Extend `SeasonManager.advance_phase()` to emit an event or call into a new `LeagueRolloverService` when moving from `PLAYOFFS` to `OFFSEASON`. Ensure scripts such as `scripts/simulate_season.py` also invoke the service explicitly after playoffs wrap to cover headless runs.
3. Finalize statistics. Enhance `utils/stats_persistence.merge_daily_history()` usage to write a frozen `season_<season_id>_stats.json` payload that includes standings, leaderboards, and playoff results. Gather standings from `utils/standings_utils.py`, postseason outcomes from `playbalance/playoffs.py`, and awards from `playbalance/awards_manager.py`.
4. Archive artifacts. Create `data/careers/<season_id>/` to store `stats.json`, `standings.json`, `awards.json`, `playoffs.json`, and optional raw schedules (`schedule.csv`). Update `scripts/merge_season_history.py` to optionally write directly into this directory when invoked with a `--season` flag.
5. Update player and team career totals. Add helpers that roll per-season totals into `career_stats` on player objects and teams. Persist a consolidated `career_players.json` and `career_teams.json` hewing to the structures already consumed by `ui/player_profile_dialog.py` and `ui/admin_dashboard/pages/season.py`. Ensure season totals reset while cumulative career numbers continue to grow.
6. Reset for the new season. Clear per-season stats files, regenerate the upcoming schedule via `playbalance/schedule_generator.py`, advance aging via `playbalance/aging_model.py`, unlock offseason roster moves, and set `SeasonPhase` to `PRESEASON`.
7. UI and API integration. Extend player cards to read archived season files for historical rows, add a league history view in the admin dashboard, and expose a context selector for choosing the displayed season.
8. Backfill migration path. Ship a one-time script (for example `scripts/backfill_career_history.py`) that iterates existing shards in `data/season_history/` to populate the new archive structure for users with ongoing saves.
9. Automated tests. Add unit tests for the new season context module, rollover orchestration, and history readers. Integrate an end-to-end test in `tests/test_season_simulator.py` that simulates through playoffs, runs the rollover, and asserts that the next season starts in `PRESEASON` with archived stats available.

## Data and Migration Considerations
Define JSON schemas for `career_index.json` and per-season snapshots so future migrations stay backward compatible. Store schema versions alongside each file. During rollout, guard against partial failures by writing to temporary files and renaming on success. Provide a CLI flag to rerun rollover if a previous attempt failed before the idempotency marker was set.

## Testing Strategy
- Unit: season context persistence, rollover service, stats archiving helpers, and backfill script.
- Integration: full season simulation verifying file outputs and state resets.
- UI regression: snapshot tests for player cards and league history views against mocked archive data.
- Smoke: run `pytest tests/test_season_simulator.py tests/test_season_manager.py` after implementing rollover.

## Open Questions
- Confirm canonical season identifier format (numeric year vs. sequential counter) to support custom league calendars.
- Decide whether postseason awards should be stored in a single file or per-award documents for flexibility.
- Determine retention policy for raw per-day shards once archived.
- Validate whether offseason transactions between rollover and opening day require additional audit logging.
