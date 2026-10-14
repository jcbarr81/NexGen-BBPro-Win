"""Release 6a, pitching (plan 2.1, part D): how a pitcher tires.

``fatigue_model`` 0 is the engine as it was: control, movement and velocity
are multiplied by factors that fall with the fatigue penalty. Model 1 takes
points and miles per hour off instead, the same for every pitcher, and adds
a loss of stuff (pitch quality) -- every coefficient a registered key.

* off: the factors are the old ones and a game hands the pitch what it
  always handed it (the whole-game digests are in
  tests/test_r6a_pitching_group.py);
* on: the losses by penalty, what the engine hands the pitch through a real
  game, and what a tired fastball looks like.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.data_loader import load_players_by_id
from physics_sim.engine_generation import engine_profile
from scripts import physics_sim_season_kpis as kpis

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
# The coefficients as registered: the owner's moderate set (decision 3).
COEFFICIENTS = {
    "fatigue_control_points": 3.0,
    "fatigue_movement_points": 1.5,
    "fatigue_stuff_points": 1.0,
    "fatigue_velocity_mph": 1.5,
}
FATIGUE_ON = {"fatigue_model": 1.0, **COEFFICIENTS}


def _g5_overrides(**extra) -> dict:
    return kpis.with_rating_centers(
        {**engine_profile(5), **extra}, CALIBRATION / "players.csv", CALIBRATION
    )


# --- registration and the formula ------------------------------------------------


def test_fatigue_keys_are_registered_off_with_the_moderate_set():
    assert DEFAULT_TUNING["fatigue_model"] == 0.0
    for key, value in COEFFICIENTS.items():
        assert DEFAULT_TUNING[key] == value, key
    tuning = load_tuning({key: 9.0 for key in FATIGUE_ON})
    assert all(tuning.get(key) == 9.0 for key in FATIGUE_ON)


def test_the_old_factors_are_untouched():
    assert engine._fatigue_factors(0.0) == (1.0, 1.0, 1.0)
    assert engine._fatigue_factors(0.85) == (
        1.0 - 0.15 * 0.85, 1.0 - 0.30 * 0.85, 1.0 - 0.25 * 0.85
    )
    assert engine._fatigue_factors(1.5) == (0.85, 0.60, 0.65)


def test_losses_are_linear_in_the_penalty_and_read_their_keys():
    tuning = load_tuning()
    assert engine._fatigue_losses(0.0, tuning) == (0.0, 0.0, 0.0, 0.0)
    assert engine._fatigue_losses(1.0, tuning) == (3.0, 1.5, 1.0, 1.5)
    # The fastball is down about 1.3 mph at the penalty of pitches 91-105.
    control, movement, stuff, velocity = engine._fatigue_losses(0.85, tuning)
    assert velocity == pytest.approx(1.275)
    assert (control, movement, stuff) == pytest.approx((2.55, 1.275, 0.85))
    # Left in to the cap: 2.25 mph, never the old 14.
    assert engine._fatigue_losses(1.5, tuning)[3] == pytest.approx(2.25)
    custom = load_tuning(
        {"fatigue_control_points": 4.0, "fatigue_movement_points": 2.0,
         "fatigue_stuff_points": 0.5, "fatigue_velocity_mph": 1.0}
    )
    assert engine._fatigue_losses(0.5, custom) == (2.0, 1.0, 0.25, 0.5)


def test_a_good_pitcher_and_a_poor_one_lose_the_same():
    """The old factors took the most from the best: 30% of a 70 control is
    21 points, of a 40 control 12. The losses are the same for both."""
    command_factor = engine._fatigue_factors(1.0)[1]
    assert 70.0 * (1.0 - command_factor) == pytest.approx(21.0)
    assert 40.0 * (1.0 - command_factor) == pytest.approx(12.0)
    assert engine._fatigue_losses(1.0, load_tuning())[0] == 3.0


# --- the pitch reads the losses --------------------------------------------------


def test_the_pitch_takes_the_velocity_loss_off_every_pitch_type(monkeypatch):
    tuning = load_tuning()
    monkeypatch.setattr(physics.random, "random", lambda: 0.999)
    fresh = {"repertoire": {"cb": 50.0}, "velocity": 93.0}
    tired = dict(fresh, velocity_loss=1.5)
    fast = physics.simulate_pitch(
        batter={"contact": 50.0}, pitcher=fresh, tuning=tuning, count=(0, 0)
    )
    slow = physics.simulate_pitch(
        batter={"contact": 50.0}, pitcher=tired, tuning=tuning, count=(0, 0)
    )
    assert fast.pitch_type == slow.pitch_type == "cb"
    assert fast.velocity == 93.0 - 11.0
    assert slow.velocity == 93.0 - 1.5 - 11.0


# --- what a game hands the pitch -------------------------------------------------


def _traced_game(monkeypatch, overrides, seed):
    """Play CAL01 at CAL02 recording what every pitch was given."""
    pitches: list[dict] = []
    fresh_values: list[float] = []
    real_pitch = engine.simulate_pitch
    real_fresh = engine._reliever_fresh_bonus

    def fresh(**kwargs):
        value = real_fresh(**kwargs)
        fresh_values.append(value)
        return value

    def pitch(**kwargs):
        pitches.append({**kwargs["pitcher"], "fresh": fresh_values[-1]})
        return real_pitch(**kwargs)

    monkeypatch.setattr(engine, "_reliever_fresh_bonus", fresh)
    monkeypatch.setattr(engine, "simulate_pitch", pitch)
    try:
        result = engine.simulate_matchup_from_files(
            away_team="CAL01", home_team="CAL02", base_dir=CALIBRATION,
            players_path=CALIBRATION / "players.csv", seed=seed,
            tuning_overrides=overrides,
        )
    finally:
        monkeypatch.undo()
    entries = [e for e in result.pitch_log if "pitch_count" in e]
    assert len(entries) == len(pitches)
    return result, entries, pitches


def test_model_0_hands_the_pitch_the_old_factors(monkeypatch):
    _batters, pitchers_by_id = load_players_by_id(CALIBRATION / "players.csv")
    tired = 0
    for overrides in (None, _g5_overrides()):
        tuning = load_tuning(overrides)
        _result, entries, pitches = _traced_game(monkeypatch, overrides, 2)
        for entry, pitch in zip(entries, pitches):
            rating = pitchers_by_id[entry["pitcher_id"]]
            velocity, command, movement = engine._fatigue_factors(
                entry["fatigue_penalty"]
            )
            control_rel = engine._league_relative(
                rating.control, "pitcher_control_usage_center", tuning
            )
            movement_rel = engine._league_relative(
                rating.movement, "pitcher_movement_usage_center", tuning
            )
            assert pitch["control"] == pytest.approx(
                (control_rel + pitch["fresh"]) * command
            )
            assert pitch["movement"] == pytest.approx(
                (movement_rel + pitch["fresh"]) * movement
            )
            assert pitch["fatigue_factor"] == velocity
            # Nothing of model 1 reaches the pitch.
            assert "velocity_loss" not in pitch and "stuff_loss" not in pitch
            tired += entry["fatigue_penalty"] > 0.0
    assert tired >= 20


def test_model_1_hands_the_pitch_the_losses(monkeypatch):
    _batters, pitchers_by_id = load_players_by_id(CALIBRATION / "players.csv")
    overrides = _g5_overrides(**FATIGUE_ON, reliever_fresh_bonus=1.7)
    tuning = load_tuning(overrides)
    tired = fresh_and_tired = 0
    worst = 0.0
    for seed in (1, 2, 3):
        _result, entries, pitches = _traced_game(monkeypatch, overrides, seed)
        for entry, pitch in zip(entries, pitches):
            penalty = entry["fatigue_penalty"]
            rating = pitchers_by_id[entry["pitcher_id"]]
            control_rel = engine._league_relative(
                rating.control, "pitcher_control_usage_center", tuning
            )
            movement_rel = engine._league_relative(
                rating.movement, "pitcher_movement_usage_center", tuning
            )
            # The fresh-arm bonus first, then the points off.
            assert pitch["control"] == pytest.approx(
                control_rel + pitch["fresh"] - 3.0 * penalty
            )
            assert pitch["movement"] == pytest.approx(
                movement_rel + pitch["fresh"] - 1.5 * penalty
            )
            assert pitch["fatigue_factor"] == 1.0
            assert pitch["velocity_loss"] == pytest.approx(1.5 * penalty)
            assert pitch["stuff_loss"] == pytest.approx(penalty)
            # What the log shows: the fastball is his own, less the loss.
            if entry["pitch_type"] == "fb":
                assert entry["velocity"] == pytest.approx(
                    pitch["velocity"] - 1.5 * penalty
                )
            tired += penalty > 0.0
            fresh_and_tired += penalty > 0.0 and pitch["fresh"] > 0.0
            worst = max(worst, penalty)
    assert tired >= 60
    assert 0.5 < worst <= 1.5
    # Nobody is taken below the cap's loss: 4.5 points and 2.25 mph.
    assert all(p["velocity_loss"] <= 2.25 + 1e-9 for p in pitches)


def test_a_tired_fastball_fades_a_mile_or_two_not_twelve(monkeypatch):
    """Pitches 91-105 of a start: the fastball is down 1 to 2 mph under
    model 1, where the old factor took 9 to 14."""

    def late_fade(overrides):
        drops = []
        for seed in range(1, 41):
            _result, entries, pitches = _traced_game(monkeypatch, overrides, seed)
            for entry, pitch in zip(entries, pitches):
                if entry["pitch_type"] == "fb" and 91 <= entry["pitch_count"] <= 105:
                    drops.append(pitch["velocity"] - entry["velocity"])
        assert len(drops) >= 15
        return sum(drops) / len(drops)

    assert 9.0 < late_fade(_g5_overrides()) < 14.5
    assert 0.8 < late_fade(_g5_overrides(**FATIGUE_ON)) < 2.25
