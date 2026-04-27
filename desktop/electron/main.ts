/**
 * Electron main process.
 *
 * Startup sequence:
 *   1. Set AUMID so Windows groups the app under the same taskbar entry as
 *      the legacy PyQt build (`NexGen.BBPro`, matching main.py).
 *   2. Spawn the Python sidecar; wait for the JSON handshake on stdout.
 *   3. Poll /healthz until it answers.
 *   4. Create the BrowserWindow and inject the sidecar URL + launch token
 *      into the renderer via preload `additionalArguments`.
 *   5. On `window-all-closed`, kill the sidecar so we never leak processes.
 */

import { BrowserWindow, app, shell } from "electron";
import path from "node:path";

import { SidecarHandle, spawnSidecar, waitForHealth } from "./sidecar";

// tsconfig.node.json emits CommonJS, so __dirname is always defined here.
const __here = __dirname;

const AUMID = "NexGen.BBPro";
const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL;

let sidecar: SidecarHandle | null = null;
let mainWindow: BrowserWindow | null = null;

function resolveAppIcon(): string {
  // Packaged: electron-builder copies extraResources into ``resourcesPath``
  // (next to the .exe). Dev: walk up to the repo root's ``packaging/``.
  const candidates = app.isPackaged
    ? [
        path.join(process.resourcesPath, "NexGen-BBPro.ico"),
        path.join(process.resourcesPath, "icon.ico"),
      ]
    : [path.join(__here, "..", "..", "packaging", "NexGen-BBPro.ico")];
  for (const candidate of candidates) {
    try {
      // require fs lazily so we don't pay the import cost in dev hot reloads
      // when the icon isn't actually queried.
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const fs = require("node:fs") as typeof import("node:fs");
      if (fs.existsSync(candidate)) return candidate;
    } catch {
      /* ignore */
    }
  }
  return candidates[0];
}

async function createMainWindow(handle: SidecarHandle): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1120,
    minHeight: 720,
    backgroundColor: "#0B0F14",
    show: false,
    autoHideMenuBar: true,
    title: "NexGen-BBPro",
    icon: resolveAppIcon(),
    webPreferences: {
      preload: path.join(__here, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
      additionalArguments: [
        `--nexgen-api-url=${handle.baseUrl}`,
        `--nexgen-ws-url=${handle.wsUrl}`,
        `--nexgen-token=${handle.token}`,
        `--nexgen-packaged=${app.isPackaged ? "1" : "0"}`,
      ],
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // External links open in the default browser, never in a new Electron window.
    shell.openExternal(url).catch(() => undefined);
    return { action: "deny" };
  });

  mainWindow.once("ready-to-show", () => {
    // Maximize on first show so the app fills the screen regardless of
    // the monitor size. The 1440x900 width/height above are the
    // un-maximized fallback dimensions if the user restores the window.
    mainWindow?.maximize();
    mainWindow?.show();
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  if (DEV_SERVER_URL) {
    await loadDevUrlWithRetry(mainWindow, DEV_SERVER_URL);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    await mainWindow.loadFile(path.join(__here, "..", "dist", "index.html"));
  }

  // Allow end users to open DevTools in packaged builds (Ctrl+Shift+I
  // or F12) so we can diagnose renderer-only bugs without shipping a
  // debug flag. before-input-event fires before the keystroke reaches
  // any focused input, so this is opt-in by key combo.
  mainWindow.webContents.on("before-input-event", (_event, input) => {
    if (input.type !== "keyDown") return;
    const key = (input.key || "").toLowerCase();
    if (key === "f12" || (input.control && input.shift && key === "i")) {
      mainWindow?.webContents.toggleDevTools();
    }
  });
}

/**
 * Vite re-optimizes deps the first time it sees a new import, which aborts
 * any in-flight navigation. Retry once after a short pause so the second
 * load lands on the freshly-restarted dev server.
 */
async function loadDevUrlWithRetry(
  win: BrowserWindow,
  url: string,
  attempts = 3,
): Promise<void> {
  for (let i = 0; i < attempts; i++) {
    try {
      await win.loadURL(url);
      return;
    } catch (err: unknown) {
      const code = (err as { code?: string } | null)?.code;
      if (code !== "ERR_ABORTED" || i === attempts - 1) throw err;
      console.warn(
        `[main] dev server aborted load (${code}); retrying in 500ms (${i + 1}/${attempts - 1})`,
      );
      await new Promise((r) => setTimeout(r, 500));
    }
  }
}

async function bootstrap(): Promise<void> {
  try {
    sidecar = await spawnSidecar();
    await waitForHealth(sidecar.baseUrl);
    await createMainWindow(sidecar);
  } catch (err) {
    console.error("[main] Failed to start sidecar:", err);
    app.quit();
  }
}

// Ensure only one instance runs -- otherwise two sidecars fight over the
// same data directory even with portalocker in place.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

if (process.platform === "win32") {
  app.setAppUserModelId(AUMID);
}

app.whenReady().then(bootstrap);

app.on("window-all-closed", () => {
  if (sidecar) {
    sidecar.kill();
    sidecar = null;
  }
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (sidecar) {
    sidecar.kill();
    sidecar = null;
  }
});
