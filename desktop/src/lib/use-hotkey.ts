/**
 * Bare-minimum keyboard-shortcut hook. Binds a handler to a key combo at
 * the window level. Ignores key events while a text input, textarea, or
 * contentEditable element has focus — so Ctrl+S in the username field
 * doesn't save a roster.
 *
 * Usage:
 *   useHotkey("mod+s", () => save(), { enabled: dirty && !saving });
 *
 * Key syntax:
 *   "mod+s" — Ctrl on Windows/Linux, Cmd on macOS
 *   "alt+/" — Alt+slash
 *   "escape"
 *   "mod+shift+k"
 *
 * The handler gets the event so callers can call preventDefault().
 */

import { useEffect, useRef } from "react";

type Handler = (event: KeyboardEvent) => void;

interface Options {
  enabled?: boolean;
  /** Fire even while text inputs are focused. Default false. */
  allowInInputs?: boolean;
  /** Prevent default browser/Electron behaviour. Default true. */
  preventDefault?: boolean;
}

const MAC = typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

function matches(event: KeyboardEvent, combo: string): boolean {
  const parts = combo.toLowerCase().split("+").map((p) => p.trim());
  const key = parts[parts.length - 1];
  const mods = new Set(parts.slice(0, -1));

  const needsMod = mods.has("mod");
  const needsCtrl = mods.has("ctrl") || (needsMod && !MAC);
  const needsMeta = mods.has("cmd") || mods.has("meta") || (needsMod && MAC);
  const needsShift = mods.has("shift");
  const needsAlt = mods.has("alt");

  if (needsCtrl && !event.ctrlKey) return false;
  if (needsMeta && !event.metaKey) return false;
  if (needsShift !== event.shiftKey) return false;
  if (needsAlt !== event.altKey) return false;
  // When neither ctrl nor meta needed explicitly (not "mod"/"ctrl"/"cmd"),
  // we still tolerate either being absent; above checks already enforce.
  // Compare the actual key case-insensitively.
  return event.key.toLowerCase() === key;
}

function isEditable(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  return false;
}

export function useHotkey(
  combo: string,
  handler: Handler,
  { enabled = true, allowInInputs = false, preventDefault = true }: Options = {},
): void {
  const handlerRef = useRef<Handler>(handler);
  handlerRef.current = handler;

  useEffect(() => {
    if (!enabled) return;
    const listener = (event: KeyboardEvent) => {
      if (!allowInInputs && isEditable(event.target)) return;
      if (!matches(event, combo)) return;
      if (preventDefault) event.preventDefault();
      handlerRef.current(event);
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [combo, enabled, allowInInputs, preventDefault]);
}
