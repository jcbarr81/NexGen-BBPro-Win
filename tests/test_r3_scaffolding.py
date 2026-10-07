"""Release 3 scaffolding (R3-0): new seams that must not change behaviour."""

import inspect

import pytest

from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from physics_sim.engine import (
    BaseState,
    LineupState,
    PitcherState,
    TeamPitchingState,
    _pitcher_enter_stats,
)
from physics_sim.models import BatterRatings, PitcherRatings
from physics_sim.usage import UsageState

# Every knob R3-0 registered, with its neutral/current value.
R3_KNOBS = {
    # item B (bullpen): on, as tuned in R3-B
    "inning_start_hook": 1.0,
    "bullpen_fallback": 1.0,
    "mop_up": 1.0,
    "emergency_starter_min_days": 2.0,
    "reliever_max_appearances_ratio": 0.50,
    # item D (extra innings)
    "max_innings_hard_stop": 60.0,
    # item E (pitcher arm hazard): on, calibrated to ~3/4 of MLB
    "pitcher_arm_enabled": 1.0,
    "pitcher_arm_base": 0.0075,
    "pitcher_arm_per_pitch": 0.00013,
    "pitcher_arm_durability_k": 0.25,
    "pitcher_arm_durability_center": 50.0,
    "pitcher_arm_reliever_rest_penalty": 0.5,
    "pitcher_arm_starter_short_rest_penalty": 0.5,
    "pitcher_arm_starter_short_rest_days": 4.0,
    "pitcher_arm_pitch_ramp": 0.15,
    "pitcher_arm_pitch_ramp_start": 100.0,
    "pitcher_arm_rate_reference": 0.1,
    "pitcher_arm_major_share": 0.30,
    # item E (owner Q14): fatigue-linked hitter injuries
    "batter_fatigue_injury_enabled": 1.0,
    "batter_fatigue_injury_base": 0.008,
    "batter_fatigue_injury_moderate_share": 0.45,
    "batter_fatigue_injury_major_share": 0.05,
    # item F (batter fatigue that accrues; tuned in R3-F)
    "batter_fatigue_game_cost_catcher": 9.0,
    "batter_fatigue_game_cost_dh": 5.0,
    "batter_fatigue_game_cost_sub": 1.5,
    "batter_rest_day_recovery_bonus": 10.0,
    "batter_rest_hard_streak_extra": 3.0,
    "batter_rest_similar_max": 1.0,
}


@pytest.mark.parametrize("key", sorted(R3_KNOBS))
def test_r3_knob_is_registered_at_its_neutral_value(key):
    assert DEFAULT_TUNING[key] == pytest.approx(R3_KNOBS[key])


@pytest.mark.parametrize("key", sorted(R3_KNOBS))
def test_r3_knob_survives_from_overrides(key):
    # from_overrides silently drops unregistered keys; a registered one must
    # come through, as a float.
    value = R3_KNOBS[key] + 1.25
    tuning = TuningConfig.from_overrides(overrides={key: str(value)})
    assert tuning.values[key] == pytest.approx(value)
    assert tuning.get(key) == pytest.approx(value)


def test_per_position_batter_cost_orders_catcher_fielder_dh():
    # R3-F: a catcher's game costs most, a DH's least, a substitute's less.
    flat = DEFAULT_TUNING["batter_fatigue_game_cost"]
    assert DEFAULT_TUNING["batter_fatigue_game_cost_catcher"] > flat
    assert flat > DEFAULT_TUNING["batter_fatigue_game_cost_dh"]
    assert DEFAULT_TUNING["batter_fatigue_game_cost_dh"] > DEFAULT_TUNING["batter_fatigue_game_cost_sub"]
    # Fatigue accrues: a day's recovery at durability 50 is below a game's cost.
    recovery = (
        DEFAULT_TUNING["batter_daily_recovery_base"]
        + 50 * DEFAULT_TUNING["batter_daily_recovery_durability_scale"]
    )
    assert recovery < flat


def test_rotation_builder_moved_and_is_re_exported():
    import utils.pitcher_recovery as tracker
    import utils.rotation as rotation

    assert tracker.choose_rotation is rotation.choose_rotation
    assert tracker._is_relief_role is rotation._is_relief_role
    assert tracker._spot_start_rank is rotation._spot_start_rank
    assert tracker.ROTATION_SLOTS == rotation.ROTATION_SLOTS == 5


def test_lineup_loader_split_into_hitters_and_pitchers():
    import utils.lineup_loader as loader

    assert list(inspect.signature(loader._default_hitters).parameters) == [
        "team_id", "roster", "all_players",
    ]
    assert list(inspect.signature(loader._default_pitchers).parameters) == [
        "team_id", "roster_dir", "roster", "all_players",
    ]


def _pitcher(pid: str = "P1") -> PitcherRatings:
    return PitcherRatings(
        player_id=pid, bats="R", throws="R", role="RP", preferred_role="RP",
        velocity=90.0, control=50.0, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=40.0, durability=50.0,
        fielding=50.0, arm=50.0, repertoire={"fb": 60.0},
    )


def test_usage_game_index_counts_distinct_game_dates():
    tuning = load_tuning()
    arms = [_pitcher()]
    usage = UsageState()
    assert usage.game_index == 0
    usage.advance_day(day=0, pitchers=arms, tuning=tuning)
    assert (usage.current_day, usage.game_index) == (0, 0)
    # Both clubs advance to the same date: one game date.
    usage.advance_day(day=0, pitchers=arms, tuning=tuning)
    assert usage.game_index == 0
    usage.advance_day(day=1, pitchers=arms, tuning=tuning)
    usage.advance_day(day=1, pitchers=arms, tuning=tuning)
    assert (usage.current_day, usage.game_index) == (1, 1)
    # An off day between dates does not count.
    usage.advance_day(day=3, pitchers=arms, tuning=tuning)
    assert (usage.current_day, usage.game_index) == (3, 2)
    # A stale (earlier) day is ignored.
    usage.advance_day(day=2, pitchers=arms, tuning=tuning)
    assert (usage.current_day, usage.game_index) == (3, 2)


def test_usage_game_index_starts_at_zero_on_a_seeded_clock():
    tuning = load_tuning()
    usage = UsageState(current_day=5)
    usage.advance_day(day=5, pitchers=[], tuning=tuning)
    assert usage.game_index == 0
    usage.advance_day(day=6, pitchers=[], tuning=tuning)
    assert usage.game_index == 1


def _batter(pid: str) -> BatterRatings:
    return BatterRatings(
        player_id=pid, bats="R", primary_position="CF", other_positions=[],
        contact=50.0, power=50.0, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=50.0, speed=50.0, eye=50.0,
        height=72.0, durability=50.0,
    )


def _enter(bases: BaseState, **kwargs):
    starter = PitcherState(pitcher=_pitcher("SP"), staff_role="SP1", rest_role="SP1")
    reliever = PitcherState(pitcher=_pitcher("CL"), staff_role="CL", rest_role="CL")
    staff = TeamPitchingState(starter=starter, bullpen=[reliever], current=starter)
    lineup = LineupState(lineup=[], positions={})
    return _pitcher_enter_stats(
        pitching_state=staff, pitcher_state=reliever, lineup_state=lineup,
        inning=10, score_diff=0, defense_score=3, offense_score=3, bases=bases,
        postseason=False, tuning=load_tuning(), **kwargs,
    )


def test_pitcher_enter_stats_charges_every_runner_by_default():
    bases = BaseState(first=_batter("B1"), second=_batter("B2"))
    assert _enter(bases).ir == 2
    assert _enter(bases, exclude_ids=None).ir == 2
    assert _enter(bases, exclude_ids=set()).ir == 2


def test_pitcher_enter_stats_skips_excluded_runners():
    bases = BaseState(first=_batter("B1"), second=_batter("GHOST"))
    line = _enter(bases, exclude_ids={"GHOST"})
    assert line.ir == 1
    assert line.inning_baserunners == 1
    assert _enter(BaseState(second=_batter("GHOST")), exclude_ids={"GHOST"}).ir == 0


def test_engine_anchor_comments_present():
    from pathlib import Path

    import physics_sim.engine as engine

    source = Path(engine.__file__).read_text(encoding="utf-8")
    for anchor in (
        "# R3: end of inning-start pitching changes",
        "# R3: first PA of half",
        "# R3: post-game hazards",
    ):
        assert source.count(anchor) == 1, anchor
    assert "auto_runner_ids: set[str] = set()" in source
    assert "exclude_ids=auto_runner_ids" in source
