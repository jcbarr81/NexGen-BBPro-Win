# S3-08 — Account Page (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 UI/IA track. Frontend-only (endpoint already exists).

## Objective

`GET /account/me` is served and the client already has `api.accountMe()`
(`desktop/src/lib/api.ts:1440-1458`), but there is **no Account page** — the
header user block links nowhere useful. Add a minimal profile page.

## Verified current state

- `desktop/src/lib/api.ts:1440` `accountMe: () => …("/account/me")` returns the
  current user's profile payload (fields: verify the response shape — likely
  email/display name/role/leagues/membership).
- The header shows a user block (locate `AppShell`/header component).
- Routing centralized in `route-index.ts`.

## Acceptance criteria

1. An **Account page** (`/account`) renders the `accountMe()` payload: display
   name, email, role, and league memberships (read-only is acceptable for v1).
2. The header user block links to `/account`.
3. Any editable fields the endpoint supports (if a PATCH exists — verify) get a
   simple form; otherwise read-only with a note.
4. `tsc --noEmit` + `vite build` clean; page renders for a logged-in user.

## Decisions (no open choices)

- **D1 — Read-only v1** unless a profile-update endpoint already exists (verify
  the account router). Ship the view first; editing is a follow-up.
- **D2 — Reuse existing data hooks/patterns** (the same query pattern other pages
  use for `accountMe`); no new state library.

## Files to change

| File | Change |
|---|---|
| `desktop/src/lib/route-index.ts` | `/account` route (owner-level, authed). |
| `desktop/src/pages/AccountPage.tsx` (new) | Profile view from `accountMe()`. |
| Header/AppShell component | Link the user block to `/account`. |

## Verification gate

- `tsc --noEmit` + `vite build`. Manual: header → Account, profile fields render.

## Non-goals

- Password/email change flows (auth-sensitive; separate task). Avatar upload.
  Notification preferences. Cross-league account management.
