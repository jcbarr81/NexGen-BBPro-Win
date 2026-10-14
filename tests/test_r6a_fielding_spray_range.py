"""Release 6a (fielding): the spray direction fix, the infield bands and the
range model (RELEASE6_PLAN.md 2.3 and 2.4).

- ``spray_direction_model`` 1: spray is drawn batter-relative (positive =
  pull) and stored once as a physical angle (positive = the right-field
  side); ``_spray_dir`` is the same for both hands and the fielder a play is
  credited to is the fielder whose rating set its out chance.
- ``infield_band_model`` 1: a ground ball belongs to the band owner (3B,
  SS, the pitcher, 2B, 1B).
- ``range_model`` 1: one responsible fielder shifts the neutral out chance
  in log-odds.

Each is off by default; with them off the helpers answer as before.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.fielding as fielding
import physics_sim.physics as physics
import scripts.physics_sim_season_kpis as kpis
from physics_sim.centred_ratings import RatingCenterMissing
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile
from physics_sim.fielding import DefenseRatings
from physics_sim.models import BatterRatings

REPO = Path(__file__).resolve().parents[1]
CAL = REPO / "data" / "calibration"
PLAYERS = CAL / "players.csv"
PROFILE = REPO / "scripts" / "kpi_profiles" / "r6_fielding.json"
SPRAY = {"spray_direction_model": 1.0}
BANDS = {"infield_band_model": 1.0}
RANGE = {"range_model": 1.0}
PITCHER = {
    "repertoire": {"fb": 55.0, "sl": 55.0, "cu": 55.0},
    "control": 50.0, "movement": 50.0,
}


def _tuning(**overrides):
    return load_tuning(overrides)


def _fielder(pid, primary, fa=50.0, arm=50.0, other=()):
    return BatterRatings(
        player_id=pid, bats="R", primary_position=primary,
        other_positions=list(other), contact=50.0, power=50.0, gb_tendency=50.0,
        pull_tendency=50.0, vs_left=50.0, fielding=fa, arm=arm, speed=50.0,
        eye=50.0, height=72.0, durability=50.0,
    )


def _defense(tuning, **fa_by_pos) -> DefenseRatings:
    positions = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
    defense = {
        pos: _fielder(f"F{pos}", pos, fa=fa_by_pos.get(pos, 50.0)) for pos in positions
    }
    return fielding.compute_defense_ratings(defense, tuning)


def _balls_in_play(tuning, *, side, pull=50.0, n=300, start=0):
    """``n`` balls in play from the kernel, one per seed (the seed that
    gives one), with the seed that produced each."""
    batter = {
        "contact": 50.0, "power": 50.0, "eye": 50.0, "bats": side,
        "batter_side": side, "pull_tendency": pull,
    }
    found = []
    seed = start
    while len(found) < n:
        random.seed(seed)
        res = physics.simulate_pitch(
            batter=batter, pitcher=PITCHER, tuning=tuning, count=(1, 1)
        )
        if res.outcome == "in_play":
            found.append((seed, res))
        seed += 1
    return found


# --- the switches ------------------------------------------------------------------


def test_the_three_switches_are_off_and_the_centre_band_is_unchanged():
    for key in ("spray_direction_model", "infield_band_model", "range_model"):
        assert DEFAULT_TUNING[key] == 0.0, key
    assert DEFAULT_TUNING["spray_center_band_deg"] == 8.0
    profile = engine_profile(5)
    for key in ("spray_direction_model", "infield_band_model", "range_model"):
        assert key not in profile


# --- the spray convention ----------------------------------------------------------


@pytest.mark.parametrize("side", ["R", "L"])
def test_the_stored_angle_is_mirrored_for_right_handed_batters_only(side):
    """Same seed, same pitch: with the model on a right-handed batter's
    stored angle is minus what it was, a left-handed batter's is what it
    was, and nothing else about the pitch changes (no extra draw)."""
    off = _balls_in_play(_tuning(), side=side, n=120)
    on = _balls_in_play(_tuning(**SPRAY), side=side, n=120)
    assert [seed for seed, _ in off] == [seed for seed, _ in on]
    for (_, before), (_, after) in zip(off, on):
        expected = -before.spray_angle if side == "R" else before.spray_angle
        assert after.spray_angle == expected
        assert after.exit_velo == before.exit_velo
        assert after.launch_angle == before.launch_angle
        assert after.location == before.location
        # The stream is where it was: the next draw is the same number.
    random.seed(off[0][0])
    physics.simulate_pitch(
        batter={"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": side,
                "batter_side": side},
        pitcher=PITCHER, tuning=_tuning(), count=(1, 1),
    )
    after_off = random.random()
    random.seed(off[0][0])
    physics.simulate_pitch(
        batter={"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": side,
                "batter_side": side},
        pitcher=PITCHER, tuning=_tuning(**SPRAY), count=(1, 1),
    )
    assert random.random() == after_off


def test_a_switch_hitter_is_read_by_the_side_he_bats_from():
    """The kernel takes the side from ``batter_side`` (set by the engine
    from the pitcher's hand), falling back on ``bats``."""
    tuning = _tuning(**SPRAY)
    for seed, res in _balls_in_play(_tuning(), side="R", n=20):
        random.seed(seed)
        batter = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R",
                  "pull_tendency": 50.0}
        mirrored = physics.simulate_pitch(
            batter=batter, pitcher=PITCHER, tuning=tuning, count=(1, 1)
        )
        assert mirrored.spray_angle == -res.spray_angle


def test_both_hands_pull_to_their_own_side_with_the_model_on():
    """Physical angle: positive is right field. A pull hitter (pl 80) who
    bats right sends the ball to left (negative), one who bats left to
    right (positive). Hand-blind, both went to right."""
    mean = {}
    for model in (0.0, 1.0):
        tuning = _tuning(spray_direction_model=model)
        for side in ("R", "L"):
            balls = _balls_in_play(tuning, side=side, pull=80.0, n=400)
            mean[(model, side)] = sum(r.spray_angle for _, r in balls) / len(balls)
    assert mean[(0.0, "R")] > 8.0 and mean[(0.0, "L")] > 8.0
    assert mean[(1.0, "R")] < -8.0 and mean[(1.0, "L")] > 8.0
    # The park and the out roll read that angle as physical already.
    assert physics.spray_to_field_angle(45.0) == 0.0  # the right-field line
    assert physics.spray_to_field_angle(-45.0) == pytest.approx(math.pi / 2)


def test_spray_dir_is_the_same_for_both_hands_with_the_model_on():
    off, on = _tuning(), _tuning(**SPRAY)
    for angle in (-30.0, -7.5, 0.0, 12.0, 40.0):
        # Legacy: negated for a right-handed batter only (and with no
        # tuning at all, as the helper used to be called).
        assert engine._spray_dir(angle, "R") == -angle
        assert engine._spray_dir(angle, "L") == angle
        assert engine._spray_dir(angle, "R", off) == -angle
        assert engine._spray_dir(angle, "L", off) == angle
        assert engine._spray_dir(angle, "R", on) == -angle
        assert engine._spray_dir(angle, "L", on) == -angle
        assert fielding.field_direction(angle, "L", on) == -angle


@pytest.mark.parametrize("side", ["R", "L"])
def test_a_ball_is_credited_on_its_physical_side_with_the_model_on(side):
    tuning = _tuning(**SPRAY)

    def credit(ball_type, angle, infield=False):
        return engine._fielder_position_for_ball(
            ball_type=ball_type, spray_angle=angle, batter_side=side,
            tuning=tuning, infield_play=infield,
        )

    assert credit("gb", 30.0, True) == "1B" and credit("gb", -30.0, True) == "3B"
    assert credit("gb", 10.0, True) == "2B" and credit("gb", -10.0, True) == "SS"
    assert credit("fb", 20.0) == "RF" and credit("fb", -20.0) == "LF"
    assert credit("fb", 3.0) == "CF"
    assert engine._hit_advance_position(
        spray_angle=20.0, batter_side=side, tuning=tuning
    ) == "RF"


def test_without_the_model_a_left_handed_batter_s_balls_are_mirrored():
    """The defect (audit M4): the credit read a left-handed batter's ball
    on the other side from the out roll."""
    tuning = _tuning()
    credited = engine._fielder_position_for_ball(
        ball_type="gb", spray_angle=30.0, batter_side="L", tuning=tuning,
        infield_play=True,
    )
    assert credited == "3B"
    assert fielding.responsible_position(
        ball_type="gb", spray_angle=30.0, tuning=tuning
    ) == "1B"


@pytest.mark.parametrize("bands", [0.0, 1.0])
@pytest.mark.parametrize("side", ["R", "L"])
def test_the_credited_fielder_is_the_one_whose_rating_set_the_out_chance(side, bands):
    """With the spray fix on, the engine's credit and the range model's
    responsible fielder are the same position on every ball -- a line
    drive too, played in the infield or not (the review's fix: under the
    range model that is decided before the out chance)."""
    tuning = _tuning(**SPRAY, **RANGE, infield_band_model=bands)
    rng = random.Random(4)
    for _ in range(2000):
        angle = rng.gauss(0.0, 20.0)
        for ball_type, infield in (
            ("gb", True), ("fb", False), ("ld", True), ("ld", False)
        ):
            assert engine._fielder_position_for_ball(
                ball_type=ball_type, spray_angle=angle, batter_side=side,
                tuning=tuning, infield_play=infield,
            ) == fielding.responsible_position(
                ball_type=ball_type, spray_angle=angle, tuning=tuning,
                infield_play=infield,
            )


def test_the_additive_out_chance_already_read_the_physical_side():
    """``out_probability`` picked the fielders by the physical side before
    the fix; the model changes where a right-handed batter's ball goes, not
    how a stored angle is read."""
    tuning = _tuning()
    left_heavy = _defense(tuning, **{"3B": 80.0, "SS": 80.0, "LF": 80.0})
    for side in ("R", "L"):
        kwargs = dict(
            ball_type="gb", exit_velo=90.0, launch_angle=0.0, batter_side=side,
            pull_tendency=50.0, defense=left_heavy, tuning=tuning,
        )
        to_left = fielding.out_probability(spray_angle=-20.0, **kwargs)
        to_right = fielding.out_probability(spray_angle=20.0, **kwargs)
        assert to_left > to_right, side
        assert to_left - to_right == pytest.approx(30.0 / 250.0)


# --- the infield bands -------------------------------------------------------------


def test_the_old_bands_without_the_model():
    cases = {40.0: "3B", 25.0: "3B", 24.9: "SS", 6.0: "SS", 0.0: "SS", -0.1: "2B",
             -6.0: "2B", -24.9: "2B", -25.0: "1B", -40.0: "1B"}
    for direction, expected in cases.items():
        assert engine._infield_pos_for_spray(direction) == expected
        assert engine._infield_pos_for_spray(direction, _tuning()) == expected
        assert fielding.infield_position(direction) == expected


def test_the_new_bands_and_their_lower_bounds():
    tuning = _tuning(**BANDS)
    cases = {40.0: "3B", 16.0: "3B", 15.9: "SS", 1.5: "SS", 1.4: "P", 0.0: "P",
             -1.5: "P", -1.6: "2B", -19.5: "2B", -19.6: "1B", -40.0: "1B"}
    for direction, expected in cases.items():
        assert engine._infield_pos_for_spray(direction, tuning) == expected
    moved = _tuning(
        **BANDS, infield_band_3b_min_deg=20.0, infield_band_ss_min_deg=5.0,
        infield_band_p_min_deg=0.0, infield_band_2b_min_deg=-10.0,
    )
    assert [fielding.infield_position(d, moved) for d in (21, 19, 4, -1, -11)] == [
        "3B", "SS", "P", "2B", "1B"
    ]
    # An infield liner follows the bands too; a fly ball does not.
    assert engine._fielder_position_for_ball(
        ball_type="ld", spray_angle=0.0, batter_side="R", tuning=tuning,
        infield_play=True,
    ) == "P"
    assert engine._fielder_position_for_ball(
        ball_type="fb", spray_angle=0.0, batter_side="R", tuning=tuning,
        infield_play=False,
    ) == "CF"


def test_the_pitcher_is_found_on_the_mound_not_in_the_defence_map():
    from physics_sim.models import PitcherRatings

    arm = PitcherRatings(
        player_id="ARM", bats="R", throws="R", role="SP", preferred_role="SP",
        velocity=50.0, control=50.0, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=50.0, durability=50.0,
        fielding=44.0, arm=50.0, repertoire={"fb": 50.0},
    )
    defense = {"SS": _fielder("FSS", "SS"), "2B": _fielder("F2B", "2B")}
    assert engine._fielder_at(defense, "P", ["SS"], pitcher=arm) == ("P", arm)
    # Without him (an old caller) the ball falls to the fallback, as before.
    assert engine._fielder_at(defense, "P", ["SS"])[0] == "SS"
    assert engine._fielder_at(defense, "2B", ["SS"], pitcher=arm)[0] == "2B"
    # He has no other position to be out of: his fa is his rating.
    assert fielding.adjusted_fielding_rating(arm, "P", _tuning()) == 44.0
    on = _tuning(position_fit_model=1.0)
    assert fielding.adjusted_fielding_rating(arm, "P", on) == 44.0


@pytest.fixture(scope="module")
def generation_6_games():
    """Thirty calibration games on generation 6 with the fielding values."""
    overrides = kpis.resolve_run_overrides(engine=6, overrides_path=PROFILE)
    overrides = kpis.with_rating_centers(overrides, PLAYERS, CAL)
    teams = [f"CAL{i:02d}" for i in range(1, 31)]
    games = []
    for seed in range(1, 31):
        away, home = teams[(2 * seed) % 30], teams[(2 * seed + 7) % 30]
        games.append(
            engine.simulate_matchup_from_files(
                away_team=away, home_team=home, players_path=PLAYERS,
                base_dir=CAL, seed=seed, tuning_overrides=overrides,
            )
        )
    return games


def test_the_ground_balls_are_shared_out_as_the_plan_asks(generation_6_games):
    """About .21 / .30 / .07 / .28 / .14 to 3B / SS / P / 2B / 1B (the
    plan's shares scaled to the whole infield), and about 40% of the
    outfield's putouts to centre."""
    grounders, air = Counter(), Counter()
    for game in generation_6_games:
        for index, pos in game.play_records["fld_pos"].items():
            entry = game.pitch_log[index]
            if entry["ball_type"] == "gb":
                grounders[pos] += 1
            elif pos in ("LF", "CF", "RF") and not entry.get("reached_on_error"):
                air[pos] += 1
    total = sum(grounders.values())
    # 482 on the integrated generation 6 (the pitching and power values
    # change who puts the ball in play): enough for bands of .05.
    assert total > 400
    shares = {pos: grounders[pos] / total for pos in ("3B", "SS", "P", "2B", "1B")}
    targets = {"3B": 0.206, "SS": 0.299, "P": 0.072, "2B": 0.278, "1B": 0.144}
    for pos, target in targets.items():
        assert shares[pos] == pytest.approx(target, abs=0.05), shares
    assert set(grounders) <= set(targets)
    centre = air["CF"] / sum(air.values())
    assert centre == pytest.approx(0.41, abs=0.05)


def test_a_ball_to_the_pitcher_is_his_play(generation_6_games):
    """The pitcher who fielded it gets the assist (a putout on a liner),
    and the play is in his club's fielding lines."""
    plays = credited = 0
    for game in generation_6_games:
        plays += sum(1 for pos in game.play_records["fld_pos"].values() if pos == "P")
        for side in ("away", "home"):
            lines = {
                line["player_id"]: line
                for line in game.metadata["fielding_lines"][side]
            }
            arms = {
                line["player_id"] for line in game.metadata["pitcher_lines"][side]
            }
            credited += sum(
                lines[pid]["a"] + lines[pid]["po"] + lines[pid]["e"]
                for pid in arms
                if pid in lines
            )
    assert plays > 30
    # Every one of them is in a pitcher's fielding line as an assist, a
    # putout or an error (his bunt plays are there too, so at least as many).
    assert credited >= plays


# --- the range model ---------------------------------------------------------------


BALLS = [
    dict(ball_type="gb", exit_velo=88.0, launch_angle=-3.0, spray_angle=-8.0),
    dict(ball_type="gb", exit_velo=101.0, launch_angle=2.0, spray_angle=24.0),
    dict(ball_type="ld", exit_velo=95.0, launch_angle=12.0, spray_angle=-22.0),
    dict(ball_type="fb", exit_velo=92.0, launch_angle=30.0, spray_angle=4.0),
    dict(ball_type="fb", exit_velo=99.0, launch_angle=24.0, spray_angle=31.0),
]


def _out(ball, defense, tuning, side="R", **extra):
    return fielding.out_probability(
        batter_side=side, pull_tendency=50.0, defense=defense, tuning=tuning,
        **ball, **extra,
    )


def test_range_model_off_is_the_additive_chance():
    tuning = _tuning()
    rng = random.Random(9)
    for _ in range(300):
        defense = _defense(
            tuning, **{pos: rng.uniform(30, 75) for pos in ("1B", "2B", "3B", "SS",
                                                           "LF", "CF", "RF")}
        )
        ball = dict(
            ball_type=rng.choice(["gb", "ld", "fb"]), exit_velo=rng.uniform(70, 110),
            launch_angle=rng.uniform(-10, 40), spray_angle=rng.gauss(0, 20),
        )
        kwargs = dict(
            batter_side=rng.choice("RL"), pull_tendency=rng.uniform(30, 80),
            defense=defense, tuning=tuning, batter_speed=rng.uniform(30, 80), **ball,
        )
        assert fielding.out_probability(**kwargs) == fielding._additive_out_probability(
            **kwargs
        )


def test_an_average_fielder_leaves_the_neutral_chance_alone():
    tuning = _tuning(**RANGE)
    average = _defense(tuning)
    for ball in BALLS:
        out0 = fielding.neutral_out_probability(
            batter_side="R", pull_tendency=50.0, tuning=tuning, **ball
        )
        assert _out(ball, average, tuning) == out0
        # out0 is the additive chance behind a defence of 50s.
        assert out0 == fielding._additive_out_probability(
            batter_side="R", pull_tendency=50.0, defense=fielding.NEUTRAL_DEFENSE,
            tuning=_tuning(), **ball,
        )


def test_the_shift_is_in_log_odds_by_the_position_s_slope():
    tuning = _tuning(**RANGE)
    slopes = {
        "1B": 0.0078, "2B": 0.0050, "3B": 0.0081, "SS": 0.0064, "LF": 0.0068,
        "CF": 0.0060, "RF": 0.0066,
    }
    for pos, slope in slopes.items():
        assert DEFAULT_TUNING[f"range_logit_slope_{pos.lower()}"] == slope

    def logit(p):
        return math.log(p / (1.0 - p))

    for ball in BALLS:
        pos = fielding.responsible_position(
            ball_type=ball["ball_type"], spray_angle=ball["spray_angle"], tuning=tuning
        )
        out0 = _out(ball, _defense(tuning), tuning)
        for fa in (35.0, 62.0, 80.0):
            got = _out(ball, _defense(tuning, **{pos: fa}), tuning)
            ratio = 0.6 if ball["ball_type"] == "ld" else 1.0
            assert logit(got) - logit(out0) == pytest.approx(
                slopes[pos] * (fa - 50.0) * ratio
            )


def test_one_fielder_is_responsible_for_a_ball():
    tuning = _tuning(**RANGE)
    everyone = ("1B", "2B", "3B", "SS", "LF", "CF", "RF")
    for ball in BALLS:
        owner = fielding.responsible_position(
            ball_type=ball["ball_type"], spray_angle=ball["spray_angle"], tuning=tuning
        )
        out0 = _out(ball, _defense(tuning), tuning)
        for pos in everyone:
            moved = _out(ball, _defense(tuning, **{pos: 80.0}), tuning)
            assert (moved != out0) == (pos == owner), (ball, pos)
    # The catcher never is.
    assert _out(BALLS[0], _defense(tuning, C=90.0), tuning) == _out(
        BALLS[0], _defense(tuning), tuning
    )


def test_coin_flip_balls_move_most():
    """The same fielder adds most where the ball could go either way and
    almost nothing to a routine out or a sure hit (the additive chance
    added the same to every ball)."""
    tuning = _tuning(**RANGE)
    gain = {}
    for out0 in (0.05, 0.5, 0.95):
        moved = fielding.range_shifted_out_probability(
            out0, position="SS", rating=70.0, ball_type="gb", tuning=tuning
        )
        gain[out0] = moved - out0
    assert gain[0.5] > 4 * gain[0.05] and gain[0.5] > 4 * gain[0.95]
    assert gain[0.5] == pytest.approx(0.0064 * 20 * 0.25, rel=0.02)
    # Never past the engine's bounds.
    assert fielding.range_shifted_out_probability(
        0.98, position="SS", rating=5000.0, ball_type="gb", tuning=tuning
    ) == 0.98


def test_the_pitcher_and_a_missing_fielder_leave_the_chance_neutral():
    tuning = _tuning(**RANGE, **BANDS)
    ball = dict(ball_type="gb", exit_velo=88.0, launch_angle=-3.0, spray_angle=0.0)
    assert fielding.responsible_position(
        ball_type="gb", spray_angle=0.0, tuning=tuning
    ) == "P"
    great = _defense(tuning, **{p: 90.0 for p in ("1B", "2B", "3B", "SS")})
    out0 = fielding.neutral_out_probability(
        batter_side="R", pull_tendency=50.0, tuning=tuning, **ball
    )
    assert _out(ball, great, tuning) == out0
    # Nobody at the position: an average fielder's chance.
    no_short = fielding.compute_defense_ratings({"2B": _fielder("F2B", "2B", 90.0)}, tuning)
    ball = dict(ball_type="gb", exit_velo=88.0, launch_angle=-3.0, spray_angle=-8.0)
    assert _out(ball, no_short, tuning) == fielding.neutral_out_probability(
        batter_side="R", pull_tendency=50.0, tuning=tuning, **ball
    )


def test_range_scale_and_the_line_drive_ratio_are_knobs():
    base = _tuning(**RANGE)
    double = _tuning(**RANGE, range_scale=2.0)
    no_liners = _tuning(**RANGE, range_ld_ratio=0.0)

    def gain(tuning, ball_type):
        return fielding.range_shifted_out_probability(
            0.5, position="CF", rating=60.0, ball_type=ball_type, tuning=tuning
        ) - 0.5

    assert gain(double, "fb") == pytest.approx(2 * gain(base, "fb"), rel=0.01)
    assert gain(base, "ld") == pytest.approx(0.6 * gain(base, "fb"), rel=0.01)
    assert gain(no_liners, "ld") == 0.0
    # range_scale no longer multiplies the rating itself (a 50 stays a 50).
    assert _out(BALLS[3], _defense(double), double) == _out(
        BALLS[3], _defense(base), base
    )


def test_the_fielder_s_rating_is_centred_and_charged_the_table_first():
    """What the range model reads is ``adjusted_fielding_rating``: the
    out-of-position table, then the league's regulars at the position."""
    centres = {key: 50.0 for key in fielding.FIELDER_FA_CENTER_KEYS.values()}
    centres.update({key: 50.0 for key in fielding.FIELDER_ARM_CENTER_KEYS.values()})
    centres["fielder_fa_center_ss"] = 56.0
    centres["fielder_arm_center_ss"] = 58.0
    tuning = _tuning(
        **RANGE, fielder_centred_ratings=1.0, position_fit_model=1.0, **centres
    )
    short = _fielder("S", "SS", fa=56.0, arm=58.0)
    assert fielding.adjusted_fielding_rating(short, "SS", tuning) == 50.0
    assert fielding.fielder_arm_rating(short, "SS", tuning) == 50.0
    assert fielding.adjusted_arm_rating(short, tuning) == 58.0  # the Release 4 read
    stand_in = _fielder("X", "1B", fa=60.0)
    assert fielding.adjusted_fielding_rating(stand_in, "SS", tuning) == 60 - 14 - 6
    # The catcher has no fielder centre: his terms centre him themselves.
    assert fielding.adjusted_fielding_rating(_fielder("C", "C", 61.0), "C", tuning) == 61.0
    defense = fielding.compute_defense_ratings({"SS": short, "C": _fielder("C", "C", 90)}, tuning)
    assert defense.positions == {"SS": 50.0, "C": 90.0}
    assert defense.infield == 50.0  # the catcher is not on the fielders' scale
    # Off: nothing is shifted and the centres are not read.
    off = _tuning(**centres)
    assert fielding.adjusted_fielding_rating(short, "SS", off) == 56.0
    assert fielding.fielder_arm_rating(short, "SS", off) == 58.0


def test_a_game_refuses_to_start_without_the_fielder_centres():
    overrides = kpis.with_rating_centers(
        {"fielder_centred_ratings": 1.0}, PLAYERS, CAL
    )
    # Delivered (the harness supplies them): it plays.
    engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", players_path=PLAYERS, base_dir=CAL,
        seed=1, tuning_overrides=overrides,
    )
    for missing in ("fielder_fa_center_ss", "fielder_arm_center_rf", "fielder_fa_center_p"):
        short = {k: v for k, v in overrides.items() if k != missing}
        with pytest.raises(RatingCenterMissing, match=missing):
            engine.simulate_matchup_from_files(
                away_team="CAL01", home_team="CAL02", players_path=PLAYERS,
                base_dir=CAL, seed=1, tuning_overrides=short,
            )
    with pytest.raises(RatingCenterMissing, match="fielder_fa_center_1b"):
        fielding.adjusted_fielding_rating(
            _fielder("X", "1B"), "1B", _tuning(fielder_centred_ratings=1.0)
        )
    # With the switch off nothing is asked for.
    engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", players_path=PLAYERS, base_dir=CAL,
        seed=1, tuning_overrides={},
    )


# --- double plays ------------------------------------------------------------------


def test_the_double_play_knobs_shrink_what_the_ratings_add():
    """The generation 6 values: the base holds the rate while the range
    and arm terms are a sixth and a third of what they were."""
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert profile["double_play_range_scale"] == 0.2
    assert profile["double_play_arm_scale"] == 0.4
    assert profile["double_play_base"] == 0.42
    old, new = _tuning(), _tuning(**{k: profile[k] for k in (
        "double_play_range_scale", "double_play_arm_scale", "double_play_base")})

    def chance(tuning, infield_range=50.0, turn_arm=50.0):
        return fielding.double_play_probability(
            runner_speed=50.0, infield_range=infield_range, turn_arm=turn_arm,
            tuning=tuning,
        )

    assert chance(new) == pytest.approx(0.42)
    range_old = chance(old, infield_range=60.0) - chance(old)
    range_new = chance(new, infield_range=60.0) - chance(new)
    assert range_new == pytest.approx(range_old / 6.0)
    arm_old = chance(old, turn_arm=60.0) - chance(old)
    arm_new = chance(new, turn_arm=60.0) - chance(new)
    assert arm_new == pytest.approx(arm_old / 3.0)


def test_the_turn_reads_centred_arms_and_leaves_the_pitcher_s_out(monkeypatch):
    from physics_sim.models import PitcherRatings

    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return 0.0

    monkeypatch.setattr(engine, "double_play_probability", spy)
    centres = {key: 50.0 for key in fielding.FIELDER_FA_CENTER_KEYS.values()}
    centres.update({key: 60.0 for key in fielding.FIELDER_ARM_CENTER_KEYS.values()})
    tuning = _tuning(
        fielder_centred_ratings=1.0, infield_band_model=1.0,
        spray_direction_model=1.0, ground_out_model=0.0, **centres,
    )
    defense = {
        pos: _fielder(f"F{pos}", pos, fa=50.0, arm=60.0)
        for pos in ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
    }
    ratings = fielding.compute_defense_ratings(defense, tuning)
    arm = PitcherRatings(
        player_id="ARM", bats="R", throws="R", role="SP", preferred_role="SP",
        velocity=95.0, control=50.0, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=50.0, durability=50.0,
        fielding=70.0, arm=95.0, repertoire={"fb": 50.0},
    )

    def turn(spray):
        seen.clear()
        bases = engine.BaseState(first=_fielder("R1", "CF"))
        engine._resolve_ground_out(
            bases=bases, outs=0, batter=_fielder("B", "CF"), defense_map=defense,
            defense_ratings=ratings, spray_angle=spray, batter_side="R",
            tuning=tuning, mound=arm,
        )
        return dict(seen)

    # A ball to short: every arm in the turn is the league's average there.
    assert turn(-8.0)["turn_arm"] == 50.0
    # A ball back to the pitcher: his 95 "arm" (velocity) is not in the
    # turn; his fa 70 is in the range the double play reads, with the
    # shortstop who takes his throw.
    back = turn(-1.0)
    assert back["turn_arm"] == 50.0
    assert back["infield_range"] == pytest.approx((70.0 + 50.0) / 2)
