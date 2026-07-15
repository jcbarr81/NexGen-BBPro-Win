from pathlib import Path
import csv

import scripts.physics_sim_season_kpis as kpis

CAL = Path("data/calibration")


def test_simulated_averages_close_to_mlb(monkeypatch):
    """Run a short physics-sim sample on the committed calibration fixture and
    ensure KPIs stay in reasonable bands.

    Runs entirely on ``data/calibration`` — never the active league — so it
    neither crashes on missing player IDs nor pollutes league lineups/stats.
    """
    with (CAL / "teams.csv").open() as fh:
        teams = [r["team_id"] for r in csv.DictReader(fh)][:2]
    monkeypatch.setattr(
        kpis, "_team_ids", lambda *a, **k: [kpis._normalize_team_id(t) for t in teams]
    )
    monkeypatch.setattr(kpis, "_team_parks", lambda *a, **k: {})
    metrics = kpis.run_sim(
        games_per_team=20,
        seed=1,
        players_path=CAL / "players.csv",
        base_dir=CAL,
    )["metrics"]
    assert 0.20 <= metrics["avg"] <= 0.30
    assert 0.28 <= metrics["obp"] <= 0.36
    assert 0.33 <= metrics["slg"] <= 0.46
    assert 3.5 <= metrics["pitches_per_pa"] <= 4.2
    assert 0.17 <= metrics["k_pct"] <= 0.27
    assert 0.05 <= metrics["bb_pct"] <= 0.11
