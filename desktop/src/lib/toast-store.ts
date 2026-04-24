/**
 * Minimal toast system. Stand-in for ``sonner`` / ``radix-toast`` without
 * the bundle weight — a Zustand store + a render component (``Toaster``).
 *
 * Use for transient action feedback (mutation success/failure, copy-to-
 * clipboard, etc.). Keep inline ``<Card>`` errors for page-load failures
 * where the user needs persistent context.
 *
 *   toast.error("Save failed");
 *   toast.success("Trade approved", { description: "Commish Bob" });
 *   toast.info("Draft regenerated");
 */

import { create } from "zustand";

export type ToastTone = "success" | "error" | "info";

export interface ToastEntry {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
  /** ms until auto-dismiss; set to ``0`` to keep it until dismissed. */
  duration: number;
}

interface ToastState {
  entries: ToastEntry[];
  push: (entry: Omit<ToastEntry, "id">) => number;
  dismiss: (id: number) => void;
  clear: () => void;
}

const useToastStore = create<ToastState>((set) => ({
  entries: [],
  push: (entry) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    set((state) => ({ entries: [...state.entries, { ...entry, id }] }));
    return id;
  },
  dismiss: (id) =>
    set((state) => ({ entries: state.entries.filter((t) => t.id !== id) })),
  clear: () => set({ entries: [] }),
}));

interface Options {
  description?: string;
  duration?: number;
}

function show(tone: ToastTone, title: string, options: Options = {}): number {
  const id = useToastStore.getState().push({
    tone,
    title,
    description: options.description,
    duration: options.duration ?? (tone === "error" ? 7000 : 4000),
  });
  const duration = options.duration ?? (tone === "error" ? 7000 : 4000);
  if (duration > 0) {
    window.setTimeout(() => {
      useToastStore.getState().dismiss(id);
    }, duration);
  }
  return id;
}

export const toast = {
  error: (title: string, options?: Options) => show("error", title, options),
  success: (title: string, options?: Options) =>
    show("success", title, options),
  info: (title: string, options?: Options) => show("info", title, options),
  dismiss: (id: number) => useToastStore.getState().dismiss(id),
  clear: () => useToastStore.getState().clear(),
};

export function useToasts() {
  return useToastStore((s) => s.entries);
}

/** Select each action individually. Returning ``{dismiss, clear}`` from a
 *  single selector creates a new object every render, and Zustand's
 *  default ``Object.is`` equality treats it as changed — which triggers
 *  an infinite render loop (React error #185). The store setters are
 *  stable references, so individual selectors stay referentially equal
 *  across renders. */
export function useToastActions() {
  const dismiss = useToastStore((s) => s.dismiss);
  const clear = useToastStore((s) => s.clear);
  return { dismiss, clear };
}
