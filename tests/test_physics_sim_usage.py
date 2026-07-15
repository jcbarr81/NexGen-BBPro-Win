from physics_sim.config import load_tuning
from physics_sim.engine import _order_pitchers_for_game
from physics_sim.models import PitcherRatings
from physics_sim.usage import UsageState


def _pitcher(player_id: str) -> PitcherRatings:
    return PitcherRatings(
        player_id=player_id,
        bats="R",
        throws="R",
        role="SP",
        preferred_role="",
        velocity=90.0,
        control=50.0,
        movement=50.0,
        gb_tendency=50.0,
        vs_left=50.0,
        hold_runner=50.0,
        endurance=60.0,
        durability=50.0,
        fielding=50.0,
        arm=50.0,
        repertoire={"fb": 60.0},
    )


def test_usage_state_advances_per_pitcher() -> None:
    tuning = load_tuning()
    usage = UsageState()
    pitcher_a = _pitcher("P1")
    pitcher_b = _pitcher("P2")

    workload_a = usage.workload_for("P1")
    workload_b = usage.workload_for("P2")
    workload_a.fatigue_debt = 20.0
    workload_b.fatigue_debt = 20.0
    workload_a.last_update_day = 0
    workload_b.last_update_day = 0

    usage.advance_day(day=1, pitchers=[pitcher_a], tuning=tuning)
    usage.advance_day(day=1, pitchers=[pitcher_b], tuning=tuning)

    assert usage.workload_for("P1").fatigue_debt < 20.0
    assert usage.workload_for("P2").fatigue_debt < 20.0


def test_rotation_orders_by_game_day() -> None:
    tuning = load_tuning()
    p1 = _pitcher("P1")
    p2 = _pitcher("P2")
    p3 = _pitcher("P3")
    rp = _pitcher("P4")
    roles = {"P1": "SP1", "P2": "SP2", "P3": "SP3", "P4": "MR"}

    ordered_day0 = _order_pitchers_for_game(
        [p1, p2, p3, rp],
        roles_by_id=roles,
        usage_state=None,
        game_day=0,
        tuning=tuning,
    )
    ordered_day1 = _order_pitchers_for_game(
        [p1, p2, p3, rp],
        roles_by_id=roles,
        usage_state=None,
        game_day=1,
        tuning=tuning,
    )

    assert ordered_day0[0].player_id == "P1"
    assert ordered_day1[0].player_id == "P2"


def test_rotation_skips_unrested_starter() -> None:
    tuning = load_tuning()
    usage = UsageState()
    p1 = _pitcher("P1")
    p2 = _pitcher("P2")
    p3 = _pitcher("P3")
    roles = {"P1": "SP1", "P2": "SP2", "P3": "SP3"}

    usage.workload_for("P2").last_used_day = 0
    usage.workload_for("P2").last_update_day = 0
    usage.workload_for("P3").last_used_day = None

    ordered = _order_pitchers_for_game(
        [p1, p2, p3],
        roles_by_id=roles,
        usage_state=usage,
        game_day=1,
        tuning=tuning,
    )

    assert ordered[0].player_id == "P3"
