"""S2-08 calibration-fixture tests: generator determinism, fixture shape, and
the player-dispersion metric math (including the small-pool None guard)."""
from __future__ import annotations

import csv
import hashlib
import statistics
from collections import Counter
from pathlib import Path

import pytest

import scripts.generate_calibration_roster as gen
import scripts.physics_sim_season_kpis as kpis
from utils.park_utils import stadium_from_name

CAL = Path("data/calibration")


def _hash_tree(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            h.update(path.relative_to(root).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def test_generator_deterministic(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    gen.generate(a, seed=gen.DEFAULT_SEED)
    gen.generate(b, seed=gen.DEFAULT_SEED)
    assert _hash_tree(a) == _hash_tree(b)


def test_fixture_shape():
    with (CAL / "teams.csv").open() as fh:
        teams = list(csv.DictReader(fh))
    assert len(teams) == 30
    for team in teams:
        assert stadium_from_name(team["stadium"]) is not None

    with (CAL / "players.csv").open() as fh:
        players = list(csv.DictReader(fh))
    assert len(players) == 780
    assert sum(1 for p in players if p["is_pitcher"] == "1") == 390

    for team in teams:
        tid = team["team_id"]
        with (CAL / "rosters" / f"{tid}.csv").open() as fh:
            roster = [r for r in csv.reader(fh) if r]
        assert len(roster) == 26
        assert all(r[1] == "ACT" for r in roster)
        with (CAL / "rosters" / f"{tid}_pitching.csv").open() as fh:
            pitching = [r for r in csv.reader(fh) if r]
        assert len(pitching) == 13
        for hand in ("rhp", "lhp"):
            with (CAL / "lineups" / f"{tid}_vs_{hand}.csv").open() as fh:
                lineup = list(csv.DictReader(fh))
            assert len(lineup) == 9


def _batter(pa: int, ab: int, h: int, hr: int, so: int, b2: int = 0) -> Counter:
    b1 = max(0, h - hr - b2)
    return Counter(
        {"pa": pa, "ab": ab, "h": h, "hr": hr, "so": so, "b1": b1, "b2": b2, "bb": 0}
    )


def test_dispersion_metrics_math():
    # 162-game season -> min_pa_q = round(162*3.1) = 502, min_ip_q = 162,
    # hr thresholds 40 / 30, teams = 30 -> scale_t = 1.0.
    avgs = [0.200, 0.220, 0.240, 0.260, 0.280, 0.300, 0.320, 0.250, 0.270, 0.290]
    batter_totals: dict[str, Counter] = {}
    for i, avg in enumerate(avgs):
        ab = 500
        h = round(avg * ab)
        hr = 40 if i in (6,) else (30 if i in (5,) else 5)
        batter_totals[f"b{i}"] = _batter(pa=550, ab=ab, h=h, hr=hr, so=100)

    metrics = kpis._dispersion_metrics(batter_totals, {}, games_per_team=162, teams=30)

    exp_avgs = [round(a * 500) / 500 for a in avgs]
    assert metrics["qualified_avg_sd"] == pytest.approx(statistics.pstdev(exp_avgs))
    # hr>=40: only b6 -> 1 ; hr>=30: b5 and b6 -> 2 (30-count includes 40s).
    assert metrics["qualified_hr40_count"] == 1.0
    assert metrics["qualified_hr30_count"] == 2.0
    # avg < .220: only b0 (.200) -> 1 ; avg >= .300: b5(.300), b6(.320) -> 2.
    assert metrics["qualified_sub220_count"] == 1.0
    assert metrics["qualified_avg300_count"] == 2.0
    # Pitcher pool empty (<10) -> era SD is None (skipped by evaluate_tolerances).
    assert metrics["qualified_era_sd"] is None


def test_dispersion_small_batter_pool_is_none():
    # Nine qualified batters (<10) -> every batter metric emits None.
    batter_totals = {
        f"b{i}": _batter(pa=550, ab=500, h=125, hr=5, so=100) for i in range(9)
    }
    metrics = kpis._dispersion_metrics(batter_totals, {}, games_per_team=162, teams=30)
    for key in (
        "qualified_avg_sd",
        "qualified_ops_sd",
        "qualified_hr40_count",
        "qualified_sub220_count",
        "qualified_k_pct_sd",
    ):
        assert metrics[key] is None


def test_scale_t_normalizes_counts():
    # Two-team league: scale_t = 15.0, so one 40-HR hitter counts as 15.
    batter_totals = {
        f"b{i}": _batter(pa=550, ab=500, h=130, hr=(40 if i == 0 else 5), so=100)
        for i in range(12)
    }
    metrics = kpis._dispersion_metrics(batter_totals, {}, games_per_team=162, teams=2)
    assert metrics["qualified_hr40_count"] == pytest.approx(15.0)
