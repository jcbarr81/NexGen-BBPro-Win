"""Regression tests for schedule-derived standings.

Root-cause fix for the season_stats team-rollup drift: standings are now a pure,
idempotent function of the played schedule (schedule.csv) instead of the
drift-prone season_stats team block. See _team_records_from_schedule.
"""

import csv
from pathlib import Path

import pytest

from api.routers import season


def _rows(*games):
    """games: (home, away, result) tuples -> schedule-style dict rows."""
    return [{"home": h, "away": a, "result": r, "played": "1"} for h, a, r in games]


def test_records_basic_win_loss_and_runs(monkeypatch):
    monkeypatch.setattr(
        season,
        "_load_schedule",
        lambda: _rows(("AAA", "BBB", "5-3"), ("BBB", "AAA", "2-4"), ("AAA", "BBB", "1-1")),
    )
    rec = season._team_records_from_schedule()
    # AAA won game1 (home 5>3) and game2 (away 4>2); tie game3 -> no decision.
    assert rec["AAA"] == {"wins": 2, "losses": 0, "runs_for": 5 + 4 + 1, "runs_against": 3 + 2 + 1}
    assert rec["BBB"] == {"wins": 0, "losses": 2, "runs_for": 3 + 2 + 1, "runs_against": 5 + 4 + 1}


def test_records_ignores_unplayed_and_unparseable(monkeypatch):
    monkeypatch.setattr(
        season,
        "_load_schedule",
        lambda: [
            {"home": "AAA", "away": "BBB", "result": "5-3"},
            {"home": "AAA", "away": "BBB", "result": ""},        # not yet played
            {"home": "AAA", "away": "BBB", "result": "PPD"},     # unparseable
            {"home": "", "away": "BBB", "result": "1-0"},         # missing team
        ],
    )
    rec = season._team_records_from_schedule()
    assert rec["AAA"] == {"wins": 1, "losses": 0, "runs_for": 5, "runs_against": 3}
    assert set(rec.keys()) == {"AAA", "BBB"}


def test_records_are_idempotent(monkeypatch):
    monkeypatch.setattr(
        season, "_load_schedule", lambda: _rows(("AAA", "BBB", "5-3"), ("AAA", "BBB", "5-3"))
    )
    # Two identical games -> counted exactly as scheduled, no runaway accumulation.
    rec = season._team_records_from_schedule()
    assert rec["AAA"]["wins"] == 2
    # Calling again yields the SAME result (pure function, no in-memory carry).
    assert season._team_records_from_schedule() == rec


def test_sync_prefers_schedule_over_corrupt_season_stats(monkeypatch, tmp_path):
    monkeypatch.setattr(season, "_load_schedule", lambda: _rows(("AAA", "BBB", "5-3")))
    monkeypatch.setattr(season, "get_data_dir", lambda: tmp_path)
    saved = {}
    monkeypatch.setattr(
        "services.standings_repository.save_standings",
        lambda standings, base_path=None: saved.update(standings),
    )
    ok = season._sync_standings_from_stats()
    assert ok is True
    # Comes from the schedule (1-0), NOT any season_stats team block.
    assert saved["AAA"] == {"wins": 1, "losses": 0, "runs_for": 5, "runs_against": 3}


def test_sync_falls_back_to_season_stats_when_no_decided_games(monkeypatch, tmp_path):
    monkeypatch.setattr(season, "_load_schedule", lambda: [])  # no schedule yet
    monkeypatch.setattr(season, "get_data_dir", lambda: tmp_path)
    (tmp_path / "season_stats.json").write_text(
        '{"teams": {"AAA": {"w": 3, "l": 2, "r": 20, "ra": 15}}}', encoding="utf-8"
    )
    saved = {}
    monkeypatch.setattr(
        "services.standings_repository.save_standings",
        lambda standings, base_path=None: saved.update(standings),
    )
    ok = season._sync_standings_from_stats()
    assert ok is True
    assert saved["AAA"] == {"wins": 3, "losses": 2, "runs_for": 20, "runs_against": 15}


# --- Validation against the REAL corrupted Smoke League schedule (if present) ---
_SMOKE = Path(
    "C:/Users/james/AppData/Local/Temp/claude/"
    "c--Users-james-OneDrive-Documents-Baseball-AI-NexGen-BBPro/"
    "5bf5c044-913f-4874-94f1-8ed5a6933c05/scratchpad/smoke_schedule.csv"
)


@pytest.mark.skipif(not _SMOKE.exists(), reason="Smoke League schedule snapshot not present")
def test_real_smoke_league_schedule_yields_clean_records(monkeypatch):
    rows = list(csv.DictReader(_SMOKE.open(encoding="utf-8", newline="")))
    monkeypatch.setattr(season, "_load_schedule", lambda: rows)
    rec = season._team_records_from_schedule()
    # All 12 teams present (the corrupt season_stats had only 7), each 162 games.
    assert len(rec) == 12
    for tid, r in rec.items():
        assert r["wins"] + r["losses"] == 162, f"{tid} not a full 162-game season"
    # Spot-check known correct records (vs the corrupt "217-185" etc.).
    assert rec["BOS"]["wins"] == 81 and rec["BOS"]["losses"] == 81
    assert rec["NAS"]["wins"] == 95 and rec["NAS"]["losses"] == 67
    assert rec["PHI"]["wins"] == 67 and rec["PHI"]["losses"] == 95
