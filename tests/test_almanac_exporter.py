from __future__ import annotations

import csv
import json
from pathlib import Path

from services.almanac_exporter import (
    AlmanacExportResult,
    export_almanac,
    validate_almanac_export,
)
from utils import path_utils


def _set_data_dir(monkeypatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_dir))
    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None
    return data_dir


def _write_csv(path: Path, header: str, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = header.split(",")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_export_almanac_generates_multi_page_bundle(monkeypatch, tmp_path):
    data_dir = _set_data_dir(monkeypatch, tmp_path)

    teams_header = (
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id"
    )
    _write_csv(
        data_dir / "teams.csv",
        teams_header,
        [
            {
                "team_id": "T1",
                "name": "Owls",
                "city": "Orchard",
                "abbreviation": "OWL",
                "division": "East",
                "stadium": "Park",
                "primary_color": "#111",
                "secondary_color": "#222",
                "owner_id": "owner",
            },
            {
                "team_id": "T2",
                "name": "Foxes",
                "city": "Fairfield",
                "abbreviation": "FOX",
                "division": "West",
                "stadium": "Park",
                "primary_color": "#111",
                "secondary_color": "#222",
                "owner_id": "cpu",
            },
        ],
    )

    players_header = (
        "player_id,first_name,last_name,birthdate,height,weight,ethnicity,skin_tone,"
        "hair_color,facial_hair,bats,primary_position,other_positions,is_pitcher,role,"
        "preferred_pitching_role,ch,ph,sp,eye,gf,pl,vl,sc,fa,arm,endurance,control,"
        "movement,hold_runner,fb,cu,cb,sl,si,scb,kn,pot_ch,pot_ph,pot_sp,pot_eye,"
        "pot_gf,pot_pl,pot_vl,pot_sc,pot_fa,pot_arm,pot_control,pot_movement,"
        "pot_endurance,pot_hold_runner,pot_fb,pot_cu,pot_cb,pot_sl,pot_si,pot_scb,"
        "pot_kn,injured,injury_description,return_date,ready,injury_list,"
        "injury_start_date,injury_minimum_days,injury_eligible_date,"
        "injury_rehab_assignment,injury_rehab_days,durability,pitcher_archetype,"
        "hitter_archetype"
    )
    base_player = {field: "" for field in players_header.split(",")}
    p1 = dict(base_player)
    p1.update(
        {
            "player_id": "P1",
            "first_name": "Alex",
            "last_name": "Batter",
            "birthdate": "1999-01-01",
            "height": "72",
            "weight": "190",
            "bats": "R",
            "primary_position": "2B",
            "is_pitcher": "0",
            "ch": "50",
            "ph": "50",
            "sp": "50",
            "pl": "50",
            "vl": "50",
            "sc": "50",
            "fa": "50",
            "arm": "50",
            "gf": "50",
        }
    )
    p2 = dict(base_player)
    p2.update(
        {
            "player_id": "P2",
            "first_name": "Pat",
            "last_name": "Pitcher",
            "birthdate": "1998-01-01",
            "height": "74",
            "weight": "205",
            "bats": "R",
            "primary_position": "P",
            "is_pitcher": "1",
            "role": "SP",
            "preferred_pitching_role": "SP",
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
            "gf": "50",
        }
    )
    _write_csv(data_dir / "players.csv", players_header, [p1, p2])

    (data_dir / "season_stats.json").write_text(
        json.dumps(
            {
                "players": {
                    "P1": {"g": 17, "ab": 64, "h": 21, "hr": 3, "rbi": 11, "team_id": "T1"},
                    "P2": {"g": 8, "gs": 8, "w": 4, "l": 2, "sv": 0, "outs": 144, "er": 15, "so": 48, "team_id": "T2"},
                },
                "teams": {},
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "careers").mkdir(parents=True, exist_ok=True)
    (data_dir / "careers" / "career_players.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {
                        "totals": {"g": 179, "ab": 644, "h": 201, "hr": 25, "rbi": 91, "avg": 0.312, "ops": 0.901},
                        "seasons": {
                            "test-2025": {"g": 162, "ab": 580, "h": 180, "hr": 22, "rbi": 80}
                        },
                    },
                    "P2": {
                        "totals": {"g": 40, "gs": 40, "w": 22, "l": 10, "sv": 0, "outs": 684, "er": 72, "so": 228},
                        "seasons": {
                            "test-2025": {"g": 32, "gs": 32, "w": 18, "l": 8, "outs": 540, "er": 57, "so": 180}
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    _write_csv(
        data_dir / "rosters" / "T1.csv",
        "player_id,level",
        [{"player_id": "P1", "level": "ACT"}],
    )
    _write_csv(
        data_dir / "rosters" / "T2.csv",
        "player_id,level",
        [{"player_id": "P2", "level": "ACT"}],
    )
    (data_dir / "transactions.csv").write_text(
        (
            "timestamp,season_date,team_id,player_id,player_name,action,from_level,to_level,counterparty,details\n"
            "2026-05-01 09:00:00,2026-05-01,T1,P1,Alex Batter,promote,AAA,ACT,,Opening Day promotion\n"
        ),
        encoding="utf-8",
    )
    (data_dir / "team_financials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "season_year": 2026,
                "teams": {
                    "T1": {
                        "cash_on_hand": 2000000,
                        "debt": 100000,
                        "revenue": {"tickets": 500000, "concessions": 120000, "media": 150000, "sponsorship": 90000},
                        "expenses": {"payroll": 3500000, "training": 50000, "scouting": 40000, "facilities": 30000, "operations": 80000},
                        "budgets": {"training": 10000, "scouting": 10000, "development": 10000, "facilities": 10000},
                    },
                    "T2": {
                        "cash_on_hand": 1800000,
                        "debt": 250000,
                        "revenue": {"tickets": 420000, "concessions": 100000, "media": 150000, "sponsorship": 85000},
                        "expenses": {"payroll": 3300000, "training": 45000, "scouting": 38000, "facilities": 28000, "operations": 76000},
                        "budgets": {"training": 10000, "scouting": 10000, "development": 10000, "facilities": 10000},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "league_financial_settings.json").write_text(
        json.dumps(
            {
                "version": 1,
                "leagues": {
                    "test": {
                        "enabled": True,
                        "preset": "standard",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "financial_transactions.csv").write_text(
        (
            "timestamp,season_year,team_id,category,amount,memo\n"
            "2026-05-01T00:00:00Z,2026,T1,revenue_tickets,250000,May gate receipts\n"
            "2026-05-01T00:00:00Z,2026,__system__,finance_cycle,0,2026-05\n"
        ),
        encoding="utf-8",
    )
    (data_dir / "finance_snapshots").mkdir(parents=True, exist_ok=True)
    (data_dir / "finance_snapshots" / "2025.json").write_text(
        json.dumps(
            {
                "version": 1,
                "created_at": "2025-10-02T00:00:00Z",
                "ended_season_year": 2025,
                "next_season_year": 2026,
                "financials_enabled": True,
                "preset": "standard",
                "annual_payroll_totals": {"T1": 8000000, "T2": 7000000},
                "team_financials": {
                    "teams": {
                        "T1": {
                            "cash_on_hand": 1500000,
                            "debt": 0,
                            "revenue": {"tickets": 1000000, "concessions": 250000, "media": 300000, "sponsorship": 180000},
                            "expenses": {"payroll": 8000000, "training": 500000, "scouting": 400000, "facilities": 300000, "operations": 900000},
                        },
                        "T2": {
                            "cash_on_hand": 1200000,
                            "debt": 200000,
                            "revenue": {"tickets": 950000, "concessions": 210000, "media": 300000, "sponsorship": 170000},
                            "expenses": {"payroll": 7000000, "training": 450000, "scouting": 380000, "facilities": 280000, "operations": 880000},
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "T1": {"wins": 12, "losses": 5, "runs_for": 68, "runs_against": 42},
                "T2": {"wins": 9, "losses": 8, "runs_for": 55, "runs_against": 58},
            }
        ),
        encoding="utf-8",
    )

    archived_standings = data_dir / "careers" / "test-2025" / "standings_2025.json"
    archived_standings.parent.mkdir(parents=True, exist_ok=True)
    archived_standings.write_text(
        json.dumps(
            {
                "T1": {"wins": 80, "losses": 82, "runs_for": 700, "runs_against": 710},
                "T2": {"wins": 84, "losses": 78, "runs_for": 730, "runs_against": 701},
            }
        ),
        encoding="utf-8",
    )
    champions_csv = archived_standings.parent / "champions.csv"
    champions_csv.write_text(
        "year,champion,runner_up,series_result\n2025,T2,T1,4-2\n",
        encoding="utf-8",
    )
    awards_json = archived_standings.parent / "awards.json"
    awards_json.write_text(
        json.dumps(
            {
                "awards": {
                    "MVP": {"player_id": "P1", "player_name": "Alex Batter"},
                    "CY_YOUNG": {"player_id": "P2", "player_name": "Pat Pitcher"},
                }
            }
        ),
        encoding="utf-8",
    )
    archived_transactions = archived_standings.parent / "transactions.csv"
    archived_transactions.write_text(
        (
            "timestamp,season_date,team_id,player_id,player_name,action,from_level,to_level,counterparty,details\n"
            "2025-07-15 12:30:00,2025-07-15,T2,P2,Pat Pitcher,trade,ACT,ACT,T1,Deadline deal\n"
        ),
        encoding="utf-8",
    )
    (archived_standings.parent / "metadata.json").write_text(
        json.dumps(
            {
                "artifacts": {
                    "standings": str(archived_standings),
                    "champions": str(champions_csv),
                    "awards": str(awards_json),
                    "transactions": str(archived_transactions),
                }
            }
        ),
        encoding="utf-8",
    )

    career_index = {
        "version": 1,
        "league": {"id": "test", "name": "Test League"},
        "current": {
            "season_id": "test-2026",
            "league_year": 2026,
            "sequence": 2,
            "started_on": "2026-04-01",
            "metadata": {},
            "rollover_complete": False,
        },
        "seasons": [
            {
                "season_id": "test-2025",
                "league_year": 2025,
                "sequence": 1,
                "started_on": "2025-04-01",
                "ended_on": "2025-10-01",
                "archived_on": "2025-10-02T00:00:00Z",
                "rollover_complete": True,
            }
        ],
    }
    (data_dir / "career_index.json").write_text(
        json.dumps(career_index, indent=2),
        encoding="utf-8",
    )

    result = export_almanac(output_dir=tmp_path / "almanac_out")
    assert result.output_dir.exists()
    assert result.index_html.exists()
    assert "test-2025" in result.season_ids
    assert "test-2026" in result.season_ids
    validation = validate_almanac_export(result)
    assert validation.is_valid
    assert validation.scanned_pages >= 16
    assert not validation.issues

    landing = result.index_html.read_text(encoding="utf-8")
    css_text = result.files["css"].read_text(encoding="utf-8")
    assert "League Almanac" in landing
    assert "Season Index" in landing
    assert "class=\"toc-grid\"" in landing
    assert "stat-card" in landing
    assert "@media print" in css_text
    assert ".table-wrap" in css_text
    assert "font-variant-numeric:tabular-nums;" in css_text

    seasons_index = result.files["seasons_index_html"]
    assert seasons_index.exists()
    seasons_text = seasons_index.read_text(encoding="utf-8")
    assert "test-2025" in seasons_text
    assert "test-2026" in seasons_text

    season_2025 = result.files["season_test-2025_html"]
    season_2026 = result.files["season_test-2026_html"]
    assert season_2025.exists()
    assert season_2026.exists()
    season_2025_text = season_2025.read_text(encoding="utf-8")
    season_2026_text = season_2026.read_text(encoding="utf-8")
    assert "Standings" in season_2025_text
    assert "Standings" in season_2026_text
    assert "season-links" in season_2025_text
    assert "Awards" in season_2025_text
    assert "Postseason" in season_2025_text
    assert "../teams/T1.html" in season_2025_text
    assert "../teams/T2.html" in season_2026_text
    assert "../players/P1.html" in season_2025_text
    assert "../players/P2.html" in season_2025_text

    teams_index = result.files["teams_index_html"]
    assert teams_index.exists()
    teams_text = teams_index.read_text(encoding="utf-8")
    assert "T1.html" in teams_text
    assert "T2.html" in teams_text

    team_1_page = result.files["team_T1_html"]
    team_2_page = result.files["team_T2_html"]
    assert team_1_page.exists()
    assert team_2_page.exists()
    team_1_text = team_1_page.read_text(encoding="utf-8")
    team_2_text = team_2_page.read_text(encoding="utf-8")
    assert "Year-by-Year History" in team_1_text
    assert "../seasons/test-2025.html" in team_1_text
    assert "../seasons/test-2026.html" in team_1_text
    assert "80" in team_1_text
    assert "12" in team_1_text
    assert "Yes" in team_2_text

    assert result.files["players_index_html"].exists()
    players_index = result.files["players_index_html"]
    players_text = players_index.read_text(encoding="utf-8")
    assert "P1.html" in players_text
    assert "P2.html" in players_text
    assert "../teams/T1.html" in players_text

    player_1_page = result.files["player_P1_html"]
    player_2_page = result.files["player_P2_html"]
    assert player_1_page.exists()
    assert player_2_page.exists()
    player_1_text = player_1_page.read_text(encoding="utf-8")
    player_2_text = player_2_page.read_text(encoding="utf-8")
    assert "Year-by-Year Log" in player_1_text
    assert "../seasons/test-2025.html" in player_1_text
    assert "../seasons/test-2026.html" in player_1_text
    assert "../teams/T1.html" in player_1_text
    assert "201" in player_1_text
    assert "0.901" in player_1_text
    assert "Career ERA" in player_2_text
    assert "../teams/T2.html" in player_2_text

    awards_index = result.files["awards_index_html"]
    postseason_index = result.files["postseason_index_html"]
    leaders_index = result.files["leaders_index_html"]
    assert awards_index.exists()
    assert postseason_index.exists()
    assert leaders_index.exists()
    awards_text = awards_index.read_text(encoding="utf-8")
    postseason_text = postseason_index.read_text(encoding="utf-8")
    leaders_text = leaders_index.read_text(encoding="utf-8")
    assert "Alex Batter" in awards_text
    assert "Pat Pitcher" in awards_text
    assert "T2" in postseason_text
    assert "4-2" in postseason_text
    assert "Batting Leaders" in leaders_text
    assert "Pitching Leaders" in leaders_text
    assert "Alex Batter" in leaders_text
    assert "Pat Pitcher" in leaders_text

    transactions_index = result.files["transactions_index_html"]
    finance_index = result.files["finance_index_html"]
    assert transactions_index.exists()
    assert finance_index.exists()
    transactions_text = transactions_index.read_text(encoding="utf-8")
    finance_text = finance_index.read_text(encoding="utf-8")
    assert "Opening Day promotion" in transactions_text
    assert "Deadline deal" in transactions_text
    assert "../players/P1.html" in transactions_text
    assert "../players/P2.html" in transactions_text
    assert "class=\"data-table\"" in transactions_text
    assert "Season Finance Summary" in finance_text
    assert "$8,000,000" in finance_text
    assert "May gate receipts" in finance_text
    assert "../teams/T1.html" in finance_text

    assert result.files["records_index_html"].exists()
    records_text = result.files["records_index_html"].read_text(encoding="utf-8")
    assert "../players/P1.html" in records_text


def test_validate_almanac_export_reports_missing_files_and_broken_links(tmp_path):
    output_dir = tmp_path / "almanac_out"
    almanac_dir = output_dir / "almanac"
    assets_dir = almanac_dir / "assets"
    seasons_dir = almanac_dir / "seasons"
    teams_dir = almanac_dir / "teams"
    players_dir = almanac_dir / "players"
    awards_dir = almanac_dir / "awards"
    postseason_dir = almanac_dir / "postseason"
    leaders_dir = almanac_dir / "leaders"
    transactions_dir = almanac_dir / "transactions"
    records_dir = almanac_dir / "records"

    for directory in (
        assets_dir,
        seasons_dir,
        teams_dir,
        players_dir,
        awards_dir,
        postseason_dir,
        leaders_dir,
        transactions_dir,
        records_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    css_path = assets_dir / "almanac.css"
    css_path.write_text("body{}", encoding="utf-8")
    index_html = almanac_dir / "index.html"
    index_html.write_text(
        "<html><head><link rel=\"stylesheet\" href=\"assets/almanac.css\"></head>"
        "<body><a href=\"missing-page.html\">Broken</a></body></html>",
        encoding="utf-8",
    )
    for path in (
        seasons_dir / "index.html",
        teams_dir / "index.html",
        players_dir / "index.html",
        awards_dir / "index.html",
        postseason_dir / "index.html",
        leaders_dir / "index.html",
        transactions_dir / "index.html",
        records_dir / "index.html",
    ):
        path.write_text("<html><body>ok</body></html>", encoding="utf-8")

    result = AlmanacExportResult(
        output_dir=output_dir,
        index_html=index_html,
        files={
            "almanac_dir": almanac_dir,
            "css": css_path,
            "index_html": index_html,
            "seasons_index_html": seasons_dir / "index.html",
            "teams_index_html": teams_dir / "index.html",
            "players_index_html": players_dir / "index.html",
            "awards_index_html": awards_dir / "index.html",
            "postseason_index_html": postseason_dir / "index.html",
            "leaders_index_html": leaders_dir / "index.html",
            "transactions_index_html": transactions_dir / "index.html",
            "records_index_html": records_dir / "index.html",
        },
        season_ids=[],
    )

    validation = validate_almanac_export(result)

    assert not validation.is_valid
    assert "finance_index_html" in validation.missing_files
    assert any("missing-page.html" in issue for issue in validation.broken_links)
