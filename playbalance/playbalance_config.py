from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from utils.path_utils import get_data_dir
from utils.league_benchmarks import load_league_benchmarks

from .pbini_loader import load_pbini

DATA_DIR = get_data_dir()
_OVERRIDE_PATH = DATA_DIR / "playbalance_overrides.json"

# MLB averages used to derive strike-based foul rates from all pitches.
# These baseline percentages are tuned to yield roughly four pitches per
# plate appearance, matching modern MLB norms.
# Match test expectations for baseline foul rates per pitch
_FOUL_PITCH_BASE_PCT = 18  # Percent of all pitches that are fouls
# Percent of all pitches that are strikes.
# Slightly reduced to encourage a few more walks across simulations.
_LEAGUE_STRIKE_PCT = 60.0

# Default values for PlayBalance configuration entries used throughout the
# simplified game playbalance.  Missing keys will fall back to these values when
# accessed as attributes.  The majority of values default to ``0`` which keeps
# related behaviour disabled unless explicitly enabled by a test case.  A small
# number have different sensible defaults, e.g. ``speedBase`` and
# ``swingSpeedBase`` which mirror the behaviour of the original game engine.
_DEFAULTS: Dict[str, Any] = {
    # Simulation sanity limits
    "halfInningLimitEnabled": 1,
    "maxHalfInningPA": 50,
    "maxHalfInningRuns": 30,
    # Feature toggles --------------------------------------------------
    "pitchCalibrationEnabled": 0,
    "pitchCalibrationTarget": 3.9,
    "pitchCalibrationTolerance": 0.05,
    "pitchCalibrationPerPlateCap": 1,
    "pitchCalibrationPerGameCap": 30,
    "pitchCalibrationMinPA": 6,
    "pitchCalibrationPreferFoul": 1,
    "pitchCalibrationEmaAlpha": 0.1,
    # Physics --------------------------------------------------------
    "speedBase": 19,
    "speedPct": 5,
    "swingSpeedBase": 61,
    "swingSpeedPHPct": 10,
    "swingSpeedPowerAdjust": 5,
    "swingSpeedNormalAdjust": 0,
    "swingSpeedContactAdjust": -5,
    "swingSpeedBuntAdjust": -70,
    "averagePitchSpeed": 94,
    "fastPitchBatSlowdownPct": 110,
    "slowPitchBatSpeedupPct": 85,
    "fbSpeedBase": 70,
    "fbSpeedRange": 2,
    "fbSpeedASPct": 30,
    "cbSpeedBase": 55,
    "cbSpeedRange": 2,
    "cbSpeedASPct": 30,
    "cuSpeedBase": 50,
    "cuSpeedRange": 2,
    "cuSpeedASPct": 30,
    "slSpeedBase": 63,
    "slSpeedRange": 2,
    "slSpeedASPct": 30,
    "sbSpeedBase": 55,
    "sbSpeedRange": 2,
    "sbSpeedASPct": 30,
    "kbSpeedBase": 65,
    "kbSpeedRange": 2,
    "kbSpeedASPct": 0,
    "siSpeedBase": 64,
    "siSpeedRange": 2,
    "siSpeedASPct": 30,
    "fbControlBoxWidth": 1.5,
    "fbControlBoxHeight": 1.5,
    "cbControlBoxWidth": 1.5,
    "cbControlBoxHeight": 1.5,
    "cuControlBoxWidth": 1.5,
    "cuControlBoxHeight": 1.5,
    "slControlBoxWidth": 1.5,
    "slControlBoxHeight": 1.5,
    "sbControlBoxWidth": 1.5,
    "sbControlBoxHeight": 1.5,
    "kbControlBoxWidth": 1.5,
    "kbControlBoxHeight": 1.5,
    "siControlBoxWidth": 1.5,
    "siControlBoxHeight": 1.5,
    "controlBoxIncreaseEffCOPct": 15,
    "controlMissPenaltyDist": 0,
    "controlMissBaseExpansion": 0.0,
    "pitchMissRandFactor": 0.0,
    "controlScale": 130,
    "speedReductionBase": 3,
    "speedReductionRange": 3,
    "speedReductionEffMOPct": 5,
    "swingAngleTenthDegreesBase": 44,
    "swingAngleTenthDegreesRange": 0,
    "swingAngleTenthDegreesGFPct": 95,
    "swingAngleTenthDegreesPowerAdjust": 0,
    "swingAngleTenthDegreesContactAdjust": 0,
    "swingAngleTenthDegreesHighAdjust": 20,
    "swingAngleTenthDegreesLowAdjust": -20,
    "swingAngleTenthDegreesOutsideAdjust": 0,
    "rollFrictionGrass": 12,
    "rollFrictionTurf": 10,
    "rollSpeedMult": 1.0,
    "ballAirResistancePct": 95,
    "ballAltitudePct": 100,
    "ballBaseAltitude": 0,
    "ballTempPct": 33,
    "ballWindSpeedPct": 33,
    "bounceVertTurfPct": 37,
    "bounceHorizTurfPct": 74,
    "bounceVertGrassPct": 35,
    "bounceHorizGrassPct": 72,
    "bounceVertDirtPct": 30,
    "bounceHorizDirtPct": 67,
    "ballCarryPct": 95,
    "bounceWetAdjust": -3,
    "bounceHotAdjust": 3,
    "bounceColdAdjust": -3,
    "batPowerHandleBase": 35,
    "batPowerHandleRange": 12,
    "batPowerDullBase": 60,
    "batPowerDullRange": 12,
    "batPowerSweetBase": 105,
    "batPowerSweetRange": 15,
    "batPowerEndBase": 60,
    "batPowerEndRange": 12,
    "hitAngleCountPower": 5,
    "hitAngleFacesPower": 13,
    "hitAngleBasePower": -1,
    "hitAngleCountNormal": 5,
    "hitAngleFacesNormal": 13,
    "hitAngleBaseNormal": -1,
    "hitAngleCountContact": 5,
    "hitAngleFacesContact": 13,
    "hitAngleBaseContact": -1,
    "hitAngleCountBunt": 30,
    "hitAngleFacesBunt": 3,
    "hitAngleBaseBunt": -30,
    "maxThrowDistBase": 190,
    "maxThrowDistASPct": 100,
    "throwSpeedIFBase": 77,
    "throwSpeedIFDistPct": 15,
    "throwSpeedIFASPct": 21,
    "throwSpeedIFMax": 92,
    "throwSpeedOFBase": 52,
    "throwSpeedOFDistPct": 3,
    "throwSpeedOFASPct": 0,
    "throwSpeedOFMax": 92,
    # Exit velocity and launch characteristics tuned via physics helpers
    "exitVeloBase": 0,
    "exitVeloPHPct": 0,
    "exitVeloSlope": 0.275,
    # Exit velocity swing type percentages
    "exitVeloPowerPct": 87,
    "exitVeloNormalPct": 88,
    "exitVeloContactPct": 100,
    "vertAngleGFPct": 0,
    "sprayAnglePLPct": 0,
    # Baseline batted ball type distribution (ground/line/fly)
    "groundBallBaseRate": 41,
    # Align with tests
    "flyBallBaseRate": 35,
    "lineDriveBaseRate": 20,
    # Weighting factors for batter/pitcher influence on batted ball types
    "bipPowerWeight": 0.2,
    "bipLaunchWeight": 0.2,
    "bipMovementWeight": 0.2,
    # League average strike percentage
    "leagueStrikePct": _LEAGUE_STRIKE_PCT,
    # Hit type distribution reflecting recent MLB averages
    "hit1BProb": 66,
    "hit2BProb": 20,
    "hit3BProb": 2,
    "hitHRProb": 12,
    # Hit probability tuning ----------------------------------------
    # Baseline hit probability value scaled down when accessed via
    # :pyattr:`hit_prob_base`.  The property multiplies the stored value by
    # ``0.1`` so a default of ``1.2`` yields an effective additive term of
    # ``0.12`` in the simulation.
    "hitProbBase": 1.35,
    # Boost contact to raise overall zone contact rate closer to MLB levels
    "contactFactorBase": 1.80,
    # Lower divisor so contact-heavy hitters see a larger boost
    # from their ``CH`` rating in hit probability calculations.
    "contactFactorDiv": 100,
    "movementFactorMin": 0.18,
    "movementImpactScale": 0.6,
    # Cap on final hit probability to prevent excessive offense
    "hitProbCap": 0.80,
    # Discipline clamps and swing probability bounds
    "disciplineNormFloor": 0.0,
    "disciplineNormCeil": 1.0,
    "swingZoneFloorMin": 0.0,
    "swingChaseCeilMax": 1.0,
    # Scales applied to swing probability on balls before and after two strikes.
    "ballSwingScale": 0.55,
    "ballSwingScaleTwoStrike": 0.85,
    "ballSwingCap": 0.25,
    "ballSwingCapTwoStrike": 0.55,
    # Baseline probabilities for converting batted balls into outs
    # MLB averages: ground balls ~24% hits (76% outs), line drives ~68% hits
    # (32% outs), fly balls ~14% hits (86% outs).  These defaults keep the
    # simplified simulation in a reasonable range when league benchmarks are
    # unavailable.  Values are tuned so that, with ``babipScale`` at ``1.2``,
    # the league-wide batting average on balls in play approaches ``.291``.
    "groundOutProb": 0.800,
    "lineOutProb": 0.323,
    "flyOutProb": 0.869,
    # Double play timing tuning (per-second probability boosts)
    "dpForceBoostPerSec": 0.50,
    "dpRelayBoostPerSec": 0.70,
    # Double play auto-convert thresholds (seconds)
    "dpForceAutoSec": 0.02,
    "dpRelayAutoSec": 0.05,
    # Hard minimum DP probability once a turn is on (0..1)
    "dpHardMinProb": 0.78,
    # Drastic calibration switch: when enabled, any successful force at 2B
    # will attempt to complete the turn with certainty (useful for testing
    # pipeline end-to-end; dial back after verifying DP path works leaguewide)
    "dpAlwaysTurn": 0,
    # Scaling factor for outs on balls in play (BABIP tuning)
    "babipScale": 1.05,
    # Foul ball tuning -----------------------------------------------
    # Percentages for foul balls and balls put in play; strike-based rate is
    # derived from all pitches.
    "foulPitchBasePct": _FOUL_PITCH_BASE_PCT,
    "foulStrikeBasePct": 31,
    "foulContactTrendPct": 2.0,
    "foulProbabilityScale": 1.0,
    "ballInPlayScale": 1.0,
    "foulStrikePctScale": 1.0,
    "foulPitchPctScale": 1.0,
    "foulPreBIPScale": 1.0,
    "foulPreBIPTwoStrikeScale": 1.0,
    "foulTwoStrikeGateProb": 0.0,
    "extraZSwingScaleMin": 0.78,
    "extraZSwingScaleMax": 1.04,
    "extraOSwingScaleMin": 1.32,
    "extraOSwingScaleMax": None,
    "twoStrikeContactBonus": 5.0,
    "twoStrikeFoulBonusPct": 0.0,
    # Target roughly 17% of all pitches being put into play
    "ballInPlayPitchPct": 9,
    "ballInPlayOuts": 0,
    "groundBallMaxRate": None,
    "carryDistanceScale": 0.85,
    "carryExitVeloBaseline": 90.0,
    # Probability that a ground ball with a force at second becomes a double play
    "doublePlayProb": 0.70,
    "dpMinSuccessProb": 0.35,
    # Baseline aggression for runners attempting extra bases
    "baserunningAggression": 0.42,
    # Baseline steal success rate (as percent, before arm/speed mods)
    "stealSuccessBasePct": 88,
    # Hit by pitch avoidance ----------------------------------------
    "hbpBatterStepOutChance": 10,
    "hbpBaseChance": 0.012,
    "leagueHBPPerGame": 0.86,
    # Pitcher AI ------------------------------------------------------
    "pitchRatVariationCount": 1,
    "pitchRatVariationFaces": 3,
    "pitchRatVariationBase": -2,
    "nonEstablishedPitchTypeAdjust": 0,
    "primaryPitchTypeAdjust": 50,
    "pitchObj00CountEstablishWeight": 0,
    "pitchObj00CountOutsideWeight": 40,
    "pitchObj00CountBestWeight": 0,
    "pitchObj00CountBestCenterWeight": 0,
    "pitchObj00CountFastCenterWeight": 0,
    "pitchObj00CountPlusWeight": 60,
    "pitchObj10CountOutsideWeight": 30,
    "pitchObj11CountOutsideWeight": 30,
    "pitchObj20CountOutsideWeight": 30,
    "pitchZoneTargetFloor": 0.0,
    # Pitcher target tuning; offsets expressed in strike-zone distance units.
    "pitchTargetEdgeOffset": 3.6,
    "pitchTargetWasteOffset": 6.3,
    "pitchTargetAimVariance": 1.8,
    "pitchTargetCrossSpread": 1.6,
    # Batter AI -------------------------------------------------------
    "sureStrikeDist": 4,
    "closeStrikeDist": 3,
    "closeBallDist": 5,
    # Baseline swing probabilities reflecting MLB averages
    "swingProbSureStrike": 0.43,
    "swingProbCloseStrike": 0.29,
    "swingProbCloseBall": 0.28,
    "swingProbSureBall": 0.12,
    # Global swing probability scaling factors (tests expect base values only)
    "swingProbScale": 1.0,
    # Separate scaling factors for pitches in and out of the zone
    "zSwingProbScale": 1.0,
    "oSwingProbScale": 0.7,
    # Additional tuning applied after benchmark adjustments
    "extraZSwingScale": 1.0,
    "extraOSwingScale": 1.0,
    # Bonus applied to close-ball swing probability per strike
    "closeBallStrikeBonus": 0,
    # Two-strike additive swing bonus (percent)
    "twoStrikeSwingBonus": 6,
    # Penalty applied when pitcher objective targets waste/edge
    "wasteObjectiveSwingPenalty": 8,
    "edgeObjectiveSwingPenalty": 3,
    "wasteObjectiveContactScale": 0.60,
    "edgeObjectiveContactScale": 0.82,
    "wasteObjectiveDistancePenalty": 8,
    "edgeObjectiveDistancePenalty": 3,
    "wasteObjectiveSwingScale": 0.32,
    "edgeObjectiveSwingScale": 0.68,
    "wasteObjectiveSwingDistanceScale": 0.16,
    "edgeObjectiveSwingDistanceScale": 0.08,
    "wasteObjectiveContactDistanceScale": 0.20,
    "edgeObjectiveContactDistanceScale": 0.12,
    # Count and location adjustments to swing probability
    "swingProb00CountAdjust": -0.03,
    "swingProb01CountAdjust": 0,
    "swingProb02CountAdjust": 0.08,
    "swingProb10CountAdjust": -0.03,
    "swingProb11CountAdjust": 0,
    "swingProb12CountAdjust": 0.06,
    "swingProb20CountAdjust": 0.00,
    "swingProb21CountAdjust": 0,
    "swingProb22CountAdjust": 0.04,
    "swingProb30CountAdjust": -0.02,
    "swingProb31CountAdjust": 0,
    "swingProb32CountAdjust": 0.02,
    "swingLocationFactor": 0,
    "lookPrimaryType00CountAdjust": 0,
    "lookPrimaryType01CountAdjust": 0,
    "lookPrimaryType02CountAdjust": 0,
    "lookPrimaryType10CountAdjust": 0,
    "lookPrimaryType11CountAdjust": 0,
    "lookPrimaryType12CountAdjust": 0,
    "lookPrimaryType20CountAdjust": 0,
    "lookPrimaryType21CountAdjust": 0,
    "lookPrimaryType22CountAdjust": 0,
    "lookPrimaryType30CountAdjust": 0,
    "lookPrimaryType31CountAdjust": 0,
    "lookPrimaryType32CountAdjust": 0,
    "lookBestType00CountAdjust": 0,
    "lookBestType01CountAdjust": 0,
    "lookBestType02CountAdjust": 0,
    "lookBestType10CountAdjust": 0,
    "lookBestType11CountAdjust": 0,
    "lookBestType12CountAdjust": 0,
    "lookBestType20CountAdjust": 0,
    "lookBestType21CountAdjust": 0,
    "lookBestType22CountAdjust": 0,
    "lookBestType30CountAdjust": 15,
    "lookBestType31CountAdjust": 15,
    "lookBestType32CountAdjust": 0,
    # Pitch identification and discipline ---------------------------------
    "idRatingBase": 25,
    "idRatingCHPct": 40,
    "idRatingExpPct": 30,
    "idRatingPitchRatPct": 0,
    "idRatingEaseScale": 1.0,
    "disciplineRatingBase": 0,
    "disciplineRatingCHPct": 150,
    "disciplineRatingExpPct": 100,
    "disciplineRatingPct": 100,
    "disciplineRatingNoPitchesAdjust": 0,
    "disciplineRatingScoringPosAdjust": 0,
    "disciplineRatingOnThird01OutsAdjust": 0,
    "disciplineRatingPlusZoneAdjust": -5,
    "disciplineRatingMinusZoneAdjust": -25,
    "disciplineRatingLocNextToLookAdjust": -5,
    "disciplineRatingFBDownMiddleAdjust": -30,
    "disciplineRating00CountAdjust": 5,
    "disciplineRating01CountAdjust": 35,
    "disciplineRating02CountAdjust": 15,
    "disciplineRating10CountAdjust": -5,
    "disciplineRating11CountAdjust": 15,
    "disciplineRating12CountAdjust": 5,
    "disciplineRating20CountAdjust": 0,
    "disciplineRating21CountAdjust": 10,
    "disciplineRating22CountAdjust": 15,
    "disciplineRating30CountAdjust": 60,
    "disciplineRating31CountAdjust": 5,
    "disciplineRating32CountAdjust": 15,
    "disciplineThreeBallScale": 0.5,
    "disciplineThreeBallPenaltyScale": 0.5,
    "swingBallDisciplineWeight": 0.20,
    "swingBallThreeBallWeightScale": 0.6,
    "disciplineZoneProtectWeightDefault": 0.34,
    "disciplineChaseProtectWeightDefault": 0.52,
    "disciplineZoneBiasDefault": 0.16,
    "disciplineChaseBiasDefault": 0.24,
    # Baseline contact chance when the batter misreads the pitch
    "minMisreadContact": 0.3,
    # Final contact multiplier applied to swing decisions
    # Lowered to reintroduce swing-and-miss outcomes while keeping run scoring in line
    "contactQualityScale": 1.34,
    "contactOutcomeScale": 0.70,
    # Scaling factors for batter skills impacting contact quality
    "contactAbilityScale": 0.4,
    "contactDisciplineScale": 0.3,
    "missChanceScale": 1.6,
    # Check-swing tuning ---------------------------------------------------
    "checkChanceBasePower": 150,
    "checkChanceBaseNormal": 250,
    "checkChanceBaseContact": 350,
    "checkChanceBaseBunt": 150,
    "checkChanceCHPctPower": 225,
    "checkChanceCHPctNormal": 265,
    "checkChanceCHPctContact": 305,
    "checkChanceCHPctBunt": 0,
    # Timing curve thresholds and dice ------------------------------------
    "timingVeryBadThresh": 40,
    "timingVeryBadCount": 7,
    "timingVeryBadFaces": 16,
    "timingVeryBadBase": -59,
    "timingBadThresh": 60,
    "timingBadCount": 7,
    "timingBadFaces": 16,
    "timingBadBase": -59,
    "timingMedThresh": 70,
    "timingMedCount": 7,
    "timingMedFaces": 15,
    "timingMedBase": -56,
    "timingGoodThresh": 80,
    "timingGoodCount": 7,
    "timingGoodFaces": 15,
    "timingGoodBase": -56,
    "timingVeryGoodCount": 9,
    "timingVeryGoodFaces": 13,
    "timingVeryGoodBase": -63,
    # Offensive manager ----------------------------------------------------
    "stealChance00Count": 0,
    "stealChance01Count": 0,
    "stealChance02Count": -10,
    "stealChance10Count": 10,
    "stealChance11Count": 0,
    "stealChance12Count": -10,
    "stealChance20Count": 15,
    "stealChance21Count": 5,
    "stealChance22Count": 0,
    "stealChance30Count": 15,
    "stealChance31Count": 15,
    "stealChance32Count": 20,
    "offManStealChancePct": 45,
    # Minimum probability thresholds to gate steal attempts (0..1).
    # Defaults are 0 to avoid changing behaviour in tests unless overridden.
    "stealAttemptMinProb": 0.4,
    "stealMinSuccessProb": 0.65,
    "closeBallTakeBonus": 0.0,
    "sureBallTakeBonus": 0.0,
    "autoTakeCloseBallBaseProb": 0.55,
    "autoTakeSureBallBaseProb": 0.35,
    "autoTakeDistanceWeight": 0.25,
    "autoTakeBallCountWeight": 0.14,
    "autoTakeStrikeCountWeight": -0.08,
    "autoTakeAggressionWeight": 0.25,
    "autoTakeThreeBallBonus": 0.20,
    "autoTakeFullCountBonus": 0.12,
    "autoTakeTwoStrikePenalty": 0.10,
    "autoTakeGlobalMaxProb": 0.90,
    "twoStrikeContactFloor": 0.0,
    "twoStrikeContactQuality": 0.0,
    "stealSuccessTagOutPct": 18,
    "stealSuccessSafePct": 82,
    "stealChanceVerySlowThresh": 13,
    "stealChanceVerySlowAdjust": -40,
    "stealChanceSlowThresh": 27,
    "stealChanceSlowAdjust": -10,
    "stealChanceMedThresh": 60,
    "stealChanceMedAdjust": 0,
    "stealChanceFastThresh": 80,
    "stealChanceFastAdjust": 20,
    "stealChanceVeryFastAdjust": 25,
    "stealChanceVeryLowHoldThresh": 19,
    "stealChanceVeryLowHoldAdjust": 15,
    "stealChanceLowHoldThresh": 39,
    "stealChanceLowHoldAdjust": 5,
    "stealChanceMedHoldThresh": 65,
    "stealChanceMedHoldAdjust": 0,
    "stealChanceHighHoldThresh": 74,
    "stealChanceHighHoldAdjust": -10,
    "stealChanceVeryHighHoldAdjust": -20,
    "stealChancePitcherFaceAdjust": -5,
    "stealChancePitcherBackAdjust": 5,
    "stealChancePitcherWindupAdjust": 5,
    "stealChancePitcherWildAdjust": 0,
    "stealChanceOnFirst2OutHighCHThresh": 60,
    "stealChanceOnFirst2OutHighCHAdjust": 10,
    "stealChanceOnFirst2OutLowCHThresh": 27,
    "stealChanceOnFirst2OutLowCHAdjust": -25,
    "stealChanceOnFirst01OutHighCHThresh": 60,
    "stealChanceOnFirst01OutHighCHAdjust": 15,
    "stealChanceOnFirst01OutLowCHThresh": 27,
    "stealChanceOnFirst01OutLowCHAdjust": -15,
    "stealChanceOnSecond0OutAdjust": -15,
    "stealChanceOnSecond1OutAdjust": 0,
    "stealChanceOnSecond2OutAdjust": -30,
    "stealChanceOnSecondHighCHThresh": 55,
    "stealChanceOnSecondHighCHAdjust": 5,
    "stealChanceWayBehindThresh": -3,
    "stealChanceWayBehindAdjust": -70,
    # Runtime tuning hooks for steal calibration
    "stealAttemptAggressionScale": 1.0,
    "stealSuccessAdjustment": 0.0,
    "stealDefensivePenaltyScale": 1.0,
    "hnrChanceBase": 0,
    "hnrChance3MoreBehindAdjust": 0,
    "hnrChance2BehindAdjust": 0,
    "hnrChance1AheadAdjust": 0,
    "hnrChance2MoreAheadAdjust": 0,
    "hnrChanceOn12Adjust": 0,
    "hnrChancePitcherWildAdjust": 0,
    "hnrChance3BallsAdjust": 0,
    "hnrChance2StrikesAdjust": 0,
    "hnrChanceEvenCountAdjust": 0,
    "hnrChance01CountAdjust": 0,
    "hnrChanceSlowSPThresh": 0,
    "hnrChanceSlowSPAdjust": 0,
    "hnrChanceMedSPThresh": 0,
    "hnrChanceMedSPAdjust": 0,
    "hnrChanceFastSPThresh": 0,
    "hnrChanceFastSPAdjust": 0,
    "hnrChanceVeryFastSPAdjust": 0,
    "hnrChanceLowCHThresh": 0,
    "hnrChanceLowCHAdjust": 0,
    "hnrChanceMedCHThresh": 0,
    "hnrChanceMedCHAdjust": 0,
    "hnrChanceHighCHThresh": 0,
    "hnrChanceHighCHAdjust": 0,
    "hnrChanceVeryHighCHAdjust": 0,
    "hnrChanceLowPHThresh": 0,
    "hnrChanceLowPHAdjust": 0,
    "hnrChanceMedPHThresh": 0,
    "hnrChanceMedPHAdjust": 0,
    "hnrChanceHighPHThresh": 0,
    "hnrChanceHighPHAdjust": 0,
    "hnrChanceVeryHighPHAdjust": 0,
    "offManHNRChancePct": 0,
    "sacChanceMaxCH": 1000,
    "sacChanceMaxPH": 1000,
    "sacChanceBase": 0,
    "sacChancePitcherAdjust": 0,
    "sacChance1OutAdjust": 0,
    "sacChanceCLAdjust": 0,
    "sacChanceCL0OutOn12Adjust": 0,
    "sacChanceCLLowCHThresh": 0,
    "sacChanceCLLowPHThresh": 0,
    "sacChanceCLLowCHPHAdjust": 0,
    "sacChancePitcherLowCHThresh": 0,
    "sacChancePitcherLowPHThresh": 0,
    "sacChancePitcherLowCHPHAdjust": 0,
    "offManSacChancePct": 0,
    "squeezeChanceMaxCH": 1000,
    "squeezeChanceMaxPH": 1000,
    "offManSqueezeChancePct": 0,
    "squeezeChanceLowCountAdjust": 0,
    "squeezeChanceMedCountAdjust": 0,
    "squeezeChanceThirdFastSPThresh": 0,
    "squeezeChanceThirdFastAdjust": 0,
    # Defensive manager ----------------------------------------------------
    "chargeChanceBaseThird": 0,
    "chargeChanceSacChanceAdjust": 0,
    "defManChargeChancePct": 0,
    "holdChanceBase": 0,
    "holdChanceMinRunnerSpeed": 0,
    "holdChanceAdjust": 0,
    "pickoffChanceBase": 0,
    "pickoffChanceStealChanceAdjust": 0,
    "pickoffChanceLeadMult": 0,
    "pickoffChancePitchesMult": 0,
    "longLeadSpeed": 0,
    "pickoffScareSpeed": 0,
    "pitchOutChanceStealThresh": 0,
    "pitchOutChanceHitRunThresh": 0,
    "pitchOutChanceBase": 0,
    "pitchOutChanceBall0Adjust": 0,
    "pitchOutChanceBall1Adjust": 0,
    "pitchOutChanceBall2Adjust": 0,
    "pitchOutChanceBall3Adjust": 0,
    "pitchOutChanceInn8Adjust": 0,
    "pitchOutChanceInn9Adjust": 0,
    "pitchOutChanceHomeAdjust": 0,
    "pitchAroundChanceNoInn": 6,
    "pitchAroundChanceBase": 12,
    "pitchAroundChanceInn7Adjust": 3,
    "pitchAroundChanceInn9Adjust": 6,
    "pitchAroundChancePH2BatAdjust": 12,
    "pitchAroundChancePH1BatAdjust": 5,
    "pitchAroundChancePHBatAdjust": 3,
    "pitchAroundChancePHODAdjust": -6,
    "pitchAroundChancePH1ODAdjust": -12,
    "pitchAroundChancePH2ODAdjust": -24,
    "pitchAroundChanceCH2BatAdjust": 8,
    "pitchAroundChanceCH1BatAdjust": 3,
    "pitchAroundChanceCHBatAdjust": 0,
    "pitchAroundChanceCHODAdjust": -3,
    "pitchAroundChanceCH1ODAdjust": -8,
    "pitchAroundChanceCH2ODAdjust": -15,
    "pitchAroundChanceLowGFThresh": 45,
    "pitchAroundChanceLowGFAdjust": 3,
    "pitchAroundChanceOut0": 0,
    "pitchAroundChanceOut1": 3,
    "pitchAroundChanceOut2": 5,
    "pitchAroundChanceOn23": 3,
    "defManPitchAroundToIBBPct": 35,
    # Substitution manager -------------------------------------------------
    "doubleSwitchPHAdjust": 0,
    "doubleSwitchBase": 0,
    "doubleSwitchPitcherDueAdjust": 0,
    "doubleSwitchNoPrimaryPosAdjust": 0,
    "doubleSwitchNoQualifiedPosAdjust": 0,
    "doubleSwitchVeryHighCurrDefThresh": 0,
    "doubleSwitchHighCurrDefThresh": 0,
    "doubleSwitchMedCurrDefThresh": 0,
    "doubleSwitchLowCurrDefThresh": 0,
    "doubleSwitchVeryHighCurrDefAdjust": 0,
    "doubleSwitchHighCurrDefAdjust": 0,
    "doubleSwitchMedCurrDefAdjust": 0,
    "doubleSwitchLowCurrDefAdjust": 0,
    "doubleSwitchVeryLowCurrDefAdjust": 0,
    "doubleSwitchVeryHighNewDefThresh": 0,
    "doubleSwitchHighNewDefThresh": 0,
    "doubleSwitchMedNewDefThresh": 0,
    "doubleSwitchLowNewDefThresh": 0,
    "doubleSwitchVeryHighNewDefAdjust": 0,
    "doubleSwitchHighNewDefAdjust": 0,
    "doubleSwitchMedNewDefAdjust": 0,
    "doubleSwitchLowNewDefAdjust": 0,
    "doubleSwitchVeryLowNewDefAdjust": 0,
    "defSubBase": 0,
    "defSubBeforeInn7Adjust": 0,
    "defSubInn7Adjust": 0,
    "defSubInn8Adjust": 0,
    "defSubAfterInn8Adjust": 0,
    "defSubNoPrimaryPosAdjust": 0,
    "defSubNoQualifiedPosAdjust": 0,
    "defSubPerInjuryPointAdjust": 0,
    "defSubVeryHighCurrDefThresh": 0,
    "defSubHighCurrDefThresh": 0,
    "defSubMedCurrDefThresh": 0,
    "defSubLowCurrDefThresh": 0,
    "defSubVeryHighCurrDefAdjust": 0,
    "defSubHighCurrDefAdjust": 0,
    "defSubMedCurrDefAdjust": 0,
    "defSubLowCurrDefAdjust": 0,
    "defSubVeryLowCurrDefAdjust": 0,
    "defSubVeryHighNewDefThresh": 0,
    "defSubHighNewDefThresh": 0,
    "defSubMedNewDefThresh": 0,
    "defSubLowNewDefThresh": 0,
    "defSubVeryHighNewDefAdjust": 0,
    "defSubHighNewDefAdjust": 0,
    "defSubMedNewDefAdjust": 0,
    "defSubLowNewDefAdjust": 0,
    "defSubVeryLowNewDefAdjust": 0,
    "doubleSwitchChance": 0,
    "warmupPitchCount": 0,
    "warmupSecsPerWarmPitch": 30,
    "warmupSecsPerQuickPitch": 20,
    "warmupSecsPerMaintPitch": 120,
    "warmupSecsPerCoolPitch": 60,
    "warmupSecsBeforeCool": 1800,
    # Emergency bullpen usage controls (Usage Model V2)
    "emergencyOutsCap": 3,
    "emergencyReliefTaxPitches": 20,
    # Usage Model V2 (MLB-like bullpen usage & rest)
    # Feature flag to gate the new usage model behavior
    "enableUsageModelV2": 0,
    # Rest curve thresholds (pitches thrown → minimum days of rest)
    # Example: ≤ restDaysPitchesLvl0 ⇒ 0 days; ≤ Lvl1 ⇒ 1 day; …; above Lvl5 ⇒ 6 days
    "restDaysPitchesLvl0": 10,
    "restDaysPitchesLvl1": 20,
    "restDaysPitchesLvl2": 35,
    "restDaysPitchesLvl3": 50,
    "restDaysPitchesLvl4": 70,
    "restDaysPitchesLvl5": 95,
    # Back-to-back and consecutive-day rules
    "b2bMaxPriorPitches": 20,
    "forbidThirdConsecutiveDay": 1,
    # Budget override floor for high-leverage relief on consecutive days
    "reliefB2BBudgetFloor": 0.5,
    # Starter late-game warmup heuristics
    "starterLateWarmLeadMax": 3,
    "starterSeventhWarmChance": 60,
    "starterEighthWarmChance": 80,
    "starterSoftPitchLimitMultiplier": 1.6,
    "starterHardPitchLimitMultiplier": 1.85,
    "starterMinSoftPitchLimit": 95,
    "starterMinHardPitchLimit": 110,
    "closerBoostStuffFloor": 92,
    "closerBoostControlFloor": 68,
    "closerBoostControlCap": 80,
    "closerBoostEnduranceFloor": 52,
    # Rolling appearance caps by role (3-day and 7-day windows)
    "maxApps3Day_CL": 2,
    "maxApps3Day_SU": 2,
    "maxApps3Day_MR": 3,
    "maxApps3Day_LR": 2,
    "maxApps7Day_CL": 4,
    "maxApps7Day_SU": 4,
    "maxApps7Day_MR": 5,
    "maxApps7Day_LR": 4,
    # Warmup tax (virtual pitches when a reliever warms and does not enter)
    "warmupTaxPitches": 25,
    # Role outing caps (outs per appearance) – advisory; enforced in SubstitutionManager
    "maxOuts_CL": 4,
    "maxOuts_SU": 4,
    "maxOuts_MR": 6,
    "maxOuts_LR": 9,
    # Role priority helpers
    "starterEarlyOutsThresh": 12,
    "lrBlowoutMargin": 4,
    # Pitch budget (endurance-driven) defaults
    "pitchBudgetMultiplier_CL": 1.25,
    "pitchBudgetMultiplier_SU": 1.35,
    "pitchBudgetMultiplier_MR": 1.35,
    "pitchBudgetMultiplier_LR": 1.55,
    "pitchBudgetMultiplier_SP": 3.5,
    "pitchBudgetRecoveryPct_CL": 0.32,
    "pitchBudgetRecoveryPct_SU": 0.32,
    "pitchBudgetRecoveryPct_MR": 0.28,
    "pitchBudgetRecoveryPct_LR": 0.24,
    "pitchBudgetRecoveryPct_SP": 0.24,
    "pitchBudgetAvailThresh_CL": 0.5,
    "pitchBudgetAvailThresh_SU": 0.6,
    "pitchBudgetAvailThresh_MR": 0.68,
    "pitchBudgetAvailThresh_LR": 0.7,
    "pitchBudgetAvailThresh_SP": 0.7,
    "warmupPitchBase_CL": 10,
    "warmupPitchBase_SU": 12,
    "warmupPitchBase_MR": 12,
    "warmupPitchBase_LR": 18,
    "warmupPitchBase_SP": 20,
    "pitchBudgetFallbackEndurance_CL": 45,
    "pitchBudgetFallbackEndurance_SU": 45,
    "pitchBudgetFallbackEndurance_MR": 45,
    "pitchBudgetFallbackEndurance_LR": 60,
    "pitchBudgetFallbackEndurance_SP": 90,
    "warmupAvailabilityExponent": 1.2,
    "warmupAvailabilityFloor": 0.2,
    "pitchBudgetExhaustionPenaltyScale": 0.4,
    "pitchBudgetEmergencyLockoutDelta": 0.15,
    "pitcherTiredThresh": 0,
    # Pitcher substitution thresholds and scoring
    "pitchScoringOut": 1,
    "pitchScoringStrikeOut": 2,
    "pitchScoringOffRun": 2,
    "pitchScoringInnsAfter4": 2,
    "pitchScoringWalk": -1,
    "pitchScoringHit": -2,
    "pitchScoringConsHit": -1,
    "pitchScoringRun": -2,
    "pitchScoringER": -2,
    "pitchScoringHR": -3,
    "pitchScoringWP": -2,
    "pitchScoringCleanInning": 3,
    "starterToastThreshInn1": -75,
    "starterToastThreshInn2": -90,
    "starterToastThreshInn3": -90,
    "starterToastThreshInn4": -90,
    "starterToastThreshInn5": -75,
    "starterToastThreshInn6": -70,
    "starterToastThreshInn7": -66,
    "starterToastThreshInn8": -30,
    "starterToastThreshInn9": -26,
    "starterToastThreshPerInn": 6,
    "starterToastThreshAwayAdjust": 2,
    "starterToastThreshFewBullpenPitchesAdjust": -4,
    "starterToastThreshManyBullpenPitchesAdjust": 4,
    "pitcherExhaustedThresh": 0,
    "tiredPitchRatPct": 100,
    "tiredASPct": 100,
    "exhaustedPitchRatPct": 100,
    "exhaustedASPct": 100,
    "effCOPct": 100,
    "effMOPct": 100,
    "posPlayerPitchingRuns": 0,
    "pitcherToastPctPitchesLeft": 0,
    "pitcherToastMaxLead": 0,
    "pitcherToastMinLead": 0,
    # Pinch running chances and adjustments
    "prChanceOnFirstBase": 0,
    "prChanceOnSecondBase": 0,
    "prChanceOnThirdBase": 0,
    "prChanceWinningRun": 0,
    "prChanceTyingRun": 0,
    "prChanceInsignificant": 0,
    "prChancePerOutAdjust": 0,
    "prChanceEarlyInnAdjust": 0,
    "prChanceMidInnAdjust": 0,
    "prChanceLateInnAdjust": 0,
    "prChanceInn9Adjust": 0,
    "prChanceExtraInnAdjust": 0,
    "prChancePerBenchPlayerAdjust": 0,
    "prChancePerInjuryPointAdjust": 0,
    "prChanceVeryFastSPThresh": 0,
    "prChanceFastSPThresh": 0,
    "prChanceMedSPThresh": 0,
    "prChanceSlowSPThresh": 0,
    "prChanceVeryFastSPAdjust": 0,
    "prChanceFastSPAdjust": 0,
    "prChanceMedSPAdjust": 0,
    "prChanceSlowSPAdjust": 0,
    "prChanceVerySlowSPAdjust": 0,
    "prChanceVeryFastPRThresh": 0,
    "prChanceFastPRThresh": 0,
    "prChanceMedPRThresh": 0,
    "prChanceSlowPRThresh": 0,
    "prChanceVeryFastPRAdjust": 0,
    "prChanceFastPRAdjust": 0,
    "prChanceMedPRAdjust": 0,
    "prChanceSlowPRAdjust": 0,
    "prChanceVerySlowPRAdjust": 0,
    # Fielding AI -------------------------------------------------------
    "couldBeCaughtSlop": -18,
    "shouldBeCaughtSlop": 6,
    "generalSlop": 9,
    "relaySlop": 12,
    "tagTimeSlop": 6,
    "stepOnBagSlop": -5,
    "tagAtBagSlop": 4,
    "throwToBagSlop": 8,
    # Multipliers improving defensive efficiency
    "fielderReactionScale": 1.0,
    "throwSuccessScale": 1.1,
    # Strike zone dimensions (half-width/height in control-box units)
    # Use a full-width plate so strike/ball calculations align with MLB geometry.
    "plateWidth": 3,
    "plateHeight": 3,
}
_BASE_DEFAULTS = dict(_DEFAULTS)

# League benchmark metrics loaded from CSV for calibration
_BENCHMARK_PATH = (
    DATA_DIR / "MLB_avg" / "mlb_league_benchmarks_2025_filled.csv"
)
try:
    _benchmarks = load_league_benchmarks(_BENCHMARK_PATH)
except OSError:  # pragma: no cover - file may be missing in some envs
    _benchmarks = {}


@dataclass
class PlayBalanceConfig:
    """Container providing convenient access to ``PlayBalance`` entries.

    The class behaves similarly to a mapping.  Values can be retrieved via the
    :py:meth:`get` method or as attributes.  Missing keys return sensible
    defaults to keep the simulation logic simple and predictable for the unit
    tests.
    """

    values: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if "pitchCalibrationEnabled" not in self.values:
            self.values["pitchCalibrationEnabled"] = _DEFAULTS.get(
                "pitchCalibrationEnabled", 0
            )
        for key in (
            "pitchCalibrationTarget",
            "pitchCalibrationTolerance",
            "pitchCalibrationPerPlateCap",
            "pitchCalibrationPerGameCap",
            "pitchCalibrationMinPA",
            "pitchCalibrationPreferFoul",
            "pitchCalibrationEmaAlpha",
        ):
            if key not in self.values:
                self.values[key] = _DEFAULTS.get(key, 0)

    def __getstate__(self) -> Dict[str, Any]:
        return self.values

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.values = state

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlayBalanceConfig":
        """Create an instance from a mapping produced by :func:`load_pbini`.

        ``data`` may be either the full nested dictionary returned by
        :func:`load_pbini` or already the ``PlayBalance`` sub-section.
        """

        if "PlayBalance" in data and isinstance(data["PlayBalance"], dict):
            section = data["PlayBalance"]
        else:
            section = data
        # Copy to avoid accidental sharing
        return cls(dict(section))

    @classmethod
    def from_file(cls, path: str | Path) -> "PlayBalanceConfig":
        """Load a PB.INI style file and return the ``PlayBalance`` section."""

        pbini = load_pbini(path)
        return cls.from_dict(pbini)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    @classmethod
    def load_overrides(cls, path: Path | None = None) -> Dict[str, Any]:
        """Merge overrides from ``path`` into the module defaults."""

        path = _OVERRIDE_PATH if path is None else path
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    _DEFAULTS.update(data)
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def save_overrides(self, path: Path | None = None) -> None:
        """Persist current values to ``path`` as overrides."""

        path = _OVERRIDE_PATH if path is None else path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(self.values, fh, indent=2, sort_keys=True)
        _DEFAULTS.update(self.values)

    def reset(self, path: Path | None = None) -> None:
        """Reset configuration and remove any saved overrides."""

        path = _OVERRIDE_PATH if path is None else path
        self.values.clear()
        _DEFAULTS.clear()
        _DEFAULTS.update(_BASE_DEFAULTS)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def exit_velo_base(self) -> int:
        """Base exit velocity for batted balls."""
        return int(self.exitVeloBase)

    @property
    def exit_velo_ph_pct(self) -> int:
        """Pinch hitter adjustment percentage for exit velocity."""
        return int(self.exitVeloPHPct)

    @property
    def exit_velo_power_pct(self) -> int:
        """Exit velocity percentage for power swings."""
        return int(self.exitVeloPowerPct)

    @property
    def exit_velo_normal_pct(self) -> int:
        """Exit velocity percentage for normal swings."""
        return int(self.exitVeloNormalPct)

    @property
    def exit_velo_slope(self) -> float:
        """Slope applied to ratings when computing exit velocity."""
        return float(self.exitVeloSlope)

    @property
    def exit_velo_contact_pct(self) -> int:
        """Exit velocity percentage for contact swings."""
        return int(self.exitVeloContactPct)

    @property
    def vert_angle_gf_pct(self) -> int:
        """Ground/fly ratio adjustment for vertical launch angle."""
        return int(self.vertAngleGFPct)

    @property
    def spray_angle_pl_pct(self) -> int:
        """Pull/line percentage for spray angle distribution."""
        return int(self.sprayAnglePLPct)

    @property
    def ground_ball_base_rate(self) -> int:
        """Baseline percentage of batted balls that are grounders."""
        return int(self.groundBallBaseRate)

    @property
    def fly_ball_base_rate(self) -> int:
        """Baseline percentage of batted balls that are fly balls."""
        return int(self.flyBallBaseRate)

    @property
    def line_drive_base_rate(self) -> int:
        """Baseline percentage of batted balls that are line drives."""
        return int(self.lineDriveBaseRate)

    @property
    def bip_power_weight(self) -> float:
        """Weight for batter power influence on batted ball distribution."""
        return float(self.bipPowerWeight)

    @property
    def bip_launch_weight(self) -> float:
        """Weight for batter launch tendency influence."""
        return float(self.bipLaunchWeight)

    @property
    def bip_movement_weight(self) -> float:
        """Weight for pitcher movement influence on batted ball distribution."""
        return float(self.bipMovementWeight)

    @property
    def hit_prob_base(self) -> float:
        """Baseline additive probability for a ball in play to become a hit."""
        return float(self.hitProbBase) * 0.1

    @property
    def contact_factor_base(self) -> float:
        """Base multiplier applied to the batter's contact rating."""
        return float(self.contactFactorBase)

    @property
    def contact_factor_div(self) -> float:
        """Divisor for converting contact rating into the hit calculation."""
        return float(self.contactFactorDiv)

    @property
    def movement_factor_min(self) -> float:
        """Minimum adjustment from pitcher movement in hit probability."""
        return float(self.movementFactorMin)

    @property
    def movement_impact_scale(self) -> float:
        """Scale applied to pitcher movement's effect in hit probability."""
        return float(self.movementImpactScale)

    @property
    def babip_scale(self) -> float:
        """Additional scaling factor for outs on balls in play."""
        return float(self.babipScale)

    @babip_scale.setter
    def babip_scale(self, value: float) -> None:
        """Set scaling factor for outs on balls in play."""
        self.babipScale = value

    @property
    def extra_z_swing_scale(self) -> float:
        """Additional scaling applied to zone swing probability."""
        return float(self.extraZSwingScale)

    @extra_z_swing_scale.setter
    def extra_z_swing_scale(self, value: float) -> None:
        """Set additional scaling for zone swing probability."""
        self.extraZSwingScale = value

    @property
    def extra_o_swing_scale(self) -> float:
        """Additional scaling applied to out-of-zone swing probability."""
        return float(self.extraOSwingScale)

    @extra_o_swing_scale.setter
    def extra_o_swing_scale(self, value: float) -> None:
        """Set additional scaling for out-of-zone swing probability."""
        self.extraOSwingScale = value

    # ------------------------------------------------------------------
    # Mapping style helpers
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = 0) -> Any:
        """Return ``key`` from the configuration or ``default`` if missing."""

        value = self.values.get(key, _DEFAULTS.get(key, default))
        if value is None:
            return _DEFAULTS.get(key, default)
        return value

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - simple delegation
        values = self.__dict__.get("values", {})
        return values.get(item, _DEFAULTS.get(item, 0))

    def __setattr__(self, key: str, value: Any) -> None:  # pragma: no cover - simple
        if key == "values":
            super().__setattr__(key, value)
        else:
            self.values[key] = value


if _benchmarks:
    _DEFAULTS["ballInPlayPitchPct"] = int(
        round(_benchmarks.get("pitches_put_in_play_pct", 0.175) * 100)
    ) - 1
    # Disable pitch injection to let natural swing decisions set Pitches/PA
    # Aim for MLB-like pitches per plate appearance; allow engine to
    # inject non-decisive pitches to reach the target on average.
    _DEFAULTS["targetPitchesPerPA"] = _benchmarks.get("pitches_per_pa", 4.0)
    dp_pct = _benchmarks.get("bip_double_play_pct", 0.028)
    gb_pct = _benchmarks.get("bip_gb_pct", 0.44)
    if gb_pct:
        # Moderate calibration bump so DP probability approaches MLB in-season.
        base_dp = dp_pct / gb_pct
        _DEFAULTS["doublePlayProb"] = round(min(1.0, max(0.0, base_dp + 0.08)), 3)

# Apply overrides after incorporating league benchmark defaults so that any
# manual tuning in ``playbalance_overrides.json`` takes precedence.
PlayBalanceConfig.load_overrides()


__all__ = ["PlayBalanceConfig"]
