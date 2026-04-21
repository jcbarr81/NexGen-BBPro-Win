/**
 * First-visit tutorial state.
 *
 * Each tutorial id gets its own localStorage flag once shown, so we
 * never show it again on the same machine. A global "enabled" flag
 * lets users switch off first-visit auto-launch entirely. "Restart
 * tutorials" wipes every flag so everything replays on next visit.
 *
 * Intentionally localStorage-only: tutorial state is per-user-per-
 * device UX trivia, not something we want to sync server-side or
 * synchronise across leagues.
 */

import { create } from "zustand";

const ENABLED_KEY = "nexgen:tutorials:enabled";
const FLAG_PREFIX = "nexgen:tutorials:seen:";

function readEnabled(): boolean {
  try {
    const raw = window.localStorage.getItem(ENABLED_KEY);
    if (raw === null) return true; // default on
    return raw === "1" || raw === "true";
  } catch {
    return true;
  }
}

function writeEnabled(value: boolean) {
  try {
    window.localStorage.setItem(ENABLED_KEY, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function hasSeen(id: string): boolean {
  try {
    return window.localStorage.getItem(FLAG_PREFIX + id) === "1";
  } catch {
    return false;
  }
}

function markSeen(id: string) {
  try {
    window.localStorage.setItem(FLAG_PREFIX + id, "1");
  } catch {
    /* ignore */
  }
}

function clearAllFlags() {
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key && key.startsWith(FLAG_PREFIX)) keys.push(key);
    }
    for (const key of keys) window.localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

interface TutorialState {
  enabled: boolean;
  /** Incrementing version counter — consumers bump this after a reset so
   *  subscribed hooks re-check their "seen" flag. */
  resetCounter: number;
  toggle: (next: boolean) => void;
  wasSeen: (id: string) => boolean;
  markSeen: (id: string) => void;
  restartAll: () => void;
}

export const useTutorialStore = create<TutorialState>((set) => ({
  enabled: typeof window !== "undefined" ? readEnabled() : true,
  resetCounter: 0,
  toggle: (next) => {
    writeEnabled(next);
    set({ enabled: next });
  },
  wasSeen: (id) => hasSeen(id),
  markSeen: (id) => markSeen(id),
  restartAll: () => {
    clearAllFlags();
    set((state) => ({ resetCounter: state.resetCounter + 1 }));
  },
}));
