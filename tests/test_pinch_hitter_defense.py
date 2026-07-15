"""S2-13: pinch-hitter defensive awareness + last-catcher protection."""
from physics_sim.config import load_tuning
from physics_sim.engine import BaseState, LineupState, _select_pinch_hitter
from physics_sim.models import BatterRatings, PitcherRatings


def _bat(pid, *, off, primary="LF", other=None):
    # offense score = contact*0.55 + power*0.45 (+platoon); set ch=ph=off, R vs R.
    return BatterRatings(
        player_id=pid, bats="R", primary_position=primary,
        other_positions=other or [], contact=off, power=off, gb_tendency=50.0,
        pull_tendency=50.0, vs_left=50.0, fielding=50.0, arm=50.0, speed=50.0,
        eye=50.0, height=72.0, durability=50.0,
    )


def _pitcher():
    return PitcherRatings(
        player_id="p", bats="R", throws="R", role="SP", preferred_role="SP",
        velocity=90.0, control=50.0, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=60.0, durability=50.0,
        fielding=50.0, arm=50.0, repertoire={"fb": 60.0},
    )


def _pick(batter, bench, vacated_pos, *, inning=8, overrides=None):
    lineup = [batter] + [_bat(f"L{i}", off=50, primary="OF") for i in range(8)]
    positions = {batter.player_id: vacated_pos}
    ls = LineupState(lineup=lineup, positions=positions, bench=list(bench))
    tuning = load_tuning(overrides) if overrides else load_tuning()
    return _select_pinch_hitter(
        lineup_state=ls, batter=batter, pitcher=_pitcher(), inning=inning,
        outs=0, score_diff=0, bases=BaseState(), tuning=tuning,
    )


def test_ph_prefers_position_capable_candidate():
    batter = _bat("cur", off=45, primary="2B")
    a = _bat("A", off=70, primary="1B")           # cannot play 2B
    b = _bat("B", off=66, primary="3B", other=["2B"])  # can play 2B
    assert _pick(batter, [a, b], "2B").player_id == "B"  # 70-8=62 < 66


def test_elite_bat_overrides_defense_penalty():
    batter = _bat("cur", off=45, primary="2B")
    a = _bat("A", off=80, primary="1B")
    b = _bat("B", off=66, primary="3B", other=["2B"])
    assert _pick(batter, [a, b], "2B").player_id == "A"  # 80-8=72 > 66


def test_no_penalty_for_dh_slot():
    batter = _bat("cur", off=45, primary="DH")
    a = _bat("A", off=70, primary="1B")  # can't play anything else
    b = _bat("B", off=66, primary="3B")
    assert _pick(batter, [a, b], "DH").player_id == "A"


def test_defense_ignored_before_knob_inning():
    batter = _bat("cur", off=45, primary="2B")
    a = _bat("A", off=70, primary="1B")
    b = _bat("B", off=66, primary="3B", other=["2B"])
    got = _pick(batter, [a, b], "2B", inning=5,
                overrides={"pinch_hit_inning": 5.0, "pinch_hit_defense_inning": 7.0})
    assert got.player_id == "A"  # penalty not applied at inning 5


def test_last_catcher_never_burned_for_noncatcher_slot():
    batter = _bat("cur", off=50, primary="1B")
    bc = _bat("BC", off=75, primary="C")          # only catcher-eligible bench bat
    corner = _bat("CO", off=62, primary="1B")
    assert _pick(batter, [bc, corner], "1B").player_id == "CO"


def test_last_catcher_used_when_bench_is_only_him():
    # Whole-bench exception keeps the lone catcher as a candidate, but he still
    # carries the out-of-position penalty (can't play 1B) and must clear
    # advantage_min: off 62 - 8 (oop) beats a .44 batter, not a .50 batter.
    bc = _bat("BC", off=62, primary="C")
    assert _pick(_bat("cur", off=44, primary="1B"), [bc], "1B").player_id == "BC"
    assert _pick(_bat("cur", off=50, primary="1B"), [bc], "1B") is None


def test_catcher_slot_requires_catcher_eligible_ph():
    batter = _bat("cur", off=45, primary="C")
    slugger = _bat("S", off=80, primary="1B")     # no C
    util = _bat("U", off=62, primary="3B", other=["C"])
    assert _pick(batter, [slugger, util], "C").player_id == "U"
    assert _pick(batter, [slugger], "C") is None  # no C-eligible bench


def test_two_catchers_on_bench_allows_burning_one():
    batter = _bat("cur", off=45, primary="1B")
    c1 = _bat("C1", off=78, primary="C")
    c2 = _bat("C2", off=70, primary="C")
    assert _pick(batter, [c1, c2], "1B").player_id == "C1"  # protection lifts with a spare
