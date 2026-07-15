# S2-03 — Pitch-count-conditional reliever rest (fix inverted rest rule)

Status: spec ready for implementation. Zero open decisions.
Plan reference: `docs/deep_review_plan.md` line 187 (task S2-03), gated by S2-12 (line 198).

## Objective

Today the physics engine blocks **every** non-closer reliever for 2 days after **any** outing
(`reliever_rest_days: 2.0`, `physics_sim/config.py:345`, enforced in `_apply_usage_state`,
`physics_sim/engine.py:456-468`), while closers (`closer_rest_days: 0.0`) get a
consecutive-day gate that with `closer_max_consecutive_days: 1.0` (config.py:353) actually
forbids all back-to-backs. Real bullpens are the opposite: back-to-backs are routine after
short outings; three consecutive days are rare. Replace the flat role-based rest with a
pitch-count-conditional table applied to ALL relievers (CL included), plus a
3-consecutive-day block for ALL relievers.

## The two rest systems — who actually gates what (verified trace)

There are two independent systems. **Do not assume the tracker gates in-game reliever use — it does not.**

1. **Engine path (BINDING for in-game reliever appearances, physics engine):**
   `playbalance/game_runner.py:_run_physics_game` (line 1079) obtains a per-process
   `UsageState` via `_physics_usage_context` (game_runner.py:54-86) and passes it to
   `physics_sim.engine.simulate_game` (call at game_runner.py:1093-1109).
   `simulate_game` calls `usage_state.advance_day` (engine.py:3298) pregame,
   `_build_team_pitching_state` → `_apply_usage_state` (engine.py:885/908/929) sets
   `PitcherState.available`, and `_select_reliever` (engine.py:691-695) filters on
   `pitcher.available and not pitcher.used`. Post-game, `usage_state.record_outing`
   (engine.py:5240-5249) writes back. **This is the only gate that decides whether a
   reliever can appear in a physics game.**

2. **Tracker path (`utils/pitcher_recovery.PitcherRecoveryTracker`, persisted JSON):**
   In the physics path it binds only (a) **starter assignment** (`assign_starter`, called
   from `game_runner.run_single_game:1256-1273`), (b) **pregame bullpen ORDERING** —
   `_apply_bullpen_usage_order` (game_runner.py:249-317) reorders `state.pitchers` from
   `tracker.bullpen_game_status` but never removes anyone, and ordering does not affect
   `_select_reliever`, which takes `max()` over all available candidates, and (c) UI /
   `services/quick_metrics.py` displays. `tracker.record_game` is fed after physics games
   (game_runner.py:1219-1232). `tracker.is_available` (pitcher_recovery.py:910) has **no
   production caller** — only the legacy engine's `substitution_manager` consumes
   tracker-derived `usage_status` maps, and the legacy engine is off behind
   `legacy_guard` (game_runner.py:89-101 resolves to "physics" by default).

**Decision — do NOT delegate engine availability to the tracker.** Rationale (one line
each):
- `simulate_game` has no `team_id`/`players_file`/`roster_dir`, which every tracker call
  requires; threading them through would couple the pure engine to roster CSV loading.
- The engine must also run tracker-less (tests, `scripts/physics_sim_season_kpis.py:526`,
  `tmp/physics_sim_league_run.py:253`), so the engine-side rule must be complete anyway.
- S1-02 made tracker calls cheap, but cheap reads don't fix the layering; instead we make
  **both systems consume one canonical table** so they can never disagree on relievers.

**Unification mechanism (exact):** the canonical pitch-count table lives in
`physics_sim/usage.py` as a module-level function; `utils/pitcher_recovery._rest_days`
imports and delegates to it for reliever roles (utils → physics_sim.usage is safe:
`physics_sim/usage.py` imports only `.config`/`.models`; `physics_sim/__init__.py` already
imports engine → `utils.path_utils`, and `utils/__init__` is inert — import
`from physics_sim.usage import reliever_rest_days` lazily inside the function, matching
the existing lazy-import pattern at pitcher_recovery.py:55-59).

## New rest rule (exact table)

"Off days" = full days with no appearance required before the next appearance.
Engine encoding: a reliever is blocked while `days_since_last_use < off_days + 1`
(so `off_days == 0` permits day N → day N+1 back-to-back but still blocks a same-day
second game, `days_since == 0`).

| Pitches in last outing | Off days required | Eligible again when `days_since >=` |
|---|---|---|
| <= 12 | 0 (back-to-back OK) | 1 |
| 13-25 | 1 | 2 |
| 26-40 | 2 | 3 |
| > 40  | 3 | 4 |

Comparison with `utils/pitcher_recovery._rest_days` (pitcher_recovery.py:39-102): the
tracker's `available_on = date + rest_days` semantics equal "eligible when
`days_since >= rest_days`", i.e. its legacy `<=10 → 1` already means "back-to-back OK
after <=10 pitches". Its legacy curve (<=10→1, <=25→2, <=45→3, <=70→4, <=95→5, else 6) and
V2 curve (10/20/35/50/70/95 → 0..6) both differ from the new table in the reliever range
(e.g. legacy gives 2-off-days for a 20-pitch outing; V2 gives *0 wait* for a 10-pitch
outing, allowing same-day reuse). They stay authoritative for starters only; relievers
delegate to the canonical table (below).

## Files to change (verified anchors)

1. `physics_sim/usage.py`
   - `PitcherWorkload` (lines 10-16): add field `last_pitches: int = 0`.
   - `record_outing` (lines 91-111): after `workload.last_used_day = day` (line 107) add
     `workload.last_pitches = pitches`.
   - New module-level function (place after `BatterWorkload`, before `UsageState`):

     ```python
     def reliever_rest_days(pitches: int, tuning: "TuningConfig | None" = None) -> int:
         """Full off days required after a relief outing of ``pitches`` pitches.

         Canonical table shared by the physics engine (UsageState gating) and
         utils.pitcher_recovery (tracker availability) — S2-03.
         """
         def _knob(name: str, default: float) -> float:
             return tuning.get(name, default) if tuning is not None else default

         if pitches <= int(_knob("reliever_rest_b2b_max_pitches", 12.0)):
             return 0
         if pitches <= int(_knob("reliever_rest_one_day_max_pitches", 25.0)):
             return 1
         if pitches <= int(_knob("reliever_rest_two_day_max_pitches", 40.0)):
             return 2
         return 3
     ```

2. `physics_sim/config.py` — `DEFAULT_TUNING` knob changes (current lines 343-354):
   - REMOVE `"closer_rest_days": 0.0` (line 344) — subsumed by the table.
   - REMOVE `"reliever_rest_days": 2.0` (line 345) — subsumed by the table.
   - ADD `"reliever_rest_b2b_max_pitches": 12.0`.
   - ADD `"reliever_rest_one_day_max_pitches": 25.0`.
   - ADD `"reliever_rest_two_day_max_pitches": 40.0`.
   - RENAME `"closer_max_consecutive_days": 1.0` (line 353) →
     `"reliever_max_consecutive_days": 2.0` (2 = may pitch two straight days, third
     consecutive day blocked). Applies to ALL bullpen roles now (rationale: real 3-peats
     are rare; 2 matches the tracker's `forbidThirdConsecutiveDay` gate at
     pitcher_recovery.py:985).
   - KEEP `"closer_availability_ratio": 1.3` (line 346), `"short_rest_penalty": 0.35`
     (line 347), `"closer_max_appearances_ratio": 0.45` (line 354), `"starter_rest_days":
     4.0` (line 343) unchanged.
   - Grep check for the implementer: `closer_max_consecutive_days` and
     `reliever_rest_days`/`closer_rest_days` appear only in `physics_sim/engine.py` and
     `physics_sim/config.py` (verified via grep); update both, no other call sites.

3. `physics_sim/engine.py`
   - `_rest_days_for_role` (lines 256-262): reduce to starters only —

     ```python
     def _rest_days_for_role(role: str, tuning: TuningConfig) -> int:
         role = (role or "").upper()
         if role.startswith("SP"):
             return int(tuning.get("starter_rest_days", 4.0))
         return 0  # relievers use the pitch-count table (S2-03)
     ```

   - `_pitcher_is_rested` (lines 279-292, used by `_order_pitchers_for_game` for the
     rotation AND for LR-as-emergency-starter at line 381): for non-SP roles compute the
     requirement from the table:

     ```python
     def _pitcher_is_rested(*, pitcher_id, role, usage_state, game_day, tuning) -> bool:
         days_since = _pitcher_days_since_use(
             pitcher_id, usage_state=usage_state, game_day=game_day
         )
         if days_since is None:
             return True
         role_u = (role or "").upper()
         if role_u.startswith("SP"):
             return days_since >= _rest_days_for_role(role_u, tuning)
         workload = usage_state.workload_for(pitcher_id)
         required = reliever_rest_days(workload.last_pitches, tuning) + 1
         return days_since >= required
     ```

     (import `reliever_rest_days` alongside `UsageState` at engine.py:33:
     `from .usage import UsageState, reliever_rest_days`.)
   - `_apply_usage_state` (lines 451-479) — replace the rest/consecutive blocks exactly:

     ```python
     rest_role = state.rest_role or state.staff_role
     availability_ratio = 1.0
     if rest_role == "CL":
         availability_ratio = tuning.get("closer_availability_ratio", 1.3)
     state.available = ratio <= availability_ratio
     is_starter = rest_role.upper().startswith("SP")
     if is_starter:
         required_days = _rest_days_for_role(rest_role, tuning)
     else:
         required_days = reliever_rest_days(workload.last_pitches, tuning) + 1
     if required_days > 0 and workload.last_used_day is not None:
         days_since = game_day - workload.last_used_day
         if days_since < required_days:
             state.available = False
             rest_penalty = tuning.get("short_rest_penalty", 0.35)
             rest_deficit = required_days - days_since
             scaled = rest_penalty * (rest_deficit / max(1.0, float(required_days)))
             state.pregame_penalty = max(state.pregame_penalty, scaled)
     if not is_starter:
         max_consecutive = int(tuning.get("reliever_max_consecutive_days", 2.0))
         if max_consecutive > 0 and workload.last_used_day is not None:
             if game_day - workload.last_used_day == 1:
                 if workload.consecutive_days_used >= max_consecutive:
                     state.available = False
     if rest_role == "CL":
         max_ratio = float(tuning.get("closer_max_appearances_ratio", 0.0))
         if max_ratio > 0.0:
             max_apps = max(1, int((game_day + 1) * max_ratio))
             if workload.appearances >= max_apps:
                 state.available = False
     ```

     Notes: the `game_day is not None` re-checks inside the old block (lines 457-458,
     472, 476) are redundant — the function already returns at line 436-437 when
     `game_day is None`; drop them. `workload.consecutive_days_used` is maintained by
     `UsageState.record_outing` (usage.py:103-106) and reset by `advance_day`
     (usage.py:70-71) — no new tracking structure needed; this generalizes the existing
     closer mechanism to the whole bullpen.

4. `utils/pitcher_recovery.py`
   - `_rest_days` (lines 38-102): add a role parameter and delegate for relievers.
     Change signature to `def _rest_days(pitches: int, role: str = "SP") -> int:`
     (lru_cache now keys on `(pitches, role)` — fine, both hashable). Insert immediately
     after the `pitches <= 0` early return (line 52-53):

     ```python
     if role in {"LR", "MR", "SU", "CL"}:
         # Canonical reliever table shared with the physics engine (S2-03).
         from physics_sim.usage import reliever_rest_days

         return reliever_rest_days(pitches) + 1
     ```

     (`+1` converts off-days to the tracker's `available_on = date + N` /
     "eligible when days_since >= N" semantics, preserving b2b for <=12-pitch outings.)
     The SP path (V2 thresholds + legacy curve) is unchanged.
   - Call sites to pass the role (all already compute `role` before calling):
     - `record_game` line 742: `rest_days = _rest_days(pitches, role)`.
     - `record_warmups` line 845: `rest_days = _rest_days(rest_basis, role_token)` — the
       existing `min(rest_days, 1)` clamp at 846-847 stays.
     - `apply_penalties` line 885: `rest_days = _rest_days(int(tax or 0), role)`.

## How UsageState and PitcherRecoveryTracker stay consistent

- Same table, one source (`physics_sim.usage.reliever_rest_days`), so a 20-pitch outing
  yields "eligible in 2 days" in both the in-game gate and the tracker's `available_on`
  used by pregame ordering, quick metrics, and `scripts/usage_calibration.py`.
- Consecutive-day rule: engine blocks the 3rd straight day via
  `reliever_max_consecutive_days=2`; tracker blocks it via `forbidThirdConsecutiveDay`
  (pitcher_recovery.py:985, PBINI default 1) — semantically identical (`consec >= 2` →
  blocked). No PBINI change required.
- The tracker remains authoritative for starter rotation only; the engine remains
  authoritative for in-game appearances. Divergence is limited to tracker-only concepts
  (warmup tax, pitch budgets), which affect ordering/UI, never engine availability.

## Acceptance criteria

1. S2-12 usage gates (deep_review_plan.md:187,198), measured over a full simulated season
   via `scripts/physics_sim_season_kpis.py`:
   - Reliever appearance leaders reach **75-80 G** (today ~54).
   - Back-to-back appearances become routine: **10-20% of reliever appearances** follow an
     appearance the previous day (short outings only); 3-consecutive-day streaks = **0**.
   - Role distribution tracks `data/MLB_avg/role_averages_mlbstats_2020_2024.csv`
     (formal KPI wiring is S2-12's deliverable, not this task's).
2. All unit tests below pass; existing `tests/test_physics_sim_usage.py` still passes
   (its three tests don't touch the removed knobs — verified).
3. `_pitcher_usage_summary` output (engine.py:415-427) unchanged in shape (no schema
   change to `pitcher_usage` metadata).

## Test plan (new file `tests/test_reliever_rest.py`)

Build states directly: construct `PitcherRatings` via the `_pitcher()` helper pattern from
`tests/test_physics_sim_usage.py:7-24`, a `UsageState` with forced
`workload_for(pid)` fields (`last_used_day`, `last_pitches`, `consecutive_days_used`,
`last_update_day`), then call `physics_sim.engine._apply_usage_state` on a `PitcherState`
with `rest_role`/`staff_role` set and assert `state.available`.

- `test_b2b_allowed_after_short_outing` — MR, 12 pitches on day 0 → available day 1.
- `test_same_day_reuse_blocked` — MR, 12 pitches on day 0 → unavailable day 0.
- `test_one_off_day_after_medium_outing` — MR, 20 pitches day 0 → unavailable day 1,
  available day 2.
- `test_two_off_days_after_long_outing` — LR, 35 pitches day 0 → unavailable days 1-2,
  available day 3.
- `test_three_off_days_after_forty_plus_pitches` — LR, 55 pitches day 0 → unavailable
  days 1-3, available day 4.
- `test_third_consecutive_day_blocked_for_all_relievers` — MR with
  `last_used_day=1, consecutive_days_used=2, last_pitches=8` → unavailable on day 2;
  available on day 3 after `advance_day` resets the streak (drive it via two
  `record_outing` calls on days 0 and 1, then `advance_day(day=2)` and `advance_day(day=3)`).
- `test_closer_back_to_back_now_allowed` — CL, 10 pitches day 0,
  `consecutive_days_used=1` → available day 1 (regression: old
  `closer_max_consecutive_days=1` blocked this).
- `test_closer_appearance_cap_still_enforced` — CL with `appearances` above
  `closer_max_appearances_ratio * (game_day+1)` → unavailable.
- `test_tracker_reliever_table_matches_engine` — for pitches in
  `(1, 12, 13, 25, 26, 40, 41, 80)` assert
  `utils.pitcher_recovery._rest_days(p, "MR") == physics_sim.usage.reliever_rest_days(p) + 1`
  (clear the lru_cache first: `_rest_days.cache_clear()`).
- `test_starter_rest_unchanged` — SP1 used day 0 → `_pitcher_is_rested` False on day 3,
  True on day 4 (`starter_rest_days=4`).

Commands:
```
python -m pytest tests/test_reliever_rest.py -q
python -m pytest tests/test_physics_sim_usage.py tests/test_physics_season_smoke.py -q
```

## Edge cases

- **Season start / unknown pitcher:** `last_used_day is None` → available (both systems).
- **No usage tracking (exhibition, `usage_state=None`):** `_apply_usage_state` returns at
  engine.py:436-437 → everyone available, unchanged.
- **`last_pitches` default 0:** a pitcher with `last_used_day` set but `last_pitches==0`
  (stale pre-migration UsageState is impossible — UsageState is per-process and rebuilt on
  restart, game_runner.py:69-82 — but defensive anyway) → table returns 0 off days →
  required `days_since >= 1`, harmless.
- **Doubleheaders:** same `game_day` for both games → `days_since == 0 < 1` → a reliever
  who threw in game 1 sits game 2 (matches `used` semantics within a single game).
- **Fatigue-debt availability** (`ratio <= availability_ratio`, engine.py:452-455) still
  applies on top of the table: a reliever with 0 off-days required can still be blocked by
  accumulated debt — intended, keeps workload realistic across dense stretches.
- **Injured relievers:** in-game injury sets `pitcher_state.available = False`
  (engine.py:2931); roster removal is handled outside the engine — untouched.

## Non-goals

- No change to starter rest (`starter_rest_days`, tracker V2/legacy SP curves).
- No change to warmup tax, pitch budgets, or `enableUsageModelV2` PBINI thresholds.
- No persistence of UsageState across process restarts (existing behavior).
- No S2-12 KPI harness work (separate task; this spec only defines the numbers it gates).
- No change to the legacy engine's `substitution_manager` caps.
