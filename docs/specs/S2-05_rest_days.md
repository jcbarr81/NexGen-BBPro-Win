# S2-05 — Position-player rest days (fatigue-aware pre-game lineup swaps)

**Depends on S2-06** (`PitcherRatings.throws`, symmetric `_platoon_bonus`). Independent of
S2-01/S2-02 code, but implement after them so the harness KPI additions merge cleanly.

## Objective

Batter fatigue accumulates (`physics_sim/usage.py:113-130 record_batter_game`, recovery in
`advance_day:73-89`) and degrades in-game performance up to −35%
(`engine.py:2816-2834 _batter_fatigue_penalty`, applied at 2837-2874), but **no code ever
benches anyone** — saved lineup files are static and every starter plays 162 games.

Decision on the trigger point (traced): `auto_fill_lineup_for_team` is NOT in the per-game
path — it runs only on missing/invalid lineups (`game_runner._sanitize_lineup:510-534`,
`engine.py:3099-3120`), from UI/API actions (`api/routers/lineups.py:132`,
`api/routers/admin_league.py:220`), and season setup (`services/roster_auto_assign.py:716`).
`UsageState` is not reachable there, and regenerating files would persist a one-day rest.
Therefore rest swaps happen **pre-game, in memory, inside `physics_sim.engine.simulate_game`**,
immediately after `usage_state.advance_day` (engine.py:3298-3303) and before
`_apply_batter_fatigue` (3305). This single hook covers all three season paths for free:
`game_runner._run_physics_game` (game_runner.py:1093-1109, usage from
`_physics_usage_context:54-86`), `engine.simulate_matchup_from_files` (3134-3151), and the KPI
harness (`scripts/physics_sim_season_kpis.py:615-624`). No lineup file is ever rewritten.

## Acceptance criteria

1. With `usage_state`/`game_day` provided, a starter over the rest threshold (or over the
   consecutive-games limit) is replaced pre-game by the best position-eligible bench bat; the
   replacement inherits the batting slot and defensive position; the rested starter is removed
   from that game's bench entirely (a true day off).
2. No swap ever occurs when `usage_state is None or game_day is None` (exhibition/tests parity
   preserved), when no eligible replacement exists, or beyond 2 swaps per team-game.
3. The same player is not benched on back-to-back game days unless over the hard-fatigue bar
   (bookkeeping via new `BatterWorkload` fields).
4. Season-level (162-game harness run): league average of each team's top-9 games-started is
   **145-155**; every team's second-catcher starts **≥ 35**. Measured by the new
   `summary["usage_kpis"]` harness aggregate (formulas below).
5. Existing KPI gates stay green (`--strict` exit 0) — bench bats are slightly worse, league
   offense may dip ~1%; `offense_scale` (config.py:11) is the corrective knob if `avg/obp/slg`
   breach tolerance.
6. `python -m pytest tests/test_rest_days.py -q` green.

## Files to change (verified anchors)

| File | Anchor | Change |
|---|---|---|
| `physics_sim/usage.py` | 19-24 (`BatterWorkload`) | add `last_rest_day: int \| None = None`, `rests: int = 0` |
| `physics_sim/config.py` | after 369 (`batter_fatigue_defense_scale`) | 6 new tuning keys |
| `physics_sim/engine.py` | new function above `simulate_game` (~3160); call inserted between 3303 and 3305 | `_apply_rest_days` + two call sites |
| `scripts/physics_sim_season_kpis.py` | 105-116 (`_load_player_names`); 539-541 (`batter_totals` — `g`/`gs` already aggregated via `batting_keys:547-572`); summary build ~714-758 | `usage_kpis` aggregate + positions loader |
| `tests/test_rest_days.py` | new | unit + smoke tests |

Verified plumbing facts the implementer can rely on:
- `UsageState.batter_workloads: Dict[str, BatterWorkload]` (usage.py:31); units: `fatigue_debt`
  in rating-scale points — game cost `6.0 + max(0,(50-durability))*0.02` (usage.py:122-124,
  config defaults 360-361), daily recovery `6.0 + durability*0.05` (usage.py:74-75, config
  358-359), in-game penalty threshold `35.0 + durability*0.45` (engine.py:2826-2827, config
  362-363). Net: only low-durability players drift upward while playing daily, so the
  consecutive-games rule below, not fatigue alone, produces routine rest days.
- `game_day` semantics: a league-wide game-DATE index, monotone within a season
  (`game_runner._physics_usage_context:83-84`; harness day_map at kpis.py:609-614). A team's
  off-date creates a `> 1` gap only when other teams play that date;
  `consecutive_days_used` resets on such gaps (usage.py:88-89, 126-129).
- Batting `gs` is set for every lineup member at game start (engine.py:3355-3359), flows
  through `_batter_line_summary` ("gs" key, 1083) into `meta["batting_lines"]`, and the harness
  already accumulates it per player (`batting_keys` includes "g","gs"; kpis.py:635-640).

## Exact implementation

### 1. `physics_sim/usage.py` — bookkeeping fields

```python
@dataclass
class BatterWorkload:
    fatigue_debt: float = 0.0
    last_used_day: int | None = None
    consecutive_days_used: int = 0
    last_update_day: int | None = None
    last_rest_day: int | None = None   # NEW: game_day of most recent forced rest
    rests: int = 0                     # NEW: season count of forced rests
```

(Defaults keep pickled/legacy states loadable; nothing serializes UsageState today — it is
in-memory per season, reset at `_physics_usage_context:69-82`.)

### 2. `physics_sim/config.py` — new keys (insert after line 369)

```python
"batter_rest_fatigue_ratio": 0.85,          # rest when debt >= ratio * in-game penalty threshold
"batter_rest_hard_ratio": 1.20,             # overrides the min-gap guard
"batter_rest_consecutive_limit": 9.0,       # non-catchers: rest on the 10th consecutive game day
"batter_rest_consecutive_limit_catcher": 3.0,  # catchers: rest on the 4th
"batter_rest_min_gap_days": 5.0,            # don't force-rest the same player again within 5 game days
"batter_rest_max_swaps": 2.0,               # per team per game
```

Constant rationale: limit 9 → a starter rests roughly every 10 consecutive league game dates ≈
14-17 rests over 162 → 145-155 starts. Catcher limit 3 → rest every 4th consecutive start ≈
38-42 backup starts, clearing the ≥35 gate even with schedule gaps resetting the counter.
Fatigue ratio 0.85 benches a player just BEFORE the in-game penalty starts (threshold at
engine.py:2826-2827), so degraded play is prevented rather than reacted to.

### 3. `physics_sim/engine.py` — `_apply_rest_days`

New module-level function placed directly above `simulate_game`:

```python
def _apply_rest_days(
    lineup: List[BatterRatings],
    bench: List[BatterRatings],
    positions: Dict[str, str],
    *,
    opposing_starter: PitcherRatings | None,
    usage_state: UsageState | None,
    game_day: int | None,
    tuning: TuningConfig,
) -> tuple[List[BatterRatings], List[BatterRatings], Dict[str, str]]:
    """Bench fatigued / overworked starters before the game. In-memory only;
    lineup files are never rewritten. Returns (lineup, bench, positions)."""
    if usage_state is None or game_day is None or not bench:
        return lineup, bench, positions
    lineup = list(lineup)
    bench = list(bench)
    positions = dict(positions)
    max_swaps = int(tuning.get("batter_rest_max_swaps", 2.0))
    ratio = tuning.get("batter_rest_fatigue_ratio", 0.85)
    hard_ratio = tuning.get("batter_rest_hard_ratio", 1.2)
    min_gap = tuning.get("batter_rest_min_gap_days", 5.0)
    swaps = 0
    for idx, starter in enumerate(list(lineup)):
        if swaps >= max_swaps:
            break
        wl = usage_state.batter_workload_for(starter.player_id)
        threshold = (
            tuning.get("batter_fatigue_threshold_base", 35.0)
            + starter.durability * tuning.get("batter_fatigue_threshold_scale", 0.45)
        )
        pos = (positions.get(starter.player_id) or starter.primary_position or "").upper()
        limit_key = (
            "batter_rest_consecutive_limit_catcher"
            if pos == "C"
            else "batter_rest_consecutive_limit"
        )
        limit = tuning.get(limit_key, 3.0 if pos == "C" else 9.0)
        fatigued = wl.fatigue_debt >= ratio * threshold
        overworked = wl.consecutive_days_used >= limit
        if not (fatigued or overworked):
            continue
        recently_rested = (
            wl.last_rest_day is not None and (game_day - wl.last_rest_day) < min_gap
        )
        if recently_rested and wl.fatigue_debt < hard_ratio * threshold:
            continue
        replacement = _best_rest_replacement(
            bench, pos, opposing_starter=opposing_starter, usage_state=usage_state,
            threshold_ratio=ratio, tuning=tuning,
        )
        if replacement is None:
            continue
        bench.remove(replacement)
        lineup[idx] = replacement                       # inherits the batting slot
        positions.pop(starter.player_id, None)
        positions[replacement.player_id] = pos          # inherits the defensive position
        wl.last_rest_day = game_day
        wl.rests += 1
        swaps += 1
    return lineup, bench, positions


def _best_rest_replacement(
    bench: List[BatterRatings],
    pos: str,
    *,
    opposing_starter: PitcherRatings | None,
    usage_state: UsageState,
    threshold_ratio: float,
    tuning: TuningConfig,
) -> BatterRatings | None:
    def eligible(b: BatterRatings) -> bool:
        if pos in {"", "DH"}:
            return True
        primary = (b.primary_position or "").upper()
        others = {str(x).upper() for x in (b.other_positions or [])}
        if pos == "C":
            return primary == "C" or "C" in others     # never emergency-catch
        return pos == primary or pos in others

    def rested(b: BatterRatings) -> bool:
        wl = usage_state.batter_workload_for(b.player_id)
        threshold = (
            tuning.get("batter_fatigue_threshold_base", 35.0)
            + b.durability * tuning.get("batter_fatigue_threshold_scale", 0.45)
        )
        return wl.fatigue_debt < threshold_ratio * threshold

    candidates = [b for b in bench if eligible(b) and rested(b)]
    if not candidates:
        return None
    if opposing_starter is not None:
        return max(candidates, key=lambda b: _batter_offense_score(b, opposing_starter))
    return max(candidates, key=lambda b: b.contact * 0.55 + b.power * 0.45)
```

Replacement scoring decision: `_batter_offense_score` (engine.py:2327-2328) — the same
platoon-aware comparator the engine already uses for pinch hitting, so the vs-hand-correct
bench bat starts (consistent with S2-06's symmetric `_platoon_bonus`).

Call sites — inside `simulate_game`, in the existing `if usage_state is not None and game_day
is not None:` block, between `advance_day` (3298-3303, so recovery is applied first and debt is
current) and `_apply_batter_fatigue` (3305):

```python
away_lineup, away_bench, away_positions = _apply_rest_days(
    list(away_lineup), list(away_bench), dict(away_positions),
    opposing_starter=home_pitchers[0] if home_pitchers else None,
    usage_state=usage_state, game_day=game_day, tuning=tuning,
)
home_lineup, home_bench, home_positions = _apply_rest_days(
    list(home_lineup), list(home_bench), dict(home_positions),
    opposing_starter=away_pitchers[0] if away_pitchers else None,
    usage_state=usage_state, game_day=game_day, tuning=tuning,
)
```

(`away_positions`/`home_positions` are normalized at 3263-3264; benches deduped at 3267-3272;
`away_pitchers[0]` is the game starter — ordering happens later at 3330-3343, but index 0 is
already the assigned starter in every caller: team_data.build_staff:210-221, game_runner
reorder_pitchers via prepare_team_state:506.) Because the swap runs before `LineupState` is
built (3345-3354), the replacement receives `g`/`gs` credit (3355-3359) and a starting fielding
line (3360-3362) automatically, and the rested player — removed from the bench — cannot be
pinch-hit back in. `record_batter_game` (5240-5277) then charges the replacement, not the
rested starter, keeping `consecutive_days_used` truthful.

### 4. Harness aggregate (`scripts/physics_sim_season_kpis.py`)

New loader (next to `_load_player_names:105-116`):

```python
def _load_player_positions(path: Path) -> dict[str, str]:
    positions: dict[str, str] = {}
    with path.open() as handle:
        for row in csv.DictReader(handle):
            pid = row.get("player_id")
            if pid:
                positions[str(pid)] = (row.get("primary_position") or "").strip().upper()
    return positions
```

In `run_sim`, after the leaders section (~line 826), using the existing `batter_totals`
(gs already accumulated) and `player_teams`:

```python
positions_by_id = _load_player_positions(players_path)
team_top9_means: list[float] = []
backup_c_starts: dict[str, int] = {}
by_team: dict[str, list[tuple[str, int]]] = defaultdict(list)
for pid, stats in batter_totals.items():
    by_team[player_teams.get(pid, "")].append((pid, int(stats.get("gs", 0))))
for team_id, entries in by_team.items():
    if not team_id:
        continue
    top9 = sorted((gs for _pid, gs in entries), reverse=True)[:9]
    if top9:
        team_top9_means.append(sum(top9) / len(top9))
    c_starts = sorted(
        (gs for pid, gs in entries if positions_by_id.get(pid) == "C"), reverse=True
    )
    backup_c_starts[team_id] = c_starts[1] if len(c_starts) > 1 else 0
summary["usage_kpis"] = {
    "starters_avg_gs": (sum(team_top9_means) / len(team_top9_means)) if team_top9_means else 0.0,
    "backup_c_min_starts": min(backup_c_starts.values()) if backup_c_starts else 0,
    "backup_c_starts": backup_c_starts,
}
```

Formula statement: `starters_avg_gs` = league mean over teams of (mean of that team's nine
largest per-player batting `gs` totals); `backup_c_min_starts` = league minimum over teams of
the second-largest `gs` among players whose `players.csv primary_position == "C"`. Gates
(checked manually / in the smoke test, NOT via `DEFAULT_TOLERANCES` since they are bands on a
per-run aggregate): `145 <= starters_avg_gs <= 155` and `backup_c_min_starts >= 35` at
`--games 162`.

## Edge cases

- **No bench / all-bench fatigued or ineligible**: `_best_rest_replacement` returns None → the
  tired starter plays (in-game fatigue penalty still applies). Never leaves a hole.
- **Catcher with no backup C on the ACT roster**: `eligible` requires real C eligibility → no
  swap; the acceptance gate makes such roster construction a data problem surfaced by
  `backup_c_starts`.
- **DH slot** (`pos == "DH"` or missing position): any rested bench bat is eligible.
- **Both catcher and another starter due the same day**: `max_swaps = 2` allows both; a third
  candidate waits (guards against gutting a lineup on day-1 of stale UsageState).
- **Doubleheaders** (same `game_day` twice): `advance_day` no-ops (`days_passed <= 0`,
  usage.py:83-84); a player rested in game 1 has `last_rest_day == game_day` → the min-gap
  guard keeps him from being re-rested, and the game-1 replacement accrues normally.
- **Fresh UsageState mid-season** (league switch/reset, `_physics_usage_context:69-82`): all
  workloads zero → no swaps until history rebuilds; harmless.
- **Tiny leagues / exhibition** (`usage_state None`): function is a no-op passthrough.
- **Switch-hitters / missing ratings**: replacement scoring uses `_batter_offense_score`,
  which handles `bats == "S"` and defaults via S2-06.

## Test plan

New file `tests/test_rest_days.py` (unit tests call `_apply_rest_days` directly with
hand-built `BatterRatings` — keyword construction per `BatterRatings.from_row` field list,
models.py:10-70 — and `load_tuning()`):

- `test_fatigued_starter_is_benched` — starter durability 50, `fatigue_debt = 60.0`
  (≥ 0.85×57.5): swapped; replacement inherits slot index and position; starter absent from
  returned bench; `wl.last_rest_day == game_day`, `wl.rests == 1`.
- `test_consecutive_limit_benches_catcher` — C with `consecutive_days_used = 3`, zero debt:
  swapped for the bench C; a 1B with the same counter is NOT swapped (limit 9).
- `test_no_eligible_replacement_no_swap` — bench lacks a C: catcher plays on.
- `test_min_gap_prevents_repeat_rest` — `last_rest_day = game_day - 2`, debt at 0.9×threshold:
  no swap; at 1.3×threshold (≥ hard_ratio): swap.
- `test_max_two_swaps_per_game` — 3 fatigued starters, ample bench: exactly 2 swaps.
- `test_noop_without_usage_state` — returns inputs unchanged (identity of contents).
- `test_replacement_gets_gs_credit` — full `simulate_game` (18 batters + 2 bench, 2 pitchers,
  fixed seed, `usage_state` with one forced-fatigued starter): rested starter absent from
  `metadata["batting_lines"]`, replacement line has `gs == 1`.
- `test_season_rest_distribution` (smoke, mark `@pytest.mark.slow`): loop
  `simulate_game` 40 consecutive `game_day`s with one shared `UsageState`, same two teams,
  bench of 3 including a backup C: assert the primary C starts ≤ 33 of 40 and every non-C
  starter starts ≥ 34 of 40, and no player's `rests` exceeds 12.

Run: `python -m pytest tests/test_rest_days.py -q` (slow test:
`python -m pytest tests/test_rest_days.py -q -m slow`).

Season acceptance:
`python scripts/physics_sim_season_kpis.py --games 162 --seed 1 --strict --output reports/kpi_s2-05.json`
then check `usage_kpis.starters_avg_gs ∈ [145, 155]` and `usage_kpis.backup_c_min_starts >= 35`.
Tuning order if out of band: adjust `batter_rest_consecutive_limit` (±1) first, then the
catcher limit (±1); leave fatigue ratios fixed.

## Non-goals

- Persisting rest decisions to lineup files or exposing them in the UI (in-memory only;
  decision-log/UI surfacing is a follow-up).
- Pitcher rest (already handled via `record_outing`/rest-day tuning, config.py:341-357).
- Injury-list interaction (ACT filtering already excludes DL players upstream).
- Legacy `playbalance` engine benching.
- Minor-league / farm-system usage tracking.
- Serializing `UsageState` across process restarts (pre-existing limitation, unchanged).
