/**
 * Preload script.
 *
 * Runs in an isolated world with `contextIsolation: true`. We expose a
 * narrow, read-only surface on `window.nexgen` describing how the renderer
 * should reach the Python sidecar. Values are injected by main via
 * `additionalArguments` at BrowserWindow creation time so no sync IPC is
 * required during the first paint.
 */

import { contextBridge } from "electron";

interface NexgenBridge {
  apiBaseUrl: string;
  wsBaseUrl: string;
  launchToken: string;
  isPackaged: boolean;
}

function parseArg(prefix: string, fallback = ""): string {
  const match = process.argv.find((a) => a.startsWith(prefix));
  return match ? match.slice(prefix.length) : fallback;
}

const bridge: NexgenBridge = {
  apiBaseUrl: parseArg("--nexgen-api-url="),
  wsBaseUrl: parseArg("--nexgen-ws-url="),
  launchToken: parseArg("--nexgen-token="),
  isPackaged: parseArg("--nexgen-packaged=") === "1",
};

contextBridge.exposeInMainWorld("nexgen", bridge);
