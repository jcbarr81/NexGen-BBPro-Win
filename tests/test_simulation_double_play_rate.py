import contextlib
import io
from datetime import timedelta
from pathlib import Path

import pytest

from playbalance.legacy_guard import legacy_enabled

# scripts.simulate_season_avg is the ARCHIVED legacy season-average tool; its
# simulate_season_average() calls require_legacy_enabled(). The physics KPI
# harness (scripts/physics_sim_season_kpis.py) covers DP rate for the shipping
# engine. Skip unless the legacy engine is explicitly enabled.
pytestmark = pytest.mark.skipif(
    not legacy_enabled(),
    reason="Legacy season-average script archived; set PB_ALLOW_LEGACY_ENGINE=1 to run.",
)

import scripts.simulate_season_avg as ssa
import playbalance.simulation as sim
from tests.test_physics import make_player, make_pitcher
from playbalance.simulation import TeamState
from collections import Counter


def fake_sim_game(home_id, away_id, seed):
    return Counter({
        "Runs": 0,
        "Hits": 0,
        "Doubles": 0,
        "Triples": 0,
        "HomeRuns": 10,
        "Walks": 0,
        "Strikeouts": 20,
        "StolenBases": 0,
        "CaughtStealing": 0,
        "HitByPitch": 0,
        "PlateAppearances": 130,
        "AtBats": 100,
        "SacFlies": 5,
        "GIDP": 8,
        "TotalPitchesThrown": 0,
        "Strikes": 0,
    })


def _run_sim(monkeypatch):
    monkeypatch.setattr(sim, "save_stats", lambda players, teams: None)

    def short_schedule(teams, start_date):
        return [
            {"date": (start_date + timedelta(days=i)).isoformat(), "home": teams[0], "away": teams[1]}
            for i in range(10)
        ]

    class DummyTeam:
        def __init__(self, tid):
            self.team_id = tid

    def short_load():
        return [DummyTeam("T1"), DummyTeam("T2")]

    def fake_build(team_id):
        lineup = [make_player(f"{team_id}{i}") for i in range(9)]
        pitchers = [make_pitcher(f"{team_id}p")]
        return TeamState(lineup=lineup, bench=[], pitchers=pitchers)

    monkeypatch.setattr(ssa, "generate_mlb_schedule", short_schedule)
    monkeypatch.setattr(ssa, "load_teams", short_load)
    monkeypatch.setattr(ssa, "build_default_game_state", fake_build)
    monkeypatch.setattr(ssa, "_simulate_game", fake_sim_game)
    sched_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "schedules"
        / "2025_schedule.pkl"
    )
    if sched_path.exists():
        sched_path.unlink()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ssa.simulate_season_average(use_tqdm=False, seed=42)
    return buf.getvalue().splitlines()


def _parse(lines, prefix):
    for line in lines:
        if line.startswith(prefix):
            return float(line.split(":", 1)[1].strip())
    raise AssertionError(f"{prefix} not found")


def test_simulation_double_play_rate(monkeypatch):
    lines = _run_sim(monkeypatch)
    dp_rate = _parse(lines, "DoublePlayRate")
    assert 0.09 < dp_rate < 0.13
