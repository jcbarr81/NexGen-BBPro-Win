# S3-06 — Consolidate Player Pages (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 UI/IA track. Frontend-only.

## Objective

Player information is scattered across parallel top-level pages
(`PitchersPage`, `PositionPlayersPage`, plus `PlayersBrowserPage`,
`RosterPage`), Team Stats is reached by a URL-swapping redirect, and the
Contracts hub is placed inconsistently. Consolidate into a coherent IA: one
Players surface with **Pitchers / Position Players** tabs, Team Stats as a tab
(not a route redirect), and Contracts placed under the league-primary nav.

## Verified current state

- `desktop/src/pages/`: `PitchersPage.tsx`, `PositionPlayersPage.tsx`,
  `PlayersBrowserPage.tsx`, `RosterPage.tsx`, `ContractsPage.tsx`,
  `PlayerProfilePage.tsx`.
- Routing is centralized in `desktop/src/lib/route-index.ts` (consumed by
  `CommandPalette`, `Breadcrumbs`, `Sidebar`) — changes must go there so the
  palette/breadcrumbs/sidebar stay consistent (this is the pattern QW-07 relied
  on).

## Acceptance criteria

1. Pitchers and Position Players become **tabs** of a single Players page (or of
   the Roster page — pick one; see D1), sharing filters/search where sensible.
2. **Team Stats is a tab**, not a route that swaps the URL/redirects.
3. Contracts appears under **league-primary** navigation (not buried), reachable
   from the hub/sidebar.
4. `route-index.ts` updated so Command Palette, Breadcrumbs, and Sidebar reflect
   the new structure; deep links to old routes redirect (no dead links).
5. `tsc --noEmit` clean; `vite build` succeeds; click-through of each tab works.

## Decisions (no open choices)

- **D1 — One "Players" page with tabs** (Pitchers / Position Players / Team
  Stats), keeping `RosterPage` as the roster-management surface. Rationale:
  Players = browsing/stats; Roster = management; don't overload Roster.
- **D2 — Preserve deep links.** Old `/pitchers` and `/position-players` routes
  become `Navigate` aliases into the tabbed page with the right tab preselected
  (like the `/standings` alias QW-02 added).
- **D3 — No data-fetch regressions.** Reuse the existing page components as tab
  panels; don't rewrite their data hooks.

## Files to change

| File | Change |
|---|---|
| `desktop/src/lib/route-index.ts` | New Players route + tab params; alias old routes; move Contracts to league-primary. |
| `desktop/src/pages/PlayersPage.tsx` (new or repurpose PlayersBrowser) | Tabbed shell hosting Pitchers/Position/Team-Stats panels. |
| `desktop/src/pages/PitchersPage.tsx`, `PositionPlayersPage.tsx` | Become tab panels (props for embedded mode). |
| `desktop/src/App.tsx` | Route wiring + aliases. |
| `desktop/src/components/layout/Sidebar.tsx` | Nav entries reflect consolidation. |

## Verification gate

- `tsc --noEmit` + `vite build` clean. Manual: each tab renders, old deep links
  redirect, Command Palette lists the new structure, Breadcrumbs correct.

## Non-goals

- Redesigning the individual stat tables. Player-profile page changes. Mobile
  layout overhaul. Server/API changes.
