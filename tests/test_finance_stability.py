from __future__ import annotations

import json

from services.finance_stability import (
    evaluate_finance_stability_guardrails,
    run_finance_stability_preset_comparison,
    run_finance_stability_simulation,
)


def test_evaluate_finance_stability_guardrails_flags_failures():
    report = evaluate_finance_stability_guardrails(
        [
            {
                "distressed_debt_ratio": 0.72,
                "negative_cash_ratio": 0.20,
                "unsigned_ratio": 0.82,
                "payroll_spread_ratio": 3.5,
                "star_candidates": 5,
                "star_retention_rate": 0.40,
            }
        ]
    )
    assert report["passed"] is False
    failed = [row for row in report["checks"] if not row["passed"]]
    assert len(failed) >= 2


def test_run_finance_stability_simulation_generates_metrics(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,CPU A,City,AAA,East,Park,#112233,#445566,cpu\n"
        "BBB,CPU B,Town,BBB,West,Park,#221133,#665544,cpu\n",
        encoding="utf-8",
    )
    (data_dir / "players.csv").write_text(
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
        "P001,A,One,2000-01-01,72,190,R,1B,,50,64,60,50,55,55,55,55,58,56,0\n"
        "P002,B,Two,2000-01-01,72,190,R,SS,,50,62,58,54,54,55,55,55,57,55,0\n"
        "P003,C,Three,2000-01-01,72,190,R,LF,,50,59,57,53,52,55,55,55,56,54,0\n"
        "P004,D,Four,2000-01-01,72,190,R,RF,,50,60,59,52,53,55,55,55,57,55,0\n",
        encoding="utf-8",
    )
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("P001,ACT\n", encoding="utf-8")
    (roster_dir / "BBB.csv").write_text("P002,ACT\n", encoding="utf-8")
    (data_dir / "team_financials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "season_year": 2030,
                "teams": {
                    "AAA": {
                        "cash_on_hand": 5_000_000,
                        "debt": 0,
                        "revenue": {},
                        "expenses": {},
                        "budgets": {},
                    },
                    "BBB": {
                        "cash_on_hand": 5_000_000,
                        "debt": 0,
                        "revenue": {},
                        "expenses": {},
                        "budgets": {},
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = run_finance_stability_simulation(
        seasons=2,
        data_dir=data_dir,
        league_id="test",
        preset="standard",
        seed=11,
    )

    assert result["seasons_run"] == 2
    assert len(result["season_metrics"]) == 2
    first = result["season_metrics"][0]
    assert "unsigned_players" in first
    assert "fa_signed_players" in first
    assert "star_retention_rate" in first
    assert isinstance(result["guardrails"]["checks"], list)


def test_run_finance_stability_preset_comparison_runs_multiple_profiles(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,CPU A,City,AAA,East,Park,#112233,#445566,cpu\n"
        "BBB,CPU B,Town,BBB,West,Park,#221133,#665544,cpu\n",
        encoding="utf-8",
    )
    (data_dir / "players.csv").write_text(
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
        "P001,A,One,2000-01-01,72,190,R,1B,,50,64,60,50,55,55,55,55,58,56,0\n"
        "P002,B,Two,2000-01-01,72,190,R,SS,,50,62,58,54,54,55,55,55,57,55,0\n"
        "P003,C,Three,2000-01-01,72,190,R,LF,,50,59,57,53,52,55,55,55,56,54,0\n"
        "P004,D,Four,2000-01-01,72,190,R,RF,,50,60,59,52,53,55,55,55,57,55,0\n",
        encoding="utf-8",
    )
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("P001,ACT\n", encoding="utf-8")
    (roster_dir / "BBB.csv").write_text("P002,ACT\n", encoding="utf-8")
    (data_dir / "team_financials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "season_year": 2030,
                "teams": {
                    "AAA": {"cash_on_hand": 5_000_000, "debt": 0, "revenue": {}, "expenses": {}, "budgets": {}},
                    "BBB": {"cash_on_hand": 5_000_000, "debt": 0, "revenue": {}, "expenses": {}, "budgets": {}},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = run_finance_stability_preset_comparison(
        seasons=1,
        data_dir=data_dir,
        league_id="test",
        presets=["simple", "standard"],
        seed=33,
    )

    assert result["mode"] == "preset_comparison"
    rows = result["results"]
    assert isinstance(rows, list) and len(rows) == 2
    presets = {row["preset"] for row in rows}
    assert presets == {"simple", "standard"}
    for row in rows:
        assert "result" in row
        assert "guardrails_passed" in row
