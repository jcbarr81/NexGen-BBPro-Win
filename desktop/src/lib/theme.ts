/**
 * Theme + color-mode management. Each theme is a CSS class applied to
 * ``<html>`` (e.g. ``theme-dugout``). The ``dark`` class is an orthogonal
 * modifier so any theme can be shown light or dark.
 *
 * Persisted to localStorage so the choice survives restarts. Reads back
 * at module load and re-applies synchronously to avoid a flash of the
 * default palette on reload.
 */

import { create } from "zustand";

export type ThemeId = "dugout" | "night" | "grass";
export type ColorMode = "light" | "dark";

export interface ThemeDefinition {
  id: ThemeId;
  label: string;
  description: string;
  className: string;
}

export const THEMES: ThemeDefinition[] = [
  {
    id: "dugout",
    label: "Dugout",
    description: "Warm leather retro — the original brown/amber palette.",
    className: "theme-dugout",
  },
  {
    id: "night",
    label: "Night Game",
    description: "LED scoreboard navy with stadium amber and chalk.",
    className: "theme-night",
  },
  {
    id: "grass",
    label: "Grass",
    description: "Daylight ballpark green with clay accents.",
    className: "theme-grass",
  },
];

const STORAGE_THEME = "nexgen:theme";
const STORAGE_MODE = "nexgen:color-mode";

function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw && allowed.includes(raw as T)) return raw as T;
  } catch {
    /* localStorage disabled */
  }
  return fallback;
}

function prefersDark(): boolean {
  try {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  } catch {
    return false;
  }
}

function applyToDocument(theme: ThemeId, mode: ColorMode) {
  const root = document.documentElement;
  // Strip any previous theme class, then add the new one.
  for (const t of THEMES) {
    root.classList.remove(t.className);
  }
  const def = THEMES.find((t) => t.id === theme) ?? THEMES[0];
  root.classList.add(def.className);
  root.classList.toggle("dark", mode === "dark");
}

interface ThemeState {
  theme: ThemeId;
  mode: ColorMode;
  setTheme: (theme: ThemeId) => void;
  setMode: (mode: ColorMode) => void;
  toggleMode: () => void;
}

const initialTheme = readStored<ThemeId>(
  STORAGE_THEME,
  ["dugout", "night", "grass"],
  "dugout",
);
const initialMode = readStored<ColorMode>(
  STORAGE_MODE,
  ["light", "dark"],
  prefersDark() ? "dark" : "dark",
  // Default to dark regardless of OS since every theme is designed to
  // look best dark — but if the user ever flips it, we honor their pick.
);

// Apply immediately so SSR/first paint matches what the store will
// return to components on hydration.
if (typeof window !== "undefined") {
  applyToDocument(initialTheme, initialMode);
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initialTheme,
  mode: initialMode,
  setTheme: (theme) => {
    try {
      window.localStorage.setItem(STORAGE_THEME, theme);
    } catch {
      /* ignore */
    }
    applyToDocument(theme, get().mode);
    set({ theme });
  },
  setMode: (mode) => {
    try {
      window.localStorage.setItem(STORAGE_MODE, mode);
    } catch {
      /* ignore */
    }
    applyToDocument(get().theme, mode);
    set({ mode });
  },
  toggleMode: () => {
    const next = get().mode === "dark" ? "light" : "dark";
    get().setMode(next);
  },
}));
