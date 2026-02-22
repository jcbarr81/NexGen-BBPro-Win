import json
import random

from playbalance.season_simulator import SeasonSimulator, _persist_daily_totals


def test_simulate_regular_season_to_completion():
    schedule = [
        {"date": "2024-04-01", "home": "A", "away": "B"},
        {"date": "2024-05-01", "home": "C", "away": "D"},
        {"date": "2024-06-01", "home": "E", "away": "F"},
    ]
    played = []

    sim = SeasonSimulator(schedule, simulate_game=lambda h, a: played.append((h, a)))

    for _ in range(len({g["date"] for g in schedule})):
        sim.simulate_next_day()

    assert len(played) == len(schedule)
    sim.simulate_next_day()
    assert len(played) == len(schedule)


def test_default_simulation_runs_without_callback():
    """Ensure the built-in season simulation runs using full game playbalance."""
    schedule = [{"date": "2024-04-01", "home": "AUS", "away": "BAL"}]

    sim = SeasonSimulator(schedule)

    # Should execute without raising exceptions using real roster data
    sim.simulate_next_day()


def _random_game(home: str, away: str, seed: int | None = None):
    rng = random.Random(seed)
    return rng.randint(0, 10), rng.randint(0, 10)


def test_parallel_simulation_invokes_after_game():
    schedule = [
        {"date": "2024-04-01", "home": "A", "away": "B"},
        {"date": "2024-04-01", "home": "C", "away": "D"},
    ]
    recorded: list[str] = []

    sim = SeasonSimulator(schedule, simulate_game=_random_game, after_game=lambda g: recorded.append(g["result"]))

    sim.simulate_next_day()

    assert len(recorded) == 2
    assert all("result" in g for g in schedule)

def test_default_simulation_saves_team_stats(monkeypatch):
    schedule = [{"date": "2024-04-01", "home": "AUS", "away": "BAL"}]
    captured: dict[str, list] = {}

    def _capture(players, teams):
        captured.setdefault("players", []).extend(list(players))
        captured.setdefault("teams", []).extend(list(teams))

    monkeypatch.setattr("playbalance.simulation.save_stats", _capture)
    monkeypatch.setattr(
        "playbalance.season_simulator._load_season_stats",
        lambda: {"players": {}, "teams": {}},
    )
    monkeypatch.setattr(
        "playbalance.season_simulator.simulate_game_scores",
        lambda *_args, **_kwargs: (
            6,
            4,
            "",
            {"score_line": {"home": 6, "away": 4}},
        ),
    )

    sim = SeasonSimulator(schedule)
    sim.simulate_next_day()

    team_ids = {getattr(team, "team_id", None) for team in captured.get("teams", [])}
    assert {"AUS", "BAL"}.issubset(team_ids)
    assert captured.get("players")


def test_fallback_does_not_overwrite_detailed_stats(tmp_path, monkeypatch):
    base = tmp_path
    data_dir = base / "data"
    data_dir.mkdir()
    stats_path = data_dir / "season_stats.json"
    stats_path.write_text(
        json.dumps(
            {
                "players": {},
                "teams": {
                    "AAA": {
                        "g": 42,
                        "w": 30,
                        "l": 12,
                        "r": 210,
                        "ra": 180,
                        "opp_pa": 0,
                    }
                },
                "history": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.path_utils.get_base_dir", lambda: base)
    monkeypatch.setattr("utils.path_utils.get_data_dir", lambda: data_dir)
    monkeypatch.setattr("utils.stats_persistence.get_data_dir", lambda: data_dir)

    _persist_daily_totals({"AAA": {"g": 1, "w": 1, "l": 0, "r": 5, "ra": 3}})

    updated = json.loads(stats_path.read_text(encoding="utf-8"))
    assert updated["teams"]["AAA"]["g"] == 42
    assert updated["teams"]["AAA"]["w"] == 30
    assert updated["teams"]["AAA"]["l"] == 12
    # Ensure derived keys remain untouched
    assert "opp_pa" in updated["teams"]["AAA"]


def test_fallback_accumulates_when_only_basic_keys(tmp_path, monkeypatch):
    base = tmp_path
    data_dir = base / "data"
    data_dir.mkdir()
    (data_dir / "season_stats.json").write_text(
        json.dumps({"players": {}, "teams": {}, "history": []}, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.path_utils.get_base_dir", lambda: base)
    monkeypatch.setattr("utils.path_utils.get_data_dir", lambda: data_dir)
    monkeypatch.setattr("utils.stats_persistence.get_data_dir", lambda: data_dir)

    day_totals = {"AAA": {"g": 1, "w": 1, "l": 0, "r": 6, "ra": 2}}
    _persist_daily_totals(day_totals)
    _persist_daily_totals(day_totals)

    updated = json.loads((data_dir / "season_stats.json").read_text(encoding="utf-8"))
    team_entry = updated["teams"]["AAA"]
    assert team_entry["g"] == 2
    assert team_entry["w"] == 2
    assert team_entry["l"] == 0
    assert team_entry["r"] == 12
    assert team_entry["ra"] == 4


def test_default_simulation_uses_active_data_paths(monkeypatch, tmp_path):
    data_dir = tmp_path / "active_data"
    captured: dict[str, object] = {}

    def _fake_simulate_game_scores(home_id, away_id, **kwargs):
        captured["home"] = home_id
        captured["away"] = away_id
        captured.update(kwargs)
        return 3, 2, "<html></html>", {}

    monkeypatch.setattr("playbalance.season_simulator.get_data_dir", lambda: data_dir)
    monkeypatch.setattr(
        "playbalance.season_simulator.simulate_game_scores",
        _fake_simulate_game_scores,
    )

    sim = SeasonSimulator([{"date": "2024-04-01", "home": "AAA", "away": "BBB"}])
    sim.simulate_next_day()

    assert captured["players_file"] == str(data_dir / "players.csv")
    assert captured["roster_dir"] == str(data_dir / "rosters")
    assert captured["lineup_dir"] == str(data_dir / "lineups")
