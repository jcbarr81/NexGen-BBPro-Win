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
const PREFERENCE_PREFIX = "nexgen:pref:";

type Kind = "session" | "local";

function store(kind: Kind): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null; // storage blocked (private window, site data off)
  }
}

function read<T>(key: string, fallback: T, kind: Kind = "session"): T {
  const s = store(kind);
  if (!s) return fallback;
  try {
    const raw = s.getItem((kind === "local" ? PREFERENCE_PREFIX : PREFIX) + key);
    if (raw == null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function write<T>(key: string, value: T, kind: Kind = "session"): void {
  const s = store(kind);
  if (!s) return;
  try {
    s.setItem(
      (kind === "local" ? PREFERENCE_PREFIX : PREFIX) + key,
      JSON.stringify(value),
    );
  } catch {
    /* quota / serialization issues — drop silently */
  }
}

/**
 * localStorage-backed useState: a preference the owner sets once and
 * expects to find again next time (e.g. a table's chosen columns, 8.10.0),
 * unlike the filters above, which reset between launches.
 */
export function useStoredPreference<T>(
  key: string,
  initial: T,
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => read(key, initial, "local"));
  useEffect(() => {
    write(key, value, "local");
  }, [key, value]);
  return [value, setValue];
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
