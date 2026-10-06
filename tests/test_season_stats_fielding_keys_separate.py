"""Audit H5: fielding counters must not overwrite batting/pitching counters.

A player's batting, pitching and fielding lines all accumulate into one
``season_stats`` dict. Fielding ``cs``/``po``/``ci`` share a name with the
batting counters (caught stealing as a runner, picked off, reached on
interference) and fielding ``pk`` with the pitcher's pickoffs, so before the fix
every caught stealing was stored twice and a first baseman's putouts showed up
as "picked off". Fielding now stores them as ``f_cs``/``f_po``/``f_ci``/``f_pk``.
"""

from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from physics_sim.engine import simulate_matchup_from_files
from playbalance import game_runner
from playbalance.simulation import BatterState, GameSimulation, TeamState
from tests.test_simulation import make_pitcher, make_player
from tests.util.pbini_factory import load_config

CAL = Path("data/calibration")


@pytest.fixture(autouse=True)
def _no_disk_writes(monkeypatch):
    # _persist_physics_stats saves through utils.stats_persistence; these tests
    # only inspect the in-memory season dicts and must never touch a league.
    monkeypatch.setattr("utils.stats_persistence.save_stats", lambda *a, **k: None)


def _player(pid: str, position: str, season: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=pid, primary_position=position, season_stats=dict(season or {})
    )


def _persist(metadata: dict, players: dict[str, SimpleNamespace]) -> None:
    game_runner._persist_physics_stats(
        metadata=metadata,
        players_lookup=players,
        home_team=None,
        away_team=None,
    )


def _metadata() -> dict:
    return {
        "score": {"home": 3, "away": 2},
        "batting_lines": {
            "home": [
                # The catcher was caught stealing once, picked off once and
                # reached on interference once as a runner/batter.
                {"player_id": "C1", "pa": 4, "ab": 3, "sb": 1, "cs": 1, "po": 1, "ci": 1},
                {"player_id": "1B1", "pa": 4, "ab": 4},
            ]
        },
        "pitcher_lines": {
            "home": [{"player_id": "P1", "outs": 27, "bf": 30, "pk": 1}],
        },
        "fielding_lines": {
            "home": [
                # ...and threw out two of three base stealers behind the plate.
                {"player_id": "C1", "g": 1, "po": 9, "a": 2, "cs": 2, "sba": 3, "ci": 1},
                {"player_id": "1B1", "g": 1, "po": 10, "a": 1},
                {"player_id": "P1", "g": 1, "pk": 1, "a": 2},
            ]
        },
    }


def test_fielding_counters_stay_out_of_batting_and_pitching() -> None:
    players = {
        "C1": _player("C1", "C"),
        "1B1": _player("1B1", "1B"),
        "P1": _player("P1", "P"),
    }
    _persist(_metadata(), players)

    catcher = players["C1"].season_stats
    assert catcher["cs"] == 1  # his own caught stealing, not the two he threw out
    assert catcher["po"] == 1
    assert catcher["ci"] == 1
    assert catcher["f_cs"] == 2
    assert catcher["f_po"] == 9
    assert catcher["f_ci"] == 1
    assert catcher["sba"] == 3
    assert catcher["sb_pct"] == pytest.approx(0.5)
    assert catcher["cs_pct"] == pytest.approx(2 / 3)
    assert catcher["tc"] == 11

    first_base = players["1B1"].season_stats
    assert first_base["po"] == 0  # putouts are not "picked off"
    assert first_base["f_po"] == 10
    assert first_base["tc"] == 11

    pitcher = players["P1"].season_stats
    assert pitcher["pk"] == 1  # one pickoff, no longer counted twice
    assert pitcher["f_pk"] == 1


def test_rows_written_before_the_fix_are_tolerated() -> None:
    # DECISIONS.md decision 1: 2026 stats are not migrated. An old row has the
    # merged counters and no f_ keys; the next game must accumulate cleanly.
    old = {"g": 10, "cs": 7, "po": 80, "ci": 1, "sba": 9, "a": 5, "sb": 2}
    players = {
        "C1": _player("C1", "C", old),
        "1B1": _player("1B1", "1B"),
        "P1": _player("P1", "P"),
    }
    _persist(_metadata(), players)

    catcher = players["C1"].season_stats
    assert catcher["cs"] == 8
    assert catcher["po"] == 81
    assert catcher["f_cs"] == 2
    assert catcher["f_po"] == 9
    assert catcher["sba"] == 12
    assert catcher["cs_pct"] == pytest.approx(2 / 12)


def _calibration_lookup() -> dict[str, SimpleNamespace]:
    import csv

    with (CAL / "players.csv").open(newline="") as fh:
        return {
            row["player_id"]: _player(row["player_id"], row["primary_position"])
            for row in csv.DictReader(fh)
        }


def test_simulated_games_store_each_caught_stealing_once() -> None:
    players = _calibration_lookup()
    rng = random.Random(5)
    teams = [f"CAL{n:02d}" for n in range(1, 11)]
    catcher_batting_cs: dict[str, int] = defaultdict(int)
    for game in range(30):
        home, away = teams[game % 10], teams[(game + 3) % 10]
        result = simulate_matchup_from_files(
            away_team=away,
            home_team=home,
            players_path=CAL / "players.csv",
            base_dir=CAL,
            seed=rng.randrange(2**32),
        )
        meta = result.metadata
        for lines in meta["batting_lines"].values():
            for line in lines:
                catcher_batting_cs[str(line["player_id"])] += int(line.get("cs", 0))
        _persist(meta, players)

    seasons = [p.season_stats for p in players.values()]
    hitter_cs = sum(s.get("cs", 0) for s in seasons)
    caught_by_catchers = sum(s.get("sba", 0) for s in seasons) - sum(
        s.get("sb", 0) for s in seasons
    )
    assert caught_by_catchers > 0, "fixture produced no caught stealing; raise games"
    assert hitter_cs == caught_by_catchers
    assert sum(s.get("f_cs", 0) for s in seasons) == caught_by_catchers

    for pid, player in players.items():
        if player.primary_position != "C" or not player.season_stats.get("sba"):
            continue
        # A catcher's batting cs counts only the times he was thrown out.
        assert player.season_stats.get("cs", 0) == catcher_batting_cs[pid]


def test_legacy_engine_namespaces_fielding_counters(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def record(players, teams):
        for player in players:
            captured[player.player_id] = dict(player.season_stats)

    monkeypatch.setattr("playbalance.simulation.save_stats", record)
    catcher = make_player("c1")
    pitcher = make_pitcher("p1")
    home = TeamState(
        lineup=[catcher] + [make_player(f"h{i}") for i in range(8)],
        bench=[],
        pitchers=[pitcher],
    )
    away = TeamState(
        lineup=[make_player(f"a{i}") for i in range(9)],
        bench=[],
        pitchers=[make_pitcher("p2")],
    )
    batting = home.lineup_stats.setdefault("c1", BatterState(catcher))
    batting.cs = 1
    fielding = home.fielding_stats["c1"]
    fielding.cs = 2
    fielding.sba = 3
    fielding.po = 7
    home.pitcher_stats["p1"].pk = 1
    home.fielding_stats["p1"].pk = 1

    GameSimulation(home, away, load_config(), random.Random(1)).simulate_game(innings=0)

    assert captured["c1"]["cs"] == 1
    assert captured["c1"]["f_cs"] == 2
    assert captured["c1"]["f_po"] == 7
    assert captured["c1"]["cs_pct"] == pytest.approx(2 / 3)
    assert captured["p1"]["pk"] == 1
    assert captured["p1"]["f_pk"] == 1
