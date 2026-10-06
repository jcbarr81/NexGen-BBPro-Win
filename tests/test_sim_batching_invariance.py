"""Audit M18 (2026-10-06): bullpen usage must not depend on how days are batched.

The engine's reliever (and batter) rest state -- ``physics_sim.usage.UsageState``
plus the game-day map -- lives only in ``playbalance.game_runner`` module
globals. A fresh process (a cold Cloud Run instance, the "Sim day" button, a
scheduled run with n=1, a sim right after another league's) starts it empty,
so a league simmed one day per process has no reliever rest gating at all.
The audit measured relievers pitching in consecutive team games 63-65% of the
time that way vs 15-19% when one process sims many days.

This test sims the same small league over the same days twice through the
production path (``SeasonSimulator`` + ``game_runner.simulate_game_scores``,
league files on disk): once as one N-day call, once as N one-day calls with the
in-process state wiped between calls the way a fresh process starts. Per-game
seeds are identical in both runs, so with rest state that survives the process
boundary the two runs agree exactly (checked by keeping the usage globals
across the one-day calls); today they do not: about 62% of relief outings are
back-to-back with one-day calls vs 16% batched, and the bullpen is used ~40%
more (3.6 vs 2.5 relief appearances per team-game).

Expected to fail until Release 3 persists or rebuilds the rest state per
league and calendar date (audit M18 fix 1; owner decision 9).
"""
from __future__ import annotations

import csv
import random
import shutil
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pytest

from playbalance import game_runner
from playbalance.league_creator import create_league
from playbalance.season_simulator import SeasonSimulator

REPO_ROOT = Path(__file__).resolve().parents[1]
DAYS = 8
SEED = 20261006
DIVISIONS = {
    "East": [("CityA", "Cats"), ("CityB", "Dogs"), ("CityC", "Owls"), ("CityD", "Elks")]
}


def _fresh_process_state() -> None:
    """Drop every in-process cache a new process would not have.

    On-disk league state (stats, rosters, pitcher_recovery.json) is kept --
    that is what survives between cloud sim calls.
    """
    from utils import path_utils
    from utils.pitcher_recovery import PitcherRecoveryTracker
    from utils.roster_loader import load_roster

    game_runner._PHYSICS_USAGE_STATE = None
    game_runner._PHYSICS_USAGE_DAY_MAP = {}
    game_runner._PHYSICS_USAGE_YEAR = None
    game_runner._PHYSICS_USAGE_LAST_DATE = None
    game_runner._PHYSICS_USAGE_LEAGUE_KEY = None
    game_runner._teams_by_id.cache_clear()
    PitcherRecoveryTracker._instance = None
    load_roster.cache_clear()
    path_utils._DATA_DIR_CACHE.clear()


def _schedule(team_ids: list[str]) -> list[dict[str, str]]:
    a, b, c, d = team_ids
    pairings = [((a, b), (c, d)), ((a, c), (b, d)), ((a, d), (b, c))]
    start = date(2026, 4, 1)
    games: list[dict[str, str]] = []
    for day in range(DAYS):
        token = (start + timedelta(days=day)).isoformat()
        for home, away in pairings[(day // 3) % 3]:
            if day % 2:
                home, away = away, home
            games.append({"date": token, "home": home, "away": away})
    return games


def _run_league(root: Path, monkeypatch, *, one_day_per_call: bool) -> dict[str, float]:
    """Sim DAYS days in a fresh league under *root*; return bullpen metrics."""
    # The league lives under *root* (base dir = root, data root = root/data);
    # the pitcher-recovery tracker reads PBINI.txt relative to the base dir.
    (root / "playbalance").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "playbalance" / "PBINI.txt", root / "playbalance")
    monkeypatch.setattr(sys, "_MEIPASS", root, raising=False)
    _fresh_process_state()
    data_dir = root / "data"
    # Same generated league in both runs.
    random.seed(SEED)
    create_league(str(data_dir), DIVISIONS, "Batching League")
    with (data_dir / "teams.csv").open(newline="") as fh:
        team_ids = [row["team_id"] for row in csv.DictReader(fh)]
    schedule = _schedule(team_ids)
    dates = sorted({g["date"] for g in schedule})
    day_index = {d: i for i, d in enumerate(dates)}

    # Record each game's pitcher lines with the calendar day it was played.
    from physics_sim import engine

    real_simulate_game = engine.simulate_game
    current = {"date": None}
    appearances: list[tuple[int, str, int]] = []  # (day, pitcher, gs)

    def _recording_simulate_game(*args, **kwargs):
        result = real_simulate_game(*args, **kwargs)
        lines = (result.metadata or {}).get("pitcher_lines", {}) or {}
        for side_lines in lines.values():
            for line in side_lines:
                appearances.append(
                    (
                        day_index[current["date"]],
                        str(line.get("player_id")),
                        int(line.get("gs", 0) or 0),
                    )
                )
        return result

    monkeypatch.setattr(engine, "simulate_game", _recording_simulate_game)

    random.seed(SEED)
    if not one_day_per_call:
        sim = SeasonSimulator(schedule, game_runner.simulate_game_scores)
        for day in dates:
            current["date"] = day
            sim.simulate_next_day()
    else:
        seed_rng = None
        for day in dates:
            # A new process per call: empty module state, a new simulator over
            # the same schedule rows (finished games already carry results).
            _fresh_process_state()
            sim = SeasonSimulator(schedule, game_runner.simulate_game_scores)
            # Keep per-game seeds identical to the batched run so the only
            # difference between the runs is the lost in-process state.
            sim._seed_rng = seed_rng
            current["date"] = day
            while sim.simulate_next_day() == 0:
                pass
            seed_rng = sim._seed_rng

    assert all(str(g.get("result", "")).strip() for g in schedule)
    team_games = 2 * len(schedule)
    relief_days: dict[str, list[int]] = defaultdict(list)
    for day, pid, gs in appearances:
        if gs == 0:
            relief_days[pid].append(day)
    total_relief = sum(len(v) for v in relief_days.values())
    back_to_back = 0
    for days in relief_days.values():
        days.sort()
        back_to_back += sum(1 for x, y in zip(days, days[1:]) if y - x == 1)
    return {
        "relief_appearances": total_relief,
        "reliever_b2b_share": back_to_back / total_relief if total_relief else 0.0,
        "relief_apps_per_team_game": total_relief / team_games,
        "top_reliever_apps_per_team_game": (
            max(len(v) for v in relief_days.values()) / (team_games / len(team_ids))
            if relief_days
            else 0.0
        ),
    }


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Audit M18: reliever rest state lives only in process memory, so "
        "one-day sim calls lose it; fixed in Release 3 (persist/rebuild "
        "UsageState by league + calendar date)."
    ),
)
def test_one_day_calls_match_one_multi_day_call(tmp_path, monkeypatch):
    monkeypatch.delenv("PB_PARALLEL_GAMES", raising=False)
    monkeypatch.setattr(game_runner, "render_boxscore_html", lambda *a, **k: "")

    batched = _run_league(tmp_path / "batched", monkeypatch, one_day_per_call=False)
    daily = _run_league(tmp_path / "daily", monkeypatch, one_day_per_call=True)

    assert batched["relief_appearances"] > 0
    # Same days, same seeds, same league: batching must not change how often
    # relievers pitch on consecutive days or how hard the bullpen is worked.
    assert daily["reliever_b2b_share"] == pytest.approx(
        batched["reliever_b2b_share"], abs=0.10
    ), (daily, batched)
    assert daily["relief_apps_per_team_game"] == pytest.approx(
        batched["relief_apps_per_team_game"], rel=0.15
    ), (daily, batched)
    assert daily["top_reliever_apps_per_team_game"] == pytest.approx(
        batched["top_reliever_apps_per_team_game"], rel=0.25
    ), (daily, batched)
