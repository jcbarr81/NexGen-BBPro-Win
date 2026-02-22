import csv
import sys
from types import SimpleNamespace

from playbalance import game_runner
from playbalance.league_creator import create_league
from utils.stats_persistence import load_stats


def test_physics_engine_updates_season_stats(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", tmp_path, raising=False)
    data_dir = tmp_path / "data"
    divisions = {"East": [("CityA", "Cats"), ("CityB", "Dogs")]}
    create_league(str(data_dir), divisions, "Test League")
    monkeypatch.setattr(game_runner, "render_boxscore_html", lambda *args, **kwargs: "")

    teams_path = data_dir / "teams.csv"
    with teams_path.open(newline="") as fh:
        teams = list(csv.DictReader(fh))
    assert len(teams) == 2
    home_id = teams[0]["team_id"]
    away_id = teams[1]["team_id"]

    game_runner.simulate_game_scores(
        home_id,
        away_id,
        seed=1,
        players_file="data/players.csv",
        roster_dir="data/rosters",
        lineup_dir="data/lineups",
        engine="physics",
    )

    stats = load_stats()
    assert stats["players"]
    assert stats["teams"]
    assert any((entry or {}).get("pa", 0) for entry in stats["players"].values())
    assert any((entry or {}).get("g", 0) for entry in stats["teams"].values())


def test_simulate_game_scores_resolves_runtime_data_paths(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "runtime_data"
    captured: dict[str, str] = {}

    def _fake_run_single_game(*_args, **kwargs):
        captured["players_file"] = kwargs.get("players_file")
        captured["roster_dir"] = kwargs.get("roster_dir")
        captured["lineup_dir"] = kwargs.get("lineup_dir")
        return (
            SimpleNamespace(runs=2),
            SimpleNamespace(runs=1),
            {},
            "<html></html>",
            {"ok": True},
        )

    monkeypatch.setattr(game_runner, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(game_runner, "run_single_game", _fake_run_single_game)

    game_runner.simulate_game_scores(
        "AAA",
        "BBB",
        players_file="data/players.csv",
        roster_dir="data/rosters",
        lineup_dir="data/lineups",
    )

    assert captured["players_file"] == str(data_dir / "players.csv")
    assert captured["roster_dir"] == str(data_dir / "rosters")
    assert captured["lineup_dir"] == str(data_dir / "lineups")
