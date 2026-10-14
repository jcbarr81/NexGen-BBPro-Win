"""Release 6a (power): who hits the doubles (plan 2.2; owner decision 11).

A ball that stays in the park is a double when it carries past
``double_distance * double_distance_scale * (1 - speed term)
* (1 - gap_norm * double_gap_scale)``. Two things are new, both off by
default:

- ``double_gap_power_weight`` (0.5 = today): Power's share of ``gap_norm``,
  ``(Contact * (1 - w) + Power * w - 50) / 50``. Generation 6 keeps a
  smaller Power share (the owner's rule: high Contact AND above-average
  Power), not the Contact-only credit the design brief proposed.
- ``double_line_drive_scale`` (0.0 = no term) with
  ``double_line_drive_span``: the distance is multiplied by
  ``1 - scale * max(0, 1 - |gf - hitter_gf_center| / span)``. The hitter at
  the league's mean ground-ball rating needs the least distance; extreme
  ground-ball and fly-ball profiles get no credit. It reads the rating,
  not the launch angle: today's model moves a hitter's mean launch angle
  0.1 degree per point of gf, so nothing read off the ball can separate
  profiles three points apart.

Neither draws a random number, on or off.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile
from physics_sim.park import load_park

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
PROFILE_PATH = REPO / "scripts" / "kpi_profiles" / "r6_power.json"
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
PARK = load_park(None)
LINE_DRIVE = {"double_line_drive_scale": 0.08, "double_line_drive_span": 10.0}


def _resolve(tuning, exit_velo, *, launch=20.0, spray=0.0, **batter):
    return physics.resolve_batted_ball(
        exit_velo=exit_velo, launch_angle=launch, spray_angle=spray, park=PARK,
        tuning=tuning, **batter,
    )


def _double_distance(tuning, **batter) -> float:
    """The shortest carry that is a double for this hitter (bisection on
    exit velocity at a 20 degree launch angle to straightaway centre)."""
    low, high = 40.0, 110.0
    assert _resolve(tuning, low, **batter)[3] == "single"
    assert _resolve(tuning, high, **batter)[3] in ("double", "triple")
    for _ in range(60):
        mid = (low + high) / 2.0
        if _resolve(tuning, mid, **batter)[3] == "single":
            low = mid
        else:
            high = mid
    return _resolve(tuning, high, **batter)[0]


def _hitter(contact=50.0, power=50.0, gf=None, speed=50.0) -> dict:
    return {
        "batter_speed": speed, "batter_contact": contact, "batter_power": power,
        "batter_gb_tendency": gf,
    }


def _generation_6(**extra):
    """Generation 6 with this area's profile, in a league whose hitters'
    ground-ball ratings average 50."""
    overrides = kpis.load_tuning_overrides_file(
        PROFILE_PATH, base=engine_profile(6, development=True)
    )
    return load_tuning(
        {**engine_profile(6, development=True), **overrides,
         "hitter_gf_center": 50.0, **extra}
    )


# --- registered, off ---


def test_the_knobs_are_registered_at_todays_behaviour():
    assert DEFAULT_TUNING["double_gap_power_weight"] == 0.5
    assert DEFAULT_TUNING["double_line_drive_scale"] == 0.0
    assert DEFAULT_TUNING["double_line_drive_span"] > 0.0
    bumped = {
        "double_gap_power_weight": 0.2, "double_line_drive_scale": 0.05,
        "double_line_drive_span": 7.0,
    }
    tuning = load_tuning(bumped)  # an unregistered key would be dropped
    for key, value in bumped.items():
        assert tuning.get(key) == value, key
    assert not set(bumped) & set(engine_profile(5))
    # Generation 6 holds this work's values since the Release 6a integration.
    profile = engine_profile(6, development=True)
    for key in bumped:
        assert profile[key] == PROFILE[key], key


def _legacy_gap_threshold(tuning, contact, power, speed):
    """The double threshold as the engine computed it before Release 6a."""
    angle = physics.spray_to_field_angle(0.0)
    speed_norm = max(-1.0, min(1.0, (speed - 50.0) / 50.0))
    gap_norm = ((contact + power) / 2.0 - 50.0) / 50.0
    gap_norm = max(-1.0, min(1.0, gap_norm))
    return (
        PARK.stadium.double_distance(angle)
        * tuning.get("park_size_scale", 1.0)
        * tuning.get("double_distance_scale", 1.0)
        * (1.0 - speed_norm * tuning.get("double_speed_scale", 0.0))
        * (1.0 - gap_norm * tuning.get("double_gap_scale", 0.0))
    )


@pytest.mark.parametrize("profile", [{}, engine_profile(5)], ids=["legacy", "gen5"])
def test_off_every_ball_resolves_exactly_as_before(profile):
    """With and without a ground-ball rating, with the new keys absent and
    with them spelled out at their defaults: the same tuple, bit for bit,
    and a double exactly where the old expression put it."""
    plain = load_tuning(profile)
    spelled = load_tuning(
        {**profile, "double_gap_power_weight": 0.5, "double_line_drive_scale": 0.0}
    )
    rng = random.Random(4)
    doubles = 0
    for _ in range(4000):
        exit_velo = rng.uniform(60.0, 112.0)
        launch = rng.uniform(-15.0, 50.0)
        spray = rng.uniform(-40.0, 40.0)
        contact, power = rng.uniform(30.0, 75.0), rng.uniform(30.0, 75.0)
        speed, gf = rng.uniform(25.0, 80.0), rng.uniform(20.0, 80.0)
        old_call = physics.resolve_batted_ball(
            exit_velo=exit_velo, launch_angle=launch, spray_angle=spray, park=PARK,
            tuning=plain, batter_speed=speed, batter_contact=contact,
            batter_power=power,
        )
        for tuning in (plain, spelled):
            assert physics.resolve_batted_ball(
                exit_velo=exit_velo, launch_angle=launch, spray_angle=spray,
                park=PARK, tuning=tuning, batter_speed=speed,
                batter_contact=contact, batter_power=power, batter_gb_tendency=gf,
            ) == old_call
        doubles += old_call[3] == "double"
    assert doubles > 100
    # The threshold itself, against the old expression written out here.
    for contact, power, speed in ((50, 50, 50), (62, 41, 35), (44, 66, 70)):
        got = _double_distance(plain, **_hitter(contact, power, gf=37.0, speed=speed))
        assert got == pytest.approx(
            _legacy_gap_threshold(plain, contact, power, speed), rel=1e-6
        )


def test_resolving_a_ball_draws_no_random_number_on_or_off():
    on = load_tuning({**LINE_DRIVE, "double_gap_power_weight": 0.25})
    for tuning in (load_tuning(), on):
        random.seed(8)
        state = random.getstate()
        for exit_velo in (70.0, 88.0, 97.0, 104.0):
            _resolve(tuning, exit_velo, **_hitter(60.0, 55.0, gf=44.0))
        assert random.getstate() == state


# --- Power's share of the gap credit ---


def test_the_power_weight_splits_the_gap_credit():
    scale = 0.3
    for weight in (0.0, 0.25, 0.5, 1.0):
        tuning = load_tuning(
            {"double_gap_power_weight": weight, "double_gap_scale": scale}
        )
        average = _double_distance(tuning, **_hitter())
        for contact, power in ((60.0, 50.0), (50.0, 60.0), (60.0, 53.33), (42.0, 64.0)):
            gap_norm = (contact * (1 - weight) + power * weight - 50.0) / 50.0
            got = _double_distance(tuning, **_hitter(contact, power))
            assert got / average == pytest.approx(1.0 - gap_norm * scale, rel=1e-6)


def test_with_no_power_share_power_does_not_move_the_distance():
    tuning = load_tuning({"double_gap_power_weight": 0.0})
    distances = {
        power: _double_distance(tuning, **_hitter(55.0, power))
        for power in (35.0, 50.0, 65.0)
    }
    assert len({round(d, 6) for d in distances.values()}) == 1
    today = load_tuning()
    assert _double_distance(today, **_hitter(55.0, 65.0)) < (
        _double_distance(today, **_hitter(55.0, 35.0))
    )


def test_generation_6_contact_leads_and_power_still_counts():
    """Decision 11: contact-led, Power keeping a smaller share."""
    weight = PROFILE["double_gap_power_weight"]
    assert 0.0 < weight < 0.5
    scale = PROFILE["double_gap_scale"]
    # A point of Contact is worth what it is today or more; a point of Power
    # less than half of what it is today.
    today = DEFAULT_TUNING["double_gap_scale"] * 0.5
    assert scale * (1.0 - weight) >= today - 1e-9
    assert 0.0 < scale * weight <= today * 0.5
    tuning = _generation_6()
    average = _double_distance(tuning, **_hitter(gf=50.0))
    contact_hitter = _double_distance(tuning, **_hitter(60.0, 50.0, gf=50.0))
    power_hitter = _double_distance(tuning, **_hitter(50.0, 60.0, gf=50.0))
    both = _double_distance(tuning, **_hitter(60.0, 53.33, gf=50.0))
    assert both < contact_hitter < power_hitter < average


# --- the line-drive credit ---


def test_the_neutral_profile_needs_the_least_distance():
    tuning = load_tuning({**LINE_DRIVE, "hitter_gf_center": 50.0})
    plain = _double_distance(load_tuning(), **_hitter())
    by_gf = {
        gf: _double_distance(tuning, **_hitter(gf=gf))
        for gf in (20.0, 40.0, 44.0, 47.0, 50.0, 53.0, 56.0, 60.0, 80.0)
    }
    assert by_gf[50.0] == pytest.approx(plain * (1.0 - 0.08), rel=1e-6)
    assert by_gf[47.0] == pytest.approx(plain * (1.0 - 0.08 * 0.7), rel=1e-6)
    assert by_gf[44.0] == pytest.approx(plain * (1.0 - 0.08 * 0.4), rel=1e-6)
    # Ground-ball and fly-ball profiles lose it alike.
    assert by_gf[53.0] == pytest.approx(by_gf[47.0], rel=1e-9)
    assert by_gf[56.0] == pytest.approx(by_gf[44.0], rel=1e-9)
    assert by_gf[50.0] < by_gf[47.0] < by_gf[44.0] < by_gf[40.0]
    # A span away or more there is no credit, however extreme the rating.
    for gf in (20.0, 40.0, 60.0, 80.0):
        assert by_gf[gf] == pytest.approx(plain, rel=1e-6), gf


def test_the_profile_is_read_against_the_leagues_ground_ball_centre():
    """A 55 in a league whose regulars average 55 is the neutral profile."""
    high = load_tuning({**LINE_DRIVE, "hitter_gf_center": 55.0})
    mid = load_tuning({**LINE_DRIVE, "hitter_gf_center": 50.0})
    assert _double_distance(high, **_hitter(gf=55.0)) == pytest.approx(
        _double_distance(mid, **_hitter(gf=50.0)), rel=1e-9
    )
    assert _double_distance(high, **_hitter(gf=50.0)) == pytest.approx(
        _double_distance(mid, **_hitter(gf=45.0)), rel=1e-9
    )
    # Generation 5's centred ratings do not shift gf: the centre is the
    # league's own, never the 50 a shifted rating is compared with.
    centred = load_tuning(
        {**LINE_DRIVE, "centred_ratings": 1.0, "hitter_gf_center": 55.0}
    )
    assert _double_distance(centred, **_hitter(gf=55.0)) == pytest.approx(
        _double_distance(high, **_hitter(gf=55.0)), rel=1e-9
    )


def test_a_hitter_with_no_ground_ball_rating_gets_no_credit():
    tuning = load_tuning({**LINE_DRIVE, "hitter_gf_center": 50.0})
    plain = _double_distance(load_tuning(), **_hitter())
    assert _double_distance(tuning, **_hitter(gf=None)) == pytest.approx(
        plain, rel=1e-9
    )
    assert _resolve(tuning, 95.0, **_hitter(gf="n/a")) == _resolve(
        load_tuning(), 95.0, **_hitter()
    )


def test_the_credit_only_moves_the_double_line():
    """Home runs, the batted-ball class, the distance and triples at the
    top of the range are untouched; some singles become doubles."""
    off = load_tuning({"hitter_gf_center": 50.0})
    on = load_tuning({**LINE_DRIVE, "hitter_gf_center": 50.0})
    rng = random.Random(12)
    gained = 0
    for _ in range(4000):
        exit_velo = rng.uniform(60.0, 112.0)
        launch = rng.uniform(-15.0, 50.0)
        spray = rng.uniform(-40.0, 40.0)
        args = dict(launch=launch, spray=spray, **_hitter(gf=50.0))
        before = _resolve(off, exit_velo, **args)
        after = _resolve(on, exit_velo, **args)
        assert after[:3] == before[:3]
        if after[3] != before[3]:
            assert (before[3], after[3]) == ("single", "double")
            gained += 1
    assert gained > 20


def test_generation_6_gives_the_line_drive_profile_a_real_lead():
    assert PROFILE["double_line_drive_scale"] > 0.0
    tuning = _generation_6()
    span = tuning.get("double_line_drive_span")
    scale = tuning.get("double_line_drive_scale")
    assert 4.0 <= span <= 12.0
    neutral = _double_distance(tuning, **_hitter(gf=50.0))
    extreme = _double_distance(tuning, **_hitter(gf=50.0 + span))
    assert neutral / extreme == pytest.approx(1.0 - scale, rel=1e-6)
    # Three points of gf -- the spread of a league's regulars -- is at least
    # 1.5% of the distance, and the far end of the scale no more than 12%.
    three = _double_distance(tuning, **_hitter(gf=53.0))
    assert three / neutral >= 1.015
    assert scale <= 0.12


def test_the_top_doubles_hitter_is_high_contact_above_average_power_neutral_profile():
    """The owner's rule, on the distance a double needs under generation 6."""
    tuning = _generation_6()
    owner = _double_distance(tuning, **_hitter(60.0, 53.33, gf=50.0))
    for contact, power, gf in (
        (60.0, 53.33, 42.0),  # the same bat with a fly-ball profile
        (60.0, 53.33, 58.0),  # the same bat with a ground-ball profile
        (60.0, 45.0, 50.0),   # high Contact, below-average Power
        (50.0, 60.0, 50.0),   # the slugger without the Contact
        (50.0, 50.0, 50.0),   # the average hitter
    ):
        assert owner < _double_distance(tuning, **_hitter(contact, power, gf=gf))


# --- the engine passes the rating ---


def test_a_game_hands_every_ball_in_play_the_hitters_ground_ball_rating(monkeypatch):
    seen = []
    real = engine.resolve_batted_ball

    def spy(**kwargs):
        seen.append(kwargs["batter_gb_tendency"])
        return real(**kwargs)

    monkeypatch.setattr(engine, "resolve_batted_ball", spy)
    players = CALIBRATION / "players.csv"
    engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", players_path=players,
        base_dir=CALIBRATION, seed=3,
        tuning_overrides=kpis.with_rating_centers({}, players, CALIBRATION),
    )
    assert len(seen) > 30
    assert all(isinstance(gf, (int, float)) for gf in seen)
    assert len(set(seen)) > 3  # the hitters' own ratings, not a constant


def test_a_game_with_the_credit_on_plays_the_same_pitches_until_a_double_moves():
    """No extra random number: the pitch stream is the old one up to the
    first ball whose hit type the credit changes."""
    players = CALIBRATION / "players.csv"
    base = kpis.with_rating_centers(engine_profile(5), players, CALIBRATION)

    def play(overrides):
        return engine.simulate_matchup_from_files(
            away_team="CAL01", home_team="CAL02", players_path=players,
            base_dir=CALIBRATION, seed=5, tuning_overrides=overrides,
        ).pitch_log

    off = play(base)
    on = play({**base, "double_line_drive_scale": 0.3, "double_line_drive_span": 10.0})
    changed = [
        index for index, (a, b) in enumerate(zip(off, on))
        if a.get("hit_type") != b.get("hit_type")
    ]
    assert changed, "a credit this large must move a hit type in nine innings"
    first = changed[0]
    assert off[:first] == on[:first]
    assert (off[first]["hit_type"], on[first]["hit_type"]) == ("single", "double")
    for key in ("exit_velo", "launch_angle", "spray_angle", "distance", "velocity"):
        assert off[first][key] == on[first][key], key
