# S2-12 — Pitching-Usage Pattern KPIs (opt-in `--usage-gates`)

**Status:** Spec approved for implementation (2026-07-15). **Depends on S2-08**
(calibration fixture + `--base-dir`). These gates are **expected RED until S2-03
(reliever rest) and S2-04 (closer usage) land** — they ship opt-in behind
`--usage-gates` and are flipped into the default strict set in the S2-03/04 commits.
**All file:line anchors verified against `main` @ `62f166edf` on 2026-07-15.**

## Objective

The hook/bullpen logic (`physics_sim/engine.py:531-657`) is elaborate but unvalidated;
`data/MLB_avg/role_averages_mlbstats_2020_2024.csv` sits unused. Add six usage metrics
to the KPI harness with MLB targets, computed from data the harness already receives,
gated only when `--usage-gates` is passed.

## Source data (verified)

`data/MLB_avg/role_averages_mlbstats_2020_2024.csv` — columns:
`Year,Role,Num_Pitchers,IP,ERA,WHIP,K%,BB%,HR/9,SV,HLD`; roles
`Closer,Middle,Setup,Starter`; rows per year 2020-2024 plus `2020-2024 AVG`. It has
**no GS/appearance columns**, so per-start and appearance-count targets below are
fixed constants from 2021-2024 MLB (2020 excluded — 60-game season):
saves: 2021-24 league SV ≈ 649+631+730+740 relievers' `SV` column ⇒ ≈ 0.25 saves per
team-game; the rest are league-known values stated per metric. The CSV's ERA/K% by
role are NOT gated here (they co-move with S2-03/04 tuning; revisit there).

Harness inputs (all already exist, verified):
- per-game `meta["pitcher_lines"][side]` — dicts from `_pitcher_line_summary`
  (`physics_sim/engine.py:943-997`) with keys incl. `g, gs, sv, hld, gf, outs, pitches`.
- season `pitcher_totals[pid]` Counters accumulated over `pitching_keys`
  (`scripts/physics_sim_season_kpis.py:573-605` — includes `g, gs, sv, hld, outs,
  pitches`).
- `game_day` from the `day_map` in the sim loop (`:609-614`) — the schedule day index,
  exactly what the engine's rest logic consumes (`engine.py:456-468`).

## Exact implementation — `scripts/physics_sim_season_kpis.py`

### 1. Accumulators (init beside `batter_totals`/`pitcher_totals`, :539-540)

```python
usage = Counter()                       # starts, start_pitches, start_outs, reliever_appearances
reliever_days: dict[str, list[int]] = defaultdict(list)   # pid -> game_day per relief appearance
```

### 2. Per-game collection (inside the loop over `("away", "home")`, extend the
existing `pitcher_lines` block at :641-646)

```python
for line in (meta.get("pitcher_lines", {}) or {}).get(side, []):
    ...existing _accumulate calls...
    if int(line.get("gs", 0) or 0) >= 1:
        usage["starts"] += 1
        usage["start_pitches"] += int(line.get("pitches", 0) or 0)
        usage["start_outs"] += int(line.get("outs", 0) or 0)
    else:
        usage["reliever_appearances"] += 1
        reliever_days[str(line.get("player_id", ""))].append(game_day)
```

(`game_day` is in scope; `player_id` key present on pitcher lines — the existing block
reads it at :643.)

### 3. Metric definitions (compute after the sim loop, insert with the S2-08
dispersion block after :825; add results to `summary["metrics"]`)

| Metric key | Formula | Target | Tolerance |
|---|---|---|---|
| `pitches_per_start` | `usage["start_pitches"] / usage["starts"]` | 86.0 | 6.0 |
| `ip_per_start` | `usage["start_outs"] / 3.0 / usage["starts"]` | 5.2 | 0.4 |
| `relievers_per_team_game` | `usage["reliever_appearances"] / (games * 2)` where `games = len(schedule)` | 3.3 | 0.4 |
| `reliever_top_appearances` | `max(g over pitcher_totals with gs == 0) * (162.0 / games_per_team)` | 77.0 | 10.0 |
| `saves_per_team_game` | `sum(sv over pitcher_totals) / (games * 2)` | 0.25 | 0.05 |
| `reliever_b2b_share` | see below | 0.15 | 0.06 |

`reliever_b2b_share` (share of relief appearances made on zero days' rest):

```python
b2b = 0
for days in reliever_days.values():
    days.sort()
    b2b += sum(1 for a, b in zip(days, days[1:]) if b - a == 1)
total = usage["reliever_appearances"]
metrics["reliever_b2b_share"] = (b2b / total) if total else None
```

All six emit `None` when their denominator is 0 (skipped by the `evaluate_tolerances`
`None` guard from S2-08). `reliever_top_appearances` normalizes to a 162-game pace so
the metric is comparable at any `--games`; the other five are already rates.

Target rationales (one line each): pitches/start — MLB 2021-24 ≈ 85-88; IP/start —
MLB 2021-24 ≈ 5.1-5.3; relievers/team-game — MLB ≈ 3.2-3.4; appearance leader —
MLB leaders 75-80 (deep_review_plan.md S2-03 row); saves — ≈ 40/team/162 ⇒ 0.25;
back-to-back share — ≈ 14-16% of MLB relief appearances come on 0 days rest.

Diagnostics (not gated): also emit `summary["usage"] = {"starts": ..., "reliever_appearances": ...,
"appearance_leaders": top-10 [{player_id, name, g}] among gs==0 pitchers}` for the
eyeball check that S2-03 needs.

### 4. Gate plumbing (opt-in)

Module level, directly below `DEFAULT_TOLERANCES` (:61):

```python
# S2-12 usage gates — expected red until S2-03/S2-04 land; enforced only
# with --usage-gates. Move these into DEFAULT_TOLERANCES in the S2-03/04 commits.
USAGE_TOLERANCES: dict[str, float] = {
    "pitches_per_start": 6.0,
    "ip_per_start": 0.4,
    "relievers_per_team_game": 0.4,
    "reliever_top_appearances": 10.0,
    "saves_per_team_game": 0.05,
    "reliever_b2b_share": 0.06,
}
```

Benchmark rows to append to `data/MLB_avg/mlb_league_benchmarks_2025_filled.csv`:

```
pitches_per_start,86.0
ip_per_start,5.2
relievers_per_team_game,3.3
reliever_top_appearances,77.0
saves_per_team_game,0.25
reliever_b2b_share,0.15
```

CLI (`main()`, add after `--strict`, :849-852):

```python
parser.add_argument(
    "--usage-gates",
    action="store_true",
    help="Also enforce the S2-12 pitching-usage tolerances under --strict "
         "(expected to fail until S2-03/S2-04 land).",
)
```

Evaluation (in `main()`, :881-895): keep the existing `failures` call unchanged, then:

```python
usage_failures = evaluate_tolerances(
    metrics=summary.get("metrics", {}),
    benchmarks=benchmarks,
    tolerances=USAGE_TOLERANCES,
)
summary["usage_tolerances"] = USAGE_TOLERANCES
summary["usage_tolerance_failures"] = usage_failures
summary["usage_tolerance_ok"] = not usage_failures
if args.usage_gates:
    failures = failures + usage_failures
```

(`summary["tolerance_failures"]`/strict-exit logic at :887-895 then behaves
unchanged; usage failures are always **reported** in the JSON, only **enforced**
under the flag.)

`_load_tolerances` (:86-102) merges override files against `DEFAULT_TOLERANCES` only —
extend it to also accept the six usage keys: build the merge base as
`{**DEFAULT_TOLERANCES, **USAGE_TOLERANCES}` split back by key membership… simpler
DECISION: change `_load_tolerances` to merge into `dict(DEFAULT_TOLERANCES)` as today
AND, if a key belongs to `USAGE_TOLERANCES`, write it there instead (both dicts
returned as a tuple). Signature: `_load_tolerances(path) -> tuple[dict, dict]`; both
call sites in `main()` updated. This keeps `--tolerances` JSON overrides working for
usage gates too.

### 5. CI

No workflow change now: the S2-08 workflow command does NOT pass `--usage-gates`.
The S2-03/S2-04 implementation commits (a) retune rest/closer knobs
(`reliever_rest_days` config.py:345, `closer_*` config.py:344-357, hook family
config.py:456-474) against these gates, (b) move the six keys from
`USAGE_TOLERANCES` into `DEFAULT_TOLERANCES`, delete the flag, and update this spec's
status line — that is the definition of "gates green after S2-03/04 land" in
deep_review_plan.md.

## Files to change (verified anchors)

| File | Change |
|---|---|
| `scripts/physics_sim_season_kpis.py:61` | `USAGE_TOLERANCES` dict |
| `scripts/physics_sim_season_kpis.py:86-102` | `_load_tolerances` returns (default, usage) pair |
| `scripts/physics_sim_season_kpis.py:539-540` | `usage` Counter + `reliever_days` init |
| `scripts/physics_sim_season_kpis.py:641-646` | per-game starter/reliever collection |
| `scripts/physics_sim_season_kpis.py:825+` | six metrics + `summary["usage"]` diagnostics |
| `scripts/physics_sim_season_kpis.py:849-852, 881-895` | `--usage-gates` flag + evaluation |
| `data/MLB_avg/mlb_league_benchmarks_2025_filled.csv` | six benchmark rows |

## Edge cases

- **Starter also relieves later in the season:** classification is per game-line
  (`gs` on that game's line), not per player — a swingman's starts count in
  `pitches_per_start`, his relief outings in reliever metrics. Correct by construction.
- **Two lines with `gs`?** Impossible: `_line_for_pitcher` sets `gs=1` only for
  `team_state.starter` (engine.py:492-493).
- **Doubleheaders:** the fixture schedule has at most one game/team/day
  (`generate_mlb_schedule`), so `b - a == 1` cleanly means consecutive days. If a
  future schedule has same-day pairs, `b - a == 0` is NOT counted as back-to-back —
  document in the code comment.
- **`sv` correctness** depends on the engine's save attribution (PitcherLine.sv,
  engine.py:107) — gate tolerance (±0.05) absorbs edge-case scoring; S2-04 owns
  fixing attribution if it's off.
- **Short runs:** `reliever_top_appearances` is pace-normalized and noisy below ~50
  games; acceptable because the gate is opt-in and the strict contract is the
  162-game CI configuration (same policy as the S2-08 SD gates).
- **`--usage-gates` without `--strict`:** flag affects only the failure list; without
  `--strict` nothing exits non-zero (matches existing tolerance semantics).

## Test plan (exact)

New file `tests/test_usage_kpis.py` (pure-python, no sim):

- `test_usage_metrics_from_synthetic_lines` — extract the metric computation into
  `_usage_metrics(usage: Counter, reliever_days: dict, pitcher_totals: dict,
  games: int, games_per_team: int) -> dict` and feed hand-built inputs: 2 starts
  (170 pitches, 31 outs), 5 relief appearances across 2 pitchers on days
  [3,4,6] and [3,5]; assert `pitches_per_start == 85.0`,
  `ip_per_start == pytest.approx(5.1667, abs=1e-3)`, `reliever_b2b_share == 0.2`
  (one adjacent pair in [3,4,6], none in [3,5]), `relievers_per_team_game`,
  `reliever_top_appearances` scaling (g=3, games_per_team=81 ⇒ 6.0), and the
  zero-denominator `None` path.
- `test_usage_gates_flag_plumbing` — call `evaluate_tolerances` with
  `USAGE_TOLERANCES` against a metrics dict that misses `ip_per_start` by 1.0 and
  assert exactly one failure; assert the key is absent from `DEFAULT_TOLERANCES`
  (guards against premature promotion).
- Integration: `run_sim(games_per_team=20, seed=1, players_path=CAL/"players.csv",
  base_dir=CAL)` (2-team monkeypatch as in `test_simulation_averages.py`) produces all
  six keys in `metrics` with `pitches_per_start > 0`.

Commands:
```
python -m pytest tests/test_usage_kpis.py -q
python scripts/physics_sim_season_kpis.py --games 162 --seed 1 --base-dir data/calibration \
  --players data/calibration/players.csv --output tmp/usage.json          # reports usage_tolerance_failures, exit 0
python scripts/physics_sim_season_kpis.py --games 162 --seed 1 --base-dir data/calibration \
  --players data/calibration/players.csv --strict --usage-gates ; echo $?  # expected exit 2 until S2-03/04
```

## Non-goals

- Fixing reliever rest / closer usage themselves (S2-03/S2-04 — these gates are their
  verification harness), holds-distribution and role-ERA gates (revisit in S2-03/04
  with the CSV's per-role ERA/K% columns), warm-up/bullpen-session modeling, any UI surface,
  promoting the gates to default-strict (explicitly done in S2-03/04 commits).
