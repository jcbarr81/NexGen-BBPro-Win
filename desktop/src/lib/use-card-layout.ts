/**
 * Hook that resolves the display order of a page's cards from the saved
 * per-user layout (see ``layout-store.ts``), reconciled against the cards
 * actually present this render.
 *
 * Key invariant: we ONLY persist on an explicit drag (``setOrder``), never on
 * render. That's what lets conditionally-rendered cards (e.g. a team switcher
 * that only shows with >1 team) keep their saved slot — when they vanish they
 * just drop out of the *displayed* order, and when they return they snap back
 * to where the user put them.
 */

import { useMemo } from "react";
import { useSyncExternalStore } from "react";

import { useAuthStore } from "@/lib/auth-store";
import {
  readOrder,
  resetOrder,
  subscribeLayout,
  writeOrder,
} from "@/lib/layout-store";

/**
 * Merge a saved order with the cards present this render.
 * - no saved order → defaults verbatim.
 * - saved ids still present → kept in saved order (removed ids dropped).
 * - present ids missing from saved (new cards) → appended in default order.
 * Pure + exported for unit testing.
 */
export function reconcileOrder(
  saved: string[] | null,
  present: string[],
): string[] {
  if (!saved || saved.length === 0) return present;
  const presentSet = new Set(present);
  const kept = saved.filter((id) => presentSet.has(id));
  const keptSet = new Set(kept);
  const appended = present.filter((id) => !keptSet.has(id));
  return [...kept, ...appended];
}

export interface CardLayout {
  /** Ids of the currently-present cards in their display order. */
  orderedIds: string[];
  /** Persist a new full order (call after arrayMove on a drag). */
  setOrder: (ids: string[]) => void;
  /** Clear the saved order → revert to defaults. */
  reset: () => void;
  /** True when a custom (non-default) order is saved for this page. */
  isCustomized: boolean;
}

export function useCardLayout(
  pageKey: string,
  presentIds: string[],
): CardLayout {
  const uid = useAuthStore((s) => s.uid);

  const saved = useSyncExternalStore(
    subscribeLayout,
    () => readOrder(uid, pageKey),
    () => null,
  );

  const presentKey = presentIds.join("|");
  const orderedIds = useMemo(
    () => reconcileOrder(saved, presentIds),
    // presentKey captures the present-id set without an unstable array dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [saved, presentKey],
  );

  return {
    orderedIds,
    isCustomized: !!saved && saved.length > 0,
    setOrder: (ids: string[]) => writeOrder(uid, pageKey, ids),
    reset: () => resetOrder(uid, pageKey),
  };
}
