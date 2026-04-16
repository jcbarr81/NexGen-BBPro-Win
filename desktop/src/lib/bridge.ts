/**
 * Resolve the sidecar endpoint and launch token.
 *
 * In Electron these come from the preload bridge (`window.nexgen`). When the
 * Vite dev server is opened directly in a browser tab (e.g. for component
 * hacking), we fall back to the env vars set in `.env.development` so the
 * renderer still works without the Electron shell.
 */

interface ResolvedBridge {
  apiBaseUrl: string;
  wsBaseUrl: string;
  launchToken: string;
  isPackaged: boolean;
  source: "electron" | "env";
}

function fromEnv(): ResolvedBridge {
  const api = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8765";
  const ws = import.meta.env.VITE_WS_BASE_URL ?? api.replace(/^http/, "ws");
  return {
    apiBaseUrl: api,
    wsBaseUrl: ws,
    launchToken: import.meta.env.VITE_LAUNCH_TOKEN ?? "",
    isPackaged: false,
    source: "env",
  };
}

export function getBridge(): ResolvedBridge {
  if (typeof window !== "undefined" && window.nexgen?.apiBaseUrl) {
    return { ...window.nexgen, source: "electron" };
  }
  return fromEnv();
}
