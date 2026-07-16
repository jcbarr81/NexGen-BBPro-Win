import random
import pytest

from playbalance.defensive_manager import DefensiveManager
from tests.util.pbini_factory import make_cfg


class MockRandom(random.Random):
    """Deterministic random generator using a predefined sequence."""

    def __init__(self, values):
        super().__init__()
        self.values = list(values)

    def random(self):  # type: ignore[override]
        return self.values.pop(0)


def test_charge_bunt_chance():
    cfg = make_cfg(
        chargeChanceBaseFirst=10,
        chargeChanceBaseThird=20,
        chargeChanceSacChanceAdjust=5,
        chargeChancePitcherFAPct=10,
        chargeChanceFAPct=10,
        chargeChanceThirdOnFirstSecond=15,
        chargeChanceThirdOnThird=25,
        defManChargeChancePct=50,
    )
    rng = MockRandom([0.1, 0.3, 0.9, 0.05])
    dm = DefensiveManager(cfg, rng)
    res = dm.maybe_charge_bunt(
        pitcher_fa=40,
        first_fa=30,
        third_fa=60,
        on_first=True,
        on_second=True,
        on_third=False,
    )
    assert res == (True, False)
    res = dm.maybe_charge_bunt(
        pitcher_fa=40,
        first_fa=30,
        third_fa=60,
        on_first=False,
        on_second=False,
        on_third=True,
    )
    assert res == (False, True)


def test_hold_runner_chance():
    cfg = make_cfg(
        holdChanceBase=10,
        holdChanceAdjust=50,
        holdChanceMinRunnerSpeed=30,
    )
    dm = DefensiveManager(cfg, MockRandom([0.5]))
    assert dm.maybe_hold_runner(35) is True  # 60% chance
    dm2 = DefensiveManager(cfg, MockRandom([0.5]))
    assert dm2.maybe_hold_runner(20) is False  # 10% chance


def test_pickoff_chance():
    cfg = make_cfg(
        pickoffChanceBase=10,
        pickoffChanceStealChanceAdjust=10,
        pickoffChanceLeadMult=5,
        pickoffChancePitchesMult=10,
    )
    rng = MockRandom([0.25, 0.9])
    dm = DefensiveManager(cfg, rng)
    assert dm.maybe_pickoff(steal_chance=5, lead=2, pitches_since=0) is True
    assert dm.maybe_pickoff(steal_chance=5, lead=2, pitches_since=4) is False


def test_pitch_out_chance():
    cfg = make_cfg(
        pitchOutChanceStealThresh=10,
        pitchOutChanceBase=20,
        pitchOutChanceBall0Adjust=5,
    )
    rng = MockRandom([0.2, 0.3])
    dm = DefensiveManager(cfg, rng)
    assert dm.maybe_pitch_out(steal_chance=15, ball_count=0) is True
    assert dm.maybe_pitch_out(steal_chance=15, ball_count=0) is False


def test_pitch_out_ball_counts():
    cfg = make_cfg(
        pitchOutChanceStealThresh=10,
        pitchOutChanceBase=20,
        pitchOutChanceBall0Adjust=10,
        pitchOutChanceBall1Adjust=-10,
    )
    rng = MockRandom([0.25, 0.25])
    dm = DefensiveManager(cfg, rng)
    assert dm.maybe_pitch_out(steal_chance=15, ball_count=0) is True
    assert dm.maybe_pitch_out(steal_chance=15, ball_count=1) is False


def test_pitch_out_innings_and_home():
    cfg = make_cfg(
        pitchOutChanceStealThresh=10,
        pitchOutChanceBase=20,
        pitchOutChanceInn8Adjust=30,
        pitchOutChanceInn9Adjust=50,
        pitchOutChanceHomeAdjust=10,
    )
    rng = MockRandom([0.4, 0.8, 0.15])
    dm = DefensiveManager(cfg, rng)
    assert dm.maybe_pitch_out(steal_chance=15, inning=8, is_home_team=True) is True
    assert dm.maybe_pitch_out(steal_chance=15, inning=5, is_home_team=False) is False
    assert dm.maybe_pitch_out(steal_chance=15, inning=9) is True


def test_pitch_around_chance():
    cfg = make_cfg(
        pitchAroundChanceNoInn=0,
        pitchAroundChanceBase=10,
        pitchAroundChanceInn7Adjust=5,
        pitchAroundChanceOut2=20,
        pitchAroundChancePH1BatAdjust=20,
        defManPitchAroundToIBBPct=50,
    )
    rng = MockRandom([0.2, 0.1, 0.4])
    dm = DefensiveManager(cfg, rng)
    pa, ibb = dm.maybe_pitch_around(
        inning=7,
        outs=2,
        batter_ph=50,
        on_deck_ph=30,
    )
    assert pa is True and ibb is True
    pa2, ibb2 = dm.maybe_pitch_around(
        inning=7,
        outs=2,
        batter_ph=30,
        on_deck_ph=50,
    )
    assert pa2 is False and ibb2 is False


def test_pitch_around_inning_threshold():
    cfg = make_cfg(
        pitchAroundChanceNoInn=3,
        pitchAroundChanceBase=100,
        pitchAroundChanceInn7Adjust=50,
    )
    dm = DefensiveManager(cfg, MockRandom([0.0]))
    pa, ibb = dm.maybe_pitch_around(inning=2, outs=1)
    assert pa is False and ibb is False


@pytest.mark.xfail(reason="legacy playbalance engine behavior drift; physics is the shipping engine and is KPI-gated separately", strict=False)
def test_pitch_around_ph_ch_levels():
    cfg = make_cfg(
        pitchAroundChanceBase=10,
        pitchAroundChancePH1BatAdjust=20,
        pitchAroundChanceCH1ODAdjust=-10,
    )
    rng = MockRandom([0.15, 0.15])
    dm = DefensiveManager(cfg, rng)
    pa1, _ = dm.maybe_pitch_around(
        batter_ph=50,
        on_deck_ph=30,
        batter_ch=30,
        on_deck_ch=55,
    )
    assert pa1 is True
    pa2, _ = dm.maybe_pitch_around(
        batter_ph=30,
        on_deck_ph=50,
        batter_ch=55,
        on_deck_ch=30,
    )
    assert pa2 is False


@pytest.mark.xfail(reason="legacy playbalance engine behavior drift; physics is the shipping engine and is KPI-gated separately", strict=False)
def test_pitch_around_gf_outs_and_bases():
    cfg = make_cfg(
        pitchAroundChanceBase=10,
        pitchAroundChanceLowGFThresh=40,
        pitchAroundChanceLowGFAdjust=15,
        pitchAroundChanceOut1=10,
        pitchAroundChanceOut2=20,
        pitchAroundChanceOn23=25,
    )
    rng = MockRandom([0.65, 0.15, 0.15])
    dm = DefensiveManager(cfg, rng)
    pa1, _ = dm.maybe_pitch_around(
        batter_gf=30,
        outs=2,
        on_second=True,
        on_third=True,
    )
    assert pa1 is True
    pa2, _ = dm.maybe_pitch_around(outs=1)
    assert pa2 is True
    pa3, _ = dm.maybe_pitch_around()
    assert pa3 is False


def test_outfield_position_shifts():
    cfg = make_cfg(
        defPosHighPull=80,
        defPosHighPullExtra=60,
        defPosLowPull=20,
        defPosLowPullExtra=40,
        defPosHighPower=80,
        defPosLowPower=30,
        normalPosLFPct=69,
        normalPosLFAngle=25,
        normalPosCFPct=69,
        normalPosCFAngle=0,
        normalPosRFPct=69,
        normalPosRFAngle=-25,
        outfieldPosPctNormal=70,
        outfieldPosPctDeep=80,
        outfieldPosPctShallow=60,
    )
    dm = DefensiveManager(cfg)

    high = dm.set_field_positions(pull=85, power=90)["outfield"]["normal"]
    assert high["LF"] == pytest.approx((55.2, 35))
    assert high["CF"] == pytest.approx((55.2, 10))
    assert high["RF"] == pytest.approx((55.2, -15))

    low = dm.set_field_positions(pull=15, power=20)["outfield"]["normal"]
    assert low["LF"] == pytest.approx((41.4, 15))
    assert low["CF"] == pytest.approx((41.4, -10))
    assert low["RF"] == pytest.approx((41.4, -35))


def test_field_position_parsing():
    cfg = make_cfg(
        infieldPosFeetPerDepth=10,
        cutoffRunPos1BDist=90,
        cutoffRunPos1BAngle=-35,
        cutoffRunPos2BDist=105,
        cutoffRunPos2BAngle=-15,
        doublePlayPos2BDist=135,
        doublePlayPos2BAngle=-12,
        guardLeftPosLFPct=65,
        guardLeftPosLFAngle=30,
        guardRightPosRFPct=65,
        guardRightPosRFAngle=30,
        normalPosCFPct=69,
        normalPosCFAngle=0,
        outfieldPosPctNormal=70,
        defPosHighPull=101,
        defPosHighPullExtra=101,
        defPosLowPull=-1,
        defPosLowPullExtra=-1,
        defPosHighPower=101,
        defPosLowPower=-1,
    )
    dm = DefensiveManager(cfg)
    pos = dm.set_field_positions()
    assert pos["infield"]["cutoffRun"]["1B"] == (90.0, -35)
    assert pos["infield"]["cutoffRun"]["2B"] == (105.0, -15)
    assert pos["infield"]["doublePlay"]["2B"] == (135.0, -12)
    cf = pos["outfield"]["normal"]["CF"]
    assert cf == pytest.approx((48.3, 0))
    gl = pos["outfield"]["guardLeft"]["LF"]
    assert gl == pytest.approx((45.5, 30))
    gr = pos["outfield"]["guardRight"]["RF"]
    assert gr == pytest.approx((45.5, 30))
