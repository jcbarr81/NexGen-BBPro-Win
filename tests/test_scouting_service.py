from __future__ import annotations

import json
from pathlib import Path

from services.scouting_service import (
    load_team_scouting_controls,
    load_scouting_settings,
    set_team_scouting_intensity,
    scouting_observed_value,
    team_scouting_profile,
    update_scouting_settings,
)


def _write_teams(path: Path) -> None:
    path.write_text(
        (
            "team_id,name,city,abbreviation,division,stadium,primary_color,"
            "secondary_color,owner_id\n"
            "AAA,Alphas,Alpha,AAA,East,Alpha Park,#111111,#222222,\n"
            "BBB,Bears,Beta,BBB,East,Beta Park,#111111,#222222,\n"
        ),
        encoding="utf-8",
    )


def _seed_team_state(
    data_dir: Path,
    *,
    league_id: str,
    team_id: str,
    confidence: float,
    credits: float,
    last_period: str,
) -> None:
    payload = {
        "version": 1,
        "leagues": {
            league_id: {
                "enabled": True,
                "teams": {
                    team_id: {
                        "confidence": confidence,
                        "credits": credits,
                        "intensity": "normal",
                        "last_period": last_period,
                    }
                },
            }
        },
    }
    (data_dir / "scouting_state.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def test_scouting_defaults_disabled(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")

    settings = load_scouting_settings(data_dir=data_dir, league_id="alpha")
    assert settings["enabled"] is False

    profile = team_scouting_profile(
        "AAA",
        finance_enabled=False,
        data_dir=data_dir,
        league_id="alpha",
    )
    assert profile.enabled is False
    assert profile.confidence_label == "Exact"
    assert profile.max_rating_error == 0


def test_observed_value_is_deterministic_for_profile():
    from services.scouting_service import TeamScoutingProfile

    profile = TeamScoutingProfile(
        enabled=True,
        team_id="AAA",
        scouting_multiplier=1.0,
        confidence_score=42,
        confidence_label="Moderate",
        max_rating_error=5,
    )
    first = scouting_observed_value(
        70,
        team_profile=profile,
        player_id="P1",
        metric_key="CH",
        team_id="AAA",
    )
    second = scouting_observed_value(
        70,
        team_profile=profile,
        player_id="P1",
        metric_key="CH",
        team_id="AAA",
    )
    assert first == second
    assert abs(int(first) - 70) <= 5


def test_finance_off_progression_is_slightly_slower(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    update_scouting_settings(enabled=True, data_dir=data_dir, league_id="alpha")

    _seed_team_state(
        data_dir,
        league_id="alpha",
        team_id="AAA",
        confidence=0.35,
        credits=0.0,
        last_period="2025-01",
    )
    team_scouting_profile(
        "AAA",
        finance_enabled=False,
        finance_multiplier=1.0,
        data_dir=data_dir,
        league_id="alpha",
        current_date="2025-03-10",
    )
    off_payload = json.loads((data_dir / "scouting_state.json").read_text(encoding="utf-8"))
    off_conf = float(
        off_payload["leagues"]["alpha"]["teams"]["AAA"]["confidence"]
    )

    _seed_team_state(
        data_dir,
        league_id="alpha",
        team_id="AAA",
        confidence=0.35,
        credits=0.0,
        last_period="2025-01",
    )
    team_scouting_profile(
        "AAA",
        finance_enabled=True,
        finance_multiplier=1.0,
        data_dir=data_dir,
        league_id="alpha",
        current_date="2025-03-10",
    )
    on_payload = json.loads((data_dir / "scouting_state.json").read_text(encoding="utf-8"))
    on_conf = float(
        on_payload["leagues"]["alpha"]["teams"]["AAA"]["confidence"]
    )

    assert on_conf > off_conf


def test_update_scouting_settings_persists_extended_tuning(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    update_scouting_settings(
        enabled=True,
        base_monthly_credits=240.0,
        finance_off_multiplier=0.82,
        monthly_decay=0.01,
        passive_gain=0.008,
        max_banked_credits=750.0,
        auto_spend_cap=140.0,
        data_dir=data_dir,
        league_id="alpha",
    )
    settings = load_scouting_settings(data_dir=data_dir, league_id="alpha")

    assert settings["enabled"] is True
    assert float(settings["base_monthly_credits"]) == 240.0
    assert float(settings["finance_off_multiplier"]) == 0.82
    assert float(settings["monthly_decay"]) == 0.01
    assert float(settings["passive_gain"]) == 0.008
    assert float(settings["max_banked_credits"]) == 750.0
    assert float(settings["auto_spend_cap"]) == 140.0


def test_team_scouting_intensity_controls_round_trip(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_teams(data_dir / "teams.csv")
    update_scouting_settings(enabled=True, data_dir=data_dir, league_id="alpha")

    saved = set_team_scouting_intensity(
        "AAA",
        "high",
        data_dir=data_dir,
        league_id="alpha",
    )
    assert saved["saved"] is True
    controls = load_team_scouting_controls(
        "AAA",
        finance_enabled=False,
        data_dir=data_dir,
        league_id="alpha",
    )
    assert controls["intensity"] == "high"
    assert float(controls["estimated_monthly_income"]) > 0.0

    set_team_scouting_intensity(
        "AAA",
        "invalid",
        data_dir=data_dir,
        league_id="alpha",
    )
    controls_after_invalid = load_team_scouting_controls(
        "AAA",
        finance_enabled=False,
        data_dir=data_dir,
        league_id="alpha",
    )
    assert controls_after_invalid["intensity"] == "normal"
