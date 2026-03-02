from __future__ import annotations

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
