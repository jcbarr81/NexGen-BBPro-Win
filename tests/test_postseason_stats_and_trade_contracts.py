"""8.1.1: playoff games keep their own totals; trades move the contract.

Playoff games used to add into the regular-season totals (alpha-test's 2026
champions read 175 games, 100-75), and a trade left each player's contract
with the club that traded him away, which kept paying him.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from models.roster import Roster
from models.trade import Trade
from playbalance import game_runner
from services.trade_execution import commit_trade
from utils import stats_persistence
from utils.roster_loader import save_roster


@pytest.fixture
def stats_dir(tmp_path, monkeypatch):
    """Point ``data/...`` stats paths at ``tmp_path``; no history shards."""

    monkeypatch.setattr(
        stats_persistence,
        "_resolve_path",
        lambda path: Path(path) if Path(path).is_absolute() else tmp_path / Path(path).name,
    )
    monkeypatch.setenv("PB_SHARD_HISTORY", "0")
    monkeypatch.setenv("PB_DISABLE_HISTORY", "1")
    monkeypatch.setattr(game_runner, "active_journal", lambda: None)
    regular = {
        "players": {
            "B1": {"g": 162, "pa": 650, "ab": 580, "h": 170, "hr": 30},
            "P1": {"g": 32, "gs": 32, "outs": 600, "er": 70, "so": 200},
        },
        "teams": {"T1": {"g": 162, "w": 95, "l": 67}, "T2": {"g": 162, "w": 90, "l": 72}},
        "history": [],
    }
    (tmp_path / "season_stats.json").write_text(json.dumps(regular), encoding="utf-8")
    return tmp_path, regular


def _game_metadata():
    return {
        "batting_lines": {
            "home": [{"player_id": "B1", "g": 1, "pa": 4, "ab": 4, "h": 2, "hr": 1, "b1": 1}],
            "away": [],
        },
        "pitcher_lines": {
            "away": [{"player_id": "P1", "g": 1, "gs": 1, "outs": 21, "er": 3, "so": 6}],
            "home": [],
        },
        "score": {"home": 5, "away": 3},
    }


def _objects(regular):
    players = {
        pid: SimpleNamespace(player_id=pid, season_stats=dict(stats))
        for pid, stats in regular["players"].items()
    }
    home = SimpleNamespace(team_id="T1", season_stats=dict(regular["teams"]["T1"]))
    away = SimpleNamespace(team_id="T2", season_stats=dict(regular["teams"]["T2"]))
    return players, home, away


def test_postseason_games_add_into_their_own_totals(stats_dir):
    tmp_path, regular = stats_dir
    before = (tmp_path / "season_stats.json").read_bytes()
    players, home, away = _objects(regular)

    for _ in range(2):
        game_runner._persist_physics_stats(
            metadata=_game_metadata(),
            players_lookup=players,
            home_team=home,
            away_team=away,
            postseason=True,
        )

    # The regular season is untouched, on disk and on the shared objects.
    assert (tmp_path / "season_stats.json").read_bytes() == before
    assert players["B1"].season_stats == regular["players"]["B1"]
    assert players["P1"].season_stats == regular["players"]["P1"]
    assert home.season_stats == regular["teams"]["T1"]
    assert away.season_stats == regular["teams"]["T2"]

    post = json.loads((tmp_path / "postseason_stats.json").read_text(encoding="utf-8"))
    batter = post["players"]["B1"]
    assert (batter["g"], batter["pa"], batter["h"], batter["hr"]) == (2, 8, 4, 2)
    assert batter["avg"] == pytest.approx(0.5)
    pitcher = post["players"]["P1"]
    assert (pitcher["g"], pitcher["gs"], pitcher["outs"], pitcher["so"]) == (2, 2, 42, 12)
    assert post["teams"]["T1"]["g"] == 2 and post["teams"]["T1"]["w"] == 2
    assert post["teams"]["T2"]["g"] == 2 and post["teams"]["T2"]["l"] == 2
    assert not (tmp_path / "season_history").exists()


def test_regular_season_games_still_add_into_the_season(stats_dir):
    tmp_path, regular = stats_dir
    players, home, away = _objects(regular)

    game_runner._persist_physics_stats(
        metadata=_game_metadata(),
        players_lookup=players,
        home_team=home,
        away_team=away,
    )

    season = json.loads((tmp_path / "season_stats.json").read_text(encoding="utf-8"))
    assert season["players"]["B1"]["g"] == 163
    assert season["players"]["B1"]["hr"] == 31
    assert season["teams"]["T1"]["g"] == 163
    assert season["teams"]["T1"]["w"] == 96
    assert not (tmp_path / "postseason_stats.json").exists()


def _contracts(data_dir: Path, payload: dict) -> None:
    (data_dir / "contracts.json").write_text(json.dumps(payload), encoding="utf-8")


def test_trade_moves_each_contract_to_the_new_club(tmp_path, monkeypatch):
    roster_dir = tmp_path / "rosters"
    roster_dir.mkdir()
    save_roster("AAA", Roster("AAA", act=["a1", "a2"]), roster_dir=roster_dir)
    save_roster("BBB", Roster("BBB", act=["b1", "b2"], aaa=["b3"]), roster_dir=roster_dir)
    monkeypatch.setattr(
        "services.trade_execution.record_transaction", lambda **_kwargs: None
    )
    _contracts(
        tmp_path,
        {
            "version": 1,
            "players": {
                "a1": {"team_id": "AAA", "annual_salary": 5_000_000, "years_left": 3},
                "a2": {"team_id": "AAA", "annual_salary": 1_000_000, "years_left": 1},
                "b1": {"team_id": "BBB", "annual_salary": 2_000_000, "years_left": 2},
            },
        },
    )

    # b3 (a minor leaguer) has no contract and must not be given one.
    commit_trade(Trade("t1", "AAA", "BBB", ["a1"], ["b1", "b3"]), data_dir=tmp_path)

    after = json.loads((tmp_path / "contracts.json").read_text(encoding="utf-8"))["players"]
    assert after["a1"]["team_id"] == "BBB"
    assert after["a1"]["annual_salary"] == 5_000_000
    assert after["a1"]["years_left"] == 3
    assert after["b1"]["team_id"] == "AAA"
    assert after["a2"]["team_id"] == "AAA"
    assert "b3" not in after


def test_refused_trade_moves_no_contract(tmp_path, monkeypatch):
    roster_dir = tmp_path / "rosters"
    roster_dir.mkdir()
    save_roster("AAA", Roster("AAA", act=["a1"]), roster_dir=roster_dir)
    save_roster("BBB", Roster("BBB", act=["b1"]), roster_dir=roster_dir)
    _contracts(
        tmp_path,
        {"version": 1, "players": {"a1": {"team_id": "AAA", "annual_salary": 1, "years_left": 1}}},
    )

    def _raise(*_args, **_kwargs):
        raise ValueError("2099|1|ZZZ is owned by ZZZ, not AAA.")

    monkeypatch.setattr("services.trade_execution.transfer_pick", _raise)
    trade = Trade("t2", "AAA", "BBB", ["a1"], ["b1"], give_pick_ids=["2099|1|ZZZ"])
    with pytest.raises(ValueError):
        commit_trade(trade, data_dir=tmp_path)

    after = json.loads((tmp_path / "contracts.json").read_text(encoding="utf-8"))["players"]
    assert after["a1"]["team_id"] == "AAA"
