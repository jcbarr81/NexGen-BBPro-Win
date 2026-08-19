# Finance — Owner Action Map (per-preset scope, for approval)

> Scope document for owner-facing finance management. Written 2026-08-19 after
> Phase 0 (correct league seeding), Phase 1 (module levels exposed to the client)
> and Phase 2 (owner budget editor) shipped in 7.3.0. This maps **which owner
> actions each finance preset should expose**, marks what's **built vs missing**,
> and lists the **open decisions** to lock before building Phase 3.

Rule of thumb used throughout: an owner action is **available** when its governing
module level is not `off`, AND finance is enabled for the league. `custom` presets
expose whatever the commissioner sets per module, so they're covered implicitly by
the module column.

---

## 1. Preset → module levels (authoritative, from `services/finance_settings.py` PRESET_PROFILES)

| Module | off | simple | standard | mlb_like |
|---|---|---|---|---|
| owner_revenue | off | basic | advanced | advanced |
| owner_market_model | off | off | basic | advanced |
| owner_budgets | off | basic | advanced | advanced |
| owner_expenses | off | basic | advanced | advanced |
| gm_contracts | off | basic | advanced | advanced |
| gm_payroll_rules | off | basic | basic | mlb_like |
| gm_arbitration | off | **off** | basic | advanced |
| gm_free_agency | off | basic | advanced | advanced |
| gm_roster_cost_enforcement | off | on | on | on |
| gm_finance_ai | off | basic | advanced | advanced |

Valid levels: `off / basic / advanced` (payroll_rules: `off / basic / mlb_like`;
roster_cost_enforcement: `off / on`).

---

## 2. Owner actions → governing module, build status

| # | Owner action | Module (gate) | Built today? | Where |
|---|---|---|---|---|
| A1 | View dashboard (cash/debt/revenue/expenses/net) | finance enabled | ✅ built | FinancePage |
| A2 | **Set budgets** (training/scouting/development/facilities) | owner_budgets | ✅ built (Phase 2) | FinancePage BudgetCard |
| A3 | Payroll-vs-threshold headroom view | gm_payroll_rules | ✅ built (read-only) | FinancePage PayrollHeadroomCard |
| A4 | **Extend** a contract (+ evaluate) | gm_contracts | ✅ built | PlayerProfilePage ContractCard |
| A5 | **Release** a player (cut → FA) | gm_contracts | ✅ built | RosterPage roster-cut |
| A6 | **Sign** a free agent (+ evaluate offer) | gm_free_agency | ✅ built | FreeAgencyPage |
| A7 | **Qualifying offer** tender/decline | gm_free_agency | ✅ built | FreeAgencyPage QO card |
| A8 | **Arbitration** decision (offer-raise / hold / non-tender) | gm_arbitration | ❌ **missing owner endpoint+UI** | admin queue only (`services/gm_finance_queue.py` has the submit service) |
| A9 | **Contract options** — exercise/decline team-or-player option | gm_contracts (advanced?) | ❌ **missing** | read-only "pending_options" badge only |
| A10 | **Renew** — pre-arb salary renewal | gm_contracts | ❌ **missing** | none |

---

## 3. Per-preset action availability (the map)

✅ = should be available & is built · ⚠️ = should be available but NOT built (Phase 3) · — = off by preset

| Action | off | simple | standard | mlb_like |
|---|---|---|---|---|
| A1 dashboard | — | ✅ | ✅ | ✅ |
| A2 set budgets | — | ✅ | ✅ | ✅ |
| A3 payroll headroom | — | ✅ | ✅ | ✅ |
| A4 extend contract | — | ✅ | ✅ | ✅ |
| A5 release player | — | ✅ | ✅ | ✅ |
| A6 sign free agent | — | ✅ | ✅ | ✅ |
| A7 qualifying offer | — | ✅ | ✅ | ✅ |
| A8 arbitration decision | — | — (gm_arbitration off) | ⚠️ | ⚠️ |
| A9 contract options | — | see D2 | ⚠️ | ⚠️ |
| A10 renew (pre-arb) | — | see D2 | ⚠️ | ⚠️ |

**Net:** `simple` is fully covered by what's already built (arbitration is off there).
The Phase-3 gaps (A8/A9/A10) only matter for **standard** and **mlb_like** (and
custom leagues that turn `gm_arbitration`/advanced `gm_contracts` on).

---

## 4. `basic` vs `advanced` depth (proposed)

- **gm_contracts basic** → extend + release only (current build).
- **gm_contracts advanced** → also options (A9) and renew (A10).
- **gm_arbitration basic** → tender/non-tender decision.
- **gm_arbitration advanced** → also file/exchange numbers (offer-raise vs hold).

This is a *proposal* — see D1/D2.

---

## 5. Phase 3 build list (only the ⚠️ gaps)

1. **Arbitration decisions (A8)** — owner endpoint wrapping the existing
   `save_team_queue_decision`; UI on the player page / a "Arbitration" section,
   gated on `gm_arbitration != off`. Highest value (it's a whole missing owner loop
   for standard/mlb_like).
2. **Contract options (A9)** — exercise/decline endpoints + UI, gated per D2.
3. **Renew / pre-arb (A10)** — endpoint + UI, gated per D2.

Each ships with: module-gated visibility (Phase 1 data), owner-only client gating,
and a verification pass, on a branch, deployed when confirmed.

---

## 6a. Decisions (locked 2026-08-19)

- **D5 → build ALL three** (A8 arbitration + A9 options + A10 renew) as one Phase 3.
- **D1 → dedicated Arbitration panel** (roll-up of arb-eligible players).
- **D2 → advanced-only** for A9/A10 (require `gm_contracts = advanced`; simple stays extend/release only).
- **D4 → enforce server-side ownership** on new endpoints AND retrofit existing
  finance mutations (extend/sign/qualifying-offer/budgets).
- **D3 → (default, override anytime):** roster-cost breaches are **allowed with a
  warning** in the owner UI (enforcement stays settlement-side, as today).

## 6. Open decisions (resolved above — kept for context)

- **D1 — Arbitration UX:** should arbitration decisions live on the **player page**
  (per-player, next to Extend), on a dedicated **"Arbitration" panel** listing all
  arb-eligible players, or both? (Backend submit service already exists.)
- **D2 — Level gating for options/renew:** do A9 (options) and A10 (renew) require
  `gm_contracts = advanced` (so `simple` owners don't get them), or should they be
  available at `basic` too? Proposal: **advanced-only** (keeps `simple` lightweight).
- **D3 — Enforcement vs advisory:** when `gm_roster_cost_enforcement = on`, should
  owner actions that breach the payroll ceiling be **blocked** or **allowed with a
  warning**? (Today enforcement is settlement-side; owner actions aren't pre-checked.)
- **D4 — Server-side ownership:** existing finance mutations gate on auth only
  (ownership is client-side). Should Phase 3 endpoints **enforce team ownership
  server-side** (and, if so, retrofit A4/A6/A7 too)? Proposal: yes for new endpoints.
- **D5 — Scope cut:** is A8 (arbitration) enough for now, with A9/A10 deferred? Or
  build all three together?
