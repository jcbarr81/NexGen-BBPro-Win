from __future__ import annotations

import json
from types import SimpleNamespace

from services.finance_settings import (
    PRESET_SIMPLE,
    apply_financial_preset,
    ensure_financial_defaults,
    update_financial_settings,
)
from services.finance_ledger import CATEGORY_PAYROLL_POLICY, list_financial_rows
from services.payroll_policy import (
    apply_payroll_rule_accounting_effects,
    build_payroll_limit_context,
    estimate_mlb_like_cbt_tax,
    evaluate_free_agent_signing,
    evaluate_opening_day_payroll,
    evaluate_payroll_delta,
    evaluate_trade_payroll_impact,
    format_payroll_policy_message,
    record_payroll_policy_result,
)


def _setup_finance_policy(data_dir, *, enforcement: str = "on", payroll_rules: str = "basic"):
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_SIMPLE,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    update_financial_settings(
        league_id="alpha",
        path=data_dir / "league_financial_settings.json",
        modules={
            "gm_roster_cost_enforcement": enforcement,
            "gm_payroll_rules": payroll_rules,
        },
    )


def _write_teams(path):
    path.write_text(
        (
            "team_id,name,city,abbreviation,division,stadium,primary_color,"
            "secondary_color,owner_id\n"
            "AAA,Alphas,Alpha,AAA,East,Alpha Park,#111111,#222222,\n"
            "BBB,Bears,Beta,BBB,East,Beta Park,#111111,#222222,\n"
        ),
        encoding="utf-8",
    )


def test_free_agent_signing_over_threshold_allowed_in_season(tmp_path):
    # Hybrid model: over the luxury threshold is allowed during the season (it's
    # taxed at settlement), not blocked. The violation is still reported so the
    # UI/notifications can surface it.
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="on", payroll_rules="basic")

    result = evaluate_free_agent_signing(
        "AAA",
        annual_salary=200_000_000,
        data_dir=data_dir,
        league_id="alpha",
    )

    assert result.allowed is True
    assert result.warning is False
    assert result.mode == "on"
    assert "AAA" in result.violations
    assert result.violations["AAA"]["projected"] > result.violations["AAA"]["threshold"]


def test_legacy_warn_block_normalize_to_on(tmp_path):
    # Old configs using warn/block should keep enforcement enabled (= "on"),
    # not silently fall back to off.
    for legacy in ("warn", "block"):
        data_dir = tmp_path / f"league-{legacy}"
        data_dir.mkdir(parents=True, exist_ok=True)
        _write_teams(data_dir / "teams.csv")
        _setup_finance_policy(data_dir, enforcement=legacy, payroll_rules="basic")

        result = evaluate_free_agent_signing(
            "AAA",
            annual_salary=200_000_000,
            data_dir=data_dir,
            league_id="alpha",
        )

        assert result.mode == "on"
        assert "AAA" in result.violations  # enforcement is active


def test_payroll_policy_skips_when_rules_are_off(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="block", payroll_rules="off")

    result = evaluate_free_agent_signing(
        "AAA",
        annual_salary=300_000_000,
        data_dir=data_dir,
        league_id="alpha",
    )

    assert result.allowed is True
    assert result.warning is False
    assert result.violations == {}


def test_trade_payroll_policy_blocks_over_limit_delta(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="block", payroll_rules="basic")
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {"team_id": "AAA", "annual_salary": 5_000_000, "years_left": 1},
                    "P2": {"team_id": "BBB", "annual_salary": 150_000_000, "years_left": 1},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    trade = SimpleNamespace(
        from_team="AAA",
        to_team="BBB",
        give_player_ids=["P1"],
        receive_player_ids=["P2"],
    )

    result = evaluate_trade_payroll_impact(
        trade,
        data_dir=data_dir,
        league_id="alpha",
    )

    # In-season trades are allowed (taxed), not blocked — the violation is
    # reported for the UI/notifications.
    assert result.allowed is True
    assert "AAA" in result.violations


def test_mlb_like_policy_reports_estimated_cbt_tax(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="on", payroll_rules="mlb_like")

    result = evaluate_free_agent_signing(
        "AAA",
        annual_salary=300_000_000,
        data_dir=data_dir,
        league_id="alpha",
    )

    assert result.allowed is True
    assert result.warning is False
    assert "AAA" in result.violations
    tax = int(result.violations["AAA"].get("estimated_tax", 0) or 0)
    assert tax > 0
    text = format_payroll_policy_message(result)
    assert "est. CBT tax" in text


def test_mlb_like_floor_blocks_payroll_dump_trade(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="block", payroll_rules="mlb_like")
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "A1": {"team_id": "AAA", "annual_salary": 30_000_000, "years_left": 1},
                    "A2": {"team_id": "AAA", "annual_salary": 30_000_000, "years_left": 1},
                    "A3": {"team_id": "AAA", "annual_salary": 35_000_000, "years_left": 1},
                    "B1": {"team_id": "BBB", "annual_salary": 1_000_000, "years_left": 1},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    trade = SimpleNamespace(
        from_team="AAA",
        to_team="BBB",
        give_player_ids=["A3"],
        receive_player_ids=["B1"],
    )

    result = evaluate_trade_payroll_impact(
        trade,
        data_dir=data_dir,
        league_id="alpha",
    )

    # Floor (under-spend) is economic — a floor fee applies, the move isn't blocked.
    assert result.allowed is True
    assert "AAA" in result.violations
    assert result.violations["AAA"]["kind"] == "min"
    message = format_payroll_policy_message(result)
    assert "under by" in message


def test_mlb_like_trade_can_report_mixed_max_and_min_violations(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="block", payroll_rules="mlb_like")
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "A_LOW": {"team_id": "AAA", "annual_salary": 1_000_000, "years_left": 1},
                    "A_BIG": {"team_id": "AAA", "annual_salary": 200_000_000, "years_left": 1},
                    "B_HIGH": {"team_id": "BBB", "annual_salary": 50_000_000, "years_left": 1},
                    "B_BASE": {"team_id": "BBB", "annual_salary": 50_000_000, "years_left": 1},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    trade = SimpleNamespace(
        from_team="AAA",
        to_team="BBB",
        give_player_ids=["A_LOW"],
        receive_player_ids=["B_HIGH"],
    )

    result = evaluate_trade_payroll_impact(
        trade,
        data_dir=data_dir,
        league_id="alpha",
    )

    # Both sides report violations (max one side, min the other); in-season
    # neither blocks — they settle as tax / floor fee.
    assert result.allowed is True
    assert result.violations["AAA"]["kind"] == "max"
    assert result.violations["BBB"]["kind"] == "min"


def test_insolvency_blocks_only_at_opening_day_deadline(tmp_path):
    # A team over its debt cap is allowed to keep operating in-season, but the
    # hard Opening-Day check (evaluate_opening_day_payroll) blocks it.
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="on", payroll_rules="basic")
    (data_dir / "team_financials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "season_year": 2032,
                "teams": {
                    "AAA": {
                        "cash_on_hand": 0,
                        "debt": 85_000_000,
                        "revenue": {},
                        "expenses": {},
                        "budgets": {},
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # In-season: an over-debt move is NOT blocked (settles economically).
    in_season = evaluate_free_agent_signing(
        "AAA",
        annual_salary=18_000_000,
        data_dir=data_dir,
        league_id="alpha",
    )
    assert in_season.allowed is True
    assert in_season.violations["AAA"]["kind"] == "debt"

    # Opening Day deadline: insolvency is a hard block.
    opening = evaluate_opening_day_payroll("AAA", data_dir=data_dir, league_id="alpha")
    assert opening.allowed is False
    assert opening.violations["AAA"]["kind"] == "debt"
    message = format_payroll_policy_message(opening)
    assert "projected debt" in message.lower()


def test_estimate_mlb_like_cbt_tax_tiers():
    assert estimate_mlb_like_cbt_tax(250_000_000, 240_000_000) == 2_000_000
    assert estimate_mlb_like_cbt_tax(300_000_000, 240_000_000) > 0


def test_record_payroll_policy_result_writes_over_limit_rows(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="on", payroll_rules="basic")

    result = evaluate_free_agent_signing(
        "AAA",
        annual_salary=250_000_000,
        data_dir=data_dir,
        league_id="alpha",
    )
    written = record_payroll_policy_result(
        result,
        action="owner_sign_free_agent",
        data_dir=data_dir,
        season_year=2032,
    )

    assert result.allowed is True
    assert result.warning is False
    assert written >= 1
    rows = list_financial_rows(
        team_id="AAA",
        category=CATEGORY_PAYROLL_POLICY,
        data_dir=data_dir,
        limit=5,
    )
    assert len(rows) >= 1
    assert "outcome=over_limit" in rows[0]["memo"]


def test_apply_payroll_rule_accounting_effects_posts_tax_and_floor_fee(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="block", payroll_rules="mlb_like")
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {"team_id": "AAA", "annual_salary": 250_000_000, "years_left": 2},
                    "P2": {"team_id": "BBB", "annual_salary": 20_000_000, "years_left": 2},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "team_financials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "season_year": 2032,
                "teams": {
                    "AAA": {
                        "cash_on_hand": 50_000_000,
                        "debt": 0,
                        "revenue": {},
                        "expenses": {"payroll": 0},
                        "budgets": {},
                    },
                    "BBB": {
                        "cash_on_hand": 50_000_000,
                        "debt": 0,
                        "revenue": {},
                        "expenses": {"payroll": 0},
                        "budgets": {},
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = apply_payroll_rule_accounting_effects(
        data_dir=data_dir,
        league_id="alpha",
        season_year=2032,
    )

    assert summary["applied"] is True
    assert summary["teams_penalized"] == 2
    assert summary["tax_total"] > 0
    assert summary["floor_fee_total"] > 0

    rows = list_financial_rows(
        team_id="AAA",
        data_dir=data_dir,
        limit=50,
    )
    categories = {str(row.get("category") or "") for row in rows}
    assert "expense_payroll_tax" in categories
    rows_bbb = list_financial_rows(
        team_id="BBB",
        data_dir=data_dir,
        limit=50,
    )
    categories_bbb = {str(row.get("category") or "") for row in rows_bbb}
    assert "expense_payroll_floor_fee" in categories_bbb

    payload = json.loads((data_dir / "team_financials.json").read_text(encoding="utf-8"))
    assert payload["teams"]["AAA"]["cash_on_hand"] < 50_000_000
    assert payload["teams"]["BBB"]["cash_on_hand"] < 50_000_000


def test_apply_payroll_rule_accounting_effects_is_idempotent(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="block", payroll_rules="basic")
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {"team_id": "AAA", "annual_salary": 200_000_000, "years_left": 2},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "team_financials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "season_year": 2032,
                "teams": {
                    "AAA": {
                        "cash_on_hand": 25_000_000,
                        "debt": 0,
                        "revenue": {},
                        "expenses": {"payroll": 0},
                        "budgets": {},
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    first = apply_payroll_rule_accounting_effects(
        data_dir=data_dir,
        league_id="alpha",
        season_year=2032,
    )
    second = apply_payroll_rule_accounting_effects(
        data_dir=data_dir,
        league_id="alpha",
        season_year=2032,
    )

    assert first["teams_penalized"] == 1
    assert second["teams_penalized"] == 0
    rows = list_financial_rows(
        team_id="AAA",
        category="expense_payroll_overage_fee",
        data_dir=data_dir,
        limit=50,
    )
    assert len(rows) == 1


def test_evaluate_payroll_delta_uses_overrides_for_sequential_checks(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="block", payroll_rules="basic")

    first = evaluate_payroll_delta(
        "AAA",
        annual_delta=80_000_000,
        data_dir=data_dir,
        league_id="alpha",
        annual_totals={"AAA": 60_000_000},
        monthly_projection={"AAA": None},
    )
    second = evaluate_payroll_delta(
        "AAA",
        annual_delta=80_000_000,
        data_dir=data_dir,
        league_id="alpha",
        annual_totals={"AAA": 140_000_000},
        monthly_projection={"AAA": None},
    )

    # In-season both are allowed (over-threshold settles via tax); the override
    # totals just change the projected payroll the violation reports.
    assert first.allowed is True
    assert second.allowed is True
    assert first.violations["AAA"]["projected"] < second.violations["AAA"]["projected"]


def test_build_payroll_limit_context_includes_threshold_ratios(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    _setup_finance_policy(data_dir, enforcement="warn", payroll_rules="basic")
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {"team_id": "AAA", "annual_salary": 90_000_000, "years_left": 2},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    context = build_payroll_limit_context(data_dir=data_dir, league_id="alpha")
    teams = context.get("teams")
    assert context["level"] == "basic"
    assert isinstance(teams, dict)
    assert "AAA" in teams
    assert int(teams["AAA"]["threshold"]) > 0
    assert float(teams["AAA"]["threshold_ratio"]) > 0.0
