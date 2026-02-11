import csv
import json

import pytest

from models.pitcher import Pitcher
from services import unified_data_service
from utils.player_loader import load_players_from_csv


def test_load_player_with_optional_columns_missing(tmp_path):
    file_path = tmp_path / "players.csv"
    fieldnames = [
        "player_id",
        "first_name",
        "last_name",
        "birthdate",
        "height",
        "weight",
        "bats",
        "primary_position",
        "gf",
        "is_pitcher",
        "role",
        "ch",
        "ph",
        "sp",
        "pl",
        "vl",
        "sc",
        "fa",
        "arm",
    ]
    with open(file_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "player_id": "1",
                "first_name": "John",
                "last_name": "Doe",
                "birthdate": "1990-01-01",
                "height": "72",
                "weight": "180",
                "bats": "R",
                "primary_position": "1B",
                "gf": "50",
                "is_pitcher": "false",
                "role": "",
                "ch": "60",
                "ph": "55",
                "sp": "70",
                "pl": "65",
                "vl": "75",
                "sc": "80",
                "fa": "85",
                "arm": "90",
            }
        )
    players = load_players_from_csv(file_path)
    assert len(players) == 1
    player = players[0]
    assert player.other_positions == []
    assert player.injury_description is None
    assert player.potential["ch"] == 60
    assert player.potential["gf"] == 50
    assert player.arm == 90


def test_missing_required_numeric_field_raises(tmp_path):
    file_path = tmp_path / "players.csv"
    fieldnames = [
        "player_id",
        "first_name",
        "last_name",
        "birthdate",
        "height",
        "weight",
        "bats",
        "primary_position",
        "gf",
        "is_pitcher",
        "role",
        "ch",
        "ph",
        "sp",
        "pl",
        "vl",
        "sc",
        "fa",
        "arm",
    ]
    with open(file_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "player_id": "1",
                "first_name": "John",
                "last_name": "Doe",
                "birthdate": "1990-01-01",
                "height": "",
                "weight": "180",
                "bats": "R",
                "primary_position": "1B",
                "gf": "50",
                "is_pitcher": "false",
                "role": "",
                "ch": "60",
                "ph": "55",
                "sp": "70",
                "pl": "65",
                "vl": "75",
                "sc": "80",
                "fa": "85",
                "arm": "90",
            }
        )
    with pytest.raises(ValueError):
        load_players_from_csv(file_path)


def test_numeric_is_pitcher_creates_pitcher(tmp_path):
    file_path = tmp_path / "players.csv"
    fieldnames = [
        "player_id",
        "first_name",
        "last_name",
        "birthdate",
        "height",
        "weight",
        "bats",
        "primary_position",
        "gf",
        "is_pitcher",
        "role",
        "endurance",
        "control",
        "movement",
        "hold_runner",
        "fb",
        "cu",
        "cb",
        "sl",
        "si",
        "scb",
        "kn",
    ]
    with open(file_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "player_id": "2",
                "first_name": "Jane",
                "last_name": "Smith",
                "birthdate": "1992-02-02",
                "height": "70",
                "weight": "150",
                "bats": "L",
                "primary_position": "P",
                "gf": "10",
                "is_pitcher": "1",
                "role": "SP",
                "endurance": "40",
                "control": "50",
                "movement": "35",
                "hold_runner": "30",
                "fb": "60",
                "cu": "50",
                "cb": "40",
                "sl": "45",
                "si": "55",
                "scb": "35",
                "kn": "25",
            }
        )

    players = load_players_from_csv(file_path)
    assert len(players) == 1
    player = players[0]
    assert isinstance(player, Pitcher)
    assert player.role == "SP"
    assert player.endurance > 0 and player.control > 0
    assert player.arm == 60


def test_pitcher_arm_defaults_to_fastball(tmp_path):
    file_path = tmp_path / "players.csv"
    fieldnames = [
        "player_id",
        "first_name",
        "last_name",
        "birthdate",
        "height",
        "weight",
        "bats",
        "primary_position",
        "gf",
        "is_pitcher",
        "role",
        "endurance",
        "control",
        "movement",
        "hold_runner",
        "fb",
        "cu",
        "cb",
        "sl",
        "si",
        "scb",
        "kn",
        "arm",
    ]
    with open(file_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "player_id": "3",
                "first_name": "Pitch",
                "last_name": "Tester",
                "birthdate": "1991-01-01",
                "height": "72",
                "weight": "180",
                "bats": "R",
                "primary_position": "SP",
                "gf": "5",
                "is_pitcher": "1",
                "role": "SP",
                "endurance": "50",
                "control": "60",
                "movement": "55",
                "hold_runner": "40",
                "fb": "70",
                "cu": "60",
                "cb": "50",
                "sl": "55",
                "si": "45",
                "scb": "65",
                "kn": "40",
                "arm": "0",
            }
        )
    players = load_players_from_csv(file_path)
    assert len(players) == 1
    player = players[0]
    assert isinstance(player, Pitcher)
    assert player.role == "SP"
    assert player.arm == 70


def test_player_loader_refreshes_stats_after_reset(tmp_path, monkeypatch):
    base_dir = tmp_path
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    players_path = data_dir / "players.csv"
    fieldnames = [
        "player_id",
        "first_name",
        "last_name",
        "birthdate",
        "height",
        "weight",
        "bats",
        "primary_position",
        "gf",
        "is_pitcher",
        "role",
        "ch",
        "ph",
        "sp",
        "pl",
        "vl",
        "sc",
        "fa",
        "arm",
    ]
    with players_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "player_id": "P42",
                "first_name": "Alex",
                "last_name": "Reset",
                "birthdate": "1991-01-01",
                "height": "72",
                "weight": "190",
                "bats": "R",
                "primary_position": "1B",
                "gf": "60",
                "is_pitcher": "false",
                "role": "",
                "ch": "55",
                "ph": "50",
                "sp": "45",
                "pl": "60",
                "vl": "65",
                "sc": "58",
                "fa": "62",
                "arm": "70",
            }
        )

    stats_path = data_dir / "season_stats.json"
    stats_path.write_text(
        json.dumps({"players": {"P42": {"pa": 10}}, "teams": {}, "history": []}, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.player_loader.get_base_dir", lambda: base_dir)
    monkeypatch.setattr("utils.player_loader.get_data_dir", lambda: data_dir)
    monkeypatch.setattr(unified_data_service, "_SERVICE", None)

    first = load_players_from_csv(players_path)
    assert first[0].season_stats["pa"] == 10

    stats_path.write_text(json.dumps({"players": {}, "teams": {}, "history": []}, indent=2), encoding="utf-8")
    second = load_players_from_csv(players_path)
    assert not hasattr(second[0], "season_stats")
