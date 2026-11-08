"""Convert calibration games to viewer plays and check every one
(backlog #74 step 2; ``services/replay_plays.py``).

Plays a number of calibration games (``data/calibration``, the KPI
fixture), builds each one's stored replay exactly as a season game does,
converts it with :func:`services.replay_plays.build_plays` and runs
:func:`services.replay_plays.check_plays`: every runner ends where the
engine put him, outs and runs add up, every out's throw beats the runner,
every safe runner beats the throw.

    python scripts/check_replay_plays.py --games 30
    python scripts/check_replay_plays.py --games 10 --generations 7 --show 5

Exits 1 when any play has a problem. Never touches a league.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.physics_sim_season_kpis as kpis  # noqa: E402
from physics_sim.engine import simulate_matchup_from_files  # noqa: E402
from physics_sim.engine_generation import engine_profile  # noqa: E402
from services import game_replay, replay_plays  # noqa: E402

CAL = ROOT / "data" / "calibration"
PLAYERS = CAL / "players.csv"
TEAMS = [f"CAL{n:02d}" for n in range(1, 9)]


def play_game(seed: int, generation: int) -> dict:
    overrides = kpis.with_rating_centers(
        engine_profile(generation, development=True), PLAYERS, CAL
    )
    away = TEAMS[seed % len(TEAMS)]
    home = TEAMS[(seed + 3) % len(TEAMS)]
    result = simulate_matchup_from_files(
        away_team=away, home_team=home, players_path=PLAYERS, base_dir=CAL,
        seed=seed, tuning_overrides=overrides,
    )
    return game_replay.build_replay(
        result, home_id=home, away_id=away, seed=seed, engine_generation=generation,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--games", type=int, default=12, help="games per generation")
    parser.add_argument("--generations", default="5,6,7")
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--show", type=int, default=10, help="problems to print")
    parser.add_argument("--dump", type=Path, help="write the first game's plays here")
    args = parser.parse_args(argv)

    total_plays = 0
    problems: list[str] = []
    kinds: collections.Counter = collections.Counter()
    silent = 0
    for generation in (int(g) for g in args.generations.split(",") if g):
        for n in range(args.games):
            seed = args.seed + n
            doc = replay_plays.build_plays(play_game(seed, generation))
            if args.dump and n == 0:
                args.dump.write_text(json.dumps(doc), encoding="utf-8")
                args.dump = None
            total_plays += len(doc["plays"])
            for play in doc["plays"]:
                if play["key"] and not play["ball"] and not play["runners"]:
                    silent += 1
                    problems.append(f"gen {generation} seed {seed}: {play['i']}: "
                                    f"no movement: {play['text']}")
            for problem in replay_plays.check_plays(doc):
                problems.append(f"gen {generation} seed {seed}: {problem}")
                kinds[problem.split(": ", 1)[-1].split(" ")[1] if ": " in problem else problem] += 1
    print(f"{total_plays} plays checked, {len(problems)} problems "
          f"({silent} key plays without movement)")
    for line in problems[: args.show]:
        print("  " + line)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
