from __future__ import annotations

import json
from types import SimpleNamespace

from services.contracts_service import (
    DEFAULT_MIN_SALARY,
    contract_payroll_value,
    extend_contract,
    get_contract,
    remove_contract,
    rollover_contracts_for_new_season,
    set_contract_option_decision,
    sign_free_agent_contract,
    transfer_contract,
    transfer_contracts,
    upsert_contract,
)
from services.finance_ledger import CATEGORY_CONTRACT_BUYOUT
from services.prospect_event_log import (
    EVENT_TYPE_OPTION_DECISION,
    load_prospect_events,
)


def test_upsert_contract_persists_and_gets(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    upsert_contract(
        "P100",
        team_id="AAA",
        annual_salary=2_500_000,
        years_left=3,
        season_year=2032,
        data_dir=data_dir,
    )
    contract = get_contract("P100", data_dir=data_dir)

    assert contract is not None
    assert contract["team_id"] == "AAA"
    assert contract["annual_salary"] == 2_500_000
    assert contract["years_left"] == 3
    assert contract["fa_year"] == 2035


def test_sign_free_agent_contract_estimates_salary(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    player = SimpleNamespace(
        player_id="P200",
        is_pitcher=False,
        primary_position="SS",
        ch=72,
        ph=70,
        sp=65,
        eye=68,
        fa=66,
        arm=64,
    )

    contract = sign_free_agent_contract(
        "P200",
        "BBB",
        player=player,
        season_year=2033,
        data_dir=data_dir,
    )

    assert contract["team_id"] == "BBB"
    assert contract["annual_salary"] >= DEFAULT_MIN_SALARY
    assert contract["fa_year"] == 2034


def test_transfer_contract_updates_team_and_preserves_salary(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    upsert_contract(
        "P300",
        team_id="AAA",
        annual_salary=4_100_000,
        years_left=2,
        season_year=2031,
        data_dir=data_dir,
    )

    transfer_contract("P300", "CCC", data_dir=data_dir)
    updated = get_contract("P300", data_dir=data_dir)

    assert updated is not None
    assert updated["team_id"] == "CCC"
    assert updated["annual_salary"] == 4_100_000
    assert updated["years_left"] == 2


def test_transfer_contracts_create_missing_entries(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    players = {
        "P400": SimpleNamespace(
            player_id="P400",
            is_pitcher=True,
            primary_position="P",
            arm=74,
            control=70,
            movement=67,
            endurance=65,
        )
    }

    updated = transfer_contracts(
        ["P400"],
        "DDD",
        players_by_id=players,
        create_if_missing=True,
        season_year=2034,
        data_dir=data_dir,
    )

    assert "P400" in updated
    assert updated["P400"]["team_id"] == "DDD"
    assert updated["P400"]["annual_salary"] >= DEFAULT_MIN_SALARY

    payload = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    assert "P400" in payload.get("players", {})


def test_remove_contract_deletes_entry(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    upsert_contract(
        "P500",
        team_id="AAA",
        annual_salary=1_500_000,
        season_year=2030,
        data_dir=data_dir,
    )
    assert remove_contract("P500", data_dir=data_dir) is True
    assert get_contract("P500", data_dir=data_dir) is None


def test_rollover_contracts_decrements_years_and_updates_fa_year(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    upsert_contract(
        "P600",
        team_id="AAA",
        annual_salary=6_500_000,
        years_left=3,
        season_year=2030,
        data_dir=data_dir,
    )

    summary = rollover_contracts_for_new_season(
        season_year=2031,
        data_dir=data_dir,
    )
    contract = get_contract("P600", data_dir=data_dir)

    assert summary["processed"] == 1
    assert summary["retained"] == 1
    assert summary["expired"] == 0
    assert contract is not None
    assert contract["years_left"] == 2
    assert contract["fa_year"] == 2033


def test_rollover_contracts_expires_one_year_deals(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "BBB.csv").write_text(
        "P700,ACT\n",
        encoding="utf-8",
    )
    upsert_contract(
        "P700",
        team_id="BBB",
        annual_salary=2_000_000,
        years_left=1,
        season_year=2030,
        data_dir=data_dir,
    )

    summary = rollover_contracts_for_new_season(
        season_year=2031,
        data_dir=data_dir,
    )

    assert summary["processed"] == 1
    assert summary["retained"] == 0
    assert summary["expired"] == 1
    assert "P700" in summary["expired_player_ids"]
    assert summary["released_from_rosters"] == 1
    assert summary["release_teams"] == ["BBB"]
    assert get_contract("P700", data_dir=data_dir) is None
    assert (roster_dir / "BBB.csv").read_text(encoding="utf-8").strip() == ""
    transactions = (data_dir / "transactions.csv").read_text(encoding="utf-8")
    assert "contract_expired" in transactions


def test_extend_contract_updates_years_and_terms(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    upsert_contract(
        "P800",
        team_id="AAA",
        annual_salary=3_000_000,
        years_left=1,
        season_year=2031,
        data_dir=data_dir,
    )

    updated = extend_contract(
        "P800",
        additional_years=2,
        annual_salary=4_500_000,
        options=[{"type": "team", "salary": 5_000_000, "buyout": 600_000}],
        incentives=[{"label": "MVP", "amount": 1_000_000, "expected_probability": 0.2}],
        season_year=2032,
        data_dir=data_dir,
    )

    assert updated is not None
    assert updated["years_left"] == 3
    assert updated["annual_salary"] == 4_500_000
    assert updated["fa_year"] == 2035
    assert updated["options"][0]["salary"] == 5_000_000
    assert updated["incentives"][0]["expected_payout"] == 200_000


def test_rollover_exercises_option_when_marked_exercised(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    upsert_contract(
        "P900",
        team_id="AAA",
        annual_salary=3_200_000,
        years_left=1,
        season_year=2030,
        options=[{"type": "team", "salary": 4_800_000, "buyout": 400_000}],
        data_dir=data_dir,
    )
    changed = set_contract_option_decision(
        "P900",
        decision="exercised",
        data_dir=data_dir,
    )
    assert changed is not None

    summary = rollover_contracts_for_new_season(
        season_year=2031,
        data_dir=data_dir,
    )
    contract = get_contract("P900", data_dir=data_dir)

    assert summary["option_exercised"] == 1
    assert summary["expired"] == 0
    assert contract is not None
    assert contract["years_left"] == 1
    assert contract["annual_salary"] == 4_800_000
    assert contract["fa_year"] == 2032
    option_events = load_prospect_events(
        player_id="P900",
        data_dir=data_dir,
        event_types=[EVENT_TYPE_OPTION_DECISION],
    )
    assert option_events
    assert option_events[0].get("details", {}).get("decision") == "exercised"


def test_rollover_declined_option_posts_buyout(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    upsert_contract(
        "P901",
        team_id="AAA",
        annual_salary=3_500_000,
        years_left=1,
        season_year=2030,
        options=[{"type": "team", "salary": 5_000_000, "buyout": 750_000, "decision": "declined"}],
        data_dir=data_dir,
    )

    summary = rollover_contracts_for_new_season(
        season_year=2031,
        data_dir=data_dir,
    )

    assert summary["option_declined"] == 1
    assert summary["buyout_total"] == 750_000
    assert get_contract("P901", data_dir=data_dir) is None
    ledger = (data_dir / "financial_transactions.csv").read_text(encoding="utf-8")
    assert CATEGORY_CONTRACT_BUYOUT in ledger
    assert "P901" in ledger
    option_events = load_prospect_events(
        player_id="P901",
        data_dir=data_dir,
        event_types=[EVENT_TYPE_OPTION_DECISION],
    )
    assert option_events
    assert option_events[0].get("details", {}).get("decision") == "declined"


def test_rollover_resets_incentive_statuses_on_retained_contract(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    upsert_contract(
        "P904",
        team_id="AAA",
        annual_salary=3_800_000,
        years_left=2,
        season_year=2030,
        incentives=[
            {
                "label": "All-Star",
                "amount": 600_000,
                "expected_probability": 0.4,
                "status": "earned",
                "actual_payout": 600_000,
            }
        ],
        data_dir=data_dir,
    )

    summary = rollover_contracts_for_new_season(
        season_year=2031,
        data_dir=data_dir,
    )
    contract = get_contract("P904", data_dir=data_dir)

    assert summary["retained"] == 1
    assert contract is not None
    incentives = contract.get("incentives") or []
    assert len(incentives) == 1
    assert incentives[0]["status"] == "pending"
    assert int(incentives[0].get("actual_payout", 0) or 0) == 0


def test_contract_payroll_value_includes_expected_incentives():
    value = contract_payroll_value(
        {
            "annual_salary": 10_000_000,
            "incentives": [
                {"label": "MVP", "amount": 1_000_000, "expected_probability": 0.5},
                {"label": "All-Star", "amount": 500_000, "status": "earned"},
            ],
        }
    )
    assert value == 11_000_000


def test_extend_contract_allows_term_updates_without_new_years(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    upsert_contract(
        "P902",
        team_id="AAA",
        annual_salary=2_000_000,
        years_left=2,
        season_year=2030,
        data_dir=data_dir,
    )
    updated = extend_contract(
        "P902",
        additional_years=0,
        options=[{"type": "player", "salary": 2_500_000, "buyout": 100_000}],
        incentives=[{"label": "Cy Young", "amount": 500_000, "expected_probability": 0.1}],
        season_year=2030,
        data_dir=data_dir,
    )
    assert updated is not None
    assert updated["years_left"] == 2
    assert updated["options"][0]["type"] == "player"
    assert updated["incentives"][0]["expected_payout"] == 50_000


def test_set_contract_option_decision_persists_lifecycle_event(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    upsert_contract(
        "P950",
        team_id="AAA",
        annual_salary=2_200_000,
        years_left=1,
        season_year=2030,
        options=[{"type": "team", "salary": 3_000_000, "buyout": 200_000}],
        data_dir=data_dir,
    )

    changed = set_contract_option_decision(
        "P950",
        decision="declined",
        option_index=0,
        data_dir=data_dir,
    )

    assert changed is not None
    events = load_prospect_events(
        player_id="P950",
        data_dir=data_dir,
        event_types=[EVENT_TYPE_OPTION_DECISION],
    )
    assert events
    latest = events[0]
    assert latest["team_id"] == "AAA"
    assert latest.get("details", {}).get("decision") == "declined"


def test_extend_contract_updates_guarantee_fields(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    upsert_contract(
        "P903",
        team_id="AAA",
        annual_salary=4_000_000,
        years_left=2,
        season_year=2030,
        guaranteed=True,
        buyout_guarantee=0,
        data_dir=data_dir,
    )
    updated = extend_contract(
        "P903",
        additional_years=0,
        guaranteed=False,
        buyout_guarantee=750_000,
        season_year=2030,
        data_dir=data_dir,
    )

    assert updated is not None
    assert updated["years_left"] == 2
    assert updated["guaranteed"] is False
    assert updated["buyout_guarantee"] == 750_000
