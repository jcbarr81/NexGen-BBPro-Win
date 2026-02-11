"""Collect pitch survival (pitches per PA) diagnostics."""
from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from playbalance.legacy_guard import require_legacy_enabled

require_legacy_enabled("Legacy playbalance diagnostics script")

from playbalance.diagnostics.pitch_survival import PitchSurvivalTracker
from playbalance.orchestrator import _clone_team_state
from playbalance.sim_config import load_tuned_playbalance_config
from playbalance.simulation import GameSimulation
from utils.league_benchmarks import load_league_benchmarks
from utils.lineup_loader import build_default_game_state
from utils.path_utils import get_base_dir


def _disable_calibration(cfg) -> None:
    cfg.pitchCalibrationEnabled = 0
    if hasattr(cfg, "values"):
        cfg.values["pitchCalibrationEnabled"] = 0
    if hasattr(cfg, "targetPitchesPerPA"):
        cfg.targetPitchesPerPA = 0
    if hasattr(cfg, "values"):
        cfg.values["targetPitchesPerPA"] = 0


@dataclass
class SurvivalSample:
    tracker: PitchSurvivalTracker
    games: int
    deterministic: bool

    def to_summary(self) -> dict:
        metrics = self.tracker.metrics()
        metrics["games"] = self.games
        metrics["deterministic"] = self.deterministic
        return metrics


def _collect_sample(
    *,
    num_games: int,
    seed: int,
    deterministic: bool,
    home_base,
    away_base,
) -> SurvivalSample:
    tracker = PitchSurvivalTracker()

    cfg, _ = load_tuned_playbalance_config()
    _disable_calibration(cfg)

    home_len = max(1, len(home_base.pitchers))
    away_len = max(1, len(away_base.pitchers))
    rotation_idx = {"home": 0, "away": 0}
    rng = random.Random(seed)

    for game_index in range(num_games):
        home = _clone_team_state(home_base)
        away = _clone_team_state(away_base)
        if home.pitchers:
            rot = rotation_idx["home"]
            home.pitchers = home.pitchers[rot:] + home.pitchers[:rot]
            rotation_idx["home"] = (rot + 1) % home_len
        if away.pitchers:
            rot = rotation_idx["away"]
            away.pitchers = away.pitchers[rot:] + away.pitchers[:rot]
            rotation_idx["away"] = (rot + 1) % away_len

        game_seed = seed + game_index if deterministic else rng.randrange(2**32)
        sim = GameSimulation(home, away, cfg, random.Random(game_seed))
        sim.set_pitch_survival_tracker(tracker)
        sim.simulate_game(persist_stats=False)

    return SurvivalSample(tracker=tracker, games=num_games, deterministic=deterministic)


def _write_curve_csv(path: Path, tracker: PitchSurvivalTracker) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["pitch", "alive_prob", "resolved_prob"])
        for row in tracker.survival_curve():
            writer.writerow([row["pitch"], row["alive"], row["resolved"]])


def _write_distribution_csv(path: Path, tracker: PitchSurvivalTracker) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["pitches", "plate_appearances"])
        for pitches, count in tracker.distribution().items():
            writer.writerow([pitches, count])


def run(
    output_dir: Path,
    *,
    stochastic_games: int = 200,
    deterministic_games: int = 10,
) -> dict:
    base_dir = Path(__file__).resolve().parents[1]
    players = base_dir / "data" / "players.csv"
    rosters = base_dir / "data" / "rosters"
    teams_file = base_dir / "data" / "teams.csv"

    home_base = build_default_game_state(
        "ABU", players_file=str(players), roster_dir=str(rosters), teams_file=str(teams_file)
    )
    away_base = build_default_game_state(
        "BCH", players_file=str(players), roster_dir=str(rosters), teams_file=str(teams_file)
    )

    stochastic = _collect_sample(
        num_games=stochastic_games,
        seed=2025,
        deterministic=False,
        home_base=home_base,
        away_base=away_base,
    )
    deterministic = _collect_sample(
        num_games=deterministic_games,
        seed=2025,
        deterministic=True,
        home_base=home_base,
        away_base=away_base,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_curve_csv(output_dir / "pitch_survival_curve_stochastic.csv", stochastic.tracker)
    _write_curve_csv(output_dir / "pitch_survival_curve_deterministic.csv", deterministic.tracker)
    _write_distribution_csv(
        output_dir / "pitch_survival_distribution_stochastic.csv", stochastic.tracker
    )
    _write_distribution_csv(
        output_dir / "pitch_survival_distribution_deterministic.csv", deterministic.tracker
    )

    summary = {
        "stochastic": stochastic.to_summary(),
        "deterministic": deterministic.to_summary(),
    }
    with (output_dir / "pitch_survival_summary.json").open("w") as fh:
        json.dump(summary, fh, indent=2)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect pitch survival diagnostics.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/notes/pitch_survival"),
        help="Directory to store CSV/JSON outputs (default: docs/notes/pitch_survival)",
    )
    parser.add_argument(
        "--stochastic-games",
        type=int,
        default=200,
        help="Number of stochastic games to sample (default: 200)",
    )
    parser.add_argument(
        "--deterministic-games",
        type=int,
        default=10,
        help="Number of deterministic games to sample (default: 10)",
    )
    args = parser.parse_args()
    summary = run(
        args.output_dir,
        stochastic_games=args.stochastic_games,
        deterministic_games=args.deterministic_games,
    )
    print(json.dumps(summary, indent=2))

    bench_path = get_data_dir() / "MLB_avg" / "mlb_league_benchmarks_2025_filled.csv"
    try:
        mlb_metrics = load_league_benchmarks(bench_path)
    except FileNotFoundError:
        print(f"[Warning] MLB benchmark file not found at {bench_path}")
        return

    mlb_p_pa = mlb_metrics.get("pitches_per_pa")
    if mlb_p_pa:
        sim_p_pa = summary["stochastic"]["mean_pitches"]
        diff = sim_p_pa - mlb_p_pa
        print(
            f"Pitches/PA: MLB {mlb_p_pa:.2f}, Sim {sim_p_pa:.2f}, Diff {diff:+.2f}"
        )


if __name__ == "__main__":
    main()
