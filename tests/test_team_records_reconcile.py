"""Team-block drift fix: _reconcile_team_records_with_schedule overwrites the
season_stats team rollup's counting fields (g/w/l/r/ra) from the authoritative
schedule, so the team-stats page can't show the drifted totals the in-memory
accumulator produces on re-sim. Idempotent; recovers already-drifted leagues.
"""

import csv
import json
from pathlib import Path

import pytest

from api.routers import season


def _rows(*games):
    return [{"home": h, "away": a, "result": r, "played": "1"} for h, a, r in games]


def _setup(monkeypatch, tmp_path, schedule_rows, teams_block):
    monkeypatch.setattr(season, "_load_schedule", lambda: schedule_rows)
    monkeypatch.setattr(season, "get_data_dir", lambda: tmp_path)
    (tmp_path / "season_stats.json").write_text(
        json.dumps({"players": {}, "teams": teams_block}), encoding="utf-8"
    )


def _read_teams(tmp_path):
    return json.loads((tmp_path / "season_stats.json").read_text(encoding="utf-8"))["teams"]


def test_overwrites_drifted_counting_fields_preserves_detail(monkeypatch, tmp_path):
    # AAA actually went 3-0 (won 5-3, 4-1, 1-0) with 10 RF / 4 RA over 3 games;
    # the block is inflated ~2.5x and carries detailed fields that must survive.
    _setup(
        monkeypatch, tmp_path,
        _rows(("AAA", "BBB", "5-3"), ("BBB", "AAA", "1-4"), ("AAA", "BBB", "1-0")),
        {"AAA": {"g": 8, "w": 12, "l": 3, "r": 25, "ra": 10, "opp_pa": 300, "der": 0.64}},
    )
    assert season._reconcile_team_records_with_schedule() is True
    aaa = _read_teams(tmp_path)["AAA"]
    assert (aaa["g"], aaa["w"], aaa["l"], aaa["r"], aaa["ra"]) == (3, 3, 0, 10, 4)
    # Detailed fields untouched.
    assert aaa["opp_pa"] == 300 and aaa["der"] == 0.64


def test_idempotent(monkeypatch, tmp_path):
    _setup(
        monkeypatch, tmp_path,
        _rows(("AAA", "BBB", "5-3")),
        {"AAA": {"g": 9, "w": 5, "l": 4, "r": 40, "ra": 20}},
    )
    season._reconcile_team_records_with_schedule()
    first = _read_teams(tmp_path)
    # Second pass makes no further change.
    season._reconcile_team_records_with_schedule()
    assert _read_teams(tmp_path) == first
    assert first["AAA"]["g"] == 1 and first["AAA"]["w"] == 1


def test_adds_team_missing_from_block(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _rows(("AAA", "BBB", "5-3")), {})  # empty block
    assert season._reconcile_team_records_with_schedule() is True
    teams = _read_teams(tmp_path)
    assert teams["AAA"] == {"g": 1, "w": 1, "l": 0, "r": 5, "ra": 3}
    assert teams["BBB"] == {"g": 1, "w": 0, "l": 1, "r": 3, "ra": 5}


def test_no_schedule_no_change(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, [], {"AAA": {"g": 9, "w": 5, "l": 4}})
    assert season._reconcile_team_records_with_schedule() is False
    assert _read_teams(tmp_path)["AAA"]["g"] == 9  # untouched


# --- Against the real corrupted Smoke League snapshot (if present) ---
_SCRATCH = Path(
    "C:/Users/james/AppData/Local/Temp/claude/"
    "c--Users-james-OneDrive-Documents-Baseball-AI-NexGen-BBPro/"
    "5bf5c044-913f-4874-94f1-8ed5a6933c05/scratchpad"
)
_SMOKE_SCHED = _SCRATCH / "smoke_schedule.csv"
_SMOKE_STATS = _SCRATCH / "smoke_season_stats.json"


@pytest.mark.skipif(
    not (_SMOKE_SCHED.exists() and _SMOKE_STATS.exists()),
    reason="Smoke League snapshot not present",
)
def test_recovers_real_smoke_league(monkeypatch, tmp_path):
    rows = list(csv.DictReader(_SMOKE_SCHED.open(encoding="utf-8", newline="")))
    stats = json.loads(_SMOKE_STATS.read_text(encoding="utf-8"))
    # BOS was corrupt at 217-185 (402 g); real schedule says 81-81, 162 g.
    assert stats["teams"]["BOS"]["g"] == 402
    monkeypatch.setattr(season, "_load_schedule", lambda: rows)
    monkeypatch.setattr(season, "get_data_dir", lambda: tmp_path)
    (tmp_path / "season_stats.json").write_text(json.dumps(stats), encoding="utf-8")

    season._reconcile_team_records_with_schedule()
    teams = _read_teams(tmp_path)
    assert len(teams) == 12  # all teams present, none dropped
    for tid, blk in teams.items():
        assert blk["w"] + blk["l"] == blk["g"] == 162
    assert (teams["BOS"]["w"], teams["BOS"]["l"]) == (81, 81)
    assert (teams["NAS"]["w"], teams["NAS"]["l"]) == (95, 67)
    # A detailed field that existed is preserved (invisible but consistent).
    assert "opp_pa" in teams["BOS"]
