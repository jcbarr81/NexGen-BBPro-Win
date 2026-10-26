"""Owner feedback, 2026-10-26 (8.6.2).

* Pitchers are priced by the shared overall (``utils.player_overall``), not
  by weights led by arm: a hard thrower with poor command was paid like a
  good pitcher. Not while a bidding window opened before 8.6.0 is open.
* Generated catchers are the slowest hitters (alpha-test's catchers came from
  an older generator and keep their ratings).
"""

from __future__ import annotations

import json
import random
import statistics
from types import SimpleNamespace

import pytest

from services import contracts_service as cs


@pytest.fixture
def league(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    (root / "players.csv").write_text("player_id\n", encoding="utf-8")
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id\nBAL,O,B,BAL,E,S,#000000,#FFFFFF,\n",
        encoding="utf-8",
    )
    (root / "users.txt").write_text("commish,pass,admin,\n", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.setenv("PB_DISABLE_FILE_CACHE", "1")
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def _pitcher(arm, control, movement, endurance=50):
    return SimpleNamespace(player_id="X", is_pitcher=True, primary_position="P",
                           arm=arm, control=control, movement=movement,
                           endurance=endurance, fb=50, sl=50, cb=50, ch=50, si=0, cu=0)


def test_a_hard_thrower_without_command_is_priced_by_the_overall(league, monkeypatch):
    monkeypatch.setattr("utils.player_overall.player_overall_score", lambda p, **k: 41.0)
    thrower = _pitcher(arm=80, control=35, movement=38)
    assert cs._pitchers_priced_by_overall()
    assert cs._player_quality_score(thrower) == 41.0


def test_hitters_keep_their_weights(league, monkeypatch):
    monkeypatch.setattr("utils.player_overall.player_overall_score", lambda p, **k: 99.0)
    hitter = SimpleNamespace(is_pitcher=False, primary_position="CF",
                             ph=60, ch=60, eye=60, sp=60, fa=60, arm=60)
    assert cs._player_quality_score(hitter) != 99.0


def test_an_old_rules_window_keeps_the_old_weights_until_it_closes(league, monkeypatch):
    monkeypatch.setattr("utils.player_overall.player_overall_score", lambda p, **k: 41.0)
    thrower = _pitcher(arm=80, control=35, movement=38)
    (league / "fa_window.json").write_text(json.dumps({"status": "open", "day": 6}),
                                           encoding="utf-8")
    assert not cs._pitchers_priced_by_overall()
    assert cs._player_quality_score(thrower) != 41.0
    # A window opened under 8.6.0 (offer_rules), or a closed one: the overall.
    (league / "fa_window.json").write_text(json.dumps({"status": "open", "offer_rules": 2}),
                                           encoding="utf-8")
    assert cs._pitchers_priced_by_overall()
    (league / "fa_window.json").write_text(json.dumps({"status": "closed"}), encoding="utf-8")
    assert cs._player_quality_score(thrower) == 41.0


def test_generated_catchers_are_the_slowest_hitters():
    import playbalance.player_generator as pg

    random.seed(11)
    speed = {
        pos: statistics.mean(
            float(pg.generate_player(is_pitcher=False, primary_position=pos,
                                     age_range=(18, 22)).get("sp", 0))
            for _ in range(150)
        )
        for pos in ("C", "1B", "2B", "SS", "3B", "LF", "CF", "RF")
    }
    assert min(speed, key=speed.get) == "C"
    assert speed["C"] < 45
