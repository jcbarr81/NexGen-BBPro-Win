from __future__ import annotations

import csv
import json
from pathlib import Path

from services.career_arc_analytics import build_career_arc_analytics
from utils import path_utils


def _set_data_dir(monkeypatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_dir))
    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None
    return data_dir


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_teams_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "team_id,name,city,abbreviation,division,stadium,primary_color,"
            "secondary_color,owner_id\n"
            "T1,Owls,Orchard,T1,East,Park,#111111,#222222,owner\n"
            "T2,Foxes,Fairfield,T2,West,Park,#111111,#222222,owner\n"
        ),
        encoding="utf-8",
    )


def _write_champions(path: Path, year: int, champion: str, runner_up: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "year,champion,runner_up,series_result\n"
            f"{year},{champion},{runner_up},4-2\n"
        ),
        encoding="utf-8",
    )


def _write_players_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "player_id,first_name,last_name,birthdate,height,weight,ethnicity,skin_tone,hair_color,facial_hair,"
        "bats,primary_position,other_positions,is_pitcher,role,preferred_pitching_role,ch,ph,sp,eye,gf,pl,vl,"
        "sc,fa,arm,endurance,control,movement,hold_runner,fb,cu,cb,sl,si,scb,kn,pot_ch,pot_ph,pot_sp,pot_eye,"
        "pot_gf,pot_pl,pot_vl,pot_sc,pot_fa,pot_arm,pot_control,pot_movement,pot_endurance,pot_hold_runner,"
        "pot_fb,pot_cu,pot_cb,pot_sl,pot_si,pot_scb,pot_kn,injured,injury_description,return_date,ready,"
        "injury_list,injury_start_date,injury_minimum_days,injury_eligible_date,injury_rehab_assignment,"
        "injury_rehab_days,durability,pitcher_archetype,hitter_archetype"
    )
    fields = header.split(",")
    default_row = {field: "" for field in fields}
    batter = dict(default_row)
    batter.update(
        {
            "player_id": "P1",
            "first_name": "Alex",
            "last_name": "Batter",
            "birthdate": "2000-01-01",
            "height": "72",
            "weight": "190",
            "ethnicity": "Anglo",
            "skin_tone": "light",
            "hair_color": "brown",
            "facial_hair": "none",
            "bats": "R",
            "primary_position": "2B",
            "is_pitcher": "0",
            "gf": "52",
            "ch": "64",
            "ph": "61",
            "sp": "57",
            "eye": "55",
            "pl": "50",
            "vl": "50",
            "sc": "50",
            "fa": "58",
            "arm": "54",
            "pot_ch": "67",
            "pot_ph": "63",
            "pot_sp": "60",
            "pot_eye": "57",
            "pot_gf": "56",
            "pot_fa": "60",
            "pot_arm": "56",
            "injured": "false",
            "ready": "true",
            "durability": "50",
        }
    )
    pitcher = dict(default_row)
    pitcher.update(
        {
            "player_id": "P2",
            "first_name": "Pat",
            "last_name": "Pitcher",
            "birthdate": "1999-02-02",
            "height": "74",
            "weight": "210",
            "ethnicity": "Anglo",
            "skin_tone": "light",
            "hair_color": "brown",
            "facial_hair": "none",
            "bats": "R",
            "primary_position": "P",
            "is_pitcher": "1",
            "role": "SP",
            "preferred_pitching_role": "SP",
            "gf": "50",
            "arm": "60",
            "endurance": "72",
            "control": "68",
            "movement": "67",
            "hold_runner": "58",
            "fb": "70",
            "cu": "55",
            "cb": "53",
            "sl": "52",
            "si": "51",
            "scb": "50",
            "kn": "0",
            "pot_arm": "75",
            "pot_control": "70",
            "pot_movement": "69",
            "pot_endurance": "73",
            "pot_hold_runner": "60",
            "pot_fb": "72",
            "pot_cu": "58",
            "pot_cb": "56",
            "pot_sl": "54",
            "pot_si": "53",
            "pot_scb": "52",
            "pot_kn": "0",
            "injured": "false",
            "ready": "true",
            "durability": "55",
        }
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(batter)
        writer.writerow(pitcher)


def test_build_career_arc_analytics_outputs_yoy_trends_and_eras(monkeypatch, tmp_path):
    data_dir = _set_data_dir(monkeypatch, tmp_path)
    _write_teams_csv(data_dir / "teams.csv")

    seasons = []
    season_rows = [
        ("test-2024", 2024, {"T1": (80, 82, 700, 710), "T2": (92, 70, 760, 690)}, "T2", "T1"),
        ("test-2025", 2025, {"T1": (88, 74, 730, 685), "T2": (78, 84, 695, 735)}, "T1", "T2"),
        ("test-2026", 2026, {"T1": (94, 68, 790, 670), "T2": (70, 92, 680, 765)}, "T1", "T2"),
    ]
    for season_id, year, teams, champion, runner_up in season_rows:
        season_dir = data_dir / "careers" / season_id
        standings_payload = {
            team_id: {
                "wins": wins,
                "losses": losses,
                "runs_for": runs_for,
                "runs_against": runs_against,
            }
            for team_id, (wins, losses, runs_for, runs_against) in teams.items()
        }
        _write_json(season_dir / "standings.json", standings_payload)
        _write_champions(season_dir / "champions.csv", year, champion, runner_up)
        seasons.append(
            {
                "season_id": season_id,
                "league_year": year,
                "artifacts": {
                    "standings": f"data/careers/{season_id}/standings.json",
                    "champions": f"data/careers/{season_id}/champions.csv",
                },
            }
        )

    _write_json(
        data_dir / "career_index.json",
        {
            "version": 1,
            "league": {"id": "test", "name": "Test League"},
            "current": {"season_id": "test-2027", "league_year": 2027},
            "seasons": seasons,
        },
    )

    payload = build_career_arc_analytics(data_dir=data_dir, era_window=2)
    yoy_rows = payload.get("yoy", [])
    trend_rows = payload.get("trends", [])
    era_rows = payload.get("team_eras", [])
    assert "similarity" in payload
    assert "aging_buckets" in payload

    assert len(yoy_rows) == 6
    t1_2025 = next(
        row for row in yoy_rows if row["team_id"] == "T1" and row["league_year"] == 2025
    )
    assert t1_2025["delta_wins"] == 8
    assert t1_2025["delta_run_diff"] == 55
    assert t1_2025["is_champion"] == 1

    t1_trend = next(row for row in trend_rows if row["team_id"] == "T1")
    assert t1_trend["championships"] == 2
    assert t1_trend["win_pct_slope"] > 0
    assert t1_trend["run_diff_slope"] > 0

    t2_trend = next(row for row in trend_rows if row["team_id"] == "T2")
    assert t2_trend["win_pct_slope"] < 0
    assert t2_trend["run_diff_slope"] < 0

    t1_era = next(
        row
        for row in era_rows
        if row["team_id"] == "T1" and row["era_label"] == "2025-2026"
    )
    assert t1_era["wins"] == 182
    assert t1_era["championships"] == 2


def test_build_career_arc_analytics_v2_similarity_and_filters(monkeypatch, tmp_path):
    data_dir = _set_data_dir(monkeypatch, tmp_path)
    _write_teams_csv(data_dir / "teams.csv")
    _write_players_csv(data_dir / "players.csv")
    (data_dir / "season_stats.json").write_text(
        json.dumps(
            {
                "players": {
                    "P1": {"ab": 300, "h": 90, "2b": 20, "3b": 2, "hr": 12, "bb": 30, "sb": 8},
                    "P2": {"outs": 300, "er": 30, "bb": 20, "h": 90, "so": 110},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "rosters").mkdir(parents=True, exist_ok=True)
    (data_dir / "rosters" / "T1.csv").write_text("P1,ACT\nP2,ACT\n", encoding="utf-8")
    _write_json(
        data_dir / "career_index.json",
        {
            "version": 1,
            "league": {"id": "test", "name": "Test League"},
            "current": {"season_id": "test-2026", "league_year": 2026},
            "seasons": [],
        },
    )

    payload = build_career_arc_analytics(
        data_dir=data_dir,
        filters={"position_group": "hitter", "team_ids": ["T1"]},
        target_player_id="P1",
        similarity_top_n=3,
    )

    similarity = payload.get("similarity", [])
    aging = payload.get("aging_buckets", [])
    assert isinstance(similarity, list)
    assert isinstance(aging, list)
    assert payload.get("filters_applied")
