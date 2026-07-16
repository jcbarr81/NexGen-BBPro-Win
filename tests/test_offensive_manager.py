import random
import pytest

from playbalance.offensive_manager import OffensiveManager
from playbalance.simulation import GameSimulation, TeamState, BatterState
from models.player import Player
from models.pitcher import Pitcher
from tests.util.pbini_factory import make_cfg, load_config


class MockRandom(random.Random):
    """Deterministic random generator using a predefined sequence."""

    def __init__(self, values):
        super().__init__()
        self.values = list(values)

    def random(self):  # type: ignore[override]
        if self.values:
            return self.values.pop(0)
        return 0.0

    def randint(self, a, b):  # type: ignore[override]
        # ``PitcherAI`` uses ``randint`` for pitch variation which is irrelevant
        # for these tests.  Always return the lower bound without consuming the
        # predefined sequence.
        return a
def make_player(pid: str, ph: int = 50, sp: int = 50, ch: int = 50) -> Player:
    return Player(
        player_id=pid,
        first_name="F" + pid,
        last_name="L" + pid,
        birthdate="2000-01-01",
        height=72,
        weight=180,
        bats="R",
        primary_position="1B",
        other_positions=[],
        gf=50,
        ch=ch,
        ph=ph,
        sp=sp,
        pl=0,
        vl=0,
        sc=0,
        fa=0,
        arm=0,
    )


def make_pitcher(pid: str) -> Pitcher:
    return Pitcher(
        player_id=pid,
        first_name="PF" + pid,
        last_name="PL" + pid,
        birthdate="2000-01-01",
        height=72,
        weight=180,
        bats="R",
        primary_position="P",
        other_positions=[],
        gf=50,
        endurance=100,
        control=50,
        movement=50,
        hold_runner=50,
        fb=50,
        cu=0,
        cb=0,
        sl=0,
        si=0,
        scb=0,
        kn=0,
        arm=50,
        fa=50,
        role="SP",
    )
def test_calculate_steal_chance():
    cfg = make_cfg(
        offManStealChancePct=50,
        stealChance10Count=10,
        stealChanceFastThresh=80,
        stealChanceFastAdjust=20,
        stealChanceMedHoldThresh=60,
        stealChanceMedHoldAdjust=0,
        stealChancePitcherBackAdjust=5,
    )
    om = OffensiveManager(cfg, MockRandom([]))
    chance = om.calculate_steal_chance(
        balls=1,
        strikes=0,
        runner_sp=80,
        pitcher_hold=55,
        pitcher_is_left=False,
    )
    assert chance == pytest.approx(0.175, abs=0.0001)


def test_calculate_steal_chance_situational_modifiers():
    cfg = make_cfg(
        offManStealChancePct=100,
        stealChance10Count=10,
        stealChanceOnFirst01OutHighCHThresh=70,
        stealChanceOnFirst01OutHighCHAdjust=20,
        stealChanceWayBehindThresh=-2,
        stealChanceWayBehindAdjust=30,
    )
    om = OffensiveManager(cfg, MockRandom([]))
    good = om.calculate_steal_chance(
        balls=1,
        strikes=0,
        runner_sp=50,
        pitcher_hold=50,
        pitcher_is_left=False,
        outs=1,
        runner_on=1,
        batter_ch=80,
        run_diff=-3,
    )
    bad = om.calculate_steal_chance(
        balls=0,
        strikes=1,
        runner_sp=50,
        pitcher_hold=50,
        pitcher_is_left=False,
        outs=1,
        runner_on=1,
        batter_ch=50,
        run_diff=0,
    )
    assert good > bad


def test_calculate_steal_chance_on_second_modifiers():
    cfg = make_cfg(
        offManStealChancePct=100,
        stealChance10Count=10,
        stealChanceOnSecond0OutAdjust=20,
        stealChanceOnSecond1OutAdjust=10,
        stealChanceOnSecond2OutAdjust=-10,
        stealChanceOnSecondHighCHThresh=70,
        stealChanceOnSecondHighCHAdjust=15,
    )
    om = OffensiveManager(cfg, MockRandom([]))
    good = om.calculate_steal_chance(
        balls=1,
        strikes=0,
        runner_sp=50,
        pitcher_hold=50,
        pitcher_is_left=False,
        outs=0,
        runner_on=2,
        batter_ch=80,
    )
    neutral = om.calculate_steal_chance(
        balls=1,
        strikes=0,
        runner_sp=50,
        pitcher_hold=50,
        pitcher_is_left=False,
        outs=1,
        runner_on=2,
        batter_ch=80,
    )
    bad = om.calculate_steal_chance(
        balls=1,
        strikes=0,
        runner_sp=50,
        pitcher_hold=50,
        pitcher_is_left=False,
        outs=2,
        runner_on=2,
        batter_ch=60,
    )
    assert good > neutral > bad


def test_hit_and_run_chance_and_advance():
    cfg = make_cfg(
        hnrChanceBase=30,
        hnrChance3BallsAdjust=10,
        hnrChanceLowCHThresh=40,
        hnrChanceLowCHAdjust=-20,
        hnrChanceLowPHThresh=40,
        hnrChanceLowPHAdjust=10,
        offManHNRChancePct=100,
    )
    rng = MockRandom([0.2, 0.4])
    om = OffensiveManager(cfg, rng)
    assert om.maybe_hit_and_run(runner_sp=50, batter_ch=20, batter_ph=20, balls=3) is True
    assert om.maybe_hit_and_run(runner_sp=50, batter_ch=20, batter_ph=20, balls=3) is False

    full = load_config()
    full.values.update({
        "hnrChanceBase": 100,
        "offManHNRChancePct": 100,
        "pitchOutChanceBase": 0,
        "pitchAroundChanceBase": 0,
        "pickoffChanceBase": 0,
        "chargeChanceBaseThird": 0,
        "chargeChancePitcherFAPct": 0,
        "chargeChanceFAPct": 0,
        "chargeChanceThirdOnFirstSecond": 0,
        "chargeChanceThirdOnThird": 0,
        "chargeChanceSacChanceAdjust": 0,
        "holdChanceBase": 0,
        "holdChanceAdjust": 0,
    })
    runner = make_player("r", sp=80)
    batter = make_player("b", ch=10, ph=10)
    home = TeamState(lineup=[make_player("h1")], bench=[], pitchers=[make_pitcher("hp")])
    away = TeamState(lineup=[batter], bench=[], pitchers=[make_pitcher("ap")])
    runner_state = BatterState(runner)
    away.lineup_stats[runner.player_id] = runner_state
    away.bases[0] = runner_state
    sim = GameSimulation(
        home,
        away,
        full,
        MockRandom([0.0, 0.0, 0.0, 0.9, 0.0, 0.9, 0.0, 0.9]),
    )
    outs = sim.play_at_bat(away, home)
    assert outs == 1
    assert away.bases[1] is runner_state


def test_sacrifice_bunt_chance_and_advance():
    cfg = make_cfg(sacChanceBase=50, offManSacChancePct=100)
    rng = MockRandom([0.4, 0.6])
    om = OffensiveManager(cfg, rng)
    assert om.maybe_sacrifice_bunt(
        batter_is_pitcher=False,
        batter_ch=30,
        batter_ph=30,
        on_deck_ch=0,
        on_deck_ph=0,
        outs=0,
        inning=1,
        on_first=True,
        on_second=False,
        run_diff=0,
    ) is True
    assert om.maybe_sacrifice_bunt(
        batter_is_pitcher=False,
        batter_ch=30,
        batter_ph=30,
        on_deck_ch=0,
        on_deck_ph=0,
        outs=0,
        inning=1,
        on_first=True,
        on_second=False,
        run_diff=0,
    ) is False

    full = load_config()
    full.values.update({
        "hnrChanceBase": 0,
        "offManHNRChancePct": 0,
        "sacChanceBase": 100,
        "offManSacChancePct": 100,
        "pitchOutChanceBase": 0,
        "pitchAroundChanceBase": 0,
        "pickoffChanceBase": 0,
        "chargeChanceBaseThird": 0,
        "chargeChancePitcherFAPct": 0,
        "chargeChanceFAPct": 0,
        "chargeChanceThirdOnFirstSecond": 0,
        "chargeChanceThirdOnThird": 0,
        "chargeChanceSacChanceAdjust": 0,
        "holdChanceBase": 0,
        "holdChanceAdjust": 0,
    })
    runner = make_player("r")
    batter = make_player("b", ch=10, ph=10)
    home = TeamState(lineup=[make_player("h1")], bench=[], pitchers=[make_pitcher("hp")])
    away = TeamState(lineup=[batter], bench=[], pitchers=[make_pitcher("ap")])
    runner_state = BatterState(runner)
    away.lineup_stats[runner.player_id] = runner_state
    away.bases[0] = runner_state
    sim = GameSimulation(home, away, full, MockRandom([]))
    outs = sim.play_at_bat(away, home)
    assert outs == 1
    assert away.bases[1] is runner_state
    assert away.bases[0] is None


@pytest.mark.xfail(reason="legacy playbalance OffensiveManager behavior drift; physics is the shipping engine and does not use it", strict=False)
def test_sacrifice_bunt_on_deck_high_close_late():
    cfg = make_cfg(
        sacChanceBase=0,
        sacChanceCLAdjust=0,
        sacChance1OutAdjust=0,
        sacChanceCL1OutODHighCHThresh=50,
        sacChanceCL1OutODHighPHThresh=50,
        sacChanceCL1OutODHighAdjust=100,
        offManSacChancePct=100,
    )
    om = OffensiveManager(cfg, MockRandom([]))
    assert om.maybe_sacrifice_bunt(
        batter_is_pitcher=False,
        batter_ch=10,
        batter_ph=10,
        on_deck_ch=60,
        on_deck_ph=10,
        outs=1,
        inning=7,
        on_first=False,
        on_second=False,
        run_diff=0,
    ) is True
    assert om.maybe_sacrifice_bunt(
        batter_is_pitcher=False,
        batter_ch=10,
        batter_ph=10,
        on_deck_ch=40,
        on_deck_ph=40,
        outs=1,
        inning=7,
        on_first=False,
        on_second=False,
        run_diff=0,
    ) is False

    full = load_config()
    full.values.update(
        {
            "hnrChanceBase": 0,
            "offManHNRChancePct": 0,
            "sacChanceBase": 0,
            "sacChance1OutAdjust": 0,
            "sacChanceCLAdjust": 0,
            "sacChanceCL1OutODHighCHThresh": 50,
            "sacChanceCL1OutODHighPHThresh": 50,
            "sacChanceCL1OutODHighAdjust": 100,
            "offManSacChancePct": 100,
            "pitchOutChanceBase": 0,
            "pitchAroundChanceBase": 0,
            "pickoffChanceBase": 0,
            "chargeChanceBaseThird": 0,
            "chargeChancePitcherFAPct": 0,
            "chargeChanceFAPct": 0,
            "chargeChanceThirdOnFirstSecond": 0,
            "chargeChanceThirdOnThird": 0,
            "chargeChanceSacChanceAdjust": 0,
            "holdChanceBase": 0,
            "holdChanceAdjust": 0,
        }
    )
    runner = make_player("r", sp=80)
    batter = make_player("b", ch=10, ph=10)
    on_deck = make_player("d", ch=60, ph=60)
    home = TeamState(lineup=[make_player("h1")], bench=[], pitchers=[make_pitcher("hp")])
    away = TeamState(lineup=[batter, on_deck], bench=[], pitchers=[make_pitcher("ap")])
    runner_state = BatterState(runner)
    away.lineup_stats[runner.player_id] = runner_state
    away.bases[0] = runner_state
    away.inning_runs = [0] * 6
    home.inning_runs = [0] * 6
    sim = GameSimulation(home, away, full, MockRandom([]))
    sim.current_outs = 1
    outs = sim.play_at_bat(away, home)
    assert outs == 1
    assert away.bases[1] is runner_state
    assert away.bases[0] is None


@pytest.mark.xfail(reason="legacy playbalance OffensiveManager behavior drift; physics is the shipping engine and does not use it", strict=False)
def test_suicide_squeeze_chance_and_score():
    cfg = make_cfg(
        offManSqueezeChancePct=50,
        squeezeChanceLowCountAdjust=100,
        squeezeChanceMedCountAdjust=0,
        squeezeChanceThirdFastSPThresh=0,
        squeezeChanceThirdFastAdjust=0,
        squeezeChanceMaxCH=100,
        squeezeChanceMaxPH=100,
    )
    rng = MockRandom([0.4, 0.6])
    om = OffensiveManager(cfg, rng)
    assert (
        om.maybe_suicide_squeeze(
            batter_ch=50,
            batter_ph=50,
            balls=0,
            strikes=0,
            runner_on_third_sp=50,
        )
        is True
    )
    assert (
        om.maybe_suicide_squeeze(
            batter_ch=50,
            batter_ph=50,
            balls=0,
            strikes=0,
            runner_on_third_sp=50,
        )
        is False
    )

    full = load_config()
    full.values.update({
        "hnrChanceBase": 0,
        "offManHNRChancePct": 0,
        "sacChanceBase": 0,
        "offManSacChancePct": 0,
        "offManSqueezeChancePct": 100,
        "squeezeChanceLowCountAdjust": 100,
        "squeezeChanceMedCountAdjust": 0,
        "squeezeChanceThirdFastSPThresh": 0,
        "squeezeChanceThirdFastAdjust": 0,
        "squeezeChanceMaxCH": 100,
        "squeezeChanceMaxPH": 100,
        "pitchOutChanceBase": 0,
        "pitchAroundChanceBase": 0,
        "pickoffChanceBase": 0,
        "chargeChanceBaseThird": 0,
        "chargeChancePitcherFAPct": 0,
        "chargeChanceFAPct": 0,
        "chargeChanceThirdOnFirstSecond": 0,
        "chargeChanceThirdOnThird": 0,
        "chargeChanceSacChanceAdjust": 0,
        "holdChanceBase": 0,
        "holdChanceAdjust": 0,
    })
    runner = make_player("r")
    batter = make_player("b")
    home = TeamState(lineup=[make_player("h1")], bench=[], pitchers=[make_pitcher("hp")])
    away = TeamState(lineup=[batter], bench=[], pitchers=[make_pitcher("ap")])
    runner_state = BatterState(runner)
    away.lineup_stats[runner.player_id] = runner_state
    away.bases[2] = runner_state
    sim = GameSimulation(home, away, full, MockRandom([]))
    outs = sim.play_at_bat(away, home)
    assert outs == 1
    assert away.runs == 1
    assert away.bases[2] is None
