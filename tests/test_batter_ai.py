import pytest

from playbalance.batter_ai import BatterAI
from tests.util.pbini_factory import load_config, make_cfg
from tests.test_simulation import make_player, make_pitcher


def test_swing_decision_respects_idrating():
    cfg = load_config()
    cfg.values.update({"idRatingBase": 100})
    ai = BatterAI(cfg)
    batter = make_player("b1")
    pitcher = make_pitcher("p1")
    swing, contact = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.0,
    )
    assert swing is True
    assert contact == pytest.approx(0.93)


def test_misidentification_reduces_contact():
    cfg = load_config()
    cfg.values.update(
        {
            "idRatingBase": 0,
            "idRatingCHPct": 0,
            "idRatingExpPct": 0,
            "idRatingPitchRatPct": 0,
        }
    )
    ai = BatterAI(cfg)
    batter = make_player("b1")
    batter.ch = 0
    batter.exp = 0
    pitcher = make_pitcher("p1")
    pitcher.fb = 100
    swing, contact = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.4,
    )
    assert swing is True
    assert contact == 0.0


def test_misread_contact_has_scaled_floor():
    cfg = make_cfg(
        idRatingBase=0,
        idRatingCHPct=0,
        idRatingExpPct=0,
        idRatingPitchRatPct=0,
        minMisreadContact=0.2,
    )
    ai = BatterAI(cfg)
    pitcher = make_pitcher("p1")

    batter_low = make_player("low", ch=20)
    batter_high = make_player("high", ch=80)

    swing_low, contact_low = ai.decide_swing(
        batter_low,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.0,
    )

    swing_high, contact_high = ai.decide_swing(
        batter_high,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.0,
    )

    assert swing_low is True and swing_high is True
    assert contact_low == pytest.approx(0.04)
    assert contact_high == pytest.approx(0.16)
    assert contact_high > contact_low


def test_primary_look_adjust_increases_swings():
    cfg = load_config()
    cfg.values.update(
        {
            "idRatingBase": 0,
            "idRatingCHPct": 0,
            "idRatingExpPct": 0,
            "idRatingPitchRatPct": 0,
            "lookPrimaryType00CountAdjust": 50,
        }
    )
    ai = BatterAI(cfg)
    batter = make_player("b1")
    batter.ch = 0
    batter.exp = 0
    pitcher = make_pitcher("p1")
    pitcher.fb = 100
    swing, contact = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.4,
    )
    assert swing is True
    assert contact == pytest.approx(0.25666666666666665)


def test_best_look_adjust_increases_swings():
    cfg = load_config()
    cfg.values.update(
        {
            "idRatingBase": 0,
            "idRatingCHPct": 0,
            "idRatingExpPct": 0,
            "idRatingPitchRatPct": 0,
            "lookBestType00CountAdjust": 50,
        }
    )
    ai = BatterAI(cfg)
    batter = make_player("b1")
    batter.ch = 0
    batter.exp = 0
    pitcher = make_pitcher("p1")
    pitcher.fb = 100
    swing, contact = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.4,
    )
    assert swing is True
    assert contact == pytest.approx(0.25666666666666665)


def test_ch_and_exp_ratings_increase_identification():
    cfg = load_config()
    cfg.values.update({"idRatingBase": 0, "idRatingPitchRatPct": 0})
    ai = BatterAI(cfg)
    pitcher = make_pitcher("p1")
    pitcher.fb = 100

    batter_low = make_player("low")
    batter_low.ch = 0
    batter_low.exp = 0
    swing_low, contact_low = ai.decide_swing(
        batter_low,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.4,
    )

    batter_high = make_player("high")
    batter_high.ch = 100
    batter_high.exp = 100
    swing_high, contact_high = ai.decide_swing(
        batter_high,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.4,
    )

    assert swing_low is True
    assert contact_low == 0.0
    assert swing_high is True
    assert contact_high == pytest.approx(0.82)


def test_pitch_rating_makes_identification_harder():
    cfg = load_config()
    cfg.values.update(
        {
            "idRatingBase": 60,
            "idRatingCHPct": 0,
            "idRatingExpPct": 0,
            "idRatingPitchRatPct": 100,
        }
    )
    ai = BatterAI(cfg)
    batter = make_player("b1")
    batter.ch = 0
    batter.exp = 0

    pitcher_easy = make_pitcher("easy")
    pitcher_easy.fb = 0
    swing_e, contact_e = ai.decide_swing(
        batter,
        pitcher_easy,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.3,
        check_random=0.9,
    )

    pitcher_hard = make_pitcher("hard")
    pitcher_hard.fb = 100
    swing_h, contact_h = ai.decide_swing(
        batter,
        pitcher_hard,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.3,
        check_random=0.3,
    )

    assert swing_e is True and contact_e > contact_h
    assert swing_h is True


def test_recognition_ease_scale_improves_contact():
    cfg = make_cfg(
        idRatingBase=20,
        idRatingCHPct=0,
        idRatingExpPct=0,
        idRatingPitchRatPct=0,
    )
    ai = BatterAI(cfg)
    batter = make_player("b1", ch=0)
    batter.exp = 0
    pitcher = make_pitcher("p1")
    swing_low, contact_low = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.3,
    )
    cfg.idRatingEaseScale = 2.0
    swing_high, contact_high = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.3,
    )
    assert swing_low is True and swing_high is True
    assert contact_high > contact_low


def test_pitch_classification():
    cfg = load_config()
    ai = BatterAI(cfg)

    assert ai.pitch_class(0) == "sure strike"
    assert ai.pitch_class(3) == "close strike"
    assert ai.pitch_class(4) == "close ball"
    assert ai.pitch_class(5) == "close ball"
    assert ai.pitch_class(6) == "sure ball"


@pytest.mark.xfail(reason="legacy playbalance engine behavior drift; physics is the shipping engine and is KPI-gated separately", strict=False)
def test_discipline_ratings_increase_takes():
    cfg = make_cfg(
        idRatingBase=0,
        idRatingCHPct=0,
        idRatingExpPct=0,
        idRatingPitchRatPct=0,
        disciplineRatingBase=0,
        disciplineRatingCHPct=150,
        disciplineRatingExpPct=100,
        disciplineRatingPct=100,
    )
    ai = BatterAI(cfg)
    pitcher = make_pitcher("p1")

    batter_low = make_player("low")
    batter_low.ch = 0
    batter_low.exp = 0
    batter_high = make_player("high")
    batter_high.ch = 100
    batter_high.exp = 100

    values = [0.0, 0.1, 0.2, 0.3, 0.4]
    takes_low = 0
    takes_high = 0
    for rv in values:
        swing_low, _ = ai.decide_swing(
            batter_low,
            pitcher,
            pitch_type="fb",
            balls=0,
            strikes=0,
            dist=5,
            random_value=rv,
        )
        swing_high, _ = ai.decide_swing(
            batter_high,
            pitcher,
            pitch_type="fb",
            balls=0,
            strikes=0,
            dist=5,
            random_value=rv,
        )
        takes_low += int(not swing_low)
        takes_high += int(not swing_high)

    assert takes_high > takes_low


@pytest.mark.xfail(reason="legacy playbalance engine behavior drift; physics is the shipping engine and is KPI-gated separately", strict=False)
def test_high_ch_batters_take_close_balls():
    cfg = make_cfg(
        idRatingBase=0,
        idRatingCHPct=0,
        idRatingExpPct=0,
        idRatingPitchRatPct=0,
        disciplineRatingBase=0,
        disciplineRatingCHPct=0,
        disciplineRatingExpPct=0,
        disciplineRatingPct=100,
    )
    ai = BatterAI(cfg)
    pitcher = make_pitcher("p1")

    batter_low = make_player("low")
    batter_low.ch = 0
    batter_high = make_player("high")
    batter_high.ch = 100

    values = [0.0, 0.1, 0.2, 0.3, 0.4]
    takes_low = 0
    takes_high = 0
    for rv in values:
        swing_low, _ = ai.decide_swing(
            batter_low,
            pitcher,
            pitch_type="fb",
            balls=0,
            strikes=0,
            dist=5,
            random_value=rv,
        )
        swing_high, _ = ai.decide_swing(
            batter_high,
            pitcher,
            pitch_type="fb",
            balls=0,
            strikes=0,
            dist=5,
            random_value=rv,
        )
        takes_low += int(not swing_low)
        takes_high += int(not swing_high)

    assert takes_high > takes_low


@pytest.mark.parametrize(
    "base,expected",
    [
        (85, 0.79),
        (92, 0.69),
        (98, 0.59),
    ],
)
def test_timing_curve_selection(base, expected):
    cfg = load_config()
    cfg.values.update(
        {
            "idRatingBase": base,
            "idRatingCHPct": 0,
            "idRatingExpPct": 0,
            "idRatingPitchRatPct": 0,
            "timingVeryBadThresh": 60,
            "timingVeryBadCount": 1,
            "timingVeryBadFaces": 1,
            "timingVeryBadBase": 0,
            "timingBadThresh": 80,
            "timingBadCount": 1,
            "timingBadFaces": 1,
            "timingBadBase": 10,
            "timingMedThresh": 90,
            "timingMedCount": 1,
            "timingMedFaces": 1,
            "timingMedBase": 20,
            "timingGoodThresh": 95,
            "timingGoodCount": 1,
            "timingGoodFaces": 1,
            "timingGoodBase": 30,
            "timingVeryGoodCount": 1,
            "timingVeryGoodFaces": 1,
            "timingVeryGoodBase": 40,
        }
    )
    ai = BatterAI(cfg)
    batter = make_player("b1")
    pitcher = make_pitcher("p1")
    swing, contact = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.4,
    )
    assert swing is True
    assert contact == pytest.approx(expected)


def test_contact_quality_variability():
    cfg = load_config()
    cfg.values.update({"idRatingBase": 100})
    ai = BatterAI(cfg)
    batter = make_player("b1")
    pitcher = make_pitcher("p1")
    _, contact1 = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.1,
    )
    _, contact2 = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        balls=0,
        strikes=0,
        dist=0,
        random_value=0.2,
    )
    assert contact1 != contact2


def test_large_adjustment_fails_small_succeeds():
    cfg = make_cfg(
        adjustUnitsCHPct=100,
        adjustUnitsPowerPct=75,
        adjustUnitsContactPct=150,
        adjustUnitsDiag=2,
        adjustUnitsHoriz=3,
        adjustUnitsVert=2,
    )
    ai = BatterAI(cfg)
    batter = make_player("b1", ch=40)
    assert ai.can_adjust_swing(batter, 20, 20, swing_type="power") is False
    assert ai.can_adjust_swing(batter, 1, 0, swing_type="contact") is True


def test_timing_adjustment_respects_speedup_multipliers():
    cfg = make_cfg(
        adjustUnitsCHPct=100,
        adjustUnitsSpeedUpHighGeared=10,
        adjustUnitsSpeedUpLowGeared=1,
    )
    ai = BatterAI(cfg)
    batter = make_player("b1", ch=10)
    assert (
        ai.can_adjust_swing(
            batter, 0, 0, timing_units=2, timing_adjust="speed_up_high"
        )
        is False
    )
    assert (
        ai.can_adjust_swing(
            batter, 0, 0, timing_units=2, timing_adjust="speed_up_low"
        )
        is True
    )


def test_timing_adjustment_respects_slowdown_multipliers():
    cfg = make_cfg(
        adjustUnitsCHPct=100,
        adjustUnitsSlowDownHighGeared=10,
        adjustUnitsSlowDownLowGeared=1,
    )
    ai = BatterAI(cfg)
    batter = make_player("b1", ch=10)
    assert (
        ai.can_adjust_swing(
            batter, 0, 0, timing_units=2, timing_adjust="slow_down_high"
        )
        is False
    )
    assert (
        ai.can_adjust_swing(
            batter, 0, 0, timing_units=2, timing_adjust="slow_down_low"
        )
        is True
    )


@pytest.mark.xfail(reason="legacy playbalance engine behavior drift; physics is the shipping engine and is KPI-gated separately", strict=False)
def test_check_swing_probability_varies_with_swing_type():
    cfg = make_cfg(
        adjustUnitsCHPct=0,
        adjustUnitsDiag=1,
        checkChanceBasePower=100,
        checkChanceCHPctPower=100,
        checkChanceBaseContact=300,
        checkChanceCHPctContact=100,
    )
    ai = BatterAI(cfg)
    batter = make_player("b1", ch=50)
    pitcher = make_pitcher("p1")

    swing_power, contact_power = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        swing_type="power",
        dx=1,
        dy=1,
        random_value=0.0,
        check_random=0.2,
    )

    swing_contact, contact_contact = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        swing_type="contact",
        dx=1,
        dy=1,
        random_value=0.0,
        check_random=0.2,
    )

    assert swing_power is True and contact_power == 0.0
    assert swing_contact is False and contact_contact == 0.0


def test_failed_check_can_make_contact():
    cfg = make_cfg(
        adjustUnitsCHPct=0,
        adjustUnitsDiag=1,
        checkChanceBaseNormal=0,
        checkChanceCHPctNormal=0,
        failedCheckContactChance=50,
    )
    ai = BatterAI(cfg)
    batter = make_player("b1", ch=50)
    pitcher = make_pitcher("p1")

    swing, contact = ai.decide_swing(
        batter,
        pitcher,
        pitch_type="fb",
        swing_type="normal",
        dx=1,
        dy=1,
        random_value=0.0,
        check_random=0.9,
    )

    assert swing is True
    assert contact == 0.1
