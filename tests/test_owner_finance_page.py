from __future__ import annotations


def test_import_owner_finance_page_headless():
    from ui.owner_finance_page import OwnerFinancePage  # noqa: F401

    assert OwnerFinancePage is not None


def test_owner_finance_page_arbitration_candidate_threshold():
    from ui.owner_finance_page import OwnerFinancePage

    assert OwnerFinancePage._is_arbitration_candidate(1, 516)
    assert OwnerFinancePage._is_arbitration_candidate(0, 700)
    assert not OwnerFinancePage._is_arbitration_candidate(2, 700)
    assert not OwnerFinancePage._is_arbitration_candidate(1, 515)


def test_owner_finance_page_level_labels():
    from ui.owner_finance_page import OwnerFinancePage

    assert OwnerFinancePage._fmt_level("basic") == "Basic"
    assert OwnerFinancePage._fmt_level("mlb_like") == "MLB-Like"


def test_owner_finance_page_option_term_detection():
    from ui.owner_finance_page import OwnerFinancePage

    assert OwnerFinancePage._row_has_option_terms({"options_count": 1})
    assert not OwnerFinancePage._row_has_option_terms({"options_count": 0})
    assert not OwnerFinancePage._row_has_option_terms({})
    assert not OwnerFinancePage._row_has_option_terms(None)


def test_owner_finance_page_incentive_term_detection():
    from ui.owner_finance_page import OwnerFinancePage

    assert OwnerFinancePage._row_has_incentive_terms({"incentives_count": 1})
    assert not OwnerFinancePage._row_has_incentive_terms({"incentives_count": 0})
    assert not OwnerFinancePage._row_has_incentive_terms({})
    assert not OwnerFinancePage._row_has_incentive_terms(None)


def test_owner_finance_page_advanced_contract_level_detection():
    from ui.owner_finance_page import OwnerFinancePage

    assert OwnerFinancePage._contracts_advanced_terms_enabled("advanced")
    assert OwnerFinancePage._contracts_advanced_terms_enabled("mlb_like")
    assert not OwnerFinancePage._contracts_advanced_terms_enabled("basic")
    assert not OwnerFinancePage._contracts_advanced_terms_enabled("off")


def test_owner_finance_page_parse_non_negative_currency():
    from ui.owner_finance_page import OwnerFinancePage

    assert OwnerFinancePage._parse_non_negative_currency("12345") == 12345
    assert OwnerFinancePage._parse_non_negative_currency("$12,345") == 12345
    assert OwnerFinancePage._parse_non_negative_currency("-10") == 0
    assert OwnerFinancePage._parse_non_negative_currency("") == 0
    assert OwnerFinancePage._parse_non_negative_currency("bad") is None


def test_owner_finance_page_builds_linear_workflow_guidance():
    from ui.owner_finance_page import OwnerFinancePage

    text = OwnerFinancePage._build_finance_workflow_guidance(
        phase="OFFSEASON",
        can_run_now=True,
        workflow_completed=False,
        requires_commissioner_review=True,
        arbitration_level="advanced",
        free_agency_level="advanced",
        arbitration_candidates=4,
        unsigned_players=25,
        pending_arb=2,
        pending_fa=1,
        approved_arb=0,
        approved_fa=0,
        settings_enabled=True,
    )

    assert "Current phase: OFFSEASON" in text
    assert "Arbitration: 4 candidate(s), pending 2" in text
    assert "Free agency: 25 unsigned player(s), pending 1" in text
    assert "commissioner must review pending finance decisions" in text


def test_owner_finance_page_formats_scouting_controls_summary():
    from ui.owner_finance_page import OwnerFinancePage

    enabled_text = OwnerFinancePage._format_scouting_controls_summary(
        controls={
            "enabled": True,
            "confidence_score": 62,
            "confidence_label": "High",
            "max_rating_error": 3,
            "intensity": "high",
            "credits": 145.5,
            "scouting_multiplier": 1.12,
            "estimated_monthly_income": 168.0,
        },
        uses_budget_model=False,
    )
    assert "Confidence: 62% (High)" in enabled_text
    assert "Estimated Rating Error Band: ±3" in enabled_text
    assert "Intensity: High" in enabled_text
    assert "League baseline progression" in enabled_text

    disabled_text = OwnerFinancePage._format_scouting_controls_summary(
        controls={"enabled": False},
        uses_budget_model=True,
    )
    assert "Fog-of-war disabled" in disabled_text
