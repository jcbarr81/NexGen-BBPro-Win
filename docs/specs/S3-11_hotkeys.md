# S3-11 — Hotkey Coverage + Shortcuts Dialog (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 UI/IA track. Frontend-only.

## Objective

Save/keyboard shortcuts are inconsistent: `mod+s` exists on some save-shaped
pages (`DepthChartPage`, `LineupPage`, `TeamSettingsPage`, `TrainingPage`) but
not all, and there's no discoverable list of shortcuts. Extend `mod+s` to the
remaining save-shaped pages and add a shortcuts help dialog.

## Verified current state

- `mod+s` is wired on: `DepthChartPage.tsx`, `LineupPage.tsx`,
  `TeamSettingsPage.tsx`, `TrainingPage.tsx` (grep confirms). Other save-shaped
  pages lack it.
- A `CommandPalette` exists (`desktop/src/components/CommandPalette.tsx`) —
  likely already keyed (mod+k). The shortcuts dialog can live alongside it.
- Hotkey handling pattern: locate the shared hook/util the four pages use so new
  pages reuse it (don't hand-roll per page).

## Acceptance criteria

1. Every **save-shaped page** (a page with a primary Save action) supports
   `mod+s` to save, via the shared hook — enumerate the save-shaped pages and
   cover the gaps.
2. A **shortcuts dialog** (e.g. `?` or a Help menu item) lists the available
   shortcuts (Command Palette, Save, navigation), discoverable and role-aware.
3. `mod+s` never triggers the browser's Save dialog (preventDefault) and is inert
   on non-save pages.
4. `tsc --noEmit` + `vite build` clean.

## Decisions (no open choices)

- **D1 — One shared `useSaveHotkey`** (extract from the existing four pages if
  not already shared) so coverage is uniform and future pages opt in with one
  line.
- **D2 — Shortcuts dialog is data-driven** from a small registry (so it stays in
  sync as shortcuts are added), mirroring how `CommandPalette` derives from
  `route-index`.

## Files to change

| File | Change |
|---|---|
| `desktop/src/hooks/useSaveHotkey.ts` (new or extract) | Shared save-hotkey hook. |
| Save-shaped pages missing it | Adopt the hook. |
| `desktop/src/components/ShortcutsDialog.tsx` (new) | Discoverable shortcut list. |
| `AppShell` / Help menu | Open the dialog (`?`). |

## Verification gate

- `tsc --noEmit` + `vite build`. Manual: `mod+s` saves on each save page (no
  browser dialog); `?` opens the shortcuts list.

## Non-goals

- Fully customizable keybindings. Vim-style chords. Global OS-level shortcuts.
  Per-page bespoke shortcuts beyond save + navigation.
