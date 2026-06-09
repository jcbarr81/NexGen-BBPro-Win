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
  // When no API URL is provided (the production build served from Cloud Run),
  // default to the page's own origin so the UI talks to the same host that
  // served it — no CORS, no hard-coded URL. Dev modes still set the env
  // (.env.development -> local sidecar, .env.cloud -> the Cloud Run URL).
  const sameOrigin =
    typeof window !== "undefined" && window.location?.origin
      ? window.location.origin
      : "http://127.0.0.1:8765";
  const envApi = import.meta.env.VITE_API_BASE_URL;
  const api = envApi && envApi.length ? envApi : sameOrigin;
  const envWs = import.meta.env.VITE_WS_BASE_URL;
  const ws = envWs && envWs.length ? envWs : api.replace(/^http/, "ws");
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
