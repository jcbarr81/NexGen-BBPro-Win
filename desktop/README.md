# NexGen-BBPro Desktop (Electron + React)

> ## ⚠️ Status corrected 2026-07-13 (app at VERSION 7.0.11)
>
> **This README's "Phase 2 scaffold" framing is obsolete.** This Electron + React
> client is now **the shipped UI** — ~64 real page components (~31k LOC) backed by
> a FastAPI sidecar (~60 routers) and a Firebase / Firestore / Cloud Run
> multi-tenant backend. **The legacy PyQt `ui/` app is retired** (the
> `python main.py` checklist item below no longer applies — there is no root
> `main.py` entrypoint anymore). Treat the phase/scaffold language in this file as
> historical; see `release_notes.md` for what actually shipped. The "Known gaps"
> section at the bottom has been updated to reflect verified current state.

Originally a Phase 2 scaffold for the new UI, developed alongside the (now
retired) PyQt6 app against the same `%LOCALAPPDATA%\NexGen-BBPro\data`
directory.

## Stack

- **Electron 32** (main + preload, compiled via `tsc`)
- **Vite 5 + React 18 + TypeScript**
- **Tailwind CSS** (`tailwind.config.ts` holds the Phase 2 starter palette;
  Phase 3 replaces it with tokens ported from `ui/theme_enhanced.py` and
  `ui/design_tokens.py`)
- **@tanstack/react-query** for server cache, **zustand** for UI state
- **react-router-dom** (HashRouter, since Electron prod loads via `file://`)

## Layout

```
desktop/
├── electron/            # Main process (compiled to dist-electron/)
│   ├── main.ts          # Window lifecycle, sidecar spawn, AUMID
│   ├── preload.ts       # Exposes window.nexgen { apiBaseUrl, launchToken, ... }
│   └── sidecar.ts       # Spawns `python -m api`, parses stdout handshake,
│                        #   polls /healthz
├── src/                 # React renderer
│   ├── lib/             # bridge, api client, auth store
│   ├── pages/           # SplashGate, LoginPage, HomePage
│   └── styles/          # Tailwind entry
├── index.html
├── vite.config.ts
└── package.json
```

## First-time setup

```powershell
cd desktop
npm install
```

You must also have the Python sidecar deps installed in the repo root:

```powershell
cd ..
python -m pip install -r requirements-dev.txt
```

## Dev workflow

One command runs Vite, the TypeScript compiler for the Electron main
process, and Electron itself:

```powershell
npm run dev
```

What happens:

1. `tsc -p tsconfig.node.json -w` compiles `electron/*.ts` → `dist-electron/*.js`.
2. `vite` serves the renderer on <http://localhost:5173>.
3. `wait-on` waits for both the Vite port and `dist-electron/main.js`,
    then launches `electron .`.
4. Electron spawns `python -m api --port 0 --print-handshake` (override the
    interpreter via `NEXGEN_PYTHON=...`). It parses the JSON handshake
    (`{ "port", "token" }`) from stdout, polls `/healthz`, and injects the
    URLs + token into the renderer via preload.

## Verification checklist (Phase 2 acceptance)

- [ ] `npm run dev` opens a 1440×900 window titled "NexGen-BBPro".
- [ ] Splash shows briefly, then the login screen renders.
- [ ] Bottom-right ribbon shows `v<version>` from the sidecar's `VERSION`.
- [ ] Signing in with `admin` / `pass` (or your bootstrapped credentials)
       navigates to the home page and the leagues list renders.
- [ ] Closing the window fully terminates the Python process (check Task
       Manager — no orphan `python.exe`).
- [ ] `python main.py` in the repo root still launches the legacy PyQt app
       with no changes.

## Production build

```powershell
# 1. Build the Python sidecar with PyInstaller → dist/sidecar/
#    (Phase 7 adds packaging/sidecar.spec; for now reuse build_exe.py)
# 2. Build + package the Electron app:
cd desktop
npm run package
```

Output lands in `desktop/release/`. The `build` block in `package.json`
already:

- Sets `appId` = `NexGen.BBPro` (matches the AUMID set in `main.py`).
- Bundles the sidecar from `../dist/sidecar` as `resources/sidecar/`.
- Uses `packaging/NexGen-BBPro.ico`.
- Produces an NSIS installer with user-choosable install path.

## Running renderer-only in a browser

If you want to iterate on UI without Electron (e.g., React DevTools):

```powershell
# Terminal 1 — sidecar
python -m api --port 8765
# Terminal 2 — Vite
cd desktop
npm run dev:vite
# Open http://localhost:5173
```

`.env.development` points the browser build at `http://127.0.0.1:8765`.

## Known gaps (reconciled 2026-07-13)

The original phase-based gap list was stale. Verified current state:

- ~~Screen ports (Phase 4): HomePage is a debug stub~~ — **Done.** ~64 real
  pages under `src/pages/`; only `ComingSoonPage.tsx` is a placeholder.
- ~~Live sim streaming (Phase 5): `/ws/sim` just echoes~~ — **Done.** Real
  pitch-by-pitch streaming with speed/pause/resume/skip controls
  (`api/ws/sim.py`, `src/lib/sim-socket.ts`, `LiveGamePage.tsx`).
- **Design system:** confirm whether Tailwind tokens are finalized or still
  partly placeholder — verify against current `tailwind.config.ts`.
- **AI assets (`/assets/*`):** verify whether asset endpoints now exist.
- **Code signing + auto-update:** installers ship via `scripts/build_release.py`
  + `packaging/NexGen-BBPro.iss`; confirm signing/auto-update status.
- **Playwright E2E:** not found — likely still absent.

Residual cleanup: one leftover import from the retired PyQt package survives at
`api/routers/history.py` (`from ui.league_history_window import ...`), and
`NexGen-BBPro.spec` still references the old `main.py` entrypoint.
