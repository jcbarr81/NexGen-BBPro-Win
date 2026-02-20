import random

from models.pitcher import Pitcher
from models.player import Player
from playbalance.player_development import (
    TrainingWeights,
    apply_training_plan,
    build_training_plan,
    execute_training_cycle,
)


def _hitter(**overrides) -> Player:
    data = dict(
        player_id="p-1",
        first_name="Devo",
        last_name=" Prospect",
        birthdate="2002-07-16",
        height=74,
        weight=205,
        bats="L",
        primary_position="1B",
        other_positions=[],
        gf=30,
        ch=45,
        ph=70,
        sp=55,
        eye=50,
        sc=40,
        fa=60,
        arm=55,
        pot_ch=75,
        pot_ph=72,
        pot_sp=60,
        pot_eye=55,
    )
    data.update(overrides)
    return Player(**data)


def _pitcher(**overrides) -> Pitcher:
    data = dict(
        player_id="pi-1",
        first_name="Dev",
        last_name=" Pitch",
        birthdate="1996-02-10",
        height=74,
        weight=210,
        bats="R",
        primary_position="P",
        other_positions=[],
        gf=30,
        endurance=92,
        control=90,
        movement=88,
        hold_runner=80,
        role="SP",
        preferred_pitching_role="starter",
        fb=60,
        cu=0,
        cb=0,
        sl=0,
        si=0,
        scb=0,
        kn=0,
        arm=90,
        fa=94,
    )
    data.update(overrides)
    return Pitcher(**data)


def test_build_plan_targets_contact_gap() -> None:
    player = _hitter(ch=40, pot_ch=80, ph=78, pot_ph=78)
    plan = build_training_plan(player)
    assert plan.focus == "Barrel Control"
    report = apply_training_plan(player, plan)
    assert any(attr in report.changes for attr in ("ch", "vl", "pl"))
    assert sum(report.changes.values()) > 0


def test_training_plan_respects_potential_ceiling() -> None:
    player = _hitter(ch=68, pot_ch=70, ph=85, pot_ph=85)
    plan = build_training_plan(player)
    report = apply_training_plan(player, plan)
    assert player.ch <= 70


def test_pitch_lab_plan_boosts_single_pitch() -> None:
    pitcher = _pitcher()
    plan = build_training_plan(pitcher)
    assert plan.focus == "Pitch Design"
    random.seed(0)
    before = pitcher.fb
    report = apply_training_plan(pitcher, plan)
    assert report.changes
    assert "fb" in report.changes
    assert pitcher.fb == int(round(before * 1.35))


def test_execute_training_cycle_returns_reports() -> None:
    players = [_hitter(player_id="p-1"), _hitter(player_id="p-2", bats="R")]
    reports = execute_training_cycle(players)
    assert len(reports) == len(players)


def test_training_weights_bias_focus_selection() -> None:
    player = _hitter(player_id="p-bias", ch=70, pot_ch=74, ph=60, pot_ph=90)
    weights = TrainingWeights(
        hitters={
            "contact": 5,
            "power": 55,
            "speed": 10,
            "discipline": 15,
            "defense": 15,
        },
        pitchers={
            "command": 25,
            "movement": 20,
            "stamina": 20,
            "velocity": 20,
            "hold": 5,
            "pitch_lab": 10,
        },
    )
    plan = build_training_plan(player, weights=weights)
    assert plan.focus == "Strength & Lift"


def test_apply_training_plan_scales_with_intensity_multiplier() -> None:
    low_player = _hitter(player_id="p-low", ch=40, pot_ch=95, ph=40, pot_ph=95)
    high_player = _hitter(player_id="p-high", ch=40, pot_ch=95, ph=40, pot_ph=95)

    low_plan = build_training_plan(low_player)
    high_plan = build_training_plan(high_player)
    low_report = apply_training_plan(low_player, low_plan, intensity_multiplier=0.8)
    high_report = apply_training_plan(high_player, high_plan, intensity_multiplier=1.25)

    assert sum(high_report.changes.values()) >= sum(low_report.changes.values())
