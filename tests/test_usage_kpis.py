"""S2-12: pitching-usage KPIs."""
from collections import Counter
from pathlib import Path

import pytest

import scripts.physics_sim_season_kpis as kpis

CAL = Path("data/calibration")

USAGE_KEYS = [
    "pitches_per_start",
    "ip_per_start",
    "relievers_per_team_game",
    "reliever_top_appearances",
    "saves_per_team_game",
    "reliever_b2b_share",
]


def test_usage_metrics_from_synthetic_lines():
    usage = Counter(
        starts=2, start_pitches=170, start_outs=31, reliever_appearances=5
    )
    reliever_days = {"r1": [3, 4, 6], "r2": [3, 5]}
    pitcher_totals = {
        "r1": Counter(g=3, gs=0),
        "r2": Counter(g=2, gs=0),
        "sp": Counter(g=2, gs=2, sv=0),
    }
    m = kpis._usage_metrics(
        usage, reliever_days, pitcher_totals, games=10, games_per_team=81
    )
    assert m["pitches_per_start"] == pytest.approx(85.0)
    assert m["ip_per_start"] == pytest.approx(31 / 3 / 2)
    assert m["reliever_b2b_share"] == pytest.approx(0.2)  # one pair (3,4)
    assert m["relievers_per_team_game"] == pytest.approx(5 / 20)
    assert m["reliever_top_appearances"] == pytest.approx(3 * (162 / 81))  # 6.0
    assert m["saves_per_team_game"] == pytest.approx(0.0)


def test_usage_metrics_zero_denominator_none():
    m = kpis._usage_metrics(Counter(), {}, {}, games=0, games_per_team=0)
    for k in USAGE_KEYS:
        assert m[k] is None


def test_usage_gates_are_default_strict():
    # S2-03/S2-04 have landed, so the usage gates are promoted to default-strict.
    for k in USAGE_KEYS:
        assert k in kpis.DEFAULT_TOLERANCES


def test_usage_gate_catches_out_of_tolerance():
    benchmarks = {"ip_per_start": 5.2}
    tolerances = {"ip_per_start": kpis.DEFAULT_TOLERANCES["ip_per_start"]}
    failures = kpis.evaluate_tolerances(
        metrics={"ip_per_start": 6.2},  # off by 1.0 >> tol 0.4
        benchmarks=benchmarks,
        tolerances=tolerances,
    )
    assert len(failures) == 1
    assert failures[0]["metric"] == "ip_per_start"


def test_usage_metrics_present_in_run_sim(monkeypatch):
    import csv

    with (CAL / "teams.csv").open() as fh:
        teams = [r["team_id"] for r in csv.DictReader(fh)][:2]
    monkeypatch.setattr(
        kpis, "_team_ids", lambda *a, **k: [kpis._normalize_team_id(t) for t in teams]
    )
    monkeypatch.setattr(kpis, "_team_parks", lambda *a, **k: {})
    summary = kpis.run_sim(
        games_per_team=20, seed=1, players_path=CAL / "players.csv", base_dir=CAL
    )
    m = summary["metrics"]
    for k in USAGE_KEYS:
        assert k in m
    assert m["pitches_per_start"] > 0
    assert "appearance_leaders" in summary["usage"]
