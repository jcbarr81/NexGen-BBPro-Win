import json
import random
from types import SimpleNamespace

from models.player import Player
from models.team import Team
from services.finance_settings import ensure_financial_defaults, update_financial_settings
from services.free_agency import (
    estimate_cpu_free_agency_rounds,
    list_unsigned_players,
    list_unsigned_players_from_files,
    run_cpu_free_agency_market,
    run_cpu_free_agency_round,
    sign_player_to_team,
)


def make_player(pid: str) -> Player:
    return Player(
        player_id=pid,
        first_name="Test",
        last_name="Player",
        birthdate="2000-01-01",
        height=72,
        weight=180,
        bats="R",
        primary_position="P",
        other_positions=[],
        gf=0,
    )


def make_team() -> Team:
    return Team(
        team_id="t1",
        name="Team",
        city="City",
        abbreviation="T1",
        division="Division",
        stadium="Stadium",
        primary_color="#FFFFFF",
        secondary_color="#000000",
        owner_id="owner",
    )


def test_list_and_sign_players() -> None:
    players = {"p1": make_player("p1"), "p2": make_player("p2")}
    team = make_team()

    unsigned = list_unsigned_players(players, [team])
    assert {p.player_id for p in unsigned} == {"p1", "p2"}

    sign_player_to_team("p1", team)
    assert team.act_roster == ["p1"]

    unsigned = list_unsigned_players(players, [team])
    assert [p.player_id for p in unsigned] == ["p2"]


def test_list_unsigned_players_from_files_uses_rosters(monkeypatch) -> None:
    team = make_team()
    players = [make_player("p1"), make_player("p2"), make_player("p3")]
    roster = SimpleNamespace(act=["p1"], aaa=["p2"], low=[])

    monkeypatch.setattr(
        "services.free_agency.load_players_from_csv",
        lambda *_args, **_kwargs: players,
    )
    monkeypatch.setattr(
        "services.free_agency.load_teams",
        lambda *_args, **_kwargs: [team],
    )
    monkeypatch.setattr(
        "services.free_agency.load_roster",
        lambda *_args, **_kwargs: roster,
    )

    unsigned = list_unsigned_players_from_files(data_dir=".")
    assert [player.player_id for player in unsigned] == ["p3"]


def test_run_cpu_free_agency_round_signs_unsigned_players(tmp_path) -> None:
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,CPU Club,City,AAA,East,Park,#112233,#445566,cpu\n"
        "BBB,Human Club,Town,BBB,West,Park,#221133,#665544,owner_1\n",
        encoding="utf-8",
    )
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )
    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {"wins": 86, "losses": 76},
                "BBB": {"wins": 74, "losses": 88},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "players.csv").write_text(
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
        "P100,Free,Agent,2000-01-01,72,190,R,1B,,50,64,60,50,55,55,55,55,58,56,0\n",
        encoding="utf-8",
    )
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("", encoding="utf-8")

    summary = run_cpu_free_agency_round(
        data_dir=data_dir,
        league_id="test",
        max_signings=3,
        rng=random.Random(7),
    )

    assert summary["signed_players"] >= 1
    signings = summary["signings"]
    assert isinstance(signings, list) and signings
    assert signings[0]["team_id"] == "AAA"
    contracts = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    assert "P100" in contracts.get("players", {})
    roster_text = (roster_dir / "AAA.csv").read_text(encoding="utf-8")
    assert "P100" in roster_text


def test_estimate_cpu_free_agency_rounds_scales_with_unsigned_players() -> None:
    few = estimate_cpu_free_agency_rounds(
        2,
        cpu_team_count=1,
        free_agency_level="advanced",
    )
    many = estimate_cpu_free_agency_rounds(
        18,
        cpu_team_count=1,
        free_agency_level="advanced",
    )
    assert many > few
    assert few >= 1


def test_run_cpu_free_agency_market_runs_multiple_rounds_for_large_pool(tmp_path) -> None:
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,CPU Club,City,AAA,East,Park,#112233,#445566,cpu\n"
        "BBB,CPU Club B,Town,BBB,West,Park,#221133,#665544,cpu\n",
        encoding="utf-8",
    )
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )
    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {"wins": 90, "losses": 72},
                "BBB": {"wins": 70, "losses": 92},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    player_rows = [
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher"
    ]
    for idx in range(1, 13):
        player_rows.append(
            f"P{idx:03d},Free,Agent{idx},2000-01-01,72,190,R,1B,,50,62,59,52,55,55,55,55,57,56,0"
        )
    (data_dir / "players.csv").write_text("\n".join(player_rows) + "\n", encoding="utf-8")
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("", encoding="utf-8")
    (roster_dir / "BBB.csv").write_text("", encoding="utf-8")

    summary = run_cpu_free_agency_market(
        data_dir=data_dir,
        league_id="test",
        rng=random.Random(11),
    )

    assert summary["rounds_planned"] >= 2
    assert summary["rounds_run"] >= 2
    assert summary["signed_players"] > 0


def test_cpu_free_agency_standard_allows_warn_level_signing_over_threshold(tmp_path) -> None:
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,CPU Club,City,AAA,East,Park,#112233,#445566,cpu\n",
        encoding="utf-8",
    )
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P_BIG": {
                        "team_id": "AAA",
                        "years_left": 2,
                        "annual_salary": 130_000_000,
                        "service_time_days": 500,
                        "arb_eligible": False,
                        "fa_year": 2033,
                        "options": [],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "standings.json").write_text(
        json.dumps({"AAA": {"wins": 86, "losses": 76}}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "players.csv").write_text(
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
        "P100,Free,Agent,2000-01-01,72,190,R,1B,,50,64,60,50,55,55,55,55,58,56,0\n",
        encoding="utf-8",
    )
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("P_BIG,ACT\n", encoding="utf-8")

    summary = run_cpu_free_agency_round(
        data_dir=data_dir,
        league_id="test",
        max_signings=2,
        rng=random.Random(7),
    )

    assert summary["signed_players"] >= 1


def test_cpu_free_agency_mlb_like_blocks_signing_when_policy_blocks(tmp_path) -> None:
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,CPU Club,City,AAA,East,Park,#112233,#445566,cpu\n",
        encoding="utf-8",
    )
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="mlb_like",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P_BIG": {
                        "team_id": "AAA",
                        "years_left": 2,
                        "annual_salary": 250_000_000,
                        "service_time_days": 500,
                        "arb_eligible": False,
                        "fa_year": 2033,
                        "options": [],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "standings.json").write_text(
        json.dumps({"AAA": {"wins": 86, "losses": 76}}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "players.csv").write_text(
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
        "P100,Free,Agent,2000-01-01,72,190,R,1B,,50,64,60,50,55,55,55,55,58,56,0\n",
        encoding="utf-8",
    )
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("P_BIG,ACT\n", encoding="utf-8")

    summary = run_cpu_free_agency_round(
        data_dir=data_dir,
        league_id="test",
        max_signings=2,
        rng=random.Random(7),
    )

    assert summary["signed_players"] == 0
    contracts = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    assert "P100" not in contracts.get("players", {})
