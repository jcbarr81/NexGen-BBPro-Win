# Project Context

> **Updated 2026-11-04 (VERSION 8.11.0).** The product is the cloud web app
> (FastAPI `api/` on Cloud Run, React `desktop/src/` on Firebase Hosting); the
> PyQt `ui/` app is retired. The full onboarding map is
> `docs/CODEX_HANDOFF.md`; what shipped is in `release_notes_draft.md`.

## Focus
- Physics engine is the primary sim path; legacy engine is archived but retained.
- Goal: production-ready physics engine with realistic season stats and stable long-run behavior.

## Decisions Locked In
- Legacy engine is guarded; use `PB_ALLOW_LEGACY_ENGINE=1` to run it intentionally.
- Park factors are disabled for now to keep stats stable; revisit later.
- Injury history should be logged per season and shown in player profiles (date + description only).
- UI rating display (rating scale 1 leagues only): hitter/pitcher-wide percentiles with a logistic curve (k=6) on a 35-99 scale, while Top % context remains position-based. Leagues on rating scale 2 (8.0.0: every league created with the switch on, and each older league from its next rollover) show every rating as stored on the full 1-99 scale, and the overall as a fixed stretch of the engine overall (`utils/rating_display.py`; pitchers use the hitters' stretch since 8.6.3).
- Engine generation 6 + rating scale 2 is on in production (`NEXGEN_GENERATION6_SCALE2`); never switch it off once a league plays generation 6 (`docs/rating_scale_switch_runbook.md`). Generation 7 (ball flight) ships off (`NEXGEN_GENERATION7`).

## Current State
- Physics engine is the default engine in `playbalance/game_runner.py`.
- Injury logging persists to `data/injury_reports/<season_id>.json`.
- Player profiles show an "Injury History" section.
- Season rollover archives stats/standings/playoffs/awards into `data/careers/<season_id>/` and updates `data/career_index.json` plus career ledgers in `data/careers/career_players.json` and `data/careers/career_teams.json`.
- Awards (MVP, CY_YOUNG) are generated during rollover via `playbalance/awards_manager.py` and stored in `data/careers/<season_id>/awards.json`.
- League history is on the web client's League History page (`desktop/src/pages/LeagueHistoryPage.tsx`), showing archived seasons and awards.
- Hall of Fame system is implemented with automated candidate scoring, manual
  induction controls, and a league-history integration surface (`HallOfFamePage.tsx`).
- Decide a pitcher's SP/RP role with `utils/pitcher_role.get_role` (explicit position, then `preferred_pitching_role`, then endurance; the stored `role` last). The stored `role` column in `players.csv` is stale ("RP") in older leagues and must not be read directly. The Pitchers page splits starters and relievers by the club's staff assignments (8.0.0).
- Ratings remain normalized for simulation. On rating scale 1 the UI maps ratings to a 0-99 percentile scale by default; on scale 2 they are shown as stored (above). New players are generated from `data/players_normalized.csv`.
- OVR is one production-weighted score in `utils/player_overall.py`, shared by the display, depth-chart autofill, CPU auto-assign and CPU trades; yearly prospect promotion deliberately keeps its own flat average (`services/prospect_promotion._player_overall`, backlog #51) (hitters: 0.45 CH + 0.45 PH + 0.07 EYE + 0.03 SP plus a provisional position-weighted FA/ARM term; pitchers: 0.47 CO + 0.38 MO + 0.15 mean grade of the pitches thrown, endurance only nudging starters). On scale 1 the displayed OVR percentile-scales that score in `utils/rating_display.py` (logistic k=6), or shows it raw when the league SD is under 3; on scale 2 it is the fixed stretch above. Since 8.6.4 the CPU's draft auto-pick, free-agent signing order, trade proposals, retirement and call-ups use this score too; CPU free-agent bidding and arbitration still use the old flat averages (backlog #52).
- Star ratings (1-5 in 0.5 increments) render in the web client through `desktop/src/components/StarRating.tsx`.
- Older local artifacts (December 2025, before the 2026-10 engine audit; not current tuning) -- locked config snapshot: `tmp/config_backups/physics_sim_config_locked_20251231_030700.py`.
- KPI/long-run artifacts from the same period:
  - `tmp/long_term_runs/hr_tune_pass_20251230_215043`
  - `tmp/long_term_runs/stability_pass_20251229_024500`

## Key Paths
- Physics tuning: `physics_sim/config.py`
- Physics engine: `physics_sim/engine.py`
- Engine routing: `playbalance/game_runner.py`
- Injury history logging: `services/injury_history.py`
- Player profiles: `desktop/src/pages/PlayerProfilePage.tsx` (view model `services/player_profile_view_model.py`)
- Season context: `playbalance/season_context.py`
- League rollover: `services/league_rollover.py`
- Awards selection: `playbalance/awards_manager.py`
- League history UI: `desktop/src/pages/LeagueHistoryPage.tsx`
- Engine generations: `physics_sim/engine_generation.py`, profiles in `physics_sim/profiles/`
- Rating scale 2 conversion: `utils/rating_scale.py`, `services/rating_scale_migration.py`
- Rating display mapping: `utils/rating_display.py`
- Full roster uses position buckets: C/1B/2B/3B/SS/OF.
- Career index: `data/career_index.json`
- Career ledgers: `data/careers/career_players.json`, `data/careers/career_teams.json`
- Injury catalog: `data/injury_catalog.json`
- Park config: `data/parks/ParkConfig.csv`
- Park factors (disabled): `data/parks/ParkFactors.csv`

## Running/Testing
- Use venv: `.\.venv\Scripts\python.exe` (Python 3.11; the `python` on PATH). Do not use `.venv2` (broken: Python 3.12 base with cp311 packages).
- Targeted tests: `python -m pytest tests\test_<area>.py` (per `AGENTS.md`); full suite `python scripts\run_tests_isolated.py -j 12`, with `PYTHONHASHSEED=0`.
- KPI sim: `python scripts\physics_sim_season_kpis.py --strict --seed 1` (and `--seed 2`).
- Local app: `python -m api --port 8765`, then `cd desktop; npm run dev:vite` (see `docs/CODEX_HANDOFF.md` section 4).

## KPI Targets (MLB deltas)
- Store the agreed benchmark deltas here (K%, BB%, AVG, OBP, SLG, HR/FB, SB%, etc.).
- `DEFAULT_TUNING` `hr_scale` is 0.925 (`physics_sim/config.py`); it is also the commissioner's Home Run Rate slider, which generation 7 reads as fly-ball carry.

## Env Flags
- `PB_ALLOW_LEGACY_ENGINE=1` to run legacy intentionally.
- `PB_GAME_ENGINE=physics` (default; legacy archived).
- `PB_PERSIST_STATS=0/1` to skip or persist per-game stats.
- `PB_RATING_DISPLAY=raw|scale_99|stars` to control UI rating display on rating scale 1 (default `scale_99`).
- `PB_PARALLEL_GAMES=<workers>|auto` plays a day's games in worker processes (production sets 2; unset = serial).
- `NEXGEN_GENERATION6_SCALE2=1` (on in production), `NEXGEN_GENERATION7` (off), `NEXGEN_NEW_SEASON_ENGINE`, `NEXGEN_RESPREAD_LEAGUES`: engine/rating-scale operations switches (runbooks in `docs/`).
- `NEXGEN_DATA_ROOT` points the app at a data folder (use a scratch folder for local copies of a league).

## Data Defaults
- Use normalized players by default if available.
- League benchmarks: `data/MLB_avg/mlb_league_benchmarks_2025_filled.csv`.

## Known Risks / TODOs
- Park factors remain deferred (`park_factor_scale` 0.0); generation 7, when switched on, plays each real park's dimensions and walls instead of factors.
- Injury rates were calibrated to MLB in 7.21.0 and re-checked in Release 3 (owner decision: about 3/4 of MLB's rate); open injury follow-ups are in `docs/future_work.md` (#58, #61).
- Keep validating that pitcher role views go through `get_role` / the staff
  assignments; regressions to raw `role` values can collapse SP/RP
  presentation.
- Extend logistic position-based display mapping beyond Full Roster once validated.

## Do Not Change (unless revisiting tuning)
- HR scale and non-HR XBH lift are locked.
- Park factors remain disabled.
- Physics engine remains the default sim path.

## Conventions
- Use `rg` for searching.
- Follow PEP8.
- ASCII-only edits unless file already uses Unicode.

