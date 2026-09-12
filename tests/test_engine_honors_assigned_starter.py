"""The game starts the pitcher the rotation assigned.

Two systems were choosing a starting pitcher and only one of them was being
obeyed. ``PitcherRecoveryTracker.assign_starter`` picks from season-long rest
and advances the rotation pointer; the physics engine then threw that away and
re-derived a slot from ``game_day % 5``.

``game_day`` is a counter that restarts at zero in every fresh process, and the
league is simulated in weekly batches, so every run replayed
SP1, SP2, SP3, SP4, SP5, SP1, SP2 -- seven games, with the first two slots
taking two starts each. Six runs of that is 12/12/6/6/6, which is exactly the
split owners reported (CHI was 13/12/6/6/6 and 17 of 20 teams matched).

Proved by comparing the tracker's decision log against the box scores for one
production week: four of seven CHI games started a pitcher the tracker had not
assigned, and the actual sequence was a clean round robin from SP1.
"""

import pytest

from physics_sim.engine import _order_pitchers_for_game


class _P:
    """Minimal stand-in for PitcherRatings."""

    def __init__(self, pid):
        self.player_id = pid
        self.preferred_role = ""
        self.role = ""


ROLES = {"p1": "SP1", "p2": "SP2", "p3": "SP3", "p4": "SP4", "p5": "SP5", "cl": "CL"}


def _staff():
    return [_P(pid) for pid in ["p1", "p2", "p3", "p4", "p5", "cl"]]


def _order(game_day, forced=None):
    return _order_pitchers_for_game(
        _staff(),
        roles_by_id=ROLES,
        usage_state=None,
        game_day=game_day,
        tuning={},
        forced_starter_id=forced,
    )


# --- the regression --------------------------------------------------------


def test_a_weekly_batch_no_longer_starts_sp1_and_sp2_twice():
    """The bug in one assertion: seven games from a fresh process used to give
    SP1 and SP2 two starts each and the rest one."""
    assigned = ["p1", "p2", "p3", "p4", "p5", "p1", "p2"]  # what the tracker wants
    # Simulate a run where game_day restarts at 0, as it does in a new process.
    starters = [_order(day, forced=want)[0].player_id for day, want in enumerate(assigned)]
    assert starters == assigned


def test_without_a_forced_starter_the_slot_still_comes_from_game_day():
    """Unchanged fallback, so nothing that has no tracker (tests, tools,
    exhibition games) changes behaviour."""
    assert [_order(day)[0].player_id for day in range(5)] == ["p1", "p2", "p3", "p4", "p5"]


def test_the_game_day_counter_restarting_is_what_biased_the_split():
    """Documents the mechanism: a counter that restarts every run cannot
    produce an even season."""
    week = [_order(day)[0].player_id for day in range(7)]
    assert week.count("p1") == 2 and week.count("p2") == 2
    assert week.count("p5") == 1


# --- the assigned starter wins ---------------------------------------------


@pytest.mark.parametrize("pid", ["p1", "p2", "p3", "p4", "p5"])
def test_any_assigned_rotation_slot_is_honoured(pid):
    assert _order(3, forced=pid)[0].player_id == pid


def test_the_assigned_starter_beats_the_game_day_slot():
    """game_day 0 would pick SP1; the tracker said SP4."""
    assert _order(0, forced="p4")[0].player_id == "p4"


def test_a_spot_start_from_the_bullpen_is_honoured():
    """Not every assigned starter is one of the five."""
    assert _order(0, forced="cl")[0].player_id == "cl"


def test_an_unknown_starter_falls_back_instead_of_dropping_the_game():
    """A stale id must not crash a simulated game or empty the staff."""
    ordered = _order(1, forced="nobody")
    assert ordered and ordered[0].player_id == "p2"


# --- the rest of the staff stays intact ------------------------------------


def test_no_pitcher_is_lost_or_duplicated():
    ordered = _order(0, forced="p3")
    ids = [p.player_id for p in ordered]
    assert sorted(ids) == sorted(["p1", "p2", "p3", "p4", "p5", "cl"])


def test_the_bullpen_still_comes_before_the_rested_rotation():
    """Relievers must be reachable before the engine walks into other
    starters, or a mid-game change burns tomorrow's starter."""
    ids = [p.player_id for p in _order(0, forced="p3")]
    assert ids[0] == "p3"
    assert ids.index("cl") < ids.index("p4")
