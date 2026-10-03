"""Pinch-run for the run that decides the game, not for every slow runner.

An owner reported bench players used almost every game -- 49 G / 25 AB / 16 SB,
43 G / 11 AB / 10 SB. The rule replaced any runner slower than 55 with any
bench player 8+ faster, from the 7th inning on, whenever the score was "within
two" -- and it checked that one-sidedly (``score_diff > 2``), so a team
trailing 9-1 still pinch-ran. Measured over 20 sim days of the live league,
bench appearances fell from 2.16 to 0.94 per team-game once the runner had to
be the tying or go-ahead run.
"""

import pytest

from physics_sim.engine import _runner_is_tying_or_go_ahead as matters


# --- whose run is it? ------------------------------------------------------


def test_tied_the_lead_runner_is_the_go_ahead_run():
    assert matters(score_diff=0, runners_ahead=0) is True


def test_tied_a_trailing_runner_is_only_an_insurance_run():
    assert matters(score_diff=0, runners_ahead=1) is False


def test_down_one_the_lead_runner_ties_and_the_next_goes_ahead():
    assert matters(score_diff=-1, runners_ahead=0) is True
    assert matters(score_diff=-1, runners_ahead=1) is True
    assert matters(score_diff=-1, runners_ahead=2) is False


def test_down_two_the_lead_runner_does_not_tie_it():
    """He only cuts it to one; the runner behind him is the tying run."""
    assert matters(score_diff=-2, runners_ahead=0) is False
    assert matters(score_diff=-2, runners_ahead=1) is True


# --- the regression --------------------------------------------------------


def test_a_blowout_deficit_never_pinch_runs():
    """The old one-sided check: trailing 9-1, every slow runner was replaced."""
    for ahead in range(3):
        assert matters(score_diff=-8, runners_ahead=ahead) is False


@pytest.mark.parametrize("lead", [1, 2, 5])
def test_a_team_in_front_never_pinch_runs(lead):
    """No runner on a leading team is the tying or go-ahead run."""
    for ahead in range(3):
        assert matters(score_diff=lead, runners_ahead=ahead) is False


# --- the selection still honours its other rules ---------------------------


class _B:
    def __init__(self, pid, speed):
        self.player_id = pid
        self.speed = speed


@pytest.fixture
def select(monkeypatch):
    import physics_sim.engine as E

    bench = [_B("fast", 80), _B("medium", 60)]
    monkeypatch.setattr(E, "_available_bench", lambda state: list(bench))
    tuning = {
        "pinch_run_inning": 7.0,
        "pinch_run_speed_min": 55.0,
        "pinch_run_speed_diff": 8.0,
    }

    def run(*, runner_speed=40, inning=9, score_diff=-1, runners_ahead=0):
        picked = E._select_pinch_runner(
            lineup_state=object(),
            runner=_B("slow", runner_speed),
            inning=inning,
            score_diff=score_diff,
            tuning=tuning,
            runners_ahead=runners_ahead,
        )
        return picked.player_id if picked else None

    return run


def test_the_tying_run_late_gets_the_fastest_bench_player(select):
    assert select() == "fast"


def test_not_before_the_seventh(select):
    assert select(inning=6) is None


def test_a_fast_runner_is_left_alone(select):
    assert select(runner_speed=70) is None


def test_trailing_big_late_is_left_alone(select):
    assert select(score_diff=-6) is None


def test_leading_late_is_left_alone(select):
    assert select(score_diff=1) is None
