# S2-06 — Load pitcher `throws` properly; symmetric platoon adjustment

**Do this task FIRST in the S2 lineup cluster. S2-01, S2-02, S2-05 build on it.**

## Objective

`physics_sim.models.PitcherRatings` has no `throws` field, so every piece of platoon logic in
the physics engine uses the pitcher's *batting* side (`pitcher.bats`) as his throwing hand.
Additionally `_platoon_bonus` and `_batter_context` apply the batter's `vs_left` rating only
when the pitcher is left-handed, so there is zero platoon adjustment vs RHP.

This task: (1) load `throws` from `players.csv` into `PitcherRatings` (with the same
bats-fallback rule `utils/player_loader.py:242-250` uses for pre-6.10.12 CSVs), (2) replace every
pitcher-hand-from-`bats` proxy in `physics_sim` with `throws`, (3) make the `vs_left`-based platoon
adjustment symmetric so batters get a signed adjustment vs BOTH hands.

**Parity note (accepted):** this changes sim results. This is a realism change; acceptance is a
KPI re-run (`python scripts/physics_sim_season_kpis.py --games 162 --strict`), NOT byte parity.

## Acceptance criteria

1. `PitcherRatings.from_row` populates `throws` from the CSV `throws` column; when the column is
   missing/empty it falls back to `bats` ("R" when `bats == "S"`).
2. No remaining use of a pitcher object's `.bats` as a throwing hand anywhere in `physics_sim/`
   (`grep -n "\.bats" physics_sim/*.py` shows only batter-side uses; the exhaustive site list
   below is empty of pitcher uses).
3. `_platoon_bonus` and `_batter_context` produce non-zero, sign-flipped adjustments vs both
   hands for a batter with `vs_left != 50` (unit-tested).
4. Data audit passes: every `is_pitcher` row in the active league's `data/players.csv` has a
   non-empty `throws` in {L, R} (command below; fallback covers legacy CSVs so this is
   informational, not a hard gate).
5. Full KPI harness re-run stays within existing tolerances (`--strict` exits 0). If the new
   S2-01 platoon-gap KPI exists already, it lands in its 20-32 wOBA-point band; if it drifts
   out, tune `handedness_contact_bonus` / `handedness_power_bonus` / `handedness_eye_bonus`
   (all currently 2.0, `physics_sim/config.py:430-432`) up/down together in 0.5 steps.

## Files to change (verified anchors, current `main`)

| File | Anchor | Change |
|---|---|---|
| `physics_sim/models.py` | 74-89 (`PitcherRatings` fields), 91-116 (`from_row`) | add `throws` field + parsing |
| `physics_sim/engine.py` | 667 | `_matchup_score`: pitcher hand from `throws` |
| `physics_sim/engine.py` | 2321-2324 | `_platoon_bonus`: symmetric formula |
| `physics_sim/engine.py` | 2975-3010 (`_batter_context`; hand at 2978, platoon block 2987-2993) | hand from `throws`; unconditional signed `vs_left` term |
| `physics_sim/engine.py` | 3013-3017 (`_lineup_hand_from_starter`) | use `starter.throws` |
| `physics_sim/engine.py` | 3839, 3865 | `_effective_batter_side(batter.bats, pitcher_state.pitcher.throws)` |
| `physics_sim/engine.py` | 3965 (`"hand": pitcher_state.pitcher.bats`) | `pitcher_state.pitcher.throws` |
| `physics_sim/engine.py` | 4338 | `pitcher_hand = (pitcher.throws or "R").upper()` |
| `physics_sim/engine.py` | 4548, 4578 | `_effective_batter_side(batter.bats, pitcher.throws)` |
| `tests/test_physics_sim_usage.py` | 8-24 (`_pitcher` helper) | add `throws="R"` kwarg |
| `tests/test_pitcher_throws.py` | new | unit tests |

**Do NOT touch** (these are batter batting-side uses, correct as-is): `engine.py:670, 2979,
4337`; first argument of `_effective_batter_side` at 3839/3865/4548/4578; `physics.py:54-59,
578-587` (reads the `"hand"` dict key fed from engine.py:3965 — fixed transitively);
`playbalance/game_runner.py:1285` (already prefers `getattr(pitcher, "throws", ...)` on the
utils `Player` object, which has had `throws` since 6.10.12).

## Exact implementation

### 1. `physics_sim/models.py`

Add the field immediately after `bats` (both fields are non-default, so ordering is legal):

```python
@dataclass
class PitcherRatings:
    player_id: str
    bats: str
    throws: str          # NEW — pitching hand, "L" or "R"
    role: str
    ...
```

In `from_row` (currently lines 100-116), compute and pass it:

```python
bats = str(row.get("bats", "") or "R").upper()
throws = str(row.get("throws", "") or "").strip().upper()
if throws not in {"L", "R"}:
    # players.csv only gained a throws column in 6.10.12; legacy league CSVs
    # lack it. Mirror utils/player_loader.py:242-250: most players throw with
    # the hand they bat; switch hitters default to "R".
    throws = "R" if bats == "S" else (bats if bats in {"L", "R"} else "R")
return cls(
    player_id=str(row.get("player_id", "")),
    bats=bats,
    throws=throws,
    ...
)
```

(Keep `bats` on the dataclass: it is genuine data and remains the batter-side source for the
BatterRatings twin; no pitcher-batting logic exists in the physics engine.)

Decision: normalize any non-L/R token (including a literal `"S"`) through the fallback —
switch-pitchers are not modeled and garbage tokens must not leak into hand comparisons.

### 2. Shared symmetric platoon helper (new, module level in `physics_sim/engine.py`, place
directly above `_platoon_bonus` at line 2321)

```python
# Share of league PA that come against LHP is ~26%; the vs-RHP counter-shift is
# scaled by 0.26/0.74 ≈ 0.35 so a batter's season-weighted platoon effect from
# vs_left is ~neutral: 0.74*(-0.35*d) + 0.26*(d) ≈ 0.
PLATOON_RHP_COUNTER_SCALE = 0.35


def _platoon_vl_delta(batter: BatterRatings, pitcher_hand: str) -> float:
    """Signed vs-hand rating delta derived from the single vs_left rating."""
    d = batter.vs_left - 50.0
    if (pitcher_hand or "R").upper() == "L":
        return d
    return -PLATOON_RHP_COUNTER_SCALE * d
```

### 3. `_platoon_bonus` (engine.py:2321-2324) — replace entirely

```python
def _platoon_bonus(batter: BatterRatings, pitcher: PitcherRatings) -> float:
    hand = (pitcher.throws or "R").upper()
    bats = (batter.bats or "R").upper()
    if bats == "S":
        h = 0.5                      # mirrors handedness_switch_bonus default
    elif bats == hand:
        h = -1.0
    else:
        h = 1.0
    return 2.0 * h + 0.2275 * _platoon_vl_delta(batter, hand)
```

Constants rationale (exact, not tunable here): `_batter_offense_score` (engine.py:2327-2328)
weights contact 0.55 / power 0.45; `_batter_context` shifts contact by `2.0*h + 0.25*d` and
power by `2.0*h + 0.20*d` (tuning defaults). The rating-space projection is
`0.55*(2h + 0.25d) + 0.45*(2h + 0.20d) = 2.0*h + 0.2275*d`. This keeps bench/pinch-hit
comparisons numerically consistent with in-PA outcomes.

### 4. `_batter_context` (engine.py:2975-3010)

- Line 2978: `pitcher_hand = (pitcher.throws or "R").upper()`
- Replace the conditional block at 2987-2993:

```python
platoon_chase = 0.0
vs_left_diff = _platoon_vl_delta(batter, pitcher_hand)
contact += vs_left_diff * tuning.get("platoon_contact_scale", 0.25)
power += vs_left_diff * tuning.get("platoon_power_scale", 0.2)
eye += vs_left_diff * tuning.get("platoon_eye_scale", 0.3)
platoon_chase -= vs_left_diff * tuning.get("platoon_chase_scale", 0.0015)
```

The existing `_handedness_advantage` bonuses (lines 2983-2986) already fire for both hands and
are untouched — after this change the league-average platoon gap is produced by the ±2.0
handedness shifts (spread of 4 rating points on contact/power/eye between same-hand and
opposite-hand PAs) plus the per-player `vs_left` spread. The S2-01 KPI measures the resulting
gap; the tuning lever if it misses 20-32 wOBA points is `handedness_*_bonus` (config.py:430-432).

### 5. Mechanical hand-source swaps

- engine.py:667 → `pitcher_hand = (pitcher_state.pitcher.throws or "R").upper()`
- engine.py:3016 → `hand = (starter.throws or "R").upper()`
- engine.py:3839, 3865 → second arg `pitcher_state.pitcher.throws`
- engine.py:3965 → `"hand": pitcher_state.pitcher.throws,`
- engine.py:4338 → `pitcher_hand = (pitcher.throws or "R").upper()`
- engine.py:4548, 4578 → second arg `pitcher.throws`

### 6. Test fixture fix

`tests/test_physics_sim_usage.py:8-24`: add `throws="R",` after `bats="R",` (keyword
construction; this is the only direct `PitcherRatings(` constructor outside `from_row` in the
repo).

## Edge cases

- **Legacy CSV without `throws` column**: `row.get("throws")` is `None` → fallback to bats. A
  switch-batting pitcher without `throws` becomes "R".
- **Whitespace / lowercase tokens** (`" l "`): `.strip().upper()` normalizes before the
  membership check.
- **Switch hitters as batters**: `_platoon_bonus` gives `h = 0.5` vs both hands;
  `_platoon_vl_delta` still applies (a switch hitter's `vs_left` remains meaningful — matches
  today's behavior vs LHP, now mirrored vs RHP).
- **`vs_left == 50`**: delta is 0 vs both hands — only the flat handedness term remains.
- **Missing/blank `throws` on a loaded object** (hand-built test objects): every read site keeps
  the `or "R"` guard.

## Test plan

New file `tests/test_pitcher_throws.py`:

- `test_from_row_reads_throws` — row with `bats="L", throws="R"` → `throws == "R"` (proves no
  bats proxying).
- `test_from_row_fallback_missing_column` — row without `throws` key, `bats="L"` → `"L"`.
- `test_from_row_fallback_switch_bats` — `bats="S"`, empty `throws` → `"R"`.
- `test_from_row_rejects_garbage_token` — `throws="X"`, `bats="L"` → `"L"`.
- `test_platoon_bonus_symmetric_r_batter` — R batter `vs_left=80`: bonus vs L-thrower
  `== 2.0*1 + 0.2275*30 == 8.825`; vs R-thrower `== 2.0*(-1) + 0.2275*(-10.5) == -4.388125`
  (use `pytest.approx`).
- `test_platoon_bonus_switch_hitter` — S batter `vs_left=50`: bonus `== 1.0` vs both hands.
- `test_batter_context_shifts_both_hands` — `_batter_context` with `vs_left=90` batter: contact
  vs LHP > base, contact vs RHP < base, and `ctx["batter_side"]` still derived from batter bats.
- `test_lineup_hand_from_starter_uses_throws` — starter `bats="R", throws="L"` → `"L"`.

Run: `python -m pytest tests/test_pitcher_throws.py tests/test_physics_sim_usage.py -q`

Data audit command (run against the active league data dir):

```
python -c "import csv; rows=[r for r in csv.DictReader(open('data/players.csv', newline='')) if (r.get('is_pitcher','') or '').strip().lower() in {'1','true','yes'}]; bad=[r['player_id'] for r in rows if (r.get('throws') or '').strip().upper() not in {'L','R'}]; print(f'{len(rows)} pitchers, {len(bad)} missing/invalid throws'); print(bad[:20])"
```

KPI re-run (acceptance): `python scripts/physics_sim_season_kpis.py --games 162 --seed 1 --strict --output reports/kpi_s2-06.json`

## Non-goals

- Pitcher-side `vs_left` symmetry (`_matchup_score` engine.py:678 and `physics.py:583-587` add
  pitcher quality only vs L-side batters; there is no `vs_right` rating — out of scope).
- `BatterRatings.throws` (batter throwing hand does not affect the sim).
- The legacy `playbalance` engine (uses utils `Player`, which already carries `throws`).
- UI display of pitcher handedness; CSV schema changes (column already exists).
- Retuning platoon magnitude — measured and gated by S2-01's KPI, adjusted there if needed.
