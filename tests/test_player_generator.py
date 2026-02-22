from collections import Counter
from datetime import date
import random

import pytest

from playbalance.player_generator import (
    generate_player,
    assign_primary_position,
    generate_birthdate,
    generate_draft_pool,
)
import playbalance.player_generator as pg


def test_generate_player_respects_age_range():
    age_range = (30, 35)
    player = generate_player(is_pitcher=False, age_range=age_range)
    age = (date.today() - player["birthdate"]).days // 365
    assert age_range[0] <= age <= age_range[1]


def test_generate_birthdate_respects_age_tables():
    trials = 100
    for ptype, (base, dice, sides) in pg.AGE_TABLES.items():
        ages = [generate_birthdate(player_type=ptype)[1] for _ in range(trials)]
        assert min(ages) >= base + dice
        assert max(ages) <= base + dice * sides


def test_generate_player_uses_age_table_for_draft():
    player = generate_player(is_pitcher=False, for_draft=True)
    age = (date.today() - player["birthdate"]).days // 365
    base, dice, sides = pg.AGE_TABLES["amateur"]
    assert base + dice <= age <= base + dice * sides


def test_generate_player_allows_explicit_player_type():
    player = generate_player(is_pitcher=False, player_type="filler")
    age = (date.today() - player["birthdate"]).days // 365
    base, dice, sides = pg.AGE_TABLES["filler"]
    assert base + dice <= age <= base + dice * sides


def test_primary_position_override():
    # Establish what random selection would yield with this seed
    random.seed(0)
    random_choice = assign_primary_position()
    assert random_choice != "SS"
    # Reset seed so generate_player would have chosen the same random position
    random.seed(0)
    player = generate_player(is_pitcher=False, primary_position="SS")
    assert player["primary_position"] == "SS"


def test_pitcher_role_sp_when_endurance_high(monkeypatch):
    def fake_core(_throws, **_kwargs):
        return {
            "endurance": 60,
            "control": 55,
            "movement": 55,
            "hold_runner": 50,
            "arm": 55,
            "fa": 50,
        }

    monkeypatch.setattr(pg, "_generate_pitcher_core_ratings", fake_core)
    player = generate_player(is_pitcher=True, rating_profile="arr")
    assert player["endurance"] == 60
    assert player["role"] == "SP"


def test_pitcher_role_rp_when_endurance_low(monkeypatch):
    def fake_core(_throws, **_kwargs):
        return {
            "endurance": 55,
            "control": 55,
            "movement": 55,
            "hold_runner": 50,
            "arm": 55,
            "fa": 50,
        }

    monkeypatch.setattr(pg, "_generate_pitcher_core_ratings", fake_core)
    player = generate_player(is_pitcher=True, rating_profile="arr")
    assert player["endurance"] == 55
    assert player["role"] == "RP"


def test_pitcher_can_hit(monkeypatch):
    def fake_add_hitting(player, age, allocation=0.75):
        rating = int(80 * allocation)
        player.update(
            {
                "ch": rating,
                "pot_ch": pg.bounded_potential(rating, age),
            }
        )

    monkeypatch.setattr(pg, "_maybe_add_hitting", fake_add_hitting)
    # Ensure a younger age so potential is not reduced.
    def fixed_birthdate(age_range=None, player_type="fictional"):
        from datetime import date, timedelta
        age = 25
        return (date.today() - timedelta(days=age * 365), age)

    monkeypatch.setattr(pg, "generate_birthdate", fixed_birthdate)

    player = generate_player(is_pitcher=True)
    assert player["ch"] == int(80 * 0.75)
    assert player["pot_ch"] >= player["ch"]


def test_lefty_pitcher_adjustment(monkeypatch):
    sequence = [50, 60, 60, 50, 55, 50]

    def fake_sample(*_args, **_kwargs):
        value = sequence.pop(0)
        return value, False

    monkeypatch.setattr(pg, "_sample_rating", fake_sample)
    monkeypatch.setattr(pg, "_adjust_endurance", lambda e: e)

    ratings = pg._generate_pitcher_core_ratings("L")
    assert ratings["movement"] == 64
    assert ratings["control"] == 56


def test_lefty_pitcher_adjustment_respects_caps(monkeypatch):
    sequence = [50, 47, 88, 50, 55, 50]

    def fake_sample(*_args, **_kwargs):
        value = sequence.pop(0)
        return value, False

    monkeypatch.setattr(pg, "_sample_rating", fake_sample)
    monkeypatch.setattr(pg, "_adjust_endurance", lambda e: e)

    ratings = pg._generate_pitcher_core_ratings("L")
    assert ratings["movement"] == 92
    assert ratings["control"] == 50


def test_hitter_can_pitch(monkeypatch):
    def fake_randint(a, b):
        if (a, b) == (1, 1000):
            return 1
        if (a, b) == (10, 99):
            return 80
        return (a + b) // 2

    monkeypatch.setattr(pg.random, "randint", fake_randint)

    player = generate_player(is_pitcher=False, primary_position="1B")
    assert player["control"] == int(80 * 0.75)
    assert "P" in player["other_positions"]


def test_hitter_distribution_totals():
    weights = pg.HITTER_RATING_WEIGHTS["1B"]
    total = 500
    ratings = pg.distribute_rating_points(total, weights)
    assert sum(ratings.values()) == total


def test_pitcher_distribution_totals():
    weights = pg.PITCHER_RATING_WEIGHTS
    total = 480
    ratings = pg.distribute_rating_points(total, weights)
    assert sum(ratings.values()) == total


def test_hitter_modifier_ranges(monkeypatch):
    monkeypatch.setattr(pg, "_maybe_add_pitching", lambda *args, **kwargs: None)
    player = generate_player(is_pitcher=False)
    assert 40 <= player["mo"] <= 60
    assert 20 <= player["gf"] <= 90
    assert 40 <= player["cl"] <= 60
    assert 40 <= player["hm"] <= 60
    assert 20 <= player["sc"] <= 90
    assert 20 <= player["pl"] <= 90
    assert 20 <= player["vl"] <= 90


def test_pitcher_modifier_ranges(monkeypatch):
    monkeypatch.setattr(pg, "_maybe_add_hitting", lambda *args, **kwargs: None)
    player = generate_player(is_pitcher=True)
    assert 40 <= player["mo"] <= 60
    assert 20 <= player["gf"] <= 95
    assert 40 <= player["cl"] <= 60
    assert 40 <= player["hm"] <= 60
    assert 30 <= player["pl"] <= 75
    assert 20 <= player["vl"] <= 90


def test_skin_tone_distribution_matches_weights():
    random.seed(0)
    num_players = 600
    ethnicity = "Anglo"
    tones = [pg.assign_skin_tone(ethnicity) for _ in range(num_players)]
    counts = Counter(tones)
    weights = pg.SKIN_TONE_WEIGHTS[ethnicity]
    total_weight = sum(weights.values())
    for tone, weight in weights.items():
        expected = weight / total_weight
        assert abs(counts[tone] / num_players - expected) < 0.05


@pytest.mark.parametrize("is_pitcher", [True, False])
def test_generate_player_includes_appearance(is_pitcher):
    player = generate_player(is_pitcher=is_pitcher)
    assert player["ethnicity"]
    assert player["skin_tone"]
    assert player["hair_color"] in pg.HAIR_COLOR_WEIGHTS[player["ethnicity"]]
    assert player["facial_hair"] in pg.FACIAL_HAIR_WEIGHTS[player["ethnicity"]]


def test_generate_player_varied_ethnicities():
    pg.reset_name_cache()
    random.seed(0)
    ethnicities = {
        generate_player(is_pitcher=False)["ethnicity"] for _ in range(50)
    }
    assert {"Anglo", "African", "Asian", "Hispanic"} <= ethnicities


def test_generate_name_handles_duplicate_pool_exhaustion(monkeypatch):
    monkeypatch.setattr(pg, "_refresh_name_pool", lambda: None)
    monkeypatch.setattr(
        pg,
        "name_pool",
        {"Anglo": [("John", "Smith"), ("John", "Smith")]},
    )
    monkeypatch.setattr(pg, "used_names", {("John", "Smith")})

    first, last, ethnicity = pg.generate_name()

    assert (first, last, ethnicity) == ("John", "Doe", "Unknown")


def test_generate_name_returns_remaining_unique_when_duplicates_exist(monkeypatch):
    monkeypatch.setattr(pg, "_refresh_name_pool", lambda: None)
    monkeypatch.setattr(
        pg,
        "name_pool",
        {
            "Anglo": [("John", "Smith"), ("John", "Smith")],
            "Hispanic": [("Luis", "Diaz")],
        },
    )
    monkeypatch.setattr(pg, "used_names", {("John", "Smith")})

    first, last, ethnicity = pg.generate_name()

    assert (first, last, ethnicity) == ("Luis", "Diaz", "Hispanic")
    assert ("Luis", "Diaz") in pg.used_names


def test_hitter_contact_speed_distribution_centered():
    random.seed(42)
    hitters = [generate_player(is_pitcher=False) for _ in range(300)]
    contacts = [h["ch"] for h in hitters]
    speeds = [h["sp"] for h in hitters]
    contact_mid = sum(45 <= c <= 72 for c in contacts) / len(contacts)
    speed_mid = sum(42 <= s <= 70 for s in speeds) / len(speeds)
    elite_combo = sum(1 for c, s in zip(contacts, speeds) if c >= 90 and s >= 90)
    assert contact_mid > 0.6
    assert speed_mid > 0.6
    assert elite_combo < 5


def test_pitcher_control_movement_floor():
    random.seed(99)
    pitchers = [generate_player(is_pitcher=True) for _ in range(200)]
    assert all(p["control"] >= 50 for p in pitchers)
    assert all(p["movement"] >= 52 for p in pitchers)


def test_generate_closer_archetype():
    player = generate_player(is_pitcher=True, pitcher_archetype="closer")
    assert player["preferred_pitching_role"] == "CL"
    assert player["role"] == "RP"
    assert player["endurance"] <= 55
    assert player["movement"] >= player["control"]
    assert player["sl"] >= 65


def test_generate_draft_pool_includes_closers():
    pool = generate_draft_pool(num_players=40)
    closers = [p for p in pool if p.get("preferred_pitching_role") == "CL"]
    pitchers = [p for p in pool if p.get("primary_position") == "P"]
    assert closers  # at least one closer present
    assert len(closers) <= len(pitchers)


def test_generate_pitches_counts_and_bounds(monkeypatch):
    def fake_randint(a, b):
        if (a, b) == (2, 5):
            return 3  # number of pitches
        if (a, b) == (40, 99):
            return 80  # fastball rating
        if (a, b) == (20, 95):
            return 50  # other pitch ratings
        return (a + b) // 2

    monkeypatch.setattr(pg.random, "randint", fake_randint)
    monkeypatch.setattr(pg.random, "choices", lambda seq, weights=None: [seq[0]])

    ratings, _ = pg.generate_pitches("R", "overhand", age=25)

    assert ratings["fb"] == 80
    assert ratings["si"] == 50
    assert ratings["cu"] == 50
    assert sum(1 for r in ratings.values() if r > 0) == 3
    assert all(0 <= r <= 99 for r in ratings.values())


def test_endurance_adjustment_adds(monkeypatch):
    def fake_randint(a, b):
        if (a, b) == (1, 100):
            return 10  # trigger modification
        if (a, b) == (1, 20):
            return 5   # delta
        return a

    monkeypatch.setattr(pg.random, "randint", fake_randint)
    monkeypatch.setattr(pg.random, "choice", lambda seq: 1)

    assert pg._adjust_endurance(40) == 45


def test_endurance_adjustment_subtracts(monkeypatch):
    def fake_randint(a, b):
        if (a, b) == (1, 100):
            return 10  # trigger modification
        if (a, b) == (1, 20):
            return 5   # delta
        return a

    monkeypatch.setattr(pg.random, "randint", fake_randint)
    monkeypatch.setattr(pg.random, "choice", lambda seq: -1)

    assert pg._adjust_endurance(40) == 35


def test_fielding_potentials_for_unassigned_positions(monkeypatch):
    monkeypatch.setattr(pg, "assign_secondary_positions", lambda primary: [])
    player = generate_player(is_pitcher=False, primary_position="1B")
    pot_fielding = player["pot_fielding"]
    assert player["primary_position"] not in pot_fielding
    assert pot_fielding["2B"] == 20
    assert len(pot_fielding) > 0
