#!/usr/bin/env python3
"""Measure the physics-sim injury rate against real-MLB baselines.

The standard KPI harness (``physics_sim_season_kpis.py``) validates offensive
and pitching rates but tracks NO injury metric, even though the engine runs with
injuries enabled by default. This script fills that gap: it runs a physics
season with injuries on and reports the metrics needed to calibrate injuries —

  * injuries per team per (162-game) season
  * average days per stint
  * pitcher share of injuries
  * a per-trigger breakdown

so a change that wires in new injury triggers (throwing/swing/fielding) can be
measured instead of guessed. Real-MLB targets (from ``calc_injury_baseline.py``
over the roster-resource injury workbook): ~27.3 injuries/team, ~78 days/stint,
~55.7% pitcher share.

Example:
    python scripts/injury_rate_kpi.py --games 54 --seed 1 --ensure-lineups
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from playbalance.schedule_generator import generate_mlb_schedule
from physics_sim.engine import simulate_matchup_from_files
from physics_sim.usage import UsageState
from utils.team_loader import load_teams

# Reuse the calibration harness's fixture/lineup setup + player helpers so this
# script measures the same league the KPI harness does.
import physics_sim_season_kpis as kpi

SEASON_GAMES = 162

# Real-MLB baselines (calc_injury_baseline.py over the roster-resource workbook).
MLB_INJURIES_PER_TEAM = 27.3
MLB_DAYS_PER_STINT = 78.0
MLB_PITCHER_SHARE = 0.557


def _is_pitcher(pid: str, positions: dict[str, str]) -> bool:
    return str(positions.get(pid, "")).upper() in {"P", "SP", "RP"}


def measure(games_per_team: int, seed: int, players_path: Path, base_dir: Path | None):
    teams_csv = (Path(base_dir) / "teams.csv") if base_dir is not None else None
    teams = kpi._team_ids(teams_csv)
    parks_by_team = kpi._team_parks(teams_csv)
    positions = kpi._load_player_positions(players_path)
    schedule = generate_mlb_schedule(teams, date(2025, 4, 1), games_per_team)

    usage_state = UsageState()
    rng = random.Random(seed)
    team_games: Counter = Counter()
    events: list[dict] = []
    day_map: dict[str, int] = {}
    for idx, game in enumerate(schedule):
        date_token = str(game.get("date") or idx)
        if date_token not in day_map:
            day_map[date_token] = len(day_map)
        result = simulate_matchup_from_files(
            away_team=game["away"],
            home_team=game["home"],
            players_path=players_path,
            base_dir=base_dir,
            park_name=parks_by_team.get(game["home"]),
            seed=rng.randrange(2**32),
            usage_state=usage_state,
            game_day=day_map[date_token],
        )
        meta = result.metadata or {}
        teams_meta = meta.get("teams", {})
        for side in ("away", "home"):
            team_id = teams_meta.get(side, game.get(side))
            if team_id:
                team_games[team_id] += 1
        events.extend(meta.get("injury_events", []) or [])

    total_team_games = sum(team_games.values())
    n_teams = len([t for t in team_games if team_games[t] > 0]) or len(teams)
    n_injuries = len(events)
    # Injuries per team per full season: rate per team-game * 162.
    per_team_game = (n_injuries / total_team_games) if total_team_games else 0.0
    per_team_season = per_team_game * SEASON_GAMES

    days = [int(e.get("days") or 0) for e in events if e.get("days")]
    avg_days = (sum(days) / len(days)) if days else 0.0
    pitcher_ct = sum(1 for e in events if _is_pitcher(str(e.get("player_id")), positions))
    pitcher_share = (pitcher_ct / n_injuries) if n_injuries else 0.0

    by_trigger = Counter(str(e.get("trigger")) for e in events)
    by_severity = Counter(str(e.get("severity")) for e in events)

    return {
        "config": {
            "games_per_team": games_per_team,
            "seed": seed,
            "teams": n_teams,
            "total_team_games": total_team_games,
        },
        "measured": {
            "injuries_total": n_injuries,
            "injuries_per_team_season": round(per_team_season, 1),
            "avg_days_per_stint": round(avg_days, 1),
            "pitcher_share": round(pitcher_share, 3),
            "by_trigger": dict(by_trigger),
            "by_severity": dict(by_severity),
        },
        "mlb_targets": {
            "injuries_per_team_season": MLB_INJURIES_PER_TEAM,
            "avg_days_per_stint": MLB_DAYS_PER_STINT,
            "pitcher_share": MLB_PITCHER_SHARE,
        },
    }


def _print_report(report: dict) -> None:
    cfg, m, t = report["config"], report["measured"], report["mlb_targets"]
    print(
        f"Ran {cfg['games_per_team']} games/team over {cfg['teams']} teams "
        f"({cfg['total_team_games']} team-games), seed {cfg['seed']}."
    )
    print("")
    print(f"{'metric':<28}{'measured':>12}{'MLB target':>14}")
    print("-" * 54)
    print(
        f"{'injuries / team / season':<28}"
        f"{m['injuries_per_team_season']:>12}{t['injuries_per_team_season']:>14}"
    )
    print(
        f"{'avg days / stint':<28}"
        f"{m['avg_days_per_stint']:>12}{t['avg_days_per_stint']:>14}"
    )
    print(
        f"{'pitcher share':<28}"
        f"{m['pitcher_share']:>12}{t['pitcher_share']:>14}"
    )
    print("")
    print(f"total injuries: {m['injuries_total']}")
    print(f"by trigger:  {m['by_trigger']}")
    print(f"by severity: {m['by_severity']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure physics-sim injury rate vs MLB.")
    parser.add_argument("--games", type=int, default=54, help="Games per team.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--players", type=Path, default=kpi._default_players_path())
    parser.add_argument("--base-dir", type=Path, default=None)
    parser.add_argument("--ensure-lineups", action="store_true")
    parser.add_argument("--output", type=Path, default=None, help="Write JSON report here.")
    args = parser.parse_args()

    players_path = args.players
    if not players_path.is_absolute():
        players_path = (kpi.BASE_DIR / players_path).resolve()
    base_dir = args.base_dir
    if base_dir is not None and not base_dir.is_absolute():
        base_dir = (kpi.BASE_DIR / base_dir).resolve()

    if args.ensure_lineups:
        for team in load_teams():
            kpi._ensure_team_files(
                team.team_id, players_path=players_path, base_dir=kpi.BASE_DIR
            )

    report = measure(args.games, args.seed, players_path, base_dir)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
