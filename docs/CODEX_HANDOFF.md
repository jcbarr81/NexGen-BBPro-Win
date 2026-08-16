# NexGen-BBPro — Developer Handoff (for OpenAI Codex or any new contributor)

> **Read this first, then keep it open.** It is the single onboarding map for
> picking up development. It points you at the authoritative files, explains how
> the pieces fit, tells you exactly how to run and test the project, and lists
> the traps that will otherwise cost you hours. It was written 2026-07-16 against
> `main` @ VERSION **7.0.11**.

---

## 0. The five files that are "source of truth"

Docs in this repo drift; several planning docs carry dated reconciliation
banners. When something here disagrees with reality, believe the code + these:

| File | What it authoritatively covers |
|---|---|
| `README.md` | Product summary + current (7.x) architecture + getting-started commands. **Current — trust it.** |
| `AGENTS.md` | Repo conventions (Codex reads this first): venv, versioning/SemVer, release-note + build workflow. |
| `release_notes.md` | The source of truth for **what has actually shipped**. Git log is the other. |
| `docs/deep_review_plan.md` | The "truth document" for the 2026-07 improvement program (Sprints 0–2). Every task has a status row + a dated change-log entry with commit hashes. |
| `docs/future_work.md` | The backlog (with a reconciliation banner; older items use stale "v5.x" milestone language). |

Everything below consolidates the operational knowledge that is otherwise spread
across those and learned the hard way.

---

## 1. What the product is

A full baseball-league simulation game: create a league, manage rosters,
contracts, finances, scouting, drafts, and trades, and simulate seasons
**pitch-by-pitch** with a physics-based engine. It runs two ways from one
codebase:

- **Electron desktop app** (local, single-user) — the FastAPI backend runs as a
  bundled "sidecar" and the React UI talks to it over localhost.
- **Cloud** (multi-tenant) — the same FastAPI backend on **Google Cloud Run**,
  the React UI served statically, **Firebase Auth + Firestore** for accounts,
  memberships, and the per-request active league (`X-League-Id` header).

The old **PyQt6 desktop UI (`ui/`) is retired** — its code remains only for
reference (and a couple of retired modules are the reason some endpoints once
imported dead code; see §8).

---

## 2. Architecture map

| Layer | Where | What |
|---|---|---|
| UI | `desktop/` | React 18 + TypeScript + Tailwind (~60 pages). `desktop/src/lib/api.ts` is the typed API client; `apiRequest()` attaches the bearer token + `X-League-Id`. Shipped via Electron locally or served by Cloud Run. |
| API | `api/` | FastAPI backend. `api/app.py` builds the app; routers live in `api/routers/*.py` (~60). Auth dependency in `api/security.py` (`require_bearer` → `CurrentIdentity`). WebSocket live-game streaming in `api/ws/`. |
| Services | `services/` | Business logic: finance, contracts, trades (`cpu_trade_proposals.py`, `cpu_trade_evaluator.py`, `trade_execution.py`), team outlook, callups (`inseason_callups.py`), scouting, drafts, prospect rules, analytics, league lifecycle/registry/rollover, standings, etc. |
| **Sim engine (shipping)** | `physics_sim/` | The physics-first game engine: pitch flight, contact, fielding, usage/fatigue. `physics_sim/engine.py` (`simulate_game`), `config.py` (`DEFAULT_TUNING` knobs), `physics.py`, `usage.py`, `models.py`. This is what runs games. |
| Legacy engine (gated) | `playbalance/` | The original PBINI-driven engine + season orchestration. The **game** part is archived — it only runs under `PB_ALLOW_LEGACY_ENGINE=1` (`playbalance/legacy_guard.py`). But **season orchestration helpers here are still live** (e.g. `playbalance/season_manager.py`, `season_simulator.py`, `game_runner.py` which dispatches to the physics engine). |
| Data | `data/` | CSV/JSON game data. The committed sample league lives under `data/leagues/cbl/data/`. `data/MLB_avg/` holds the real-MLB benchmark tables the KPI harness compares against. |
| Auth | Firebase (cloud) / HMAC session token (local) | `NEXGEN_FIREBASE=1` turns on the cloud control plane; local uses `users.txt` + a signed session token. |

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
    runs are reproducible and never touch a real league.
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

**Prereqs:** Python 3.11+, Node 20+.

**Python virtualenvs:** both `.venv` and `.venv2` exist in the repo. `AGENTS.md`
says use **`.venv2`**; `.venv` also works for tests. Pick one and be consistent.
(If you see import errors for `fastapi`/`numpy`, install the runtime deps — see
below.)

**Dependencies:**
- `requirements-server.txt` — **the Cloud Run runtime set** (fastapi, uvicorn,
  pydantic, portalocker, httpx, websockets, numpy, bcrypt, Pillow,
  opencv-python-headless, firebase-admin). Install this to run the backend + the
  API tests locally; it mirrors production exactly.
- `requirements-dev.txt` — the above API stack **plus** the heavy local-only
  ML/image stack (torch, diffusers, transformers, opencv) used for logo/avatar
  generation and PyInstaller packaging.

```powershell
# backend deps that match production
.\.venv2\Scripts\python.exe -m pip install -r requirements-server.txt

# run the API (see README for the exact uvicorn command / Electron dev flow)
# frontend:
cd desktop; npm install; npm run dev
```

**Build a desktop release** (per `AGENTS.md`):
`.\.venv2\Scripts\python.exe scripts\build_release.py --clean`

**Deploy (cloud):** the backend deploys to Cloud Run from
`requirements-server.txt`; the React app is built and served statically; Firebase
provides auth/Firestore. (No one-command deploy is committed — confirm the exact
`gcloud`/Firebase steps with the owner before deploying. Deploys are
outward-facing and should be gated on the acceptance items in §7.)

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
python scripts/run_tests_isolated.py            # full gate (~7 min): 201/201 files green
python scripts/run_tests_isolated.py -k trade    # only files whose name matches
python scripts/run_tests_isolated.py --list      # list files, don't run
```

`scripts/run_tests_isolated.py` runs **each `tests/test_*.py` file in its own
pytest subprocess** (fresh interpreter → zero cross-file leakage), restores
`data/` between files, and exits non-zero on any failure. **This is the
authoritative "is the suite green" check.** As of this handoff it is
**201/201 green**.

`tests/conftest.py` also does a cheap per-test env restore (`NEXGEN_*`,
`PB_SIM_*`) and a session-end `data/` cleanup so a plain `pytest` run never
leaves the working tree dirty.

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
   archived legacy CLIs (need `PB_ALLOW_LEGACY_ENGINE=1`), Windows-only
   `os.replace`-on-open-file semantics, and the `players_normalized.csv` gap
   (§7). Don't "fix" these by deleting the reason.

Two files are excluded from the default gate on purpose: `test_auto_tune_solver`
(archived legacy engine) and `test_build_exe` (PyInstaller packaging).

---

## 6. Conventions & workflow (from `AGENTS.md`)

- **Versioning (SemVer) via the `VERSION` file.** PATCH for fixes/tests/small
  UX; MINOR for complete user-facing features; MAJOR only with explicit
  confirmation. **Docs-only changes need no bump.** When you bump `VERSION`,
  match it in the `.iss` installer file.
- **Release notes:** add entries to the release-notes-draft as you bump versions;
  `release_notes.md` is the shipped record (`scripts/add_release_note.py`).
- **Backlog:** add new ideas to `docs/future_work.md`.
- **New features:** create a tutorial/guide and wire it into the menu.
- Use `rg` (ripgrep) for searching; PEP8 style.
- **The truth-doc discipline (from the 2026-07 program):** for a planned task,
  a change is only "Done" when its verification gate passed **and** it's
  committed — record the commit hash in `docs/deep_review_plan.md` (status row +
  a dated change-log entry). Keep that discipline for any resumed Sprint work.

---

## 7. Current state — where development was left off (2026-07-16)

**Shipped/committed this program (all on `main`, pushed):**
- **Sprint 2 simulation-realism + CPU-AI features are complete:** platoon
  lineups (S2-01), modern batting order (S2-02), pitch-count reliever rest
  (S2-03), tied-game closer usage (S2-04), position-player rest days (S2-05),
  pitcher handedness/platoon (S2-06), times-through-order batter bonus (S2-07),
  player-dispersion KPI gate + calibration repair (S2-08), deadline-aware CPU
  trading (S2-09), CPU-to-CPU trades (S2-10), in-season callups + September
  expansion (S2-11), pitching-usage KPIs (S2-12), pinch-hitter defensive
  awareness (S2-13). Each is a row in `docs/deep_review_plan.md` with its hash.
- **Two pre-existing API bugs fixed:** `/league/history` (imported a deleted
  PyQt module → ported the loader to `services/league_history.py`) and
  `/leagues` (was served without auth → added `require_bearer`).
- **Full test-hygiene pass + the green gate** (§5): ~50 stale/broken tests fixed
  or removed, cross-file pollution root-caused, `scripts/run_tests_isolated.py`
  added. Suite is 201/201 green via the gate.

**NOT done — explicit pick-up-here list, roughly prioritized:**

1. **Run the two deferred acceptance gates before any production deploy.** They
   were framed as manual gates and hadn't been run (fastapi wasn't installed
   locally at the time — it is installable now via `requirements-server.txt`):
   - **S2-10**: 3-season CPU-CPU trade-stability sim (15–40 executed CPU-CPU
     trades/season, team-win% stddev not growing). See the "Test plan" in
     `docs/specs/S2-10_cpu_to_cpu_trades.md`.
   - **S2-11**: season-scale roster-churn audit (promotions/demotions look sane;
     `validate_roster_state` passes for all teams post-September-revert). See
     `docs/specs/S2-11_inseason_callups.md`.
2. **S1-10 — parallel day simulation (NOT started, design ready).** A
   multiprocessing rewrite of the per-day game loop with a side-effect journal.
   Implementation-ready spec: `docs/specs/S1-10_parallel_day.md`. Its release
   gate is **byte-parity** of the three `benchmark_sim_days.py` digests between
   serial and parallel, and it **changes serial seed behavior** (forces a
   benchmark re-baseline). High blast radius (touches the core sim write path) —
   do it in a focused session and lean on the parity harness.
3. **Restore `data/players_normalized.csv` (the KPI-calibration blocker).** It
   was deleted in v3.1.17 and never restored. Its absence makes
   `playbalance/player_generator.py` generate degenerate (all-elite) contact
   ratings — that's why `test_player_generator.py::
   test_hitter_contact_speed_distribution_centered` is `xfail`. The normalizer
   templates (`scripts/normalize_players.py`) have drifted; regenerating naively
   produces bad calibration. Fixing this properly (regenerate/replace the
   normalized roster so the generator + CI have a real distribution source) is
   its own task and is referenced throughout `docs/deep_review_plan.md`.
4. **(Optional) True single-process test isolation.** Making a *single* `pytest`
   run green would require redirecting every test's data dir to a per-test tmp
   and making the reload-heavy modules reload-safe — a real refactor. The
   per-file gate (§5) sidesteps it reliably; only do this if you want plain
   `pytest` to be green.
5. **Nothing is deployed.** All the above is committed + pushed to GitHub only.

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
| `docs/deep_review_plan.md` | Sprint 0–2 truth doc (status + hashes). |
| `docs/specs/S1-10_parallel_day.md`, `S2-*.md` | Implementation-ready specs. |
| `data/leagues/cbl/data/` | The committed sample league (don't pollute it). |
| `data/calibration/` | Deterministic calibration roster for KPI runs. |

---

## 10. Suggested first moves for a new agent

1. Read `README.md`, `AGENTS.md`, then this file.
2. Install `requirements-server.txt` into the venv.
3. Run the green gate: `python scripts/run_tests_isolated.py` — confirm 201/201.
4. Run the KPI harness once (strict, seed 1) to see the engine-vs-MLB gate in
   action and learn the tolerance mindset.
5. Pick a pick-up item from §7. For anything touching the engine, make the KPI
   harness (and, for perf, the parity harness) your gate before committing, and
   record the outcome + hash in `docs/deep_review_plan.md`.
