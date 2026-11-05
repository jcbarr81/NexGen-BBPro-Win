# Architecture & Data Flow

_Rewritten 2026-11-04 (VERSION 8.11.0). The October 2025 notes this file used
to hold described the retired PyQt desktop app; they are kept at the end as
history. For onboarding detail (testing, traps, current state) read
`docs/CODEX_HANDOFF.md`._

## Deployment

| Piece | Where | Notes |
|---|---|---|
| Web client | Firebase Hosting, site `nexgen-bbpro` | React 18 + TypeScript + Tailwind in `desktop/src/`, built by `npm run build:renderer` (Vite) into `desktop/dist`. `firebase.json` rewrites every non-file path to Cloud Run, so the API is same-origin. |
| API | Cloud Run service `nexgen-bbpro-api` (`us-central1`, project `nexgen-bbpro`) | FastAPI (`api/app.py`, routers in `api/routers/`), one image from `Dockerfile`, at most one instance. |
| Accounts | Firebase Auth + Firestore | The client signs in with the Firebase JS SDK (`desktop/src/lib/firebase.ts`); the API verifies the ID token (`api/firebase_auth.py`, on with `NEXGEN_FIREBASE=1`). Accounts, the league catalog, memberships, invites and join requests live in Firestore (`services/firestore_store.py`); game data, `users.txt` included, stays in the bucket. |
| League data | GCS bucket `nexgen-bbpro-data` | Mounted by gcsfuse at `/data` (`NEXGEN_SYNC_REMOTE`). Each league is a folder of CSV/JSON files (`leagues/<id>/data/`). |
| Scheduled work | Cloud Scheduler job `nexgen-autorun-tick` (every 10 min) | POSTs `/season/schedule/tick` with the `NEXGEN_SCHEDULER_TOKEN` secret: due auto-run sims, draft pick clocks, free-agency window deadlines, avatar recolors. |
| Notifications out | Discord webhooks, SendGrid | `services/discord_notify.py` (`NEXGEN_DISCORD_WEBHOOK_URL`, optional `NEXGEN_DISCORD_DRAFT_WEBHOOK_URL`); invite email via `services/email_sender.py` (`SENDGRID_API_KEY`). Secrets come from Secret Manager. |
| Images | Vertex AI | Logos and player avatars (`utils/vertex_image.py`, `NEXGEN_VERTEX_IMAGES`). |

The Electron desktop app, the Windows installer and the PyQt UI are retired.

## Request flow

1. The client calls the API with `Authorization: Bearer <token>` and
   `X-League-Id` (`desktop/src/lib/api.ts`, `apiRequest()`).
2. `LeagueContextMiddleware` (`api/app.py`) binds the league for the request
   (`utils/path_utils.set_request_league`), so every read and write in it goes
   to that league's folder (`get_data_dir()`).
3. `api/security.py` resolves the identity (`require_bearer`); every
   team-scoped write calls `require_team_owner`. Club ownership is read from
   the league's `users.txt` (`services/team_ownership.py`).
4. Routers call the services layer (`services/`: contracts, finance, free
   agency, drafts, trades, rollover, notifications, ...) and the season
   orchestration in `playbalance/`.
5. After a mutating request the working copy pushes the changed files back to
   the bucket before the response returns (below).

Live games stream over WebSocket (`api/ws/sim.py`); the client connects to the
Cloud Run URL directly because Hosting does not proxy WebSockets.

## Storage: the working copy

`api/working_copy.py` (on with `NEXGEN_WORKING_COPY=1`): at startup the app
pulls the bucket into a fast local folder (`NEXGEN_DATA_ROOT=/work/data`),
serves every request from it, and after each mutating request pushes every
file whose (mtime, size) changed, and deletes on the bucket what was deleted
locally. Background jobs (sims, CPU free agency, avatar work) run through
`working_copy.as_background_writer` and push when they finish; a graceful
shutdown flushes what is left. Writers use atomic replaces
(`utils/atomic_write.py`) and file locks (`api/file_lock.py`). Locally none of
this runs: the app reads and writes `NEXGEN_DATA_ROOT` or the repo's `data/`.

## Simulation

`api/routers/season.py` → `playbalance/season_simulator.py` (day by day, per-game
seeds, batched stat writes; `PB_PARALLEL_GAMES` plays a day's games in worker
processes) → `playbalance/game_runner.py` → `physics_sim/engine.py::simulate_game`.
Each league season is given an engine generation when it starts
(`physics_sim/engine_generation.py`): the tuning is `DEFAULT_TUNING`, then the
generation's profile (`physics_sim/profiles/engine_<N>.json`), then the
league's commissioner overrides and rating centres (`services/league_tuning.py`).
Generation 6 with the full 1-99 rating scale is on behind
`NEXGEN_GENERATION6_SCALE2`; generation 7 (ball flight) ships off behind
`NEXGEN_GENERATION7`. The legacy PB.INI engine in `playbalance/` runs only with
`PB_ALLOW_LEGACY_ENGINE=1`.

Realism is gated by `scripts/physics_sim_season_kpis.py --strict` against
`data/MLB_avg/` benchmarks on committed fixtures (`data/calibration*`), in CI by
`.github/workflows/physics_sim_kpi.yml`.

## Historical notes (October 2025, PyQt desktop era)

These were improvement ideas for the desktop app. The `ui/` widgets they cite
(`ui/admin_dashboard.py`, `ui/owner_dashboard.py`, `ui/playbalance_editor.py`)
no longer exist; persistence is still CSV/JSON files (no SQLite layer), now
synced to GCS by the working copy.

- Centralize persistence behind a repository/SQLite layer so modules stop
  re-opening CSV/JSON files independently (`utils/player_loader.py`,
  `services/transaction_log.py`, `playbalance/season_manager.py`).
- Move business logic out of widgets into reusable services with an event bus
  (done in effect: the web client talks to the FastAPI services layer).
- Version and surface configuration bundles for play-balance tuning
  (`playbalance/playbalance_config.py`). Engine tuning now lives in
  `physics_sim/config.py`, generation profiles and per-league overrides.
- Extend stats persistence with structured logging/telemetry alongside the
  daily shards (`utils/stats_persistence.py`).
