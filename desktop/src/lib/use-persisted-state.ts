/**
 * sessionStorage-backed useState replacement. Used for filter/sort/active-tab
 * UI state on list pages so back-navigation + intra-session navigation
 * restore the user's view instead of resetting to defaults.
 *
 * sessionStorage (not localStorage) is intentional — these are ephemeral
 * UI preferences that should reset between launches but persist across
 * page navigations within the same session. localStorage would persist
 * stale filter state forever.
 *
 * Usage:
 *   const [sortKey, setSortKey] = usePersistedState("pitchers:sortKey", "overall");
 *
 * Keys should be globally unique. Convention: ``<page>:<slice>``.
 */

import { useEffect, useState } from "react";

const PREFIX = "nexgen:filter:";

function read<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.sessionStorage.getItem(PREFIX + key);
    if (raw == null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function write<T>(key: string, value: T): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    /* quota / serialization issues — drop silently */
  }
}

export function usePersistedState<T>(
  key: string,
  initial: T,
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => read(key, initial));
  useEffect(() => {
    write(key, value);
  }, [key, value]);
  return [value, setValue];
}

/** Imperative reader — useful when you want to peek without subscribing. */
export function readPersistedState<T>(key: string, fallback: T): T {
  return read(key, fallback);
}
