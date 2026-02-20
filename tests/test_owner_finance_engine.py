from __future__ import annotations

import csv
import json

from services.finance_budget_effects import training_camp_multiplier_for_team
from services.finance_settings import (
    PRESET_OFF,
    PRESET_SIMPLE,
    PRESET_STANDARD,
    apply_financial_preset,
    ensure_financial_defaults,
    update_financial_settings,
)
from services.finance_ledger import (
    CATEGORY_FINANCE_CYCLE,
    LEDGER_TEAM_SYSTEM,
    append_financial_rows,
    build_finance_cycle_marker_row,
    list_financial_rows,
)
from services.owner_finance_engine import (
    apply_owner_finance_cadence_for_dates,
    apply_monthly_owner_finance,
    apply_monthly_owner_finance_for_dates,
    get_team_finance_snapshot,
    list_team_financial_transactions,
    period_keys_from_dates,
    project_monthly_owner_finance,
    update_team_budget_targets,
)
from services.payroll_engine import (
    calculate_annual_payroll_totals,
    calculate_monthly_payroll_totals,
)


def _write_teams(path) -> None:
    path.write_text(
        (
            "team_id,name,city,abbreviation,division,stadium,primary_color,"
            "secondary_color,owner_id\n"
            "AAA,Alphas,Alpha,AAA,East,Alpha Park,#111111,#222222,\n"
            "BBB,Bears,Beta,BBB,East,Beta Park,#111111,#222222,\n"
        ),
        encoding="utf-8",
    )


def _write_schedule(path, rows: list[tuple[str, str, str, str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "home", "away", "result", "played", "boxscore"])
        for date, home, away, result, played in rows:
            writer.writerow([date, home, away, result, played, ""])


def test_payroll_engine_totals(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {"team_id": "AAA", "annual_salary": 1_200_000},
                    "P2": {"team_id": "AAA", "annual_salary": 2_400_000},
                    "P3": {"team_id": "BBB", "annual_salary": 600_000},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    annual = calculate_annual_payroll_totals(data_dir=data_dir)
    monthly = calculate_monthly_payroll_totals(data_dir=data_dir)

    assert annual == {"AAA": 3_600_000, "BBB": 600_000}
    assert monthly == {"AAA": 300_000, "BBB": 50_000}


def test_payroll_engine_counts_expected_incentives(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {
                        "team_id": "AAA",
                        "annual_salary": 1_000_000,
                        "incentives": [
                            {"label": "Award", "amount": 600_000, "expected_probability": 0.5}
                        ],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    annual = calculate_annual_payroll_totals(data_dir=data_dir)
    monthly = calculate_monthly_payroll_totals(data_dir=data_dir)
    assert annual == {"AAA": 1_300_000}
    assert monthly == {"AAA": 108_333}


def test_project_monthly_owner_finance_respects_global_off(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_OFF,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")

    assert set(snapshots.keys()) == {"AAA", "BBB"}
    for snapshot in snapshots.values():
        assert snapshot.financials_enabled is False
        assert snapshot.projected_net == 0
        assert all(value == 0 for value in snapshot.projected_revenue.values())
        assert all(value == 0 for value in snapshot.projected_expenses.values())


def test_apply_monthly_owner_finance_is_idempotent_per_period(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_SIMPLE,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {"team_id": "AAA", "annual_salary": 1_200_000},
                    "P2": {"team_id": "BBB", "annual_salary": 2_400_000},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    first = apply_monthly_owner_finance(
        data_dir=data_dir,
        league_id="alpha",
        period_key="2032-04",
    )
    second = apply_monthly_owner_finance(
        data_dir=data_dir,
        league_id="alpha",
        period_key="2032-04",
    )

    assert first["applied"] is True
    assert first["applied_teams"] == 2
    assert second["applied"] is False
    assert second["applied_teams"] == 0

    payload = json.loads((data_dir / "team_financials.json").read_text(encoding="utf-8"))
    assert payload["teams"]["AAA"]["expenses"]["payroll"] == 100_000
    assert payload["teams"]["BBB"]["expenses"]["payroll"] == 200_000

    rows = list(
        csv.DictReader((data_dir / "financial_transactions.csv").read_text(encoding="utf-8").splitlines())
    )
    cycles = [
        row for row in rows
        if row.get("team_id") == LEDGER_TEAM_SYSTEM
        and row.get("category") == CATEGORY_FINANCE_CYCLE
        and row.get("memo") == "2032-04"
    ]
    assert len(cycles) == 1

    snapshot = get_team_finance_snapshot("AAA", data_dir=data_dir, league_id="alpha")
    assert snapshot is not None
    assert snapshot.projected_expenses["payroll"] == 100_000


def test_update_team_budget_targets_persists_values(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_SIMPLE,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    result = update_team_budget_targets(
        "AAA",
        {
            "training": 123_456,
            "scouting": 234_567,
            "development": 345_678,
            "facilities": 456_789,
        },
        data_dir=data_dir,
        league_id="alpha",
    )

    assert result["saved"] is True
    payload = json.loads((data_dir / "team_financials.json").read_text(encoding="utf-8"))
    budgets = payload["teams"]["AAA"]["budgets"]
    assert budgets["training"] == 123_456
    assert budgets["scouting"] == 234_567
    assert budgets["development"] == 345_678
    assert budgets["facilities"] == 456_789


def test_update_team_budget_targets_respects_disabled_module(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_OFF,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    result = update_team_budget_targets(
        "AAA",
        {"training": 111_000},
        data_dir=data_dir,
        league_id="alpha",
    )

    assert result["saved"] is False
    assert "disabled" in str(result.get("message") or "").lower()


def test_budget_target_updates_are_league_scoped_and_change_budget_effects(tmp_path):
    alpha_dir = tmp_path / "league-alpha"
    beta_dir = tmp_path / "league-beta"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    beta_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(alpha_dir / "teams.csv")
    _write_teams(beta_dir / "teams.csv")

    ensure_financial_defaults(data_dir=alpha_dir, league_id="alpha")
    ensure_financial_defaults(data_dir=beta_dir, league_id="beta")
    apply_financial_preset(
        PRESET_STANDARD,
        path=alpha_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    apply_financial_preset(
        PRESET_STANDARD,
        path=beta_dir / "league_financial_settings.json",
        league_id="beta",
    )

    baseline_alpha = training_camp_multiplier_for_team(
        "AAA",
        data_dir=alpha_dir,
        league_id="alpha",
    )
    baseline_beta = training_camp_multiplier_for_team(
        "AAA",
        data_dir=beta_dir,
        league_id="beta",
    )

    result = update_team_budget_targets(
        "AAA",
        {
            "training": 2_000_000,
            "scouting": 2_000_000,
            "development": 2_000_000,
            "facilities": 2_000_000,
        },
        data_dir=alpha_dir,
        league_id="alpha",
    )

    assert result["saved"] is True
    updated_alpha = training_camp_multiplier_for_team(
        "AAA",
        data_dir=alpha_dir,
        league_id="alpha",
    )
    unchanged_beta = training_camp_multiplier_for_team(
        "AAA",
        data_dir=beta_dir,
        league_id="beta",
    )

    assert updated_alpha > baseline_alpha
    assert unchanged_beta == baseline_beta


def test_period_keys_from_dates_dedupes_in_order():
    periods = period_keys_from_dates(
        [
            "2032-04-01",
            "2032-04-15",
            "2032-05-01",
            "bad-date",
            "",
            "2032-05-20",
            "2032-06-03T00:00:00Z",
        ]
    )
    assert periods == ["2032-04", "2032-05", "2032-06"]


def test_apply_monthly_owner_finance_for_dates_applies_each_month_once(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_SIMPLE,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {"team_id": "AAA", "annual_salary": 1_200_000},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    dates = ["2032-04-28", "2032-04-29", "2032-05-01", "2032-05-02"]

    first = apply_monthly_owner_finance_for_dates(
        dates,
        data_dir=data_dir,
        league_id="alpha",
    )
    second = apply_monthly_owner_finance_for_dates(
        dates,
        data_dir=data_dir,
        league_id="alpha",
    )

    assert first["applied_periods"] == ["2032-04", "2032-05"]
    assert second["applied_periods"] == []
    assert second["skipped_periods"] == ["2032-04", "2032-05"]

    payload = json.loads((data_dir / "team_financials.json").read_text(encoding="utf-8"))
    assert payload["teams"]["AAA"]["expenses"]["payroll"] == 200_000


def test_list_team_financial_transactions_returns_latest_first(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ledger = data_dir / "financial_transactions.csv"
    ledger.write_text(
        (
            "timestamp,season_year,team_id,category,amount,memo\n"
            "2032-04-01T00:00:00Z,2032,AAA,revenue_tickets,1000,m1\n"
            "2032-04-02T00:00:00Z,2032,BBB,revenue_tickets,2000,m1\n"
            "2032-04-03T00:00:00Z,2032,AAA,expense_payroll,-500,m1\n"
        ),
        encoding="utf-8",
    )

    rows = list_team_financial_transactions("AAA", data_dir=data_dir, limit=10)

    assert len(rows) == 2
    assert rows[0]["timestamp"] == "2032-04-03T00:00:00Z"
    assert rows[0]["amount"] == -500
    assert rows[1]["timestamp"] == "2032-04-01T00:00:00Z"


def test_advanced_revenue_uses_schedule_home_game_volume(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {"wins": 0, "losses": 0, "home_wins": 0, "home_losses": 0},
                "BBB": {"wins": 0, "losses": 0, "home_wins": 0, "home_losses": 0},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    schedule_rows = []
    for day in range(1, 16):
        schedule_rows.append((f"2032-04-{day:02d}", "AAA", "BBB", "", "0"))
    for day in range(1, 16):
        schedule_rows.append((f"2032-05-{day:02d}", "AAA", "BBB", "", "0"))
    for day in range(1, 3):
        schedule_rows.append((f"2032-04-{20 + day:02d}", "BBB", "AAA", "", "0"))
    for day in range(1, 3):
        schedule_rows.append((f"2032-05-{20 + day:02d}", "BBB", "AAA", "", "0"))
    _write_schedule(data_dir / "schedule.csv", schedule_rows)

    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")

    assert snapshots["AAA"].projected_revenue["tickets"] > snapshots["BBB"].projected_revenue["tickets"]
    assert snapshots["AAA"].projected_revenue["concessions"] > snapshots["BBB"].projected_revenue["concessions"]


def test_advanced_revenue_uses_home_record_for_attendance(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {"wins": 10, "losses": 10, "home_wins": 8, "home_losses": 2},
                "BBB": {"wins": 10, "losses": 10, "home_wins": 2, "home_losses": 8},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    schedule_rows = [
        ("2032-04-01", "AAA", "BBB", "", "0"),
        ("2032-04-02", "AAA", "BBB", "", "0"),
        ("2032-04-03", "AAA", "BBB", "", "0"),
        ("2032-05-01", "AAA", "BBB", "", "0"),
        ("2032-05-02", "AAA", "BBB", "", "0"),
        ("2032-05-03", "AAA", "BBB", "", "0"),
        ("2032-04-04", "BBB", "AAA", "", "0"),
        ("2032-04-05", "BBB", "AAA", "", "0"),
        ("2032-04-06", "BBB", "AAA", "", "0"),
        ("2032-05-04", "BBB", "AAA", "", "0"),
        ("2032-05-05", "BBB", "AAA", "", "0"),
        ("2032-05-06", "BBB", "AAA", "", "0"),
    ]
    _write_schedule(data_dir / "schedule.csv", schedule_rows)

    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")

    assert snapshots["AAA"].projected_revenue["tickets"] > snapshots["BBB"].projected_revenue["tickets"]
    assert snapshots["AAA"].projected_revenue["concessions"] > snapshots["BBB"].projected_revenue["concessions"]


def test_advanced_revenue_moves_after_outcome_and_attendance_shift(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {
                    "wins": 10,
                    "losses": 10,
                    "home_wins": 5,
                    "home_losses": 5,
                    "runs_for": 80,
                    "runs_against": 80,
                },
                "BBB": {
                    "wins": 10,
                    "losses": 10,
                    "home_wins": 5,
                    "home_losses": 5,
                    "runs_for": 80,
                    "runs_against": 80,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_schedule(
        data_dir / "schedule.csv",
        [
            ("2032-04-01", "AAA", "BBB", "", "0"),
            ("2032-04-02", "AAA", "BBB", "", "0"),
            ("2032-04-03", "BBB", "AAA", "", "0"),
            ("2032-04-04", "BBB", "AAA", "", "0"),
            ("2032-05-01", "AAA", "BBB", "", "0"),
            ("2032-05-02", "AAA", "BBB", "", "0"),
            ("2032-05-03", "BBB", "AAA", "", "0"),
            ("2032-05-04", "BBB", "AAA", "", "0"),
        ],
    )
    baseline = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")["AAA"]

    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {
                    "wins": 20,
                    "losses": 10,
                    "home_wins": 12,
                    "home_losses": 3,
                    "runs_for": 135,
                    "runs_against": 98,
                },
                "BBB": {
                    "wins": 10,
                    "losses": 20,
                    "home_wins": 3,
                    "home_losses": 12,
                    "runs_for": 98,
                    "runs_against": 135,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_schedule(
        data_dir / "schedule.csv",
        [
            ("2032-04-01", "AAA", "BBB", "", "0"),
            ("2032-04-02", "AAA", "BBB", "", "0"),
            ("2032-04-03", "AAA", "BBB", "", "0"),
            ("2032-04-04", "AAA", "BBB", "", "0"),
            ("2032-04-05", "AAA", "BBB", "", "0"),
            ("2032-04-06", "AAA", "BBB", "", "0"),
            ("2032-04-07", "AAA", "BBB", "", "0"),
            ("2032-04-08", "AAA", "BBB", "", "0"),
            ("2032-04-09", "BBB", "AAA", "", "0"),
            ("2032-04-10", "BBB", "AAA", "", "0"),
            ("2032-05-01", "AAA", "BBB", "", "0"),
            ("2032-05-02", "AAA", "BBB", "", "0"),
            ("2032-05-03", "AAA", "BBB", "", "0"),
            ("2032-05-04", "AAA", "BBB", "", "0"),
            ("2032-05-05", "AAA", "BBB", "", "0"),
            ("2032-05-06", "AAA", "BBB", "", "0"),
            ("2032-05-07", "AAA", "BBB", "", "0"),
            ("2032-05-08", "AAA", "BBB", "", "0"),
            ("2032-05-09", "BBB", "AAA", "", "0"),
            ("2032-05-10", "BBB", "AAA", "", "0"),
        ],
    )
    shifted = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")["AAA"]

    assert shifted.projected_revenue["tickets"] > baseline.projected_revenue["tickets"]
    assert shifted.projected_revenue["concessions"] > baseline.projected_revenue["concessions"]
    assert shifted.projected_revenue["media"] > baseline.projected_revenue["media"]
    assert shifted.projected_revenue["sponsorship"] > baseline.projected_revenue["sponsorship"]


def test_basic_revenue_is_not_affected_by_schedule_volume(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_SIMPLE,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {"wins": 0, "losses": 0, "home_wins": 0, "home_losses": 0},
                "BBB": {"wins": 0, "losses": 0, "home_wins": 0, "home_losses": 0},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_schedule(
        data_dir / "schedule.csv",
        [
            ("2032-04-01", "AAA", "BBB", "", "0"),
            ("2032-04-02", "AAA", "BBB", "", "0"),
            ("2032-04-03", "AAA", "BBB", "", "0"),
            ("2032-04-04", "AAA", "BBB", "", "0"),
            ("2032-04-05", "AAA", "BBB", "", "0"),
            ("2032-04-06", "AAA", "BBB", "", "0"),
            ("2032-04-07", "AAA", "BBB", "", "0"),
            ("2032-05-01", "BBB", "AAA", "", "0"),
        ],
    )
    with_schedule = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")

    (data_dir / "schedule.csv").unlink(missing_ok=True)
    without_schedule = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")

    assert (
        with_schedule["AAA"].projected_revenue["tickets"]
        == without_schedule["AAA"].projected_revenue["tickets"]
    )
    assert (
        with_schedule["AAA"].projected_revenue["concessions"]
        == without_schedule["AAA"].projected_revenue["concessions"]
    )


def test_advanced_revenue_media_and_sponsorship_follow_fan_interest(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    update_financial_settings(
        modules={
            "owner_market_model": "off",
            "owner_revenue": "advanced",
        },
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {
                    "wins": 70,
                    "losses": 40,
                    "home_wins": 40,
                    "home_losses": 15,
                    "runs_for": 560,
                    "runs_against": 430,
                },
                "BBB": {
                    "wins": 40,
                    "losses": 70,
                    "home_wins": 18,
                    "home_losses": 37,
                    "runs_for": 430,
                    "runs_against": 560,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_schedule(
        data_dir / "schedule.csv",
        [
            ("2032-04-01", "AAA", "BBB", "", "0"),
            ("2032-04-02", "AAA", "BBB", "", "0"),
            ("2032-05-01", "AAA", "BBB", "", "0"),
            ("2032-05-02", "AAA", "BBB", "", "0"),
            ("2032-04-03", "BBB", "AAA", "", "0"),
            ("2032-04-04", "BBB", "AAA", "", "0"),
            ("2032-05-03", "BBB", "AAA", "", "0"),
            ("2032-05-04", "BBB", "AAA", "", "0"),
        ],
    )

    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")

    assert snapshots["AAA"].projected_revenue["media"] > snapshots["BBB"].projected_revenue["media"]
    assert (
        snapshots["AAA"].projected_revenue["sponsorship"]
        > snapshots["BBB"].projected_revenue["sponsorship"]
    )


def test_advanced_expenses_operations_follow_away_travel_volume(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    update_financial_settings(
        modules={
            "owner_market_model": "off",
            "owner_expenses": "advanced",
        },
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {"wins": 0, "losses": 0, "home_wins": 0, "home_losses": 0},
                "BBB": {"wins": 0, "losses": 0, "home_wins": 0, "home_losses": 0},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    schedule_rows = []
    for day in range(1, 13):
        schedule_rows.append((f"2032-04-{day:02d}", "BBB", "AAA", "", "0"))
    for day in range(1, 13):
        schedule_rows.append((f"2032-05-{day:02d}", "BBB", "AAA", "", "0"))
    for day in range(1, 3):
        schedule_rows.append((f"2032-04-{20 + day:02d}", "AAA", "BBB", "", "0"))
    for day in range(1, 3):
        schedule_rows.append((f"2032-05-{20 + day:02d}", "AAA", "BBB", "", "0"))
    _write_schedule(data_dir / "schedule.csv", schedule_rows)

    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")

    assert (
        snapshots["AAA"].projected_expenses["operations"]
        > snapshots["BBB"].projected_expenses["operations"]
    )
    assert (
        snapshots["BBB"].projected_expenses["facilities"]
        > snapshots["AAA"].projected_expenses["facilities"]
    )


def test_apply_owner_finance_cadence_for_dates_runs_daily_weekly_and_monthly(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {"wins": 12, "losses": 8, "home_wins": 7, "home_losses": 3, "runs_for": 110, "runs_against": 90},
                "BBB": {"wins": 8, "losses": 12, "home_wins": 3, "home_losses": 7, "runs_for": 90, "runs_against": 110},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_schedule(
        data_dir / "schedule.csv",
        [
            ("2032-04-01", "AAA", "BBB", "", "0"),
            ("2032-04-02", "AAA", "BBB", "", "0"),
            ("2032-04-03", "BBB", "AAA", "", "0"),
            ("2032-04-04", "BBB", "AAA", "", "0"),
        ],
    )

    result = apply_owner_finance_cadence_for_dates(
        ["2032-04-01", "2032-04-02"],
        data_dir=data_dir,
        league_id="alpha",
    )

    assert result["applied_daily_dates"] == ["2032-04-01", "2032-04-02"]
    assert result["applied_weeks"]
    assert result["applied_periods"] == ["2032-04"]
    assert isinstance(result["total_net_change"], int)


def test_monthly_cycle_skips_daily_and_weekly_categories_when_markers_exist(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    update_financial_settings(
        modules={
            "owner_market_model": "off",
            "owner_revenue": "advanced",
            "owner_expenses": "advanced",
        },
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    _write_schedule(
        data_dir / "schedule.csv",
        [
            ("2032-04-01", "AAA", "BBB", "", "0"),
            ("2032-04-02", "AAA", "BBB", "", "0"),
            ("2032-04-03", "BBB", "AAA", "", "0"),
            ("2032-04-04", "BBB", "AAA", "", "0"),
        ],
    )
    append_financial_rows(
        [
            build_finance_cycle_marker_row(season_year=2032, period_key="daily:2032-04-01"),
            build_finance_cycle_marker_row(season_year=2032, period_key="weekly:2032-04:W14"),
        ],
        data_dir=data_dir,
    )

    result = apply_monthly_owner_finance(
        data_dir=data_dir,
        league_id="alpha",
        period_key="2032-04",
    )
    assert result["applied"] is True

    payload = json.loads((data_dir / "team_financials.json").read_text(encoding="utf-8"))
    aaa = payload["teams"]["AAA"]
    assert aaa["revenue"]["tickets"] == 0
    assert aaa["revenue"]["concessions"] == 0
    assert aaa["expenses"]["training"] == 0
    assert aaa["expenses"]["scouting"] == 0
    assert aaa["expenses"]["facilities"] == 0
    assert aaa["revenue"]["media"] > 0
    assert aaa["expenses"]["operations"] > 0


def test_owner_modules_revenue_off_disables_projected_revenue(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    update_financial_settings(
        modules={"owner_revenue": "off"},
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")

    assert snapshots
    for row in snapshots.values():
        assert all(int(v) == 0 for v in row.projected_revenue.values())


def test_owner_modules_expenses_off_keeps_payroll_only_when_enabled(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_SIMPLE,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {"team_id": "AAA", "annual_salary": 1_200_000},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    update_financial_settings(
        modules={"owner_expenses": "off", "gm_contracts": "basic"},
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")
    aaa = snapshots["AAA"].projected_expenses
    assert aaa["payroll"] > 0
    assert aaa["training"] == 0
    assert aaa["scouting"] == 0
    assert aaa["facilities"] == 0
    assert aaa["operations"] == 0


def test_owner_modules_budgets_off_zeroes_targets(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    update_financial_settings(
        modules={"owner_budgets": "off"},
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")
    for row in snapshots.values():
        assert all(int(v) == 0 for v in row.projected_budgets.values())


def test_owner_modules_basic_vs_advanced_budget_split(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_SIMPLE,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    update_financial_settings(
        modules={
            "owner_market_model": "off",
            "owner_revenue": "basic",
            "owner_budgets": "basic",
        },
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    basic = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")
    basic_training = basic["AAA"].projected_budgets["training"]

    update_financial_settings(
        modules={"owner_budgets": "advanced"},
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    advanced = project_monthly_owner_finance(data_dir=data_dir, league_id="alpha")
    advanced_training = advanced["AAA"].projected_budgets["training"]
    assert advanced_training > basic_training


def test_owner_cadence_daily_and_weekly_respect_module_levels(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    _write_schedule(
        data_dir / "schedule.csv",
        [
            ("2032-04-01", "AAA", "BBB", "", "0"),
            ("2032-04-02", "AAA", "BBB", "", "0"),
        ],
    )

    update_financial_settings(
        modules={"owner_revenue": "basic", "owner_expenses": "advanced"},
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    result_basic_revenue = apply_owner_finance_cadence_for_dates(
        ["2032-04-01", "2032-04-02"],
        data_dir=data_dir,
        league_id="alpha",
    )
    assert result_basic_revenue["applied_daily_dates"] == []

    update_financial_settings(
        modules={"owner_revenue": "advanced", "owner_expenses": "basic"},
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    result_basic_expense = apply_owner_finance_cadence_for_dates(
        ["2032-05-01", "2032-05-02"],
        data_dir=data_dir,
        league_id="alpha",
    )
    assert result_basic_expense["applied_weeks"] == []


def test_owner_cadence_is_idempotent_for_same_dates(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    _write_schedule(
        data_dir / "schedule.csv",
        [
            ("2032-04-01", "AAA", "BBB", "", "0"),
            ("2032-04-02", "AAA", "BBB", "", "0"),
            ("2032-04-03", "BBB", "AAA", "", "0"),
            ("2032-04-04", "BBB", "AAA", "", "0"),
        ],
    )
    first = apply_owner_finance_cadence_for_dates(
        ["2032-04-01", "2032-04-02"],
        data_dir=data_dir,
        league_id="alpha",
    )
    second = apply_owner_finance_cadence_for_dates(
        ["2032-04-01", "2032-04-02"],
        data_dir=data_dir,
        league_id="alpha",
    )

    assert first["applied_daily_dates"]
    assert first["applied_weeks"]
    assert first["applied_periods"]
    assert second["applied_daily_dates"] == []
    assert second["applied_weeks"] == []
    assert second["applied_periods"] == []


def test_owner_cadence_ignores_invalid_and_duplicate_dates(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    _write_schedule(
        data_dir / "schedule.csv",
        [
            ("2032-04-01", "AAA", "BBB", "", "0"),
            ("2032-04-02", "AAA", "BBB", "", "0"),
            ("2032-04-03", "BBB", "AAA", "", "0"),
            ("2032-04-04", "BBB", "AAA", "", "0"),
        ],
    )

    result = apply_owner_finance_cadence_for_dates(
        ["2032-04-01", "bad", "2032-04-01", "", "2032-04-02", "2032-13-99"],
        data_dir=data_dir,
        league_id="alpha",
    )

    assert result["dates"] == ["2032-04-01", "2032-04-02"]
    assert result["applied_daily_dates"] == ["2032-04-01", "2032-04-02"]


def test_owner_cadence_writes_daily_weekly_and_monthly_markers_once(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    _write_schedule(
        data_dir / "schedule.csv",
        [
            ("2032-04-01", "AAA", "BBB", "", "0"),
            ("2032-04-02", "AAA", "BBB", "", "0"),
            ("2032-04-03", "BBB", "AAA", "", "0"),
            ("2032-04-04", "BBB", "AAA", "", "0"),
        ],
    )
    apply_owner_finance_cadence_for_dates(
        ["2032-04-01", "2032-04-02"],
        data_dir=data_dir,
        league_id="alpha",
    )
    apply_owner_finance_cadence_for_dates(
        ["2032-04-01", "2032-04-02"],
        data_dir=data_dir,
        league_id="alpha",
    )

    markers = list_financial_rows(
        team_id=LEDGER_TEAM_SYSTEM,
        category=CATEGORY_FINANCE_CYCLE,
        limit=0,
        newest_first=False,
        data_dir=data_dir,
    )
    memos = [str(row.get("memo") or "") for row in markers]
    assert memos.count("daily:2032-04-01") == 1
    assert memos.count("daily:2032-04-02") == 1
    assert any(memo.startswith("weekly:2032-04:") for memo in memos)
    assert memos.count("2032-04") == 1
