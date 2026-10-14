from models.player import Player
from models.pitcher import Pitcher
from playbalance.aging import spring_training_pitch


def make_player(**kwargs):
    defaults = {
        "player_id": "1",
        "first_name": "Test",
        "last_name": "Player",
        "birthdate": "2000-01-01",
        "height": 72,
        "weight": 180,
        "bats": "R",
        "primary_position": "OF",
        "other_positions": [],
        "gf": 50,
    }
    defaults.update(kwargs)
    return Player(**defaults)


def make_pitcher(**kwargs):
    defaults = {
        "player_id": "2",
        "first_name": "Pitch",
        "last_name": "Er",
        "birthdate": "2000-01-01",
        "height": 72,
        "weight": 180,
        "bats": "R",
        "primary_position": "P",
        "other_positions": [],
        "gf": 50,
    }
    defaults.update(kwargs)
    return Pitcher(**defaults)


def test_player_ratings_capped_on_assignment():
    player = make_player(ch=120)
    assert player.ch == 99
    player.sp = 150
    assert player.sp == 99


def test_pitch_training_capped_at_99():
    pitcher = make_pitcher(fb=98)
    spring_training_pitch(pitcher)
    assert pitcher.fb == 99
