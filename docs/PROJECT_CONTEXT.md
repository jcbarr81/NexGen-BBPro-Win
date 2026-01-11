# Project Context

## Focus
- Physics engine is the primary sim path; legacy engine is archived but retained.
- Goal: production-ready physics engine with realistic season stats and stable long-run behavior.

## Decisions Locked In
- Legacy engine is guarded; use `PB_ALLOW_LEGACY_ENGINE=1` to run it intentionally.
- Park factors are disabled for now to keep stats stable; revisit later.
- Injury history should be logged per season and shown in player profiles (date + description only).
- UI rating display should use hitter/pitcher-wide percentiles with a logistic curve (k=6) on a 35-99 scale, while Top % context remains position-based.

## Current State
- Physics engine is the default engine in `playbalance/game_runner.py`.
- Injury logging persists to `data/injury_reports/<season_id>.json`.
- Player profiles show an “Injury History” section.
- Season rollover archives stats/standings/playoffs/awards into `data/careers/<season_id>/` and updates `data/career_index.json` plus career ledgers in `data/careers/career_players.json` and `data/careers/career_teams.json`.
- Awards (MVP, CY_YOUNG) are generated during rollover via `playbalance/awards_manager.py` and stored in `data/careers/<season_id>/awards.json`.
- League history viewer is available from the Team Dashboard (League Hub) and Admin Dashboard, showing archived seasons and awards.
- No Hall of Fame system implemented.
- Pitcher roster UIs (full roster/pitchers dialogs) display `preferred_pitching_role` instead of the `role` field.
- Ratings remain normalized for simulation; UI display maps ratings to a 0-99 percentile scale by default using `data/players_normalized.csv` (fallback `data/players.csv`).
- Player profile Overall rating displays a 1-5 star scale.
- Full roster tables include an OVR column after player name.
- Latest locked config snapshot: `tmp/config_backups/physics_sim_config_locked_20251231_030700.py`.
- Latest KPI/long-run artifacts:
  - `tmp/long_term_runs/hr_tune_pass_20251230_215043`
  - `tmp/long_term_runs/stability_pass_20251229_024500`

## Key Paths
- Physics tuning: `physics_sim/config.py`
- Physics engine: `physics_sim/engine.py`
- Engine routing: `playbalance/game_runner.py`
- Injury history logging: `services/injury_history.py`
- Player profiles: `ui/player_profile_dialog.py`
- Season context: `playbalance/season_context.py`
- League rollover: `services/league_rollover.py`
- Awards selection: `playbalance/awards_manager.py`
- League history UI: `ui/league_history_window.py`
- Rating display mapping: `utils/rating_display.py`
- Full roster uses position buckets: C/1B/2B/3B/SS/OF.
- Career index: `data/career_index.json`
- Career ledgers: `data/careers/career_players.json`, `data/careers/career_teams.json`
- Injury catalog: `data/injury_catalog.json`
- Park config: `data/parks/ParkConfig.csv`
- Park factors (disabled): `data/parks/ParkFactors.csv`

## Running/Testing
- Use venv: `./.venv/bin/python`
- Targeted tests: `pytest` (per `AGENTS.md`)
- KPI sim: `./.venv/bin/python scripts/physics_sim_season_kpis.py`
- Full-season UI sim: launch `./.venv/bin/python main.py`

## KPI Targets (MLB deltas)
- Store the agreed benchmark deltas here (K%, BB%, AVG, OBP, SLG, HR/FB, SB%, etc.).
- Current HR tuning locked at `hr_scale=0.965`.

## Env Flags
- `PB_ALLOW_LEGACY_ENGINE=1` to run legacy intentionally.
- `PB_GAME_ENGINE=physics` (default; legacy archived).
- `PB_PERSIST_STATS=0/1` to skip or persist per-game stats.
- `PB_RATING_DISPLAY=raw|scale_99|stars` to control UI rating display (default `scale_99`).

## Data Defaults
- Use normalized players by default if available.
- League benchmarks: `data/MLB_avg/mlb_league_benchmarks_2025_filled.csv`.

## Known Risks / TODOs
- Park factors remain deferred; re-enable and validate later.
- Injury rates are currently low due to trigger gating; revisit if desired.
- Pitcher role display uses `players.csv` role field; all pitchers currently have `role=RP`, so roster UI shows only RPs even when `preferred_pitching_role` or `data/rosters/*_pitching.csv` indicates SP.
- Extend logistic position-based display mapping beyond Full Roster once validated.

## Do Not Change (unless revisiting tuning)
- HR scale and non-HR XBH lift are locked.
- Park factors remain disabled.
- Physics engine remains the default sim path.

## Conventions
- Use `rg` for searching.
- Follow PEP8.
- ASCII-only edits unless file already uses Unicode.
