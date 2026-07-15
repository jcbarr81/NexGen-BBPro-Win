# S2-01 — Genuinely different vs-LHP / vs-RHP lineups + platoon-split KPI

**Depends on S2-06** (`PitcherRatings.throws`, `_platoon_vl_delta`, symmetric `_platoon_bonus`).

## Objective

`utils/lineup_autofill.py` builds ONE lineup and writes it to both `{team}_vs_lhp.csv` and
`{team}_vs_rhp.csv` (lines 181-194); `hitter_score` (lines 82-92) ignores handedness. The
engine's per-game file choice (`playbalance/game_runner.py:1281-1299` and
`physics_sim/engine.py:3086-3092`) is therefore a no-op. Make `hitter_score` handedness-aware,
build the two files from two independent passes, and add a league platoon-split KPI to the
season harness so the realized L/R gap is measured and gated.

## Acceptance criteria

1. For a roster containing a platoon candidate (see lineup-diff test), the generated
   `_vs_lhp.csv` and `_vs_rhp.csv` differ (personnel and/or order).
2. Both files always contain exactly 9 data rows with 9 unique non-pitcher player IDs covering
   C, SS, CF, 3B, 2B, 1B, LF, RF (+ DH), whenever ≥9 eligible non-pitchers exist (same
   fill/fallback ladder as today).
3. Existing callers keep working unchanged: `api/routers/lineups.py:132` (`vs=` filter),
   `api/routers/admin_league.py:220`, `services/roster_auto_assign.py:716`,
   `playbalance/game_runner.py:527` (`_sanitize_lineup`), `physics_sim/engine.py:3100/3111`.
4. New harness KPI `platoon_gap_woba` (league wOBA of opposite-hand PAs minus same-hand PAs,
   switch hitters excluded) reported in the summary and gated at **0.026 ± 0.006**
   (pass band 20-32 wOBA points).
5. `python -m pytest tests/test_lineup_autofill_platoon.py -q` green; full harness
   `--games 162 --strict` green.

## Files to change (verified anchors)

| File | Anchor | Change |
|---|---|---|
| `utils/lineup_autofill.py` | 22-42 docstring; 82-92 `hitter_score`; 102-180 selection+sort; 181-194 write loop; 196-238 explanation | per-hand two-pass build |
| `physics_sim/engine.py` | new consts near 153 (`BatterLine`); 3653-3666 `finalize_half_inning`; 3737-3749 PA open (after `batter_line.pa += 1` at 3746) | per-PA result logging (`pa_result`) |
| `scripts/physics_sim_season_kpis.py` | 27-61 `DEFAULT_TOLERANCES`; 119-140 ratings loader; 649-697 pitch-log loop; 703-713 `_summarize` call site; 876-888 `main` gate | hands lookup + platoon split + gate |
| `tests/test_lineup_autofill_platoon.py` | new | unit tests |

## Exact implementation

### 1. `hitter_score` — new signature and formula (`utils/lineup_autofill.py:82-92`)

Keep the pid-based closure (all three call sites pass pids; taking a Player would force extra
lookups at each `max(..., key=...)`):

```python
def hitter_score(pid: str, *, vs_hand: str) -> float:
    p = players.get(pid)
    if not p:
        return -1.0
    ch = float(getattr(p, "ch", 0)); ph = float(getattr(p, "ph", 0))
    sp = float(getattr(p, "sp", 0))
    fa = float(getattr(p, "fa", 0)); arm = float(getattr(p, "arm", 0))
    off = 0.5 * ch + 0.5 * ph
    defense = 0.5 * fa + 0.5 * arm
    base_score = (0.6 * off) + (0.2 * sp) + (0.2 * defense)
    return (
        base_score
        + _platoon_adjustment(p, vs_hand=vs_hand)
        + _strategy_hitter_bonus(p, profile=profile)
    )
```

New module-level helper (place next to `_strategy_hitter_bonus`, line ~278):

```python
def _platoon_adjustment(player: object, *, vs_hand: str) -> float:
    """Mirror the physics engine's platoon scale (engine._batter_context /
    _platoon_vl_delta) projected onto hitter_score's 0.6*(0.5*ch+0.5*ph)
    offense weight: 0.6*(0.5*(2h+0.25d) + 0.5*(2h+0.20d)) = 1.2*h + 0.135*d.
    Keeping the same constants makes lineup choices agree with in-game
    outcomes."""
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
        d = -0.35 * d          # PLATOON_RHP_COUNTER_SCALE, see S2-06
    return 1.2 * h + 0.135 * d
```

(`models/player.py:39` confirms `vl` exists on `Player`; `bats` is set by
`utils/player_loader.py:242`.)

### 2. Two-pass generation flow (`auto_fill_lineup_for_team`)

Restructure lines 62-194. Everything from line 62 (`# Collect non-pitchers first`) through
line 180 (the order sort) moves into an inner function built once per hand; the write loop
iterates hands and builds independently:

```python
def _build_lineup(hand: str) -> tuple[list[tuple[str, str]], dict[str, int]]:
    lineup: list[tuple[str, str]] = []
    used: set[str] = set()
    counters = {"depth_chart": 0, "fallback": 0, "emergency": 0}
    # ... lines 102-176 verbatim, with two substitutions:
    #   every `hitter_score(pid)` / `key=hitter_score`
    #     -> `hitter_score(pid, vs_hand=hand)` / `key=lambda pid: hitter_score(pid, vs_hand=hand)`
    #     (call sites: line 120 `best = max(candidates, key=hitter_score)`,
    #      line 146 `best = max(remaining, key=hitter_score)`)
    #   counters increment the local dict instead of the outer ints
    ordered = _assign_batting_order(lineup[:9], players, vs_hand=hand, profile=profile)  # S2-02
    return ordered, counters
```

Until S2-02 lands, `_assign_batting_order(...)` is
`sorted(lineup[:9], key=lambda pair: hitter_score(pair[0], vs_hand=hand), reverse=True)` —
S2-02 replaces only that line.

Write loop (replaces 181-194):

```python
vs_token = (vs or "").strip().lower()
if vs_token in {"lhp", "rhp"}:
    targets: tuple[str, ...] = (f"vs_{vs_token}",)
else:
    targets = ("vs_lhp", "vs_rhp")
built: dict[str, list[tuple[str, str]]] = {}
counters_by_target: dict[str, dict[str, int]] = {}
for target in targets:
    hand = "L" if target == "vs_lhp" else "R"
    result, counters = _build_lineup(hand)
    built[target] = result
    counters_by_target[target] = counters
    path = lineup_root / f"{team_id}_{target}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["order", "player_id", "position"])
        for i, (pid, pos) in enumerate(result, start=1):
            writer.writerow([i, pid, pos])
result = built[targets[-1]]   # vs_rhp when both are written (majority hand); the
                              # single requested variant otherwise
```

Return value decision: return the vs_rhp lineup when both are generated — RHP starters are the
majority matchup and `_sanitize_lineup` (game_runner.py:527-534) uses the return as the
salvage lineup. Order `targets` as today (`("vs_lhp", "vs_rhp")`), so `targets[-1]` is vs_rhp.

Decision-log payload (lines 196-238): keep the same reason codes; in `context` replace the
three flat counters with `"assignments_by_target": counters_by_target` and add
`"targets": list(targets)`; `lineup_size` = `len(result)`. (The payload is free-form —
`tests/test_decision_explanations.py:69-78` asserts only category/action and that context
exists; verify it still passes.)

Update the docstring bullet at lines 40 (“Write both ... using the same order for now.”) to
describe per-hand builds.

**Why personnel can differ, not just order:** the fallback/DH/emergency selections (lines
111-176) pick by `hitter_score`, which is now hand-dependent, so a lefty-masher wins a slot vs
LHP and loses it vs RHP. Depth-chart-preferred slots (lines 104-110) intentionally still
override score — a fully specified depth chart pins personnel and only the batting order
differs. Note this in the module docstring.

### 3. Bench interplay (no code)

Bench is never written to a file: `physics_sim/team_data.py:258-278 build_bench` derives the
bench per game as ACT minus that game's lineup, and `playbalance` builds bench the same way.
A platoon bat left out of the vs-RHP file is therefore automatically on the vs-RHP bench and
available to `_select_pinch_hitter` (which, after S2-06, evaluates him with the symmetric
`_platoon_bonus`). Nothing to change; state this in the spec-comment at the write loop.

### 4. Nine-row / coverage guarantee (verified, keep as-is)

Current behavior: the ladder at lines 102-176 fills C, SS, CF, 3B, 2B, 1B, LF, RF, DH, then
pads with emergency DH rows; the writer emits `result[:9]` rows. Consumers validate length:
`game_runner._select_saved_lineup` (1288-1299) requires `len(lineup) == 9` else falls through
to regeneration, and `physics_sim/engine.py:3099-3120` re-autofills when `len(lineup) < 9`.
Each per-hand build runs the full ladder, so both files independently retain the invariant.
Add the invariant test below so a regression is caught at the generator.

### 5. Platoon-split KPI

#### 5a. Engine: per-PA result logging (`physics_sim/engine.py`)

The pitch log does NOT carry PA outcomes today (verified: hit resolution at 4397-4408 updates
`batter_line`/`totals` only), so pure aggregation-time reconstruction is impossible. Add a
minimal `pa_result` tag on the last log entry of each PA via snapshot-diff — one open point,
one close helper:

Module constant (near `BatterLine`, line ~190):

```python
_PA_RESULT_KEYS = (
    "ab", "h", "b2", "b3", "hr", "bb", "ibb", "hbp",
    "so", "sf", "sh", "roe", "fc", "gidp",
)


def _pa_result_token(delta: Dict[str, int]) -> str | None:
    if delta.get("hr"):
        return "hr"
    if delta.get("b3"):
        return "3b"
    if delta.get("b2"):
        return "2b"
    if delta.get("h"):
        return "1b"
    if delta.get("ibb"):
        return "ibb"
    if delta.get("bb"):
        return "bb"
    if delta.get("hbp"):
        return "hbp"
    if delta.get("so"):
        return "so"
    if delta.get("sf"):
        return "sf"
    if delta.get("sh"):
        return "sh"
    if delta.get("roe"):
        return "roe"
    if delta.get("ab") or delta.get("fc") or delta.get("gidp"):
        return "out"
    return None
```

(Priority order matters: IBB also increments `bb` — engine.py:3767-3768; hits also increment
`h` and `ab`.)

In `play_half_inning` scope (next to `post_at_bat`, line 3668), add:

```python
open_pa: list[tuple[BatterLine, dict[str, int]]] = []

def _close_open_pa() -> None:
    if not open_pa:
        return
    bline, snap = open_pa.pop()
    delta = {k: getattr(bline, k) - snap[k] for k in _PA_RESULT_KEYS}
    token = _pa_result_token(delta)
    if token and pitch_log:
        pitch_log[-1]["pa_result"] = token
```

Call `_close_open_pa()` (a) as the first statement of `finalize_half_inning` (line 3653) —
covers both loop exits at 5072 (walkoff) and 5140, and (b) immediately after
`batter_line.pa += 1` (line 3746) BEFORE opening the new PA, then open:

```python
_close_open_pa()
open_pa.append(
    (batter_line, {k: getattr(batter_line, k) for k in _PA_RESULT_KEYS})
)
```

Why this is safe: the snapshot keys are only mutated during that player's own PA (runner stats
`sb/cs/r/lob` are excluded), and no pitch-log entries are appended between a PA's last entry
and the next PA's first (the IBB entry at 3781-3787 and the bunt entry at 3814-3818/3947 are the
last entries of their PAs and correctly receive the tag). Entries already carry `batter_id`
and `pitcher_id` (3785/3817 and 4027-4028).

#### 5b. Harness: hands lookup + split (`scripts/physics_sim_season_kpis.py`)

- Extend `_load_player_ratings` (119-140) to also return `bats: dict[str, str]` and
  `throws: dict[str, str]` (read `row["bats"]`/`row["throws"]`, apply the same fallback:
  empty `throws` → `"R"` if bats `"S"` else bats or `"R"`). Update the two call/unpack sites
  (543-545 and none else) accordingly, or add a separate `_load_player_hands(path)` — DECIDED:
  separate `_load_player_hands` to avoid churn on the existing 3-tuple.
- In `run_sim`, add `platoon_counts: dict[str, Counter] = defaultdict(Counter)`.
- In the pitch-log loop (649-694): the loop currently starts with
  `if "pitch_type" not in entry: continue` — insert the PA scan BEFORE that guard (ibb/bunt
  entries lack `pitch_type`):

```python
pa_result = entry.get("pa_result")
if pa_result:
    b_hand = bats_by_id.get(str(entry.get("batter_id", "")), "R")
    p_hand = throws_by_id.get(str(entry.get("pitcher_id", "")), "R")
    platoon_counts[f"{b_hand}{p_hand}"][pa_result] += 1
```

- wOBA per bucket (new helper `_woba_from_pa_counts(c: Counter) -> tuple[float, int]`;
  weights are fixed FanGraphs-style constants):

```python
uBB = c["bb"]; HBP = c["hbp"]
B1 = c["1b"]; B2 = c["2b"]; B3 = c["3b"]; HR = c["hr"]
AB = B1 + B2 + B3 + HR + c["so"] + c["out"] + c["roe"]
den = AB + uBB + c["sf"] + HBP
woba = (0.69*uBB + 0.72*HBP + 0.88*B1 + 1.25*B2 + 1.59*B3 + 2.05*HR) / den if den else 0.0
return woba, den
```

  (`ibb` and `sh` are excluded from both numerator and denominator — standard wOBA.)
- Aggregate: `same = platoon_counts["LL"] + platoon_counts["RR"]`,
  `opp = platoon_counts["LR"] + platoon_counts["RL"]` (Counter addition); switch-hitter
  buckets `S*` reported but excluded from the gap.
- `summary["platoon"] = {"buckets": {k: {"woba": w, "den": n, ...} }, "gap_woba": woba_opp - woba_same, "same_pa": den_same, "opp_pa": den_opp}` and
  `summary["metrics"]["platoon_gap_woba"] = gap`.
- Gate: add `"platoon_gap_woba": 0.006` to `DEFAULT_TOLERANCES` (line 27-61) and pass
  `targets={"platoon_gap_woba": 0.026}` to `evaluate_tolerances` in `main` (881-885) —
  `evaluate_tolerances` already supports a `targets` dict (489-498). Pass band: 0.020-0.032.

Note: lineup files on disk must be regenerated once after S2-01 ships (`--ensure-lineups` only
fills missing files — `_ensure_team_files:238-268`). Acceptance runs delete `data/lineups/*`
first or call the admin "Set All Team Lineups" action.

## Edge cases

- **Switch hitters**: `h = +0.5` vs both hands; never creates an artificial file difference by
  themselves (same adjustment both sides except the `d` term, which flips scale via 0.35).
- **Missing `vl`/`bats` attributes**: `getattr(..., 50)` / `or "R"` defaults — score falls back
  to today's hand-neutral value.
- **Tiny rosters (<9 non-pitchers)**: unchanged emergency ladder (152-176) pads from the full
  players file; both hands run it identically.
- **Depth chart covers all 8 positions + DH**: identical personnel both files; only the S2-02
  order can differ. Legal outcome; the lineup-diff test uses a roster WITHOUT a depth chart.
- **`vs="lhp"`/`"rhp"` explicit**: builds and writes only that hand (API contract preserved).
- **PA with no result token** (e.g. inning ends on a caught-stealing mid-PA): no `pa_result`
  written; PA excluded from the KPI denominator.
- **Mid-PA pitching change**: hands resolved from the entry the token lands on (last pitch of
  the PA) — pitcher_id on that entry is the pitcher who finished the PA. Correct by
  construction.

## Test plan

New file `tests/test_lineup_autofill_platoon.py` (build a temp league dir with `players.csv`,
`data/rosters/TST.csv`, no depth chart, monkeypatch `utils.path_utils.get_data_dir`/use
explicit `players_file/roster_dir/lineup_dir` kwargs as `tests/test_simulation_averages.py`
does):

- `test_platoon_candidate_produces_different_files` — 10 hitters; two 1B-only candidates:
  A (`bats="R"`, `vl=90`, ch/ph 60) and B (`bats="L"`, `vl=30`, ch/ph 62). Assert the two CSVs
  differ and A starts vs LHP while B starts vs RHP.
- `test_both_files_nine_unique_rows_and_coverage` — parse both files: 9 rows, 9 unique pids,
  position multiset covers {C,SS,CF,3B,2B,1B,LF,RF} (9th row DH), no pitcher ids.
- `test_vs_filter_writes_single_file` — `vs="lhp"` touches only the lhp file (compare mtimes /
  file absence in a fresh dir).
- `test_platoon_adjustment_values` — direct: R bat `vl=90` → `+1.2 + 0.135*40 = 6.6` vs "L",
  `-1.2 + 0.135*(-14.0) = -3.09` vs "R"; S bat `vl=50` → `+0.6` both hands (approx).
- `test_pa_result_tokens` — unit-test `_pa_result_token` priority (ibb before bb, hr before 1b,
  fc→"out", empty→None) in `tests/test_pitcher_throws.py` or a new
  `tests/test_physics_pa_log.py`; plus one `simulate_game` smoke (2 teams × 9 batters, seed
  fixed) asserting `sum(1 for e in result.pitch_log if "pa_result" in e)` equals
  `result.totals["pa"]` minus unresolved PAs (assert ≥ 0.98 × totals["pa"]).

Run: `python -m pytest tests/test_lineup_autofill_platoon.py tests/test_physics_pa_log.py tests/test_decision_explanations.py -q`

KPI acceptance: regenerate lineups, then
`python scripts/physics_sim_season_kpis.py --games 162 --seed 1 --strict --output reports/kpi_s2-01.json`
and check `summary["platoon"]["gap_woba"] ∈ [0.020, 0.032]`.

## Non-goals

- Batting-order intelligence (S2-02 replaces the final sort only).
- Rest/fatigue-aware selection (S2-05).
- Per-team platoon *strategy* knobs (strategy profiles keep their existing bonus).
- Persisting bench files or changing lineup CSV schema.
- In-game (mid-sim) lineup re-selection when a reliever of the other hand enters.
