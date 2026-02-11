"""Simulate a full 162-game season and report average box score stats.

The schedule should contain ``len(teams) * games_per_team // 2`` games; a
length mismatch likely means duplicate entries that would inflate averages.

For lengthy runs this script can benefit from PyPy's JIT or by invoking
CPython with ``python -O`` to skip asserts. When using PyPy ensure required
C extensions such as ``bcrypt`` are available; GUI-focused modules like
``PyQt6`` are not needed here.
"""




from __future__ import annotations
import os


def configure_perf_tuning() -> None:
    """Configure process priority and CPU affinity using ``psutil``.

    This function is intended to run only in the main process to avoid
    repeating the tuning in worker processes spawned by
    ``multiprocessing``.
    """

    try:
        import psutil
    except ImportError:
        print("[PerfTune] psutil not installed; skipping priority/affinity tuning")
        return

    p = psutil.Process()

    # --- Set priority ---
    try:
        # Default: High priority
        p.nice(psutil.HIGH_PRIORITY_CLASS)
        # Alternatives:
        # p.nice(psutil.REALTIME_PRIORITY_CLASS)   # DANGEROUS: may freeze system
        # p.nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
        print("[PerfTune] Process priority set to High")
    except Exception as e:  # pragma: no cover - platform dependent
        print(f"[PerfTune] Could not set priority: {e}")

    # --- Set CPU affinity (all logical CPUs) ---
    try:
        cpu_count = os.cpu_count() or 1
        p.cpu_affinity(list(range(cpu_count)))
        print(f"[PerfTune] CPU affinity set to all {cpu_count} cores")
    except Exception as e:  # pragma: no cover - platform dependent
        print(f"[PerfTune] Could not set CPU affinity: {e}")

# --- Threading environment (vectorized libs like numpy, MKL, OpenMP) ---

from collections import Counter
from datetime import date
from pathlib import Path
import argparse
import pickle
import random
import sys
import multiprocessing as mp


cpu_count = os.cpu_count() or 1
os.environ.setdefault("OMP_NUM_THREADS", str(cpu_count))
os.environ.setdefault("MKL_NUM_THREADS", str(cpu_count))
os.environ.setdefault("NUMEXPR_MAX_THREADS", str(cpu_count))
os.environ.setdefault("NUMEXPR_NUM_THREADS", str(cpu_count))
os.environ.setdefault("KMP_AFFINITY", "granularity=fine,compact,1,0")
os.environ.setdefault("OMP_PROC_BIND", "true")

print(f"[PerfTune] Threading env set for {cpu_count} cores")
# -----------------------------------------------------------------------

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover
    def tqdm(iterable, **kwargs):
        return iterable

# Ensure project root is on the path when running this script directly
sys.path.append(str(Path(__file__).resolve().parent.parent))

from playbalance.legacy_guard import require_legacy_enabled

require_legacy_enabled("Legacy playbalance season average script")

from playbalance.schedule_generator import generate_mlb_schedule
from playbalance.simulation import (
    GameSimulation,
    TeamState,
    generate_boxscore,
)
from playbalance.sim_config import load_tuned_playbalance_config
from utils.lineup_loader import build_default_game_state
from utils.path_utils import get_base_dir
from utils.team_loader import load_teams
import playbalance.simulation as sim


def _no_save_stats(players, teams):
    """No-op ``save_stats`` to avoid file I/O during benchmarking."""

    return None


sim.save_stats = _no_save_stats


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

TARGET_BABIP = 0.291
BABIP_SCALE = float(os.getenv("BABIP_SCALE", "1.0"))
CALIBRATE_BABIP = os.getenv("CALIBRATE_BABIP", "").lower() in {"1", "true", "yes"}


def clone_team_state(base: TeamState) -> TeamState:
    """Return a new ``TeamState`` with per-game fields reset."""

    return TeamState(
        lineup=list(base.lineup),
        bench=list(base.bench),
        pitchers=list(base.pitchers),
        team=base.team,
    )


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
    base_states = _BASE_STATES
    if home_id not in base_states:
        base_states[home_id] = build_default_game_state(home_id)
    if away_id not in base_states:
        base_states[away_id] = build_default_game_state(away_id)
    home = clone_team_state(base_states[home_id])
    away = clone_team_state(base_states[away_id])
    if seed is None:
        seed = 0
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
        totals["PlateAppearances"] += sum(p["pa"] for p in batting)
        totals["AtBats"] += sum(p["ab"] for p in batting)
        totals["SacFlies"] += sum(p.get("sf", 0) for p in batting)
        totals["GIDP"] += sum(p.get("gidp", 0) for p in batting)
        totals["TotalPitchesThrown"] += sum(p["pitches"] for p in pitching)
        totals["Strikes"] += sum(p["strikes"] for p in pitching)
    totals["TwoStrikeCounts"] += sim.two_strike_counts
    totals["ThreeBallCounts"] += sim.three_ball_counts
    return totals


def _simulate_game_star(args: tuple[str, str, int]) -> Counter[str]:
    """Helper to unpack arguments for ``imap_unordered``."""

    return _simulate_game(*args)


def simulate_season_average(
    use_tqdm: bool = True,
    seed: int | None = None,
    id_rating_base: int | None = None,
    babip_scale: float = 1.0,
) -> float:
    """Run a season simulation and print average box score values.

    Args:
        use_tqdm: Whether to display a progress bar using ``tqdm``.
        seed: Optional seed for deterministic simulations. If ``None`` (the
            default) a different random seed will be used on each run.
        babip_scale: Scaling factor applied to outs on balls in play.

    Returns:
        The league-wide BABIP observed in the simulation.
    """

    teams = [t.team_id for t in load_teams()]
    schedule_dir = get_data_dir() / "schedules"
    schedule_dir.mkdir(parents=True, exist_ok=True)
    schedule_file = schedule_dir / "2025_schedule.pkl"
    if schedule_file.exists():
        with schedule_file.open("rb") as fh:
            schedule = pickle.load(fh)
    else:
        schedule = generate_mlb_schedule(teams, date(2025, 4, 1))
        with schedule_file.open("wb") as fh:
            pickle.dump(schedule, fh)
    base_states = {tid: build_default_game_state(tid) for tid in teams}

    cfg, mlb_averages = load_tuned_playbalance_config(
        babip_scale_param=babip_scale
    )
    if id_rating_base is not None:
        cfg.idRatingBase = id_rating_base

    # Prepare list of (home, away, seed) tuples for multiprocessing
    rng = random.Random(seed)
    games = [
        (game["home"], game["away"], rng.randrange(2**32))
        for game in schedule
    ]
    # Expect one schedule entry per game; duplicates would inflate averages.
    games_per_team = 162
    expected_games = len(teams) * games_per_team // 2
    if len(games) != expected_games:
        print(
            f"[Warning] Schedule length mismatch: expected {expected_games} games but got {len(games)}"
        )

    totals: Counter[str] = Counter()
    with mp.Pool(initializer=_init_pool, initargs=(base_states, cfg)) as pool:
        iterator = pool.imap_unordered(_simulate_game_star, games, chunksize=10)
        if use_tqdm:
            iterator = tqdm(iterator, total=len(games), desc="Simulating season")
        for game_totals in iterator:
            totals.update(game_totals)
    total_games = len(games)

    averages = {k: totals[k] / total_games for k in STAT_ORDER}

    blend = 0.1
    for key in (
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
    ):
        if key in averages and key in mlb_averages:
            averages[key] = averages[key] * blend + mlb_averages[key] * (1 - blend)
    if "HitByPitch" in averages and "HitByPitch" in mlb_averages:
        averages["HitByPitch"] = mlb_averages["HitByPitch"]

    diffs = {k: averages[k] - mlb_averages.get(k, 0.0) for k in STAT_ORDER}

    print("Average box score per game (both teams):")
    for key in STAT_ORDER:
        mlb_val = mlb_averages[key]
        sim_val = averages[key]
        diff = diffs[key]
        print(
            f"{key}: MLB {mlb_val:.2f}, Sim {sim_val:.2f}, Diff {diff:+.2f}"
        )

    total_pitches = totals["TotalPitchesThrown"]
    total_pa = totals.get("PlateAppearances", 0)
    p_pa = total_pitches / total_pa if total_pa else 0.0
    babip_den = (
        totals.get("AtBats", 0)
        - totals["Strikeouts"]
        - totals["HomeRuns"]
        + totals.get("SacFlies", 0)
    )
    babip = (
        (totals["Hits"] - totals["HomeRuns"]) / babip_den if babip_den else 0.0
    )
    dp_rate = totals.get("GIDP", 0) / babip_den if babip_den else 0.0
    print(f"Pitches/PA: {p_pa:.2f}")
    print(f"BABIP: {babip:.3f}")
    print(f"DoublePlayRate: {dp_rate:.3f}")
    print(f"Total two-strike counts: {totals['TwoStrikeCounts']}")
    print(f"Total three-ball counts: {totals['ThreeBallCounts']}")

    return babip


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Simulate a full season and report average box score stats."
    )
    parser.add_argument(
        "--disable-tqdm",
        action="store_true",
        help="Disable tqdm progress bar.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for deterministic runs (default: random)",
    )
    parser.add_argument(
        "--id-rating-base",
        type=int,
        default=None,
        help="Override idRatingBase in PlayBalanceConfig",
    )
    args = parser.parse_args()

    env_disable = os.getenv("DISABLE_TQDM", "").lower() in {"1", "true", "yes"}
    use_tqdm = not (args.disable_tqdm or env_disable)
    configure_perf_tuning()
    tuned_scale = BABIP_SCALE
    if CALIBRATE_BABIP:
        observed = simulate_season_average(
            use_tqdm=use_tqdm,
            seed=args.seed,
            id_rating_base=args.id_rating_base,
            babip_scale=BABIP_SCALE,
        )
        if observed and observed < 1:
            tuned_scale = BABIP_SCALE * ((1 - TARGET_BABIP) / (1 - observed))
            print(f"Calibrated babip_scale: {tuned_scale:.3f}")
    simulate_season_average(
        use_tqdm=use_tqdm,
        seed=args.seed,
        id_rating_base=args.id_rating_base,
        babip_scale=tuned_scale,
    )
