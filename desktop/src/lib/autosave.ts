/**
 * Autosave hook — ports the QTimer-based recovery file in the PyQt
 * lineup/pitching editors. Persists dirty editor state to localStorage at
 * a throttled cadence; on reload, the mount-time check returns any
 * outstanding draft so the UI can offer "restore unsaved edits?".
 *
 * Usage:
 *   const { autosavedDraft, clearDraft } = useAutosaveDraft({
 *     key: `lineup:${teamId}:${vs}`,
 *     data: rows,
 *     dirty,
 *   });
 *
 * When ``dirty`` is true, the provided data is written to localStorage
 * after ``delay`` ms of no further changes. When ``dirty`` flips back to
 * false (e.g. save succeeded), the stored draft is cleared automatically.
 */

import { useEffect, useRef, useState } from "react";

const PREFIX = "nexgen:draft:";
const DEFAULT_DELAY_MS = 1500;

interface Options<T> {
  /** Stable, unique key per editor context (e.g. `lineup:POR:rhp`). */
  key: string;
  /** Currently-editing data. */
  data: T;
  /** True while edits have been made but not saved. */
  dirty: boolean;
  /** Debounce in ms. Defaults to 1.5s. */
  delay?: number;
}

interface Result<T> {
  /** Draft detected at mount, if any. Consume via `clearDraft()`. */
  autosavedDraft: T | null;
  /** Call after restoring (or dismissing) the offered draft. */
  clearDraft: () => void;
  /** Timestamp of the last successful autosave (ms since epoch) or 0. */
  lastSavedAt: number;
}

export function useAutosaveDraft<T>({
  key,
  data,
  dirty,
  delay = DEFAULT_DELAY_MS,
}: Options<T>): Result<T> {
  const storageKey = PREFIX + key;
  const [autosavedDraft, setAutosavedDraft] = useState<T | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState(0);
  const timerRef = useRef<number | null>(null);

  // Mount-time: look for a previous draft and surface it.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw) as { data: T; t: number };
        if (parsed && "data" in parsed) {
          setAutosavedDraft(parsed.data);
          setLastSavedAt(Number(parsed.t) || 0);
        }
      }
    } catch {
      /* ignore corrupt drafts */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  // Debounced persist whenever `dirty` is true and data changes.
  useEffect(() => {
    if (!dirty) {
      // Clean save state ⇒ wipe draft.
      try {
        window.localStorage.removeItem(storageKey);
      } catch {
        /* storage may be disabled */
      }
      return;
    }
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(() => {
      try {
        const payload = JSON.stringify({ data, t: Date.now() });
        window.localStorage.setItem(storageKey, payload);
        setLastSavedAt(Date.now());
      } catch {
        /* ignore quota errors */
      }
    }, delay);
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, [data, dirty, delay, storageKey]);

  const clearDraft = () => {
    try {
      window.localStorage.removeItem(storageKey);
    } catch {
      /* ignore */
    }
    setAutosavedDraft(null);
  };

  return { autosavedDraft, clearDraft, lastSavedAt };
}
