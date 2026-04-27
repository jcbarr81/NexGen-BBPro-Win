/**
 * Tiny in-app navigation history stack.
 *
 * The Header mounts per AppShell so we can't keep the stack in
 * component state — instead it lives in a module-level array exposed
 * via ``useSyncExternalStore``. ``record(path)`` should fire on every
 * meaningful navigation; ``goBack()`` pops the last entry and returns
 * it. Auth / splash routes are excluded so clicking Back from the
 * dashboard never lands the user on the login screen.
 */

import { useSyncExternalStore } from "react";

const STACK: string[] = [];
const MAX = 50;
const EXCLUDE_PATTERNS = [/^\/login/, /^\/splash/, /^\/select-league/, /^\/leagues\/new/];

type Listener = () => void;
const listeners = new Set<Listener>();

function isInAppRoute(path: string): boolean {
  if (!path) return false;
  return !EXCLUDE_PATTERNS.some((re) => re.test(path));
}

function notify() {
  for (const fn of listeners) fn();
}

function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function getSnapshot(): number {
  return STACK.length;
}

function getServerSnapshot(): number {
  return 0;
}

/**
 * Record a navigation. The Header mounts a hook that fires this on
 * every ``location.pathname`` change. Ignored when:
 *   - the route is auth/splash
 *   - the same path was already at the top (e.g. a useEffect re-run)
 */
export function recordNavigation(path: string): void {
  if (!isInAppRoute(path)) return;
  if (STACK.length > 0 && STACK[STACK.length - 1] === path) return;
  STACK.push(path);
  if (STACK.length > MAX) STACK.shift();
  notify();
}

/**
 * Pop the most recent in-app route below the current one. Returns the
 * path to navigate to, or ``null`` if there's nothing to go back to.
 *
 * The current page sits at the top of the stack — the previous page is
 * the one before it. Pop both: the destination becomes the new top so
 * a subsequent navigation re-records it cleanly.
 */
export function popPrevious(): string | null {
  if (STACK.length < 2) return null;
  STACK.pop(); // drop current
  const prev = STACK.pop() ?? null;
  notify();
  return prev;
}

/**
 * React hook returning whether there's anywhere to go back to. Use to
 * gate the Back button's enabled state.
 */
export function useCanGoBack(): boolean {
  const length = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return length >= 2;
}
