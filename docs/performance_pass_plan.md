# Performance Pass Plan: Auto-Assign + League Creation

## Objective
Reduce total runtime and perceived UI latency for:
- `auto_assign_all_teams` (Auto Reassign All Rosters)
- `create_league` (new league creation flow)

Keep scope locked to these two workflows until targets are met.

## Scope
- In scope:
  - End-to-end runtime for both workflows
  - Internal step timing to find hotspots
  - Safe optimizations (I/O reduction, batching, cache-aware flow)
  - Progress UX improvements (phase + elapsed messaging)
- Out of scope:
  - New product features
  - Non-related UI redesign
  - Broad simulation-engine optimization

## Success Criteria (Definition of Done)
- `auto_assign_all_teams` runtime reduced by at least 40% against baseline on the same dataset.
- `create_league` runtime materially reduced against baseline at both:
  - Typical league size (project default setup)
  - Max league size (40 teams)
- UI remains responsive during both operations.
- No functional regressions in:
  - roster validity
  - required position coverage checks
  - generated league integrity (teams/players/rosters)

## Work Plan

## Phase 1: Baseline & Instrumentation
- Add/confirm benchmark harness for both workflows.
- Capture step timings:
  - data load
  - processing/assignment/generation
  - persistence writes
  - post-validation
- Save baseline report (CSV/JSON) for comparison.

## Phase 2: Hotspot Analysis
- Identify highest-cost steps from baseline.
- Classify cost drivers:
  - repeated CSV reads
  - repeated cache invalidation/reload
  - write amplification
  - avoidable per-team recomputation

## Phase 3: Optimization Pass
- Implement targeted improvements only for measured hotspots.
- Preferred techniques:
  - one-pass in-memory maps reused across teams
  - batched writes where safe
  - defer expensive validations to one final pass
  - avoid redundant disk reloads in loops

## Phase 4: UX Feedback
- Keep work async/background.
- Show progress dialog phases:
  - Loading
  - Processing
  - Saving
  - Validating
- Include elapsed time and completion status.

## Phase 5: Validation & Guardrails
- Re-run benchmark harness and compare against baseline.
- Run targeted pytest for impacted modules.
- Add lightweight regression guardrails:
  - benchmark script retained in repo
  - optional release validation check for major perf regressions

## Tracking Checklist
- [x] Baseline report captured for both workflows
- [x] Top 3 hotspots identified with measured impact
- [x] Optimization patch 1 implemented and measured
- [x] Optimization patch 2 implemented and measured
- [x] UX progress phases added/verified
- [x] Regression tests green
- [x] Post-optimization benchmark report captured
- [x] Checklist sign-off with before/after numbers

## Commands (Execution)
- Build/release context:
  - `.\.venv2\Scripts\python.exe scripts\build_release.py --clean`
- Targeted tests:
  - `.\.venv2\Scripts\python.exe -m pytest <targeted_tests>`

## Change Control
- Do not add unrelated features while this plan is active.
- Every optimization change must reference measured hotspot evidence.
- If a proposed change does not move measured runtime, drop it.

## Benchmarks (Captured)
- Baseline run:
  - `reports/performance/workflow_benchmark_20260221_205733/workflow_summary.json`
  - `create_league`: typical 26.645s, max_40 71.951s
  - `auto_assign_all_teams`: typical 3.344s, max_40 3.347s
- Post-optimization run:
  - `reports/performance/workflow_benchmark_20260221_211227/workflow_summary.json`
  - `create_league`: typical 4.317s, max_40 12.749s
  - `auto_assign_all_teams`: typical 0.180s, max_40 0.172s

## Measured Hotspots Addressed
- Hotspot 1: repeated path root probing in `utils/path_utils.get_data_root/get_data_dir`.
  - Fix: cache data-root/data-dir resolution by runtime context.
- Hotspot 2: per-team/per-player repeated age and player-load work in auto-assign.
  - Fix: pre-load player map once, resolve sim date once, and reuse age cache for sort keys.

## Final Sign-Off
- `auto_assign_all_teams`:
  - Typical: `3.344s -> 0.180s` (`94.6%` faster)
  - Max-40: `3.347s -> 0.172s` (`94.9%` faster)
- `create_league`:
  - Typical: `26.645s -> 4.317s` (`83.8%` faster)
  - Max-40: `71.951s -> 12.749s` (`82.3%` faster)
- UX progress feedback delivered for both workflows with phase + elapsed time messaging.
- Regression checks run for impacted modules and passing.
- Status: Closed.
