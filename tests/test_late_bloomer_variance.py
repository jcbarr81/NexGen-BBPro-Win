from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from services.finance_budget_effects import ScoutingDisplayProfile
from services.late_bloomer_variance import (
    apply_late_bloomer_variance,
    late_bloomer_adjustment,
)


def _player(age: int):
    today = date.today()
    birthdate = date(today.year - age, today.month, today.day).isoformat()
    return SimpleNamespace(birthdate=birthdate)


def test_late_bloomer_adjustment_scales_with_uncertainty():
    low = late_bloomer_adjustment(
        player_id="P1",
        team_id="AAA",
        age=27,
        uncertainty_score=0.25,
        season_token="season-2030",
    )
    high = late_bloomer_adjustment(
        player_id="P1",
        team_id="AAA",
        age=27,
        uncertainty_score=0.85,
        season_token="season-2030",
    )
    assert abs(high) >= abs(low)


def test_apply_late_bloomer_variance_is_deterministic(monkeypatch):
    def _profile(*_args, **_kwargs):
        return ScoutingDisplayProfile(
            team_id="AAA",
            scouting_multiplier=1.0,
            confidence_score=42,
            confidence_label="Moderate",
            max_rating_error=6,
        )

    monkeypatch.setattr(
        "services.late_bloomer_variance.scouting_display_profile_for_team",
        _profile,
    )

    players = {"P1": _player(28), "P2": _player(24)}
    team_lookup = {"P1": "AAA", "P2": "AAA"}
    base = {"P1": 1.0, "P2": 1.0}

    first = apply_late_bloomer_variance(
        players_by_id=players,
        player_team_lookup=team_lookup,
        base_multipliers=base,
        season_token="season-2031",
    )
    second = apply_late_bloomer_variance(
        players_by_id=players,
        player_team_lookup=team_lookup,
        base_multipliers=base,
        season_token="season-2031",
    )

    assert first == second
    assert set(first.keys()) == {"P1", "P2"}


def test_apply_late_bloomer_variance_no_uncertainty_no_change(monkeypatch):
    def _profile(*_args, **_kwargs):
        return ScoutingDisplayProfile(
            team_id="AAA",
            scouting_multiplier=1.0,
            confidence_score=100,
            confidence_label="Exact",
            max_rating_error=0,
        )

    monkeypatch.setattr(
        "services.late_bloomer_variance.scouting_display_profile_for_team",
        _profile,
    )

    players = {"P1": _player(31)}
    team_lookup = {"P1": "AAA"}
    base = {"P1": 1.08}
    output = apply_late_bloomer_variance(
        players_by_id=players,
        player_team_lookup=team_lookup,
        base_multipliers=base,
        season_token="season-2032",
    )
    assert output["P1"] == 1.08
