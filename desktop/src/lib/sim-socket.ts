/**
 * Thin wrapper around the live-sim WebSocket.
 *
 * Connects to `ws://127.0.0.1:<port>/ws/sim/<gameId>` with the session token
 * attached as a query parameter (headers aren't writable on the browser
 * WebSocket API). The returned handle lets the caller subscribe to parsed
 * events and send playback control messages.
 */

import { getBridge } from "./bridge";
import { useAuthStore } from "./auth-store";
import type { SimEvent } from "./api";

export interface SimConnection {
  send: (payload: Record<string, unknown>) => void;
  pause: () => void;
  resume: () => void;
  skip: () => void;
  setSpeed: (ms: number) => void;
  close: () => void;
}

export interface SimHandlers {
  onOpen?: () => void;
  onEvent: (event: SimEvent) => void;
  onError?: (ev: Event) => void;
  onClose?: (ev: CloseEvent) => void;
}

export interface SimOpenOptions {
  away: string;
  home: string;
  seed?: number;
  speedMs?: number;
  gameId?: string;
}

export function openSimSocket(
  options: SimOpenOptions,
  handlers: SimHandlers,
): SimConnection {
  const { wsBaseUrl } = getBridge();
  const token =
    useAuthStore.getState().token ?? getBridge().launchToken ?? "";

  const qs = new URLSearchParams({
    token,
    away: options.away,
    home: options.home,
  });
  if (options.seed !== undefined) qs.set("seed", String(options.seed));
  if (options.speedMs !== undefined) qs.set("speed", String(options.speedMs));

  const gameId = options.gameId ?? `g-${Date.now()}`;
  const ws = new WebSocket(`${wsBaseUrl}/ws/sim/${gameId}?${qs.toString()}`);

  ws.addEventListener("open", () => handlers.onOpen?.());
  ws.addEventListener("message", (ev) => {
    try {
      const parsed = JSON.parse(ev.data) as SimEvent;
      handlers.onEvent(parsed);
    } catch {
      /* ignore malformed frames */
    }
  });
  ws.addEventListener("error", (ev) => handlers.onError?.(ev));
  ws.addEventListener("close", (ev) => handlers.onClose?.(ev));

  function send(payload: Record<string, unknown>) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }

  return {
    send,
    pause: () => send({ type: "pause" }),
    resume: () => send({ type: "resume" }),
    skip: () => send({ type: "skip" }),
    setSpeed: (ms) => send({ type: "speed", ms }),
    close: () => ws.close(),
  };
}
