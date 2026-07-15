# S2-02 — Modern slot-weighted batting order

**Depends on S2-01** (per-hand `_build_lineup` / `hitter_score(pid, *, vs_hand)`), which in turn
depends on S2-06. Implement in that order.

## Objective

`utils/lineup_autofill.py:179-180` orders the batting lineup strictly best-to-worst by a single
`hitter_score`, and OBP is not part of that score at all. Replace the sort with a
slot-specific weighted assignment: leadoff favors OBP/speed, #2 the best overall bat, #3-#4
power, #9 the worst bat with a "second leadoff" speed tilt. The assignment consumes the
platoon-adjusted scores from S2-01 so the vs-LHP and vs-RHP orders each reflect their matchup.

## Acceptance criteria

1. The final sort at `utils/lineup_autofill.py:179-180` is replaced by
   `_assign_batting_order(...)`; personnel selection (coverage ladder, depth chart, DH,
   emergency fills) is byte-identical to S2-01's behavior.
2. On the constructed test roster below: the leadoff hitter's OBP proxy is top-2 in the lineup,
   the cleanup hitter's power proxy is top-2, slot 2 holds the best overall score among players
   not already placed at 2/4 anchors (i.e. the roster's best overall bat), and the lineup's
   worst overall bat hits 8th or 9th.
3. Output is deterministic for a fixed roster (stable tie-breaks; no RNG).
4. Both lineup files still satisfy S2-01's 9-row/coverage invariants (the assignment is a pure
   permutation of the 9 selected `(pid, pos)` pairs).
5. `python -m pytest tests/test_batting_order.py tests/test_lineup_autofill_platoon.py -q` green;
   season harness `--games 162 --strict` stays green (order changes shift some counting stats
   but no gated league-rate KPI depends on order strongly enough to breach tolerance — verify
   by re-run).

## Files to change (verified anchors)

| File | Anchor | Change |
|---|---|---|
| `utils/lineup_autofill.py` | 179-180 (post-S2-01: the `_assign_batting_order` stub inside `_build_lineup`) | real implementation |
| `utils/lineup_autofill.py` | module level, next to `_platoon_adjustment` (~278) | new helpers `_slot_components`, `_assign_batting_order`, weight table |
| `tests/test_batting_order.py` | new | unit tests |

No engine changes: the engine consumes the written file order verbatim
(`physics_sim/team_data.py:101-124 load_lineup` sorts by the `order` column;
`engine.py:3703` bats in list order).

## Exact implementation

All player rating fields verified on `models/player.py:34-42` (`ch, ph, sp, eye, vl, fa, arm`
all present, ints 0-99; `bats` from `utils/player_loader.py:242`).

### 1. Per-player components (new module-level helper)

```python
def _slot_components(player: object, *, vs_hand: str) -> dict[str, float]:
    """Rating-space proxies for batting-slot fit. The platoon shifts reuse the
    engine's _batter_context scales (contact 0.25, power 0.20, eye 0.30 per
    point of vs-hand delta, plus the flat ±2.0 handedness shift) so slotting
    agrees with simulated outcomes."""
    hand = "L" if str(vs_hand or "R").upper().startswith("L") else "R"
    bats = str(getattr(player, "bats", "") or "R").upper()
    if bats == "S":
        h = 0.5
    elif bats == hand:
        h = -1.0
    else:
        h = 1.0
    d = float(getattr(player, "vl", 50) or 50) - 50.0
    if hand != "L":
        d = -0.35 * d                      # PLATOON_RHP_COUNTER_SCALE (S2-06)
    ch = float(getattr(player, "ch", 0)) + 2.0 * h + 0.25 * d
    ph = float(getattr(player, "ph", 0)) + 2.0 * h + 0.20 * d
    eye = float(getattr(player, "eye", 0)) + 2.0 * h + 0.30 * d
    sp = float(getattr(player, "sp", 0))
    return {
        "obp": 0.6 * eye + 0.4 * ch,
        "power": ph,
        "contact": ch,
        "speed": sp,
    }
```

Proxy formulas (decided):
- `obp_proxy = 0.6*eye_adj + 0.4*ch_adj` — walks dominate OBP separation, contact supplies the
  hit component (eye drives BB% in the engine via `_batter_context` eye → chase/whiff).
- `power_proxy = ph_adj` — PH is the engine's direct exit-velo/HR input
  (`bat_speed_power_scale`, config.py:321).
- `contact_proxy = ch_adj`; `speed_proxy = sp` (raw; speed has no platoon component).
- `overall = hitter_score(pid, vs_hand=hand)` — the S2-01 score (offense + speed + defense +
  strategy + platoon), NOT recomputed here.

### 2. Slot weight table (exact; each row sums to 1.00)

Module constant:

```python
_SLOT_WEIGHTS: dict[int, dict[str, float]] = {
    #        overall  obp   power  speed  contact
    1: {"overall": 0.20, "obp": 0.45, "power": 0.05, "speed": 0.25, "contact": 0.05},
    2: {"overall": 0.50, "obp": 0.25, "power": 0.10, "speed": 0.05, "contact": 0.10},
    3: {"overall": 0.35, "obp": 0.15, "power": 0.35, "speed": 0.05, "contact": 0.10},
    4: {"overall": 0.25, "obp": 0.10, "power": 0.55, "speed": 0.00, "contact": 0.10},
    5: {"overall": 0.30, "obp": 0.10, "power": 0.40, "speed": 0.05, "contact": 0.15},
    6: {"overall": 0.60, "obp": 0.10, "power": 0.15, "speed": 0.10, "contact": 0.05},
    7: {"overall": 0.70, "obp": 0.10, "power": 0.10, "speed": 0.05, "contact": 0.05},
    8: {"overall": 0.80, "obp": 0.05, "power": 0.05, "speed": 0.05, "contact": 0.05},
    9: {"overall": 0.55, "obp": 0.05, "power": 0.05, "speed": 0.30, "contact": 0.05},
}
```

Rationale per row (one line each): 1 = on-base + steal threat sets the table; 2 = modern
sabermetric "best hitter bats 2nd" (highest overall weight of the top 5); 3-4 = run producers,
4 maximally power-loaded; 5 = secondary power/contact protection; 6-8 = descending best
remaining bat (overall dominates); 9 = "second leadoff" — this league is DH-only (the autofill
never selects pitchers, lines 63-64/116, and the engine has no pitcher batting), so #9 is the
worst bat but speed-tilted to feed the top of the order.

All five components are on the same 0-99 rating scale (overall = weighted 0-99 ratings plus
small bonuses), so the weights are directly comparable — no normalization pass.

### 3. Assignment algorithm

```python
_SLOT_FILL_ORDER = (2, 4, 1, 3, 5, 6, 7, 8, 9)


def _assign_batting_order(
    selected: list[tuple[str, str]],
    players: dict[str, object],
    *,
    vs_hand: str,
    overall_score,          # callable: (pid) -> float, pass the closure
) -> list[tuple[str, str]]:
    pool = list(selected[:9])
    comps = {
        pid: _slot_components(players.get(pid), vs_hand=vs_hand)
        for pid, _pos in pool
        if players.get(pid) is not None
    }
    overall = {pid: float(overall_score(pid)) for pid, _pos in pool}
    slots: dict[int, tuple[str, str]] = {}
    remaining = list(pool)
    for slot in _SLOT_FILL_ORDER:
        if not remaining:
            break
        weights = _SLOT_WEIGHTS[slot]

        def slot_score(pair: tuple[str, str]) -> tuple[float, float, str]:
            pid = pair[0]
            c = comps.get(pid, {"obp": 0.0, "power": 0.0, "contact": 0.0, "speed": 0.0})
            score = (
                weights["overall"] * overall.get(pid, 0.0)
                + weights["obp"] * c["obp"]
                + weights["power"] * c["power"]
                + weights["speed"] * c["speed"]
                + weights["contact"] * c["contact"]
            )
            # tie-breaks: higher overall, then ascending pid for determinism
            return (score, overall.get(pid, 0.0), _neg_str(pid))

        best = max(remaining, key=slot_score)
        slots[slot] = best
        remaining.remove(best)
    return [slots[i] for i in sorted(slots)]
```

`_neg_str(pid)`: implement the pid tie-break by sorting `remaining` ascending by pid once
before the loop and relying on `max` returning the first maximal element — DECIDED: pre-sort
`remaining = sorted(pool, key=lambda pr: pr[0])` and have `slot_score` return only
`(score, overall)`; Python's `max` keeps the earliest (lowest pid) on full ties. Delete the
`_neg_str` sketch in favor of this.

Fill order `2, 4, 1, 3, 5, 6, 7, 8, 9` (decided): anchor the two highest-leverage identities
first — best overall bat at 2 and the top power bat at 4 — so the leadoff slot's heavy
OBP/speed weights cannot steal the best all-around hitter; then leadoff, then the remaining
run-producer slots, then descending.

Positions ride along untouched: the function permutes `(pid, pos)` pairs; defensive coverage
is fixed by the S2-01 ladder before ordering.

### 4. Call site (inside S2-01's `_build_lineup`)

Replace the stub sort with:

```python
ordered = _assign_batting_order(
    lineup[:9],
    players,
    vs_hand=hand,
    overall_score=lambda pid: hitter_score(pid, vs_hand=hand),
)
```

## Edge cases

- **Fewer than 9 selected** (tiny roster, emergency ladder exhausted): loop fills
  `_SLOT_FILL_ORDER` until `remaining` empties; `sorted(slots)` yields a contiguous-by-slot
  partial order and the writer emits that many rows (same as today's behavior with short
  lineups).
- **Missing player object for a pid** (stale roster row): components default to zeros and
  overall to `hitter_score`'s `-1.0` → the player sinks to slot 8/9 instead of crashing.
- **Missing ratings** (`eye`/`vl` absent on legacy objects): `getattr` defaults (0 / 50) —
  degrades to today's contact/power ordering.
- **Switch hitters**: handled entirely inside `_slot_components` via `h = 0.5`; both hands get
  the same flat shift so a switch hitter's slot changes only via the `d` term.
- **All-identical ratings**: deterministic pid-ascending tie-break; snapshot-stable output.
- **Strategy profiles**: flow in only through `overall` (hitter_score includes
  `_strategy_hitter_bonus`, lines 278-305) — power_offense teams tilt every slot's overall
  component, which is intended; the proxy columns stay profile-neutral.

## Test plan

New file `tests/test_batting_order.py` — pure-function tests on `_assign_batting_order` with a
constructed 9-player dict of `types.SimpleNamespace` (attributes: `ch, ph, sp, eye, vl, fa,
arm, bats`; all `bats="R"`, `vl=50` so platoon terms cancel and `vs_hand="R"` is neutral),
`overall_score` = the documented base formula. Roster (design targets in comments):

| pid | ch | ph | sp | eye | archetype |
|---|---|---|---|---|---|
| OB1 | 78 | 45 | 88 | 92 | leadoff (top OBP+speed, mediocre power) |
| BE2 | 90 | 82 | 60 | 80 | best overall |
| PW4 | 62 | 96 | 30 | 48 | pure slugger |
| PW3 | 70 | 88 | 45 | 60 | second power |
| AV5 | 80 | 70 | 50 | 55 | contact/power blend |
| MD6 | 65 | 60 | 55 | 55 | mid |
| MD7 | 60 | 55 | 50 | 50 | mid-low |
| WK8 | 45 | 40 | 40 | 40 | weak |
| WK9 | 40 | 35 | 75 | 35 | weakest bat, fast |

(`fa=arm=50` for all so defense doesn't reorder overall.)

- `test_leadoff_is_obp_speed` — slot 1 == OB1; assert OB1's obp proxy is top-2 in lineup.
- `test_two_is_best_overall` — slot 2 == BE2.
- `test_cleanup_is_top_power` — slot 4 == PW4; assert slot-4 power proxy is top-2.
- `test_three_five_are_run_producers` — {PW3, AV5} ⊆ slots {3, 5}.
- `test_worst_bat_hits_eighth_or_ninth` — WK8 and WK9 occupy slots {8, 9}, and slot 9 has the
  higher speed of the two (WK9 ninth).
- `test_deterministic_on_ties` — 9 identical players with pids P1..P9 → order P1..P9, twice.
- `test_partial_lineup_short_roster` — 6 pairs in → 6 pairs out, no crash, slots contiguous.
- `test_platoon_shifts_order` — give AV5 `bats="L", vl=20` and OB1 `vl=80`; assert order
  differs between `vs_hand="L"` and `vs_hand="R"`.
- Integration (in `tests/test_lineup_autofill_platoon.py`, extend): after
  `auto_fill_lineup_for_team`, parse `_vs_rhp.csv` and assert row 1's player has top-2 obp
  proxy among the nine (uses the same temp league as S2-01's tests).

Run: `python -m pytest tests/test_batting_order.py tests/test_lineup_autofill_platoon.py -q`
KPI sanity: `python scripts/physics_sim_season_kpis.py --games 162 --seed 1 --strict` and
eyeball `summary["leaders"]["batting"]["obp"]` overlap with top-of-order players.

## Non-goals

- Pitcher batting slots (DH-only league; autofill never selects pitchers — verified lines
  63-64, 116).
- Lineup-vs-specific-starter re-slotting at game time (files are per-hand only).
- Optimizing via run-expectancy simulation or lineup-sim search; the weight table is static.
- Depth-chart-driven batting order (depth chart affects personnel only, per S2-01).
- Rest/fatigue inputs to ordering (S2-05 swaps personnel pre-game in the engine, order slot is
  inherited by the replacement).
