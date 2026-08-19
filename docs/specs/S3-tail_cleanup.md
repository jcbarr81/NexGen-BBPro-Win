# S3-tail — Post-PyQt-Retirement Cleanup (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 tail. Small cleanup left over from the PyQt UI
> retirement.

## Objective

Two loose ends from retiring the PyQt `ui/`:
1. **`validate_help_surface.py`** asserts help/tutorial coverage against the
   **retired PyQt files**, so it is permanently red and validates nothing.
   Rewrite it against the **React** help/tutorial surfaces (or retire it).
2. **PyQt-retirement test breakage** — mostly already resolved during the
   2026-07-16 test-hygiene pass; this spec records what remains.

## Verified current state

- `scripts/validate_help_surface.py` — points at PyQt UI files that no longer
  exist. Confirm exactly what it checks (menu/tutorial registration coverage).
- Test status (from the test-hygiene pass, `docs/deep_review_plan.md` change log):
  - `test_admin_tutorials.py` — **removed** (imported the deleted
    `ui._admin_dashboard_legacy`).
  - `test_finance_ledger_usage.py` — **fixed** (lint check scoped to real event
    emission).
  - `test_auto_tune_solver.py` — collection error is the **legacy-engine guard**;
    intentionally excluded from the green gate (`scripts/run_tests_isolated.py`)
    and runnable only under `PB_ALLOW_LEGACY_ENGINE=1`. Leave as-is unless the
    legacy auto-tune tool is revived.
- The green gate is `python scripts/run_tests_isolated.py` (201/201).

## Acceptance criteria

1. `validate_help_surface.py` either (a) validates that every React page/feature
   that should have a tutorial/manual entry has one (driven off `route-index.ts`
   + the React help/tutorial registry), or (b) is deleted if the React help
   system already guarantees coverage another way. No permanently-red script.
2. If rewritten, it passes on the current tree and is wired into CI/the standing
   testing strategy.
3. No open PyQt-retirement test breakage beyond the intentionally-excluded
   `test_auto_tune_solver` (legacy engine).

## Decisions (no open choices)

- **D1 — Rewrite against `route-index.ts` + the React tutorial registry.** The
  React app already derives navigation from `route-index`; the help validator
  should assert each user-facing route with a `helpKey`/tutorial expectation has
  a matching entry, mirroring how QW-07 derived the Command Palette.
- **D2 — Delete if redundant.** If the React help menu is already generated from
  the same registry (so drift is impossible), retire the script instead of
  maintaining a parallel check — and remove it from any CI reference.

## Files to change

| File | Change |
|---|---|
| `scripts/validate_help_surface.py` | Rewrite against React surfaces, or delete. |
| React help/tutorial registry | (If needed) expose the registry the validator reads. |
| CI / standing-testing docs | Update the reference to the script. |

## Verification gate

- The (rewritten) validator passes on the current tree, or is cleanly removed
  with its CI reference. `run_tests_isolated.py` stays 201/201.

## Non-goals

- Writing new tutorials/help content. Reviving the legacy auto-tune tool.
  Broader help-system redesign.
