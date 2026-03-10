from __future__ import annotations

import importlib

import pytest

from services.team_strategy_profiles import save_team_strategy_settings


@pytest.fixture()
def prospect_rules_module(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))

    import utils.path_utils as path_utils

    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None

    import services.prospect_rules as prospect_rules

    importlib.reload(prospect_rules)
    return prospect_rules


def test_defaults_disabled(prospect_rules_module):
    settings = prospect_rules_module.load_prospect_rules()
    assert settings.enabled is False
    decision = prospect_rules_module.evaluate_roster_move(
        "AAA",
        "P1",
        from_level="aaa",
        to_level="act",
    )
    assert decision.allowed is True


def test_protection_required_blocks_unprotected_promotions(prospect_rules_module):
    prospect_rules_module.update_prospect_rules(enabled=True, auto_protect_on_promotion=False)

    decision = prospect_rules_module.evaluate_roster_move(
        "AAA",
        "P1",
        from_level="aaa",
        to_level="act",
    )
    assert decision.allowed is False
    assert "not protected" in decision.reason.lower()
    assert decision.reason_tag == "protection_required"
    payload = decision.decision_explanation
    assert payload.get("decision_type") == "prospect_roster_move"
    assert payload.get("outcome") == "blocked"
    tags = {entry.get("tag") for entry in payload.get("reasons", [])}
    assert "protection_required" in tags
    assert payload.get("context", {}).get("to_level") == "act"


def test_auto_protect_allows_and_persists(prospect_rules_module):
    prospect_rules_module.update_prospect_rules(enabled=True, auto_protect_on_promotion=True)
    decision = prospect_rules_module.evaluate_roster_move(
        "AAA",
        "P1",
        from_level="low",
        to_level="act",
    )
    assert decision.allowed is True
    assert decision.requires_auto_protect is True
    assert decision.reason_tag == "league_auto_protect"
    assert decision.decision_explanation.get("outcome") == "allowed"

    prospect_rules_module.apply_roster_move(
        "AAA",
        "P1",
        from_level="low",
        to_level="act",
        decision=decision,
        actor="system",
        trigger="test",
    )
    assert prospect_rules_module.is_player_protected("AAA", "P1") is True


def test_development_focus_strategy_auto_protects_when_rule_enabled(prospect_rules_module):
    save_team_strategy_settings(
        default_profile="balanced",
        team_overrides={"AAA": "development_focus"},
    )
    prospect_rules_module.update_prospect_rules(
        enabled=True,
        auto_protect_on_promotion=False,
    )

    decision = prospect_rules_module.evaluate_roster_move(
        "AAA",
        "P4",
        from_level="low",
        to_level="act",
    )
    assert decision.allowed is True
    assert decision.requires_auto_protect is True
    assert "auto-protect" in decision.reason.lower()
    assert decision.reason_tag == "strategy_auto_protect"


def test_option_limit_blocks_after_limit(prospect_rules_module):
    prospect_rules_module.update_prospect_rules(
        enabled=True,
        auto_protect_on_promotion=False,
        default_option_years=1,
    )
    prospect_rules_module.set_player_protection(
        "AAA",
        "P2",
        protected=True,
        actor="test",
        trigger="seed",
    )
    first = prospect_rules_module.evaluate_roster_move(
        "AAA",
        "P2",
        from_level="act",
        to_level="aaa",
    )
    assert first.allowed is True
    assert first.reason_tag == "option_available"
    assert first.details.get("options_remaining") == 1
    prospect_rules_module.apply_roster_move(
        "AAA",
        "P2",
        from_level="act",
        to_level="aaa",
        decision=first,
        actor="test",
        trigger="demote1",
    )

    second = prospect_rules_module.evaluate_roster_move(
        "AAA",
        "P2",
        from_level="act",
        to_level="low",
    )
    assert second.allowed is False
    assert "no option assignments remaining" in second.reason.lower()
    assert second.reason_tag == "option_limit_reached"
    assert second.details.get("options_used") == 1
    assert second.details.get("option_limit") == 1
