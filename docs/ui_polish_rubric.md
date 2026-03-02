# UI Polish Rubric (v5.2)

Use this rubric for baseline and post-polish scoring on core screens:

- Lineups (`ui/lineup_editor.py`)
- Pitching Staff (`ui/pitching_editor.py`)
- Trades (`ui/trade_dialog.py`)
- Standings (`ui/standings_window.py`)
- Schedule (`ui/schedule_window.py`)

Score each criterion from 1 to 5:

- `1` = Poor (hard to use, unclear, inconsistent).
- `2` = Needs work (several rough edges and readability issues).
- `3` = Acceptable (functional, minor polish gaps remain).
- `4` = Strong (clear and consistent, only minor issues).
- `5` = Ship-ready (high clarity, consistency, and visual quality).

## Criteria

1. Layout density and spacing:
   Controls and content are balanced, not cramped or overly sparse.
2. Typography and readability:
   Headers, body text, tables, and labels are legible at common resolutions.
3. Action clarity and hierarchy:
   Primary and secondary actions are obvious and consistently placed.
4. Theme and visual consistency:
   Color, icon, panel, and spacing usage align with the active design system.
5. State and feedback clarity:
   Loading, empty, warning, error, and success states are understandable.

## Pass Thresholds

- Per-screen average score >= 4.0.
- No individual criterion below 3.
- Cross-screen consistency notes have no unresolved "high" severity issues.

## Baseline Process

1. Run:
   `.\.venv2\Scripts\python.exe scripts\create_ui_polish_baseline.py --touch-placeholders`
2. Capture one screenshot per listed screen and save to the generated
   `screens/` folder.
3. Fill scores/notes in the generated `checklist.md`.
4. Keep the baseline bundle under `reports/ui_polish_baselines/` for later
   before/after comparison.
