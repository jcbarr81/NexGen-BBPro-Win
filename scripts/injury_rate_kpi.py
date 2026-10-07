#!/usr/bin/env python3
"""Measure the physics-sim injury rate against real-MLB baselines.

The standard KPI harness (``physics_sim_season_kpis.py``) validates offensive
and pitching rates but tracks NO injury metric, even though the engine runs with
injuries enabled by default. This script fills that gap: it runs a physics
season with injuries on and reports the metrics needed to calibrate injuries —

  * injured-list (IL) stints per team per 162-game season, all and pitchers
  * pitcher share of IL stints
  * average days per IL stint
  * every injury event (IL + day-to-day) per team-season, for information
  * a per-trigger / per-severity / per-tier breakdown

Audit M15 (2026-10-06): the MLB targets are injured-list stints, so only
events that put a player on an injured list (``dl_tier`` other than ``none``)
are compared with them. Day-to-day knocks are reported separately; counting
them against an IL-only target hid that pitcher IL stints run ~9x below MLB.
The default length is a full 162-game season (the old default, 54, was below
the schedule generator's minimum for a 30-team league and always crashed),
and the default league is the calibration fixture, so a bare run never reads
a real user league.

MLB references (``calc_injury_baseline.py`` over the roster-resource injury
workbook; audit M15): ~11.4 pitcher IL stints per team in-season (~15.3
counting offseason stints), so the calibration band is 11-15; pitchers are
~51% of in-season stints (~56% with offseason); ~27.3 IL stints per team and
~78 days per stint including offseason stints.

Example:
    python scripts/injury_rate_kpi.py --seed 1
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

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
DEFAULT_BASE_DIR = Path("data") / "calibration"

# Real-MLB baselines (audit M15; calc_injury_baseline.py over the
# roster-resource workbook). In-season figures are the calibration targets.
MLB_PITCHER_IL_PER_TEAM = 11.4  # in-season
MLB_PITCHER_IL_PER_TEAM_WITH_OFFSEASON = 15.3
MLB_PITCHER_IL_BAND = (11.0, 15.0)
MLB_PITCHER_SHARE = 0.51  # in-season
MLB_PITCHER_SHARE_WITH_OFFSEASON = 0.557
MLB_IL_PER_TEAM_WITH_OFFSEASON = 27.3
MLB_DAYS_PER_STINT = 78.0

# Tiers that are NOT an injured-list placement (game_runner treats these as
# day-to-day and never calls place_on_injury_list).
_NON_IL_TIERS = {"", "none"}


def _is_pitcher(pid: str, positions: Mapping[str, str]) -> bool:
    return str(positions.get(pid, "")).upper() in {"P", "SP", "RP"}


def is_il_stint(event: Mapping[str, object]) -> bool:
    """True when the injury event puts the player on an injured list."""
    return str(event.get("dl_tier") or "").strip().lower() not in _NON_IL_TIERS


def _per_team_season(count: int, total_team_games: int) -> float:
    if not total_team_games:
        return 0.0
    return count / total_team_games * SEASON_GAMES


def summarize_events(
    events: Iterable[Mapping[str, object]],
    *,
    total_team_games: int,
    positions: Mapping[str, str],
) -> dict[str, object]:
    """Reduce engine injury events to per-team-season IL metrics.

    Rates are per team-game scaled to 162, so a short run is comparable with
    a full season.
    """
    events = list(events)
    il = [e for e in events if is_il_stint(e)]
    il_pitcher = [e for e in il if _is_pitcher(str(e.get("player_id")), positions)]
    days = [int(e.get("days") or 0) for e in il if e.get("days")]
    return {
        "il_stints_total": len(il),
        "il_stints_per_team_season": round(
            _per_team_season(len(il), total_team_games), 2
        ),
        "pitcher_il_stints_per_team_season": round(
            _per_team_season(len(il_pitcher), total_team_games), 2
        ),
        "hitter_il_stints_per_team_season": round(
            _per_team_season(len(il) - len(il_pitcher), total_team_games), 2
        ),
        "pitcher_share_of_il": (
            round(len(il_pitcher) / len(il), 3) if il else None
        ),
        "avg_days_per_il_stint": (
            round(sum(days) / len(days), 1) if days else None
        ),
        # Informational: every injury, day-to-day included (NOT comparable
        # with the IL-only MLB targets).
        "all_injury_events_total": len(events),
        "all_injury_events_per_team_season": round(
            _per_team_season(len(events), total_team_games), 2
        ),
        "il_by_trigger": dict(Counter(str(e.get("trigger")) for e in il)),
        "il_by_severity": dict(Counter(str(e.get("severity")) for e in il)),
        "all_by_tier": dict(
            Counter(str(e.get("dl_tier") or "none") for e in events)
        ),
    }


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
    measured = summarize_events(
        events, total_team_games=total_team_games, positions=positions
    )
    pitcher_rate = measured["pitcher_il_stints_per_team_season"]
    lo, hi = MLB_PITCHER_IL_BAND
    return {
        "config": {
            "games_per_team": games_per_team,
            "seed": seed,
            "teams": n_teams,
            "total_team_games": total_team_games,
        },
        "measured": measured,
        "mlb_targets": {
            "pitcher_il_stints_per_team_season": MLB_PITCHER_IL_PER_TEAM,
            "pitcher_il_stints_per_team_season_with_offseason": (
                MLB_PITCHER_IL_PER_TEAM_WITH_OFFSEASON
            ),
            "pitcher_il_band": list(MLB_PITCHER_IL_BAND),
            "pitcher_share_of_il": MLB_PITCHER_SHARE,
            "pitcher_share_of_il_with_offseason": MLB_PITCHER_SHARE_WITH_OFFSEASON,
            "il_stints_per_team_season_with_offseason": MLB_IL_PER_TEAM_WITH_OFFSEASON,
            "avg_days_per_il_stint": MLB_DAYS_PER_STINT,
        },
        # Report-only for now (audit Release 2); the engine fix is M15 step 1.
        "pitcher_il_in_band": lo <= pitcher_rate <= hi,
    }


def _fmt(value: object) -> str:
    return "n/a" if value is None else str(value)


def _print_report(report: dict) -> None:
    cfg, m, t = report["config"], report["measured"], report["mlb_targets"]
    print(
        f"Ran {cfg['games_per_team']} games/team over {cfg['teams']} teams "
        f"({cfg['total_team_games']} team-games), seed {cfg['seed']}."
    )
    print("Injured-list stints only; rates per team per 162 games.")
    print("")
    print(f"{'metric':<34}{'measured':>10}{'MLB target':>22}")
    print("-" * 66)
    lo, hi = t["pitcher_il_band"]
    rows = [
        (
            "pitcher IL stints / team",
            m["pitcher_il_stints_per_team_season"],
            f"{t['pitcher_il_stints_per_team_season']} ({lo:g}-{hi:g})",
        ),
        (
            "pitcher share of IL stints",
            m["pitcher_share_of_il"],
            f"~{t['pitcher_share_of_il']}",
        ),
        (
            "all IL stints / team",
            m["il_stints_per_team_season"],
            f"{t['il_stints_per_team_season_with_offseason']} w/ offseason",
        ),
        (
            "hitter IL stints / team",
            m["hitter_il_stints_per_team_season"],
            "",
        ),
        (
            "avg days / IL stint",
            m["avg_days_per_il_stint"],
            f"{t['avg_days_per_il_stint']} w/ offseason",
        ),
    ]
    for label, value, target in rows:
        print(f"{label:<34}{_fmt(value):>10}{target:>22}")
    print("")
    print(
        f"pitcher IL in MLB band: {'yes' if report['pitcher_il_in_band'] else 'NO'}"
    )
    print(
        f"all injury events (incl. day-to-day): {m['all_injury_events_total']} "
        f"({m['all_injury_events_per_team_season']} / team-season)"
    )
    print(f"IL by trigger:  {m['il_by_trigger']}")
    print(f"IL by severity: {m['il_by_severity']}")
    print(f"all by tier:    {m['all_by_tier']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure physics-sim injury rate vs MLB.")
    parser.add_argument(
        "--games", type=int, default=SEASON_GAMES, help="Games per team (default 162)."
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=DEFAULT_BASE_DIR,
        help="League folder with teams.csv/rosters/lineups (default: the "
        "calibration fixture).",
    )
    parser.add_argument(
        "--players",
        type=Path,
        default=None,
        help="players.csv (default: <base-dir>/players.csv).",
    )
    parser.add_argument("--ensure-lineups", action="store_true")
    parser.add_argument("--output", type=Path, default=None, help="Write JSON report here.")
    args = parser.parse_args(argv)

    base_dir = args.base_dir
    if base_dir is not None and not base_dir.is_absolute():
        base_dir = (kpi.BASE_DIR / base_dir).resolve()
    players_path = args.players
    if players_path is None:
        candidate = base_dir / "players.csv" if base_dir is not None else None
        players_path = (
            candidate
            if candidate is not None and candidate.exists()
            else kpi._default_players_path()
        )
    if not players_path.is_absolute():
        players_path = (kpi.BASE_DIR / players_path).resolve()

    if args.ensure_lineups:
        for team in load_teams():
            kpi._ensure_team_files(
                team.team_id, players_path=players_path, base_dir=kpi.BASE_DIR
            )

    try:
        report = measure(args.games, args.seed, players_path, base_dir)
    except ValueError as exc:
        # e.g. --games below the schedule generator's minimum for the league.
        parser.error(str(exc))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
