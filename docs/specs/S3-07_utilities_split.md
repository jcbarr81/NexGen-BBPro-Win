# S3-07 — Utilities Split (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 UI/IA track. Frontend-only.

## Objective

The Utilities page mixes **owner-usable** tools (reports/exports) with
**admin-only** actions (including an admin-elevate card). Split it: a
non-admin **Reports/Exports** page owners can use, mark the remaining Utilities
surface `adminOnly`, and move the admin-elevate card out of the general area.

## Verified current state

- Routing/roles live in `desktop/src/lib/route-index.ts` (each route carries an
  `adminOnly` flag; `RequireAdmin` wrapper from QW-03 enforces it).
- The Utilities page + admin-elevate card are in `desktop/src/pages/` (locate
  the current UtilitiesPage / admin-elevate component).

## Acceptance criteria

1. A **Reports/Exports** page exists, reachable by owners (not `adminOnly`),
   containing the export/report tools that don't require admin.
2. The remaining Utilities surface is flagged `adminOnly` in `route-index.ts`
   (enforced by the existing `RequireAdmin` wrapper) and hidden from owners in
   Sidebar + Command Palette.
3. The **admin-elevate** card is moved into an admin-only location (not shown to
   owners).
4. `tsc --noEmit` + `vite build` clean; owner cannot reach admin Utilities by
   direct nav (redirect to /home).

## Decisions (no open choices)

- **D1 — Reuse the `adminOnly` + `RequireAdmin` mechanism** (QW-03) — no new
  guard. Reports/Exports = no flag; Utilities = `adminOnly: true`.
- **D2 — Split by capability, not by cosmetics.** Only genuinely admin actions
  stay admin; everything an owner can already do server-side moves to
  Reports/Exports.

## Files to change

| File | Change |
|---|---|
| `desktop/src/lib/route-index.ts` | New Reports/Exports route (owner); Utilities → `adminOnly`. |
| `desktop/src/pages/ReportsExportsPage.tsx` (new) | Owner-facing report/export tools. |
| `desktop/src/pages/UtilitiesPage.tsx` | Remove owner tools + the elevate card. |
| `desktop/src/components/layout/Sidebar.tsx` | Nav reflects the split + role filter. |

## Verification gate

- `tsc --noEmit` + `vite build`. Manual: as owner, Reports/Exports reachable,
  Utilities not shown and direct-nav redirects; as admin, both present.

## Non-goals

- New report types. Backend/API changes. Redesigning the export flow itself.
