/**
 * Global "edit layout" mode.
 *
 * A reorderable page registers itself (``registerPage(pageKey)``) on mount so
 * the Header can show the "Edit layout" toggle only where it does something.
 * While ``editing`` is true, cards on the active page show drag handles and can
 * be reordered; otherwise they're completely static. AppShell resets
 * ``editing`` to false on navigation.
 */

import { useEffect } from "react";
import { create } from "zustand";

interface LayoutEditState {
  editing: boolean;
  /** pageKey of the reorderable page currently mounted, or null. */
  activePage: string | null;
  setEditing: (v: boolean) => void;
  registerPage: (pageKey: string | null) => void;
}

export const useLayoutEditStore = create<LayoutEditState>((set) => ({
  editing: false,
  activePage: null,
  setEditing: (v) => set({ editing: v }),
  registerPage: (pageKey) => set({ activePage: pageKey, editing: false }),
}));

/**
 * Register the current page as reorderable for the lifetime of the component.
 * On unmount it clears the active page (and exits edit mode) if it still owns
 * the slot.
 */
export function useRegisterLayoutPage(pageKey: string): void {
  useEffect(() => {
    useLayoutEditStore.setState({ activePage: pageKey, editing: false });
    return () => {
      // Only clear if no other page has taken over in the meantime.
      const { activePage } = useLayoutEditStore.getState();
      if (activePage === pageKey) {
        useLayoutEditStore.setState({ activePage: null, editing: false });
      }
    };
  }, [pageKey]);
}
