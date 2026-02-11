import csv
from pathlib import Path

from utils.roster_loader import load_roster


def _prepare_base(tmp_path: Path, monkeypatch) -> Path:
    data = tmp_path / "data"
    rosters = data / "rosters"
    rosters.mkdir(parents=True)
    monkeypatch.setattr("utils.path_utils.get_base_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.path_utils.get_data_dir", lambda: data)
    monkeypatch.setattr("utils.roster_loader.get_base_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.roster_loader.get_data_dir", lambda: data)
    monkeypatch.setattr("utils.player_loader.get_base_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.player_loader.get_data_dir", lambda: data)
    load_roster.cache_clear()
    registry = rosters / "_placeholder_registry.json"
    if registry.exists():
        registry.unlink()
    return data


def _write_players(path: Path, hitters: int = 400, pitchers: int = 200) -> None:
    fieldnames = [
        "player_id",
        "first_name",
        "last_name",
        "birthdate",
        "height",
        "weight",
        "ethnicity",
        "skin_tone",
        "hair_color",
        "facial_hair",
        "bats",
        "primary_position",
        "other_positions",
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
        "gf",
        "durability",
        "injured",
        "injury_description",
        "return_date",
        "ready",
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
        "pot_ch",
        "pot_ph",
        "pot_sp",
        "pot_gf",
        "pot_pl",
        "pot_vl",
        "pot_sc",
        "pot_fa",
        "pot_arm",
        "pot_endurance",
        "pot_control",
        "pot_movement",
        "pot_hold_runner",
        "pot_fb",
        "pot_cu",
        "pot_cb",
        "pot_sl",
        "pot_si",
        "pot_scb",
        "pot_kn",
    ]
    players_path = path / "players.csv"
    with players_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for idx in range(hitters):
            writer.writerow(
                {
                    "player_id": f"H{idx:03d}",
                    "first_name": "Hitter",
                    "last_name": str(idx),
                    "birthdate": "1995-01-01",
                    "height": "72",
                    "weight": "190",
                    "ethnicity": "Anglo",
                    "skin_tone": "medium",
                    "hair_color": "brown",
                    "facial_hair": "clean_shaven",
                    "bats": "R",
                    "primary_position": "1B",
                    "other_positions": "",
                    "is_pitcher": "0",
                    "role": "",
                    "ch": str(50 + (idx % 40)),
                    "ph": "50",
                    "sp": "50",
                    "pl": "50",
                    "vl": "50",
                    "sc": "50",
                    "fa": "50",
                    "arm": "50",
                    "gf": "50",
                    "durability": "70",
                    "injured": "false",
                    "injury_description": "",
                    "return_date": "",
                    "ready": "false",
                    "endurance": "0",
                    "control": "0",
                    "movement": "0",
                    "hold_runner": "0",
                    "fb": "0",
                    "cu": "0",
                    "cb": "0",
                    "sl": "0",
                    "si": "0",
                    "scb": "0",
                    "kn": "0",
                    "pot_ch": str(50 + (idx % 40)),
                    "pot_ph": "50",
                    "pot_sp": "50",
                    "pot_gf": "50",
                    "pot_pl": "50",
                    "pot_vl": "50",
                    "pot_sc": "50",
                    "pot_fa": "50",
                    "pot_arm": "50",
                    "pot_endurance": "0",
                    "pot_control": "0",
                    "pot_movement": "0",
                    "pot_hold_runner": "0",
                    "pot_fb": "0",
                    "pot_cu": "0",
                    "pot_cb": "0",
                    "pot_sl": "0",
                    "pot_si": "0",
                    "pot_scb": "0",
                    "pot_kn": "0",
                }
            )
        for idx in range(pitchers):
            pid = f"P{idx:03d}"
            writer.writerow(
                {
                    "player_id": pid,
                    "first_name": "Pitch",
                    "last_name": str(idx),
                    "birthdate": "1995-01-01",
                    "height": "74",
                    "weight": "200",
                    "ethnicity": "Anglo",
                    "skin_tone": "medium",
                    "hair_color": "brown",
                    "facial_hair": "clean_shaven",
                    "bats": "R",
                    "primary_position": "P",
                    "other_positions": "",
                    "is_pitcher": "1",
                    "role": "SP",
                    "ch": "40",
                    "ph": "40",
                    "sp": "40",
                    "pl": "40",
                    "vl": "40",
                    "sc": "40",
                    "fa": "40",
                    "arm": "60",
                    "gf": "40",
                    "durability": "65",
                    "injured": "false",
                    "injury_description": "",
                    "return_date": "",
                    "ready": "false",
                    "endurance": str(60 + (idx % 20)),
                    "control": "55",
                    "movement": str(50 + (idx % 30)),
                    "hold_runner": "45",
                    "fb": str(70 + (idx % 10)),
                    "cu": "40",
                    "cb": "40",
                    "sl": "40",
                    "si": "40",
                    "scb": "0",
                    "kn": "0",
                    "pot_ch": "40",
                    "pot_ph": "40",
                    "pot_sp": "40",
                    "pot_gf": "40",
                    "pot_pl": "40",
                    "pot_vl": "40",
                    "pot_sc": "40",
                    "pot_fa": "40",
                    "pot_arm": "60",
                    "pot_endurance": str(60 + (idx % 20)),
                    "pot_control": "55",
                    "pot_movement": str(50 + (idx % 30)),
                    "pot_hold_runner": "45",
                    "pot_fb": str(70 + (idx % 10)),
                    "pot_cu": "40",
                    "pot_cb": "40",
                    "pot_sl": "40",
                    "pot_si": "40",
                    "pot_scb": "0",
                    "pot_kn": "0",
                }
            )


def test_placeholder_rosters_use_unique_players(tmp_path, monkeypatch):
    data = _prepare_base(tmp_path, monkeypatch)
    _write_players(data)

    roster_a = load_roster("AAA")
    roster_b = load_roster("BBB")

    assert len(roster_a.act) == 25
    assert len(roster_b.act) == 25

    overlap = set(roster_a.act) & set(roster_b.act)
    assert not overlap, f"Placeholder rosters reuse players: {overlap}"
