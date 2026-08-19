# S3-12 — Sidebar Phase-Hiding → Disabled + Tooltip (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 UI/IA track. Frontend-only. NOTE: the plan's anchor
> `Sidebar.tsx:469-476` did not match on a `phase` grep at 7.1.0 — the phase-gate
> may have moved or use different terms; **locate the current phase-based
> show/hide before coding** (`desktop/src/components/layout/Sidebar.tsx`).

## Objective

Pinned favorites (e.g. Draft, Offseason) **silently vanish** from the sidebar
when the season phase makes them inapplicable — a pinned item disappearing with
no explanation is confusing. Replace phase-based *hiding* with **disabled +
tooltip** so the item stays visible but clearly unavailable, with a reason.

## Verified current state

- `desktop/src/components/layout/Sidebar.tsx` renders nav + pinned favorites and
  applies a phase-based visibility filter (locate it — the plan cited ~469-476).
- Season phase is available in the app state the sidebar already reads.
- Route metadata (which phase a route applies to) lives with `route-index.ts` /
  the nav config.

## Acceptance criteria

1. A pinned/favorited nav item that is phase-inapplicable renders **disabled**
   (greyed, non-navigable) instead of being removed.
2. Hovering the disabled item shows a **tooltip** with the reason (e.g.
   "Available during the Amateur Draft phase").
3. Non-pinned phase-specific entries: keep current behavior OR also disable —
   pick one and be consistent (D2).
4. Clicking a disabled item does nothing (no nav, no error); `tsc --noEmit` +
   `vite build` clean.

## Decisions (no open choices)

- **D1 — Disable, don't hide, for PINNED items** (the confusing case). A pinned
  favorite must never silently disappear.
- **D2 — For non-pinned phase entries, keep hiding** (they were never pinned, so
  disappearing isn't surprising) — minimizes churn. Document the split.
- **D3 — Reason text** comes from the route's phase metadata (a small
  `phaseLabel` map), not hard-coded per item.

## Files to change

| File | Change |
|---|---|
| `desktop/src/components/layout/Sidebar.tsx` | Pinned phase-inapplicable items → disabled + tooltip (reason from metadata); keep hiding for non-pinned. |
| `desktop/src/lib/route-index.ts` (or nav config) | Phase-applicability + reason label per route. |
| Shared Tooltip component | Reuse existing. |

## Verification gate

- `tsc --noEmit` + `vite build`. Manual: pin Draft during regular season →
  visible-but-disabled with a tooltip; clicking does nothing; it re-enables in
  the Draft phase.

## Non-goals

- Redesigning the sidebar. Drag-reorder of favorites. Phase-transition
  animations. Changing which routes are phase-gated.
