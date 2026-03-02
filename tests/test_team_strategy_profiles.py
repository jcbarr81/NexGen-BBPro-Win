from __future__ import annotations

import json

from services.team_strategy_profiles import (
    load_team_strategy_settings,
    resolve_team_strategy_profile,
    save_team_strategy_settings,
    set_team_strategy_profile,
    to_finance_strategy_profile,
    update_league_default_strategy,
)


def test_team_strategy_defaults_to_balanced(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    settings = load_team_strategy_settings(data_dir=data_dir, league_id="alpha")

    assert settings["default_profile"] == "balanced"
    assert settings["team_overrides"] == {}


def test_team_strategy_save_and_resolve_override(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    update_league_default_strategy(
        "win_now",
        data_dir=data_dir,
        league_id="alpha",
    )
    set_team_strategy_profile(
        "AAA",
        "development_focus",
        data_dir=data_dir,
        league_id="alpha",
    )

    aaa = resolve_team_strategy_profile("AAA", data_dir=data_dir, league_id="alpha")
    bbb = resolve_team_strategy_profile("BBB", data_dir=data_dir, league_id="alpha")

    assert aaa.profile == "development_focus"
    assert aaa.source == "team_override"
    assert bbb.profile == "win_now"
    assert bbb.source == "league_default"


def test_team_strategy_save_discards_overrides_matching_default(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    saved = save_team_strategy_settings(
        default_profile="balanced",
        team_overrides={
            "AAA": "balanced",
            "BBB": "power_offense",
        },
        data_dir=data_dir,
        league_id="alpha",
    )
    assert saved["team_overrides"] == {"BBB": "power_offense"}

    payload = json.loads((data_dir / "team_strategy_profiles.json").read_text(encoding="utf-8"))
    assert payload["leagues"]["alpha"]["teams"] == {"BBB": "power_offense"}


def test_set_team_strategy_profile_clears_to_default(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    save_team_strategy_settings(
        default_profile="balanced",
        team_overrides={"AAA": "power_offense"},
        data_dir=data_dir,
        league_id="alpha",
    )

    result = set_team_strategy_profile(
        "AAA",
        "default",
        data_dir=data_dir,
        league_id="alpha",
    )
    assert result["saved"] is True
    settings = load_team_strategy_settings(data_dir=data_dir, league_id="alpha")
    assert settings["team_overrides"] == {}


def test_to_finance_strategy_profile_map():
    assert to_finance_strategy_profile("win_now") == "contend"
    assert to_finance_strategy_profile("development_focus") == "rebuild"
    assert to_finance_strategy_profile("defense_first") == "balanced"
