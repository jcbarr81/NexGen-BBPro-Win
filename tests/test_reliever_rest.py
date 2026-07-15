"""S2-03: pitch-count-conditional reliever rest (unified engine + tracker table)."""
import physics_sim.usage as usage_mod
from physics_sim.config import load_tuning
from physics_sim.engine import (
    PitcherState,
    _apply_usage_state,
    _pitcher_is_rested,
)
from physics_sim.models import PitcherRatings
from physics_sim.usage import UsageState, reliever_rest_days


def _pitcher(pid: str, role: str = "MR") -> PitcherRatings:
    return PitcherRatings(
        player_id=pid, bats="R", throws="R", role=role, preferred_role=role,
        velocity=90.0, control=50.0, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=40.0, durability=50.0,
        fielding=50.0, arm=50.0, repertoire={"fb": 60.0},
    )


def _available(pid, role, *, game_day, last_used_day, last_pitches,
               consecutive=1, appearances=1):
    tuning = load_tuning()
    usage = UsageState(current_day=game_day)
    wl = usage.workload_for(pid)
    wl.last_used_day = last_used_day
    wl.last_pitches = last_pitches
    wl.consecutive_days_used = consecutive
    wl.appearances = appearances
    wl.last_update_day = game_day
    state = PitcherState(
        pitcher=_pitcher(pid, role), fatigue_start=50.0, fatigue_limit=60.0,
        rest_role=role, staff_role=role,
    )
    _apply_usage_state(state, usage, game_day, tuning)
    return state.available


def test_b2b_allowed_after_short_outing():
    assert _available("p", "MR", game_day=1, last_used_day=0, last_pitches=12) is True


def test_same_day_reuse_blocked():
    assert _available("p", "MR", game_day=0, last_used_day=0, last_pitches=12) is False


def test_one_off_day_after_medium_outing():
    assert _available("p", "MR", game_day=1, last_used_day=0, last_pitches=20) is False
    assert _available("p", "MR", game_day=2, last_used_day=0, last_pitches=20) is True


def test_two_off_days_after_long_outing():
    assert _available("p", "LR", game_day=1, last_used_day=0, last_pitches=35) is False
    assert _available("p", "LR", game_day=2, last_used_day=0, last_pitches=35) is False
    assert _available("p", "LR", game_day=3, last_used_day=0, last_pitches=35) is True


def test_three_off_days_after_forty_plus_pitches():
    for d in (1, 2, 3):
        assert _available("p", "LR", game_day=d, last_used_day=0, last_pitches=55) is False
    assert _available("p", "LR", game_day=4, last_used_day=0, last_pitches=55) is True


def test_third_consecutive_day_blocked_for_all_relievers():
    tuning = load_tuning()
    usage = UsageState(current_day=0)
    pitchers = [_pitcher("p", "MR")]
    usage.advance_day(day=0, pitchers=pitchers, tuning=tuning)
    usage.record_outing(pitcher_id="p", pitches=8, day=0, multiplier=1.0, tuning=tuning)
    usage.advance_day(day=1, pitchers=pitchers, tuning=tuning)
    usage.record_outing(pitcher_id="p", pitches=8, day=1, multiplier=1.0, tuning=tuning)
    # consecutive_days_used is now 2 -> third straight day (day 2) is blocked.
    usage.advance_day(day=2, pitchers=pitchers, tuning=tuning)
    state = PitcherState(pitcher=pitchers[0], fatigue_start=50.0, fatigue_limit=60.0,
                         rest_role="MR", staff_role="MR")
    _apply_usage_state(state, usage, 2, tuning)
    assert state.available is False
    # After a full off day the streak resets -> available again on day 3.
    usage.advance_day(day=3, pitchers=pitchers, tuning=tuning)
    state2 = PitcherState(pitcher=pitchers[0], fatigue_start=50.0, fatigue_limit=60.0,
                          rest_role="MR", staff_role="MR")
    _apply_usage_state(state2, usage, 3, tuning)
    assert state2.available is True


def test_closer_back_to_back_now_allowed():
    # Later in the season so the separate appearance cap doesn't gate; the point
    # is that the consecutive-day rule no longer blocks a CL back-to-back.
    assert _available("c", "CL", game_day=10, last_used_day=9, last_pitches=10,
                      consecutive=1, appearances=3) is True


def test_closer_appearance_cap_still_enforced():
    # closer_max_appearances_ratio 0.45 -> on day 9, cap = int(10*0.45)=4.
    assert _available("c", "CL", game_day=9, last_used_day=5, last_pitches=10,
                      appearances=10) is False


def test_tracker_reliever_table_matches_engine():
    from utils.pitcher_recovery import _rest_days

    _rest_days.cache_clear()
    for p in (1, 12, 13, 25, 26, 40, 41, 80):
        assert _rest_days(p, "MR") == reliever_rest_days(p) + 1


def test_starter_rest_unchanged():
    tuning = load_tuning()
    usage = UsageState(current_day=0)
    wl = usage.workload_for("sp")
    wl.last_used_day = 0
    wl.last_pitches = 95
    kwargs = dict(pitcher_id="sp", role="SP1", usage_state=usage, tuning=tuning)
    assert _pitcher_is_rested(game_day=3, **kwargs) is False
    assert _pitcher_is_rested(game_day=4, **kwargs) is True
