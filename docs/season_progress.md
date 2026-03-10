# Season Progress

The Season Progress window controls the flow of the league through its phases
and provides quick 'simulate to' actions for major milestones.

- The window includes a single Season Timeline list for milestone visibility
  without a separate timeline feed panel.

- Current phases: PRESEASON -> REGULAR_SEASON -> AMATEUR_DRAFT -> PLAYOFFS -> OFFSEASON.
- The big action button adapts to context:
  - Simulate to Midseason: available during the first half of the regular season.
  - Simulate to Draft: after midseason and before Draft Day (third Tuesday in July).
  - Simulate to Playoffs: after Draft Day or once the regular season is near completion.

Amateur Draft
- On Draft Day, the simulator switches to the Amateur Draft phase and opens the
  Draft Console. Simulation is paused until draft results are committed, after
  which the phase returns to REGULAR_SEASON.
- Draft artifacts are saved to `data/`:
  - `draft_pool_<year>.csv` / `draft_pool_<year>.json`
  - `draft_state_<year>.json`
  - `draft_results_<year>.csv`
  - Completion tracking in `season_progress.json` under `draft_completed_years`

Tip: Use a non-empty seed in Draft Settings for reproducible pools and order.
