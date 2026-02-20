from __future__ import annotations

from types import SimpleNamespace

import services.finance_reporting as finance_reporting


def test_build_commissioner_projection_report_summarizes_and_sorts(monkeypatch):
    monkeypatch.setattr(
        finance_reporting,
        "load_financial_settings",
        lambda **_: SimpleNamespace(
            league_id="alpha",
            enabled=True,
            preset="standard",
            enforcement_mode="warn",
            modules={
                "gm_arbitration": "advanced",
                "gm_free_agency": "advanced",
            },
        ),
    )
    monkeypatch.setattr(
        finance_reporting,
        "project_monthly_owner_finance",
        lambda **_: {
            "AAA": SimpleNamespace(
                cash_on_hand=1_000_000,
                debt=5_000_000,
                projected_net=-100_000,
            ),
            "BBB": SimpleNamespace(
                cash_on_hand=9_000_000,
                debt=0,
                projected_net=250_000,
            ),
        },
    )
    monkeypatch.setattr(
        finance_reporting,
        "calculate_annual_payroll_totals",
        lambda **_: {"AAA": 120_000_000, "BBB": 80_000_000},
    )
    monkeypatch.setattr(
        finance_reporting,
        "build_payroll_limit_context",
        lambda **_: {
            "level": "basic",
            "teams": {
                "AAA": {
                    "threshold": 100_000_000,
                    "floor": 0,
                    "over_threshold": 20_000_000,
                    "under_floor": 0,
                    "threshold_ratio": 1.20,
                    "floor_ratio": 0.0,
                },
                "BBB": {
                    "threshold": 95_000_000,
                    "floor": 0,
                    "over_threshold": 0,
                    "under_floor": 0,
                    "threshold_ratio": 0.84,
                    "floor_ratio": 0.0,
                },
            },
        },
    )
    monkeypatch.setattr(
        finance_reporting,
        "collect_offseason_finance_overview",
        lambda **_: {
            "phase": "OFFSEASON",
            "can_run_now": True,
            "requires_commissioner_finance_review": True,
            "gm_queue_pending": 1,
            "gm_queue_approved_unapplied": 2,
            "arbitration_candidates": 3,
            "unsigned_players": 41,
        },
    )
    monkeypatch.setattr(
        finance_reporting,
        "get_offseason_checklist",
        lambda **_: {
            "next_stage_id": "contracts_review",
            "stages": [
                {
                    "id": "contracts_review",
                    "label": "Review Contract Expirations",
                }
            ],
        },
    )

    report = finance_reporting.build_commissioner_projection_report()

    assert report["league_id"] == "alpha"
    assert report["summary"]["team_count"] == 2
    assert report["summary"]["teams_negative_net"] == 1
    assert report["summary"]["teams_over_threshold"] == 1
    assert report["top_surplus_teams"][0]["team_id"] == "BBB"
    assert report["top_deficit_teams"][0]["team_id"] == "AAA"
    assert report["offseason"]["next_stage_label"] == "Review Contract Expirations"


def test_build_finance_alerts_includes_actionable_items():
    report = {
        "modules": {
            "gm_arbitration": "advanced",
            "gm_free_agency": "advanced",
        },
        "payroll_rule_level": "mlb_like",
        "teams": [
            {
                "team_id": "AAA",
                "cash_on_hand": 1_000_000,
                "debt": 40_000_000,
                "projected_net": -250_000,
                "over_threshold": 4_500_000,
                "under_floor": 0,
                "threshold_ratio": 1.03,
                "floor_ratio": 1.00,
            }
        ],
        "offseason": {
            "can_run_now": True,
            "requires_commissioner_finance_review": True,
            "gm_queue_pending": 2,
            "gm_queue_approved_unapplied": 1,
            "arbitration_candidates": 4,
            "unsigned_players": 22,
            "next_stage_id": "contracts_review",
            "next_stage_label": "Review Contract Expirations",
        },
    }

    alerts = finance_reporting.build_finance_alerts(report=report, limit=12)
    titles = {str(row.get("title") or "") for row in alerts}

    assert "AAA: Cashflow Risk" in titles
    assert "AAA: Payroll Over Threshold" in titles
    assert "Offseason Checklist Pending" in titles
    assert "GM Finance Queue Needs Review" in titles
    assert "Arbitration Deadline Window" in titles
    assert "Free-Agency Market Active" in titles
    assert all(str(row.get("next_step") or "").strip() for row in alerts)


def test_build_finance_alerts_returns_no_issue_info_when_clean():
    alerts = finance_reporting.build_finance_alerts(
        report={
            "modules": {
                "gm_arbitration": "off",
                "gm_free_agency": "off",
            },
            "payroll_rule_level": "off",
            "teams": [
                {
                    "team_id": "AAA",
                    "cash_on_hand": 8_000_000,
                    "debt": 0,
                    "projected_net": 200_000,
                    "over_threshold": 0,
                    "under_floor": 0,
                    "threshold_ratio": 0.50,
                    "floor_ratio": 0.0,
                }
            ],
            "offseason": {
                "can_run_now": False,
                "requires_commissioner_finance_review": False,
                "gm_queue_pending": 0,
                "gm_queue_approved_unapplied": 0,
                "arbitration_candidates": 0,
                "unsigned_players": 0,
                "next_stage_id": "",
                "next_stage_label": "None",
            },
        },
        limit=5,
    )

    assert len(alerts) == 1
    assert alerts[0]["title"] == "No Immediate Finance Alerts"
