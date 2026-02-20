from datetime import date

from playbalance.aging import age_player
from models.player import Player


def _make_player(age: int) -> Player:
    today = date.today()
    birthdate = date(today.year - age, today.month, today.day).isoformat()
    return Player(
        player_id="p",
        first_name="Test",
        last_name="Player",
        birthdate=birthdate,
        height=72,
        weight=180,
        bats="R",
        primary_position="1b",
        other_positions=[],
        gf=0,
        ch=50,
        ph=50,
        sp=50,
        fa=50,
        arm=50,
    )


def test_age_24_increases_ratings():
    player = _make_player(24)
    age_player(player)
    assert player.ch == 54
    assert player.ph == 59
    assert player.sp == 51
    assert player.arm == 51
    assert player.fa == 56


def test_age_30_declines_speed_and_power():
    player = _make_player(30)
    age_player(player)
    assert player.ch == 50
    assert player.ph == 52
    assert player.sp == 48
    assert player.arm == 50
    assert player.fa == 51


def test_age_40_declines_all():
    player = _make_player(40)
    age_player(player)
    assert player.ch == 44
    assert player.ph == 46
    assert player.sp == 44
    assert player.arm == 47
    assert player.fa == 46


def test_development_multiplier_boosts_growth_years():
    player = _make_player(24)
    age_player(player, development_multiplier=1.25)
    assert player.ch > 54
    assert player.ph > 59
    assert player.fa > 56


def test_development_multiplier_mitigates_decline_years():
    player = _make_player(40)
    age_player(player, development_multiplier=1.25)
    assert player.ch > 44
    assert player.ph > 46
    assert player.sp > 44
