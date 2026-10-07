"""Audit M18 (2026-10-06): bullpen usage must not depend on how days are batched.

The engine's reliever (and batter) rest state -- ``physics_sim.usage.UsageState``
-- used to live only in ``playbalance.game_runner`` module globals. A fresh
process (a cold Cloud Run instance, the "Sim day" button, a scheduled run with
n=1, a sim right after another league's) started it empty, so a league simmed
one day per process had no reliever rest gating at all: the audit measured
relievers pitching in consecutive team games 63-65% of the time that way vs
15-19% when one process simmed many days.

Release 3 persists the state per league (``playbalance.usage_store``). These
tests sim the same small league over the same days through the production path
(``SeasonSimulator`` + ``game_runner.simulate_game_scores``, league files on
disk) in several batchings -- one N-day call, N one-day calls, a 7+1 split,
each call after a simulated fresh process -- and require the bullpen metrics,
the scores and the persisted rest and tracker files to be exactly equal. They
also run with league off days in the schedule, and in parallel-day mode
(``PB_PARALLEL_GAMES=2``) against serial.
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
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
# 20+ game dates so the season appearance caps (keyed on the game-date index)
# reach past their floor and bind (plan V6).
DAYS = 22
WEEKLY = (7, 7, 7, 1)
SEED = 20261006
DIVISIONS = {
    "East": [("CityA", "Cats"), ("CityB", "Dogs"), ("CityC", "Owls"), ("CityD", "Elks")]
}


def _fresh_process_state() -> None:
    """Drop every in-process cache a new process would not have.

    On-disk league state (stats, rosters, pitcher_recovery.json,
    physics_usage.json) is kept -- that is what survives between cloud sim
    calls.
    """
    from playbalance import usage_store
    from utils import path_utils
    from utils.pitcher_recovery import PitcherRecoveryTracker
    from utils.roster_loader import load_roster

    usage_store.clear_cache()
    game_runner._teams_by_id.cache_clear()
    PitcherRecoveryTracker._instance = None
    load_roster.cache_clear()
    path_utils._DATA_DIR_CACHE.clear()


def _schedule(team_ids: list[str], *, off_days: bool) -> list[dict[str, str]]:
    a, b, c, d = team_ids
    pairings = [((a, b), (c, d)), ((a, c), (b, d)), ((a, d), (b, c))]
    start = date(2026, 4, 1)
    games: list[dict[str, str]] = []
    for day in range(DAYS):
        # With off days, every 4th calendar day is a league off day.
        offset = day + (day // 3 if off_days else 0)
        token = (start + timedelta(days=offset)).isoformat()
        for home, away in pairings[(day // 3) % 3]:
            if day % 2:
                home, away = away, home
            games.append({"date": token, "home": home, "away": away})
    return games


def _canonical(path: Path) -> str:
    return json.dumps(json.loads(path.read_text(encoding="utf-8")), sort_keys=True)


_NEWS_STAMP = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")


def _league_files(data_dir: Path) -> dict[str, object]:
    """The league files a sim writes that every batching must leave identical.

    The news feed is compared in order with its wall-clock stamps removed.
    """
    files: dict[str, object] = {}
    for sub in ("rosters", "lineups"):
        for path in sorted((data_dir / sub).glob("*.csv")):
            files[f"{sub}/{path.name}"] = path.read_text(encoding="utf-8")
    for name in ("players.csv", "season_stats.json"):
        path = data_dir / name
        if path.exists():
            files[name] = path.read_text(encoding="utf-8")
    news = data_dir / "news_feed.txt"
    if news.exists():
        files["news_feed.txt"] = [
            _NEWS_STAMP.sub("", line)
            for line in news.read_text(encoding="utf-8").splitlines()
        ]
    return files


def _run_league(
    root: Path,
    monkeypatch,
    *,
    calls: tuple[int, ...],
    off_days: bool = False,
) -> dict[str, object]:
    """Sim DAYS days in a fresh league under *root*.

    *calls* gives the number of days each sim call covers; every call after the
    first starts from a fresh process state. Returns the bullpen metrics, the
    scores and the persisted rest/tracker files.
    """
    assert sum(calls) == DAYS
    # The league lives under *root* (base dir = root, data root = root/data);
    # the pitcher-recovery tracker reads PBINI.txt relative to the base dir.
    (root / "playbalance").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "playbalance" / "PBINI.txt", root / "playbalance")
    monkeypatch.setattr(sys, "_MEIPASS", root, raising=False)
    _fresh_process_state()
    data_dir = root / "data"
    # Same generated league in every run.
    random.seed(SEED)
    create_league(str(data_dir), DIVISIONS, "Batching League")
    # Parallel-day workers are spawned processes: they resolve the league
    # through NEXGEN_DATA_ROOT, with the repo as their base dir (the
    # sys._MEIPASS patch above does not reach them). A data root with no
    # league registry and no leagues/ folder gets the repo's data/ seeded
    # into it on first use -- users.txt, settings, the injury catalog, every
    # tracked league -- so the workers would sim a different league from the
    # parent. A real data root always has leagues/; give this one the same,
    # and the injury catalog a real league carries.
    (data_dir / "leagues").mkdir(exist_ok=True)
    shutil.copy(REPO_ROOT / "data" / "injury_catalog.json", data_dir)
    with (data_dir / "teams.csv").open(newline="") as fh:
        team_ids = [row["team_id"] for row in csv.DictReader(fh)]
    schedule = _schedule(team_ids, off_days=off_days)
    dates = sorted({g["date"] for g in schedule})
    day_index = {d: i for i, d in enumerate(dates)}
    calendar = {d: (date.fromisoformat(d) - date.fromisoformat(dates[0])).days for d in dates}

    # Record each game's pitcher lines with the date it was played: from the
    # engine for serial games, from the journal for parallel-day games.
    from physics_sim import engine

    current = {"date": None}
    appearances: list[tuple[str, str, int]] = []  # (date, pitcher, gs)

    def _record(pitcher_lines, token) -> None:
        for side_lines in (pitcher_lines or {}).values():
            for line in side_lines:
                appearances.append(
                    (token, str(line.get("player_id")), int(line.get("gs", 0) or 0))
                )

    real_simulate_game = engine.simulate_game

    def _recording_simulate_game(*args, **kwargs):
        result = real_simulate_game(*args, **kwargs)
        _record((result.metadata or {}).get("pitcher_lines"), current["date"])
        return result

    real_replay = game_runner.replay_game_journal

    def _recording_replay(journal, **kwargs):
        _record((journal.get("lines") or {}).get("pitcher_lines"), kwargs.get("game_date"))
        return real_replay(journal, **kwargs)

    monkeypatch.setattr(engine, "simulate_game", _recording_simulate_game)
    monkeypatch.setattr(game_runner, "replay_game_journal", _recording_replay)

    random.seed(SEED)
    seed_rng = None
    next_day = 0
    for call_index, ndays in enumerate(calls):
        if call_index:
            # A new process per call: empty module state, a new simulator over
            # the same schedule rows (finished games already carry results).
            _fresh_process_state()
        sim = SeasonSimulator(schedule, game_runner.simulate_game_scores)
        # Keep per-game seeds identical across runs so the only difference is
        # the batching.
        sim._seed_rng = seed_rng
        for day in dates[next_day:next_day + ndays]:
            current["date"] = day
            while sim.simulate_next_day() == 0:
                pass
        next_day += ndays
        seed_rng = sim._seed_rng

    assert all(str(g.get("result", "")).strip() for g in schedule)
    team_games = 2 * len(schedule)
    relief_days: dict[str, list[int]] = defaultdict(list)
    relief_calendar: dict[str, list[int]] = defaultdict(list)
    for token, pid, gs in appearances:
        if gs == 0:
            relief_days[pid].append(day_index[token])
            relief_calendar[pid].append(calendar[token])
    total_relief = sum(len(v) for v in relief_days.values())

    def _b2b(days_by_pid: dict[str, list[int]]) -> int:
        count = 0
        for days in days_by_pid.values():
            days.sort()
            count += sum(1 for x, y in zip(days, days[1:]) if y - x == 1)
        return count

    metrics = {
        "relief_appearances": total_relief,
        "reliever_b2b_game_share": _b2b(relief_days) / total_relief if total_relief else 0.0,
        "reliever_b2b_share": _b2b(relief_calendar) / total_relief if total_relief else 0.0,
        "relief_apps_per_team_game": total_relief / team_games,
        "top_reliever_apps_per_team_game": (
            max(len(v) for v in relief_days.values()) / (team_games / len(team_ids))
            if relief_days
            else 0.0
        ),
    }
    usage = json.loads((data_dir / "physics_usage.json").read_text(encoding="utf-8"))
    return {
        "metrics": metrics,
        "scores": [g.get("result") for g in schedule],
        "game_index": usage["usage"]["game_index"],
        "game_dates": len(dates),
        "usage": _canonical(data_dir / "physics_usage.json"),
        "tracker": _canonical(data_dir / "pitcher_recovery.json"),
        "files": _league_files(data_dir),
    }


@pytest.fixture
def _serial_env(monkeypatch):
    monkeypatch.delenv("PB_PARALLEL_GAMES", raising=False)
    monkeypatch.setattr(game_runner, "render_boxscore_html", lambda *a, **k: "")
    yield
    from playbalance import usage_store

    usage_store.clear_cache()


# One serial multi-day run per schedule shape, shared by the tests in this
# module: it is the reference every other batching must reproduce.
_SERIAL_RUNS: dict[bool, dict[str, object]] = {}


def _serial_run(tmp_path: Path, monkeypatch, *, off_days: bool) -> dict[str, object]:
    if off_days not in _SERIAL_RUNS:
        _SERIAL_RUNS[off_days] = _run_league(
            tmp_path / "batched", monkeypatch, calls=(DAYS,), off_days=off_days
        )
    return _SERIAL_RUNS[off_days]


def _assert_caps_live(run: dict[str, object]) -> None:
    """The run reached the dates where the appearance caps bind."""
    from physics_sim.config import load_tuning

    tuning = load_tuning()
    assert tuning.get("reliever_max_appearances_ratio", 0.0) > 0.0
    assert tuning.get("closer_max_appearances_ratio", 0.0) > 0.0
    floor = tuning.get("appearance_cap_min_apps", 1.0)
    # game_index counts the dates played (0-based); it must have advanced
    # once per date, or every cap sits at its floor all season.
    assert run["game_index"] == run["game_dates"] - 1
    assert (run["game_index"] + 1) * tuning.get("reliever_max_appearances_ratio", 0.0) > floor
    assert run["metrics"]["relief_appearances"] > 0


@pytest.mark.parametrize("off_days", [False, True], ids=["every-day", "off-days"])
def test_one_day_and_weekly_calls_match_one_multi_day_call(
    tmp_path, monkeypatch, _serial_env, off_days
):
    batched = _serial_run(tmp_path, monkeypatch, off_days=off_days)
    daily = _run_league(tmp_path / "daily", monkeypatch, calls=(1,) * DAYS, off_days=off_days)
    weekly = _run_league(tmp_path / "weekly", monkeypatch, calls=WEEKLY, off_days=off_days)

    _assert_caps_live(batched)
    # Same days, same seeds, same league: batching must not change anything --
    # not the bullpen metrics, the scores, or the persisted state.
    assert daily == batched, (daily["metrics"], batched["metrics"])
    assert weekly == batched, (weekly["metrics"], batched["metrics"])


@pytest.mark.skipif(
    os.environ.get("PYTHONHASHSEED") != "0",
    reason="parallel-day parity needs PYTHONHASHSEED=0 in the parent too",
)
def test_parallel_day_matches_serial(tmp_path, monkeypatch, _serial_env):
    """PB_PARALLEL_GAMES=2 over 20+ dates, split across two processes, must
    leave exactly what one serial call leaves: scores, bullpen metrics, the
    rest state (game_index included, so the caps bind the same way), the
    tracker, rosters, lineups, stats and the news feed in order."""
    from playbalance import parallel_day

    serial = _serial_run(tmp_path, monkeypatch, off_days=True)
    monkeypatch.setenv("PB_PARALLEL_GAMES", "2")
    try:
        parallel = _run_league(
            tmp_path / "parallel", monkeypatch, calls=(7, DAYS - 7), off_days=True
        )
    finally:
        parallel_day.shutdown_pool()
    _assert_caps_live(serial)
    assert parallel == serial, (parallel["metrics"], serial["metrics"])
