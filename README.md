# NexGen-BBPro

NexGen-BBPro is a full baseball-league simulation game: create a league, manage
rosters, contracts, and finances, and simulate seasons pitch-by-pitch with a
physics-based engine. It runs as an **Electron desktop app** or fully **in the
cloud** (multi-tenant, hosted on Google Cloud Run + Firebase).

## Architecture (7.x)

| Layer | Where | What |
|---|---|---|
| UI | `desktop/` | React 18 + TypeScript + Tailwind, ~60 pages. Shipped via Electron (local) or served by Cloud Run (cloud). |
| API | `api/` | FastAPI "sidecar" — ~60 routers over the game services, WebSocket live-game streaming (`api/ws/sim.py`). |
| Services | `services/` | Finance, contracts, trades, scouting, drafts, qualifying offers, prospect rules, analytics… |
| Sim engine | `physics_sim/` | Physics-first game engine (pitch flight, contact, fielding). This is what runs games. |
| Legacy engine | `playbalance/` | Original PB.INI-driven engine — archived; only runs with `PB_ALLOW_LEGACY_ENGINE=1`. Season orchestration helpers here are still live. |
| Auth | Firebase (cloud) / HMAC session token (local) | Multi-tenant via `X-League-Id` + Firestore memberships. |

The old PyQt6 interface (`ui/`) is retired; its code remains only for reference.

> **Doc freshness:** `release_notes.md` and the git log are the source of truth
> for what has shipped. Planning docs under `docs/` carry dated reconciliation
> banners where they lag reality.

## Getting started (development)

Prereqs: Python 3.11+ and Node 20+.

```powershell
# Python deps (repo root)
python -m venv .venv2
.\.venv2\Scripts\python.exe -m pip install -r requirements-dev.txt

# Desktop app (Electron + Vite + sidecar, one command)
cd desktop
npm install
npm run dev
```

`npm run dev` compiles the Electron main process, serves the renderer on
Vite, spawns the Python sidecar (`python -m api`), and opens the app.

### Browser-only mode (no Electron)

```powershell
# Terminal 1 — API
.\.venv2\Scripts\python.exe -m api --port 8765
# Terminal 2 — renderer
cd desktop
npm run dev:vite     # then open http://localhost:5173
```

`npm run dev:cloud` points the browser build at the hosted Cloud Run backend
instead (see `desktop/.env.cloud`).

## Cloud deployment

One Docker image serves both the API and the built UI:

```powershell
gcloud run deploy nexgen-bbpro-api --source . --project nexgen-bbpro --region us-central1
# Static hosting for the custom domain (rewrites fall through to Cloud Run):
cd desktop; npm run build:renderer; cd ..
npx firebase-tools deploy --only hosting --project nexgen-bbpro
```

Upload filtering lives in `.gcloudignore` (mirrors `.dockerignore`).

## Simulation engine

Games run on `physics_sim/`. Realism is guarded by a strict KPI harness wired
into CI (`.github/workflows/physics_sim_kpi.yml`):

```powershell
.\.venv2\Scripts\python.exe scripts\physics_sim_season_kpis.py --strict
```

Engine selection: `PB_GAME_ENGINE=physics` is the default everywhere. The
legacy engine only runs if you set `PB_ALLOW_LEGACY_ENGINE=1` *and* request
`engine="legacy"` explicitly.

## Testing & release validation

```powershell
# Full test suite
.\.venv2\Scripts\python.exe -m pytest

# Finance release gate (finance tests + multi-league smoke + stability sim)
.\.venv2\Scripts\python.exe scripts\validate_finance_release.py --seasons 8

# Multi-league isolation smoke matrix
.\.venv2\Scripts\python.exe scripts\smoke_multi_league.py

# Windows installer build (runs pre-build validation)
.\.venv2\Scripts\python.exe scripts\build_release.py --clean
```

The full release checklist lives in `RELEASE.md`; capture user-facing changes
as you go with `scripts\add_release_note.py "…"`.

## Key features

- **League management** — create/clone leagues from presets, multi-league per
  owner, commissioner and owner roles, invites/join requests (cloud).
- **Physics game simulation** — pitch-by-pitch with live streaming to the
  Live Game page (speed/pause/skip controls).
- **Finance system** — modular (10 toggleable modules with presets Off /
  Simple / Standard / MLB-Like): budgets, payroll rules with luxury-tax
  hybrid enforcement, arbitration, qualifying offers + compensation picks,
  signing bonuses, an owner payroll-headroom dashboard, and signing-impact
  previews in free agency.
- **Rosters & transactions** — trades (with CPU trade AI that responds,
  counters, and proposes), draft (amateur draft day with console), free
  agency, injuries/DL, prospect protection & option rules.
- **Season flow** — phase-aware progression (preseason → regular season →
  amateur draft → playoffs → offseason), MLB-style playoffs, awards,
  Hall of Fame, records, almanac export (Baseball-Reference-style HTML).
- **Analytics** — league leaders, career arcs, player similarity, team eras,
  exportable report bundles.
- **AI-generated art** — team logos and player avatars via OpenAI images.

## OpenAI setup (optional — logos/avatars)

Set `OPENAI_API_KEY` in the environment, or create a git-ignored `config.ini`:

```ini
[OpenAIkey]
key=<your API key>
```

## Data layout

League data lives under `data/` (or `%LOCALAPPDATA%\NexGen-BBPro\data` for
installed builds; GCS-backed working copy in the cloud). Useful landmarks:

- `data/leagues/<league-id>/data/` — per-league saves (players, rosters,
  contracts, finances, schedules, playoffs)
- `data/lineups/<TEAM>_vs_lhp.csv` / `_vs_rhp.csv` — lineup files
  (`order,player_id,position`)
- `data/playoffs_config.json` — optional playoff seeding/series overrides
- `data/users.txt` — per-league accounts; the admin credential is seeded from
  the installer/bootstrap password on league creation or overwrite

## Repository map

```
api/            FastAPI routers + WebSocket sim streaming
desktop/        Electron + React client (see desktop/README.md)
physics_sim/    Physics game engine + tuning config
playbalance/    Season orchestration + archived legacy engine
services/       Domain logic (finance, trades, drafts, analytics, …)
models/         Core dataclasses (players, teams, rosters)
scripts/        Dev/release/validation tooling
tests/          Pytest suite
docs/           Design docs & manuals (check banners for freshness)
packaging/      Windows installer (Inno Setup) assets
```
