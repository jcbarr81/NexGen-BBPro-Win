# 5.2.0 (Draft) - 2026-03-02

- Closed `V5.2-21` release gates and finalized milestone sign-off for `v5.2` (targeted pytest suite, multi-league smoke validation, help-surface validation, and archived UI/installer checklist artifact).
- Updated `reports/release_validation/v5_2_21_gate_summary.md` with the latest gate run details and archived checklist path.
- Marked all `v5.2` subtasks complete in `docs/future_work.md` and advanced the implementation queue to `V5.3-01`.
- Bumped app version to `5.2.0` and synchronized installer `AppVersion` to `5.2.0`.

# 5.1.28 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-10` by expanding League Command Center deadline and finance-risk card behavior.
- Updated `services/league_command_center.py` to track richer deadline statuses (trade deadline windows, draft timing, offseason workflow tasks, arbitration/free-agency workload) and add stronger finance-card actions.
- Updated `ui/league_command_center_window.py` card-row formatting so deadline rows and finance alerts render clear status/context and explicit next-step guidance.
- Expanded targeted coverage in `tests/test_league_command_center.py` and `tests/test_league_command_center_window.py` for new deadline semantics, finance actions, and detailed item-row formatting.

# 5.1.27 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-09` by polishing Command Center card behavior for injuries, approvals, and roster conflicts in `ui/league_command_center_window.py`.
- Added card-aware detail formatting and per-card suggested-action buttons that resolve to available owner/admin handlers when present.
- Added fallback-safe action resolution for key workflows (`Open Injury Center`, `Review Pending Trades`, `Review Change Requests`, `Run Auto-Reassign`, and related command-center actions).
- Expanded coverage in `tests/test_league_command_center_window.py` to validate command-center action handler resolution.

# 5.1.26 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-08` by adding a League Command Center UI shell in `ui/league_command_center_window.py`.
- Added owner/admin navigation entry points for League Command Center from League Hub, dashboard quick actions, Owner Tools, Admin Season page, and Admin Home shortcuts.
- Added owner and admin command-center tutorial entries so the new workflow is discoverable from in-app Tutorials menus.
- Added targeted coverage in `tests/test_league_command_center_window.py` for command-center snapshot rendering state and item formatting.

# 5.1.25 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-06` with a schedule-window polish pass in `ui/schedule_window.py`.
- Added grouped schedule status/actions sections with explicit refresh control and last-updated feedback.
- Improved schedule table readability defaults while preserving existing row data and box score open-on-double-click behavior.
- Added safer loading/refresh helpers for schedule data and fallback-safe optional UI calls for lightweight test stubs.

# 5.1.24 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-05` with a standings-window polish pass in `ui/standings_window.py`.
- Added a **Standings Snapshot** status panel and **Actions** group with explicit refresh control and last-updated timestamp.
- Improved standings window readability/layout sizing while keeping the existing detailed standings table format intact.
- Hardened standings auto-refresh scheduling and lightweight test-stub compatibility for optional UI methods.

# 5.1.23 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-04` with a trade-window polish pass in `ui/trade_dialog.py`.
- Reorganized Trade Center UI into clearer grouped sections for setup, assets, offer review, and actions in both **New Trade** and **Incoming** tabs.
- Added live Trade Center status and incoming-offer counters so owners can quickly see trading state and pending offer volume.
- Added incoming-tab action-state handling (disabled accept/reject when no offer selected), plus a dedicated **Clear Selection** action for new trade composition.

# 5.1.22 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-03` with a pitching-staff window polish pass in `ui/pitching_editor.py`.
- Reorganized Pitching Staff Editor into clearer grouped sections (status, role assignments, actions) with improved spacing and action hierarchy.
- Added live staff health feedback (`Filled` and `Duplicates`) so assignment completeness/errors are visible while editing.
- Added robust `QTimer` fallback handling for lightweight Qt test stubs in `ui/pitching_editor.py`, `ui/reassign_players_dialog.py`, `ui/trade_dialog.py`, and `ui/transactions_window.py`.

# 5.1.21 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-02` with a lineup-window polish pass in `ui/lineup_editor.py`.
- Reorganized Lineup Editor UI into clearer grouped sections (view/status, batting order, bench, actions, auto-fill reasons) and improved action hierarchy.
- Added live lineup health feedback (`Filled` and `Duplicates`) to reduce lineup editing errors during manual setup.
- Added robust fallback handling for lightweight Qt test stubs when `QTimer` is unavailable.

# 5.1.20 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-19` by adding Career Arc analytics v1 outputs for year-over-year, trendline, and team-era comparisons.
- Added `services/career_arc_analytics.py` to compute archive-driven analytics from season standings and champions metadata.
- Updated `services/report_exporter.py` to include `career_arc_yoy.csv`, `career_arc_trends.csv`, and `career_arc_team_eras.csv` in standard report exports.
- Added targeted tests in `tests/test_career_arc_analytics.py` and expanded export coverage in `tests/test_report_exporter.py`.

# 5.1.19 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-18` by wiring team strategy profiles into auto-assign and automation valuation paths.
- Updated `services/roster_auto_assign.py` so `auto_assign_all_teams` resolves each team profile once and passes it into both roster assignment and lineup auto-fill.
- Updated roster sort/scoring hooks to apply strategy-aware bonuses for active/prospect placement while keeping `balanced` as a no-op baseline.
- Fixed strategy profile resolution path handling by importing `Path` in `services/roster_auto_assign.py`.
- Expanded targeted coverage in `tests/test_roster_auto_assign.py` and `tests/test_decision_explanations.py` for strategy propagation and lineup explanation payload tags/context.

# 5.1.18 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-17` by adding team strategy profile domain persistence and settings UI for commissioner/owner workflows.
- Added `services/team_strategy_profiles.py` with league-scoped default strategy, per-team overrides, resolved profile metadata, and finance-profile mapping helpers.
- Added `ui/team_strategy_settings_dialog.py` and wired **League Settings -> Team Strategy Profiles** in the admin dashboard.
- Updated `ui/team_settings_dialog.py` and `ui/owner_dashboard.py` so owners can choose **Use League Default** or set a team strategy override from Team Settings.
- Updated `services/finance_ai.py` to respect explicit strategy profile settings while preserving legacy behavior when no explicit strategy configuration is provided.
- Added targeted coverage in `tests/test_team_strategy_profiles.py`, `tests/test_team_strategy_settings_dialog.py`, and `tests/test_finance_ai.py`.

# 5.1.17 (Draft) - 2026-03-02

- Completed roadmap subtask `V5.2-16` by adding scouting budget tuning persistence and UI controls across commissioner and owner workflows.
- Expanded `services/scouting_service.py` with persisted commissioner tuning values (including passive gain, bank cap, and auto-spend cap), plus team-level scouting intensity save/load APIs for owner control.
- Updated `ui/financial_settings_dialog.py` with a new **Scouting Fog-of-War Tuning** section so commissioners can tune scouting pace while finance is on or off.
- Updated `ui/owner_finance_page.py` with a new **Scouting Controls** card showing confidence/error status and allowing owners to save Low/Normal/High scouting intensity.
- Updated the owner **Finance Hub Overview** tutorial (`ui/owner_dashboard.py`) to cover scouting intensity controls and commissioner scouting tuning.
- Added/updated targeted tests in `tests/test_scouting_service.py`, `tests/test_financial_settings_dialog.py`, and `tests/test_owner_finance_page.py`; targeted suite passed.

# 5.1.16 (Draft) - 2026-03-02

- Added a new league-scoped scouting fog-of-war engine in `services/scouting_service.py` with commissioner-controlled enablement, persistent team scouting state, deterministic observed ratings, and monthly confidence progression that works with finance on or off.
- Updated scouting display integration in `services/finance_budget_effects.py` so player profile scouting confidence/range now flows through the new scouting system while preserving true-rating internals.
- Added a commissioner toggle to `ui/financial_settings_dialog.py` (`Enable Scouting Fog-of-War`) so existing leagues remain disabled by default until explicitly enabled.
- Added targeted regression coverage in `tests/test_scouting_service.py` and updated scouting budget effect tests in `tests/test_finance_budget_effects.py`.
- Marked roadmap subtask `V5.2-15` complete in `docs/future_work.md`.

# 5.1.15 (Draft) - 2026-03-01

- Added trade decision rationale panels in both owner and commissioner trade workflows (`ui/trade_dialog.py`, `ui/admin_dashboard/actions/trades.py`) so rejected/blocked/cancelled decisions show explicit AI/user reason tags and messages in the UI.
- Added targeted trade-response summary coverage in `tests/test_decision_explanations.py`.
- Marked roadmap subtask `V5.2-14` complete in `docs/future_work.md`.

# 5.1.14 (Draft) - 2026-03-01

- Added bullpen-usage explanation summaries to game metadata in `playbalance/game_runner.py` so simulation results carry AI rationale for reliever ordering decisions.
- Updated `ui/season_progress_window.py` to display a live "Bullpen Usage Reasons" status line sourced from recent simulated games.
- Added coverage for bullpen reason metadata extraction in `tests/test_decision_explanations.py` and marked roadmap subtask `V5.2-13` complete in `docs/future_work.md`.

# 5.1.13 (Draft) - 2026-03-01

- Added `summarize_decision_explanation` in `services/decision_explanations.py` to render AI decision payloads into compact user-facing reason summaries.
- Updated `ui/lineup_editor.py` to surface Auto-Fill decision rationale in a new "Auto-Fill Decision Reasons" panel after running lineup auto-fill.
- Added formatter coverage in `tests/test_decision_explanations.py` and marked roadmap subtask `V5.2-12` complete in `docs/future_work.md`.

# 5.1.12 (Draft) - 2026-03-01

- Added services/league_command_center.py as the v5.2 Command Center data contract/service layer with normalized card payloads for injuries, pending approvals, roster conflicts, deadlines, and finance risks.
- Added targeted coverage in tests/test_league_command_center.py and marked roadmap subtask V5.2-07 complete in docs/future_work.md.

# 5.1.11 (Draft) - 2026-03-01

- Added a shared AI decision explanation schema in services/decision_explanations.py (reason tags, context payload, actor/team/subject metadata, and optional JSONL persistence via NEXGEN_DECISION_LOG).
- Integrated explanation payload emission for lineup autofill (utils/lineup_autofill.py), bullpen ordering (playbalance/game_runner.py), and owner/commissioner trade responses (ui/trade_dialog.py, ui/admin_dashboard/actions/trades.py).
- Added targeted tests in tests/test_decision_explanations.py and marked roadmap subtask V5.2-11 complete in docs/future_work.md.

# 5.1.10 (Draft) - 2026-03-01

- Added scripts/create_ui_polish_baseline.py to scaffold v5.2 UI polish baseline bundles (checklist + JSON index + optional screenshot placeholders) for core screens: Lineups, Pitching, Trades, Standings, and Schedule.
- Added docs/ui_polish_rubric.md with standardized scoring criteria and pass thresholds for ship-readiness evaluations.
- Updated roadmap tracking in docs/future_work.md: marked V5.2-01 complete and advanced the implementation queue to V5.2-11.

# 5.1.9 (Draft) - 2026-02-27

- Added an Auto-Reassign Team button to the Owner Reassign Players dialog so owners can run policy-based ACT/AAA/LOW assignment directly from that workflow.
- After auto-reassign, the dialog now reloads roster levels in-place, refreshes counts, clears recovery state, and reports coverage warnings when applicable.





