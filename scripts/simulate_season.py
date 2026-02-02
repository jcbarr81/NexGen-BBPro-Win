"""Simulate a full 162-game season and report average box score stats.

For lengthy runs this script can benefit from PyPy's JIT or by invoking
CPython with ``python -O`` to skip asserts. When using PyPy ensure required
C extensions such as ``bcrypt`` are available; GUI-focused modules like
``PyQt6`` are not needed here.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
import argparse
import os
import random
import sys

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover
    def tqdm(iterable, **kwargs):
        return iterable

# Ensure project root is on the path when running this script directly
sys.path.append(str(Path(__file__).resolve().parent.parent))

from playbalance.legacy_guard import require_legacy_enabled

require_legacy_enabled("Legacy playbalance season simulation script")

from playbalance.schedule_generator import generate_mlb_schedule
from playbalance.season_simulator import SeasonSimulator
from playbalance.simulation import (
    FieldingState,
    GameSimulation,
    TeamState,
    generate_boxscore,
)
from playbalance.state import PitcherState
from utils.lineup_loader import build_default_game_state
from utils.safe_copy import deepcopy
from utils.path_utils import get_base_dir
from utils.team_loader import load_teams
from playbalance.sim_config import load_tuned_playbalance_config


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


def simulate_season_average(
    use_tqdm: bool = True,
    seed: int | None = None,
    babip_scale: float = 1.0,
    baserunning_aggression: float | None = None,
) -> float:
    """Run a season simulation and print average box score values.

    Args:
        use_tqdm: Whether to display a progress bar using ``tqdm``.
        seed: Optional seed for deterministic simulations. If ``None`` (the
            default) a different random seed will be used on each run.
        babip_scale: Scaling factor applied to outs on balls in play.
        baserunning_aggression: Optional aggression factor for baserunning
            decisions. When ``None`` the configuration default is used.
    """

    teams = [t.team_id for t in load_teams()]
    schedule = generate_mlb_schedule(teams, date(2025, 4, 1))
    base_states = {tid: build_default_game_state(tid) for tid in teams}

    cfg, mlb_averages = load_tuned_playbalance_config(
        babip_scale_param=babip_scale,
        baserunning_aggression=baserunning_aggression,
    )

    rng = random.Random(seed)

    totals: Counter[str] = Counter()
    total_games = 0

    def simulate_game(home_id: str, away_id: str) -> tuple[int, int]:
        nonlocal total_games

        home = clone_team_state(base_states[home_id])
        away = clone_team_state(base_states[away_id])
        sim = GameSimulation(home, away, cfg, rng)
        sim.simulate_game()
        box = generate_boxscore(home, away)

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

        total_games += 1
        return box["home"]["score"], box["away"]["score"]

    simulator = SeasonSimulator(schedule, simulate_game=simulate_game)
    iterator = range(len(simulator.dates))
    if use_tqdm:
        iterator = tqdm(iterator, desc="Simulating season")
    for _ in iterator:
        simulator.simulate_next_day()

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
        "--baserunning-aggression",
        type=float,
        default=None,
        help="Aggression factor for baserunning decisions (default: config value)",
    )
    args = parser.parse_args()

    env_disable = os.getenv("DISABLE_TQDM", "").lower() in {"1", "true", "yes"}
    use_tqdm = not (args.disable_tqdm or env_disable)
    tuned_scale = BABIP_SCALE
    if CALIBRATE_BABIP:
        observed = simulate_season_average(
            use_tqdm=use_tqdm,
            seed=args.seed,
            babip_scale=BABIP_SCALE,
            baserunning_aggression=args.baserunning_aggression,
        )
        if observed and observed < 1:
            tuned_scale = BABIP_SCALE * ((1 - TARGET_BABIP) / (1 - observed))
            print(f"Calibrated babip_scale: {tuned_scale:.3f}")
    simulate_season_average(
        use_tqdm=use_tqdm,
        seed=args.seed,
        babip_scale=tuned_scale,
        baserunning_aggression=args.baserunning_aggression,
    )
