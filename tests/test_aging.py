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
    # Growth year: ratings rise from the 50 baseline (values match the current
    # deterministic aging curve).
    assert player.ch == 56
    assert player.ph == 57
    assert player.sp == 51
    assert player.arm == 51
    assert player.fa == 57


def test_age_30_declines_speed_and_power():
    player = _make_player(30)
    age_player(player)
    assert player.ch == 50
    assert player.ph == 53
    assert player.sp == 49
    assert player.arm == 50
    assert player.fa == 52


def test_age_40_declines_all():
    player = _make_player(40)
    age_player(player)
    assert player.ch == 44
    assert player.ph == 46
    assert player.sp == 44
    assert player.arm == 47
    assert player.fa == 46


def test_development_multiplier_boosts_growth_years():
    # Compare against the non-multiplier baseline rather than hardcoded magic
    # numbers, so this stays valid as the aging curve is retuned.
    base = _make_player(24)
    age_player(base)
    boosted = _make_player(24)
    age_player(boosted, development_multiplier=1.25)
    assert boosted.ch >= base.ch
    assert boosted.ph >= base.ph
    assert boosted.fa >= base.fa
    assert (boosted.ch, boosted.ph, boosted.fa) != (base.ch, base.ph, base.fa)


def test_development_multiplier_mitigates_decline_years():
    player = _make_player(40)
    age_player(player, development_multiplier=1.25)
    assert player.ch > 44
    assert player.ph > 46
    assert player.sp > 44
