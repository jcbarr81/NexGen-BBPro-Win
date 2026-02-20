# Financial Backlog (Nice-to-Haves / Suggested Upgrades)

Purpose:
- Capture finance feature ideas while implementation stays checklist-driven.
- Keep non-checklist enhancements visible without mixing them into current scope.

Usage rules:
- Add items here when discovered during checklist execution.
- Do not implement backlog items unless explicitly approved.
- Reference checklist item context when relevant.

## Backlog Items

| ID | Area | Suggestion | Why It Helps | Status |
|---|---|---|---|---|
| FIN-BL-001 | Owner Revenue Realism | Replace schedule/standings attendance proxies with explicit per-game attendance events written during simulation. | Makes gate/concessions calculations truly game-driven and easier to tune. | Open |
| FIN-BL-002 | Owner Expenses Realism | Add travel-distance weighting (road-trip distance/cluster effects) to operations costs. | Improves realism beyond away-game count only. | Open |
| FIN-BL-003 | Finance UX | Add a commissioner finance-alert dashboard card (cash risk, payroll threshold, floor risk, overdue queues). | Reduces hidden risk and improves operational visibility. | Open |
| FIN-BL-004 | Auditability | Add budget-change audit trail rows (who/when/old/new) to finance ledger. | Helps multi-owner governance and post-hoc debugging. | Open |
| FIN-BL-005 | QA Automation | Add integration tests that verify daily/weekly/monthly cadence behavior through `ui/season_progress_window.py` simulation paths. | Guards against regressions between service-level cadence and real sim UI execution. | Open |
| FIN-BL-006 | MLB-Like Economics | Add repeat-offender CBT tiers across consecutive seasons plus optional compensation-pick rules for elite FA departures. | Improves long-horizon MLB-like realism beyond one-season payroll accounting. | Open |
| FIN-BL-007 | Finance Policy UX | Add league-level editable debt-cap controls (instead of preset-fixed caps) with in-dialog policy preview before save. | Lets commissioners tune strictness for custom leagues without code changes. | Open |
