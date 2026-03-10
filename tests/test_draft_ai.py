from __future__ import annotations

from services.draft_ai import score_prospect


def test_score_prospect_strategy_bias_for_hitters():
    needs = {"1B": 0.0, "CF": 0.0}
    slugger = {
        "is_pitcher": False,
        "primary_position": "1B",
        "ch": 60,
        "ph": 84,
        "sp": 44,
        "eye": 55,
        "fa": 38,
        "arm": 40,
        "gf": 42,
        "birthdate": "2006-05-10",
    }
    defender = {
        "is_pitcher": False,
        "primary_position": "CF",
        "ch": 56,
        "ph": 58,
        "sp": 67,
        "eye": 52,
        "fa": 86,
        "arm": 84,
        "gf": 79,
        "birthdate": "2006-05-10",
    }

    power_slugger = score_prospect(slugger, needs, strategy_profile="power_offense")
    power_defender = score_prospect(defender, needs, strategy_profile="power_offense")
    defense_slugger = score_prospect(slugger, needs, strategy_profile="defense_first")
    defense_defender = score_prospect(defender, needs, strategy_profile="defense_first")

    assert power_slugger > power_defender
    assert defense_defender > defense_slugger


def test_score_prospect_strategy_bias_for_pitchers():
    needs = {"SP": 0.2, "RP": 0.2}
    young_project = {
        "is_pitcher": True,
        "primary_position": "P",
        "endurance": 56,
        "control": 52,
        "movement": 51,
        "hold_runner": 45,
        "arm": 74,
        "pot_arm": 88,
        "pot_control": 79,
        "pot_movement": 77,
        "birthdate": "2008-06-01",
    }
    ready_veteran = {
        "is_pitcher": True,
        "primary_position": "P",
        "endurance": 77,
        "control": 73,
        "movement": 70,
        "hold_runner": 58,
        "arm": 66,
        "pot_arm": 68,
        "pot_control": 70,
        "pot_movement": 68,
        "birthdate": "2001-06-01",
    }

    dev_young = score_prospect(young_project, needs, strategy_profile="development_focus")
    dev_veteran = score_prospect(ready_veteran, needs, strategy_profile="development_focus")
    win_now_young = score_prospect(young_project, needs, strategy_profile="win_now")
    win_now_veteran = score_prospect(ready_veteran, needs, strategy_profile="win_now")

    assert dev_young > win_now_young
    assert win_now_veteran > dev_veteran
