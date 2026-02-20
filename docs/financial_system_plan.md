# Financial System Implementation Plan (Post-5.0)

## Purpose
Implement a two-layer financial system that can run in multiple complexity levels:

- Owner layer: franchise operations and business finance.
- GM/Coach layer: roster payroll and player-contract finance.

The system must be fully optional, league-scoped, and configurable so commissioners can run:

- No finance at all (current behavior).
- Very simple finance.
- Full MLB-like finance.

## Core Product Goals

1. Add meaningful long-term team-building constraints without forcing complexity.
2. Let leagues tune realism via presets and per-module controls.
3. Keep all finance data isolated per active league.
4. Maintain backward compatibility for existing leagues.
5. Provide clear UX for both commissioners and owners.

## Finance Control Model (Required)

### Global switch

- `financial_system.enabled = false|true`
- If `false`, all finance logic/UI/enforcement is bypassed and gameplay behaves like pre-finance mode.

### When global is ON

- Each finance module is configured independently.
- Module levels:
  - `off`
  - `basic`
  - `advanced` (or `mlb_like` for MLB-specific rules)

### Precedence rules

1. Global OFF always wins.
2. If global ON, each module executes only at its selected level.
3. Missing/invalid module config defaults safely to `off`.

### Preset + custom hybrid

- Presets:
  - `simple`
  - `standard`
  - `mlb_like`
- `custom` lets commissioner override each module and level.

## Two-Layer System Design

### Layer 1: Owner Finance (Franchise Business)

- Revenue:
  - Tickets
  - Concessions
  - Sponsorship/media
- Market effects:
  - Market size
  - Fan interest
  - Recent team performance
- Operating budgets:
  - Training/development budget
  - Scouting budget
  - Facilities/operations budget
- Expenses:
  - Fixed operating costs
  - Variable costs (travel, staffing, development)

### Layer 2: GM/Coach Finance (Baseball Operations)

- Payroll management
- Contracts and extensions
- Arbitration
- Free agency bidding/signing
- Luxury tax / floor / cap-style rules (module-dependent)
- Roster-cost enforcement rules

## Module Matrix

| Layer | Module | off | basic | advanced / mlb_like |
|---|---|---|---|---|
| Owner | Revenue | disabled | fixed seasonal income | attendance-driven tickets + concessions + media + sponsorship |
| Owner | Market model | disabled | small/medium/large multiplier | dynamic market + fan interest + recent performance |
| Owner | Budgets | disabled | single combined ops budget | separate training/scouting/dev/facilities budgets + carryover rules |
| Owner | Expenses | disabled | fixed monthly expense | staffing/facility/travel/development operating costs |
| GM/Coach | Contracts | disabled | salary + years only | guarantees, option years, buyouts, incentives |
| GM/Coach | Payroll rules | disabled | soft payroll target | CBT/luxury-tax thresholds + penalties + floor/cap options |
| GM/Coach | Arbitration | disabled | simple salary bump | service-time arbitration rounds |
| GM/Coach | Free agency | disabled | age/rating ask + simple accept | market-driven bidding + optional comp picks |
| GM/Coach | Roster constraints | disabled | warning-only | hard enforcement when configured |
| GM/Coach | AI behavior | disabled | spend-to-budget | strategy + market-aware multi-year behavior |

## Data Model (Per League)

All files live under the active league `data/` root.

### New files

1. `league_financial_settings.json`
2. `team_financials.json`
3. `contracts.json`
4. `financial_transactions.csv`
5. `finance_snapshots/<season>.json`

### `league_financial_settings.json` (shape)

```json
{
  "version": 1,
  "enabled": true,
  "preset": "custom",
  "enforcement_mode": "warn",
  "modules": {
    "owner_revenue": "basic",
    "owner_market_model": "off",
    "owner_budgets": "basic",
    "owner_expenses": "basic",
    "gm_contracts": "basic",
    "gm_payroll_rules": "off",
    "gm_arbitration": "off",
    "gm_free_agency": "basic",
    "gm_roster_cost_enforcement": "warn",
    "gm_finance_ai": "basic"
  }
}
```

### `team_financials.json` (shape)

```json
{
  "version": 1,
  "season_year": 2027,
  "teams": {
    "NYY": {
      "cash_on_hand": 12000000,
      "debt": 0,
      "revenue": {
        "tickets": 0,
        "concessions": 0,
        "media": 0,
        "sponsorship": 0
      },
      "expenses": {
        "payroll": 0,
        "training": 0,
        "scouting": 0,
        "facilities": 0,
        "operations": 0
      },
      "budgets": {
        "training": 0,
        "scouting": 0,
        "development": 0,
        "facilities": 0
      }
    }
  }
}
```

### `contracts.json` (shape)

```json
{
  "version": 1,
  "players": {
    "P12345": {
      "team_id": "NYY",
      "years_left": 3,
      "annual_salary": 8500000,
      "service_time_days": 620,
      "arb_eligible": true,
      "fa_year": 2029,
      "options": []
    }
  }
}
```

## Service Architecture

1. `services/finance_settings.py`
   - Load/save settings
   - Validate module levels
   - Apply preset profiles
2. `services/owner_finance_engine.py`
   - Owner-layer revenue/expenses/budget resolution
3. `services/contracts_service.py`
   - Contract lifecycle, arb/FA eligibility, extension logic
4. `services/payroll_engine.py`
   - Payroll totals, taxes, penalties, enforcement decisions
5. `services/finance_ai.py`
   - Team budget allocation and finance-aware signing behavior
6. `services/finance_ledger.py`
   - Canonical transaction writing and reporting source

All services must resolve league paths at runtime via current active-league path helpers.

## UI Plan

### Commissioner/Admin

- Add `League Settings -> Financial System`.
- Controls:
  - Global On/Off
  - Preset selector
  - Per-module level controls
  - Enforcement mode (`off`, `warn`, `block`)
  - Projection preview panel

### Owner

- Add `Finance` hub with two tabs:
  - `Owner Ops`
  - `GM/Coach Ops`
- Owner Ops:
  - Cashflow summary
  - Revenue/expense breakdown
  - Budget controls (if allowed)
- GM/Coach Ops:
  - Payroll tracker
  - Contract table
  - Arbitration/FA queues
  - Signing and extension actions

### Alerts/notifications

- Over-budget warnings
- Tax threshold warnings
- Pending arbitration/FA expirations
- Cash risk alerts

## Simulation Cadence

1. Per game day:
   - Attendance-driven tickets/concessions updates (if enabled)
2. Weekly:
   - Training/scouting/facility budget effects
3. Monthly:
   - Media/sponsorship payments and recurring expenses
4. Offseason:
   - Arbitration, qualifying offers (if enabled), free agency cycle
5. Year-end:
   - Owner review, next-year budgets, finance snapshot

## AI Finance Behavior

- Basic mode:
  - Spend within target budget
  - Simple FA decisioning by value score and affordability
- Advanced/MLB-like:
  - Strategy-aware (contend/rebuild)
  - Market-aware spending
  - Multi-year commitment balancing
  - Tax/floor behavior controls

## Permissions and Control

Default recommendation:

1. Commissioners configure league-level finance settings.
2. Owners can operate within allowed financial controls.
3. GM/Coach-level actions can be permission-gated per league mode.

## Migration and Backward Compatibility

1. Existing leagues default to finance OFF.
2. Missing files auto-seed defaults.
3. Invalid config safely falls back to `off` at module level.
4. No schema break to existing core league files.

## Implementation Phases

### Phase A - Foundation

1. Add schemas + defaults.
2. Add settings service and preset resolver.
3. Add file seeding/migration for existing leagues.

### Phase B - Simple End-to-End

1. Owner revenue/expense basic mode.
2. GM payroll + basic contracts.
3. Initial admin/owner UI surfaces.

### Phase C - Standard Mode

1. Market model and split budgets.
2. Arbitration-lite + improved FA.
3. Enhanced reporting.

### Phase D - MLB-Like Mode

1. Service-time arbitration flow.
2. Luxury-tax/floor/cap-style enforcement.
3. Advanced contract terms.

### Phase E - AI and Balance

1. Strategy-aware finance AI.
2. Economic tuning pass.
3. Multi-season stability sims.

### Phase F - QA, Tutorials, Release

1. Full automated test matrix.
2. Updated tutorials/guides.
3. Release smoke checklist updates.

## Testing Plan

### Unit tests

- Settings validation/preset resolution
- Revenue/expense calculations
- Payroll/tax calculations
- Contract state transitions

### Integration tests

- Offseason flow: arbitration -> FA -> signings
- Enforcement modes: off/warn/block
- Admin and owner finance workflows

### Isolation tests

- Ensure finance files are league-scoped only
- Add finance checks to `scripts/smoke_multi_league.py`

## Open Decisions to Confirm Before Coding

1. Permission model: owner vs GM/Coach controls in UI.
2. Over-budget behavior in simple mode: warning-only or block.
3. CBT/luxury-tax availability in standard mode vs MLB-like only.
4. Whether training/scouting budgets directly change development/scouting outcomes in v1.
5. AI cash-floor policy: allow negative cash or enforce hard limits.

## Initial Execution Slice (Recommended)

1. Implement Phase A + Phase B minimal vertical slice.
2. Deliver one complete playable mode:
   - Global ON
   - Owner revenue/expense basic
   - GM payroll/contracts basic
   - Admin config + owner finance dashboard readout
3. Keep advanced modules off by default until validated.

## Financial System Closeout Checklist

Use this checklist as the release gate for the financial-system rollout.
A section is considered complete only when every item is marked done and validated.

### A) Owner Finance Realism

- [x] Replace static monthly revenue/expense assumptions with simulation-driven values (attendance, fan interest, market/performance trend).
- [x] Ensure cadence is fully implemented: per-game/day updates, weekly budget effects, monthly settlements, offseason/year-end transitions.
- [x] Add owner-facing budget editing workflow (not read-only projections), with validation and league-setting guardrails.
- [x] Confirm owner modules honor `off/basic/advanced` behavior exactly as configured.
- [x] Add/expand tests for owner revenue/expense realism and cadence behavior.

Acceptance criteria:
- [x] Owner finance numbers visibly move based on game outcomes and attendance.
- [x] Budget edits persist per league and affect downstream simulation behavior.
- [x] All owner-finance tests pass in release validation.

### B) GM/Coach Economics Completion

- [x] Finalize arbitration depth (service-time handling and configured league-mode behavior).
- [x] Finalize free-agency market behavior for standard/MLB-like modes.
- [x] Implement full payroll-rule accounting effects (CBT/tax/floor/cap-style penalties where enabled), not just warnings/blocks.
- [x] Verify advanced contract terms are fully covered in lifecycle paths (extension, rollover, option decisions, incentives, buyouts).
- [x] Add integration tests for full offseason sequence (arbitration -> FA -> signings -> rollover).

Acceptance criteria:
- [x] Offseason processing yields consistent payroll/contract state with no manual correction.
- [x] Payroll rules produce deterministic, auditable ledger effects when enabled.
- [x] GM/Coach finance tests pass across single-player and multi-owner modes.

### C) Enforcement and Policy Hardening

- [x] Verify enforcement mode (`off/warn/block`) is applied consistently to all write paths (owner/admin actions, offseason, queue apply flows).
- [x] Finalize policy defaults for each preset (`simple`, `standard`, `mlb_like`) and document them.
- [x] Finalize hard-limit behavior for negative cash/debt (or explicitly define allowed debt model).
- [x] Add policy edge-case tests (mixed transactions, floor/cap transitions, blocked operations).

Policy defaults (enforcement + debt model):
- `simple`: payroll rules `basic`, roster-cost enforcement `warn`, debt-cap guardrail `$25M`.
- `standard`: payroll rules `basic`, roster-cost enforcement `warn`, debt-cap guardrail `$80M`.
- `mlb_like`: payroll rules `mlb_like`, roster-cost enforcement `block`, debt-cap guardrail `$150M`.

Debt model:
- Cash is floored at `0`; overages convert into debt (`debt` increases).
- Debt-cap guardrails apply to discretionary payroll actions (signings/trades/arbitration raises/non-tenders) via enforcement mode.
- System accounting penalties (CBT/tax/floor fees) remain auditable and deterministic; they always post and can increase debt.

Acceptance criteria:
- [x] No known bypass path exists for blocked policy actions.
- [x] Preset behavior matches documented rules and test expectations.
- [x] Policy guardrails are represented in release validation.

### D) CPU Finance AI and Balance

- [x] Complete CPU multi-year budgeting and commitment strategy (contend/balanced/rebuild behavior).
- [x] Improve CPU handling for expensive underperformers, star retention, and FA aggressiveness by strategy.
- [x] Calibrate AI tuning defaults and ranges with multi-season simulation output.
- [x] Add deterministic tests for AI decision boundaries and tuning overrides.

Acceptance criteria:
- [x] CPU teams show distinct, strategy-consistent financial behavior.
- [x] Multi-season sims remain stable under default tuning.
- [x] AI-related regression tests pass in release validation.

### E) UX, Alerts, and Tutorials

- [x] Add commissioner projection preview/reporting surfaces in Financial Settings.
- [x] Add finance alert surfaces for risk/threshold events (cash risk, payroll threshold/floor, arbitration/FA deadlines).
- [x] Ensure owner and commissioner workflows are linear and understandable in UI.
- [x] Update and verify tutorials/guides for all finance workflows and module-level differences.

Acceptance criteria:
- [x] A new user can run a full offseason finance cycle using only in-app guidance.
- [x] Alert messages are actionable and tied to exact next steps.
- [x] Owner and admin documentation is aligned with current UI labels/paths.

### F) QA and Release Gate

- [x] Expand automated test matrix for full finance lifecycle and cross-league isolation.
- [x] Keep `scripts/validate_finance_release.py` as the blocking gate in `scripts/build_release.py`.
- [x] Run strict multi-season stability simulation with agreed thresholds before release.
- [x] Update `release_notes_draft.md` and `release_notes.md` with finance closeout changes.
- [ ] Run installer/update smoke checklist and confirm no regression in upgrade/reinstall flow.

Acceptance criteria:
- [x] Release validation command passes end-to-end without skips.
- [x] Stability guardrails pass in strict mode for release seed/run config.
- [ ] Manual UI/installer checklist is completed and archived with release artifacts.

### Final Go/No-Go

- [ ] All sections A-F completed.
- [ ] No open P0/P1 finance defects.
- [ ] Version bump + installer version sync completed.
- [ ] Release notes finalized and reviewed.
