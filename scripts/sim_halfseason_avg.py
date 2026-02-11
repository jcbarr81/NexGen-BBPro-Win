"""Simulate a half 81-game season and report average box score stats.

For lengthy runs this script can benefit from PyPy's JIT or by invoking
CPython with ``python -O`` to skip asserts. When using PyPy ensure required
C extensions such as ``bcrypt`` are available; GUI-focused modules like
``PyQt6`` are not needed here.
"""

from __future__ import annotations
import os
try:
    import psutil

    p = psutil.Process()

    # --- Set priority ---
    try:
        # Default: High priority
        p.nice(psutil.HIGH_PRIORITY_CLASS)
        # Alternatives:
        # p.nice(psutil.REALTIME_PRIORITY_CLASS)   # DANGEROUS: may freeze system
        # p.nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
        print(f"[PerfTune] Process priority set to High")
    except Exception as e:
        print(f"[PerfTune] Could not set priority: {e}")

    # --- Set CPU affinity (all logical CPUs) ---
    try:
        cpu_count = os.cpu_count() or 1
        p.cpu_affinity(list(range(cpu_count)))
        print(f"[PerfTune] CPU affinity set to all {cpu_count} cores")
    except Exception as e:
        print(f"[PerfTune] Could not set CPU affinity: {e}")

except ImportError:
    print("[PerfTune] psutil not installed; skipping priority/affinity tuning")

# --- Threading environment (vectorized libs like numpy, MKL, OpenMP) ---

from collections import Counter
from datetime import date
from pathlib import Path
import argparse
import csv
import random
import sys
import multiprocessing as mp

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover
    def tqdm(iterable, **kwargs):
        return iterable

# Ensure project root is on the path when running this script directly
sys.path.append(str(Path(__file__).resolve().parent.parent))

from playbalance.legacy_guard import require_legacy_enabled

require_legacy_enabled("Legacy playbalance half-season script")

from playbalance.schedule_generator import generate_mlb_schedule
from playbalance.simulation import (
    FieldingState,
    GameSimulation,
    TeamState,
    generate_boxscore,
)
from playbalance.state import PitcherState
from playbalance.playbalance_config import PlayBalanceConfig
from utils.lineup_loader import build_default_game_state
from utils.safe_copy import deepcopy
from utils.path_utils import get_base_dir
from utils.team_loader import load_teams


STAT_ORDER = [
    "Runs",
    "Hits",
    "Doubles",
    "Triples",
    "HomeRuns",
    "Walks",
    "Strikeouts",
    "StolenBases",
    "CaughtStealing",
    "HitByPitch",
    "TotalPitchesThrown",
    "Strikes",
]


def clone_team_state(base: TeamState) -> TeamState:
    """Return a deep-copied ``TeamState`` with per-game fields reset."""

    team = deepcopy(base)
    team.lineup_stats = {}
    team.pitcher_stats = {}
    team.fielding_stats = {}
    team.batting_index = 0
    team.bases = [None, None, None]
    team.base_pitchers = [None, None, None]
    team.runs = 0
    team.inning_runs = []
    team.lob = 0
    team.inning_lob = []
    team.inning_events = []
    team.team_stats = {}
    team.warming_reliever = False
    team.bullpen_warmups = {}
    if team.pitchers:
        starter = team.pitchers[0]
        state = PitcherState()
        state.player = starter
        team.pitcher_stats[starter.player_id] = state
        team.current_pitcher_state = state
        state.g = getattr(state, "g", 0) + 1
        state.gs = getattr(state, "gs", 0) + 1
        fs = team.fielding_stats.setdefault(starter.player_id, FieldingState(starter))
        fs.g += 1
        fs.gs += 1
    else:
        team.current_pitcher_state = None
    for p in team.lineup:
        fs = team.fielding_stats.setdefault(p.player_id, FieldingState(p))
        fs.g += 1
        fs.gs += 1
    return team


# Global objects used by worker processes
_BASE_STATES: dict[str, TeamState] | None = None
_CFG: PlayBalanceConfig | None = None


def _init_pool(base_states: dict[str, TeamState], cfg: PlayBalanceConfig) -> None:
    """Initializer to share state across worker processes."""

    global _BASE_STATES, _CFG
    _BASE_STATES = base_states
    _CFG = cfg


def _simulate_game(home_id: str, away_id: str, seed: int) -> Counter[str]:
    """Simulate a single game and return stat totals for both teams."""

    assert _BASE_STATES is not None and _CFG is not None
    home = clone_team_state(_BASE_STATES[home_id])
    away = clone_team_state(_BASE_STATES[away_id])
    rng = random.Random(seed)
    sim = GameSimulation(home, away, _CFG, rng)
    sim.simulate_game()
    box = generate_boxscore(home, away)
    totals: Counter[str] = Counter()
    for side in ("home", "away"):
        batting = box[side]["batting"]
        pitching = box[side]["pitching"]
        totals["Runs"] += box[side]["score"]
        totals["Hits"] += sum(p["h"] for p in batting)
        totals["Doubles"] += sum(p["2b"] for p in batting)
        totals["Triples"] += sum(p["3b"] for p in batting)
        totals["HomeRuns"] += sum(p["hr"] for p in batting)
        totals["Walks"] += sum(p["bb"] for p in batting)
        totals["Strikeouts"] += sum(p["so"] for p in batting)
        totals["StolenBases"] += sum(p["sb"] for p in batting)
        totals["CaughtStealing"] += sum(p["cs"] for p in batting)
        totals["HitByPitch"] += sum(p["hbp"] for p in batting)
        totals["TotalPitchesThrown"] += sum(p["pitches"] for p in pitching)
        totals["Strikes"] += sum(p["strikes"] for p in pitching)
    totals["TwoStrikeCounts"] += sim.two_strike_counts
    totals["ThreeBallCounts"] += sim.three_ball_counts
    return totals


def simulate_halfseason_average(
    use_tqdm: bool = True
) -> None:
    """Run a half-season simulation and print average box score values.

    Args:
        use_tqdm: Whether to display a progress bar using ``tqdm``.
    """

    teams = [t.team_id for t in load_teams()]
    schedule = generate_mlb_schedule(teams, date(2025, 4, 1), 81)
    base_states = {tid: build_default_game_state(tid) for tid in teams}

    cfg = PlayBalanceConfig.from_file(get_base_dir() / "playbalance" / "PBINI.txt")

    csv_path = (
        get_data_dir()
        / "MLB_avg"
        / "mlb_avg_boxscore_2020_2024_both_teams.csv"
    )
    with csv_path.open(newline="") as f:
        row = next(csv.DictReader(f))
    hits = float(row["Hits"])
    singles = (
        hits
        - float(row["Doubles"])
        - float(row["Triples"])
        - float(row["HomeRuns"])
    )
    cfg.hit1BProb = int(round(singles / hits * 100))
    cfg.hit2BProb = int(round(float(row["Doubles"]) / hits * 100))
    cfg.hit3BProb = int(round(float(row["Triples"]) / hits * 100))
    cfg.hitHRProb = max(
        0,
        100 - cfg.hit1BProb - cfg.hit2BProb - cfg.hit3BProb,
    )
    mlb_averages = {stat: float(val) for stat, val in row.items() if stat}

    # Prepare list of (home, away, seed) tuples for multiprocessing
    games = [
        (g["home"], g["away"], 42 + i) for i, g in enumerate(schedule)
    ]
    iterator = games
    if use_tqdm:
        iterator = tqdm(iterator, total=len(games), desc="Simulating season")

    # ``spawn`` start method on Windows requires all objects to be picklable.
    # ``TeamState`` and ``PlayBalanceConfig`` are complex and can trigger
    # pickling errors, so fall back to a simple sequential loop when the
    # ``spawn`` method is active.  This keeps the function usable on Windows
    # while still taking advantage of multiprocessing on Unix-like systems.
    use_pool = mp.get_start_method() != "spawn"

    if use_pool:
        with mp.Pool(initializer=_init_pool, initargs=(base_states, cfg)) as pool:
            results = pool.starmap(_simulate_game, iterator)
    else:  # pragma: no cover - exercised only on Windows
        _init_pool(base_states, cfg)
        results = [_simulate_game(h, a, s) for h, a, s in iterator]

    totals: Counter[str] = Counter()
    for game_totals in results:
        totals.update(game_totals)
    total_games = len(results)

    averages = {k: totals[k] / total_games for k in STAT_ORDER}

    diffs = {k: averages[k] - mlb_averages.get(k, 0.0) for k in STAT_ORDER}

    print("Average box score per game (both teams):")
    for key in STAT_ORDER:
        mlb_val = mlb_averages[key]
        sim_val = averages[key]
        diff = diffs[key]
        print(
            f"{key}: MLB {mlb_val:.2f}, Sim {sim_val:.2f}, Diff {diff:+.2f}"
        )
    print(f"Total two-strike counts: {totals['TwoStrikeCounts']}")
    print(f"Total three-ball counts: {totals['ThreeBallCounts']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Simulate a half season and report average box score stats."
    )
    parser.add_argument(
        "--disable-tqdm",
        action="store_true",
        help="Disable tqdm progress bar.",
    )
    args = parser.parse_args()

    env_disable = os.getenv("DISABLE_TQDM", "").lower() in {"1", "true", "yes"}
    use_tqdm = not (args.disable_tqdm or env_disable)
    simulate_halfseason_average(use_tqdm=use_tqdm)
