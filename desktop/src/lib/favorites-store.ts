/**
 * Pin-to-sidebar favorites store.
 *
 * A flat list of route paths (e.g. ``"/roster"``) stored in
 * localStorage. The sidebar renders these in a "Favorites" section
 * above the hubs; right-click context menus (on hub cards + sidebar
 * items) toggle membership.
 */

import { useSyncExternalStore } from "react";

const STORAGE_KEY = "nexgen:sidebar:favorites";

type Listener = () => void;

let cache: string[] | null = null;
const listeners = new Set<Listener>();

function read(): string[] {
  if (cache) return cache;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      cache = [];
      return cache;
    }
    const parsed = JSON.parse(raw);
    cache = Array.isArray(parsed)
      ? parsed.filter((p): p is string => typeof p === "string")
      : [];
    return cache;
  } catch {
    cache = [];
    return cache;
  }
}

function write(next: string[]) {
  cache = [...next];
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // localStorage unavailable — keep the in-memory cache.
  }
  for (const fn of listeners) fn();
}

function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function getSnapshot(): string[] {
  return read();
}

const SERVER_SNAPSHOT: string[] = [];
function getServerSnapshot(): string[] {
  return SERVER_SNAPSHOT;
}

interface FavoritesAPI {
  pinned: string[];
  isPinned: (path: string) => boolean;
  add: (path: string) => void;
  remove: (path: string) => void;
  toggle: (path: string) => void;
  clear: () => void;
}

export function useFavoritesStore<T>(selector: (api: FavoritesAPI) => T): T {
  const pinned = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const api: FavoritesAPI = {
    pinned,
    isPinned: (path: string) => pinned.includes(path),
    add: (path: string) => {
      if (pinned.includes(path)) return;
      write([...pinned, path]);
    },
    remove: (path: string) => {
      if (!pinned.includes(path)) return;
      write(pinned.filter((p) => p !== path));
    },
    toggle: (path: string) => {
      if (pinned.includes(path)) {
        write(pinned.filter((p) => p !== path));
      } else {
        write([...pinned, path]);
      }
    },
    clear: () => write([]),
  };
  return selector(api);
}
