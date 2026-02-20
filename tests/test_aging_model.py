from __future__ import annotations

from datetime import date

from models.player import Player
from playbalance.aging_model import age_and_retire


def _make_player(player_id: str, *, age: int, ch: int = 50, ph: int = 50, sp: int = 50, fa: int = 50, arm: int = 50) -> Player:
    today = date.today()
    birthdate = date(today.year - age, today.month, today.day).isoformat()
    return Player(
        player_id=player_id,
        first_name="Test",
        last_name="Player",
        birthdate=birthdate,
        height=72,
        weight=180,
        bats="R",
        primary_position="1b",
        other_positions=[],
        gf=0,
        ch=ch,
        ph=ph,
        sp=sp,
        fa=fa,
        arm=arm,
    )


def test_age_and_retire_applies_per_player_development_multiplier():
    low = _make_player("low", age=24)
    high = _make_player("high", age=24)
    players = {"low": low, "high": high}

    retired = age_and_retire(
        players,
        development_multiplier_by_player={"low": 0.85, "high": 1.25},
    )

    assert retired == []
    low_gain = (low.ch - 50) + (low.ph - 50) + (low.fa - 50)
    high_gain = (high.ch - 50) + (high.ph - 50) + (high.fa - 50)
    assert high_gain >= low_gain
