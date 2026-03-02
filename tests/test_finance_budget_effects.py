from __future__ import annotations

import json
from datetime import date

from services.finance_budget_effects import (
    development_multiplier_by_player,
    list_team_budget_effects,
    scouting_display_profile_for_team,
    scouting_display_value,
    training_camp_multiplier_by_player,
)
from services.scouting_service import update_scouting_settings
from services.finance_settings import (
    PRESET_OFF,
    PRESET_STANDARD,
    apply_financial_preset,
    ensure_financial_defaults,
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


def _month_token(months_back: int) -> str:
    today = date.today()
    month_index = (today.year * 12 + today.month - 1) - max(0, int(months_back))
    year = month_index // 12
    month = (month_index % 12) + 1
    return f"{year:04d}-{month:02d}"


def test_budget_effects_neutral_when_finance_off(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_OFF,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    effects = list_team_budget_effects(data_dir=data_dir, league_id="alpha")

    assert effects
    for team in effects.values():
        assert team.training_multiplier == 1.0
        assert team.scouting_multiplier == 1.0
        assert team.development_multiplier == 1.0
        assert team.facilities_multiplier == 1.0
        assert team.training_camp_multiplier == 1.0


def test_budget_effects_reflect_budget_ratio(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    payload = json.loads((data_dir / "team_financials.json").read_text(encoding="utf-8"))
    payload["teams"]["AAA"]["budgets"] = {
        "training": 10_000,
        "scouting": 10_000,
        "development": 10_000,
        "facilities": 10_000,
    }
    payload["teams"]["BBB"]["budgets"] = {
        "training": 2_000_000,
        "scouting": 2_000_000,
        "development": 2_000_000,
        "facilities": 2_000_000,
    }
    (data_dir / "team_financials.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    effects = list_team_budget_effects(data_dir=data_dir, league_id="alpha")

    assert effects["AAA"].training_camp_multiplier < 1.0
    assert effects["BBB"].training_camp_multiplier > 1.0


def test_training_camp_multiplier_by_player_uses_team_lookup(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    player_map = {"P1": "AAA", "P2": "BBB", "P3": None}
    multipliers = training_camp_multiplier_by_player(
        player_map,
        data_dir=data_dir,
        league_id="alpha",
    )

    assert set(multipliers.keys()) == {"P1", "P2", "P3"}
    assert multipliers["P1"] > 0
    assert multipliers["P2"] > 0
    assert multipliers["P3"] == 1.0


def test_development_multiplier_by_player_uses_team_lookup(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    payload = json.loads((data_dir / "team_financials.json").read_text(encoding="utf-8"))
    payload["teams"]["AAA"]["budgets"]["development"] = 25_000
    payload["teams"]["BBB"]["budgets"]["development"] = 2_000_000
    (data_dir / "team_financials.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    multipliers = development_multiplier_by_player(
        {"P1": "AAA", "P2": "BBB", "P3": None},
        data_dir=data_dir,
        league_id="alpha",
    )

    assert multipliers["P1"] < multipliers["P2"]
    assert multipliers["P3"] == 1.0


def test_scouting_display_profile_exact_when_finance_off(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_OFF,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    profile = scouting_display_profile_for_team(
        "AAA",
        data_dir=data_dir,
        league_id="alpha",
    )

    assert profile.confidence_label == "Exact"
    assert profile.confidence_score == 100
    assert profile.max_rating_error == 0
    assert scouting_display_value(
        78,
        player_id="P1",
        metric_key="OVR",
        team_id="AAA",
        data_dir=data_dir,
        league_id="alpha",
    ) == 78


def test_scouting_display_value_tracks_budget_and_remains_deterministic(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    apply_financial_preset(
        PRESET_STANDARD,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    update_scouting_settings(enabled=True, data_dir=data_dir, league_id="alpha")

    payload = json.loads((data_dir / "team_financials.json").read_text(encoding="utf-8"))
    payload["teams"]["AAA"]["budgets"]["scouting"] = 25_000
    payload["teams"]["BBB"]["budgets"]["scouting"] = 2_000_000
    (data_dir / "team_financials.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    scouting_payload = {
        "version": 1,
        "leagues": {
            "alpha": {
                "enabled": True,
                "teams": {
                    "AAA": {
                        "confidence": 0.35,
                        "credits": 0.0,
                        "intensity": "normal",
                        "last_period": _month_token(2),
                    },
                    "BBB": {
                        "confidence": 0.35,
                        "credits": 0.0,
                        "intensity": "normal",
                        "last_period": _month_token(2),
                    },
                },
            }
        },
    }
    (data_dir / "scouting_state.json").write_text(
        json.dumps(scouting_payload, indent=2),
        encoding="utf-8",
    )

    low_profile = scouting_display_profile_for_team(
        "AAA",
        data_dir=data_dir,
        league_id="alpha",
    )
    high_profile = scouting_display_profile_for_team(
        "BBB",
        data_dir=data_dir,
        league_id="alpha",
    )

    assert low_profile.confidence_score < high_profile.confidence_score
    assert low_profile.max_rating_error >= high_profile.max_rating_error

    low_first = scouting_display_value(
        70,
        player_id="P1",
        metric_key="CH",
        team_id="AAA",
        data_dir=data_dir,
        league_id="alpha",
    )
    low_second = scouting_display_value(
        70,
        player_id="P1",
        metric_key="CH",
        team_id="AAA",
        data_dir=data_dir,
        league_id="alpha",
    )
    high_value = scouting_display_value(
        70,
        player_id="P1",
        metric_key="CH",
        team_id="BBB",
        data_dir=data_dir,
        league_id="alpha",
    )

    assert low_first == low_second
    assert abs(int(low_first) - 70) <= low_profile.max_rating_error
    assert abs(int(high_value) - 70) <= high_profile.max_rating_error
