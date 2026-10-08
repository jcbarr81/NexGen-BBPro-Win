"""Reset to Opening Day deletes playoff brackets, not the playoff format.

``playoffs_config.json`` (the commissioner's playoff format: teams per league,
seeding, series lengths) also matches ``playoffs_*.json``; the reset used to
delete it with the brackets, so a league quietly went back to the default
format (Release 3 live-path review).
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def league_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    # Sentinels so get_data_dir() resolves this root, never a real league.
    (root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\n", encoding="utf-8"
    )
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id\n",
        encoding="utf-8",
    )
    (root / "users.txt").write_text("", encoding="utf-8")
    (root / "schedule.csv").write_text(
        "date,home,away,result,played,boxscore\n2026-04-01,AAA,BBB,3-2,1,\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def test_reset_to_opening_day_keeps_the_playoff_format(league_root):
    from api.routers import admin_league

    config = {"num_playoff_teams_per_league": 6, "series_lengths": {"ws": 7}}
    (league_root / "playoffs_config.json").write_text(json.dumps(config), encoding="utf-8")
    (league_root / "playoffs_2026.json").write_text(
        json.dumps({"year": 2026, "rounds": []}), encoding="utf-8"
    )

    admin_league.reset_to_opening_day(payload={}, _={"r": "admin"})

    assert json.loads((league_root / "playoffs_config.json").read_text(encoding="utf-8")) == config
    assert not (league_root / "playoffs_2026.json").exists()
