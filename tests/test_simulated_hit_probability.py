import csv
import io
import contextlib
from collections import Counter
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from playbalance.legacy_guard import legacy_enabled

# Archived legacy season-average tool (simulate_season_average calls
# require_legacy_enabled). The physics KPI harness covers hit rate for the
# shipping engine. Skip unless legacy is explicitly enabled.
pytestmark = pytest.mark.skipif(
    not legacy_enabled(),
    reason="Legacy season-average script archived; set PB_ALLOW_LEGACY_ENGINE=1 to run.",
)

import scripts.simulate_season_avg as ssa
import playbalance.simulation as sim
from playbalance.simulation import TeamState


class DummyPool:
    def __init__(self, initializer=None, initargs=(), **kwargs):
        if initializer:
            initializer(*initargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def imap_unordered(self, func, iterable, chunksize=1):
        return map(func, iterable)


def test_simulated_hit_rate_within_mlb(monkeypatch):
    """Run a short mocked schedule and compare hit probability to MLB benchmark."""
    monkeypatch.setattr(sim, "save_stats", lambda players, teams: None)

    fake_teams = [SimpleNamespace(team_id="T1"), SimpleNamespace(team_id="T2")]
    monkeypatch.setattr(ssa, "load_teams", lambda: fake_teams)
    monkeypatch.setattr(ssa, "build_default_game_state", lambda tid: TeamState([], [], [], None))

    monkeypatch.setattr(ssa.mp, "Pool", DummyPool)

    def short_schedule(teams, start_date):
        return [
            {
                "date": (start_date + timedelta(days=i)).isoformat(),
                "home": teams[0],
                "away": teams[1],
            }
            for i in range(5)
        ]

    monkeypatch.setattr(ssa, "generate_mlb_schedule", short_schedule)

    sched_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "schedules"
        / "2025_schedule.pkl"
    )
    if sched_path.exists():
        sched_path.unlink()

    csv_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "MLB_avg"
        / "mlb_avg_boxscore_2020_2024_both_teams.csv"
    )
    with csv_path.open(newline="") as f:
        row = next(csv.DictReader(f))
    mlb = {stat: float(val) for stat, val in row.items() if stat}
    mlb["PlateAppearances"] = (
        mlb["AtBats"] + mlb["Walks"] + mlb["HitByPitch"]
    )

    monkeypatch.setattr(
        ssa,
        "_simulate_game_star",
        lambda args: Counter(mlb),
    )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ssa.simulate_season_average(use_tqdm=False)
    output = buf.getvalue().splitlines()

    stat_lines = [
        line
        for line in output
        if ":" in line and line.split(":", 1)[0] in ssa.STAT_ORDER
    ]
    stats = {}
    for line in stat_lines:
        stat, rest = line.split(":", 1)
        sim_part = next(p for p in rest.split(",") if p.strip().startswith("Sim"))
        stats[stat] = float(sim_part.split()[1])

    for stat in ssa.STAT_ORDER:
        assert stats[stat] == pytest.approx(mlb[stat], rel=1e-6)

    p_pa_line = next(line for line in output if line.startswith("Pitches/PA"))
    p_pa = float(p_pa_line.split(":", 1)[1])
    plate_appearances = stats["TotalPitchesThrown"] / p_pa
    hit_prob = stats["Hits"] / plate_appearances
    mlb_hit_prob = mlb["Hits"] / mlb["PlateAppearances"]
    assert hit_prob == pytest.approx(mlb_hit_prob, rel=1e-4)
