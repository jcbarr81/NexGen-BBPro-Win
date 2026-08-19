# S3-09 — Owner Dashboard Finance Card + Tier-3 Finance Polish (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 UI/IA track. Frontend-forward (finance endpoints exist).

## Objective

The Owner Dashboard has no at-a-glance finance summary; owners must navigate to
the Finance page to see where they stand. Add a compact headroom + cash card
(deep-linking to Finance), trend sparklines (cash / payroll / debt), and
surface QO / comp-pick status.

## Verified current state

- Finance data endpoints exist and are consumed by the Finance page
  (`FinancePage`/finance hooks) — the payroll-context + finance summary APIs from
  the 7.0 finance overhaul (`/teams/{id}/finance/...`). Verify the exact
  summary/history endpoints (a history/trend endpoint is needed for sparklines;
  if absent, that's a small server add — see D2).
- `OwnerDashboardPage.tsx` is the target surface (its header comment was fixed in
  QW-08; the finance card itself was deferred to this task).

## Acceptance criteria

1. A **compact finance card** on the Owner Dashboard shows luxury-threshold
   headroom + cash, color-coded, deep-linking to the Finance page.
2. **Sparklines** for cash, payroll, and debt over recent periods.
3. **QO / comp-pick** visibility (pending qualifying offers, comp picks owed/due)
   surfaced where relevant.
4. `tsc --noEmit` + `vite build` clean; card renders with live data and matches
   the Finance page's numbers.

## Decisions (no open choices)

- **D1 — Reuse the Finance page's math/hooks** so the card can't disagree with
  the Finance page (single source — the same settlement math the 7.0 overhaul
  established).
- **D2 — Sparkline data source.** Prefer an existing finance-history endpoint; if
  none returns a time series, add a minimal `GET /teams/{id}/finance/history`
  (server) returning recent cash/payroll/debt points — keep it small and cached.
- **D3 — Progressive:** if history data is unavailable for a team, render the
  card without sparklines (headroom+cash only), not an error.

## Files to change

| File | Change |
|---|---|
| `desktop/src/pages/OwnerDashboardPage.tsx` | Finance card + sparklines + QO/comp visibility. |
| `desktop/src/lib/api.ts` | Wire history endpoint client (if added). |
| `api/routers/*finance*` (only if D2) | Minimal finance-history endpoint. |
| Shared chart component | Small sparkline (reuse existing charting if present). |

## Verification gate

- `tsc --noEmit` + `vite build`. Manual: card numbers match Finance page;
  deep-link works; graceful when history absent.

## Non-goals

- Full finance-dashboard redesign. Multi-season financial planning tools.
  Editing finances from the card. New finance rules (that's the 7.0 system).
