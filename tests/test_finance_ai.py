from __future__ import annotations

import json
from types import SimpleNamespace

from services.finance_ai import (
    TeamFinanceStrategy,
    build_cpu_free_agent_bid_book,
    estimate_free_agent_salary_band,
    load_team_finance_strategies,
    recommend_cpu_arbitration_decision,
)
from services.finance_settings import ensure_financial_defaults


def test_load_team_finance_strategies_assigns_profiles_from_context(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    (data_dir / "team_financials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "season_year": 2030,
                "teams": {
                    "AAA": {"cash_on_hand": 12_000_000, "debt": 500_000},
                    "BBB": {"cash_on_hand": 1_000_000, "debt": 7_000_000},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {"wins": 72, "losses": 50},
                "BBB": {"wins": 46, "losses": 76},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    strategies = load_team_finance_strategies(data_dir=data_dir)
    assert strategies["AAA"].profile == "contend"
    assert strategies["BBB"].profile == "rebuild"


def test_load_team_finance_strategies_respects_strategy_profile_overrides(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    (data_dir / "team_financials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "season_year": 2030,
                "teams": {
                    "AAA": {"cash_on_hand": 4_000_000, "debt": 0},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "standings.json").write_text(
        json.dumps({"AAA": {"wins": 81, "losses": 81}}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "team_strategy_profiles.json").write_text(
        json.dumps(
            {
                "version": 1,
                "leagues": {
                    "test": {
                        "default_profile": "power_offense",
                        "teams": {},
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    strategies = load_team_finance_strategies(data_dir=data_dir)

    assert strategies["AAA"].profile == "contend"


def test_load_team_finance_strategies_tracks_multi_year_commitments(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "P1": {
                        "team_id": "AAA",
                        "years_left": 3,
                        "annual_salary": 20_000_000,
                    },
                    "P2": {
                        "team_id": "AAA",
                        "years_left": 2,
                        "annual_salary": 10_000_000,
                    },
                    "P3": {
                        "team_id": "BBB",
                        "years_left": 1,
                        "annual_salary": 9_000_000,
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    strategies = load_team_finance_strategies(data_dir=data_dir)

    assert strategies["AAA"].next_year_commitment == 30_000_000
    assert strategies["AAA"].two_year_commitment == 20_000_000
    assert strategies["BBB"].next_year_commitment == 0
    assert strategies["BBB"].two_year_commitment == 0


def test_recommend_cpu_arbitration_decision_retain_star():
    strategy = TeamFinanceStrategy(
        team_id="AAA",
        profile="contend",
        budget_tone="aggressive",
        win_pct=0.600,
        cash_on_hand=10_000_000,
        debt=0,
        projected_net=150_000,
        annual_payroll=120_000_000,
    )
    result = recommend_cpu_arbitration_decision(
        ai_level="advanced",
        team_strategy=strategy,
        base_bump=0.12,
        current_salary=14_000_000,
        salary_share=0.16,
        talent_score=82,
        performance_score=80,
    )
    assert result.non_tender is False
    assert result.decision_code == "cpu_retain_star"
    assert result.applied_bump > 0.12


def test_recommend_cpu_arbitration_decision_non_tender_high_cost_underperformer():
    strategy = TeamFinanceStrategy(
        team_id="BBB",
        profile="rebuild",
        budget_tone="cautious",
        win_pct=0.390,
        cash_on_hand=500_000,
        debt=8_500_000,
        projected_net=-400_000,
        annual_payroll=90_000_000,
    )
    result = recommend_cpu_arbitration_decision(
        ai_level="advanced",
        team_strategy=strategy,
        base_bump=0.12,
        current_salary=25_000_000,
        salary_share=0.31,
        talent_score=54,
        performance_score=36,
    )
    assert result.non_tender is True
    assert result.decision_code == "cpu_non_tender_high_cost_underperformer"
    assert result.applied_bump == 0.0


def test_recommend_cpu_arbitration_decision_differs_by_strategy_profile():
    contend = TeamFinanceStrategy(
        team_id="AAA",
        profile="contend",
        budget_tone="neutral",
        win_pct=0.600,
        cash_on_hand=8_000_000,
        debt=0,
        projected_net=120_000,
        annual_payroll=180_000_000,
    )
    rebuild = TeamFinanceStrategy(
        team_id="BBB",
        profile="rebuild",
        budget_tone="cautious",
        win_pct=0.380,
        cash_on_hand=500_000,
        debt=6_000_000,
        projected_net=-280_000,
        annual_payroll=150_000_000,
    )
    common = dict(
        ai_level="advanced",
        base_bump=0.12,
        current_salary=18_000_000,
        salary_share=0.22,
        talent_score=64,
        performance_score=40,
    )
    contend_result = recommend_cpu_arbitration_decision(
        team_strategy=contend,
        **common,
    )
    rebuild_result = recommend_cpu_arbitration_decision(
        team_strategy=rebuild,
        **common,
    )

    assert contend_result.non_tender is False
    assert rebuild_result.applied_bump <= contend_result.applied_bump
    assert rebuild_result.decision_code in {
        "cpu_hold_salary_underperformer",
        "cpu_non_tender_high_cost_underperformer",
    }


def test_recommend_cpu_arbitration_decision_respects_tuning_thresholds():
    strategy = TeamFinanceStrategy(
        team_id="AAA",
        profile="contend",
        budget_tone="neutral",
        win_pct=0.580,
        cash_on_hand=7_000_000,
        debt=0,
        projected_net=90_000,
        annual_payroll=118_000_000,
    )
    result = recommend_cpu_arbitration_decision(
        ai_level="advanced",
        team_strategy=strategy,
        base_bump=0.12,
        current_salary=15_000_000,
        salary_share=0.20,
        talent_score=80,
        performance_score=79,
        tuning={
            "star_talent_threshold": 90,
            "star_performance_threshold": 90,
            "max_raise_pct": 0.10,
        },
    )
    assert result.decision_code != "cpu_retain_star"
    assert result.applied_bump <= 0.10


def test_estimate_free_agent_salary_band_reflects_profile_and_budget_tone():
    strategy = TeamFinanceStrategy(
        team_id="BBB",
        profile="rebuild",
        budget_tone="cautious",
        win_pct=0.430,
        cash_on_hand=700_000,
        debt=4_500_000,
        projected_net=-240_000,
        annual_payroll=96_000_000,
    )
    low, high = estimate_free_agent_salary_band(strategy, ai_level="advanced")
    assert low <= high
    assert low <= 0.60
    assert high <= 1.0


class _MaxRng:
    @staticmethod
    def randint(low: int, high: int) -> int:
        return high


def test_build_cpu_free_agent_bid_book_uses_profiles_and_skips_human_teams(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    (data_dir / "league_financial_settings.json").write_text(
        json.dumps(
            {
                "version": 1,
                "leagues": {
                    "test": {
                        "enabled": True,
                        "preset": "standard",
                        "enforcement_mode": "warn",
                        "modules": {
                            "owner_revenue": "advanced",
                            "owner_market_model": "basic",
                            "owner_budgets": "advanced",
                            "owner_expenses": "advanced",
                            "gm_contracts": "advanced",
                            "gm_payroll_rules": "basic",
                            "gm_arbitration": "basic",
                            "gm_free_agency": "advanced",
                            "gm_roster_cost_enforcement": "warn",
                            "gm_finance_ai": "advanced",
                        },
                    }
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
                "season_year": 2030,
                "teams": {
                    "AAA": {"cash_on_hand": 20_000_000, "debt": 0},
                    "BBB": {"cash_on_hand": 1_000_000, "debt": 7_500_000},
                    "CCC": {"cash_on_hand": 8_000_000, "debt": 0},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "standings.json").write_text(
        json.dumps(
            {
                "AAA": {"wins": 84, "losses": 58},
                "BBB": {"wins": 54, "losses": 88},
                "CCC": {"wins": 74, "losses": 68},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    teams = [
        SimpleNamespace(team_id="AAA", owner_id="cpu"),
        SimpleNamespace(team_id="BBB", owner_id="cpu"),
        SimpleNamespace(team_id="CCC", owner_id="owner_jane"),
    ]
    player = SimpleNamespace(
        player_id="P9",
        is_pitcher=False,
        primary_position="1B",
        ch=66,
        ph=63,
        sp=52,
        eye=58,
        fa=55,
        arm=56,
    )

    bids = build_cpu_free_agent_bid_book(
        player,
        teams,
        ai_level="advanced",
        data_dir=data_dir,
        rng=_MaxRng(),
    )

    assert "AAA" in bids
    assert "BBB" in bids
    assert "CCC" not in bids
    assert bids["AAA"] > bids["BBB"]


def test_build_cpu_free_agent_bid_book_respects_commitment_tuning_limits(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    (data_dir / "league_financial_settings.json").write_text(
        json.dumps(
            {
                "version": 1,
                "leagues": {
                    "test": {
                        "enabled": True,
                        "preset": "custom",
                        "enforcement_mode": "warn",
                        "modules": {
                            "owner_revenue": "advanced",
                            "owner_market_model": "basic",
                            "owner_budgets": "advanced",
                            "owner_expenses": "advanced",
                            "gm_contracts": "advanced",
                            "gm_payroll_rules": "basic",
                            "gm_arbitration": "basic",
                            "gm_free_agency": "advanced",
                            "gm_roster_cost_enforcement": "warn",
                            "gm_finance_ai": "advanced",
                        },
                        "finance_ai_tuning": {
                            "future_year_commitment_ratio_limit": 0.70,
                            "future_year_hard_commitment_ratio_limit": 0.75,
                            "commitment_pressure_ratio": 0.90,
                            "commitment_relief_ratio": 0.60,
                            "commitment_pressure_penalty": 25_000_000,
                            "commitment_relief_bonus": 5_000_000,
                        },
                    }
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
                "season_year": 2030,
                "teams": {
                    "AAA": {"cash_on_hand": 3_000_000, "debt": 0},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "standings.json").write_text(
        json.dumps({"AAA": {"wins": 96, "losses": 66}}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "players": {
                    "C1": {"team_id": "AAA", "years_left": 4, "annual_salary": 80_000_000},
                    "C2": {"team_id": "AAA", "years_left": 3, "annual_salary": 70_000_000},
                    "C3": {"team_id": "AAA", "years_left": 2, "annual_salary": 60_000_000},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    teams = [SimpleNamespace(team_id="AAA", owner_id="cpu")]
    player = SimpleNamespace(
        player_id="P9",
        is_pitcher=False,
        primary_position="1B",
        ch=90,
        ph=88,
        sp=78,
        eye=85,
        fa=82,
        arm=80,
    )

    blocked_bids = build_cpu_free_agent_bid_book(
        player,
        teams,
        ai_level="advanced",
        data_dir=data_dir,
        rng=_MaxRng(),
    )
    assert blocked_bids == {}

    payload = json.loads((data_dir / "league_financial_settings.json").read_text(encoding="utf-8"))
    payload["leagues"]["test"]["finance_ai_tuning"]["future_year_commitment_ratio_limit"] = 2.0
    payload["leagues"]["test"]["finance_ai_tuning"]["future_year_hard_commitment_ratio_limit"] = 2.0
    payload["leagues"]["test"]["finance_ai_tuning"]["commitment_pressure_penalty"] = 0
    (data_dir / "league_financial_settings.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    relaxed_bids = build_cpu_free_agent_bid_book(
        player,
        teams,
        ai_level="advanced",
        data_dir=data_dir,
        rng=_MaxRng(),
    )
    assert "AAA" in relaxed_bids
