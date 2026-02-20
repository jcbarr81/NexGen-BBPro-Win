from __future__ import annotations

from services.finance_ledger import (
    CATEGORY_ARB_AWARD,
    CATEGORY_CONTRACT_BUYOUT,
    CATEGORY_FINANCE_CYCLE,
    CATEGORY_PAYROLL_POLICY,
    LEDGER_TEAM_SYSTEM,
    append_financial_rows,
    build_team_expense_row,
    build_team_revenue_row,
    ledger_has_entry,
    list_financial_rows,
    post_arb_award,
    post_contract_buyout,
    post_payroll_policy_event,
    post_team_expense,
    post_team_revenue,
    post_finance_cycle_marker,
)


def test_append_and_list_financial_rows_latest_first(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    append_financial_rows(
        [
            ("2032-04-01T00:00:00Z", 2032, "AAA", "revenue_tickets", 1000, "m1"),
            ("2032-04-02T00:00:00Z", 2032, "BBB", "revenue_tickets", 2000, "m1"),
            ("2032-04-03T00:00:00Z", 2032, "AAA", "expense_payroll", -500, "m1"),
        ],
        data_dir=data_dir,
    )

    rows = list_financial_rows(team_id="AAA", data_dir=data_dir, limit=10)

    assert len(rows) == 2
    assert rows[0]["timestamp"] == "2032-04-03T00:00:00Z"
    assert rows[0]["amount"] == -500
    assert rows[1]["timestamp"] == "2032-04-01T00:00:00Z"


def test_ledger_has_entry_filters_by_team_category_and_memo(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    append_financial_rows(
        [
            (
                "2032-04-15T00:00:00Z",
                2032,
                "__system__",
                "finance_cycle",
                0,
                "2032-04",
            )
        ],
        data_dir=data_dir,
    )

    assert ledger_has_entry(
        team_id="__system__",
        category="finance_cycle",
        memo="2032-04",
        data_dir=data_dir,
    )
    assert not ledger_has_entry(
        team_id="__system__",
        category="finance_cycle",
        memo="2032-05",
        data_dir=data_dir,
    )


def test_append_financial_rows_accepts_mapping_payloads(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    written = append_financial_rows(
        [
            {
                "timestamp": "2032-04-01T00:00:00Z",
                "season_year": 2032,
                "team_id": "AAA",
                "category": "contract_buyout",
                "amount": -250000,
                "memo": "Option buyout",
            }
        ],
        data_dir=data_dir,
    )

    rows = list_financial_rows(data_dir=data_dir, limit=5)
    assert written == 1
    assert len(rows) == 1
    assert rows[0]["category"] == "contract_buyout"
    assert rows[0]["amount"] == -250000


def test_post_finance_cycle_marker_uses_system_category(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    posted = post_finance_cycle_marker(
        season_year=2032,
        period_key="2032-04",
        timestamp="2032-04-30T00:00:00Z",
        data_dir=data_dir,
    )

    assert posted
    assert ledger_has_entry(
        team_id=LEDGER_TEAM_SYSTEM,
        category=CATEGORY_FINANCE_CYCLE,
        memo="2032-04",
        data_dir=data_dir,
    )


def test_post_contract_buyout_writes_negative_expense(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    posted = post_contract_buyout(
        team_id="AAA",
        season_year=2033,
        player_id="P100",
        buyout_amount=450000,
        detail="Option buyout (team)",
        timestamp="2033-10-01T00:00:00Z",
        data_dir=data_dir,
    )

    assert posted
    rows = list_financial_rows(team_id="AAA", data_dir=data_dir, limit=5)
    assert len(rows) == 1
    assert rows[0]["category"] == CATEGORY_CONTRACT_BUYOUT
    assert rows[0]["amount"] == -450000
    assert rows[0]["memo"] == "Option buyout (team): P100"


def test_post_arb_award_writes_negative_expense(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    posted = post_arb_award(
        team_id="AAA",
        season_year=2034,
        salary_delta=2250000,
        memo="Offseason arbitration awards (2034)",
        timestamp="2034-10-01T00:00:00Z",
        data_dir=data_dir,
    )

    assert posted
    rows = list_financial_rows(team_id="AAA", data_dir=data_dir, limit=5)
    assert len(rows) == 1
    assert rows[0]["category"] == CATEGORY_ARB_AWARD
    assert rows[0]["amount"] == -2250000


def test_build_team_revenue_and_expense_rows_normalize_categories():
    revenue_row = build_team_revenue_row(
        team_id="AAA",
        season_year=2032,
        revenue_type="Ticket Sales",
        amount=1500,
        memo="2032-04",
        timestamp="2032-04-01T00:00:00Z",
    )
    expense_row = build_team_expense_row(
        team_id="AAA",
        season_year=2032,
        expense_type="Player Payroll",
        amount=2500,
        memo="2032-04",
        timestamp="2032-04-01T00:00:00Z",
    )

    assert revenue_row is not None
    assert revenue_row[3] == "revenue_ticket_sales"
    assert revenue_row[4] == 1500
    assert expense_row is not None
    assert expense_row[3] == "expense_player_payroll"
    assert expense_row[4] == -2500


def test_post_team_revenue_and_expense_write_rows(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    posted_revenue = post_team_revenue(
        team_id="AAA",
        season_year=2032,
        revenue_type="tickets",
        amount=1000,
        memo="2032-04",
        timestamp="2032-04-01T00:00:00Z",
        data_dir=data_dir,
    )
    posted_expense = post_team_expense(
        team_id="AAA",
        season_year=2032,
        expense_type="payroll",
        amount=500,
        memo="2032-04",
        timestamp="2032-04-01T00:00:01Z",
        data_dir=data_dir,
    )

    assert posted_revenue
    assert posted_expense
    rows = list_financial_rows(team_id="AAA", data_dir=data_dir, limit=10)
    assert len(rows) == 2
    assert rows[0]["category"] == "expense_payroll"
    assert rows[0]["amount"] == -500
    assert rows[1]["category"] == "revenue_tickets"
    assert rows[1]["amount"] == 1000


def test_post_payroll_policy_event_writes_audit_row(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    posted = post_payroll_policy_event(
        team_id="AAA",
        season_year=2036,
        action="owner_trade_accept",
        outcome="warning",
        kind="max",
        projected=205_000_000,
        threshold=180_000_000,
        delta=8_000_000,
        over=25_000_000,
        estimated_tax=3_000_000,
        timestamp="2036-07-01T00:00:00Z",
        data_dir=data_dir,
    )

    assert posted
    rows = list_financial_rows(team_id="AAA", data_dir=data_dir, limit=5)
    assert len(rows) == 1
    assert rows[0]["category"] == CATEGORY_PAYROLL_POLICY
    assert rows[0]["amount"] == 0
    assert "action=owner_trade_accept" in rows[0]["memo"]
    assert "estimated_tax=3000000" in rows[0]["memo"]
