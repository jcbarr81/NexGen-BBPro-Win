# NexGen-BBPro Desktop (Electron + React)

Phase 2 scaffold for the new UI. Lives alongside the existing PyQt6 app —
both run against the same `%LOCALAPPDATA%\NexGen-BBPro\data` directory so
you can develop the Electron UI without disturbing the shipping build.

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

## Known gaps (addressed in later phases)

- **Design system (Phase 3):** tailwind tokens are placeholders.
- **Screen ports (Phase 4):** HomePage is a debug stub.
- **Live sim streaming (Phase 5):** `/ws/sim/{game_id}` just echoes.
- **AI assets (Phase 6):** no `/assets/*` endpoints yet.
- **Code signing + auto-update (Phase 7):** electron-builder config is
   skeletal.
- **Playwright E2E (Phase 9).**
