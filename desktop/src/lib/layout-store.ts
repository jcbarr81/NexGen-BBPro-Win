/**
 * Per-user, per-page card-layout order store (localStorage).
 *
 * Lets users reorder the cards on a page; the chosen order is saved as an
 * array of stable card ids under ``nexgen:layout:<uid|local>:<pageKey>``.
 * Modeled on ``favorites-store.ts`` but keyed per (user, page), so the cache
 * is a Map of storageKey -> order. The cached value is returned by reference
 * and only replaced on write, which keeps ``useSyncExternalStore`` snapshots
 * referentially stable (returning a fresh array each render would loop).
 *
 * A value of ``null`` means "no custom order saved" → the page uses its
 * default order. We never persist an empty array.
 */

const PREFIX = "nexgen:layout:";

type Order = string[];
type Listener = () => void;

// storageKey -> parsed order (null = explicitly unset / default). ``undefined``
// (absent key) means "not read from localStorage yet".
const cache = new Map<string, Order | null>();
const listeners = new Set<Listener>();

export function layoutStorageKey(uid: string | null, pageKey: string): string {
  return `${PREFIX}${uid ?? "local"}:${pageKey}`;
}

function readRaw(key: string): Order | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    const ids = parsed.filter((p): p is string => typeof p === "string");
    return ids.length ? ids : null;
  } catch {
    return null;
  }
}

/** Read the saved order for (uid, pageKey), using the referentially-stable cache. */
export function readOrder(uid: string | null, pageKey: string): Order | null {
  const key = layoutStorageKey(uid, pageKey);
  if (!cache.has(key)) {
    cache.set(key, readRaw(key));
  }
  return cache.get(key) ?? null;
}

export function writeOrder(uid: string | null, pageKey: string, order: Order): void {
  const key = layoutStorageKey(uid, pageKey);
  const next = [...order];
  cache.set(key, next);
  try {
    window.localStorage.setItem(key, JSON.stringify(next));
  } catch {
    // localStorage unavailable — keep the in-memory cache for this session.
  }
  for (const fn of listeners) fn();
}

export function resetOrder(uid: string | null, pageKey: string): void {
  const key = layoutStorageKey(uid, pageKey);
  cache.set(key, null);
  try {
    window.localStorage.removeItem(key);
  } catch {
    // ignore
  }
  for (const fn of listeners) fn();
}

export function subscribeLayout(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
