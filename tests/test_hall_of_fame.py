import csv
import importlib
import json
from pathlib import Path

import pytest


def _write_players_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "player_id",
        "first_name",
        "last_name",
        "primary_position",
        "is_pitcher",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_awards(path: Path, awards: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"awards": awards, "generated_at": "2026-01-01T00:00:00Z"}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_career_index(path: Path, seasons: list[dict], current_year: int) -> None:
    payload = {
        "version": 1,
        "league": {"id": "nexgen", "name": "Test League"},
        "current": {
            "season_id": f"nexgen-{current_year}",
            "league_year": current_year,
            "sequence": len(seasons) + 1,
            "metadata": {},
            "rollover_complete": False,
        },
        "seasons": seasons,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_career_totals(path: Path, totals: dict[str, dict]) -> None:
    payload = {"version": 1, "players": {}}
    for pid, stats in totals.items():
        payload["players"][pid] = {"totals": stats, "seasons": {}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    import utils.path_utils as path_utils
    path_utils._DATA_DIR = None
    import playbalance.season_context as season_context
    importlib.reload(season_context)
    return data_root


def _setup_league(data_root: Path) -> None:
    season_2020 = "nexgen-2020"
    season_2024 = "nexgen-2024"
    season_dir_2020 = data_root / "careers" / season_2020
    season_dir_2024 = data_root / "careers" / season_2024
    _write_players_csv(
        season_dir_2020 / "players.csv",
        [
            {
                "player_id": "P1",
                "first_name": "Hall",
                "last_name": "Legend",
                "primary_position": "SS",
                "is_pitcher": "false",
            },
        ],
    )
    _write_players_csv(
        season_dir_2024 / "players.csv",
        [
            {
                "player_id": "P2",
                "first_name": "Border",
                "last_name": "Line",
                "primary_position": "1B",
                "is_pitcher": "false",
            },
        ],
    )
    _write_awards(
        season_dir_2020 / "awards.json",
        {"MVP": {"player_id": "P1", "player_name": "Hall Legend"}},
    )
    _write_awards(
        season_dir_2024 / "awards.json",
        {"MVP": {"player_id": "P2", "player_name": "Border Line"}},
    )

    seasons = [
        {
            "season_id": season_2020,
            "league_year": 2020,
            "artifacts": {
                "players": str(season_dir_2020 / "players.csv"),
                "awards": str(season_dir_2020 / "awards.json"),
            },
        },
        {
            "season_id": season_2024,
            "league_year": 2024,
            "artifacts": {
                "players": str(season_dir_2024 / "players.csv"),
                "awards": str(season_dir_2024 / "awards.json"),
            },
        },
    ]
    _write_career_index(data_root / "career_index.json", seasons, current_year=2026)

    _write_players_csv(
        data_root / "players.csv",
        [
            {
                "player_id": "P3",
                "first_name": "Active",
                "last_name": "Player",
                "primary_position": "CF",
                "is_pitcher": "false",
            },
        ],
    )

    totals = {
        "P1": {
            "h": 3000,
            "hr": 500,
            "rbi": 1500,
            "bb": 1200,
            "sb": 200,
            "r": 1600,
            "g": 2400,
            "war": 70,
        },
        "P2": {
            "h": 800,
            "hr": 80,
            "rbi": 400,
            "bb": 300,
            "sb": 20,
            "r": 350,
            "g": 900,
            "war": 5,
        },
    }
    _write_career_totals(data_root / "careers" / "career_players.json", totals)


def test_auto_inducts_eligible(data_dir):
    _setup_league(data_dir)
    import services.hall_of_fame as hof
    importlib.reload(hof)

    result = hof.update_hall_of_fame(current_year=2026)
    assert result["added"], "Expected at least one inductee"
    inductees = hof.list_inductees()
    inducted_ids = {entry.get("player_id") for entry in inductees}
    assert "P1" in inducted_ids
    assert "P2" not in inducted_ids


def test_manual_add_and_remove(data_dir):
    _setup_league(data_dir)
    import services.hall_of_fame as hof
    importlib.reload(hof)

    hof.update_hall_of_fame(current_year=2026)
    add_result = hof.add_manual_inductee("P2", current_year=2026)
    assert add_result["status"] == "added"
    inductees = hof.list_inductees()
    inducted_ids = {entry.get("player_id") for entry in inductees}
    assert "P2" in inducted_ids

    hof.remove_inductee("P2")
    inductees = hof.list_inductees()
    inducted_ids = {entry.get("player_id") for entry in inductees}
    assert "P2" not in inducted_ids

    hof.update_hall_of_fame(current_year=2026)
    inductees = hof.list_inductees()
    inducted_ids = {entry.get("player_id") for entry in inductees}
    assert "P2" not in inducted_ids
