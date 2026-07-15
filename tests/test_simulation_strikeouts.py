from pathlib import Path
import csv

import scripts.physics_sim_season_kpis as kpis

CAL = Path("data/calibration")


def test_strikeouts_within_mlb_range(monkeypatch):
    """K% stays in a reasonable band on the committed calibration fixture.

    Runs entirely on ``data/calibration`` (never the active league), so it does
    not pollute league lineups/stats and survives the harness signature changes.
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
    assert 0.12 <= metrics["k_pct"] <= 0.32
