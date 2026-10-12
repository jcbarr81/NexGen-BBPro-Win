"""Release 5: league-relative ratings (``centred_ratings``).

Audit decision 2: the engine reads a rating as 50 + (rating - league mean).
With ``centred_ratings`` on (generation 5's profile) every rating that
feeds a plate appearance is shifted once, where it enters the pitch kernel,
by 50 minus its league centre (``physics_sim.centred_ratings``), and the
hitter centres are means over the lineup regulars
(``services.league_rating_centers``).

A pitcher's four ratings are shifted by workload-weighted centres (the
``pitcher_*_usage_center`` keys: a rotation starter counts 2.5 times a
reliever); the plain ACT means stay what the Release 4 running-game terms
read.

The acceptance test is INVARIANCE: add one constant to every hitter's
Contact, Power and Eye and to the three hitter centres -- or to every
pitcher's control, movement, arm and pitch grades and to their centres --
and a seeded game is the same game, to the last bit of every float in the
pitch log. That holds for a league's real two-decimal centres and for a
shift that is not a whole number too, because the shifted rating is rounded
where it is made (``centred_ratings.league_relative``): without that,
``rating + (50 - centre)`` lands a last bit apart in the two leagues, and
one game in thirty picked a different reliever on it. With the switch off
the same shift changes the game. The legacy engine (the switch off, the
default) is untouched.

A game is never played half-shifted: the engine refuses to shift by a
centre that was not delivered, and a generation 5 season entry whose
Release 5 centres were fixed by an earlier build (or merged with an older
instance's) is recomputed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
from physics_sim import centred_ratings
from physics_sim.centred_ratings import (
    CENTRED_RATING_KEYS,
    MODEL_CENTER_KEYS,
    REQUIRED_CENTER_KEYS,
    RatingCenterMissing,
    league_relative,
    rating_center,
    ratings_centred,
    require_rating_centers,
    source_shift,
)
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile
from physics_sim.models import PITCH_KEYS, BatterRatings, PitcherRatings
from physics_sim.usage import UsageState
from services import league_rating_centers as centers
from utils.roster_rules import counts_as_pitcher

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "physics_sim"
CALIBRATION = REPO / "data" / "calibration"
CALIBRATION_LEAGUE = REPO / "data" / "calibration_league"

HITTER_CENTRES = (
    "hitter_contact_center",
    "hitter_power_center",
    "hitter_eye_center",
)
# The workload-weighted centres the shift reads ...
PITCHER_USAGE_CENTRES = (
    "pitcher_control_usage_center",
    "pitcher_movement_usage_center",
    "pitcher_arm_usage_center",
    "pitcher_grade_usage_center",
)
# ... and the plain ACT means: what the Release 4 running-game terms read
# (control and arm) and what the Release 5 models read with the switch off.
PITCHER_PLAIN_CENTRES = (
    "pitcher_control_center",
    "pitcher_movement_center",
    "pitcher_arm_center",
    "pitcher_grade_center",
)
# A league whose pitchers all move by a constant moves both sets.
PITCHER_CENTRES = PITCHER_USAGE_CENTRES + PITCHER_PLAIN_CENTRES
HITTER_COLUMNS = ("ch", "ph", "eye")
PITCHER_COLUMNS = ("control", "movement", "arm") + tuple(PITCH_KEYS)
# Centres that are exact in binary floating point, so a shifted league's
# arithmetic is exact and its game can be compared to the last bit.
EXACT_CENTRES = {
    "hitter_contact_center": 51.5,
    "hitter_power_center": 50.25,
    "hitter_eye_center": 49.75,
    "pitcher_control_usage_center": 52.75,
    "pitcher_movement_usage_center": 52.5,
    "pitcher_arm_usage_center": 55.25,
    "pitcher_grade_usage_center": 55.75,
    "pitcher_control_center": 52.5,
    "pitcher_movement_center": 53.25,
    "pitcher_arm_center": 56.0,
    "pitcher_grade_center": 55.5,
    "hitter_speed_center": 48.0,
    "pitcher_hold_center": 50.5,
    "catcher_arm_center": 55.0,
    "catcher_fa_center": 54.5,
}
SHIFTS = (6.0, -4.0)


@pytest.fixture(autouse=True)
def _fresh_cache():
    centers.clear_rating_center_cache()
    yield
    centers.clear_rating_center_cache()


def _tuning(**overrides):
    return load_tuning(overrides)


def _centred(**overrides):
    """The switch on with every centre it reads delivered (at 50 unless
    ``overrides`` says otherwise), as a league's tuning always is."""
    delivered = {key: 50.0 for key in CENTRED_RATING_KEYS | set(MODEL_CENTER_KEYS)}
    return load_tuning({"centred_ratings": 1, **delivered, **overrides})


def _generation_5(switch: float = 1.0, **overrides) -> dict:
    return {**engine_profile(5), "centred_ratings": switch, **overrides}


def _batter(**ratings) -> BatterRatings:
    values = dict(
        player_id="b", bats="R", primary_position="CF", other_positions=[],
        contact=50.0, power=50.0, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=50.0, speed=50.0, eye=50.0,
        height=73.0, durability=50.0,
    )
    values.update(ratings)
    return BatterRatings(**values)


def _pitcher(**ratings) -> PitcherRatings:
    values = dict(
        player_id="p", bats="R", throws="R", role="SP", preferred_role="SP",
        velocity=50.0, control=50.0, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=50.0, durability=50.0,
        fielding=50.0, arm=50.0, repertoire={"fb": 60.0, "sl": 45.0},
    )
    values.update(ratings)
    return PitcherRatings(**values)


# --- registration and the profile ---------------------------------------------


def test_the_switch_and_the_power_centre_are_registered_off():
    assert DEFAULT_TUNING["centred_ratings"] == 0.0
    assert DEFAULT_TUNING["hitter_power_center"] == 50.0
    # from_overrides silently drops a key that is not registered.
    tuning = _tuning(centred_ratings=1, hitter_power_center="52.25")
    assert tuning.get("centred_ratings") == 1.0
    assert tuning.get("hitter_power_center") == 52.25
    assert not ratings_centred(load_tuning()) and ratings_centred(tuning)
    assert not ratings_centred(None)
    for key in CENTRED_RATING_KEYS | set(MODEL_CENTER_KEYS):
        assert DEFAULT_TUNING[key] == 50.0, key
    # The shift reads the hitters' own centres and the pitchers' usage
    # centres; the models name the plain pitcher means.
    assert CENTRED_RATING_KEYS == set(HITTER_CENTRES) | set(PITCHER_USAGE_CENTRES)
    assert set(MODEL_CENTER_KEYS) == set(HITTER_CENTRES) | set(PITCHER_PLAIN_CENTRES)
    for plain, usage in MODEL_CENTER_KEYS.items():
        assert usage in (plain, plain.replace("_center", "_usage_center"))


def test_generation_5_switches_it_on_and_legacy_does_not():
    assert engine_profile(5)["centred_ratings"] == 1
    assert "centred_ratings" not in engine_profile(4)
    harness = json.loads(
        (REPO / "scripts" / "kpi_profiles" / "r5.json").read_text(encoding="utf-8")
    )
    assert harness["centred_ratings"] == 1
    # The live path hands the engine every centre the switch shifts by.
    assert CENTRED_RATING_KEYS <= set(centers.RATING_CENTER_KEYS)


# --- the accessor ---------------------------------------------------------------


def test_source_shift_is_fifty_minus_the_centre_only_with_the_switch_on():
    on = _centred(hitter_contact_center=52.5)
    off = _tuning(hitter_contact_center=52.5)
    assert source_shift(on, "hitter_contact_center") == -2.5
    assert source_shift(on, "hitter_power_center") == 0.0  # delivered as 50
    assert source_shift(off, "hitter_contact_center") == 0.0
    # A pitcher's rating is shifted by its usage centre, never by the plain
    # ACT mean (the Release 4 terms' centre), whatever that holds.
    arms = _centred(pitcher_arm_usage_center=57.75, pitcher_arm_center=59.5)
    assert source_shift(arms, "pitcher_arm_usage_center") == -7.75
    with pytest.raises(KeyError):
        source_shift(arms, "pitcher_arm_center")
    # A rating that is not shifted at its source has no shift to ask for.
    with pytest.raises(KeyError):
        source_shift(on, "catcher_fa_center")
    with pytest.raises(KeyError):
        source_shift(on, "hitter_speed_center")


def test_rating_center_reads_fifty_for_a_rating_already_shifted():
    values = {key: 57.0 for key in CENTRED_RATING_KEYS | set(MODEL_CENTER_KEYS)}
    values["catcher_fa_center"] = 54.5
    on = _tuning(centred_ratings=1, **values)
    off = _tuning(**values)
    # The centre a model names: 50 once its rating arrives shifted.
    for key in MODEL_CENTER_KEYS:
        assert rating_center(on, key) == 50.0, key
        assert rating_center(off, key) == 57.0, key
    # Catcher fielding is not shifted: its centre is always the league's.
    assert rating_center(on, "catcher_fa_center") == 54.5
    assert rating_center(off, "catcher_fa_center") == 54.5
    # A usage centre is the shift's: no model may name one.
    for key in PITCHER_USAGE_CENTRES:
        with pytest.raises(KeyError):
            rating_center(on, key)
        with pytest.raises(KeyError):
            rating_center(off, key)


# --- a centre that was not delivered is never read as 50 --------------------------


def test_a_shift_by_an_undelivered_centre_raises():
    """Every centre defaults to 50.0; that default is never taken for a
    league's centre once the switch is on."""
    bare = _tuning(centred_ratings=1, hitter_contact_center=52.5)
    assert bare.delivered == {"centred_ratings", "hitter_contact_center"}
    assert source_shift(bare, "hitter_contact_center") == -2.5
    for key in CENTRED_RATING_KEYS - {"hitter_contact_center"}:
        with pytest.raises(RatingCenterMissing, match=key):
            source_shift(bare, key)
    with pytest.raises(RatingCenterMissing, match="hitter_power_center"):
        league_relative(60.0, "hitter_power_center", bare)
    with pytest.raises(RatingCenterMissing):
        engine._batter_context(_batter(), _pitcher(), bare)
    with pytest.raises(RatingCenterMissing):
        engine._pitcher_context(_pitcher(), bare)
    # Delivered AS 50 is a league whose mean is 50: a shift of nothing.
    assert source_shift(_centred(), "hitter_power_center") == 0.0
    # With the switch off nothing is asked of anyone.
    off = _tuning(hitter_contact_center=52.5)
    assert source_shift(off, "pitcher_arm_usage_center") == 0.0
    assert league_relative(60.0, "hitter_power_center", off) == 60.0
    require_rating_centers(off)
    require_rating_centers(None)
    # A TuningConfig that was not built from overrides delivered nothing.
    from physics_sim.config import TuningConfig

    plain = TuningConfig()
    assert plain.delivered == frozenset()
    plain.values["centred_ratings"] = 1.0
    with pytest.raises(RatingCenterMissing):
        require_rating_centers(plain)


def test_a_generation_5_game_without_its_centres_is_not_played():
    profile = _generation_5()
    kwargs = dict(
        away_team="CAL01", home_team="CAL02", base_dir=CALIBRATION,
        players_path=CALIBRATION / "players.csv", seed=1,
    )
    with pytest.raises(RatingCenterMissing) as failure:
        engine.simulate_matchup_from_files(tuning_overrides=profile, **kwargs)
    for key in REQUIRED_CENTER_KEYS:
        assert key in str(failure.value)
    # Half of them is as bad: hitters would shift and pitchers would not.
    real = centers.active_rating_centers(CALIBRATION)
    hitters_only = {**profile, **{key: real[key] for key in HITTER_CENTRES}}
    with pytest.raises(RatingCenterMissing, match="pitcher_control_usage_center"):
        engine.simulate_matchup_from_files(tuning_overrides=hitters_only, **kwargs)
    # A usage state is not touched by a game that is refused.
    usage = UsageState()
    with pytest.raises(RatingCenterMissing):
        engine.simulate_matchup_from_files(
            tuning_overrides=profile, usage_state=usage, game_day=3, **kwargs
        )
    assert usage.workloads == {} and usage.current_day != 3
    played = engine.simulate_matchup_from_files(
        tuning_overrides={**profile, **real}, **kwargs
    )
    assert played.totals["pa"] > 50
    # The legacy engine asks for none of them.
    assert engine.simulate_matchup_from_files(**kwargs).totals["pa"] > 50


def test_a_pitcher_without_pitch_grades_asks_for_no_grade_centre():
    # A league whose pitchers carry no pitch grades has no grade centre to
    # deliver; they throw the stand-in 50, which needs no shift.
    tuning = load_tuning(
        {"centred_ratings": 1, **{key: 52.0 for key in REQUIRED_CENTER_KEYS}}
    )
    require_rating_centers(tuning)
    bare = engine._pitcher_context(_pitcher(repertoire={}), tuning)
    assert bare["repertoire"] == {"fb": 50} and bare["control"] == 48.0
    with pytest.raises(RatingCenterMissing, match="pitcher_grade_usage_center"):
        engine._pitcher_context(_pitcher(), tuning)


# --- no centre is read twice ------------------------------------------------------
# (The static guard on how the engine's source reads centres and raw ratings
# is tests/test_r5_centred_guard.py.)

# Every centre the switch has a say in: the ones the shift reads and the
# ones a model names for a shifted rating.
COVERED_KEYS = CENTRED_RATING_KEYS | set(MODEL_CENTER_KEYS)


def test_under_the_switch_the_models_compare_against_fifty():
    """The formulas that subtract a centre themselves: with the switch on a
    league's centres must not move them (their inputs arrive shifted)."""
    wild = {key: 63.0 for key in COVERED_KEYS}
    models = dict(
        swing_model=1, contact_model=1, command_model=1,
        swing_two_strike_contact_logit=0.06, two_strike_protect_contact=0.06,
        two_strike_protect_eye=0.05, eye_control_blend=0.2,
    )
    plain = _tuning(centred_ratings=1, **models)
    moved = _tuning(centred_ratings=1, **models, **wild)
    off = _tuning(**models, **wild)

    def readings(tuning):
        return (
            physics._contact_probability(
                contact=58.0, pitch_quality=61.0, break_mag=0.3, velocity=93.0,
                pitch_type="fb", in_zone=True, strikes=2, tuning=tuning,
            ),
            physics._swing_probability(
                eye=57.0, contact=58.0, platoon_chase=0.0, in_zone=False,
                balls=1, strikes=1, tuning=tuning,
            ),
            physics._swing_probability(
                eye=57.0, contact=58.0, platoon_chase=0.0, in_zone=True,
                balls=1, strikes=2, tuning=tuning,
            ),
            physics._command_error(control=61.0, movement=55.0, tuning=tuning),
            physics._two_strike_zone_protect(
                0.5, contact=58.0, eye=57.0, tuning=tuning
            ),
            physics._swing_logit_table(tuning)[1],
        )

    assert readings(moved) == readings(plain)
    assert physics._swing_logit_table(moved)[1] == 50.0
    # With the switch off the same centres are the league's own.
    assert all(a != b for a, b in zip(readings(off), readings(plain)))


# --- the shift, once, at the source -------------------------------------------------


def test_batter_context_shifts_contact_power_and_eye_before_everything():
    centres = dict(
        hitter_contact_center=53.0, hitter_power_center=47.5,
        hitter_eye_center=51.0, pitcher_control_usage_center=56.0,
        # The plain ACT mean is not what the shift reads.
        pitcher_control_center=71.0,
    )
    quiet = dict(
        handedness_contact_bonus=0.0, handedness_power_bonus=0.0,
        handedness_eye_bonus=0.0, platoon_contact_scale=0.0,
        platoon_power_scale=0.0, platoon_eye_scale=0.0, eye_control_blend=0.0,
    )
    batter = _batter(contact=60.0, power=55.0, eye=44.0)
    pitcher = _pitcher(control=70.0)
    on = engine._batter_context(
        batter, pitcher, _tuning(centred_ratings=1, **centres, **quiet)
    )
    assert on["contact"] == 57.0
    assert on["power"] == on["power_base"] == 57.5
    assert on["eye"] == 43.0
    off = engine._batter_context(batter, pitcher, _tuning(**centres, **quiet))
    assert (off["contact"], off["power"], off["power_base"], off["eye"]) == (
        60.0, 55.0, 55.0, 44.0,
    )
    # The control blended into the eye is the pitcher's shifted control.
    blend = dict(quiet, eye_control_blend=0.2)
    mixed = engine._batter_context(
        batter, pitcher, _tuning(centred_ratings=1, **centres, **blend)
    )
    assert mixed["eye"] == pytest.approx(43.0 * 0.8 + (100.0 - 64.0) * 0.2)
    # The situational shifts ride on top of the shifted rating, and the
    # clamp comes last: a 99 in a weak league is still capped at 100.
    star = engine._batter_context(
        _batter(contact=99.0, power=99.0, eye=99.0),
        pitcher,
        _centred(
            hitter_contact_center=45.0, hitter_power_center=45.0,
            hitter_eye_center=45.0, **quiet,
        ),
    )
    assert (star["contact"], star["power"], star["eye"]) == (100.0, 100.0, 100.0)
    assert star["power_base"] == 104.0
    edge = _tuning(centred_ratings=1, home_field_edge=0.8, **centres, **quiet)
    home = engine._batter_context(batter, pitcher, edge, home=True)
    assert home["contact"] == pytest.approx(57.8)
    assert home["power_base"] == 57.5


def test_pitcher_context_shifts_control_movement_arm_and_grades():
    centres = dict(
        pitcher_control_usage_center=52.0, pitcher_movement_usage_center=54.5,
        pitcher_arm_usage_center=57.5, pitcher_grade_usage_center=58.0,
    )
    pitcher = _pitcher(control=60.0, movement=50.0, arm=65.0)
    on = engine._pitcher_context(pitcher, _tuning(centred_ratings=1, **centres))
    # The plain ACT means (the Release 4 terms' centres) have no say in it.
    plain = {key: 77.0 for key in PITCHER_PLAIN_CENTRES}
    assert on == engine._pitcher_context(
        pitcher, _tuning(centred_ratings=1, **centres, **plain)
    )
    assert on["control"] == 58.0
    assert on["movement"] == 45.5
    assert on["velocity"] == 83.0 + (65.0 - 7.5) * 0.2
    assert on["repertoire"] == {"fb": 52.0, "sl": 37.0}
    assert pitcher.repertoire == {"fb": 60.0, "sl": 45.0}  # not mutated
    off = engine._pitcher_context(pitcher, _tuning(**centres))
    assert off == {
        "repertoire": pitcher.repertoire,
        "velocity": 83.0 + 65.0 * 0.2,
        "control": 60.0,
        "movement": 50.0,
        "fatigue_factor": 1.0,
        "hand": "R",
        "vs_left": 50.0,
    }
    assert off["repertoire"] is pitcher.repertoire
    # No repertoire: the stand-in 50 fastball is the league-average pitch.
    bare = engine._pitcher_context(
        _pitcher(repertoire={}), _tuning(centred_ratings=1, **centres)
    )
    assert bare["repertoire"] == {"fb": 50}


def _traced_pitches(monkeypatch, overrides, seed):
    """Play CAL01 at CAL02 recording the pitcher inputs of every pitch."""
    pitches: list[dict] = []
    fresh: list[float] = []
    real_pitch = engine.simulate_pitch
    real_fresh = engine._reliever_fresh_bonus

    def pitch(**kwargs):
        pitches.append({**kwargs["pitcher"], "fresh": fresh[-1]})
        return real_pitch(**kwargs)

    def bonus(**kwargs):
        fresh.append(real_fresh(**kwargs))
        return fresh[-1]

    monkeypatch.setattr(engine, "simulate_pitch", pitch)
    monkeypatch.setattr(engine, "_reliever_fresh_bonus", bonus)
    result = engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", base_dir=CALIBRATION,
        players_path=CALIBRATION / "players.csv", seed=seed,
        tuning_overrides=overrides,
    )
    return result, pitches


def test_every_pitch_gets_the_shift_before_the_bonus_and_the_fatigue(monkeypatch):
    from physics_sim.data_loader import load_players_by_id

    _batters, pitchers = load_players_by_id(CALIBRATION / "players.csv")
    overrides = _generation_5(**EXACT_CENTRES)
    result, pitches = _traced_pitches(monkeypatch, overrides, seed=2)
    entries = [e for e in result.pitch_log if "pitch_count" in e]
    assert len(entries) == len(pitches) > 200
    # 50 minus the usage centres: control 52.75, movement 52.5, arm 55.25,
    # grade 55.75 (the plain means in EXACT_CENTRES differ from every one).
    shift = {
        key: 50.0 - EXACT_CENTRES[key] for key in PITCHER_USAGE_CENTRES
    }
    tired = fresh = 0
    for entry, pitch in zip(entries, pitches):
        rating = pitchers[entry["pitcher_id"]]
        velocity_factor, command_factor, movement_factor = engine._fatigue_factors(
            entry["fatigue_penalty"]
        )
        tired += command_factor < 1.0
        fresh += pitch["fresh"] > 0.0
        assert pitch["control"] == (
            rating.control + shift["pitcher_control_usage_center"] + pitch["fresh"]
        ) * command_factor
        assert pitch["movement"] == (
            rating.movement
            + shift["pitcher_movement_usage_center"]
            + pitch["fresh"]
        ) * movement_factor
        # The arm rating is shifted, not the fatigued velocity.
        assert pitch["velocity"] == 83.0 + (
            (rating.arm + shift["pitcher_arm_usage_center"]) * 0.2
        )
        assert pitch["fatigue_factor"] == velocity_factor
        assert pitch["repertoire"] == {
            name: grade + shift["pitcher_grade_usage_center"]
            for name, grade in rating.repertoire.items()
        }
    assert tired and fresh


# --- games ------------------------------------------------------------------------


def _shifted_league(
    root: Path, fixture: Path, *, hitters: float = 0.0, pitchers: float = 0.0
) -> Path:
    """A copy of ``fixture`` with a constant added to every hitter's
    Contact, Power and Eye and to every pitcher's control, movement, arm and
    pitch grades (a pitch he does not throw stays unthrown)."""
    shutil.copytree(fixture, root)
    path = root / "players.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        if counts_as_pitcher(row):
            columns, delta = PITCHER_COLUMNS, pitchers
        else:
            columns, delta = HITTER_COLUMNS, hitters
        for column in columns:
            raw = (row.get(column) or "").strip()
            if delta and raw and float(raw) > 0.0:
                row[column] = repr(float(raw) + delta)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return root


def _shifted_centres(centres: dict, *, hitters: float = 0.0, pitchers: float = 0.0):
    moved = dict(centres)
    for key in HITTER_CENTRES:
        moved[key] = moved[key] + hitters
    for key in PITCHER_CENTRES:
        moved[key] = moved[key] + pitchers
    return moved


def _play(root: Path, overrides: dict, teams, seeds, *, series: bool = False):
    usage = UsageState() if series else None
    games = []
    for day, seed in enumerate(seeds):
        games.append(
            engine.simulate_matchup_from_files(
                away_team=teams[day % 2], home_team=teams[(day + 1) % 2],
                base_dir=root, players_path=root / "players.csv", seed=seed,
                tuning_overrides=overrides, usage_state=usage,
                game_day=day if series else None,
            )
        )
    return games


def _canon(value):
    if isinstance(value, float):
        return float.__repr__(value)
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def _digest(games) -> str:
    """sha256 of the pitch log, totals and metadata, every float at full
    precision (its repr)."""
    blob = json.dumps(
        _canon(
            [
                {"pitch_log": g.pitch_log, "totals": g.totals, "meta": g.metadata}
                for g in games
            ]
        ),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _scores(games):
    return [(g.metadata["score"]["away"], g.metadata["score"]["home"]) for g in games]


def _close(a, b, where="game"):
    """Equal in every outcome; floats equal to 1e-9."""
    if isinstance(a, float) and isinstance(b, float):
        assert a == pytest.approx(b, rel=1e-9, abs=1e-9), where
    elif isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), where
        for key in a:
            _close(a[key], b[key], f"{where}.{key}")
    elif isinstance(a, (list, tuple)):
        assert isinstance(b, (list, tuple)) and len(a) == len(b), where
        for index, (left, right) in enumerate(zip(a, b)):
            _close(left, right, f"{where}[{index}]")
    else:
        assert a == b, where


def _assert_same_games(got, want):
    for index, (a, b) in enumerate(zip(got, want)):
        _close(a.totals, b.totals, f"game {index} totals")
        _close(a.pitch_log, b.pitch_log, f"game {index} pitch log")
        _close(a.metadata, b.metadata, f"game {index} metadata")


SEEDS = (1, 2, 3)
GAME_CASES = [
    pytest.param(CALIBRATION, ("CAL01", "CAL02"), id="calibration"),
    pytest.param(CALIBRATION_LEAGUE, ("ALB", "AUS"), id="league"),
]


@pytest.mark.parametrize("fixture, teams", GAME_CASES)
def test_a_seeded_game_is_invariant_to_a_league_wide_shift(tmp_path, fixture, teams):
    """The acceptance test, exact: the same pitch-by-pitch digest at full
    float precision, three seeded games per league."""
    on = _generation_5(**EXACT_CENTRES)
    plain = _play(_shifted_league(tmp_path / "plain", fixture), on, teams, SEEDS)
    want = _digest(plain)
    assert sum(len(g.pitch_log) for g in plain) > 600
    for delta in SHIFTS:
        for who in ("hitters", "pitchers"):
            name = f"{who}{delta:+.0f}"
            root = _shifted_league(tmp_path / name, fixture, **{who: delta})
            moved = _play(
                root, _shifted_centres(on, **{who: delta}), teams, SEEDS
            )
            assert _scores(moved) == _scores(plain), name
            assert _digest(moved) == want, name
    # Both at once, by different amounts.
    root = _shifted_league(tmp_path / "both", fixture, hitters=6.0, pitchers=-4.0)
    both = _play(
        root, _shifted_centres(on, hitters=6.0, pitchers=-4.0), teams, SEEDS
    )
    assert _digest(both) == want


def _pin_release_4_reader(monkeypatch, centres: dict) -> None:
    """Make the Release 4 running-game terms read ``centres``, whatever the
    game's tuning holds (the same arithmetic as ``engine._centred_rating``)."""
    monkeypatch.setattr(
        engine,
        "_centred_rating",
        lambda value, key, tuning: value - centres[key] + 50.0,
    )


@pytest.mark.parametrize("fixture, teams", GAME_CASES)
def test_the_plain_pitcher_means_act_only_through_the_release_4_terms(
    tmp_path, monkeypatch, fixture, teams
):
    """The shift reads the usage centres alone. The plain ACT means still
    move the Release 4 running-game terms (wild pitches, steals), which is
    their job, and nothing else in a generation 5 game."""
    on = _generation_5(**EXACT_CENTRES)
    root = _shifted_league(tmp_path / "plain", fixture)
    want = _digest(_play(root, on, teams, SEEDS))
    # The plain movement and pitch-grade means: nothing reads them.
    unread = dict(on)
    unread["pitcher_movement_center"] += 6.0
    unread["pitcher_grade_center"] -= 4.0
    assert _digest(_play(root, unread, teams, SEEDS)) == want
    # Every plain pitcher mean moved, with the Release 4 reader held on the
    # centres it had: the same game, so the shift did not read them.
    wild = dict(on)
    for key in PITCHER_PLAIN_CENTRES + ("pitcher_hold_center",):
        wild[key] += 6.0
    _pin_release_4_reader(monkeypatch, on)
    assert _digest(_play(root, wild, teams, SEEDS)) == want
    # Every pitcher 6 points better and only the USAGE centres following:
    # the pitch is the same pitch. (The Release 4 reader is given the plain
    # means such a league would have, which the tuning here does not hold.)
    better = _shifted_league(tmp_path / "better", fixture, pitchers=6.0)
    followed = dict(on)
    for key in PITCHER_USAGE_CENTRES:
        followed[key] += 6.0
    _pin_release_4_reader(monkeypatch, _shifted_centres(on, pitchers=6.0))
    assert _digest(_play(better, followed, teams, SEEDS)) == want
    monkeypatch.undo()
    # And the Release 4 terms do read the plain means, not the usage ones.
    assert engine._missed_pitch_rates(
        45.0, 50.0, 0.2, load_tuning(wild)
    ) != engine._missed_pitch_rates(45.0, 50.0, 0.2, load_tuning(on))
    assert engine._missed_pitch_rates(
        45.0, 50.0, 0.2, load_tuning(followed)
    ) == engine._missed_pitch_rates(45.0, 50.0, 0.2, load_tuning(on))


@pytest.mark.parametrize("fixture, teams", GAME_CASES)
def test_with_the_switch_off_the_same_shift_changes_the_game(tmp_path, fixture, teams):
    off = _generation_5(0.0, **EXACT_CENTRES)
    plain = _shifted_league(tmp_path / "plain", fixture)
    want = _digest(_play(plain, off, teams, SEEDS))
    for who in ("hitters", "pitchers"):
        root = _shifted_league(tmp_path / who, fixture, **{who: 6.0})
        moved = _play(root, _shifted_centres(off, **{who: 6.0}), teams, SEEDS)
        assert _digest(moved) != want, who


def test_a_series_with_workloads_is_invariant_too(tmp_path):
    """Eight games in a row on one usage state: tired pitchers, rested and
    worn relievers, tired hitters. Every outcome is identical and the floats
    agree to 1e-9 (a tired hitter's rating goes to league-relative and back,
    which rounds in the last place)."""
    on = _generation_5(**EXACT_CENTRES)
    teams = ("CAL01", "CAL02")
    seeds = tuple(range(11, 19))
    plain = _play(
        _shifted_league(tmp_path / "plain", CALIBRATION), on, teams, seeds, series=True
    )
    for who, delta in (("hitters", 6.0), ("pitchers", -4.0)):
        root = _shifted_league(tmp_path / who, CALIBRATION, **{who: delta})
        moved = _play(
            root, _shifted_centres(on, **{who: delta}), teams, seeds, series=True
        )
        assert _scores(moved) == _scores(plain), who
        _assert_same_games(moved, plain)


def test_invariance_with_a_leagues_real_centres(tmp_path):
    """The fixture's own two-decimal centres: 50 - 50.28 is not exact in
    binary, so the shifted league's ratings would differ in the last place.
    The shifted rating is rounded where it is made, so the games are still
    equal to the last bit."""
    real = centers.active_rating_centers(CALIBRATION)
    assert real["hitter_contact_center"] == 50.28
    on = _generation_5(**real)
    teams = ("CAL03", "CAL04")
    plain = _play(_shifted_league(tmp_path / "plain", CALIBRATION), on, teams, SEEDS)
    for who, delta in (("hitters", -4.0), ("pitchers", 6.0)):
        root = _shifted_league(tmp_path / who, CALIBRATION, **{who: delta})
        moved = _play(root, _shifted_centres(on, **{who: delta}), teams, SEEDS)
        assert _scores(moved) == _scores(plain), who
        assert _digest(moved) == _digest(plain), who
        # The shifted league's own centres are the plain league's plus the
        # constant: the centres follow the ratings.
        found = centers.active_rating_centers(root)
        for key in HITTER_CENTRES if who == "hitters" else PITCHER_CENTRES:
            assert found[key] == pytest.approx(real[key] + delta, abs=0.006), key


def test_a_shift_that_is_not_a_whole_number_breaks_no_near_tie(tmp_path):
    """The reviewer's case: calibration, real centres, pitchers +3.37 and
    +15, thirty games. Before the shifted rating was rounded, one game in
    thirty picked a different reliever: two arms' scores were 51.124 and
    51.123999999999995 in one league and the other way round in the other.
    """
    real = centers.active_rating_centers(CALIBRATION)
    on = _generation_5(**real)
    teams = ("CAL01", "CAL02")
    seeds = tuple(range(1, 31))
    plain = _play(_shifted_league(tmp_path / "plain", CALIBRATION), on, teams, seeds)
    want = [_digest([game]) for game in plain]
    for delta in (3.37, 15.0):
        root = _shifted_league(tmp_path / f"p{delta}", CALIBRATION, pitchers=delta)
        moved = _play(root, _shifted_centres(on, pitchers=delta), teams, seeds)
        got = [_digest([game]) for game in moved]
        different = [seed for seed, a, b in zip(seeds, got, want) if a != b]
        assert not different, (delta, different)
    # Hitters by a fraction too (their thresholds: the bunt, pitch selection).
    root = _shifted_league(tmp_path / "h", CALIBRATION, hitters=-2.63)
    moved = _play(root, _shifted_centres(on, hitters=-2.63), teams, seeds[:10])
    assert [_digest([game]) for game in moved] == want[:10]


def test_a_shifted_rating_is_rounded_where_it_is_made():
    # A 61 in a league centred on 50.28, and the same player in a league
    # 3.37 higher: 60.72 and 60.720000000000006 ...
    rating, centre, lift = 61.0, 50.28, 3.37
    a = rating + (50.0 - centre)
    b = (rating + lift) + (50.0 - (centre + lift))
    assert a != b and abs(a - b) < 1e-12
    # ... is one number once it is a league-relative rating.
    key = "hitter_contact_center"
    one = league_relative(rating, key, _centred(**{key: centre}))
    two = league_relative(rating + lift, key, _centred(**{key: centre + lift}))
    assert one == two == 60.72
    # Legacy: not rounded, not touched.
    raw = 63.000000000000014
    assert league_relative(raw, "hitter_contact_center", load_tuning()) == raw
    assert engine._league_relative(raw, "hitter_contact_center", None) == raw


def test_a_tie_between_candidates_goes_to_the_lower_player_id():
    on, off = _centred(), load_tuning()
    # Two scores a last bit apart are level under the switch.
    assert engine._choice_score(51.124, on) == engine._choice_score(
        51.123999999999995, on
    )
    assert engine._choice_score(51.123999999999995, off) == 51.123999999999995
    arms = [
        engine.PitcherState(pitcher=_pitcher(player_id=pid), staff_role="MR")
        for pid in ("P9", "P2", "P5")
    ]
    score = {"P9": 51.124, "P2": 51.124, "P5": 50.0}

    def of(state):
        return score[state.pitcher.player_id]

    # Legacy: the first of the level candidates in the list, as always.
    assert engine._pick_best(arms, of, engine._pitcher_state_id, off) is arms[0]
    assert engine._pick_best(arms, of, engine._pitcher_state_id, None) is arms[0]
    # Under the switch: the lower id, whatever order they were listed in.
    assert engine._pick_best(arms, of, engine._pitcher_state_id, on) is arms[1]
    assert (
        engine._pick_best(arms[::-1], of, engine._pitcher_state_id, on) is arms[1]
    )
    assert engine._least_worn(arms[:2], "mid", 0, on) is arms[1]
    assert engine._least_worn(arms[:2], "mid", 0, off) is arms[0]
    # The same for two level bench hitters.
    bench = [_batter(player_id="B7"), _batter(player_id="B3")]

    def level(_batter_):
        return 55.5

    assert engine._pick_best(bench, level, engine._batter_id, on) is bench[1]
    assert engine._pick_best(bench, level, engine._batter_id, off) is bench[0]


def test_the_scores_managers_choose_on_are_rounded_only_under_the_switch():
    centres = dict(
        hitter_contact_center=50.28, hitter_power_center=50.2,
        pitcher_control_usage_center=51.59, pitcher_movement_usage_center=52.52,
        pitcher_arm_usage_center=55.27,
    )
    on, off = _centred(**centres), _tuning(**centres)
    batter, pitcher = _batter(contact=61.0, power=47.0), _pitcher()
    relative = engine._batter_offense_score(batter, pitcher, on)
    assert relative == round(relative, 6)
    assert engine._rest_bench_value(batter, None, on) == round(
        (61.0 - 0.28) * 0.55 + (47.0 - 0.2) * 0.45, 6
    )
    # Legacy: the same floats as ever.
    assert engine._batter_offense_score(batter, pitcher, off) == (
        61.0 * 0.55 + 47.0 * 0.45 + engine._platoon_bonus(batter, pitcher, off)
    )
    assert engine._rest_bench_value(batter, None, off) == 61.0 * 0.55 + 47.0 * 0.45
    state = engine.PitcherState(
        pitcher=_pitcher(control=61.0, movement=57.0, arm=64.0),
        pregame_penalty=0.137,
    )
    score = engine._reliever_score(state, "high", score_diff=1, tuning=on)
    assert score == round(score, 6)
    legacy = engine._reliever_score(state, "high", score_diff=1, tuning=off)
    assert legacy == engine._reliever_score(state, "high", score_diff=1)
    assert legacy != round(legacy, 6)


# --- the pickoff ------------------------------------------------------------------


def test_the_pickoff_reads_hold_and_arm_through_the_release_4_reader():
    """It read both raw against 50: neither shifted nor centred, the one
    term that made a "pitchers +3" season diverge. Under the switch they
    are read against the plain ACT means, like the steal terms."""
    centres = dict(pitcher_hold_center=53.0, pitcher_arm_center=58.0)
    on, off = _centred(**centres), _tuning(**centres)
    kwargs = dict(speed=55.0, defense_arm=52.0)

    def success(hold, arm, tuning):
        return engine._pickoff_success_prob(
            pitcher_hold=hold, pitcher_arm=arm, tuning=tuning, **kwargs
        )

    def attempt(hold, tuning):
        return engine._pickoff_attempt_rate(
            speed=55.0, base_rate=0.004, pitcher_hold=hold, tuning=tuning
        )

    # Legacy: the raw ratings against 50, whatever the centres are.
    assert success(60.0, 66.0, off) == success(60.0, 66.0, load_tuning())
    assert attempt(60.0, off) == attempt(60.0, load_tuning())
    # Under the switch: the league's average pitcher is the old 50.
    assert success(53.0, 58.0, on) == success(50.0, 50.0, off)
    assert attempt(53.0, on) == attempt(50.0, off)
    # Invariant: every pitcher 3 better with the means 3 higher.
    higher = _centred(pitcher_hold_center=56.0, pitcher_arm_center=61.0)
    assert success(63.0, 69.0, higher) == success(60.0, 66.0, on)
    assert attempt(63.0, higher) == attempt(60.0, on)
    # The usage centres are the pitch's, not the pickoff's.
    other = _centred(**centres, pitcher_arm_usage_center=44.0)
    assert success(60.0, 66.0, other) == success(60.0, 66.0, on)


def test_a_game_full_of_pickoffs_is_invariant_to_the_pitchers_arms(tmp_path):
    """Pickoffs are rare (about one a club a season), so the ordinary
    invariance games never see one. Many more throws over, three times as
    likely to work, and the same shift. (With the pickoff reading the raw
    arm, as it did, the shifted games differ.)"""
    on = _generation_5(
        **EXACT_CENTRES, pickoff_freq_scale=40.0, pickoff_success_scale=3.0
    )
    teams = ("CAL07", "CAL08")
    seeds = tuple(range(1, 9))
    plain = _play(_shifted_league(tmp_path / "plain", CALIBRATION), on, teams, seeds)
    events = [
        str(entry.get("runner_event") or "")
        for game in plain
        for entry in game.pitch_log
    ]
    throws = [event for event in events if event.startswith("po")]
    # Enough throws, and enough of them successful, for the comparison to
    # mean something. The counts move with the profile's run environment
    # (4 to 6 successes over these eight games across retunes), so the floor
    # is a presence check, not a calibration.
    assert len(throws) >= 25
    assert len([event for event in throws if not event.startswith("poa")]) >= 3
    for delta in SHIFTS:
        root = _shifted_league(tmp_path / f"p{delta}", CALIBRATION, pitchers=delta)
        moved = _play(root, _shifted_centres(on, pitchers=delta), teams, seeds)
        assert _digest(moved) == _digest(plain), delta


def test_the_switch_is_one_shift_of_the_data(tmp_path):
    """Nothing is centred twice and nothing is missed: the switch on, with
    centres C, plays the same game as the switch OFF on data already moved
    by 50 - C with every centre at 50."""
    hitters = 50.0 - 51.5
    pitchers = 50.0 - 52.5
    centres = dict(EXACT_CENTRES)
    for key in HITTER_CENTRES:
        centres[key] = 51.5
    for key in PITCHER_CENTRES:
        centres[key] = 52.5
    teams = ("CAL05", "CAL06")
    on = _play(
        _shifted_league(tmp_path / "raw", CALIBRATION),
        _generation_5(**centres), teams, SEEDS,
    )
    moved = _shifted_league(
        tmp_path / "moved", CALIBRATION, hitters=hitters, pitchers=pitchers
    )
    flat = dict(centres)
    for key in HITTER_CENTRES + PITCHER_CENTRES:
        flat[key] = 50.0
    off = _play(moved, _generation_5(0.0, **flat), teams, SEEDS)
    assert _digest(on) == _digest(off)


# --- the terms around the pitch ---------------------------------------------------


def test_league_relative_reads_a_raw_rating_as_the_pitch_does():
    on = _tuning(centred_ratings=1, hitter_power_center=55.0)
    assert engine._league_relative(62.0, "hitter_power_center", on) == 57.0
    assert engine._league_relative(62.0, "hitter_power_center", load_tuning()) == 62.0
    assert engine._league_relative(62.0, "hitter_power_center", None) == 62.0


def test_the_bunt_reads_power_and_contact_league_relative(monkeypatch):
    bases = engine.BaseState(first=_batter(player_id="r"))
    slugger = _batter(power=62.0)
    kwargs = dict(bases=bases, batter=slugger, inning=3, outs=0, score_diff=0)
    # 62 Power in a 55 league is a 57: no longer a hitter managers will not
    # bunt with, so the full rate applies. A roll between the two rates
    # tells them apart.
    full = load_tuning().get("bunt_attempt_rate", 0.03)
    monkeypatch.setattr(engine.random, "random", lambda: full * 0.8)
    on = _tuning(centred_ratings=1, hitter_power_center=55.0)
    off = _tuning(hitter_power_center=55.0)
    assert engine._should_bunt(**kwargs, tuning=on) is True
    assert engine._should_bunt(**kwargs, tuning=off) is False
    assert engine._should_bunt(**kwargs, tuning=_centred()) is False


def test_the_offence_score_and_the_reliever_score_shift_with_the_league():
    pitcher = _pitcher()
    centres = dict(
        hitter_contact_center=54.0, hitter_power_center=52.0,
        pitcher_control_usage_center=53.0, pitcher_movement_usage_center=56.0,
        pitcher_arm_usage_center=59.0,
        # Not read: the manager's view follows the pitch's.
        pitcher_control_center=70.0, pitcher_arm_center=30.0,
    )
    on = _tuning(centred_ratings=1, **centres)
    off = _tuning(**centres)
    batter = _batter(contact=60.0, power=40.0)
    raw = engine._batter_offense_score(batter, pitcher, off)
    assert raw == engine._batter_offense_score(batter, pitcher, None)
    assert engine._batter_offense_score(batter, pitcher, on) == pytest.approx(
        raw - 4.0 * 0.55 - 2.0 * 0.45
    )
    state = engine.PitcherState(
        pitcher=_pitcher(control=60.0, movement=62.0, arm=64.0),
        pregame_penalty=0.25,
    )
    plain = engine._reliever_score(state, "mid", score_diff=0)
    assert engine._reliever_score(state, "mid", score_diff=0, tuning=off) == plain
    # stuff (62) drops by the mean of the three shifts (6); "mid" weighs it
    # 0.6, and the freshness factor (0.75) scales the whole score.
    assert engine._reliever_score(
        state, "mid", score_diff=0, tuning=on
    ) == pytest.approx(plain - 6.0 * 0.6 * 0.75)


def test_a_tired_hitter_loses_a_share_of_his_league_relative_rating(monkeypatch):
    monkeypatch.setattr(engine, "_batter_fatigue_penalty", lambda *a, **k: 0.25)
    batter = _batter(contact=60.0, power=70.0, eye=40.0, speed=60.0)
    centres = dict(
        hitter_contact_center=56.0, hitter_power_center=48.0,
        hitter_eye_center=52.0, batter_fatigue_offense_scale=0.8,
        batter_fatigue_eye_scale=0.4,
    )

    def tired(tuning, hitter=batter):
        (out,) = engine._apply_batter_fatigue(
            [hitter], usage_state=UsageState(), game_day=3, tuning=tuning
        )
        return out

    off = tired(_tuning(**centres))
    assert (off.contact, off.power, off.eye) == (48.0, 56.0, 36.0)
    on = tired(_tuning(centred_ratings=1, **centres))
    # (60 - 6) * 0.8 + 6, (70 + 2) * 0.8 - 2, (40 - 2) * 0.9 + 2.
    assert (on.contact, on.power, on.eye) == pytest.approx((49.2, 55.6, 36.2))
    assert on.speed == off.speed  # speed is not a centred rating
    # Invariant: a league 6 points higher loses the same league-relative
    # amount, so the plate appearance sees the same hitter.
    higher = tired(
        _tuning(
            centred_ratings=1,
            **{
                **centres, "hitter_contact_center": 62.0,
                "hitter_power_center": 54.0, "hitter_eye_center": 58.0,
            },
        ),
        _batter(contact=66.0, power=76.0, eye=46.0, speed=60.0),
    )
    assert (higher.contact, higher.power, higher.eye) == pytest.approx(
        (on.contact + 6.0, on.power + 6.0, on.eye + 6.0)
    )


def test_the_contact_hit_edge_still_reads_the_raw_rating_against_its_centre():
    centred = _tuning(
        centred_ratings=1, contact_babip_per10=0.005, hitter_contact_center=52.0
    )
    plain = _tuning(contact_babip_per10=0.005, hitter_contact_center=52.0)
    batter = _batter(contact=62.0)
    assert engine._contact_babip_edge(batter, centred) == pytest.approx(0.005)
    assert engine._contact_babip_edge(batter, centred) == engine._contact_babip_edge(
        batter, plain
    )


def test_release_4_terms_keep_reading_the_raw_rating_against_their_centre():
    centres = dict(
        pitcher_control_center=56.0, pitcher_arm_center=58.0,
        # The usage centres are the shift's, never these terms'.
        pitcher_control_usage_center=44.0, pitcher_arm_usage_center=66.0,
    )
    on = _tuning(centred_ratings=1, **centres)
    off = _tuning(**centres)
    for key, value in (("pitcher_control_center", 61.0), ("pitcher_arm_center", 49.0)):
        assert engine._centred_rating(value, key, on) == engine._centred_rating(
            value, key, off
        )
        assert engine._clipped_battery(value, key, on) == engine._clipped_battery(
            value, key, off
        )
    assert engine._centred_rating(61.0, "pitcher_control_center", on) == 55.0


# --- the legacy engine --------------------------------------------------------------


def test_the_legacy_engine_reads_none_of_it():
    """With the switch off (the defaults) the three hitter centres -- the
    ones this release redefines -- and the new Power and pitcher usage
    centres change nothing."""
    wild = {key: 71.0 for key in HITTER_CENTRES + PITCHER_USAGE_CENTRES}
    plain = _play(CALIBRATION, {}, ("CAL01", "CAL02"), SEEDS)
    moved = _play(CALIBRATION, wild, ("CAL01", "CAL02"), SEEDS)
    assert _digest(moved) == _digest(plain)
    tuning = _tuning(**wild, pitcher_grade_center=71.0, pitcher_movement_center=71.0)
    batter, pitcher = _batter(contact=61.0, power=43.0, eye=57.0), _pitcher()
    assert engine._batter_context(batter, pitcher, tuning) == engine._batter_context(
        batter, pitcher, load_tuning()
    )
    assert engine._pitcher_context(pitcher, tuning) == engine._pitcher_context(
        pitcher, load_tuning()
    )


# --- the hitter centres are the lineup regulars' ------------------------------------

PLAYER_FIELDS = [
    "player_id", "primary_position", "is_pitcher", "bats", "sp", "ch", "ph",
    "eye", "vl", "fa", "arm", "control", "movement", "hold_runner", "fb", "sl",
    "endurance", "role", "preferred_pitching_role",
]


def _hitter_row(pid, ch, ph, eye, **more):
    return {
        "player_id": pid, "primary_position": "CF", "is_pitcher": "0",
        "bats": "R", "ch": str(ch), "ph": str(ph), "eye": str(eye), **more,
    }


def _write_club(root: Path, team: str, players: list[dict], *, levels=None):
    (root / "rosters").mkdir(parents=True, exist_ok=True)
    levels = levels or {}
    with (root / "rosters" / f"{team}.csv").open(
        "w", newline="", encoding="utf-8"
    ) as fh:
        csv.writer(fh).writerows(
            (p["player_id"], levels.get(p["player_id"], "ACT")) for p in players
        )


def _write_players(root: Path, players: list[dict]):
    with (root / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PLAYER_FIELDS)
        writer.writeheader()
        for row in players:
            writer.writerow({key: row.get(key, "") for key in PLAYER_FIELDS})


def _write_lineup(root: Path, team: str, hand: str, ids):
    (root / "lineups").mkdir(parents=True, exist_ok=True)
    with (root / "lineups" / f"{team}_vs_{hand}.csv").open(
        "w", newline="", encoding="utf-8"
    ) as fh:
        writer = csv.writer(fh)
        writer.writerow(["order", "player_id", "position"])
        for order, pid in enumerate(ids, start=1):
            writer.writerow([order, pid, "DH"])


def _club(team: str) -> list[dict]:
    """Twelve ACT hitters: ch 40, 42 ... 62, ph ch + 10, eye ch - 10; the
    better the bat the higher the id, so the nine best are H3-H11."""
    return [
        _hitter_row(f"{team}H{i:02d}", 40 + 2 * i, 50 + 2 * i, 30 + 2 * i)
        for i in range(12)
    ]


def _regulars_league(root: Path) -> Path:
    """Club AAA with both lineups saved, club BBB with none."""
    root.mkdir(parents=True, exist_ok=True)
    aaa, bbb = _club("AAA"), _club("BBB")
    pitcher = {
        "player_id": "P1", "primary_position": "SP", "is_pitcher": "1",
        "bats": "R", "ch": "99", "ph": "99", "eye": "99", "control": "60",
        "movement": "55", "arm": "70", "fb": "65",
    }
    minor = _hitter_row("M1", 99, 99, 99)
    _write_players(root, aaa + bbb + [pitcher, minor])
    _write_club(root, "AAA", aaa + [pitcher])
    _write_club(root, "BBB", bbb + [minor], levels={"M1": "AAA"})
    ids = [p["player_id"] for p in aaa]
    # vs LHP: H00-H08 (the nine WORST bats); vs RHP: H00-H05 and H09-H11.
    _write_lineup(root, "AAA", "lhp", ids[:9])
    _write_lineup(root, "AAA", "rhp", ids[:6] + ids[9:])
    return root


def _mean(values) -> float:
    values = list(values)
    return round(sum(values) / len(values), 2)


# AAA: H00-H05 in both files (twice), H06-H11 in one. BBB: no lineup file,
# so its nine best (H03-H11), once per hand.
AAA_CH = [40 + 2 * i for i in range(6)] * 2 + [40 + 2 * i for i in range(6, 12)]
BBB_CH = [40 + 2 * i for i in range(3, 12)] * 2
REGULARS_CH = _mean(AAA_CH + BBB_CH)


def test_regulars_are_the_saved_lineups_and_the_nine_best_without_one(tmp_path):
    base = _regulars_league(tmp_path / "league")
    found = centers.active_rating_centers(base)
    # AAA 49.0 over its 18 lineup spots, BBB 54.0 over its 18.
    assert REGULARS_CH == 51.5
    assert found["hitter_contact_center"] == REGULARS_CH
    assert found["hitter_power_center"] == REGULARS_CH + 10.0
    assert found["hitter_eye_center"] == REGULARS_CH - 10.0
    # Every ACT hitter would be 51.0: the bench is in that mean, not in this.
    assert _mean([40 + 2 * i for i in range(12)]) == 51.0
    assert found["pitcher_control_center"] == 60.0
    # The speed centre and the batting-side figures are still every ACT
    # hitter's (24 of them).
    assert found["hitter_speed_center"] == 50.0
    assert found["hitter_bats_share_r"] == 1.0
    assert list(found) == [k for k in centers.RATING_CENTER_KEYS if k in found]
    assert not (base / centers.RATING_CENTERS_FILENAME).exists()
    assert sorted(p.name for p in (base / "lineups").iterdir()) == [
        "AAA_vs_lhp.csv", "AAA_vs_rhp.csv",
    ]


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param(lambda ids: ids[:8], id="eight hitters"),
        pytest.param(lambda ids: ids[:8] + ids[:1], id="a hitter twice"),
        pytest.param(lambda ids: ids[:8] + ["P1"], id="a pitcher"),
        pytest.param(lambda ids: ids[:8] + ["M1"], id="not on the roster"),
        pytest.param(lambda ids: ids[:8] + ["BBBH11"], id="another club's"),
    ],
)
def test_a_lineup_a_game_would_not_play_falls_back_for_that_hand(tmp_path, broken):
    base = _regulars_league(tmp_path / "league")
    ids = [f"AAAH{i:02d}" for i in range(12)]
    _write_lineup(base, "AAA", "lhp", broken(ids))
    found = centers.active_rating_centers(base)
    # vs LHP is now AAA's nine best (H03-H11); vs RHP is still its file.
    aaa = [40 + 2 * i for i in range(3, 12)] + [
        40 + 2 * i for i in (0, 1, 2, 3, 4, 5, 9, 10, 11)
    ]
    assert found["hitter_contact_center"] == _mean(aaa + BBB_CH)


def test_a_club_with_nine_hitters_or_fewer_counts_them_all(tmp_path):
    base = tmp_path / "league"
    base.mkdir()
    club = _club("AAA")[:7]
    _write_players(base, club)
    _write_club(base, "AAA", club)
    found = centers.active_rating_centers(base)
    assert found["hitter_contact_center"] == _mean(40 + 2 * i for i in range(7))


def test_the_nine_best_are_picked_by_lineup_value_not_by_file_order(tmp_path):
    base = tmp_path / "league"
    base.mkdir()
    club = _club("AAA")
    # The weakest bat is a burner with a gold glove and a cannon: he plays.
    club[0].update(sp="99", fa="99", arm="99")
    _write_players(base, club)
    _write_club(base, "AAA", list(reversed(club)))
    found = centers.active_rating_centers(base)
    assert found["hitter_contact_center"] == _mean(
        [40] + [40 + 2 * i for i in range(4, 12)]
    )


def test_a_league_without_hitters_has_no_hitter_centres(tmp_path):
    base = tmp_path / "league"
    base.mkdir()
    pitcher = {
        "player_id": "P1", "primary_position": "SP", "is_pitcher": "1",
        "control": "60", "fb": "65",
    }
    _write_players(base, [pitcher])
    _write_club(base, "AAA", [pitcher])
    found = centers.active_rating_centers(base)
    assert found["pitcher_control_center"] == 60.0
    assert not set(found) & set(HITTER_CENTRES)


# --- the pitcher usage centres weigh a starter 2.5 times a reliever -----------------


def _arm(pid, *, control, movement, endurance, **pitches):
    # A stale stored role ("RP" for every arm, as in an older league) and a
    # plain "P" position: neither says who starts.
    return {
        "player_id": pid, "primary_position": "P", "is_pitcher": "1",
        "bats": "R", "role": "RP", "control": str(control),
        "movement": str(movement), "arm": "55", "endurance": str(endurance),
        **{pitch: str(grade) for pitch, grade in pitches.items()},
    }


def _staff_league(root: Path, *, staff_file: bool = True) -> Path:
    """One club, eight ACT arms. S1-S5 are the staff file's SP1-SP5
    (control 60, movement 40, one 70 pitch, endurance 30); R1-R3 its
    closer, setup man and middle reliever (control 40, movement 60, pitches
    50 and 30, endurance 90). A minor leaguer the file also calls SP1."""
    root.mkdir(parents=True, exist_ok=True)
    starters = [
        _arm(f"S{i}", control=60, movement=40, endurance=30, fb=70)
        for i in range(1, 6)
    ]
    relievers = [
        _arm(f"R{i}", control=40, movement=60, endurance=90, fb=50, sl=30)
        for i in range(1, 4)
    ]
    minor = _arm("M9", control=99, movement=99, endurance=99, fb=99)
    _write_players(root, starters + relievers + [minor])
    _write_club(root, "AAA", starters + relievers + [minor], levels={"M9": "AAA"})
    if staff_file:
        rows = [("M9", "SP1")] + [(f"S{i}", f"SP{i}") for i in range(1, 6)]
        rows += [("R1", "CL"), ("R2", "SU"), ("R3", "MR1")]
        with (root / "rosters" / "AAA_pitching.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            csv.writer(fh).writerows(rows)
    return root


def _weighted(starters: float, n_starters: int, relievers: float, n_relievers: int):
    heavy = 2.5 * n_starters
    return round(
        (heavy * starters + n_relievers * relievers) / (heavy + n_relievers), 2
    )


def test_usage_centres_weigh_the_staff_files_rotation(tmp_path):
    base = _staff_league(tmp_path / "league")
    found = centers.active_rating_centers(base)
    # Five starters at 2.5 and three relievers at 1.
    assert found["pitcher_control_usage_center"] == _weighted(60, 5, 40, 3) == 56.13
    assert found["pitcher_movement_usage_center"] == _weighted(40, 5, 60, 3) == 43.87
    assert found["pitcher_grade_usage_center"] == _weighted(70, 5, 40, 3) == 64.19
    assert found["pitcher_arm_usage_center"] == 55.0
    # The plain ACT means are what they were: every arm counts once.
    assert found["pitcher_control_center"] == 52.5
    assert found["pitcher_movement_center"] == 47.5
    assert found["pitcher_grade_center"] == 58.75
    assert found["pitcher_arm_center"] == 55.0
    assert list(found)[-4:] == list(centers.PITCHER_USAGE_CENTER_KEYS)
    assert list(centers.RATING_CENTER_KEYS)[-4:] == list(
        centers.PITCHER_USAGE_CENTER_KEYS
    )


def test_a_club_with_no_staff_file_gets_the_rotation_a_game_would_build(tmp_path):
    base = _staff_league(tmp_path / "league", staff_file=False)
    # No file: utils.rotation.staff_rotation fills the five from the arms
    # that can start (endurance above 55: R1-R3), then by endurance (S1, S2
    # on the id). S3-S5 are the relievers.
    found = centers.active_rating_centers(base)
    control = round((2.5 * (3 * 40 + 2 * 60) + 3 * 60) / 15.5, 2)
    assert found["pitcher_control_usage_center"] == control == 50.32
    assert found["pitcher_control_center"] == 52.5
    # The same five the engine's own staff builder starts.
    from physics_sim.data_loader import load_players_by_id
    from physics_sim.team_data import build_staff

    _batters, pitchers = load_players_by_id(base / "players.csv")
    act = {pid for pid in pitchers if pid != "M9"}
    _ordered, roles, _missing = build_staff([], pitchers, active_ids=act)
    assert {pid for pid, role in roles.items() if role.startswith("SP")} == {
        "R1", "R2", "R3", "S1", "S2",
    }


def test_a_declared_role_beats_endurance_and_the_stored_role_is_not_read(tmp_path):
    base = _staff_league(tmp_path / "league", staff_file=False)
    with (base / "players.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        # The stored column now says the opposite of the declared role.
        if row["player_id"].startswith("S"):
            row.update(preferred_pitching_role="SP", role="RP")
        elif row["player_id"].startswith("R"):
            row.update(preferred_pitching_role="CL", role="SP")
    _write_players(base, rows)
    found = centers.active_rating_centers(base)
    assert found["pitcher_control_usage_center"] == 56.13


def test_fixture_usage_centres_sit_between_starters_and_the_plain_mean():
    cal = centers.active_rating_centers(CALIBRATION)
    assert [cal[key] for key in centers.PITCHER_USAGE_CENTER_KEYS] == [
        51.59, 52.52, 54.87, 55.27,
    ]
    league = centers.active_rating_centers(CALIBRATION_LEAGUE)
    assert [league[key] for key in centers.PITCHER_USAGE_CENTER_KEYS] == [
        53.41, 55.43, 57.17, 57.72,
    ]
    # The league fixture's relievers out-rate its starters: the usage
    # centres are well under the plain means (59.66 arm, 56.41 movement).
    assert league["pitcher_arm_center"] - league["pitcher_arm_usage_center"] > 1.5
    assert league["pitcher_movement_center"] > league["pitcher_movement_usage_center"]


def test_fixture_centres_are_the_regulars():
    cal = centers.active_rating_centers(CALIBRATION)
    assert (
        cal["hitter_contact_center"], cal["hitter_eye_center"],
        cal["hitter_power_center"],
    ) == (50.28, 50.33, 50.2)
    league = centers.active_rating_centers(CALIBRATION_LEAGUE)
    assert (
        league["hitter_contact_center"], league["hitter_eye_center"],
        league["hitter_power_center"],
    ) == (51.13, 50.37, 50.92)
    # Nothing else moved (the Release 4 and 5a values).
    assert cal["hitter_speed_center"] == 47.72
    assert cal["pitcher_control_center"] == 51.31
    assert cal["pitcher_movement_center"] == 52.96
    assert cal["pitcher_arm_center"] == 55.83
    assert cal["pitcher_grade_center"] == 54.76
    assert cal["hitter_vl_center_l"] == 49.86
    assert league["hitter_speed_center"] == 54.41
    assert league["pitcher_arm_center"] == 59.66
    assert league["catcher_fa_center"] == 56.35
    assert league["hitter_bats_share_r"] == 0.6513


def _stored(base: Path) -> dict:
    return json.loads((base / centers.RATING_CENTERS_FILENAME).read_text())


def test_a_new_season_entry_holds_the_three_regulars_centres(tmp_path):
    base = _regulars_league(tmp_path / "league")
    found = centers.league_rating_centers(base, season="2027")
    assert found["hitter_contact_center"] == REGULARS_CH
    assert found["hitter_power_center"] == REGULARS_CH + 10.0
    # One ACT pitcher: his usage centres are his ratings.
    assert found["pitcher_control_usage_center"] == 60.0
    assert found["pitcher_arm_usage_center"] == 70.0
    assert found["pitcher_grade_usage_center"] == 65.0
    assert _stored(base)["seasons"]["2027"] == found
    assert list(found)[-4:] == list(centers.PITCHER_USAGE_CENTER_KEYS)
    # Fixed for the season: a new lineup does not move them.
    _write_lineup(base, "BBB", "lhp", [f"BBBH{i:02d}" for i in range(9)])
    assert centers.league_rating_centers(base, season="2027") == found
    centers.clear_rating_center_cache()
    assert centers.league_rating_centers(base, season="2027") == found


def test_an_existing_season_entry_is_not_recomputed_and_gains_no_key(tmp_path):
    base = _regulars_league(tmp_path / "league")
    # A season fixed before this release: ACT-mean Contact and Eye centres
    # (values the rosters would not reproduce) and no Power centre.
    entry = {
        "hitter_speed_center": 47.25, "pitcher_control_center": 53.5,
        "pitcher_hold_center": 51.25, "pitcher_arm_center": 59.5,
        "hitter_contact_center": 48.81, "hitter_eye_center": 48.41,
        "pitcher_movement_center": 52.96, "pitcher_grade_center": 54.76,
        "hitter_vl_center_l": 49.86, "hitter_vl_center_r": 49.05,
        "hitter_vl_center_s": 49.35, "hitter_bats_share_l": 0.3846,
        "hitter_bats_share_r": 0.5128, "hitter_bats_share_s": 0.1026,
    }
    path = base / centers.RATING_CENTERS_FILENAME
    path.write_text(json.dumps({"version": 1, "seasons": {"2026": entry}}, indent=2))
    before = path.read_bytes()
    new_keys = {"hitter_power_center", *PITCHER_USAGE_CENTRES}
    for _ in range(2):
        found = centers.league_rating_centers(base, season="2026")
        assert found == entry
        assert not new_keys & set(found)
        assert path.read_bytes() == before
        centers.clear_rating_center_cache()
    assert centers.league_rating_centers(base, season="2026", store=False) == entry
    # The engine reads the default for the missing centres.
    for key in new_keys:
        assert load_tuning(found).get(key) == 50.0
    # The file is not re-read for them game after game.
    centers.league_rating_centers(base, season="2026")
    path.unlink()
    assert centers.league_rating_centers(base, season="2026") == entry


# (What a generation 5 season's entry gains, and when its Release 5 centres
# are recomputed, is tests/test_r5_centred_entries.py.)


def test_an_entry_holding_only_the_generation_gains_all_three_together(tmp_path):
    base = _regulars_league(tmp_path / "league")
    path = base / centers.RATING_CENTERS_FILENAME
    path.write_text(
        json.dumps({"version": 1, "seasons": {"2027": {"engine_generation": 5}}})
    )
    found = centers.league_rating_centers(base, season="2027")
    assert found["hitter_contact_center"] == REGULARS_CH
    assert found["hitter_power_center"] == REGULARS_CH + 10.0
    assert set(PITCHER_USAGE_CENTRES) <= set(found)
    stored = _stored(base)["seasons"]["2027"]
    assert stored["engine_generation"] == 5
    assert stored[centers.CENTERS_VERSION_KEY] == centers.CENTERS_VERSION
    assert {key: stored[key] for key in found} == found


def test_store_false_reads_the_regulars_live_and_writes_nothing(tmp_path):
    base = _regulars_league(tmp_path / "league")
    found = centers.league_rating_centers(base, season="2027", store=False)
    assert found["hitter_power_center"] == REGULARS_CH + 10.0
    assert not (base / centers.RATING_CENTERS_FILENAME).exists()


# --- the KPI harness ----------------------------------------------------------------


def test_the_harness_plays_a_fixture_on_its_regulars_centres():
    from scripts import physics_sim_season_kpis as kpis

    assert kpis.RATING_CENTER_KEYS == centers.RATING_CENTER_KEYS
    for fixture in (CALIBRATION, CALIBRATION_LEAGUE):
        merged = kpis.with_rating_centers({}, fixture / "players.csv", fixture)
        assert merged == centers.active_rating_centers(fixture)
        assert CENTRED_RATING_KEYS <= set(merged)
    # A centre pinned in the overrides still wins.
    pinned = kpis.with_rating_centers(
        {"hitter_power_center": 44.0}, CALIBRATION / "players.csv", CALIBRATION
    )
    assert pinned["hitter_power_center"] == 44.0


def test_the_matchup_grid_pins_every_centre_the_switch_reads():
    from scripts import kpi_extras as kx

    assert COVERED_KEYS <= set(kx.GRID_RATING_CENTERS)
    grades = {"pitcher_grade_center", "pitcher_grade_usage_center"}
    for key in COVERED_KEYS - grades:
        assert kx.GRID_RATING_CENTERS[key] == 50.0, key
    for key in grades:
        assert kx.GRID_RATING_CENTERS[key] == kx.GRID_PITCH_GRADE
    # A grid cell goes through the engine's own contexts, so under the
    # switch its pitches are the league-average 50 pitch.
    seen = []
    real = physics.simulate_pitch

    def spy(**kwargs):
        seen.append(dict(kwargs["pitcher"]))
        return real(**kwargs)

    from physics_sim.park import load_park

    tuning = load_tuning({**_generation_5(), **kx.GRID_RATING_CENTERS})
    original = physics.simulate_pitch
    physics.simulate_pitch = spy
    state = random.getstate()
    try:
        kx._simulate_cell(
            contact=50.0, power=50.0, pitcher_level=50.0, n=5, seed=3,
            tuning=tuning, park=load_park(None),
        )
    finally:
        physics.simulate_pitch = original
        random.setstate(state)
    assert seen and all(
        set(p["repertoire"].values()) == {50.0} and p["velocity"] == 93.0
        for p in seen
    )
    assert centred_ratings.ratings_centred(tuning)
