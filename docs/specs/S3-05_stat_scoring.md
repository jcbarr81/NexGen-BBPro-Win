# S3-05 — Stat-Scoring Fixes (spec)

> Implementation-ready spec. Anchors verified against `main` @ VERSION 7.1.0
> (2026-07-16). Sprint 3 track. Small, targeted scorekeeping corrections with
> boxscore regression tests — no engine-outcome (KPI) impact.

## Objective

Two scorekeeping bugs that misattribute fielding stats:
1. **Strikeouts credit a fielding assist.** A swinging/called third strike runs
   through the fielder-credit path (`engine.py:~1565-1571`,
   `_fielding_line(...).a += 1`), inflating catcher/pitcher assist totals. A
   strikeout is a putout to the catcher (and, by scoring convention, generally
   **no** assist unless it's a dropped-third-strike throw).
2. **Catcher interference isn't charged as an error (E2).** The `interference`
   outcome (`engine.py:~4425`) awards the batter first base but does not charge
   the catcher an error, so team/fielder error totals are short.

## Verified current state

- **Assist path:** `engine.py:1565-1571`
  ```python
  _, assist_fielder = _find_fielder(...)
  if assist_fielder is not None:
      _fielding_line(defense_state, assist_fielder.player_id).a += 1
  ```
  Verify whether the strikeout branch (`engine.py:4458` `line.strikeouts += 1`)
  reaches this assist path — the fix is to ensure it credits a **putout to the
  catcher** and **no assist** on a clean K.
- **Interference:** `engine.py:4425` `elif res.outcome == "interference":` — the
  batter is awarded first; no E2 is recorded. Confirm the exact block and the
  fielder-error recording helper used elsewhere.
- Boxscore assembly + fielding lines: `_fielding_line`, the boxscore/stat
  emission (`engine.py:~1039` maps `strikeouts`→`so`).

## Acceptance criteria

1. A clean strikeout credits a **putout to the catcher** and **zero fielding
   assist** to pitcher/catcher/fielders.
2. Catcher interference on a batter records **E2** (a catcher error) and the
   batter reaches on interference (existing behavior) — CI is charged to the
   catcher's error total and the team error total.
3. Existing boxscore/stat regression tests stay green, and new tests lock in
   both behaviors.
4. No change to game outcomes / league KPI lines (this is scorekeeping only).

## Decisions (no open choices)

- **D1 — Strikeout = PO to catcher, no assist.** In the strikeout branch, credit
  `_fielding_line(defense, catcher).po += 1` and do **not** run the generic
  `_find_fielder` assist credit. (Dropped-third-strike-with-throw is a non-goal;
  a clean K gets PO-only.)
- **D2 — CI = E2.** In the `interference` branch, record a catcher error via the
  same error helper the rest of the engine uses (find it — search `.e += 1` /
  `errors`), attributing to the catcher (position 2), in addition to awarding
  first.

## Files to change

| File | Change |
|---|---|
| `physics_sim/engine.py` | Strikeout branch: PO to catcher, suppress the assist credit. Interference branch: charge E2 to the catcher. |
| `tests/test_stat_scoring.py` (new) | (a) simulate a K → catcher PO +1, no assist deltas; (b) force interference → catcher E2 +1, batter on first. |

## Verification gate

- New unit tests green + existing boxscore regression suite
  (`tests/test_boxscore_html_save.py`, `tests/test_simulation` boxscore paths)
  green. KPI harness unchanged (scorekeeping-only — league lines identical).

## Non-goals

- Full scorer edge cases (fielder's choice attribution, wild-pitch vs passed-ball
  on K+advance, sac-fly RBI nuances). Dropped-third-strike modeling. Rewriting
  the fielding-credit engine — these are two surgical corrections.
