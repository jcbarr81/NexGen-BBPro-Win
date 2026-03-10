import csv
import json
from collections import Counter
from datetime import date
import bcrypt
from playbalance.league_creator import create_league, _dict_to_model, _abbr
from models.pitcher import Pitcher
from playbalance.player_generator import reset_name_cache
from utils.team_loader import load_teams
from utils.user_manager import load_users
import random
import pytest


def test_create_league_generates_files(tmp_path):
    random.seed(0)
    divisions = {"East": [("CityA", "Cats"), ("CityB", "Dogs")]}
    create_league(str(tmp_path), divisions, "Test League")

    teams_path = tmp_path / "teams.csv"
    players_path = tmp_path / "players.csv"
    rosters_dir = tmp_path / "rosters"
    league_path = tmp_path / "league.txt"

    assert teams_path.exists()
    assert players_path.exists()
    assert rosters_dir.is_dir()
    assert league_path.exists()

    with open(teams_path, newline="") as f:
        teams = list(csv.DictReader(f))
    assert len(teams) == 2

    with open(players_path, newline="") as f:
        players = list(csv.DictReader(f))
    players_by_id = {p["player_id"]: p for p in players}
    assert len(players) == 100

    for t in teams:
        r_file = rosters_dir / f"{t['team_id']}.csv"
        assert r_file.exists()
        with open(r_file) as f:
            rows = [line.split(",") for line in f.read().strip().splitlines() if line]
        assert len(rows) == 50
        counts = Counter(level for _, level in rows)
        assert counts["ACT"] == 25
        assert counts["AAA"] == 15
        assert counts["LOW"] == 10
        assert set(counts.keys()) == {"ACT", "AAA", "LOW"}

        act_players = [players_by_id[pid] for pid, level in rows if level == "ACT"]
        act_pitchers = sum(1 for p in act_players if p["is_pitcher"] == "1")
        assert act_pitchers >= 11
        act_positions = {p["primary_position"] for p in act_players if p["is_pitcher"] == "0"}
        assert {"C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"} <= act_positions

        for pid, level in rows:
            birthdate = date.fromisoformat(players_by_id[pid]["birthdate"])
            age = (date.today() - birthdate).days // 365
            if level in {"ACT", "AAA"}:
                assert 21 <= age <= 38
            else:
                assert 18 <= age <= 21
    lineup_dir = tmp_path / "lineups"
    assert lineup_dir.is_dir()
    for t in teams:
        for suffix in ("vs_rhp", "vs_lhp"):
            lineup_file = lineup_dir / f"{t['team_id']}_{suffix}.csv"
            assert lineup_file.exists()
            with lineup_file.open(newline="") as fh:
                entries = list(csv.DictReader(fh))
            assert len(entries) == 9
            for entry in entries:
                assert entry["player_id"] in players_by_id

    stats_path = tmp_path / "season_stats.json"
    assert json.loads(stats_path.read_text()) == {"players": {}, "teams": {}, "history": []}
    progress_path = tmp_path / "season_progress.json"
    progress = json.loads(progress_path.read_text())
    assert progress["preseason_done"] == {
        "free_agency": False,
        "training_camp": False,
        "schedule": False,
    }
    assert progress["sim_index"] == 0
    news_path = tmp_path / "news_feed.txt"
    assert news_path.exists()
    assert news_path.read_text() == ""
    standings_path = tmp_path / "standings.json"
    assert json.loads(standings_path.read_text()) == {}

    with open(league_path) as f:
        assert f.read() == "Test League"


def test_abbr_uses_city_only():
    existing = set()
    assert _abbr("Dallas", "Wolves", existing) == "DAL"
    # Subsequent team from a different city uses that city's letters
    assert _abbr("Denver", "Wolves", existing) == "DEN"
    # A repeat city receives a numeric suffix
    assert _abbr("Dallas", "Bears", existing) == "DAL1"


def test_create_league_assigns_unique_color_pairs(tmp_path):
    random.seed(0)
    divisions = {
        "East": [("CityA", "Cats"), ("CityB", "Dogs")],
        "West": [("CityC", "Rats"), ("CityD", "Bats")],
    }
    create_league(str(tmp_path), divisions, "Test League")

    teams = load_teams(str(tmp_path / "teams.csv"))
    assert len(teams) == 4
    color_pairs = {(t.primary_color, t.secondary_color) for t in teams}
    assert len(color_pairs) == len(teams)


def test_create_league_uses_unique_names(tmp_path):
    reset_name_cache()
    random.seed(0)
    divisions = {"East": [("CityA", "Cats")]}  # single team for simplicity
    create_league(str(tmp_path), divisions, "Test League")

    players_path = tmp_path / "players.csv"
    with open(players_path, newline="") as f:
        players = list(csv.DictReader(f))

    names = {(p["first_name"], p["last_name"]) for p in players}
    assert ("John", "Doe") not in names
    assert len(names) == len(players)

    with open("data/names.csv", newline="") as f:
        allowed = {(r["first_name"], r["last_name"]) for r in csv.DictReader(f)}
    assert names <= allowed


def test_dict_to_model_defaults_pitcher_arm_to_fastball():
    data = {
        "player_id": "p1",
        "first_name": "Pitch",
        "last_name": "Er",
        "birthdate": "1990-01-01",
        "height": 72,
        "weight": 180,
        "bats": "R",
        "primary_position": "P",
        "other_positions": "",
        "gf": 5,
        "is_pitcher": True,
        "endurance": 50,
        "control": 60,
        "movement": 55,
        "hold_runner": 40,
        "fb": 70,
        "cu": 60,
        "cb": 50,
        "sl": 55,
        "si": 45,
        "scb": 65,
        "kn": 40,
    }
    pitcher = _dict_to_model(data)
    assert isinstance(pitcher, Pitcher)
    assert pitcher.arm == 70
    assert pitcher.potential["arm"] == 70


def test_create_league_clears_users_and_rosters(tmp_path, monkeypatch):
    # Set up temporary users file and stray roster file
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    users_file = data_dir / "users.txt"
    users_file.write_text("olduser,pw,admin,\n")

    base_dir = tmp_path / "league"
    rosters_dir = base_dir / "rosters"
    rosters_dir.mkdir(parents=True)
    stray = rosters_dir / "OLD.csv"
    stray.write_text("junk")

    divisions = {"East": [("CityA", "Cats")]}  # single team for simplicity

    # Ensure clear_users operates on our temporary data directory
    monkeypatch.chdir(tmp_path)

    create_league(str(base_dir), divisions, "Test League")

    assert users_file.exists()
    assert users_file.read_text() == "admin,pass,admin,\n"
    assert not stray.exists()


def test_create_league_uses_bootstrap_admin_password(tmp_path, monkeypatch):
    data_root = tmp_path / "data_root"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))

    import utils.path_utils as path_utils
    from utils.user_manager import save_admin_bootstrap

    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None

    save_admin_bootstrap(
        data_root=data_root,
        password_plaintext="league-admin",
        require_setup=False,
    )

    base_dir = tmp_path / "league"
    divisions = {"East": [("CityA", "Cats")]}

    create_league(str(base_dir), divisions, "Test League")

    users_file = base_dir / "users.txt"
    users = load_users(users_file)
    admin = next(u for u in users if u["username"] == "admin")
    assert bcrypt.checkpw(b"league-admin", admin["password"].encode())


def test_create_league_purges_old_files_but_keeps_avatars(tmp_path):
    root_dir = tmp_path
    data_dir = root_dir / "data"
    data_dir.mkdir()
    old_file = data_dir / "old.txt"
    old_file.write_text("old")
    old_dir = data_dir / "lineups"
    old_dir.mkdir()
    (old_dir / "dummy.csv").write_text("x")

    avatars_dir = root_dir / "images" / "avatars"
    avatars_dir.mkdir(parents=True)
    avatar = avatars_dir / "p1.png"
    avatar.write_text("img")

    divisions = {"East": [("CityA", "Cats")]}
    create_league(str(data_dir), divisions, "Test League")

    assert not old_file.exists()
    lineup_dir = data_dir / "lineups"
    assert lineup_dir.is_dir()
    assert not (lineup_dir / "dummy.csv").exists()
    assert any(lineup_dir.glob("*.csv"))
    assert avatar.exists()


def test_create_league_requires_all_positions(tmp_path, monkeypatch):
    def fake_generate_player(is_pitcher=False, age_range=None, primary_position=None, **kwargs):
        return {
            "player_id": "p1",
            "primary_position": "P" if is_pitcher else "1B",
        }

    monkeypatch.setattr("playbalance.league_creator.generate_player", fake_generate_player)
    divisions = {"East": [("CityA", "Cats")]}

    with pytest.raises(ValueError):
        create_league(str(tmp_path), divisions, "Test League")


def test_create_league_reports_progress_phases(tmp_path):
    random.seed(0)
    phases: list[str] = []
    divisions = {"East": [("CityA", "Cats")]}

    create_league(
        str(tmp_path),
        divisions,
        "Progress League",
        progress_callback=phases.append,
    )

    assert phases
    assert phases[0] == "Loading"
    assert "Processing" in phases
    assert "Saving" in phases
    assert "Validating" in phases
    assert phases[-1] == "Complete"
