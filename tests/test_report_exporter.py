from pathlib import Path
import csv
import json

from services.report_exporter import export_reports
from utils import path_utils


def _set_data_dir(monkeypatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_dir))
    path_utils._DATA_DIR = None
    return data_dir


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join([header] + rows)
    path.write_text(content, encoding="utf-8")


def _write_players_csv(path: Path, header: str, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = header.split(",")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_export_reports_creates_csvs(monkeypatch, tmp_path):
    data_dir = _set_data_dir(monkeypatch, tmp_path)

    teams_header = "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id"
    teams_rows = [
        "T1,Owls,Orchard,T1,East,Park,#111,#222,owner",
        "T2,Foxes,Fairfield,T2,West,Park,#111,#222,owner",
    ]
    _write_csv(data_dir / "teams.csv", teams_header, teams_rows)

    players_header = (
        "player_id,first_name,last_name,birthdate,height,weight,ethnicity,skin_tone,hair_color,facial_hair,"
        "bats,primary_position,other_positions,is_pitcher,role,preferred_pitching_role,ch,ph,sp,eye,gf,pl,vl,"
        "sc,fa,arm,endurance,control,movement,hold_runner,fb,cu,cb,sl,si,scb,kn,pot_ch,pot_ph,pot_sp,pot_eye,"
        "pot_gf,pot_pl,pot_vl,pot_sc,pot_fa,pot_arm,pot_control,pot_movement,pot_endurance,pot_hold_runner,"
        "pot_fb,pot_cu,pot_cb,pot_sl,pot_si,pot_scb,pot_kn,injured,injury_description,return_date,ready,"
        "injury_list,injury_start_date,injury_minimum_days,injury_eligible_date,injury_rehab_assignment,"
        "injury_rehab_days,durability,pitcher_archetype,hitter_archetype"
    )
    default_player = {field: "" for field in players_header.split(",")}
    batter = dict(default_player)
    batter.update(
        {
            "player_id": "P1",
            "first_name": "Alex",
            "last_name": "Batter",
            "birthdate": "1995-01-01",
            "height": "72",
            "weight": "190",
            "bats": "R",
            "primary_position": "2B",
            "is_pitcher": "0",
            "gf": "50",
            "ch": "50",
            "ph": "50",
            "sp": "50",
            "pl": "50",
            "vl": "50",
            "sc": "50",
            "fa": "50",
            "arm": "50",
        }
    )
    pitcher = dict(default_player)
    pitcher.update(
        {
            "player_id": "P2",
            "first_name": "Pat",
            "last_name": "Pitcher",
            "birthdate": "1994-02-02",
            "height": "74",
            "weight": "200",
            "bats": "R",
            "primary_position": "P",
            "is_pitcher": "1",
            "role": "SP",
            "preferred_pitching_role": "SP",
            "gf": "50",
            "endurance": "50",
            "control": "50",
            "movement": "50",
            "hold_runner": "50",
            "fb": "50",
            "cu": "50",
            "cb": "50",
            "sl": "50",
            "si": "50",
            "scb": "50",
            "kn": "50",
            "arm": "50",
        }
    )
    _write_players_csv(data_dir / "players.csv", players_header, [batter, pitcher])

    _write_csv(data_dir / "rosters" / "T1.csv", "player_id,level", ["P1,ACT"])
    _write_csv(data_dir / "rosters" / "T2.csv", "player_id,level", ["P2,ACT"])

    standings = {
        "T1": {"wins": 10, "losses": 5, "runs_for": 50, "runs_against": 40},
        "T2": {"wins": 8, "losses": 7, "runs_for": 45, "runs_against": 48},
    }
    (data_dir / "standings.json").write_text(json.dumps(standings), encoding="utf-8")

    season_stats = {
        "players": {
            "P1": {"g": 10, "ab": 30, "h": 10, "hr": 2, "rbi": 5, "bb": 3, "so": 4, "sb": 1},
            "P2": {"g": 8, "outs": 24, "er": 2, "bb": 1, "h": 5, "so": 9, "w": 2, "l": 1, "sv": 0},
        },
        "teams": {
            "T1": {"g": 15, "w": 10, "l": 5, "r": 50, "ra": 40},
            "T2": {"g": 15, "w": 8, "l": 7, "r": 45, "ra": 48},
        },
        "history": [],
    }
    (data_dir / "season_stats.json").write_text(json.dumps(season_stats), encoding="utf-8")

    result = export_reports(include_pdf=False)
    assert result.output_dir.exists()
    assert result.files["standings_csv"].exists()
    assert result.files["league_stats_teams_csv"].exists()
    assert result.files["league_stats_batting_csv"].exists()
    assert result.files["league_stats_pitching_csv"].exists()
    assert result.files["league_leaders_batting_csv"].exists()
    assert result.files["league_leaders_pitching_csv"].exists()
    assert result.files["league_history_csv"].exists()
    assert result.files["record_book_batting_csv"].exists()
    assert result.files["record_book_pitching_csv"].exists()
    assert result.files["record_book_team_csv"].exists()

    standings_header = result.files["standings_csv"].read_text(encoding="utf-8").splitlines()[0]
    assert "team_id" in standings_header
    batting_header = result.files["league_stats_batting_csv"].read_text(encoding="utf-8").splitlines()[0]
    assert "player_id" in batting_header
