"""Major-league service time per player (8.5.1, ``services.service_time``).

It used to live only on contracts and only grow in the arbitration step
(skipped when that module is off), and a contract that expired took it with
it: every contract in both live leagues read 0 days.
"""

from __future__ import annotations

import json

import pytest

from services import service_time as st


@pytest.fixture
def league(tmp_path):
    base = tmp_path
    (base / "rosters").mkdir()
    (base / "rosters" / "BAL.csv").write_text(
        "A,ACT\nB,AAA\nC,DL15\nD,IR\n", encoding="utf-8")
    (base / "rosters" / "BAL_pitching.csv").write_text("A,SP1\n", encoding="utf-8")
    (base / "rosters" / "NYY.csv").write_text("E,ACT\n", encoding="utf-8")
    (base / "contracts.json").write_text(json.dumps({"version": 1, "players": {
        "A": {"team_id": "BAL", "years_left": 2, "annual_salary": 1_000_000, "service_time_days": 0},
        "B": {"team_id": "BAL", "years_left": 1, "annual_salary": 800_000, "service_time_days": 0},
        "E": {"team_id": "NYY", "years_left": 1, "annual_salary": 900_000, "service_time_days": 0},
    }}), encoding="utf-8")
    return base


def test_major_leaguers_are_credited_once_per_regular_season_date(league):
    assert st.credit_played_date("2027-04-01", phase="REGULAR_SEASON", data_dir=league) == 4
    assert st.credit_played_date("2027-04-01", phase="REGULAR_SEASON", data_dir=league) == 0
    assert st.credit_played_date("2027-10-02", phase="PLAYOFFS", data_dir=league) == 0
    credit = st.load(league)["season"]["credit"]
    # Active roster and both injured lists count; AAA does not.
    assert credit == {"A": 1, "C": 1, "D": 1, "E": 1}


def test_close_season_turns_dates_into_days_and_syncs_contracts(league):
    for day in range(1, 11):
        st.credit_played_date(f"2027-04-{day:02d}", phase="REGULAR_SEASON", data_dir=league)
    # E is sent down for the last half of the season.
    (league / "rosters" / "NYY.csv").write_text("E,AAA\n", encoding="utf-8")
    for day in range(11, 21):
        st.credit_played_date(f"2027-04-{day:02d}", phase="REGULAR_SEASON", data_dir=league)
    out = st.close_season(league)
    assert out["season_dates"] == 20
    players = st.load(league)["players"]
    assert players["A"] == 172 and players["E"] == 86
    assert "B" not in players
    assert st.load(league)["season"] == {"dates": [], "credit": {}}
    contracts = json.loads((league / "contracts.json").read_text())["players"]
    assert contracts["A"]["service_time_days"] == 172
    assert contracts["E"]["service_time_days"] == 86
    # A second season adds on.
    st.credit_played_date("2028-04-01", phase="REGULAR_SEASON", data_dir=league)
    st.close_season(league)
    assert st.service_days("A", league) == 344


def test_a_league_without_a_ledger_keeps_its_contracts_service(league):
    contracts = json.loads((league / "contracts.json").read_text())
    contracts["players"]["A"]["service_time_days"] = 600
    (league / "contracts.json").write_text(json.dumps(contracts), encoding="utf-8")
    assert st.service_days("A", league) == 600
    st.credit_played_date("2027-04-01", phase="REGULAR_SEASON", data_dir=league)
    st.close_season(league)
    assert st.service_days("A", league) == 772


def test_a_new_contract_carries_his_service(league, monkeypatch):
    from services.contracts_service import upsert_contract

    st.save({"version": 1, "players": {"Z": 900}, "season": {"dates": [], "credit": {}}}, league)
    contract = upsert_contract("Z", team_id="BAL", annual_salary=2_000_000, years_left=2,
                               season_year=2027, data_dir=league)
    assert contract["service_time_days"] == 900


def test_arbitration_reads_the_ledger_instead_of_adding_a_year(league):
    import inspect

    from services import offseason_finance_flow as off

    src = inspect.getsource(off._apply_arbitration_updates)
    assert "service_ledger.get(str(player_id)" in src


def test_seed_new_league_credits_active_players_by_age(league, monkeypatch):
    from types import SimpleNamespace

    (league / "players.csv").write_text("player_id\n", encoding="utf-8")
    monkeypatch.setattr("utils.player_loader.load_players_from_csv",
                        lambda path: [SimpleNamespace(player_id="A"), SimpleNamespace(player_id="E")])
    ages = {"A": 30, "E": 21}
    monkeypatch.setattr("services.contracts_service._player_age",
                        lambda p, season_year=None: ages.get(getattr(p, "player_id", None)))
    assert st.seed_new_league(league, season_year=2026) == 1
    assert st.service_days("A", league) == 8 * 172
    assert st.service_days("E", league) == 0
    # Never twice.
    assert st.seed_new_league(league, season_year=2026) == 0


def test_playing_time_share():
    assert st.playing_time_share({"g": 140}) == 1.0
    assert st.playing_time_share({"g": 70}) == 0.5
    assert st.playing_time_share({"g": 30, "gs": 30, "outs": 500}) == 1.0
    assert st.playing_time_share({"g": 55, "gs": 0, "outs": 180}) == 1.0
    assert round(st.playing_time_share({"g": 14, "gs": 7, "ip": 40}), 3) == round(7 / 28 + 7 / 55, 3)
    assert st.pre_league_days(22) == 0 and st.pre_league_days(30) == 8 * 172
    assert st.pre_league_days(45) == 15 * 172 and st.pre_league_days(None) == 0
