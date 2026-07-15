# S2-13 — Pinch-hitter defensive awareness

Status: spec ready for implementation. Zero open decisions.
Plan reference: `docs/deep_review_plan.md` line 199 (task S2-13). Plan cites
`_select_pinch_hitter` at engine.py:2461-2487 and position inheritance at 2436-2440;
current verified anchors are `_select_pinch_hitter` at engine.py:2468-2494 and the
inheritance in `_apply_substitution` at engine.py:2442-2446.

## Objective

`_select_pinch_hitter` (physics_sim/engine.py:2468-2494) picks the bench bat with the best
`_batter_offense_score` (engine.py:2327-2328) and nothing else. `_apply_substitution`
(engine.py:2429-2465) then hands the PH the vacated fielding position verbatim
(`lineup_state.positions[new_player.player_id] = pos`, lines 2443-2445) — a 1B pinch
hitting for the catcher ends up catching, taking the out-of-position fielding cut
(`_defense_rating_for_pos`, engine.py:2344-2354: `defense_out_of_pos_scale` default 0.75)
for the rest of the game. Add position awareness to PH selection and protect the last
catcher.

## Position-eligibility data source (exact)

`BatterRatings.primary_position: str` and `BatterRatings.other_positions: List[str]`
(physics_sim/models.py:14-15), loaded from the players CSV columns of the same names
(models.py:46-56, uppercased). This is the same source `_select_defensive_replacement`
(engine.py:2385) and `_select_injury_replacement` (engine.py:2727-2731) already use.
Shared helper to add (place right after `_defense_rating_for_pos`, engine.py:2355):

```python
def _can_play(player: BatterRatings, position: str) -> bool:
    pos = (position or "").upper()
    if not pos or pos == "DH":
        return True
    return player.primary_position == pos or pos in player.other_positions


def _catcher_eligible(player: BatterRatings) -> bool:
    return _can_play(player, "C")
```

## Exact implementation — `_select_pinch_hitter` (engine.py:2468-2494)

Replace the candidate scoring block (lines 2486-2494) with:

```python
    candidates = _available_bench(lineup_state)
    if not candidates:
        return None
    vacated_pos = (lineup_state.positions.get(batter.player_id) or "").upper()
    defense_matters = inning >= int(tuning.get("pinch_hit_defense_inning", 7.0))

    # Never burn the last catcher (hard rules, applied before scoring):
    if vacated_pos == "C":
        candidates = [b for b in candidates if _catcher_eligible(b)]
        if not candidates:
            return None
    else:
        c_eligible = [b for b in candidates if _catcher_eligible(b)]
        if len(c_eligible) == 1:
            last_c = c_eligible[0]
            non_burning = [b for b in candidates if b is not last_c]
            if non_burning:
                candidates = non_burning

    oop_penalty = tuning.get("pinch_hit_oop_penalty", 8.0)

    def ph_score(candidate: BatterRatings) -> float:
        score = _batter_offense_score(candidate, pitcher)
        if defense_matters and not _can_play(candidate, vacated_pos):
            score -= oop_penalty
        return score

    current_score = _batter_offense_score(batter, pitcher)
    best = max(candidates, key=ph_score)
    if ph_score(best) - current_score < tuning.get("pinch_hit_advantage_min", 6.0):
        return None
    return best
```

Decided semantics, one-line rationale each:

- **Can cover the vacated position (primary or other_positions, or slot is DH/unknown) →
  no penalty.** Matches the eligibility test the engine already uses for defensive subs
  (engine.py:2385) and injury replacements (engine.py:2730).
- **Cannot cover → flat penalty `pinch_hit_oop_penalty = 8.0` offense-score points, not a
  hard filter.** Rationale for X=8.0: `pinch_hit_advantage_min` is 6.0
  (config.py:407), so a can't-cover bat must out-hit the current batter by **14+** points
  of `contact*0.55 + power*0.45 (+platoon)` — only genuinely elite bats clear it, mirroring
  the severity of the existing out-of-position fielding cut he would then carry
  (`defense_out_of_pos_scale` 0.75 = −25% fielding vs −10% for a secondary position,
  engine.py:2350-2353). A hard filter would strand elite bench bats in NL-style late
  innings; a penalty keeps the trade-off explicit.
- **Adjacent-position shuffle (e.g. PH can play 1B, current 1B slides to C) — NON-GOAL.**
  Decided out of scope: `_apply_substitution` performs single-slot swaps only (engine.py:
  2442-2446); multi-player position rotation is new machinery with its own failure modes
  (cascading eligibility, fielding-line bookkeeping at 2447) and belongs to a follow-up
  task if month-long log audits (acceptance #3) show it's needed.
- **Never-burn-last-catcher (hard rules):**
  - PH **for the catcher slot**: only catcher-eligible candidates; none → no pinch hitter
    (return None). Count basis: the vacated slot is "C" exactly when
    `lineup_state.positions.get(batter.player_id) == "C"`.
  - PH **for any other slot**: if exactly one available bench player is catcher-eligible
    (`len(c_eligible) == 1` among `_available_bench`, engine.py:2331-2332 — bench minus
    `bench_used`), exclude him unless he is the entire bench. The lineup's current
    catcher is untouched by a non-C PH, so bench count is the correct resource measure;
    players already in the lineup are not "burnable" bench resources.
  - If the only bench player left IS the last catcher and the slot is not C: he stays
    reserved only when other candidates exist; when he is the whole bench, PH with him is
    allowed (`non_burning` empty → keep candidates) — decided: an empty-bench team should
    still be able to pinch hit; the alternative (never) strands him in blowouts too.
- **Late-inning defensive weight / interplay with defensive subs (engine.py:2357-2426):**
  the penalty applies only from `pinch_hit_defense_inning = 7.0` (new knob) onward; before
  inning 7 PH choice ignores defense. With defaults this is always active because
  `pinch_hit_inning = 7.0` (config.py:405) already gates PH to inning >= 7 — the separate
  knob exists so tuning experiments that lower `pinch_hit_inning` don't silently drag
  defense weighting into the 5th. Defensive subs (`_maybe_defensive_sub`, engine.py:2395,
  runs at the start of each defensive half-inning >= `defensive_sub_inning` 7.0 when
  leading/tied by <= 2) remain the cleanup mechanism: a penalized-but-chosen PH can still
  be replaced defensively next half-inning if a bench glove with `defensive_sub_fielding_diff
  >= 8.0` gain exists — no code change to that path.

## Config knobs (physics_sim/config.py, insert after `"pinch_hit_advantage_min": 6.0`, line 407)

- ADD `"pinch_hit_oop_penalty": 8.0`.
- ADD `"pinch_hit_defense_inning": 7.0`.
- Existing `pinch_hit_inning` (405), `pinch_hit_close_run_diff` (406),
  `pinch_hit_advantage_min` (407) unchanged.

## Files to change (verified anchors)

1. `physics_sim/engine.py`
   - Add `_can_play` / `_catcher_eligible` helpers after engine.py:2354.
   - Rewrite candidate selection in `_select_pinch_hitter` (engine.py:2486-2494) as above.
     The early gates (lines 2479-2485: inning, `score_diff > close_diff`, 2-out empty
     bases) are unchanged. Note `score_diff` at the call site (engine.py:3712) is
     `offense_score - defense_score`, so trailing teams always pass the gate — unchanged.
   - No change to `_apply_substitution` — the PH still inherits the vacated position;
     the fix is choosing someone who can hold it.
2. `physics_sim/config.py` — two knobs above.

## Acceptance criteria

1. Unit tests below pass; `tests/test_physics_season_smoke.py` unaffected.
2. In a simulated month (existing harness: run `scripts/physics_sim_season_kpis.py` or a
   seeded schedule slice), grep game metadata `substitutions` lists (populated at
   engine.py:2454-2464, role "PH") joined against players CSV: **zero** cases of a PH
   inheriting "C" without catcher eligibility, and out-of-position PH inheritances
   (any position) drop to < 5% of PH events (was: unconstrained).
3. PH frequency does not collapse: PH substitutions per game within ±20% of pre-change
   baseline (the 8.0 penalty prices, not bans, mismatches).

## Test plan (new file `tests/test_pinch_hitter_defense.py`)

Helpers: build `BatterRatings` directly. All non-optional dataclass fields must be passed
(physics_sim/models.py:11-28): `player_id`, `bats`, `primary_position`,
`other_positions`, `contact`, `power`, `gb_tendency`, `pull_tendency`, `vs_left`,
`fielding`, `arm`, `speed`, `eye`, `height`, `durability` (use 50.0 / 72.0 fillers; only
`zone_bottom`/`zone_top` have defaults). Build a
`LineupState` (engine.py:70-78) with a 9-man lineup, `positions` mapping, and a bench;
call `physics_sim.engine._select_pinch_hitter` with `tuning=load_tuning()`, inning=8,
outs=0, `score_diff=0`, empty `BaseState()`, and a generic RHP `PitcherRatings`.

- `test_ph_prefers_position_capable_candidate` — vacated slot "2B"; bench has bat A
  (offense 70, cannot play 2B) and bat B (offense 66, other_positions=["2B"]) →
  B selected (70−8 = 62 < 66).
- `test_elite_bat_overrides_defense_penalty` — same, but bat A offense 80 → A selected
  (80−8 = 72 > 66): penalty prices, doesn't ban.
- `test_no_penalty_for_dh_slot` — vacated slot "DH"; can't-play-anything slugger
  selected with no penalty.
- `test_defense_ignored_before_knob_inning` — set tuning override
  `pinch_hit_inning=5.0`, `pinch_hit_defense_inning=7.0`, inning=5 → penalty not applied
  (bat A from test 1 selected).
- `test_last_catcher_never_burned_for_noncatcher_slot` — vacated slot "1B"; bench =
  [backup catcher (offense 75, primary "C"), corner bat (offense 62, primary "1B")];
  current batter offense 50 → corner bat selected despite lower offense.
- `test_last_catcher_used_when_bench_is_only_him` — vacated slot "1B"; bench = [backup
  catcher, offense 60], batter offense 50 → catcher selected (whole-bench exception);
  with offense 54 → None (advantage_min unmet).
- `test_catcher_slot_requires_catcher_eligible_ph` — vacated slot "C"; bench = [slugger
  offense 80 no C, utility offense 62 with "C" in other_positions] → utility selected;
  bench without any C-eligible → returns None.
- `test_two_catchers_on_bench_allows_burning_one` — vacated slot "1B"; bench has two
  C-eligible bats → the better one is selectable (no protection when a spare exists).

Commands:
```
python -m pytest tests/test_pinch_hitter_defense.py -q
python -m pytest tests/test_physics_season_smoke.py -q
```

## Edge cases

- **Empty bench:** existing guard (engine.py:2487-2488) returns None — unchanged.
- **Injured catcher mid-game:** handled by `_select_injury_replacement`
  (engine.py:2716-2737) which already prefers position-eligible bench players and falls
  back to best-fielding — out of scope; the last-catcher rule here makes that fallback
  less likely to be needed by keeping a C-eligible body on the bench.
- **Batter with no positions entry** (`positions.get` → None, e.g. data gaps or a PH
  hitting for a previous PH whose position was inherited): `vacated_pos == ""` →
  `_can_play` returns True → pure-offense selection, old behavior.
- **Pitcher batting (no-DH configs):** pitchers aren't in `lineup_state.positions` with a
  field position in physics lineups (positions come from lineup CSVs); `vacated_pos` ""
  → no penalty path, unchanged.
- **Extra innings:** no inning upper bound; `pinch_hit_defense_inning` gate satisfied,
  rules apply identically.
- **Bench of only catchers:** vacated "1B", bench = two C-eligible → protection lifts
  (`len(c_eligible) == 1` false), best bat hits.
- **PH for the DH:** vacated "DH" → `_can_play` True for everyone; last-catcher rule for
  non-C slots still protects the lone backup catcher from being burned as a DH bat.

## Non-goals

- **Position shuffling** (moving an incumbent fielder to cover the vacated slot so a
  better bat can PH) — explicitly out of scope, see decision above.
- Double-switches, pitcher pinch-hit logic, pinch-running changes
  (`_select_pinch_runner`, engine.py:2497 untouched).
- Changing `_apply_substitution` position inheritance or fielding-line bookkeeping.
- Defensive-sub tuning (`defensive_sub_*` knobs) and `_maybe_defensive_sub` logic.
- Legacy engine (`playbalance/substitution_manager.py`) PH behavior.
