from __future__ import annotations

import json

from services import gm_finance_queue
from services.contracts_service import rollover_contracts_for_new_season
from services.finance_ledger import CATEGORY_ARB_AWARD
from services.finance_settings import ensure_financial_defaults, update_financial_settings
from services.free_agency import run_cpu_free_agency_market
from services.offseason_finance_flow import (
    collect_offseason_finance_overview,
    get_offseason_checklist,
    get_offseason_stage_details,
    mark_offseason_stage,
    run_offseason_financial_rollover,
)
from utils.league_settings import configure_league_settings


def test_offseason_finance_rollover_applies_arbitration_and_resets_year(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )

    (data_dir / "team_financials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "season_year": 2030,
                "teams": {
                    "AAA": {
                        "cash_on_hand": 5_000_000,
                        "debt": 0,
                        "revenue": {
                            "tickets": 1_000_000,
                            "concessions": 200_000,
                            "media": 300_000,
                            "sponsorship": 150_000,
                        },
                        "expenses": {
                            "payroll": 750_000,
                            "training": 120_000,
                            "scouting": 90_000,
                            "facilities": 100_000,
                            "operations": 220_000,
                        },
                        "budgets": {
                            "training": 10_000,
                            "scouting": 10_000,
                            "development": 10_000,
                            "facilities": 10_000,
                        },
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {
                        "team_id": "AAA",
                        "years_left": 1,
                        "annual_salary": 5_000_000,
                        "service_time_days": 620,
                        "arb_eligible": False,
                        "fa_year": 2031,
                        "options": [],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = run_offseason_financial_rollover(
        ended_season_year=2030,
        next_season_year=2031,
        contract_rollover={"retained": 1, "expired": 0},
        data_dir=data_dir,
        league_id="test",
    )

    assert summary["snapshot_path"] == "finance_snapshots/2030.json"
    assert summary["applied"] is True
    assert summary["arbitration"]["awards"] == 1
    assert summary["arbitration"]["salary_delta"] > 0
    assert summary["team_reset"]["season_year"] == 2031
    assert summary["team_reset"]["teams_reset"] == 1
    assert summary["team_reset"]["budgets_refreshed"] == 1

    contracts = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    contract = contracts["players"]["P1"]
    assert contract["arb_eligible"] is True
    assert contract["service_time_days"] == 792
    assert contract["annual_salary"] > 5_000_000

    team_financials = json.loads((data_dir / "team_financials.json").read_text(encoding="utf-8"))
    entry = team_financials["teams"]["AAA"]
    assert team_financials["season_year"] == 2031
    assert all(value == 0 for value in entry["revenue"].values())
    assert all(value == 0 for value in entry["expenses"].values())

    snapshot = json.loads((data_dir / "finance_snapshots" / "2030.json").read_text(encoding="utf-8"))
    assert snapshot["ended_season_year"] == 2030
    assert snapshot["next_season_year"] == 2031
    assert snapshot["team_financials"]["season_year"] == 2030
    assert snapshot["contract_rollover"]["retained"] == 1

    ledger = (data_dir / "financial_transactions.csv").read_text(encoding="utf-8")
    assert CATEGORY_ARB_AWARD in ledger

    details = get_offseason_stage_details(data_dir=data_dir, league_id="test")
    arbitration_rows = details["arbitration_details"]
    assert len(arbitration_rows) == 1
    assert arbitration_rows[0]["team_id"] == "AAA"
    assert arbitration_rows[0]["delta"] > 0
    budget_rows = details["budget_deltas"]
    assert len(budget_rows) == 1
    assert budget_rows[0]["team_id"] == "AAA"
    assert details["gm_finance_queue"] == []

    second = run_offseason_financial_rollover(
        ended_season_year=2030,
        next_season_year=2031,
        data_dir=data_dir,
        league_id="test",
    )
    assert second["already_completed"] is True
    assert second["arbitration"]["awards"] == 0


def test_offseason_finance_rollover_skips_arbitration_when_finance_off(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="off",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )

    summary = run_offseason_financial_rollover(
        ended_season_year=2035,
        next_season_year=2036,
        data_dir=data_dir,
        league_id="test",
    )

    assert summary["applied"] is False
    assert summary["arbitration"]["enabled"] is False
    assert summary["arbitration"]["awards"] == 0
    assert summary["team_reset"]["season_year"] == 2036
    assert (data_dir / "finance_snapshots" / "2035.json").exists()


def test_offseason_arbitration_advanced_handles_super_two_player(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        enabled=True,
        preset="custom",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
        modules={
            "owner_revenue": "advanced",
            "owner_market_model": "basic",
            "owner_budgets": "advanced",
            "owner_expenses": "advanced",
            "gm_contracts": "advanced",
            "gm_payroll_rules": "basic",
            "gm_arbitration": "advanced",
            "gm_free_agency": "advanced",
            "gm_roster_cost_enforcement": "warn",
            "gm_finance_ai": "advanced",
        },
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P_SUPER2": {
                        "team_id": "AAA",
                        "years_left": 2,
                        "annual_salary": 4_200_000,
                        "service_time_days": 300,
                        "arb_eligible": False,
                        "fa_year": 2032,
                        "options": [],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = run_offseason_financial_rollover(
        ended_season_year=2030,
        next_season_year=2031,
        data_dir=data_dir,
        league_id="test",
    )

    assert summary["arbitration"]["awards"] >= 1
    details = summary["arbitration"].get("details") or []
    assert details
    assert details[0].get("arb_tier") == "super_two"


def test_offseason_arbitration_no_longer_policy_blocks_raise(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
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
                    "P_CAP": {
                        "team_id": "AAA",
                        "years_left": 1,
                        "annual_salary": 230_000_000,
                        "service_time_days": 620,
                        "arb_eligible": True,
                        "fa_year": 2031,
                        "options": [],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = run_offseason_financial_rollover(
        ended_season_year=2030,
        next_season_year=2031,
        data_dir=data_dir,
        league_id="test",
    )

    details = summary["arbitration"].get("details") or []
    assert details
    # Enforcement no longer hard-blocks offseason arbitration; the over-threshold
    # cost settles as luxury tax instead of producing a policy-block hold.
    assert details[0]["decision"] != "policy_block_hold"


def test_collect_offseason_finance_overview_reports_contract_and_fa_counts(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )

    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,Team A,City,AAA,East,Park,#112233,#445566,owner\n",
        encoding="utf-8",
    )
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("P1,ACT\n", encoding="utf-8")
    (data_dir / "players.csv").write_text(
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
        "P1,A,One,2000-01-01,72,180,R,1B,,50,50,50,50,50,50,50,50,50,50,0\n"
        "P2,B,Two,2000-01-01,72,180,R,SS,,50,50,50,50,50,50,50,50,50,50,0\n",
        encoding="utf-8",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {
                        "team_id": "AAA",
                        "years_left": 1,
                        "annual_salary": 3_000_000,
                        "service_time_days": 550,
                        "arb_eligible": False,
                        "fa_year": 2031,
                        "options": [],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "team_financials.json").write_text(
        json.dumps({"version": 1, "season_year": 2030, "teams": {"AAA": {}}}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "season_state.json").write_text(
        json.dumps({"phase": "OFFSEASON"}, indent=2),
        encoding="utf-8",
    )

    overview = collect_offseason_finance_overview(data_dir=data_dir, league_id="test")
    assert overview["financials_enabled"] is True
    assert overview["phase"] == "OFFSEASON"
    assert overview["contracts_total"] == 1
    assert overview["contracts_expiring"] == 1
    assert overview["arbitration_candidates"] == 1
    assert overview["unsigned_players"] == 1
    assert overview["requires_commissioner_finance_review"] is False
    assert overview["gm_queue_total"] == 0
    assert overview["can_run_now"] is True


def test_offseason_checklist_progresses_in_order(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )
    (data_dir / "season_state.json").write_text(
        json.dumps({"phase": "OFFSEASON"}, indent=2),
        encoding="utf-8",
    )

    run_offseason_financial_rollover(
        ended_season_year=2030,
        next_season_year=2031,
        data_dir=data_dir,
        league_id="test",
    )
    checklist = get_offseason_checklist(data_dir=data_dir, league_id="test")
    assert checklist["next_stage_id"] == "contracts_review"

    result = mark_offseason_stage("arbitration_review", data_dir=data_dir, league_id="test")
    assert result["ok"] is False
    assert "contracts_review" in str(result["reason"])

    result = mark_offseason_stage("contracts_review", data_dir=data_dir, league_id="test")
    assert result["ok"] is True
    checklist = result["checklist"]
    assert checklist["next_stage_id"] == "arbitration_review"

    assert mark_offseason_stage("arbitration_review", data_dir=data_dir, league_id="test")["ok"] is True
    assert mark_offseason_stage("budgets_review", data_dir=data_dir, league_id="test")["ok"] is True
    assert mark_offseason_stage("free_agency_kickoff", data_dir=data_dir, league_id="test")["ok"] is True
    final = mark_offseason_stage("finalize", data_dir=data_dir, league_id="test")
    assert final["ok"] is True
    assert final["checklist"]["next_stage_id"] in {"", None}


def test_cpu_team_non_tenders_high_cost_underperformer(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )
    (data_dir / "users.txt").write_text("admin,pass,admin,\n", encoding="utf-8")
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,CPU Club,City,AAA,East,Park,#112233,#445566,cpu\n",
        encoding="utf-8",
    )
    (data_dir / "players.csv").write_text(
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
        "P9,Expensive,Bat,2000-01-01,72,190,R,1B,,50,55,54,40,40,55,55,45,48,50,0\n",
        encoding="utf-8",
    )
    (data_dir / "season_stats.json").write_text(
        json.dumps(
            {
                "players": {
                    "P9": {
                        "ops": 0.58,
                        "ab": 520,
                        "h": 108,
                    }
                },
                "teams": {},
                "history": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("P9,ACT\n", encoding="utf-8")
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P9": {
                        "team_id": "AAA",
                        "years_left": 1,
                        "annual_salary": 25_000_000,
                        "service_time_days": 620,
                        "arb_eligible": False,
                        "fa_year": 2031,
                        "options": [],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "team_financials.json").write_text(
        json.dumps({"version": 1, "season_year": 2030, "teams": {"AAA": {}}}, indent=2),
        encoding="utf-8",
    )

    result = run_offseason_financial_rollover(
        ended_season_year=2030,
        next_season_year=2031,
        data_dir=data_dir,
        league_id="test",
    )

    arbitration = result.get("arbitration", {})
    assert arbitration.get("cpu_non_tenders") == 1
    assert arbitration.get("cpu_releases") == 1
    contracts = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    assert contracts.get("players", {}) == {}
    assert (roster_dir / "AAA.csv").read_text(encoding="utf-8").strip() == ""


def test_owner_league_offseason_requires_gm_queue_resolution_stage(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )
    configure_league_settings(
        mode="owner_league",
        commissioner_password="secret",
        path=data_dir / "league_settings.json",
    )
    (data_dir / "team_financials.json").write_text(
        json.dumps({"version": 1, "season_year": 2030, "teams": {"AAA": {}}}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "season_state.json").write_text(
        json.dumps({"phase": "OFFSEASON"}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {
                        "team_id": "AAA",
                        "years_left": 1,
                        "annual_salary": 5_000_000,
                        "service_time_days": 620,
                        "arb_eligible": True,
                        "fa_year": 2031,
                        "options": [],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    gm_finance_queue.save_team_queue_decision(
        "AAA",
        queue_type="arbitration",
        item_id="P1",
        action="offer_raise",
        review_status="pending_commissioner",
        payload={"projected_salary": 6_500_000},
        data_dir=data_dir,
    )

    run_offseason_financial_rollover(
        ended_season_year=2030,
        next_season_year=2031,
        data_dir=data_dir,
        league_id="test",
    )
    assert mark_offseason_stage("contracts_review", data_dir=data_dir, league_id="test")["ok"] is True
    assert mark_offseason_stage("arbitration_review", data_dir=data_dir, league_id="test")["ok"] is True

    checklist = get_offseason_checklist(data_dir=data_dir, league_id="test")
    assert checklist["next_stage_id"] == "gm_finance_review"
    details = get_offseason_stage_details(data_dir=data_dir, league_id="test")
    gm_rows = details.get("gm_finance_queue") or []
    assert len(gm_rows) == 1
    assert gm_rows[0]["review_status"] == "pending_commissioner"
    blocked = mark_offseason_stage("gm_finance_review", data_dir=data_dir, league_id="test")
    assert blocked["ok"] is False
    assert "pending" in str(blocked["reason"]).lower()

    gm_finance_queue.set_queue_review_status(
        "AAA",
        queue_type="arbitration",
        item_id="P1",
        review_status="approved_commissioner",
        data_dir=data_dir,
    )
    completed = mark_offseason_stage("gm_finance_review", data_dir=data_dir, league_id="test")
    assert completed["ok"] is True
    apply_summary = completed.get("apply_summary") or {}
    assert int(apply_summary.get("applied", 0) or 0) == 1

    contracts = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    assert contracts["players"]["P1"]["annual_salary"] == 6_500_000

    checklist = get_offseason_checklist(data_dir=data_dir, league_id="test")
    assert checklist["next_stage_id"] == "budgets_review"


def test_full_offseason_sequence_single_player_mode(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )
    (data_dir / "season_state.json").write_text(
        json.dumps({"phase": "OFFSEASON"}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,CPU Club,City,AAA,East,Park,#112233,#445566,cpu\n",
        encoding="utf-8",
    )
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("P_ARB,ACT\n", encoding="utf-8")
    (data_dir / "players.csv").write_text(
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
        "P_ARB,Arb,Player,2000-01-01,72,190,R,1B,,50,70,68,52,64,55,55,55,58,56,0\n"
        "P_FA,Free,Agent,2000-01-01,72,190,R,SS,,50,74,72,58,68,55,55,55,62,58,0\n",
        encoding="utf-8",
    )
    (data_dir / "standings.json").write_text(
        json.dumps({"AAA": {"wins": 88, "losses": 74}}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P_ARB": {
                        "team_id": "AAA",
                        "years_left": 1,
                        "annual_salary": 5_500_000,
                        "service_time_days": 620,
                        "arb_eligible": False,
                        "fa_year": 2031,
                        "options": [],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    offseason = run_offseason_financial_rollover(
        ended_season_year=2030,
        next_season_year=2031,
        data_dir=data_dir,
        league_id="test",
    )
    assert offseason["arbitration"]["awards"] >= 1

    market = run_cpu_free_agency_market(
        data_dir=data_dir,
        league_id="test",
        max_rounds=2,
    )
    assert market["signed_players"] >= 1

    rollover = rollover_contracts_for_new_season(
        season_year=2032,
        data_dir=data_dir,
    )
    assert rollover["processed"] >= 1
    assert rollover["processed"] == (rollover["retained"] + rollover["expired"])


def test_full_offseason_sequence_multi_owner_queue_apply_and_rollover(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard",
        path=data_dir / "league_financial_settings.json",
        league_id="test",
    )
    configure_league_settings(
        mode="owner_league",
        commissioner_password="secret",
        path=data_dir / "league_settings.json",
    )
    (data_dir / "season_state.json").write_text(
        json.dumps({"phase": "OFFSEASON"}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,Owner Club,City,AAA,East,Park,#112233,#445566,owner_1\n",
        encoding="utf-8",
    )
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("P_ARB,ACT\n", encoding="utf-8")
    (data_dir / "players.csv").write_text(
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
        "P_ARB,Arb,Player,2000-01-01,72,190,R,1B,,50,70,68,52,64,55,55,55,58,56,0\n"
        "P_FA,Free,Agent,2000-01-01,72,190,R,SS,,50,74,72,58,68,55,55,55,62,58,0\n",
        encoding="utf-8",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P_ARB": {
                        "team_id": "AAA",
                        "years_left": 1,
                        "annual_salary": 5_500_000,
                        "service_time_days": 620,
                        "arb_eligible": True,
                        "fa_year": 2031,
                        "options": [],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    run_offseason_financial_rollover(
        ended_season_year=2030,
        next_season_year=2031,
        data_dir=data_dir,
        league_id="test",
    )

    arb_queue = gm_finance_queue.apply_recommended_arbitration_decisions(
        "AAA",
        data_dir=data_dir,
    )
    assert arb_queue["queued_count"] >= 1
    for row in gm_finance_queue.list_team_queue_decisions(
        "AAA",
        queue_type="arbitration",
        data_dir=data_dir,
    ):
        gm_finance_queue.set_queue_review_status(
            "AAA",
            queue_type="arbitration",
            item_id=str(row.get("item_id") or ""),
            review_status="approved_commissioner",
            data_dir=data_dir,
        )
    arb_apply = gm_finance_queue.apply_approved_queue_decisions(
        team_id="AAA",
        queue_type="arbitration",
        data_dir=data_dir,
    )
    assert int(arb_apply.get("applied", 0) or 0) >= 1

    fa_queue = gm_finance_queue.apply_recommended_free_agency_targets(
        "AAA",
        data_dir=data_dir,
        limit=1,
    )
    assert fa_queue["queued_count"] == 1
    for row in gm_finance_queue.list_team_queue_decisions(
        "AAA",
        queue_type="free_agency",
        data_dir=data_dir,
    ):
        gm_finance_queue.set_queue_review_status(
            "AAA",
            queue_type="free_agency",
            item_id=str(row.get("item_id") or ""),
            review_status="approved_commissioner",
            data_dir=data_dir,
        )
    fa_apply = gm_finance_queue.apply_approved_queue_decisions(
        team_id="AAA",
        queue_type="free_agency",
        data_dir=data_dir,
    )
    assert int(fa_apply.get("applied", 0) or 0) >= 1

    rollover = rollover_contracts_for_new_season(
        season_year=2032,
        data_dir=data_dir,
    )
    assert rollover["processed"] >= 1
