# S2-07 — Times-Through-Order Batter Bonus + `tto_ops_gap` KPI

**Status:** Spec approved for implementation (2026-07-15). **Depends on S2-08**
(calibration fixture + green baseline; the new gate is tuned on that fixture).
**All file:line anchors verified against `main` @ `62f166edf` on 2026-07-15.**

## Objective

Batters currently gain nothing on the 2nd/3rd look at a pitcher — only the hook logic
knows TTO (`physics_sim/engine.py:601-604`). Add a rating bonus per pass beyond the
first (MLB familiarity penalty ≈ 20-30 OPS pts/pass), an engine-emitted per-pass stat
split, and a strict-gated harness KPI `tto_ops_gap`.

## Acceptance criteria

1. `_batter_context` applies contact/eye/power bonuses scaled by `(tto - 1)`, clamped
   at pass 3, via three new `DEFAULT_TUNING` knobs.
2. `GameResult.metadata["tto_splits"]` carries exact per-pass batting totals
   (pa/ab/h/b1/b2/b3/hr/bb/hbp/sf/so), keys `"1"`, `"2"`, `"3"` (3 = third-and-later).
3. Harness computes `metrics["tto_ops_gap"] = OPS(pass 3) − OPS(pass 1)`; benchmark
   row `tto_ops_gap,0.050`; tolerance `0.025`; KPI harness `--strict` green on the
   calibration fixture including the new gate AND all S2-08 gates (retune per the
   calibration procedure below if any trip).
4. With all three knobs set to 0 via `tuning_overrides`, a fixed-seed game is
   play-by-play identical to pre-change (the change adds **no RNG draws**).
5. New unit + KPI tests green.

## Exact implementation

### 1. Knobs — `physics_sim/config.py`, insert into `DEFAULT_TUNING` directly after
`"handedness_switch_bonus": 0.5,` (config.py:433):

```python
# S2-07: batter familiarity bonus per times-through-order pass beyond the
# first (rating points; MLB TTO penalty ≈ 20-30 OPS pts per pass).
"tto_contact_bonus": 1.5,
"tto_eye_bonus": 1.5,
"tto_power_bonus": 1.0,
"tto_max_passes": 3.0,
```

Magnitude sanity (why 1.5/1.5/1.0 is the right starting point): at pass 3 the batter
gets +3 contact, +3 eye, +2 power. Engine sensitivities: contact feeds
`contact_base` 1:1 (`physics_sim/physics.py:760` — +3 ⇒ ≈ +3% contact prob ⇒ K%↓ ≈
0.6pp ⇒ ≈ +12-18 OPS via AVG/OBP); eye moves zone/chase swing (`physics.py:678-679`,
with the S2-08 widened divisors /160, /190 ⇒ +3 eye ⇒ ≈ +1.9pp zone-swing, −1.6pp
chase ⇒ ≈ +8-12 OPS via BB%); power moves bat speed +0.35 mph/pt
(`physics.py:806-809` ⇒ +2 ⇒ ≈ +0.5 EV ⇒ ≈ +8-12 OPS via ISO). Total pass-1→3 ≈
+30-40 OPS — inside the 50±25 gate; the calibration step below trues it up.

### 2. Engine — compute TTO once per PA and pass it into the batter context

**a. `_batter_context` (`physics_sim/engine.py:2975-3010`)** — new keyword-only param
and bonus application inserted immediately after the handedness bonuses
(engine.py:2984-2986), BEFORE the platoon block and the clamps at 2994-2996:

```python
def _batter_context(
    batter: BatterRatings, pitcher: PitcherRatings, tuning: TuningConfig,
    *, tto: int = 1,
) -> Dict[str, Any]:
    ...
    contact += handedness * tuning.get("handedness_contact_bonus", 2.0)
    power += handedness * tuning.get("handedness_power_bonus", 2.0)
    eye += handedness * tuning.get("handedness_eye_bonus", 2.0)
    # S2-07: familiarity — batters improve on the 2nd/3rd look.
    max_passes = int(tuning.get("tto_max_passes", 3.0))
    tto_extra = float(max(0, min(tto, max_passes) - 1))
    if tto_extra:
        contact += tto_extra * tuning.get("tto_contact_bonus", 0.0)
        eye += tto_extra * tuning.get("tto_eye_bonus", 0.0)
        power += tto_extra * tuning.get("tto_power_bonus", 0.0)
    ...
```

Defaults inside `tuning.get()` calls are 0.0 so a bare/legacy TuningConfig without the
knobs is behavior-neutral; the real defaults live in `DEFAULT_TUNING`.

**b. Call site — the S1-09 per-PA hoist (`physics_sim/engine.py:3950-3954`).**
`line.batters_faced` is incremented at PA start (engine.py:3749, verified: before the
IBB/bunt branches, so it already counts the current batter), `line` is the current
pitcher's `PitcherLine` (engine.py:3697), and the offense lineup is
`offense_state.lineup` (engine.py:3703). Replace line 3954:

```python
_pa_tto = _times_through_order(line.batters_faced, len(offense_state.lineup))
_pa_batter_ctx = _batter_context(batter, pitcher_state.pitcher, tuning, tto=_pa_tto)
```

(`_times_through_order` verified at engine.py:503-506; identical function the hook
logic uses, so the batter bonus and the hook see the same pass count.)

**c. Stamp the pass on every pitch-log entry** — after `entry["batter_id"] =
batter.player_id` (engine.py:4028) add `entry["tto"] = _pa_tto`. (Diagnostic only;
the KPI uses metadata, not the log.)

### 3. Engine — per-pass stat split via snapshot-diff (exact, no RNG, no log parsing)

Maintain inside `simulate_game`'s closure scope (same scope as `totals`, near the
`batter_tracking` init):

```python
tto_splits: dict[str, Counter] = {"1": Counter(), "2": Counter(), "3": Counter()}
_TTO_FIELDS = ("pa", "ab", "h", "b1", "b2", "b3", "hr", "bb", "hbp", "sf", "so")
_pending_tto: tuple[Counter | None, str, BatterLine | None] = (None, "1", None)

def _flush_tto() -> None:
    snap, bucket, bl = _pending_tto
    if snap is None or bl is None:
        return
    for f in _TTO_FIELDS:
        d = getattr(bl, f) - snap[f]
        if d:
            tto_splits[bucket][f] += d
```

- **At PA start** (immediately after `line.batters_faced += 1`, engine.py:3749, and
  after `_pa_tto` would be knowable — compute `pa_tto_bucket = str(min(_pa_tto, 3))`
  there; note `_pa_tto` must therefore be computed at 3749-3750, and the hoist at
  3954 reuses it rather than recomputing):
  ```python
  _flush_tto()
  _pending_tto = (Counter({f: getattr(batter_line, f) for f in _TTO_FIELDS}),
                  pa_tto_bucket, batter_line)
  ```
  `batter_line` is bound at engine.py:3737 (before 3749) — order holds.
- **At game end**: call `_flush_tto()` once, immediately before the metadata dict is
  assembled, and set `metadata["tto_splits"] = {k: dict(v) for k, v in tto_splits.items()}`.

Why snapshot-diff: PA outcomes are recorded across many branches (IBB engine.py:3760+,
bunts 3790+, sac flies 4846-4848, in-play 3860+), but ALL of them mutate the same
`batter_line`; diffing it between PA starts is exact by construction and adds zero
RNG draws (criterion 4). `post_at_bat` (engine.py:3668-3694) is NOT a reliable PA-end
hook (early-returns on `outs >= 3`/walkoff) — do not use it.

### 4. Harness — `scripts/physics_sim_season_kpis.py`

- In the per-game loop (after the `fielding_lines` accumulation, :647-648):
  ```python
  for bucket, stats in (meta.get("tto_splits") or {}).items():
      tto_totals[bucket].update(stats)
  ```
  with `tto_totals: dict[str, Counter] = defaultdict(Counter)` initialized beside
  `batter_totals` (:539-540).
- After `_summarize` returns (:703-713), compute using the existing
  `_split_batter_metrics` (:397-423 — field names match `_TTO_FIELDS`; strikeouts key
  `so` unused by OPS):
  ```python
  ops1 = _split_batter_metrics(tto_totals["1"])["ops"]
  ops3 = _split_batter_metrics(tto_totals["3"])["ops"]
  summary["metrics"]["tto_ops_gap"] = (ops3 - ops1) if tto_totals["3"].get("pa", 0) >= 500 else None
  summary["tto_splits"] = {k: dict(v) for k, v in tto_totals.items()}
  ```
  (`None` under 500 pass-3 PA → skipped by the `evaluate_tolerances` `None` guard
  added in S2-08.)
- `DEFAULT_TOLERANCES` (:27-61): add `"tto_ops_gap": 0.025,`.
- Benchmark CSV `data/MLB_avg/mlb_league_benchmarks_2025_filled.csv`: add row
  `tto_ops_gap,0.050`.

**Benchmark decision:** gate on the pass-3−pass-1 OPS gap at **+0.050 ± 0.025** (two
passes × 20-30 OPS pts/pass, net of the pass-3 selection effect — bad starters don't
reach pass 3). The existing `tto_penalty_runs,0.2` benchmark row stays in the CSV but
remains **unused**: it is runs-denominated with no direct formula from the harness's
accumulators, and the OPS gap measures the same phenomenon directly. Do not wire it.

### 5. Calibration procedure (after S2-08 baseline is green)

1. Run the S2-08 baseline command (162 games, seed 1, calibration fixture, `--strict`).
2. Read `metrics["tto_ops_gap"]`. If outside [0.025, 0.075]: scale all three knobs by
   `0.050 / measured_gap` (linear response holds in this range), rounded to 0.1;
   re-run. At most 3 iterations expected.
3. The bonus raises league offense slightly (most PAs vs starters are pass 1-3 with
   mean pass ≈ 1.9 ⇒ ≈ +1.3 rating league-wide). If `k_pct`/`bb_pct`/`avg`/`ops`
   league gates trip: compensate with `k_scale` +0.01 and/or `offense_scale` −0.005
   (Decision-3 families in the S2-08 spec), then re-verify BOTH the league gates and
   the gap.
4. Done: `--strict` exit 0 on seeds 1 and 2 with `tto_ops_gap` gated.

### 6. Interplay with the hook logic (engine.py:601-604)

The hook already adds `hook_tto_penalty` (0.7) to the hook score when `tto >= 3` and
the fatigue soft-trigger is met. The batter bonus makes pass-3 pitching genuinely
worse, so runs/hits-based hook terms fire slightly earlier — that is the desired
emergent behavior. No change to the hook block. Expected second-order effect:
`ip_per_start` drops ≈ 0.1-0.2; irrelevant until S2-12's gates are opted in, but note
it in the S2-12 tuning session.

## Files to change (verified anchors)

| File | Change |
|---|---|
| `physics_sim/config.py:433` (after `handedness_switch_bonus`) | 4 new knobs |
| `physics_sim/engine.py:2975-3010` | `_batter_context(..., *, tto: int = 1)` + bonus block |
| `physics_sim/engine.py:3749-3750` | compute `_pa_tto` / `pa_tto_bucket`; snapshot flush + take |
| `physics_sim/engine.py:3954` | pass `tto=_pa_tto` (reuse, don't recompute) |
| `physics_sim/engine.py:4028` | `entry["tto"] = _pa_tto` |
| `physics_sim/engine.py` (metadata assembly) | `_flush_tto()`; `metadata["tto_splits"]` |
| `scripts/physics_sim_season_kpis.py:539-540, 647-648, 703+, 27-61` | accumulate splits; `tto_ops_gap`; tolerance |
| `data/MLB_avg/mlb_league_benchmarks_2025_filled.csv` | `tto_ops_gap,0.050` |

## Edge cases

- **Pinch hitters:** substitution happens before PA start (engine.py:3713-3732), so the
  snapshot is taken on the PH's own `batter_line` — correct attribution.
- **Mid-PA pitcher change:** cannot happen in this engine (hooks are evaluated between
  PAs); `_pa_tto` is stable for the PA.
- **Reliever TTO:** relievers rarely exceed 9 BF; `tto` naturally stays 1 — no special
  case.
- **Extra innings / walkoff:** the final PA's diff is captured by the game-end
  `_flush_tto()`; a walkoff PA's partial stats (runs count, batter credited) diff
  correctly because the flush runs after all `batter_line` mutations.
- **Lineup size ≠ 9** (bench-depleted edge): `_times_through_order` already guards
  `lineup_size <= 0` (engine.py:503-506); `len(offense_state.lineup)` is the live list.
- **`tto_max_passes`** clamps runaway bonuses in blowout long outings (pass 4+ treated
  as pass 3 — matches MLB evidence that the penalty plateaus).

## Test plan (exact)

New file `tests/test_tto_bonus.py`:

- `test_batter_context_tto_bonus` — `_batter_context(b, p, tuning, tto=3)` returns
  contact/eye +3.0 and power +2.0 over the `tto=1` result (same batter/pitcher, R vs R,
  default knobs); `tto=1` result identical to a call without the kwarg.
- `test_tto_clamps_at_max_passes` — `tto=6` equals `tto=3` output.
- `test_tto_zero_knobs_parity` — `simulate_matchup_from_files` on the calibration
  fixture (2 teams, seed 42) twice: once on pre-change code path emulated by
  `tuning_overrides={"tto_contact_bonus":0,"tto_eye_bonus":0,"tto_power_bonus":0}`,
  once… (implementer note: true pre/post parity is verified once at the commit
  boundary by running the same seed on the parent commit; in-repo, assert the
  zero-knob run's `pitch_log` length and totals equal a golden snapshot captured at
  implementation time).
- `test_tto_splits_reconcile` — one simulated game: sum of
  `metadata["tto_splits"][k][f]` over k equals the game's aggregate batting line for
  every field in `_TTO_FIELDS` (exactness of snapshot-diff, incl. IBB/bunt/SF branches).
- `test_tto_ops_gap_direction` — 20-game 2-team `run_sim` on the fixture with knobs
  ×4 via `tuning_overrides` shows `tto_ops_gap` strictly greater than with knobs at 0.

Commands:
```
python -m pytest tests/test_tto_bonus.py -q
python scripts/physics_sim_season_kpis.py --games 162 --seed 1 --base-dir data/calibration --players data/calibration/players.csv --output tmp/tto.json --strict
```

## Non-goals

- TTO-aware hook redesign / openers (S3-15), pitcher-side per-pitch-type familiarity,
  wiring `tto_penalty_runs`, catcher-game-calling effects, exposing tto splits in any
  API/UI.
