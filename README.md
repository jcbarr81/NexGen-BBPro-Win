# NexGen-BBPro

NexGen-BBPro is a full baseball-league simulation game: create a league, manage
rosters, contracts, and finances, and simulate seasons pitch-by-pitch with a
physics-based engine. It is a **cloud web app** (multi-tenant, several human
owners per league), hosted on Google Cloud Run + Firebase at
https://nexgen-bbpro.firebaseapp.com. The Electron desktop app and the Windows
installer are retired.

New to the codebase? Start with `docs/CODEX_HANDOFF.md` (architecture, running,
testing, deploying, and the traps) and `AGENTS.md` (repo conventions).

## Architecture (8.x)

| Layer | Where | What |
|---|---|---|
| UI | `desktop/` | React 18 + TypeScript + Tailwind, ~60 pages. Built with Vite (`npm run build:renderer`) and served by Firebase Hosting, which rewrites every non-file path to Cloud Run. (The Electron shell in `desktop/` is retired.) |
| API | `api/` | FastAPI backend — ~55 routers over the game services, WebSocket live-game streaming (`api/ws/sim.py`). |
| Services | `services/` | Finance, contracts, free agency, trades, scouting, drafts, qualifying offers, prospect rules, analytics… |
| Sim engine | `physics_sim/` | Physics-first game engine (pitch flight, contact, fielding). This is what runs games. Each league season is played on an engine generation (`physics_sim/engine_generation.py`). |
| Legacy engine | `playbalance/` | Original PB.INI-driven engine — archived; only runs with `PB_ALLOW_LEGACY_ENGINE=1`. Season orchestration helpers here are still live. |
| Auth | Firebase (cloud) / HMAC session token (local) | Multi-tenant via `X-League-Id` + Firestore memberships. |

The old PyQt6 interface (`ui/`) is retired; its code remains only for reference.

> **Doc freshness:** `release_notes_draft.md` (one entry per version, 7.1 to the
> current `VERSION`) and the git log are the source of truth for what has
> shipped; `release_notes.md` stops at 7.2. Planning docs under `docs/` carry
> dated reconciliation banners where they lag reality.

## Getting started (development)

Prereqs: Python 3.11+ and Node 20+. Use the `.venv` virtualenv (Python 3.11);
`.venv2` is broken (see `AGENTS.md`).

```powershell
# Python deps (repo root) — the Cloud Run runtime set
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-server.txt

# Terminal 1 — API
.\.venv\Scripts\python.exe -m api --port 8765
# Terminal 2 — browser UI
cd desktop
npm install
npm run dev:vite     # then open http://localhost:5173

# Client type check
npm run typecheck
```

`npm run dev:cloud` points the browser build at the hosted Cloud Run backend
instead (see `desktop/.env.cloud`). Local runs use `users.txt` logins and the
repo's `data/` (or `NEXGEN_DATA_ROOT`); never point one at a live league's
data.

## Cloud deployment

The Docker image builds the UI and serves it with the API; Firebase Hosting
serves the same build for the public site. Deploys reach live leagues with
human owners, so confirm before deploying. The full release checklist
(version bump, validation, deploy, verify, announce) is `RELEASE.md`.

```powershell
gcloud run deploy nexgen-bbpro-api --source . --project nexgen-bbpro --region us-central1
# Static hosting (rewrites fall through to Cloud Run):
cd desktop; npm run build:renderer; cd ..
npx firebase-tools deploy --only hosting --project nexgen-bbpro
# Last step: announce the release on Discord
.\.venv\Scripts\python.exe scripts\announce_release.py --message "<bullets>"
```

Upload filtering lives in `.gcloudignore` (mirrors `.dockerignore`). Secrets
(`SENDGRID_API_KEY`, `NEXGEN_SCHEDULER_TOKEN`, `NEXGEN_DISCORD_WEBHOOK_URL`,
`NEXGEN_DISCORD_DRAFT_WEBHOOK_URL`) are Secret Manager references on the
Cloud Run service; env vars and secrets carry over to each new revision.

## Simulation engine

Games run on `physics_sim/`. Realism is guarded by a strict KPI harness wired
into CI (`.github/workflows/physics_sim_kpi.yml`):

```powershell
.\.venv\Scripts\python.exe scripts\physics_sim_season_kpis.py --strict
```

Engine selection: `PB_GAME_ENGINE=physics` is the default everywhere. The
legacy engine only runs if you set `PB_ALLOW_LEGACY_ENGINE=1` *and* request
`engine="legacy"` explicitly. Engine generations 6 (8.0.0, with ratings on the
full 1-99 scale) and 7 (ball flight, 8.1.0) are gated by operations switches;
see `docs/rating_scale_switch_runbook.md` and
`docs/generation7_switch_runbook.md`.

## Testing & release validation

```powershell
# Full test suite (per-file isolation, 12 at a time; ~3.5 minutes)
$env:PYTHONHASHSEED = "0"
.\.venv\Scripts\python.exe scripts\run_tests_isolated.py -j 12

# Targeted tests
.\.venv\Scripts\python.exe -m pytest tests\test_rating_scale_display.py

# Finance release gate (finance tests + multi-league smoke + stability sim)
.\.venv\Scripts\python.exe scripts\validate_finance_release.py --seasons 8

# Multi-league isolation smoke matrix
.\.venv\Scripts\python.exe scripts\smoke_multi_league.py
```

A single `pytest` run over the whole suite shows cross-file pollution
failures that are not real bugs; `AGENTS.md` lists the known failures of the
isolated run. Capture user-facing changes as you go with
`scripts\add_release_note.py "…"` (it appends to `release_notes_draft.md`).
`scripts\build_release.py` (the Windows EXE + installer) is retired.

## Key features

- **League management** — create/clone leagues from presets, multi-league per
  owner, commissioner and owner roles, invites/join requests, email invites.
- **Physics game simulation** — pitch-by-pitch with live streaming to the
  Live Game page (speed/pause/skip controls).
- **Finance system** — modular (10 toggleable modules with presets Off /
  Simple / Standard / MLB-Like): budgets, payroll rules with luxury-tax
  hybrid enforcement, arbitration, qualifying offers + compensation picks,
  signing bonuses, an owner payroll-headroom dashboard, and signing-impact
  previews in free agency.
- **Rosters & transactions** — trades (with CPU trade AI that responds,
  counters, and proposes), free agency with asking prices and a bidding
  window, contract extension talks, the amateur draft with owners' private
  draft boards and CPU need-aware drafting, injuries/IL, prospect protection
  & option rules.
- **Season flow** — phase-aware progression (preseason → regular season →
  amateur draft → playoffs → offseason), MLB-style playoffs, player
  development and retirements at the rollover, awards, Hall of Fame,
  records, almanac export (Baseball-Reference-style HTML).
- **Owner dashboard** — a Spotlight of what needs your club this phase,
  notifications with stop-sim rules, and Discord posts for sims and the
  draft.
- **Analytics** — league leaders (regular season and postseason), career
  arcs, player similarity, team eras, exportable report bundles.
- **AI-generated art** — team logos and player avatars via Google Vertex AI
  in the cloud (no key needed); OpenAI images optionally for local runs.

## OpenAI setup (optional — local logos/avatars)

Set `OPENAI_API_KEY` in the environment, or create a git-ignored `config.ini`:

```ini
[OpenAIkey]
key=<your API key>
```

## Data layout

League data lives under `data/` locally (or `NEXGEN_DATA_ROOT`); in the cloud
it is files in the GCS bucket `nexgen-bbpro-data`, worked on through a local
copy. Useful landmarks:

- `data/leagues/<league-id>/data/` — per-league saves (players, rosters,
  contracts, finances, schedules, playoffs)
- `data/lineups/<TEAM>_vs_lhp.csv` / `_vs_rhp.csv` — lineup files
  (`order,player_id,position`)
- `data/playoffs_config.json` — optional playoff seeding/series overrides
- `data/users.txt` — per-league accounts for local runs (the cloud uses
  Firebase accounts and Firestore memberships)

## Repository map

```
api/            FastAPI routers + WebSocket sim streaming
desktop/        React client (its Electron shell is retired; see desktop/README.md)
physics_sim/    Physics game engine + tuning config
playbalance/    Season orchestration + archived legacy engine
services/       Domain logic (finance, trades, drafts, analytics, …)
models/         Core dataclasses (players, teams, rosters)
scripts/        Dev/release/validation tooling
tests/          Pytest suite
docs/           Design docs & manuals (check banners for freshness)
packaging/      Retired Windows installer (Inno Setup) assets
```
