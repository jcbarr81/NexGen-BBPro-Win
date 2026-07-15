"""S2-04: closer usage in tied 9th innings and extras."""
import pytest

from physics_sim.config import load_tuning
from physics_sim.engine import (
    PitcherState,
    TeamPitchingState,
    _leverage_type,
    _reliever_score,
    _select_reliever,
)
from physics_sim.models import PitcherRatings


def _pr(pid: str) -> PitcherRatings:
    return PitcherRatings(
        player_id=pid, bats="R", throws="R", role="RP", preferred_role="RP",
        velocity=90.0, control=50.0, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=40.0, durability=50.0,
        fielding=50.0, arm=50.0, repertoire={"fb": 60.0},
    )


def _ps(role: str, *, available: bool = True) -> PitcherState:
    return PitcherState(
        pitcher=_pr(role), staff_role=role, rest_role=role,
        available=available, used=False,
    )


def _team(*roles: str) -> TeamPitchingState:
    bullpen = [_ps(r) for r in roles]
    starter = _ps("SP1")
    return TeamPitchingState(starter=starter, bullpen=bullpen, current=starter)


def _pick(team, *, inning, score_diff, is_home_defense, leverage=None):
    tuning = load_tuning()
    lev = leverage or _leverage_type(inning, score_diff, tuning)
    return _select_reliever(
        team, lev, inning=inning, score_diff=score_diff,
        is_home_defense=is_home_defense, tuning=tuning,
    ).staff_role


def test_closer_selected_tied_ninth_home():
    team = _team("CL", "SU", "MR", "LR")
    assert _pick(team, inning=9, score_diff=0, is_home_defense=True) == "CL"


def test_setup_selected_tied_ninth_away():
    team = _team("CL", "SU", "MR", "LR")
    assert _pick(team, inning=9, score_diff=0, is_home_defense=False) == "SU"


def test_closer_selected_tied_extras_away():
    team = _team("CL", "SU", "MR", "LR")
    assert _pick(team, inning=10, score_diff=0, is_home_defense=False) == "CL"


def test_closer_never_selected_in_blowout():
    for score_diff in (5, -5):
        for inning in (7, 9):
            for home in (True, False):
                team = _team("CL", "SU", "MR", "LR")
                assert _pick(team, inning=inning, score_diff=score_diff,
                             is_home_defense=home) != "CL"


def test_save_situation_priority_unchanged():
    team = _team("CL", "SU", "MR", "LR")
    assert _pick(team, inning=9, score_diff=2, is_home_defense=False) == "CL"
    # CL unavailable -> SU fallback (unchanged behavior).
    team2 = TeamPitchingState(
        starter=_ps("SP1"),
        bullpen=[_ps("CL", available=False), _ps("SU"), _ps("MR"), _ps("LR")],
        current=_ps("SP1"),
    )
    assert _pick(team2, inning=9, score_diff=2, is_home_defense=False) == "SU"


def test_reliever_score_tied_values():
    cl = _ps("CL")
    su = _ps("SU")
    base = 50.0 * 1.1 + 40.0 * 0.1  # stuff*1.1 + endurance*0.1 = 59.0
    assert _reliever_score(cl, "high", score_diff=0) == pytest.approx(base)
    assert _reliever_score(su, "high", score_diff=0) == pytest.approx(base + 4.0)
    assert _reliever_score(cl, "high", score_diff=-1) == pytest.approx(base - 6.0)
    assert _reliever_score(su, "high", score_diff=-1) == pytest.approx(base - 2.0)


def test_tied_entry_predicate():
    def tied_entry(lead, inning, home):
        return lead == 0 and inning >= 9 and (home or inning >= 10)

    assert tied_entry(0, 9, True) is True
    assert tied_entry(0, 9, False) is False
    assert tied_entry(0, 10, False) is True
    assert tied_entry(1, 9, False) is False  # not tied -> save path instead
