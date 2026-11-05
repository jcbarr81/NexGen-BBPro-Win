# NexGen-BBPro — Developer Handoff (for OpenAI Codex or any new contributor)

> **Read this first, then keep it open.** It is the single onboarding map for
> picking up development. It points you at the authoritative files, explains how
> the pieces fit, tells you exactly how to run and test the project, and lists
> the traps that will otherwise cost you hours. It was first written 2026-07-16
> against `main` @ VERSION **7.0.11** and brought up to date 2026-11-04 at
> VERSION **8.11.0** (sections 1, 2, 4, 5 and 7 rewritten for the cloud-only
> product; the engine, testing-trap and gotcha sections still hold).

---

## 0. The files that are "source of truth"

Docs in this repo drift; several planning docs carry dated reconciliation
banners. When something here disagrees with reality, believe the code + these:

| File | What it authoritatively covers |
|---|---|
| `AGENTS.md` | Repo conventions (Codex reads this first): venv, test commands + the known failures, versioning/SemVer, release-note workflow. |
| `release_notes_draft.md` | **What has actually shipped, one entry per version** (7.1 to the current VERSION, oldest first). Git log is the other. `release_notes.md` stops at 7.2 — don't use it for anything newer. |
| `docs/future_work.md` | The backlog, numbered (#7 … #71). Shipped items keep a **SHIPPED x.y.z** marker for their design history; older items use stale "v5.x" milestone language. |
| `docs/audits/2026-10-06-engine-ratings-audit/` | The engine/ratings audit that drove 7.45–8.1: `REPORT.md` (findings), `DECISIONS.md` (the owner's numbered decisions the code cites), `RELEASE4/5/6_PLAN.md`. |
| `docs/deep_review_plan.md` | The "truth document" for the 2026-07 improvement program (Sprints 0–2, complete). Historical now. |

`README.md` is the product summary. Up to 8.11.0 it still described the 7.x
desktop + cloud split (Electron, `.venv2` commands); if it and this file
disagree, prefer this file and `RELEASE.md` (deploy steps).

Everything below consolidates the operational knowledge that is otherwise spread
across those and learned the hard way.

---

## 1. What the product is

A full baseball-league simulation game: create a league, manage rosters,
contracts, finances, scouting, drafts, and trades, and simulate seasons
**pitch-by-pitch** with a physics-based engine. It is a **cloud web app only**
(multi-tenant, several human owners per league):

- the FastAPI backend on **Google Cloud Run** (service `nexgen-bbpro-api`,
  region `us-central1`, project `nexgen-bbpro`, one instance at most);
- the React UI on **Firebase Hosting** (site `nexgen-bbpro`), which rewrites
  every non-file path to the Cloud Run service (`firebase.json`);
- **Firebase Auth + Firestore** for accounts, memberships and the per-request
  active league (`X-League-Id` header);
- league data as files in the GCS bucket `nexgen-bbpro-data`, mounted into
  the container and worked on through a local copy (§2);
- a **Cloud Scheduler** job (`nexgen-autorun-tick`, every 10 minutes) that
  drives commissioner-scheduled sims, pick clocks and free-agency deadlines.

The **Electron desktop app and the Windows installer are retired** (the React
code still lives in `desktop/` and `npm run dev` still starts Electron, but
nothing ships that way). The old **PyQt6 desktop UI is retired** too; what is
left of `ui/` is not imported by `api/`, `services/`, `playbalance/` or
`utils/`.

---

## 2. Architecture map

| Layer | Where | What |
|---|---|---|
| UI | `desktop/` | React 18 + TypeScript + Tailwind (~60 pages, `HashRouter`). `desktop/src/lib/api.ts` is the typed API client; `apiRequest()` attaches the bearer token + `X-League-Id`. Built with `npm run build:renderer` (Vite → `desktop/dist`) and served by Firebase Hosting. Sign-in uses the Firebase JS SDK (`desktop/src/lib/firebase.ts`). Live-game WebSockets go straight to the Cloud Run URL (Hosting does not proxy WS; `desktop/.env`). |
| API | `api/` | FastAPI backend. `api/app.py` builds the app; routers live in `api/routers/*.py` (56). Auth in `api/security.py` (`require_bearer` → identity; `require_team_owner` on every `{team_id}` write) and `api/firebase_auth.py` (`NEXGEN_FIREBASE=1`). WebSocket live-game streaming in `api/ws/`. `/meta/app-status` and `/healthz` report the running VERSION. |
| Storage | `api/working_copy.py`, `utils/path_utils.py` | On Cloud Run the bucket is a gcsfuse mount (`NEXGEN_SYNC_REMOTE=/data`); with `NEXGEN_WORKING_COPY=1` the app pulls it into a local dir (`NEXGEN_DATA_ROOT=/work/data`) at startup, serves every request from there and pushes changed files back after each mutating request (and on shutdown). Background threads that write league data must run through `working_copy.as_background_writer`. Each league is a folder of CSV/JSON files under `data/leagues/<id>/data/`. |
| Scheduler | `api/routers/season.py` (`machine_router`) | `POST /season/schedule/tick`, authorized by the `NEXGEN_SCHEDULER_TOKEN` secret, not a user token: runs due auto-run sims, draft pick clocks, free-agency window deadlines and avatar recolors for every league. |
| Services | `services/` | Business logic: finance, contracts, trades (`cpu_trade_proposals.py`, `cpu_trade_evaluator.py`, `trade_execution.py`), team outlook, callups (`inseason_callups.py`), scouting, drafts, prospect rules, analytics, league lifecycle/registry/rollover, standings, etc. |
| **Sim engine (shipping)** | `physics_sim/` | The physics-first game engine: pitch flight, contact, fielding, usage/fatigue. `physics_sim/engine.py` (`simulate_game`), `config.py` (`DEFAULT_TUNING` knobs), `physics.py`, `usage.py`, `models.py`. This is what runs games. **Engine generations** (`physics_sim/engine_generation.py`): each league season is given a generation when it starts — 4/5 are `DEFAULT_TUNING` (+ `profiles/engine_5.json`); 6 (8.0.0, with ratings converted to the full 1-99 "scale 2") is live behind `NEXGEN_GENERATION6_SCALE2=1`; 7 (ball flight, real parks, 8.1.0) is shipped **off** behind `NEXGEN_GENERATION7`. Runbooks: `docs/rating_scale_switch_runbook.md`, `docs/generation7_switch_runbook.md`. |
| Legacy engine (gated) | `playbalance/` | The original PBINI-driven engine + season orchestration. The **game** part is archived — it only runs under `PB_ALLOW_LEGACY_ENGINE=1` (`playbalance/legacy_guard.py`). But **season orchestration helpers here are still live** (e.g. `playbalance/season_manager.py`, `season_simulator.py`, `game_runner.py` which dispatches to the physics engine). |
| Data | `data/` | CSV/JSON game data. The committed sample league lives under `data/leagues/cbl/data/`. `data/MLB_avg/` holds the real-MLB benchmark tables the KPI harness compares against. `data/` is excluded from the image (`.dockerignore`); live leagues exist only in the bucket. |
| Auth | Firebase (cloud) / HMAC session token (local) | `NEXGEN_FIREBASE=1` turns on the cloud control plane; local uses `users.txt` + a signed session token. **Team ownership lives in each league's `users.txt`, not `teams.csv`** — use `services/team_ownership.py` (`human_owned_team_ids_strict` for anything that acts for CPU clubs). |

**Game execution path (the important one):**
`api/routers/season.py` → `playbalance/game_runner.py::simulate_game_scores`
→ resolves engine via `_resolve_game_engine(None)` → **"physics"** →
`physics_sim/engine.py::simulate_game`. The `SeasonSimulator`
(`playbalance/season_simulator.py`) drives day-by-day scheduling, per-game seeds,
and the per-day batched stats/recovery writes.

---

## 3. The simulation engine — how it's kept honest

The physics engine is tuned against **real MLB benchmarks**, not vibes. Two
harness scripts are the gates:

- **KPI harness — `scripts/physics_sim_season_kpis.py`.** Simulates a season and
  compares ~dozens of metrics (AVG/OBP/SLG, K%, BB%, SwStr%, HR/game, batted-ball
  mix, plus dispersion + usage + platoon + TTO gates added in Sprint 2) against
  `data/MLB_avg/mlb_league_benchmarks_2025_filled.csv` within tolerances. Run
  with `--strict` to make any out-of-tolerance metric fail. **This is the gate
  for any change that could move on-field outcomes.** The convention is
  "green on seeds 1 AND 2, 162 games" before committing an engine/calibration
  change.
  - It sims against a **committed calibration fixture** (`data/calibration/`,
    generated deterministically by `scripts/generate_calibration_roster.py`) so
    runs are reproducible and never touch a real league. Two more fixtures
    exist: `data/calibration_league` (a league-like spread, from
    `scripts/generate_league_fixture.py`) and `data/calibration_flat`
    (bunched ratings). `--engine 6` / `--engine 7` run the later engine
    generations; CI (`.github/workflows/physics_sim_kpi.yml`) runs on PRs
    that touch the engine, the harness or the services it reads.
- **Parity/benchmark harness — `scripts/benchmark_sim_days.py`.** Times an N-day
  sim on a throwaway copy of a league and emits digests (`scores`,
  `season_stats`, `pitcher_recovery`) so a pure-performance change can *prove* it
  didn't alter behavior (same seed + same code → identical digests).
  **Caveat:** digests are only comparable **same calendar day** (some paths key
  off the wall-clock date), so re-baseline the pre-change code the same day.

**Determinism rules (respect these or reproductions break):**
- Always run sims/tests with `PYTHONHASHSEED=0` (some set iteration order feeds
  RNG; the harness re-execs itself to pin it).
- Per-game seeds are generated in `SeasonSimulator.simulate_next_day`. The
  engine reseeds *global* `random` per game, so anything reading global random
  across games is order-sensitive.

---

## 4. Environments & running

**Prereqs:** Python 3.11+, Node 20+. (The Cloud Run image runs Python 3.12
— `Dockerfile` — while local development and tests use the 3.11 `.venv`.)

**Python virtualenv:** use **`.venv`** (Python 3.11; the `python` on PATH).
`.venv2` is broken -- its base interpreter was switched to Python 3.12 while
its packages are cp311 builds, so pydantic/fastapi imports fail. Don't use it.
(If you see import errors for `fastapi`/`numpy`, install the runtime deps — see
below.)

**Dependencies:**
- `requirements-server.txt` — **the Cloud Run runtime set** (fastapi, uvicorn,
  pydantic, portalocker, httpx, websockets, numpy, bcrypt, Pillow,
  opencv-python-headless, firebase-admin). Install this to run the backend + the
  API tests locally; it mirrors production exactly.
- `requirements-dev.txt` — the above API stack **plus** the heavy local-only
  ML/image stack (torch, diffusers, transformers, opencv) used for logo/avatar
  generation and the retired PyInstaller packaging.

```powershell
# backend deps that match production
.\.venv\Scripts\python.exe -m pip install -r requirements-server.txt

# local API + browser UI (no Electron): two terminals
.\.venv\Scripts\python.exe -m api --port 8765   # API on 127.0.0.1:8765
cd desktop; npm install; npm run dev:vite        # http://localhost:5173 (.env.development points at 8765)

# client type check (the AGENTS.md "tsc check")
cd desktop; npm run typecheck
```

Local runs never set `NEXGEN_FIREBASE` / `NEXGEN_WORKING_COPY`, so they use
`users.txt` logins and the repo's `data/` (or `NEXGEN_DATA_ROOT`). Never point
a local run at a copy of a live league without `NEXGEN_DATA_ROOT` set to a
scratch folder.

**Deploy (cloud):** the exact steps are in `RELEASE.md` — backend
`gcloud run deploy nexgen-bbpro-api --source . --project nexgen-bbpro --region us-central1`
(builds the `Dockerfile`; uploads filtered by `.gcloudignore`; env vars and
secrets carry over to the new revision), client
`cd desktop; npm run build:renderer` then
`npx firebase-tools deploy --only hosting --project nexgen-bbpro` from the
repo root, then `python scripts/announce_release.py --message "..."` to post
to Discord. Deploys are outward-facing (live leagues with human owners):
confirm with the owner before deploying.

`scripts\build_release.py` (the Windows EXE + installer) is retired; don't
run it for a release, whatever older docs say.

---

## 5. Testing — READ THIS BEFORE YOU TRUST A GREEN/RED RESULT

This is the single most important operational section. The suite has **pervasive
shared process-global state** (the active `data/` league dir, module-level
singletons/caches, and several tests that `importlib.reload` modules — which
breaks later monkeypatches). Consequences:

- **Every test file passes on its own.** ✅
- **A single `pytest` invocation over the whole suite has ~50 failures** — these
  are *cross-file pollution*, **not real bugs**. They are diffuse (spread over
  ~28 files, heaviest in the league-lifecycle/registry/migration/rollover files).
- Windows has **no `os.fork`**, so `pytest-forked` / true per-test process
  isolation is unavailable.

### The green gate

```
python scripts/run_tests_isolated.py            # full gate, one file at a time (~23 min)
python scripts/run_tests_isolated.py -j 12      # full gate, 12 at a time (~3.5 min)
python scripts/run_tests_isolated.py -k trade    # only files whose name matches
python scripts/run_tests_isolated.py --list      # list files, don't run
```

`scripts/run_tests_isolated.py` runs **each `tests/test_*.py` file in its own
pytest subprocess** (fresh interpreter → zero cross-file leakage), restores
`data/` between files, and exits non-zero on any failure. **This is the
authoritative "is the suite green" check.** At 8.11.0 there are 435 test
files; five fail in every run and are known, not regressions:
`test_league_command_center`, `test_openai_client`, `test_payroll_policy`,
`test_phase5_path_isolation`, `test_team_loader` (`AGENTS.md`). Anything else
red is yours.

`-j N` (8.8.3) runs N files at a time. Tests write into the checkout's
`data/`, so files can't share one checkout: the driver commits a snapshot
of the working tree with a throwaway index (your index is untouched;
untracked files included, stray `data/leagues` dirs left out), checks it out
into N worktrees under the temp dir, gives each the next file (slowest
first, from the times saved in `.git/nexgen-test-durations.json`), gives
each its own pytest `--basetemp`, and removes the worktrees at the end.

`tests/conftest.py` also does a cheap per-test env restore (`NEXGEN_*`,
`PB_SIM_*`) and a session-end `data/` cleanup so a plain `pytest` run never
leaves the working tree dirty. **That cleanup is `git checkout -- data` plus
`git clean -fdq -- data/leagues`: it silently reverts any unstaged edit you
made to a tracked file under `data/`** (stage or commit data edits before
running tests).

When the full suite isn't needed (a small contained change), run the area's
test files plus the cross-cutting pins `tests/test_rating_scale_display.py`
and `tests/test_team_scoped_write_ownership.py`, and the client type check.
The type check is **not clean on `main`**: `npm run typecheck` (or
`npx tsc --noEmit -p tsconfig.json`) reports ~26 pre-existing strict-mode
errors at 8.11.0, so compare against `main` and add none.

### Iron rules for the test suite

1. **Never let a test pollute the active league.** Tests read/write the shared
   `data/leagues/cbl/data/` dir. If a test must write, redirect it to a
   `tmp_path` (see the patterns in `tests/test_record_notifications.py`,
   `test_league_snapshot.py`, `test_boxscore_html_save.py`), or snapshot/restore
   the file (see the autouse fixture in `tests/test_pitcher_usage_windows.py`).
   `git checkout -- data/leagues` reverts **tracked** files only — **untracked**
   pollution survives it; use `git clean -fdq data/leagues` too.
2. **Never run sims/tests against a real user league.** Use the calibration
   fixture / tmp dirs.
3. Run with `PYTHONHASHSEED=0` for reproducibility.
4. A handful of tests are intentionally `xfail`/`skip` with explicit reasons —
   legacy-engine behavior (physics is the shipping path, KPI-gated separately),
   archived legacy CLIs (need `PB_ALLOW_LEGACY_ENGINE=1`) and Windows-only
   `os.replace`-on-open-file semantics. Don't "fix" these by deleting the
   reason. (The old `players_normalized.csv` xfail is gone: the file was
   restored.)

Two files are excluded from the default gate on purpose: `test_auto_tune_solver`
(archived legacy engine) and `test_build_exe` (PyInstaller packaging).

---

## 6. Conventions & workflow (from `AGENTS.md`)

- **Versioning (SemVer) via the `VERSION` file.** PATCH for fixes/tests/small
  UX; MINOR for complete user-facing features; MAJOR only with explicit
  confirmation. **Docs-only changes need no bump.** When you bump `VERSION`,
  match `AppVersion` in `packaging/NexGen-BBPro.iss` (the installer is retired
  but `AGENTS.md` still asks for it, and every release commit does it).
- **Release notes:** add one entry per version to `release_notes_draft.md`
  (plain, owner-facing wording; see the 8.x entries). `release_notes.md` has
  not been updated since 7.2.
- **Backlog:** add new ideas to `docs/future_work.md`.
- **New features:** create a tutorial/guide and wire it into the menu.
- Use `rg` (ripgrep) for searching; PEP8 style.
- **The truth-doc discipline (from the 2026-07 program):** for a planned task,
  a change is only "Done" when its verification gate passed **and** it's
  committed — record the commit hash in `docs/deep_review_plan.md` (status row +
  a dated change-log entry). Keep that discipline for any resumed Sprint work.

---

## 7. Current state — where development was left off (2026-11-04, VERSION 8.11.0)

**Deployed vs. committed.** The live service reported **8.9.0** on
2026-11-04 (`https://nexgen-bbpro.web.app/meta/app-status`). `main` holds
8.9.1, 8.10.0 and 8.11.0, committed but **not deployed**, and is 5 commits
ahead of `origin/main` (not pushed). The three are meant to go out together;
8.9.1 also settles the 16 negotiations alpha-test's 2027 free-agency window
left open, which it does only once the league is out of the amateur draft
(its release note).

**Live leagues and operations switches.** Two live leagues with human owners,
`alpha-test` (seven owner clubs) and `stats-test`. Cloud Run env (checked
2026-11-04): `NEXGEN_GENERATION6_SCALE2=1` (the 8.0.0 switch: each league
moves to engine generation 6 + the full 1-99 rating scale at its next
rollover), `NEXGEN_RESPREAD_LEAGUES=alpha-test`, `PB_PARALLEL_GAMES=2`;
`NEXGEN_GENERATION7` is **unset** (ball flight off). **Never turn the 8.0.0
switch off once a league plays generation 6** — hold new moves with
`NEXGEN_NEW_SEASON_ENGINE=5` instead (`docs/rating_scale_switch_runbook.md`).
Secrets are Secret Manager references: `SENDGRID_API_KEY`,
`NEXGEN_SCHEDULER_TOKEN`, `NEXGEN_DISCORD_WEBHOOK_URL`.

**Most recent releases** (full text: `release_notes_draft.md`):
- **8.9.0** — free-agent prices re-anchored to the real quality spread, with
  the player's last three big-league seasons blended in (backlog #66).
- **8.9.1** — every free-agent negotiation settles inside the bidding window;
  the window stays open on its last day until none is open.
- **8.10.0** — a Columns menu on the Roster, Free Agency, Players, Position
  Players, Pitchers and Lineup tables; every pitch rating; drag-and-drop
  pitching staff with swap (#69, #68).
- **8.11.0** — CPU clubs draft by need (`services/draft_board.py`
  `cpu_plan` / `cpu_choose`, `api/routers/draft.py`); owners with no draft
  board are picked for the same way (#70).

Earlier 8.x, for orientation: 8.0.0 engine generation 6 + scale 2 + player
development; 8.1.0 generation 7 (shipped off) and one-club-per-player
fixes; 8.1.1 postseason stats in their own file; 8.2.0 the dashboard
Spotlight; 8.4.0 postseason pages; 8.5.x extension talks and service time;
8.6.x free-agent asking prices, realistic retirements, a Discord draft
channel; 8.7.x owners' draft boards; 8.8.x free-agent bid standing,
owner-only notifications, the parallel test runner.

**Open work — pick up here** (`docs/future_work.md` has the detail):
1. **Deploy 8.9.1–8.11.0** when the owner gives the word (§4, `RELEASE.md`).
2. **#64 MLB-like salary arbitration** — fully specified, but the owner said
   to leave today's behaviour alone for now.
3. **#52 remainder** — CPU free-agent bidding and arbitration still score
   players on the old flat rating average; their bars are stored per league
   in `finance_ai_tuning`, so switching needs a matched bar plus a migration.
   `services/draft_ai.py` is still unused (8.11.0 built need-aware drafting
   in `draft_board.py` instead): wire it or delete it.
4. **#51** retune prospect promotion for the shared overall; **#35** pick
   your team in the league-creation wizard; **#48** an unresolvable
   `NEXGEN_DATA_ROOT` silently falls back to the repo's `data/`.
5. **Engine:** turning on generation 7 (`docs/generation7_switch_runbook.md`;
   park data first, `docs/park_data_generation7_runbook.md`); #55 explicit
   park picks for older leagues; #57 fast runners in the generator; #58
   report-only KPI gates to promote.
6. **Follow-up lists** from each release: #60 (26-man roster), #61
   (Release 3), #62 (Release 4), #63 (preseason draft), and the dated
   Release 5 / 6a / 6b / 8.0.0 sections.
7. **Not started:** #7.3–7.5 owner messaging, chat rooms, forums / trade
   block; #20 player morale; #26 What-If Lab (deferred); the rest of #24
   team strategy profiles.
8. **(Optional) True single-process test isolation.** Making a *single*
   `pytest` run green would need every test's data dir redirected to a
   per-test tmp and the reload-heavy modules made reload-safe. The per-file
   gate (§5) sidesteps it.

**Done since the 2026-07-16 version of this list:** the S2-10 / S2-11
acceptance gates ran (2026-07-16, `23888ebe9`, `docs/deep_review_plan.md`);
S1-10 parallel day simulation shipped in 7.2 (`PB_PARALLEL_GAMES`,
`release_notes.md`); `data/players_normalized.csv` is back (`9173b6e80`);
the cloud app has been deployed routinely since 7.x.

---

## 8. Traps & gotchas (the landmines — each cost real time)

- **Untracked data pollution survives `git checkout`.** Tests can drop untracked
  files under `data/leagues/cbl/data/` (overrides, rosters, boxscores, season
  history). Clean them with `git clean -fdq data/leagues`, not just
  `git checkout`.
- **`cfg.save_overrides()` writes to the *active* league.** Any test that tunes a
  `PlayBalanceConfig` and saves it leaks `playbalance_overrides.json` into the
  live data dir, which then silently shifts the legacy physics for every
  downstream `make_cfg()`/`load_config()` test. Redirect or snapshot/restore it.
- **`get_data_dir()` auto-seeds a fresh data dir.** Pointing `NEXGEN_DATA_ROOT`
  at an empty tmp does **not** give you a clean slate — on first use it
  full-copies the bundled repo `data/` (including a populated `special_events.json`
  and `careers/`) unless `teams.csv`/`players.csv`/`users.txt` already exist in
  the target. Pre-create those sentinel files to suppress the bulk seed.
- **The data-dir cache is `utils.path_utils._DATA_DIR_CACHE` (a dict), not
  `_DATA_DIR`.** Old fixtures that set `_DATA_DIR = None` are no-ops now; clear
  the cache dict and `delenv NEXGEN_ACTIVE_LEAGUE` so `get_data_dir()` resolves
  to the bare tmp root.
- **`importlib.reload` in a test breaks later monkeypatches.** Several
  league-lifecycle tests reload modules; a later test's
  `monkeypatch.setattr("mod.func", …)` then patches a *different* module object
  than the code under test holds. This is the main reason single-process runs are
  flaky. The per-file gate avoids it.
- **`MockRandom([...])` tests are fragile.** The legacy engine's per-pitch RNG
  consumption drifts, so hardcoded draw-sequences stop producing the intended
  outcome. Those are `xfail`ed for the legacy engine (physics is the shipping
  path).
- **Date-dependent tests.** `playbalance/season_manager.py::TRADE_DEADLINE`
  is `date(date.today().year, 7, 31)`; some trade tests patch `_today`/phase.
  Watch for wall-clock coupling.
- **Legacy vs physics naming is confusing.** `tests/test_physics.py` tests the
  **legacy** `playbalance.physics`/`GameSimulation`, *not* the shipping
  `physics_sim/` engine.
- **`save_players` replaces the whole players file**
  (`services/players_repository.py`). Passing a subset once wiped a
  1,000-player league; change some players with `update_players`.
- **The request's league wins over the "active" league.** The `X-League-Id`
  header binds a per-request ContextVar (`utils/path_utils.set_request_league`);
  code that creates or switches a league inside a request, or reproduces a
  cloud bug locally, must set it (with `NEXGEN_DATA_ROOT`) or its writes land
  in the wrong league.
- **Keep the Firestore stack pinned** (`requirements-server.txt`:
  `firebase-admin==7.5.0`, `google-cloud-firestore==2.28.0`, plus the
  api-core/grpc pins). A newer transport broke every Firestore read, so
  logins failed.
- **Every `{team_id}` write must call `require_team_owner`.**
  `tests/test_team_scoped_write_ownership.py` walks the live router table and
  fails on any unguarded endpoint.

---

## 9. Key-file cheat sheet

| Path | Role |
|---|---|
| `physics_sim/engine.py` | Shipping game engine (`simulate_game`). |
| `physics_sim/config.py` | `DEFAULT_TUNING` — every calibration knob. |
| `scripts/physics_sim_season_kpis.py` | KPI gate vs MLB benchmarks (`--strict`). |
| `scripts/benchmark_sim_days.py` | Parity/perf digests (serial-vs-change). |
| `scripts/run_tests_isolated.py` | The green test gate (per-file isolation). |
| `playbalance/game_runner.py` | Engine dispatch + per-game orchestration. |
| `playbalance/season_simulator.py` | Day-by-day season driver, seeds, batched writes. |
| `playbalance/season_manager.py` | Season phase state machine + rollover. |
| `api/app.py`, `api/routers/*`, `api/security.py` | FastAPI backend + auth. |
| `desktop/src/lib/api.ts` | Typed frontend API client. |
| `services/cpu_trade_proposals.py`, `cpu_trade_evaluator.py`, `trade_execution.py`, `team_outlook.py` | CPU trading (Sprint 2). |
| `services/inseason_callups.py` | Monthly callups + September expansion (Sprint 2). |
| `api/working_copy.py` | Local working copy of the GCS-mounted league data (pull at start, push after writes). |
| `utils/path_utils.py` | Data root / league dir resolution, `set_request_league`. |
| `services/team_ownership.py` | Who owns which club (from `users.txt`). |
| `services/league_rollover.py`, `services/rating_scale_migration.py` | Season rollover; the 8.0.0 scale 2 conversion. |
| `physics_sim/engine_generation.py`, `physics_sim/profiles/` | Engine generations and their tuning profiles. |
| `utils/player_overall.py`, `utils/rating_display.py` | The shared overall; what pages show on scale 1 / scale 2. |
| `services/fa_window.py`, `services/extension_talks.py` | Offseason free-agency bidding window; ask/minimum negotiation rules. |
| `services/draft_board.py`, `api/routers/draft.py` | Owners' draft boards and CPU need-aware picks. |
| `services/discord_notify.py`, `scripts/announce_release.py` | Discord posts (server side; release announcement). |
| `docs/deep_review_plan.md` | Sprint 0–2 truth doc (status + hashes). |
| `docs/specs/` | Feature specs (`S1-10_parallel_day.md`, `S2-*.md`, `S3-*.md`). |
| `data/leagues/cbl/data/` | The committed sample league (don't pollute it). |
| `data/calibration/`, `data/calibration_league/`, `data/calibration_flat/` | Deterministic KPI fixtures. |

---

## 10. Suggested first moves for a new agent

1. Read `AGENTS.md`, then this file, then the 8.x entries at the end of
   `release_notes_draft.md`.
2. Install `requirements-server.txt` into `.venv` (Python 3.11).
3. Run the green gate: `python scripts/run_tests_isolated.py -j 12` (~3.5 min)
   — expect only the five known failures (§5).
4. Run the KPI harness once (strict, seed 1) to see the engine-vs-MLB gate in
   action and learn the tolerance mindset.
5. Pick an item from §7. For anything touching the engine, make the KPI
   harness on seeds 1 and 2 (and, for perf, the parity harness) your gate
   before committing. Record shipped work in `release_notes_draft.md` and the
   item's status in `docs/future_work.md`.
