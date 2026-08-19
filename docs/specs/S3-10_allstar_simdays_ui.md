# S3-10 — All-Star Admin + Sim-N-Days UI (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 UI/IA track. Frontend-only (endpoints exist).

## Objective

Two server capabilities have no UI: `triggerAllStarGame`
(`desktop/src/lib/api.ts:2046`) and `seasonSimulateDays(n)`
(`desktop/src/lib/api.ts:2231`). Add admin controls to fire the All-Star Game
and to simulate a chosen number of days.

## Verified current state

- `api.ts:2046` `triggerAllStarGame(year, {force?, seed?})`.
- `api.ts:2231` `seasonSimulateDays(n)`.
- Season/admin controls live on the Season/Command-Center admin surfaces
  (locate the season-admin page that already has sim controls).

## Acceptance criteria

1. An admin control to **simulate N days** (numeric input + button) calling
   `seasonSimulateDays(n)`, with progress/results feedback and error handling,
   guarded `adminOnly`.
2. An admin control to **trigger the All-Star Game** (`triggerAllStarGame`) with
   an optional force/seed, guarded `adminOnly`, shown at the appropriate phase
   (around the break).
3. Both reflect success/failure (toast + refreshed state); disabled when not
   applicable (wrong phase).
4. `tsc --noEmit` + `vite build` clean; owner cannot see/trigger these.

## Decisions (no open choices)

- **D1 — Place on the existing season-admin surface** (the page that already
  drives sim/advance-phase), not a new page.
- **D2 — Reuse the app's confirm-dialog + toast** patterns (no native
  `window.confirm`, per the codebase ban).
- **D3 — Phase-gating:** disable + tooltip when the action isn't valid for the
  current phase (aligns with S3-12's disabled-not-hidden approach).

## Files to change

| File | Change |
|---|---|
| Season-admin page (`SeasonPage`/Command-Center admin) | Sim-N-days input + All-Star trigger controls, `adminOnly`. |
| `desktop/src/lib/api.ts` | Already has the client fns — wire them. |

## Verification gate

- `tsc --noEmit` + `vite build`. Manual (admin): sim-N-days advances the calendar
  N days; All-Star trigger runs at the break; both blocked for owners.

## Non-goals

- All-Star roster selection UI. Sim-to-date / sim-to-phase (separate). Changing
  the underlying sim/all-star server logic.
