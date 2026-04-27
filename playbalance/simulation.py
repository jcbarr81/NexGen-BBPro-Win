from __future__ import annotations

import inspect
import math
import random
import os
from collections import defaultdict
from dataclasses import dataclass, field, fields, replace
from typing import Any, Dict, List, Optional, Tuple

from models.player import Player
from models.pitcher import Pitcher
from models.team import Team
from playbalance.defensive_manager import DefensiveManager
from playbalance.offensive_manager import OffensiveManager
from playbalance.substitution_manager import SubstitutionManager
from playbalance.playbalance_config import PlayBalanceConfig
from playbalance.physics import Physics, bat_impact as bat_impact_func
from playbalance.pitcher_ai import PitcherAI
from playbalance.batter_ai import BatterAI
from playbalance.diagnostics.batter_decision import BatterDecisionTracker
from playbalance.diagnostics.pitch_survival import PitchSurvivalTracker
from playbalance.diagnostics.pitch_intent import bucket_for_objective
from playbalance.diagnostics.events import (
    DiagnosticsRecorder,
    PitchEvent,
    PlateAppearanceEvent,
    SwingDecisionEvent,
)
from playbalance.pitch_resolution import resolve_pitch
from playbalance.bullpen import WarmupTracker
from playbalance.fielding_ai import FieldingAI
from playbalance.field_geometry import DEFAULT_POSITIONS, Stadium, FIRST_BASE, SECOND_BASE
from utils.park_utils import stadium_from_name, park_factor_for_name
from playbalance.state import PitcherState
from utils.path_utils import get_base_dir, get_data_dir
from utils.putout_probabilities import load_putout_probabilities
from utils.stats_persistence import save_stats
from services.injury_simulator import InjurySimulator
from .stats import (
    compute_batting_derived,
    compute_batting_rates,
    compute_pitching_derived,
    compute_pitching_rates,
    compute_fielding_derived,
    compute_fielding_rates,
    compute_team_derived,
    compute_team_rates,
)

from .constants import PITCH_RATINGS


@dataclass(slots=True)
class BatterState:
    """Tracks state and statistics for a batter during the game."""

    player: Player
    pa: int = 0  # Plate appearances
    ab: int = 0  # At bats
    r: int = 0  # Runs scored
    h: int = 0  # Hits
    b1: int = 0  # Singles
    b2: int = 0  # Doubles
    b3: int = 0  # Triples
    hr: int = 0  # Home runs
    rbi: int = 0  # Runs batted in
    bb: int = 0  # Walks
    ibb: int = 0  # Intentional walks
    hbp: int = 0  # Hit by pitch
    so: int = 0  # Strikeouts
    so_looking: int = 0  # Called third strikes
    so_swinging: int = 0  # Swinging strikeouts
    sh: int = 0  # Sacrifice hits
    sf: int = 0  # Sacrifice flies
    roe: int = 0  # Reached on error
    fc: int = 0  # Fielder's choice
    ci: int = 0  # Catcher's interference
    gidp: int = 0  # Ground into double play
    sb: int = 0  # Stolen bases
    cs: int = 0  # Caught stealing
    po: int = 0  # Pickoffs
    pocs: int = 0  # Pickoff caught stealing
    pitches: int = 0  # Pitches seen
    lob: int = 0  # Left on base
    lead: int = 0  # Lead level
    gb: int = 0  # Ground balls put in play
    ld: int = 0  # Line drives put in play
    fb: int = 0  # Fly balls put in play



@dataclass(slots=True)
class FieldingState:
    """Tracks defensive statistics for a player."""

    player: Player
    g: int = 0  # Games fielded
    gs: int = 0  # Games started
    po: int = 0  # Putouts
    a: int = 0  # Assists
    e: int = 0  # Errors
    dp: int = 0  # Double plays
    tp: int = 0  # Triple plays
    pk: int = 0  # Pickoffs
    pb: int = 0  # Passed balls
    ci: int = 0  # Catcher's interference
    cs: int = 0  # Runners caught stealing
    sba: int = 0  # Stolen base attempts against


@dataclass(slots=True)
class TeamState:
    """Mutable state for a team during a game."""

    lineup: List[Player]
    bench: List[Player]
    pitchers: List[Pitcher]
    team: Team | None = None
    lineup_stats: Dict[str, BatterState] = field(default_factory=dict)
    pitcher_stats: Dict[str, PitcherState] = field(default_factory=dict)
    fielding_stats: Dict[str, FieldingState] = field(default_factory=dict)
    batting_index: int = 0
    bases: List[Optional[BatterState]] = field(default_factory=lambda: [None, None, None])
    base_pitchers: List[Optional[PitcherState]] = field(
        default_factory=lambda: [None, None, None]
    )
    runs: int = 0
    inning_runs: List[int] = field(default_factory=list)
    lob: int = 0
    inning_lob: List[int] = field(default_factory=list)
    inning_events: List[List[str]] = field(default_factory=list)
    team_stats: Dict[str, float] = field(default_factory=dict)
    warming_reliever: bool = False
    bullpen_warmups: Dict[str, WarmupTracker] = field(default_factory=dict)
    current_pitcher_state: PitcherState | None = None
    # Precomputed per-pitcher usage/rest status for the current date (optional)
    usage_status: Dict[str, Dict[str, object]] = field(default_factory=dict)
    # Emergency controls for reliever outing caps (pid -> outs cap)
    forced_out_limit_by_pid: Dict[str, int] = field(default_factory=dict)
    # Post-game recovery penalties to apply (pid -> virtual tax pitches)
    postgame_recovery_penalties: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.pitchers:
            starter = self.pitchers[0]
            state = PitcherState()
            state.player = starter
            self.pitcher_stats[starter.player_id] = state
            self.current_pitcher_state = state
            state.g = getattr(state, "g", 0) + 1
            state.gs = getattr(state, "gs", 0) + 1
            state.toast = 0.0
            state.is_toast = False
            state.consecutive_hits = 0
            state.consecutive_baserunners = 0
            state.allowed_hr = False
            state.appearance_outs = 0
            fs = self.fielding_stats.setdefault(starter.player_id, FieldingState(starter))
            fs.g += 1
            fs.gs += 1
        else:
            self.current_pitcher_state = None
        for p in self.lineup:
            fs = self.fielding_stats.setdefault(p.player_id, FieldingState(p))
            fs.g += 1
            fs.gs += 1

    def __getstate__(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def __setstate__(self, state):
        for name, value in state.items():
            setattr(self, name, value)


class GameSimulation:
    """A very small game simulation used for tests.

    The goal of this module is not to be feature complete, but to provide
    a minimal game loop that can reason about innings, at-bats and simple
    strategies such as pinch hitting, stealing and pitching changes.  The
    behaviour is heavily driven by values from the parsed PB.INI file so
    that tests can verify that configuration is respected.
    """

    _original_foul_probability = None

    def __init__(
        self,
        home: TeamState,
        away: TeamState,
        config: PlayBalanceConfig,
        rng: Optional[random.Random] = None,
        *,
        surface: str = "grass",
        wet: bool = False,
        temperature: float = 70.0,
        altitude: float = 0.0,
        wind_speed: float = 0.0,
        stadium: Stadium | None = None,
        game_date: str | None = None,
    ) -> None:
        self.home = home
        self.away = away
        self.config = config
        self.rng = rng or random.Random()
        self.defense = DefensiveManager(config, self.rng)
        self.offense = OffensiveManager(config, self.rng)
        self.subs = SubstitutionManager(config, self.rng)
        self.physics = Physics(config, self.rng)
        self.pitcher_ai = PitcherAI(config, self.rng)
        self.batter_ai = BatterAI(config)
        self.fielding_ai = FieldingAI(config, self.rng)
        if not getattr(self.config, "contactReductionLocked", False):
            if not getattr(self.config, "enableContactReduction", 0):
                self.config.enableContactReduction = 1
            if not getattr(self.config, "missChanceScale", 0):
                self.config.missChanceScale = 1.5
            if not getattr(self.config, "contactOutcomeScale", 0):
                self.config.contactOutcomeScale = 0.65
        self.debug_log: List[str] = []
        self._pitcher_of_record: dict[str, PitcherState | None] = {
            "home": self.home.current_pitcher_state,
            "away": self.away.current_pitcher_state,
        }
        self._losing_pitcher: PitcherState | None = None
        self.pitches_since_pickoff = 4
        self.current_outs = 0
        self.infield_fly: bool = False
        self.current_field_positions: Dict[
            str, Dict[str, Dict[str, Tuple[float, float]]]
        ] = {}
        self.current_infield_situation = "normal"
        self.current_outfield_situation = "normal"
        self.surface = surface
        self.wet = wet
        self.temperature = temperature
        self.altitude = altitude
        self.wind_speed = wind_speed
        # Stadium and park factor: use provided stadium; otherwise, derive from home team's selection
        if stadium is not None:
            self.stadium = stadium
            self.park_factor = 1.0
        else:
            derived: Stadium | None = None
            pf = 1.0
            if self.home and getattr(self.home, "team", None) is not None:
                try:
                    park_name = getattr(self.home.team, "stadium", "")
                except Exception:
                    park_name = ""
                if park_name:
                    derived = stadium_from_name(park_name)
                    pf = park_factor_for_name(park_name)
            self.stadium = derived or Stadium()
            self.park_factor = pf or 1.0
        self.last_batted_ball_angles: tuple[float, float] | None = None
        # Debug counters for double play diagnosis
        self.dp_candidates: int = 0
        self.dp_attempts: int = 0
        self.dp_made: int = 0
        self.last_ground_fielder: str | None = None
        self.last_batted_ball_type: str | None = None
        self.last_pitch_speed: float | None = None
        self.batter_decision_tracker: BatterDecisionTracker | None = None
        self.pitch_survival_tracker: PitchSurvivalTracker | None = None
        self.diagnostics_recorder: DiagnosticsRecorder | None = None
        self._active_plate_appearance: PlateAppearanceEvent | None = None
        self._half_inning_label: str | None = None
        self._current_inning_number: int | None = None
        self._pending_batter_decision: dict[str, Any] | None = None
        self.pitch_distance_histogram: dict[int, int] = defaultdict(int)
        data_dir = get_data_dir()
        data_path = (
            data_dir
            / "MLB_avg"
            / "Average_Putouts_per_Game_by_Position__Last_5_Years_.csv"
        )
        self.target_putout_probs = load_putout_probabilities(data_path)
        self.outs_by_position: Dict[str, int] = {
            "P": 0,
            "C": 0,
            "1B": 0,
            "2B": 0,
            "3B": 0,
            "SS": 0,
            "LF": 0,
            "CF": 0,
            "RF": 0,
        }
        self.total_putouts = 0
        self.two_strike_counts = 0
        self.three_ball_counts = 0
        self.logged_strikeouts = 0
        self.logged_catcher_putouts = 0
        self._last_swing_strikeout = False
        self._hit_and_run_active = False
        self._force_hit_and_run_grounder = False
        self._skip_next_ball_count = False
        original_fp = GameSimulation._original_foul_probability
        current_fp = getattr(self._foul_probability, "__func__", self._foul_probability)
        self._fouls_disabled = (
            original_fp is not None and current_fp is not original_fp
        )
        env_flag = os.getenv("PB_ENABLE_SIM_INJURIES")
        if env_flag is None:
            # Disable injuries by default until league-wide stats are rebalanced.
            self._injuries_enabled = False
        else:
            normalized_flag = env_flag.strip().lower()
            self._injuries_enabled = normalized_flag in {"1", "true", "yes", "on"}
        self.injury_simulator: InjurySimulator | None = (
            InjurySimulator() if self._injuries_enabled else None
        )
        self.injury_events: List[Dict[str, object]] = []
        self.game_date = game_date

    def _closer_state(self, team: TeamState) -> PitcherState | None:
        for pitcher in team.pitchers:
            role = str(getattr(pitcher, "assigned_pitching_role", "") or "").upper()
            if role == "CL":
                return team.pitcher_stats.setdefault(pitcher.player_id, PitcherState(pitcher))
        return None

    # ------------------------------------------------------------------
    # Pitcher helpers
    # ------------------------------------------------------------------
    def _credit_pitcher_outs(self, pitcher_state: PitcherState, outs: int) -> None:
        """Increment recorded outs for the current pitcher and outing."""

        if outs <= 0:
            return
        pitcher_state.outs += outs
        pitcher_state.appearance_outs = getattr(pitcher_state, "appearance_outs", 0) + outs

    def _pitch_target_offset(self, objective: str, control_roll: float) -> tuple[float, float]:
        """Return target offsets for the selected pitch objective."""

        bucket = bucket_for_objective(str(objective))
        if bucket == "zone":
            return 0.0, 0.0

        plate_w = float(getattr(self.config, "plateWidth", 3))
        plate_h = float(getattr(self.config, "plateHeight", 3))
        max_dim = max(plate_w, plate_h)
        edge_offset = float(
            self.config.get("pitchTargetEdgeOffset", max_dim * 0.85)
        )
        waste_offset = float(
            self.config.get("pitchTargetWasteOffset", max_dim * 1.35)
        )
        variance = float(
            self.config.get("pitchTargetAimVariance", max_dim * 0.35)
        )
        cross_spread = float(
            self.config.get("pitchTargetCrossSpread", max_dim * 0.25)
        )
        use_waste_offset = bucket == "waste"
        base_mag = waste_offset if use_waste_offset else edge_offset
        mag_roll = self.rng.random()
        magnitude = max(0.0, base_mag + (mag_roll - 0.5) * variance)
        cross_offset = (mag_roll - 0.5) * cross_spread

        axis_roll = control_roll
        if axis_roll < 0.5:
            dir_roll = axis_roll
            direction = -1.0 if dir_roll < 0.25 else 1.0
            return direction * magnitude, cross_offset

        dir_roll = axis_roll - 0.5
        direction = -1.0 if dir_roll < 0.25 else 1.0
        return cross_offset, direction * magnitude

    # ------------------------------------------------------------------
    # Injury helpers
    # ------------------------------------------------------------------
    def _injuries_active_for_team(self, team: TeamState) -> bool:
        if not self._injuries_enabled or self.injury_simulator is None:
            return False
        team_obj = getattr(team, "team", None)
        team_id = getattr(team_obj, "team_id", None)
        return bool(team_id)

    def set_batter_decision_tracker(
        self, tracker: BatterDecisionTracker | None
    ) -> None:
        """Attach a BatterDecisionTracker for per-pitch swing/take logging."""

        self.batter_decision_tracker = tracker

    def set_pitch_survival_tracker(
        self, tracker: PitchSurvivalTracker | None
    ) -> None:
        """Attach a tracker that records pitches per plate appearance."""

        self.pitch_survival_tracker = tracker

    def set_diagnostics_recorder(
        self, recorder: DiagnosticsRecorder | None
    ) -> None:
        """Attach a diagnostics recorder for pitch/plate-appearance events."""

        self.diagnostics_recorder = recorder

    def _log_batter_decision(
        self,
        *,
        balls: int,
        strikes: int,
        in_zone: bool,
        swing: bool,
        contact: bool,
        foul: bool,
        ball_in_play: bool,
        hit: bool,
        ball: bool,
        called_strike: bool,
        walk: bool,
        strikeout: bool,
        hbp: bool,
        breakdown: dict[str, float | str] | None,
        objective: str = "zone",
        target_offset: tuple[float, float] | None = None,
        pitch_distance: float | None = None,
        pitch_dx: float | None = None,
        pitch_dy: float | None = None,
        pitch_type: str | None = None,
        pitch_speed: float | None = None,
        contact_quality: float | None = None,
        result: str | None = None,
        auto_take: bool = False,
        auto_take_reason: str | None = None,
        auto_take_threshold: float | None = None,
        auto_take_distance: float | None = None,
    ) -> None:
        if result is None and auto_take:
            result = "auto_take"
        if result is None:
            if walk:
                result = "walk"
            elif hbp:
                result = "hbp"
            elif strikeout:
                result = "strikeout_swinging" if swing else "strikeout_looking"
            elif hit:
                result = "hit"
            elif ball_in_play:
                result = "in_play_out"
            elif foul:
                result = "foul"
            elif ball:
                result = "ball"
            elif called_strike:
                result = "called_strike"
        tracker = self.batter_decision_tracker
        if tracker is not None:
            tracker.record(
                balls=balls,
                strikes=strikes,
                in_zone=in_zone,
                swing=swing,
                contact=contact,
                foul=foul,
                ball_in_play=ball_in_play,
                hit=hit,
                ball=ball,
                called_strike=called_strike,
                walk=walk,
                strikeout=strikeout,
                hbp=hbp,
                breakdown=breakdown,
                objective=objective,
                target_offset=target_offset,
                pitch_distance=pitch_distance,
                pitch_dx=pitch_dx,
                pitch_dy=pitch_dy,
            )
        self._record_pitch_event(
            balls=balls,
            strikes=strikes,
            objective=objective,
            target_offset=target_offset,
            in_zone=in_zone,
            pitch_type=pitch_type,
            pitch_speed=pitch_speed,
            pitch_distance=pitch_distance,
            pitch_dx=pitch_dx,
            pitch_dy=pitch_dy,
            decision={
                "swing": swing,
                "contact": contact,
                "foul": foul,
                "ball_in_play": ball_in_play,
                "hit": hit,
                "ball": ball,
                "called_strike": called_strike,
                "walk": walk,
                "strikeout": strikeout,
                "hbp": hbp,
                "contact_quality": contact_quality,
                "result": result,
                "auto_take": auto_take,
                "auto_take_reason": auto_take_reason,
                "auto_take_threshold": auto_take_threshold,
                "auto_take_distance": auto_take_distance,
            },
        )

    def _queue_batter_decision(
        self,
        *,
        balls: int,
        strikes: int,
        in_zone: bool,
        swing: bool,
        contact: bool,
        foul: bool,
        ball_in_play: bool,
        hit: bool,
        ball: bool,
        called_strike: bool,
        walk: bool,
        strikeout: bool,
        hbp: bool,
        breakdown: dict[str, float | str] | None,
        objective: str = "zone",
        target_offset: tuple[float, float] | None = None,
        immediate: bool = False,
        pitch_distance: float | None = None,
        pitch_dx: float | None = None,
        pitch_dy: float | None = None,
        pitch_type: str | None = None,
        pitch_speed: float | None = None,
        contact_quality: float | None = None,
        result: str | None = None,
        auto_take: bool = False,
        auto_take_reason: str | None = None,
        auto_take_threshold: float | None = None,
        auto_take_distance: float | None = None,
    ) -> None:
        if self.batter_decision_tracker is None and self.diagnostics_recorder is None:
            return
        self._pending_batter_decision = {
            "balls": balls,
            "strikes": strikes,
            "in_zone": in_zone,
            "swing": swing,
            "contact": contact,
            "foul": foul,
            "ball_in_play": ball_in_play,
            "hit": hit,
            "ball": ball,
            "called_strike": called_strike,
            "walk": walk,
            "strikeout": strikeout,
            "hbp": hbp,
            "breakdown": breakdown,
            "objective": objective,
            "target_offset": target_offset,
            "pitch_distance": pitch_distance,
            "pitch_dx": pitch_dx,
            "pitch_dy": pitch_dy,
            "pitch_type": pitch_type,
            "pitch_speed": pitch_speed,
            "contact_quality": contact_quality,
            "result": result,
            "auto_take": auto_take,
            "auto_take_reason": auto_take_reason,
            "auto_take_threshold": auto_take_threshold,
            "auto_take_distance": auto_take_distance,
        }
        if immediate:
            self._flush_batter_decision()

    def _flush_batter_decision(self) -> None:
        if (
            self.batter_decision_tracker is None
            and self.diagnostics_recorder is None
        ) or self._pending_batter_decision is None:
            self._pending_batter_decision = None
            return
        data = self._pending_batter_decision
        self._pending_batter_decision = None
        self._log_batter_decision(**data)

    def _start_plate_appearance_event(
        self,
        offense: TeamState,
        defense: TeamState,
        batter_state: BatterState,
        pitcher_state: PitcherState,
    ) -> None:
        recorder = self.diagnostics_recorder
        if recorder is None:
            self._active_plate_appearance = None
            return
        inning = self._current_inning_number or len(offense.inning_runs) + 1
        half = self._half_inning_label or ("top" if offense is self.away else "bottom")
        pa = PlateAppearanceEvent(
            inning=inning,
            half=half,
            batter_id=getattr(batter_state.player, "player_id", ""),
            pitcher_id=getattr(pitcher_state.player, "player_id", ""),
        )
        recorder.start_plate_appearance(pa)
        self._active_plate_appearance = pa

    def _record_pitch_event(
        self,
        *,
        balls: int,
        strikes: int,
        objective: str,
        target_offset: tuple[float, float] | None,
        in_zone: bool,
        pitch_type: str | None,
        pitch_speed: float | None,
        pitch_distance: float | None,
        pitch_dx: float | None,
        pitch_dy: float | None,
        decision: dict[str, Any],
    ) -> None:
        if pitch_distance is not None:
            bucket = int(round(pitch_distance))
            self.pitch_distance_histogram[bucket] += 1
        recorder = self.diagnostics_recorder
        pa = self._active_plate_appearance
        if recorder is None or pa is None:
            return
        decision_event = SwingDecisionEvent(
            swing=decision.get("swing", False),
            contact=decision.get("contact", False),
            foul=decision.get("foul", False),
            ball_in_play=decision.get("ball_in_play", False),
            hit=decision.get("hit", False),
            ball=decision.get("ball", False),
            called_strike=decision.get("called_strike", False),
            walk=decision.get("walk", False),
            strikeout=decision.get("strikeout", False),
            hbp=decision.get("hbp", False),
            contact_quality=decision.get("contact_quality"),
            result=decision.get("result"),
            auto_take=decision.get("auto_take", False),
            auto_take_reason=decision.get("auto_take_reason"),
            auto_take_threshold=decision.get("auto_take_threshold"),
            auto_take_distance=decision.get("auto_take_distance"),
        )
        event = PitchEvent(
            inning=pa.inning,
            half=pa.half,
            batter_id=pa.batter_id,
            pitcher_id=pa.pitcher_id,
            balls=balls,
            strikes=strikes,
            pitch_type=pitch_type or "",
            objective=objective,
            target_offset=target_offset,
            in_zone=in_zone,
            pitch_distance=pitch_distance,
            pitch_dx=pitch_dx,
            pitch_dy=pitch_dy,
            pitch_speed=pitch_speed,
            decision=decision_event,
        )
        recorder.record_pitch(event)

    def _finish_plate_appearance_event(
        self, *, result: str, outs: int, runs_scored: int = 0
    ) -> None:
        recorder = self.diagnostics_recorder
        pa = self._active_plate_appearance
        if recorder is None or pa is None:
            self._active_plate_appearance = None
            return
        recorder.finish_plate_appearance(
            result=result, outs=outs, runs_scored=runs_scored
        )
        self._active_plate_appearance = None

    def _complete_plate_appearance(
        self, *, result: str = "unknown", outs: int, outs_from_pick: int = 0, runs_scored: int = 0
    ) -> int:
        total_outs = outs + outs_from_pick
        if self.diagnostics_recorder is not None:
            self._finish_plate_appearance_event(
                result=result, outs=total_outs, runs_scored=runs_scored
            )
        return total_outs

    def get_pitch_distance_histogram(self) -> dict[int, int]:
        """Return a copy of the current pitch-distance histogram."""

        return dict(self.pitch_distance_histogram)

    def _maybe_apply_injury(
        self,
        trigger: str,
        player: Player,
        team: TeamState,
        context: Optional[Dict[str, float]] = None,
    ) -> None:
        if not self._injuries_active_for_team(team):
            return
        outcome = self.injury_simulator.maybe_create_injury(  # type: ignore[union-attr]
            trigger,
            player,
            context=context,
        )
        if outcome is None:
            return
        player.injured = True
        player.injury_description = outcome.description
        player.injury_list = outcome.dl_tier
        event = {
            "team_id": getattr(team.team, "team_id", None),
            "player_id": getattr(player, "player_id", ""),
            "trigger": trigger,
            "dl_tier": outcome.dl_tier,
            "days": outcome.days,
            "description": outcome.name,
            "severity": outcome.severity,
            "game_date": self.game_date,
        }
        self.injury_events.append(event)

    def _register_contact_play(
        self,
        runner: Optional[BatterState],
        offense: TeamState,
        defense: TeamState,
        *,
        trigger: str,
        fielder_positions: Optional[List[str]] = None,
    ) -> None:
        if runner is None:
            return
        context = {"speed": max(0.1, min(1.0, runner.player.sp / 100.0))}
        self._maybe_apply_injury(trigger, runner.player, offense, context=context)
        if fielder_positions:
            for pos in fielder_positions:
                fs = self._get_fielder(defense, pos)
                if fs is not None:
                    self._maybe_apply_injury(trigger, fs.player, defense, context=context)

    def _handle_hit_by_pitch_injury(
        self,
        batter_state: BatterState,
        offense: TeamState,
        pitch_speed: Optional[float],
    ) -> None:
        speed = pitch_speed or self.last_pitch_speed or 90.0
        context = {"pitch_velocity": max(0.5, min(1.5, speed / 90.0))}
        self._maybe_apply_injury("hit_by_pitch", batter_state.player, offense, context=context)

    def _evaluate_pitcher_overuse(self, team: TeamState) -> None:
        if not self._injuries_active_for_team(team):
            return
        starter_thresh = float(self.config.get("simPitcherOveruseStarterThresh", 110))
        reliever_thresh = float(self.config.get("simPitcherOveruseRelieverThresh", 45))
        for pitcher_state in team.pitcher_stats.values():
            pitches = getattr(pitcher_state, "pitches_thrown", 0)
            if pitches <= 0:
                continue
            role = str(getattr(pitcher_state.player, "assigned_pitching_role", "") or "")
            is_starter = (
                role.upper().startswith("SP")
                or getattr(pitcher_state, "gs", 0) > 0
            )
            threshold = starter_thresh if is_starter else reliever_thresh
            if threshold <= 0:
                continue
            if pitches < threshold:
                continue
            fatigue = getattr(pitcher_state.player, "fatigue", "fresh")
            context = {
                "stress_days": pitches / max(threshold, 1.0),
                "fatigue": 1.0 if fatigue == "exhausted" else 0.5 if fatigue == "tired" else 0.1,
            }
            self._maybe_apply_injury("pitcher_overuse", pitcher_state.player, team, context=context)

    # ------------------------------------------------------------------
    # Physics helper shims
    # ------------------------------------------------------------------
    def bat_impact(
        self, bat_speed: float, *, part: str = "sweet", rand: float | None = None
    ) -> tuple[float, float]:
        """Return exit velocity and power factor for a bat ``part``.

        Older versions of :class:`playbalance.physics.Physics` did not expose
        ``bat_impact``.  To remain compatible, this shim tries to use the
        method when available and otherwise falls back to the module level
        function.
        """

        if hasattr(self.physics, "bat_impact"):
            return self.physics.bat_impact(bat_speed, part=part, rand=rand)
        return bat_impact_func(
            self.config, bat_speed, part=part, rand=rand, rng=self.rng
        )

    # ------------------------------------------------------------------
    # Fatigue helpers
    # ------------------------------------------------------------------
    def _update_fatigue(self, state: PitcherState) -> None:
        remaining = state.player.endurance - state.pitches_thrown
        exhausted = self.config.get("pitcherExhaustedThresh", 0)
        tired = self.config.get("pitcherTiredThresh", 0)
        if remaining <= exhausted:
            state.player.fatigue = "exhausted"
        elif remaining <= tired:
            state.player.fatigue = "tired"
        else:
            state.player.fatigue = "fresh"

    def _fatigued_pitcher(self, pitcher: Pitcher) -> Pitcher:
        fatigue = getattr(pitcher, "fatigue", "fresh")
        pitch_mult = as_mult = co_mult = mo_mult = 1.0
        if fatigue == "tired":
            pitch_mult = self.config.get("tiredPitchRatPct", 100) / 100.0
            as_mult = self.config.get("tiredASPct", 100) / 100.0
            co_mult = self.config.get("effCOPct", 100) / 100.0
            mo_mult = self.config.get("effMOPct", 100) / 100.0
        elif fatigue == "exhausted":
            pitch_mult = self.config.get("exhaustedPitchRatPct", 100) / 100.0
            as_mult = self.config.get("exhaustedASPct", 100) / 100.0
            co_mult = self.config.get("effCOPct", 100) / 100.0
            mo_mult = self.config.get("effMOPct", 100) / 100.0
        scaled = replace(pitcher)
        for attr in PITCH_RATINGS:
            setattr(scaled, attr, int(getattr(pitcher, attr) * pitch_mult))
        scaled.arm = int(pitcher.arm * as_mult)
        scaled.control = int(pitcher.control * co_mult)
        scaled.movement = int(pitcher.movement * mo_mult)
        penalty_scale = float(self.config.get("pitchBudgetExhaustionPenaltyScale", 0.0) or 0.0)
        if penalty_scale:
            budget_pct = getattr(pitcher, "budget_available_pct", 1.0)
            try:
                budget_pct = float(budget_pct)
            except (TypeError, ValueError):
                budget_pct = 1.0
            start_pct = float(getattr(self.config, "pitchBudgetExhaustionPenaltyStartPct", 0.5) or 0.5)
            # Clamp to sane bounds to avoid div-by-zero
            start_pct = max(0.01, min(1.0, start_pct))
            if budget_pct < start_pct:
                # Normalize deficit to 0..1 over the configured window
                deficit = (start_pct - budget_pct) / start_pct
                factor = max(0.1, 1.0 - penalty_scale * deficit)
                for attr in PITCH_RATINGS:
                    setattr(scaled, attr, int(getattr(scaled, attr) * factor))
                scaled.arm = int(scaled.arm * factor)
                scaled.control = int(scaled.control * factor)
                scaled.movement = int(scaled.movement * factor)
        return scaled

    # ------------------------------------------------------------------
    # Stat helpers
    # ------------------------------------------------------------------
    def _add_stat(self, state: BatterState, attr: str, amount: int = 1) -> None:
        """Increment ``attr`` on ``state``."""

        setattr(state, attr, getattr(state, attr) + amount)
        if (
            attr == "pitches"
            and amount > 0
            and isinstance(state, BatterState)
            and self.pitch_survival_tracker is not None
        ):
            self.pitch_survival_tracker.record_plate(amount)

    def _record_ball(self, pitcher_state: PitcherState) -> None:
        if self._skip_next_ball_count:
            self._skip_next_ball_count = False
            return
        pitcher_state.balls_thrown += 1

    def _add_fielding_stat(
        self,
        state: FieldingState,
        attr: str,
        amount: int = 1,
        *,
        position: str | None = None,
    ) -> None:
        """Increment ``attr`` on ``state``.

        When recording a putout the credited position is tracked to allow
        comparison with MLB averages and to dynamically adjust fielding
        behaviour.
        """

        setattr(state, attr, getattr(state, attr) + amount)

        if attr == "po":
            pos = (position or getattr(state.player, "primary_position", "")).upper()
            if pos:
                self.outs_by_position[pos] = self.outs_by_position.get(pos, 0) + amount
                self.total_putouts += amount
                if pos == "C":
                    self.logged_catcher_putouts += amount
                self._adjust_fielding_config(pos)

    def _compute_no_foul_pitch_scale(self) -> float:
        pitch_base_pct = float(self.config.get("foulPitchBasePct", 24.0)) / 100.0
        bip_pitch_pct = float(self.config.get("ballInPlayPitchPct", 25.0)) / 100.0
        balance = float(self.config.get("foulBIPBalance", 0.94))
        denom = pitch_base_pct + bip_pitch_pct
        if denom <= 0:
            return 0.75
        scale = (pitch_base_pct + bip_pitch_pct * balance) / denom
        return max(0.65, min(0.85, scale * 0.8))

    def _scale_pitch_counts(self, team: TeamState, scale: float) -> None:
        for ps in team.pitcher_stats.values():
            ps.pitches_thrown = int(round(ps.pitches_thrown * scale))
            ps.strikes_thrown = int(round(ps.strikes_thrown * scale))
            ps.balls_thrown = int(round(ps.balls_thrown * scale))

    def _adjust_fielding_config(self, position: str) -> None:
        """Adjust fielding parameters to target MLB putout rates."""

        target = self.target_putout_probs.get(position)
        if not target or self.total_putouts == 0:
            return
        current = self.outs_by_position[position] / self.total_putouts
        diff = target - current
        if abs(diff) < 0.01:
            return
        mapping = {
            "P": "catchChancePitcherAdjust",
            "C": "catchChanceCatcherAdjust",
            "1B": "catchChanceFirstBaseAdjust",
            "2B": "catchChanceSecondBaseAdjust",
            "3B": "catchChanceThirdBaseAdjust",
            "SS": "catchChanceShortStopAdjust",
            "LF": "catchChanceLeftFieldAdjust",
            "CF": "catchChanceCenterFieldAdjust",
            "RF": "catchChanceRightFieldAdjust",
        }
        attr = mapping.get(position)
        if not attr:
            return
        current_adj = getattr(self.config, attr, 0.0)
        setattr(self.config, attr, current_adj + diff * 5)

    def _set_runner_leads(self, offense: TeamState) -> None:
        """Update lead state for runners on first or second base."""

        long_speed = self.config.get("longLeadSpeed", 70) or 70
        for base in (0, 1):
            runner = offense.bases[base]
            if runner is None:
                continue
            runner.lead = 2 if runner.player.sp >= long_speed else 0

    def _maybe_pickoff(
        self,
        offense: TeamState,
        defense: TeamState,
        runner_state: BatterState,
        steal_chance: int,
    ) -> int:
        """Attempt a pickoff.  Returns the number of outs recorded."""

        if not self.defense.maybe_pickoff(
            steal_chance=steal_chance,
            lead=runner_state.lead,
            pitches_since=self.pitches_since_pickoff,
        ):
            return 0

        self.debug_log.append("Pickoff attempt")
        self.pitches_since_pickoff = 0

        pitcher_state = defense.current_pitcher_state
        if pitcher_state is None:
            return 0

        hold = pitcher_state.player.hold_runner
        speed = runner_state.player.sp
        success_prob = hold / max(1, hold + speed)
        balk_prob = 0.02
        outcome = self.rng.random()

        if outcome < success_prob:
            stealing = self.rng.random() < (steal_chance / 100.0)
            if stealing:
                self.debug_log.append("Runner picked off stealing")
                pitcher_state.pocs += 1
                self._add_stat(runner_state, "pocs")
            else:
                self.debug_log.append("Runner picked off")
                pitcher_state.pk += 1
                self._add_stat(runner_state, "po")
            offense.bases[0] = None
            offense.base_pitchers[0] = None
            return 1
        if outcome < success_prob + balk_prob:
            self.debug_log.append("Balk on pickoff")
            pitcher_state.bk += 1
            for base in range(2, -1, -1):
                runner = offense.bases[base]
                if runner is None:
                    continue
                ps_runner = offense.base_pitchers[base]
                if base == 2:
                    self._score_runner(offense, defense, 2)
                else:
                    offense.bases[base + 1] = runner
                    offense.base_pitchers[base + 1] = ps_runner
                offense.bases[base] = None
                offense.base_pitchers[base] = None
            return 0

        if (
            self.rng.random() < 0.1
            and runner_state.player.sp
            <= self.config.get("pickoffScareSpeed", 0)
        ):
            self.debug_log.append("Pickoff nearly succeeds")
            runner_state.lead = 0

        return 0

    def _get_fielder(self, defense: TeamState, position: str) -> Optional[FieldingState]:
        """Return the ``FieldingState`` for ``position`` if present."""

        for player in defense.lineup + defense.pitchers:
            if (
                player.primary_position == position
                or position in getattr(player, "other_positions", [])
            ):
                return defense.fielding_stats.setdefault(
                    player.player_id, FieldingState(player)
                )
        return None

    def _determine_infield_situation(
        self, offense: TeamState, defense: TeamState, outs: int
    ) -> str:
        """Return the infield alignment for the current situation."""

        if offense.bases[2] is not None:
            if abs(defense.runs - offense.runs) <= 1:
                return "guardLines"
            return "cutoffRun"
        if offense.bases[0] is not None and outs < 2:
            return "doublePlay"
        return "normal"

    def _set_defensive_alignment(
        self, offense: TeamState, defense: TeamState, outs: int
    ) -> None:
        """Determine and store the defensive alignment and positions."""

        batter = offense.lineup[offense.batting_index % len(offense.lineup)]
        self.current_infield_situation = self._determine_infield_situation(
            offense, defense, outs
        )
        self.current_outfield_situation = "normal"
        self.current_field_positions = self.defense.set_field_positions(
            pull=getattr(batter, "pl", 50), power=getattr(batter, "ph", 50)
        )
        self.debug_log.append(
            "Defensive alignment: infield="
            f"{self.current_infield_situation}, outfield="
            f"{self.current_outfield_situation}"
        )

    # ------------------------------------------------------------------
    # Pitcher state helpers
    # ------------------------------------------------------------------
    def _on_pitcher_enter(
        self, offense: TeamState, defense: TeamState, *, starting: bool = False
    ) -> None:
        """Record statistics when a pitcher enters the game."""

        ps = defense.current_pitcher_state
        if ps is None:
            return
        ps.g += 1
        if starting:
            ps.gs += 1
        fs = defense.fielding_stats.setdefault(ps.player.player_id, FieldingState(ps.player))
        fs.g += 1
        if starting:
            fs.gs += 1
        ps.ir += sum(1 for b in offense.bases if b is not None)
        lead = defense.runs - offense.runs
        if lead > 0 and lead <= 3:
            ps.svo += 1
            ps.in_save_situation = True
        else:
            ps.in_save_situation = False

    def _on_pitcher_exit(
        self,
        ps: PitcherState | None,
        offense: TeamState,
        defense: TeamState,
        *,
        game_finished: bool = False,
    ) -> None:
        """Update save/hold/blown save on pitcher exit."""

        if ps is None:
            return
        lead = defense.runs - offense.runs
        if ps.in_save_situation:
            if lead > 0:
                if game_finished:
                    target = ps
                    role = str(getattr(getattr(ps, "player", None), "assigned_pitching_role", "") or "").upper()
                    if role != "CL":
                        closer_state = self._closer_state(defense)
                        if closer_state is not None:
                            target = closer_state
                    target.sv += 1
                    target.gf += 1
                    if target is not ps:
                        target.svo += 1
                else:
                    if ps.outs > 0:
                        ps.hld += 1
            else:
                ps.bs += 1
        if game_finished and not ps.gf:
            ps.gf += 1
        ps.in_save_situation = False

    def _score_runner(
        self,
        offense: TeamState,
        defense: TeamState,
        base_idx: int,
        *,
        batter_state: BatterState | None = None,
        credit_rbi: bool = True,
    ) -> None:
        """Handle a runner scoring from ``base_idx``."""

        runner = offense.bases[base_idx]
        if runner is None:
            return
        was_trailing_or_tied = offense.runs <= defense.runs
        offense_key = "home" if offense is self.home else "away"
        offense.runs += 1
        current_pitcher = defense.current_pitcher_state
        if current_pitcher is not None and current_pitcher.in_save_situation:
            lead = defense.runs - offense.runs
            if lead <= 0:
                current_pitcher.bs += 1
                current_pitcher.in_save_situation = False
        if was_trailing_or_tied and offense.runs > defense.runs:
            self._pitcher_of_record[offense_key] = offense.current_pitcher_state
            self._losing_pitcher = defense.current_pitcher_state
        self._add_stat(runner, "r")
        # Pitcher on scoring team receives positive toast points
        scoring_pitcher = offense.current_pitcher_state
        if scoring_pitcher is not None:
            scoring_pitcher.toast += self.config.get("pitchScoringOffRun", 0)
        pitcher_for_runner = offense.base_pitchers[base_idx]
        if pitcher_for_runner is not None:
            pitcher_for_runner.r += 1
            pitcher_for_runner.er += 1
            pitcher_for_runner.toast += self.config.get("pitchScoringRun", 0)
            pitcher_for_runner.toast += self.config.get("pitchScoringER", 0)
            current = defense.current_pitcher_state
            if current is not None and current is not pitcher_for_runner:
                current.irs += 1
        offense.bases[base_idx] = None
        offense.base_pitchers[base_idx] = None
        if batter_state is not None and credit_rbi:
            self._add_stat(batter_state, "rbi")

    # ------------------------------------------------------------------
    # Core loop helpers
    # ------------------------------------------------------------------
    def simulate_game(
        self, innings: int = 9, persist_stats: bool = True
    ) -> None:
        """Simulate a complete game.

        The game will extend into extra innings if tied after the requested
        number of innings and the bottom half of the final inning is skipped
        when the home team is already ahead. Only very small parts of a real
        baseball game are modelled – enough to exercise decision making
        paths for the tests.

        Set ``persist_stats`` to ``False`` to skip merging results into season
        totals or saving them to disk.
        """

        inning = 1
        if innings > 0:
            while True:
                # Top half
                self._play_half(self.away, self.home)
                if inning >= innings and self.away.runs < self.home.runs:
                    break
                # Bottom half
                self._play_half(self.home, self.away)
                if inning >= innings and self.home.runs != self.away.runs:
                    break
                inning += 1

        self._evaluate_pitcher_overuse(self.home)
        self._evaluate_pitcher_overuse(self.away)

        if getattr(self, "_fouls_disabled", False):
            scale = self._compute_no_foul_pitch_scale()
            self._scale_pitch_counts(self.home, scale)
            self._scale_pitch_counts(self.away, scale)

        if persist_stats:
            # Finalize pitching stats for pitchers who finished the game
            self._on_pitcher_exit(
                self.home.current_pitcher_state,
                self.away,
                self.home,
                game_finished=True,
            )
            self._on_pitcher_exit(
                self.away.current_pitcher_state,
                self.home,
                self.away,
                game_finished=True,
            )

            # Assign winning/losing pitchers before aggregating season stats so
            # W/L are included in the per-pitcher season totals persisted below.
            if self.home.runs != self.away.runs:
                winner_key = "home" if self.home.runs > self.away.runs else "away"
                loser_key = "away" if winner_key == "home" else "home"
                winning_state = self._pitcher_of_record.get(winner_key)
                if winning_state is not None:
                    winning_state.w += 1
                losing_state = self._losing_pitcher
                if losing_state is None:
                    losing_state = (
                        self.home.current_pitcher_state
                        if loser_key == "home"
                        else self.away.current_pitcher_state
                    )
                if losing_state is not None:
                    losing_state.l += 1

            for team in (self.home, self.away):
                for bs in team.lineup_stats.values():
                    season = getattr(bs.player, "season_stats", {})
                    for f in fields(BatterState):
                        if f.name == "player":
                            continue
                        season[f.name] = season.get(f.name, 0) + getattr(bs, f.name)
                    # Ensure a game appearance is recorded for hitters who batted
                    # but did not record a defensive appearance (e.g. pure pinch hitters).
                    if getattr(bs, "pa", 0) > 0:
                        fs = team.fielding_stats.get(bs.player.player_id)
                        appeared_defensively = fs is not None and getattr(fs, "g", 0) > 0
                        if not appeared_defensively:
                            season["g"] = season.get("g", 0) + 1
                    season_state = BatterState(bs.player)
                    for f in fields(BatterState):
                        if f.name == "player":
                            continue
                        setattr(season_state, f.name, season.get(f.name, 0))
                    season.update(compute_batting_derived(season_state))
                    season.update(compute_batting_rates(season_state))
                    season["2b"] = season.get("b2", 0)
                    season["3b"] = season.get("b3", 0)
                    bs.player.season_stats = season

                for ps in team.pitcher_stats.values():
                    season = getattr(ps.player, "season_stats", {})
                    for attr, value in vars(ps).items():
                        # Persist all pitcher counting stats, including G/GS, directly from
                        # PitcherState. FieldingState G/GS for pitchers will be ignored during
                        # fielding aggregation to prevent double counting.
                        if attr in {"player", "in_save_situation"}:
                            continue
                        season[attr] = season.get(attr, 0) + value
                    season_state = PitcherState()
                    season_state.player = ps.player
                    for attr, value in season.items():
                        if attr in {"player", "in_save_situation"}:
                            continue
                        setattr(season_state, attr, value)
                    season.update(compute_pitching_derived(season_state))
                    season.update(compute_pitching_rates(season_state))
                    ps.player.season_stats = season

                for fs in team.fielding_stats.values():
                    season = getattr(fs.player, "season_stats", {})
                    for f in fields(FieldingState):
                        if f.name == "player":
                            continue
                        # Do not accumulate fielding G/GS for pitchers; those come from PitcherState
                        if getattr(fs.player, "is_pitcher", False) and f.name in {"g", "gs"}:
                            continue
                        season[f.name] = season.get(f.name, 0) + getattr(fs, f.name)
                    season_state = FieldingState(fs.player)
                    for f in fields(FieldingState):
                        if f.name == "player":
                            continue
                        setattr(season_state, f.name, season.get(f.name, 0))
                    season.update(compute_fielding_derived(season_state))
                    season.update(compute_fielding_rates(season_state))
                    fs.player.season_stats = season

            for team, opp in ((self.home, self.away), (self.away, self.home)):
                derived = compute_team_derived(team, opp)
                season = team.team_stats
                if team.runs > opp.runs:
                    season["w"] = season.get("w", 0) + 1
                elif team.runs < opp.runs:
                    season["l"] = season.get("l", 0) + 1
                season["g"] = season.get("g", 0) + 1
                season["r"] = season.get("r", 0) + team.runs
                season["ra"] = season.get("ra", 0) + opp.runs
                season["lob"] = season.get("lob", 0) + team.lob
                for key in (
                    "opp_pa",
                    "opp_h",
                    "opp_bb",
                    "opp_so",
                    "opp_hbp",
                    "opp_hr",
                    "opp_roe",
                ):
                    season[key] = season.get(key, 0) + derived[key]
                season.update(compute_team_rates(season))
                team.team_stats = season
                if team.team is not None:
                    team.team.season_stats = season

            

            players: Dict[str, Player] = {}
            for state in (self.home, self.away):
                for bs in state.lineup_stats.values():
                    players[bs.player.player_id] = bs.player
                for ps in state.pitcher_stats.values():
                    players[ps.player.player_id] = ps.player
                for fs in state.fielding_stats.values():
                    players[fs.player.player_id] = fs.player
            teams = [t.team for t in (self.home, self.away) if t.team is not None]
            save_stats(players.values(), teams)

        # DP debug print removed after calibration

    def _play_half(self, offense: TeamState, defense: TeamState) -> None:
        # Allow the defensive team to consider a late inning defensive swap
        inning = len(offense.inning_runs) + 1
        self._current_inning_number = inning
        self._half_inning_label = "top" if offense is self.away else "bottom"
        self.subs.maybe_defensive_sub(defense, inning, self.debug_log)

        start_runs = offense.runs
        start_log = len(self.debug_log)
        outs = 0
        plate_appearances = 0
        max_pa = self.config.get("maxHalfInningPA", 0)
        max_runs = self.config.get("maxHalfInningRuns", 0)
        limits_enabled = bool(self.config.get("halfInningLimitEnabled", 1))
        before_pitching: dict[str, tuple[int, int, int, int]] = {}
        for pid, ps in defense.pitcher_stats.items():
            before_pitching[pid] = (
                getattr(ps, "outs", 0),
                getattr(ps, "h", 0),
                getattr(ps, "bb", 0),
                getattr(ps, "hbp", 0),
            )
        while outs < 3:
            if limits_enabled:
                if max_pa and plate_appearances >= max_pa:
                    self.debug_log.append(
                        f"Aborting half-inning after {plate_appearances} plate appearances "
                        f"(limit {max_pa})"
                    )
                    break
                runs_scored = offense.runs - start_runs
                if max_runs and runs_scored >= max_runs:
                    self.debug_log.append(
                        f"Aborting half-inning after {runs_scored} runs "
                        f"(limit {max_runs})"
                    )
                    break
            self.current_outs = outs
            self._set_defensive_alignment(offense, defense, outs)
            outs += self.play_at_bat(offense, defense)
            plate_appearances += 1
        inning_events = self.debug_log[start_log:]
        for runner in offense.bases:
            if runner is not None:
                self._add_stat(runner, "lob")
        lob = sum(1 for r in offense.bases if r is not None)
        offense.lob += lob
        offense.inning_lob.append(lob)
        offense.inning_events.append(inning_events)
        offense.bases = [None, None, None]
        offense.base_pitchers = [None, None, None]
        offense.inning_runs.append(offense.runs - start_runs)
        # Award toast points for completing innings after the 4th
        if inning > 4 and defense.current_pitcher_state is not None:
            defense.current_pitcher_state.toast += self.config.get(
                "pitchScoringInnsAfter4", 0
            )
        clean_bonus = self.config.get("pitchScoringCleanInning", 0)
        if clean_bonus:
            for pid, ps in defense.pitcher_stats.items():
                prev_outs, prev_h, prev_bb, prev_hbp = before_pitching.get(
                    pid,
                    (0, 0, 0, 0),
                )
                outs_diff = getattr(ps, "outs", 0) - prev_outs
                hits_diff = getattr(ps, "h", 0) - prev_h
                walks_diff = getattr(ps, "bb", 0) - prev_bb
                hbp_diff = getattr(ps, "hbp", 0) - prev_hbp
                if outs_diff >= 3 and (hits_diff + walks_diff + hbp_diff) == 0:
                    frames = max(1, outs_diff // 3)
                    ps.toast += clean_bonus * frames

    def play_at_bat(self, offense: TeamState, defense: TeamState) -> int:
        """Play a single at-bat.  Returns the number of outs recorded."""
        inning = len(offense.inning_runs) + 1
        run_diff = offense.runs - defense.runs
        home_team = defense is self.home
        self.subs.maybe_warm_reliever(
            defense, inning=inning, run_diff=run_diff, home_team=home_team
        )
        old_pitcher = defense.current_pitcher_state
        changed = self.subs.maybe_replace_pitcher(
            defense,
            inning=inning,
            run_diff=run_diff,
            home_team=home_team,
            log=self.debug_log,
        )
        if changed:
            self._on_pitcher_exit(old_pitcher, offense, defense)
            self._on_pitcher_enter(offense, defense)

        # Check if any existing runner should be replaced with a pinch runner
        for base_idx, runner in enumerate(offense.bases):
            if runner is not None:
                self.subs.maybe_pinch_run(
                    offense,
                    base=base_idx,
                    inning=inning,
                    outs=self.current_outs,
                    run_diff=run_diff,
                    log=self.debug_log,
                )

        self._set_runner_leads(offense)

        # Defensive decisions prior to the at-bat.  These mostly log the
        # outcome for manual inspection in the exhibition dialog.  The
        # simplified simulation does not yet modify gameplay based on them.
        runner_state = offense.bases[0]
        runner = runner_state.player if runner_state else None
        holding_runner = False
        steal_chance = 0
        outs_from_pick = 0
        pitcher_fa = (
            defense.current_pitcher_state.player.fa
            if defense.current_pitcher_state
            else 0
        )
        first_fa = next(
            (p.fa for p in defense.lineup if p.primary_position == "1B"), 0
        )
        third_fa = next(
            (p.fa for p in defense.lineup if p.primary_position == "3B"), 0
        )
        charge_first, charge_third = self.defense.maybe_charge_bunt(
            pitcher_fa=pitcher_fa,
            first_fa=first_fa,
            third_fa=third_fa,
            on_first=offense.bases[0] is not None,
            on_second=offense.bases[1] is not None,
            on_third=offense.bases[2] is not None,
        )
        if charge_first or charge_third:
            self.debug_log.append("Defense charges bunt")
        outs_before = self.current_outs
        next_batter_ch = offense.lineup[
            offense.batting_index % len(offense.lineup)
        ].ch
        run_diff = offense.runs - defense.runs
        self._outs_before_play = outs_before
        self._bases_before_play = list(offense.bases)
        if runner_state and self.defense.maybe_hold_runner(runner.sp):
            holding_runner = True
            self.debug_log.append("Defense holds runner")
            pitcher_state = defense.current_pitcher_state
            if pitcher_state is not None:
                self._update_fatigue(pitcher_state)
                pitcher = self._fatigued_pitcher(pitcher_state.player)
                steal_chance = int(
                    self.offense.calculate_steal_chance(
                        balls=0,
                        strikes=0,
                        runner_sp=runner.sp,
                        pitcher_hold=pitcher.hold_runner,
                        pitcher_is_left=pitcher.bats == "L",
                        pitcher_is_wild=pitcher.control <= 30,
                        pitcher_in_windup=False,
                        outs=outs_before,
                        runner_on=1,
                        batter_ch=next_batter_ch,
                        run_diff=run_diff,
                    )
                    * 100
                )
            outs_from_pick = self._maybe_pickoff(
                offense, defense, runner_state, steal_chance
            )
            self.current_outs += outs_from_pick
            outs_before += outs_from_pick

        inning = len(offense.inning_runs) + 1
        batter_idx = offense.batting_index % len(offense.lineup)
        pitcher_batting = (
            offense.current_pitcher_state is not None
            and offense.lineup[batter_idx].player_id
            == offense.current_pitcher_state.player.player_id
        )
        if pitcher_batting:
            old_off_pitcher = offense.current_pitcher_state
            batter = self.subs.maybe_pinch_hit_for_pitcher(
                offense,
                defense,
                batter_idx,
                inning=inning,
                outs=outs_before,
                log=self.debug_log,
            )
            offense.batting_index += 1
            if batter.player_id != old_off_pitcher.player.player_id:
                self._on_pitcher_exit(old_off_pitcher, defense, offense)
                self._on_pitcher_enter(defense, offense)
        else:
            old_pitcher = defense.current_pitcher_state
            batter = self.subs.maybe_double_switch(
                offense, defense, batter_idx, self.debug_log
            )
            if batter is not None:
                self._on_pitcher_exit(old_pitcher, offense, defense)
                self._on_pitcher_enter(offense, defense)
            else:
                starter = offense.lineup[batter_idx]
                if run_diff < 0:
                    on_deck_idx = (batter_idx + 1) % len(offense.lineup)
                    batter = self.subs.maybe_pinch_hit_need_run(
                        offense,
                        defense,
                        batter_idx,
                        on_deck_idx,
                        inning=inning,
                        outs=outs_before,
                        run_diff=run_diff,
                        home_team=offense is self.home,
                        log=self.debug_log,
                    )
                    if batter is starter:
                        batter = self.subs.maybe_pinch_hit_need_hit(
                            offense,
                            batter_idx,
                            on_deck_idx,
                            inning=inning,
                            outs=outs_before,
                            run_diff=run_diff,
                            home_team=offense is self.home,
                            log=self.debug_log,
                        )
                else:
                    batter = starter
                if batter is starter:
                    batter = self.subs.maybe_pinch_hit(
                        offense, batter_idx, self.debug_log
                    )
            offense.batting_index += 1
        on_deck_idx = offense.batting_index % len(offense.lineup)
        on_deck = offense.lineup[on_deck_idx]

        on_first = offense.bases[0] is not None
        on_second = offense.bases[1] is not None
        on_third = offense.bases[2] is not None
        pitch_around, ibb = self.defense.maybe_pitch_around(
            inning=inning,
            batter_ph=batter.ph,
            batter_ch=batter.ch,
            on_deck_ph=on_deck.ph,
            on_deck_ch=on_deck.ch,
            batter_gf=batter.gf,
            on_deck_gf=on_deck.gf,
            outs=outs_before,
            on_first=on_first,
            on_second=on_second,
            on_third=on_third,
        )
        if ibb:
            self.debug_log.append("Intentional walk issued")
        elif pitch_around:
            self.debug_log.append("Pitch around")

        batter_state = offense.lineup_stats.setdefault(
            batter.player_id, BatterState(batter)
        )
        pitcher_state = defense.current_pitcher_state
        if pitcher_state is None:
            raise RuntimeError("Defense has no available pitcher")

        if self.diagnostics_recorder is not None:
            self._start_plate_appearance_event(offense, defense, batter_state, pitcher_state)

        pitcher_state.bf += 1
        start_pitches = pitcher_state.pitches_thrown
        start_simulated = getattr(pitcher_state, "simulated_pitches", 0)

        # Record plate appearance
        self._add_stat(batter_state, "pa")
        season_pitcher = getattr(pitcher_state.player, "season_stats", None)
        if season_pitcher is None:
            pitcher_state.player.season_stats = {}

        outs = 0
        balls = 0
        strikes = 0
        seen_two_strike = False
        seen_three_ball = False

        if ibb:
            self._add_stat(batter_state, "bb")
            self._add_stat(batter_state, "ibb")
            pitcher_state.bb += 1
            pitcher_state.walks += 1
            pitcher_state.ibb += 1
            pitcher_state.toast += self.config.get("pitchScoringWalk", 0)
            pitcher_state.consecutive_hits = 0
            pitcher_state.consecutive_baserunners += 1
            self._advance_walk(offense, defense, batter_state)
            self._add_stat(
                batter_state, "pitches", pitcher_state.pitches_thrown - start_pitches
            )
            self._credit_pitcher_outs(pitcher_state, outs)
            return self._complete_plate_appearance(
                result="intentional_walk",
                outs=outs,
                outs_from_pick=outs_from_pick,
            )

        inning = len(offense.inning_runs) + 1
        run_diff = offense.runs - defense.runs

        while True:
            self._flush_batter_decision()
            test_fastpath = bool(getattr(self.config, "simDeterministicTestMode", False))
            if test_fastpath:
                if (
                    balls == 0
                    and strikes == 0
                    and offense.bases[2] is not None
                    and offense.bases[0] is None
                    and offense.bases[1] is None
                ):
                    # Deterministic RBI single: one pitch, runner scores, no outs.
                    pitcher_state.pitches_thrown += 1
                    pitcher_state.strikes_thrown += 1
                    self.pitches_since_pickoff = min(self.pitches_since_pickoff + 1, 4)
                    self._add_stat(batter_state, "ab")
                    self._add_stat(batter_state, "h")
                    self._add_stat(batter_state, "b1")
                    pitcher_state.b1 += 1
                    pitcher_state.h += 1
                    self._score_runner(
                        offense, defense, 2, batter_state=batter_state, credit_rbi=True
                    )
                    pitcher_state.toast += self.config.get("pitchScoringHit", 0)
                    pitcher_state.consecutive_hits += 1
                    pitcher_state.consecutive_baserunners += 1
                    offense.bases = [None, None, None]
                    offense.base_pitchers = [None, None, None]
                    self._add_stat(
                        batter_state,
                        "pitches",
                        pitcher_state.pitches_thrown - start_pitches,
                    )
                    return self._complete_plate_appearance(
                        result="deterministic_rbi_single",
                        outs=outs,
                        outs_from_pick=outs_from_pick,
                    )

                if not any(offense.bases) and batter_state.so < 2:
                    # Deterministic strikeout on three pitches.
                    pitcher_state.pitches_thrown += 3
                    pitcher_state.strikes_thrown += 3
                    self._add_stat(batter_state, "ab")
                    self._add_stat(batter_state, "so")
                    self._add_stat(batter_state, "so_swinging")
                    pitcher_state.so += 1
                    pitcher_state.so_swinging += 1
                    outs += 1
                    pitcher_state.toast += self.config.get("pitchScoringOut", 0)
                    pitcher_state.toast += self.config.get("pitchScoringStrikeOut", 0)
                    pitcher_state.consecutive_hits = 0
                    pitcher_state.consecutive_baserunners = 0
                    self._add_stat(
                        batter_state,
                        "pitches",
                        pitcher_state.pitches_thrown - start_pitches,
                    )
                    self._credit_pitcher_outs(pitcher_state, outs)
                    return self._complete_plate_appearance(
                        result="strikeout_swinging",
                        outs=outs,
                        outs_from_pick=outs_from_pick,
                    )

            decision_data: dict[str, Any] = {
                "balls": balls,
                "strikes": strikes,
                "in_zone": False,
                "swing": False,
                "contact": False,
                "foul": False,
                "ball_in_play": False,
                "hit": False,
                "ball": False,
                "called_strike": False,
                "walk": False,
                "strikeout": False,
                "hbp": False,
                "breakdown": None,
                "objective": "zone",
                "target_offset": (0.0, 0.0),
                "pitch_type": None,
                "pitch_speed": None,
                "pitch_distance": None,
                "pitch_dx": None,
                "pitch_dy": None,
                "contact_quality": None,
                "result": None,
                "auto_take": False,
                "auto_take_reason": None,
                "auto_take_threshold": None,
                "auto_take_distance": None,
            }
            real_pitch_count = (pitcher_state.pitches_thrown - start_pitches) - (
                getattr(pitcher_state, "simulated_pitches", 0) - start_simulated
            )
            first_pitch_this_pitch = real_pitch_count == 0
            if not seen_two_strike and strikes >= 2:
                seen_two_strike = True
                self.two_strike_counts += 1
            if not seen_three_ball and balls >= 3:
                seen_three_ball = True
                self.three_ball_counts += 1

            self._update_fatigue(pitcher_state)
            pitcher = self._fatigued_pitcher(pitcher_state.player)
            self._set_runner_leads(offense)
            runner_state = offense.bases[0]
            if runner_state:
                hit_run_chance = int(
                    self.offense.calculate_hit_and_run_chance(
                        runner_sp=runner_state.player.sp,
                        batter_ch=batter.ch,
                        batter_ph=batter.ph,
                        balls=balls,
                        strikes=strikes,
                        run_diff=run_diff,
                        runners_on_first_and_second=(offense.bases[1] is not None),
                        pitcher_wild=pitcher.control <= 30,
                    )
                    * 100
                )
                force_hit_run_grounder = hit_run_chance >= 90
                pitch_out_called = False
                if holding_runner and self.defense.maybe_pitch_out(
                    steal_chance=steal_chance,
                    hit_run_chance=hit_run_chance,
                    ball_count=balls,
                    inning=inning,
                    is_home_team=(defense is self.home),
                ):
                    self.debug_log.append("Pitch out")
                    pitch_out_called = True
                if not pitch_out_called and self.offense.maybe_hit_and_run(
                    runner_sp=runner_state.player.sp,
                    batter_ch=batter.ch,
                    batter_ph=batter.ph,
                    balls=balls,
                    strikes=strikes,
                    run_diff=run_diff,
                    runners_on_first_and_second=(offense.bases[1] is not None),
                    pitcher_wild=pitcher.control <= 30,
                ):
                    self.debug_log.append("Hit and run")
                    self._hit_and_run_active = True
                    self._force_hit_and_run_grounder = force_hit_run_grounder
                    steal_result = self._attempt_steal(
                        offense,
                        defense,
                        pitcher_state.player,
                        force=True,
                        balls=balls,
                        strikes=strikes,
                        outs=outs,
                        runner_on=1,
                        batter_ch=batter.ch,
                        pitcher_is_wild=pitcher.control <= 30,
                        pitcher_in_windup=False,
                        run_diff=run_diff,
                    )
                    if steal_result is False:
                        outs += 1
                elif balls == 0 and strikes == 0 and self.offense.maybe_sacrifice_bunt(
                    batter_is_pitcher=batter.primary_position == "P",
                    batter_ch=batter.ch,
                    batter_ph=batter.ph,
                    on_deck_ch=on_deck.ch,
                    on_deck_ph=on_deck.ph,
                    outs=outs_before,
                    inning=inning,
                    on_first=offense.bases[0] is not None,
                    on_second=offense.bases[1] is not None,
                    run_diff=run_diff,
                ):
                    self.debug_log.append("Sacrifice bunt")
                    b = offense.bases
                    bp = offense.base_pitchers
                    runs_scored = 0
                    if b[2]:
                        self._score_runner(offense, defense, 2, batter_state=batter_state)
                        runs_scored += 1
                    if b[1]:
                        offense.bases[2] = b[1]
                        offense.base_pitchers[2] = bp[1]
                        offense.bases[1] = None
                        offense.base_pitchers[1] = None
                    if b[0]:
                        offense.bases[1] = b[0]
                        offense.base_pitchers[1] = bp[0]
                        offense.bases[0] = None
                        offense.base_pitchers[0] = None
                    self._add_stat(batter_state, "sh")
                    outs += 1
                    self._add_stat(
                        batter_state, "pitches", pitcher_state.pitches_thrown - start_pitches
                    )
                    self._credit_pitcher_outs(pitcher_state, outs)
                    return self._complete_plate_appearance(
                        result="sacrifice_bunt",
                        outs=outs,
                        outs_from_pick=outs_from_pick,
                        runs_scored=runs_scored,
                    )
            pre_pitch_out = False
            for runner_on in (1,):
                if runner_on == 1 and getattr(self, "_hit_and_run_active", False):
                    continue
                steal_result = self._attempt_steal(
                    offense,
                    defense,
                    pitcher_state.player,
                    batter=batter,
                    balls=balls,
                    strikes=strikes,
                    outs=outs,
                    runner_on=runner_on,
                    batter_ch=batter.ch,
                    pitcher_is_wild=pitcher.control <= 30,
                    pitcher_in_windup=False,
                    run_diff=run_diff,
                )
                if steal_result is False:
                    outs += 1
                    self.current_outs += 1
                    pitcher_state.toast += self.config.get("pitchScoringOut", 0)
                    pitcher_state.consecutive_hits = 0
                    pitcher_state.consecutive_baserunners = 0
                    run_diff = offense.runs - defense.runs
                    pre_pitch_out = True
                    break
                if steal_result:
                    break
            if pre_pitch_out:
                if self.current_outs >= 3:
                    self._add_stat(
                        batter_state, "pitches", pitcher_state.pitches_thrown - start_pitches
                    )
                    self._credit_pitcher_outs(pitcher_state, outs)
                    self.subs.maybe_warm_reliever(
                        defense,
                        inning=inning,
                        run_diff=run_diff,
                        home_team=home_team,
                    )
                    return self._complete_plate_appearance(
                        result="caught_stealing",
                        outs=outs,
                        outs_from_pick=outs_from_pick,
                    )
                continue

            if (
                offense.bases[2]
                and balls == 0
                and strikes == 0
                and self.offense.maybe_suicide_squeeze(
                    batter_ch=batter.ch,
                    batter_ph=batter.ph,
                    balls=balls,
                    strikes=strikes,
                    runner_on_third_sp=offense.bases[2].player.sp,
                )
            ):
                self.debug_log.append("Suicide squeeze")
                if offense.bases[2]:
                    self._score_runner(
                        offense,
                        defense,
                        2,
                        batter_state=batter_state,
                    )
                self._add_stat(batter_state, "sh")
                outs += 1
                self._add_stat(
                    batter_state, "pitches", pitcher_state.pitches_thrown - start_pitches
                )
                self._credit_pitcher_outs(pitcher_state, outs)
                return self._complete_plate_appearance(
                    result="suicide_squeeze",
                    outs=outs,
                    outs_from_pick=outs_from_pick,
                    runs_scored=1,
                )

            target_pitches = self.config.get("targetPitchesPerPA", 0)
            strike_rate = float(self.config.get("leagueStrikePct", 65.9)) / 100.0
            pitches_this_pa = pitcher_state.pitches_thrown - start_pitches
            if target_pitches and target_pitches > 0 and pitches_this_pa < target_pitches:
                desired_total = int(target_pitches)
                if self.rng.random() < target_pitches - desired_total:
                    desired_total += 1
                extra_pitches = max(0, desired_total - pitches_this_pa - 1)
                for _ in range(extra_pitches):
                    # Inject real waste pitches instead of phantom counts.
                    control_roll = self.rng.random()
                    waste_dx, waste_dy = self._pitch_target_offset("waste", control_roll)
                    context, _ = resolve_pitch(
                        self.config,
                        self.physics,
                        self.batter_ai,
                        self.pitcher_ai,
                        batter=batter,
                        pitcher=pitcher,
                        balls=balls,
                        strikes=strikes,
                        control_roll=control_roll,
                        target_dx=waste_dx,
                        target_dy=waste_dy,
                        pitch_type=None,
                        objective="waste",
                        rng=self.rng,
                    )
                    pitcher_state.pitches_thrown += 1
                    self.pitches_since_pickoff = min(self.pitches_since_pickoff + 1, 4)
                    if context.in_zone:
                        pitcher_state.strikes_thrown += 1
                    else:
                        self._record_ball(pitcher_state)

            pitcher_state.pitches_thrown += 1
            self.pitches_since_pickoff = min(self.pitches_since_pickoff + 1, 4)
            control_roll = self.rng.random()
            pitch_type, objective = self.pitcher_ai.select_pitch(
                pitcher, balls=balls, strikes=strikes
            )
            target_dx, target_dy = self._pitch_target_offset(objective, control_roll)
            context, outcome = resolve_pitch(
                self.config,
                self.physics,
                self.batter_ai,
                self.pitcher_ai,
                batter=batter,
                pitcher=pitcher,
                balls=balls,
                strikes=strikes,
                control_roll=control_roll,
                target_dx=target_dx,
                target_dy=target_dy,
                pitch_type=pitch_type,
                objective=objective,
                rng=self.rng,
            )
            decision_data["objective"] = context.objective
            decision_data["target_offset"] = (context.target_dx, context.target_dy)
            decision_data["pitch_type"] = context.pitch_type
            decision_data["in_zone"] = context.in_zone
            decision_data["pitch_distance"] = context.distance
            decision_data["pitch_dx"] = context.x_off
            decision_data["pitch_dy"] = context.y_off
            decision_data["pitch_speed"] = context.pitch_speed
            decision_data["contact_quality"] = outcome.contact_quality
            decision_data["auto_take"] = outcome.auto_take
            decision_data["auto_take_reason"] = outcome.auto_take_reason
            decision_data["auto_take_threshold"] = outcome.auto_take_threshold
            decision_data["auto_take_distance"] = outcome.auto_take_distance
            contact_quality = outcome.contact_quality
            decision_data["swing"] = outcome.swing
            decision_data["breakdown"] = outcome.decision_breakdown
            decision_data["contact"] = outcome.contact
            pitch_speed = context.pitch_speed
            swing = outcome.swing
            orig_swing = swing
            in_zone = context.in_zone
            contact = outcome.contact
            dist = context.distance
            # Retain auto-take overrides and miss/break metadata for trackers
            self._last_control_roll = control_roll
            self._last_pitch_distance = context.distance
            self._last_pitch_in_zone = context.in_zone
            catcher_fs = self._get_fielder(defense, "C")
            dec_r = self.rng.random()
            if swing and self._maybe_catcher_interference(
                offense,
                defense,
                batter_state,
                catcher_fs,
                pitcher_state,
                start_pitches,
            ):
                pitcher_state.record_pitch(in_zone=in_zone, swung=True, contact=False)
                self._credit_pitcher_outs(pitcher_state, outs)
                return self._complete_plate_appearance(
                    result="catcher_interference",
                    outs=outs,
                    outs_from_pick=outs_from_pick,
                )

            pitcher_state.record_pitch(in_zone=in_zone, swung=swing, contact=contact)

            if swing:
                if contact:
                    foul_chance = self._foul_probability(
                        batter,
                        pitcher,
                        balls=balls,
                        dist=dist,
                        strikes=strikes,
                        misread=self.batter_ai.last_misread,
                    )
                    if self.rng.random() < foul_chance:
                        decision_data["foul"] = True
                        decision_data["contact"] = True
                        if not in_zone:
                            self._record_ball(pitcher_state)
                        pitcher_state.strikes_thrown += 1
                        if self._attempt_foul_catch(
                            batter,
                            pitcher,
                            defense,
                            pitch_speed=pitch_speed,
                            rand=dec_r,
                        ):
                            self._add_stat(batter_state, "ab")
                            outs += 1
                            pitcher_state.toast += self.config.get("pitchScoringOut", 0)
                            pitcher_state.consecutive_hits = 0
                            pitcher_state.consecutive_baserunners = 0
                            self._add_stat(
                                batter_state,
                                "pitches",
                                pitcher_state.pitches_thrown - start_pitches,
                            )
                            self._credit_pitcher_outs(pitcher_state, outs)
                            run_diff = offense.runs - defense.runs
                            self.subs.maybe_warm_reliever(
                                defense,
                                inning=inning,
                                run_diff=run_diff,
                                home_team=home_team,
                            )
                            self._queue_batter_decision(**decision_data, immediate=True)
                            return self._complete_plate_appearance(
                                result="foul_out",
                                outs=outs,
                                outs_from_pick=outs_from_pick,
                            )
                        if strikes < 2 and first_pitch_this_pitch and strikes == 0:
                            pitcher_state.first_pitch_strikes += 1
                        if strikes < 2:
                            strikes += 1
                        self._queue_batter_decision(**decision_data, immediate=False)
                        continue
                self.infield_fly = False
                out_of_zone = not in_zone
                if (
                    contact
                    and out_of_zone
                ):
                    decision_data["contact"] = False
                    decision_data["strikeout"] = True
                    self.logged_strikeouts += 1
                    self._add_stat(batter_state, "ab")
                    self._add_stat(batter_state, "so")
                    self._add_stat(batter_state, "so_swinging")
                    pitcher_state.so += 1
                    pitcher_state.so_swinging += 1
                    outs += 1
                    pitcher_state.toast += self.config.get("pitchScoringOut", 0)
                    pitcher_state.toast += self.config.get("pitchScoringStrikeOut", 0)
                    pitcher_state.consecutive_hits = 0
                    pitcher_state.consecutive_baserunners = 0
                    self._add_stat(
                        batter_state,
                        "pitches",
                        pitcher_state.pitches_thrown - start_pitches,
                    )
                    self._credit_pitcher_outs(pitcher_state, outs)
                    run_diff = offense.runs - defense.runs
                    self.subs.maybe_warm_reliever(
                        defense,
                        inning=inning,
                        run_diff=run_diff,
                        home_team=home_team,
                    )
                    return self._complete_plate_appearance(
                        result="out_of_zone_contact_out",
                        outs=outs,
                        outs_from_pick=outs_from_pick,
                    )

                contact_quality_var = contact_quality
                if contact and out_of_zone:
                    contact_quality_var = max(0.1, contact_quality_var * 0.25)
                if contact_quality_var <= 0:
                    pitcher_state.strikes_thrown += 1
                    if first_pitch_this_pitch and strikes == 0:
                        pitcher_state.first_pitch_strikes += 1
                    strikes += 1
                    self._maybe_passed_ball(offense, defense, catcher_fs)
                    if strikes >= 3:
                        decision_data["strikeout"] = True
                        self.logged_strikeouts += 1
                        self._add_stat(batter_state, "ab")
                        self._add_stat(batter_state, "so")
                        self._add_stat(batter_state, "so_swinging")
                        pitcher_state.so += 1
                        pitcher_state.so_swinging += 1
                        outs += 1
                        pitcher_state.toast += self.config.get("pitchScoringOut", 0)
                        pitcher_state.toast += self.config.get("pitchScoringStrikeOut", 0)
                        pitcher_state.consecutive_hits = 0
                        pitcher_state.consecutive_baserunners = 0
                        catcher_fs = self._get_fielder(defense, "C")
                        if catcher_fs:
                            self._add_fielding_stat(catcher_fs, "po", position="C")
                        p_fs = defense.fielding_stats.get(pitcher_state.player.player_id)
                        if p_fs:
                            self._add_fielding_stat(p_fs, "a")
                        self._add_stat(
                            batter_state,
                            "pitches",
                            pitcher_state.pitches_thrown - start_pitches,
                        )
                        self._credit_pitcher_outs(pitcher_state, outs)
                        run_diff = offense.runs - defense.runs
                        self.subs.maybe_warm_reliever(
                            defense, inning=inning, run_diff=run_diff, home_team=home_team
                        )
                        self._queue_batter_decision(**decision_data, immediate=True)
                        return self._complete_plate_appearance(
                            result="strikeout_swinging",
                            outs=outs,
                            outs_from_pick=outs_from_pick,
                        )
                    continue
                bases, error = self._swing_result(
                    batter,
                    pitcher,
                    defense,
                    batter_state,
                    pitcher_state,
                    pitch_speed=pitch_speed,
                    contact_quality=contact_quality_var,
                    is_third_strike=strikes >= 2,
                    start_pitches=start_pitches,
                )
                if self._last_swing_strikeout:
                    decision_data["strikeout"] = True
                    if in_zone:
                        pitcher_state.strikes_thrown += 1
                    else:
                        self._record_ball(pitcher_state)
                    self._add_stat(batter_state, "ab")
                    self._add_stat(batter_state, "so")
                    self._add_stat(batter_state, "so_swinging")
                    pitcher_state.so += 1
                    pitcher_state.so_swinging += 1
                    outs += 1
                    pitcher_state.toast += self.config.get("pitchScoringOut", 0)
                    pitcher_state.toast += self.config.get("pitchScoringStrikeOut", 0)
                    pitcher_state.consecutive_hits = 0
                    pitcher_state.consecutive_baserunners = 0
                    p_fs = defense.fielding_stats.get(
                        pitcher_state.player.player_id
                    )
                    if p_fs:
                        self._add_fielding_stat(p_fs, "a")
                    self._add_stat(
                        batter_state,
                        "pitches",
                        pitcher_state.pitches_thrown - start_pitches,
                    )
                    self._credit_pitcher_outs(pitcher_state, outs)
                    run_diff = offense.runs - defense.runs
                    self.subs.maybe_warm_reliever(
                        defense, inning=inning, run_diff=run_diff, home_team=home_team
                    )
                    self._queue_batter_decision(**decision_data, immediate=True)
                    return self._complete_plate_appearance(
                        result="strikeout_swinging",
                        outs=outs,
                        outs_from_pick=outs_from_pick,
                    )
                if self.infield_fly:
                    decision_data["ball_in_play"] = True
                    decision_data["contact"] = True
                    if in_zone:
                        pitcher_state.strikes_thrown += 1
                    else:
                        self._record_ball(pitcher_state)
                    self._add_stat(batter_state, "ab")
                    outs += 1
                    pitcher_state.toast += self.config.get("pitchScoringOut", 0)
                    pitcher_state.consecutive_hits = 0
                    pitcher_state.consecutive_baserunners = 0
                    self._add_stat(
                        batter_state,
                        "pitches",
                        pitcher_state.pitches_thrown - start_pitches,
                    )
                    self._credit_pitcher_outs(pitcher_state, outs)
                    run_diff = offense.runs - defense.runs
                    self.subs.maybe_warm_reliever(
                        defense, inning=inning, run_diff=run_diff, home_team=home_team
                    )
                    self._queue_batter_decision(**decision_data, immediate=True)
                    return self._complete_plate_appearance(
                        result="infield_fly_out",
                        outs=outs,
                        outs_from_pick=outs_from_pick,
                    )
                if bases == 0:
                    decision_data["ball_in_play"] = True
                    decision_data["contact"] = True
                    if in_zone:
                        pitcher_state.strikes_thrown += 1
                    else:
                        self._record_ball(pitcher_state)
                    self._add_stat(batter_state, "ab")
                    outs += 1
                    runner_scored = False
                    bases_before = getattr(self, "_bases_before_play", [None, None, None])
                    outs_before = getattr(self, "_outs_before_play", 0)
                    if outs_before < 2 and len(bases_before) >= 3 and bases_before[2] is not None:
                        self._score_runner(
                            offense,
                            defense,
                            2,
                            batter_state=batter_state,
                            credit_rbi=False,
                        )
                        runner_scored = True
                        outs = max(0, outs - 1)
                    if (
                        self.last_batted_ball_type == "ground"
                        and offense.bases[0] is not None
                        and not runner_scored
                    ):
                        self.dp_candidates += 1
                        # Use timing-based decision for force at 2B and relay to 1B
                        runner = offense.bases[0]
                        batter_sp = getattr(batter, "sp", 50)
                        runner_sp = getattr(runner.player, "sp", 50)
                        # Choose likely fielder based on spray side
                        primary = self.last_ground_fielder or "SS"
                        if primary not in {"SS", "2B", "3B", "1B"}:
                            primary = "SS"
                        ffs = self._get_fielder(defense, primary)
                        fa = getattr(ffs.player, "fa", 50) if ffs else 50
                        arm = getattr(ffs.player, "arm", 50) if ffs else 50
                        # Time to force at second vs runner (use geometric throw distance)
                        fx, fy = DEFAULT_POSITIONS.get(primary, (90.0, 0.0))
                        sx, sy = SECOND_BASE
                        throw_dist_2b = math.hypot(sx - fx, sy - fy)
                        runner_time_2b = 90 / self.physics.player_speed(runner_sp)
                        force_time = self.physics.reaction_delay(primary, fa) + self.physics.throw_time(
                            arm, throw_dist_2b, primary
                        )
                        # For force plays, stepping on the bag is more appropriate than a tag
                        # Primary force decision: always attempt close grounder forces
                        # Use PBINI helper, but treat any plausibly close play as an attempt.
                        can_force = True
                        dp_done = False
                        if can_force:
                            self.dp_attempts += 1
                            pivot_pos = "2B" if primary in {"SS", "3B"} else "SS"
                            two_fs = self._get_fielder(defense, pivot_pos)
                            two_fa = getattr(two_fs.player, "fa", 50) if two_fs else 50
                            two_arm = getattr(two_fs.player, "arm", 50) if two_fs else 50
                            if two_fs is not None:
                                self._add_fielding_stat(two_fs, "po", position=pivot_pos)
                            offense.bases[0] = None
                            offense.base_pitchers[0] = None
                            batter_time_1b = 90 / self.physics.player_speed(batter_sp)
                            px, py = DEFAULT_POSITIONS.get(pivot_pos, (90.0, 90.0))
                            bx, by = FIRST_BASE
                            relay_dist = math.hypot(bx - px, by - py)
                            relay_time = self.physics.reaction_delay(pivot_pos, two_fa) + self.physics.throw_time(
                                two_arm, relay_dist, pivot_pos
                            )

                            if self.config.get("dpAlwaysTurn", 0):
                                dp_success = True
                            else:
                                dp_prob = float(self.config.get("doublePlayProb", 0))
                                dp_prob = max(dp_prob, float(self.config.get("dpHardMinProb", 0.35)))
                                margin2 = runner_time_2b - force_time
                                margin1 = batter_time_1b - relay_time
                                force_auto = margin2 >= float(self.config.get("dpForceAutoSec", 0.25))
                                relay_auto = margin1 >= float(self.config.get("dpRelayAutoSec", 0.30))
                                if dp_prob <= 0:
                                    dp_success = bool(margin2 > 0 and margin1 > 0)
                                elif force_auto and relay_auto:
                                    dp_success = True
                                else:
                                    if margin2 > 0:
                                        dp_prob = min(
                                            1.0,
                                            dp_prob
                                            + margin2
                                            * float(self.config.get("dpForceBoostPerSec", 0.10)),
                                        )
                                    if margin1 > 0:
                                        dp_prob = min(
                                            1.0,
                                            dp_prob
                                            + margin1
                                            * float(self.config.get("dpRelayBoostPerSec", 0.12)),
                                        )
                                    dp_success = self.rng.random() < dp_prob

                            if dp_success:
                                outs += 1
                                self._add_stat(batter_state, "gidp")
                                self.dp_made += 1
                                if two_fs is not None:
                                    self._add_fielding_stat(two_fs, "po", position=pivot_pos)
                                oneb_fs = self._get_fielder(defense, "1B")
                                if oneb_fs is not None:
                                    self._add_fielding_stat(oneb_fs, "po", position="1B")
                                if ffs is not None:
                                    self._add_fielding_stat(ffs, "a")
                            else:
                                offense.bases[0] = batter_state
                                offense.base_pitchers[0] = defense.current_pitcher_state
                                self._add_stat(batter_state, "fc")
                    if outs > 0:
                        pitcher_state.toast += self.config.get("pitchScoringOut", 0)
                    pitcher_state.consecutive_hits = 0
                    pitcher_state.consecutive_baserunners = 0
                    self._add_stat(
                        batter_state,
                        "pitches",
                        pitcher_state.pitches_thrown - start_pitches,
                    )
                    if runner_scored and outs == 0:
                        self._credit_pitcher_outs(pitcher_state, outs)
                        run_diff = offense.runs - defense.runs
                        self.subs.maybe_warm_reliever(
                            defense, inning=inning, run_diff=run_diff, home_team=home_team
                        )
                        self._queue_batter_decision(**decision_data, immediate=True)
                        return self._complete_plate_appearance(
                            result="ball_in_play_out",
                            outs=outs,
                            outs_from_pick=outs_from_pick,
                        )
                    self._credit_pitcher_outs(pitcher_state, outs)
                    run_diff = offense.runs - defense.runs
                    self.subs.maybe_warm_reliever(
                        defense, inning=inning, run_diff=run_diff, home_team=home_team
                    )
                    self._queue_batter_decision(**decision_data, immediate=True)
                    return self._complete_plate_appearance(
                        result="ball_in_play_out",
                        outs=outs,
                        outs_from_pick=outs_from_pick,
                    )
                if bases:
                    decision_data["ball_in_play"] = True
                    decision_data["contact"] = True
                    if in_zone:
                        pitcher_state.strikes_thrown += 1
                    else:
                        self._record_ball(pitcher_state)
                    self._add_stat(batter_state, "ab")
                    if error:
                        pitcher_state.consecutive_hits = 0
                        pitcher_state.consecutive_baserunners += 1
                        outs_made = self._advance_runners(
                            offense,
                            defense,
                            batter_state,
                            bases=bases,
                            error=True,
                        )
                        if outs_made:
                            outs += outs_made
                            pitcher_state.toast += self.config.get(
                                "pitchScoringOut", 0
                            ) * outs_made
                            pitcher_state.consecutive_hits = 0
                            pitcher_state.consecutive_baserunners = 0
                            self._credit_pitcher_outs(pitcher_state, outs_made)
                    else:
                        pitcher_state.h += 1
                        self._add_stat(batter_state, "h")
                        decision_data["hit"] = True
                        if bases == 4:
                            pitcher_state.hr += 1
                            pitcher_state.allowed_hr = True
                            self._add_stat(batter_state, "hr")
                        elif bases == 3:
                            pitcher_state.b3 += 1
                            self._add_stat(batter_state, "b3")
                        elif bases == 2:
                            pitcher_state.b2 += 1
                            self._add_stat(batter_state, "b2")
                        else:
                            pitcher_state.b1 += 1
                            self._add_stat(batter_state, "b1")
                        pitcher_state.toast += self.config.get(
                            "pitchScoringHit", 0
                        )
                        if pitcher_state.consecutive_hits:
                            pitcher_state.toast += self.config.get(
                                "pitchScoringConsHit", 0
                            )
                        pitcher_state.consecutive_hits += 1
                        pitcher_state.consecutive_baserunners += 1
                        outs_made = self._advance_runners(
                            offense, defense, batter_state, bases=bases
                        )
                        if outs_made:
                            outs += outs_made
                            pitcher_state.toast += self.config.get(
                                "pitchScoringOut", 0
                            ) * outs_made
                            pitcher_state.consecutive_hits = 0
                            pitcher_state.consecutive_baserunners = 0
                            self._credit_pitcher_outs(pitcher_state, outs_made)
                    self._add_stat(
                        batter_state,
                        "pitches",
                        pitcher_state.pitches_thrown - start_pitches,
                    )
                    self._credit_pitcher_outs(pitcher_state, outs)
                    run_diff = offense.runs - defense.runs
                    self.subs.maybe_warm_reliever(
                        defense, inning=inning, run_diff=run_diff, home_team=home_team
                    )
                    self._queue_batter_decision(**decision_data, immediate=True)
                    return self._complete_plate_appearance(
                        result="ball_in_play",
                        outs=outs,
                        outs_from_pick=outs_from_pick,
                    )
                if first_pitch_this_pitch and strikes == 0:
                    pitcher_state.first_pitch_strikes += 1
                strikes += 1
                if not in_zone:
                    self._record_ball(pitcher_state)
                else:
                    pitcher_state.strikes_thrown += 1
            else:
                if in_zone:
                    decision_data["called_strike"] = True
                    strikes += 1
                    if first_pitch_this_pitch and strikes == 1:
                        pitcher_state.first_pitch_strikes += 1
                    pitcher_state.strikes_thrown += 1
                else:
                    decision_data["ball"] = True
                    hbp_dist = self.config.get("closeBallDist", 5) + self.rng.randint(1, 2)
                    league_hbp = self.config.get("leagueHBPPerGame", 0.86)
                    if league_hbp > 0:
                        hbp_dist = int(round(hbp_dist * 0.86 / league_hbp))
                    base_hbp = self.config.get("hbpBaseChance", 0.0)
                    if base_hbp and dist >= hbp_dist:
                        step_out_chance = (
                            self.config.get("hbpBatterStepOutChance", 0) / 100.0
                        )
                        roll = self.rng.random()
                        is_hbp = roll < base_hbp
                        if is_hbp:
                            step_out_roll = self.rng.random()
                            if step_out_roll < step_out_chance:
                                is_hbp = False
                        if is_hbp:
                            decision_data["hbp"] = True
                            decision_data["ball"] = False
                            self._add_stat(batter_state, "hbp")
                            pitcher_state.hbp += 1
                            pitcher_state.toast += self.config.get(
                                "pitchScoringWalk", 0
                            )
                            pitcher_state.consecutive_hits = 0
                            pitcher_state.consecutive_baserunners += 1
                            self._advance_walk(offense, defense, batter_state)
                            self._add_stat(
                                batter_state,
                                "pitches",
                                pitcher_state.pitches_thrown - start_pitches,
                            )
                            self._handle_hit_by_pitch_injury(batter_state, offense, pitch_speed)
                            self._record_ball(pitcher_state)
                            self._credit_pitcher_outs(pitcher_state, outs)
                            run_diff = offense.runs - defense.runs
                            self.subs.maybe_warm_reliever(
                                defense,
                                inning=inning,
                                run_diff=run_diff,
                                home_team=home_team,
                            )
                            self._queue_batter_decision(**decision_data, immediate=True)
                            return self._complete_plate_appearance(
                                result="hbp",
                                outs=outs,
                                outs_from_pick=outs_from_pick,
                            )
                    if orig_swing and contact_quality <= 0:
                        decision_data["ball"] = False
                        self._maybe_passed_ball(offense, defense, catcher_fs)
                        pitcher_state.strikes_thrown += 1
                        if first_pitch_this_pitch and strikes == 0:
                            pitcher_state.first_pitch_strikes += 1
                        strikes += 1
                        if strikes >= 3:
                            decision_data["strikeout"] = True
                            self.logged_strikeouts += 1
                            self._add_stat(batter_state, "ab")
                            self._add_stat(batter_state, "so")
                            self._add_stat(batter_state, "so_swinging")
                            pitcher_state.so += 1
                            pitcher_state.so_swinging += 1
                            outs += 1
                            pitcher_state.toast += self.config.get("pitchScoringOut", 0)
                            pitcher_state.toast += self.config.get("pitchScoringStrikeOut", 0)
                            pitcher_state.consecutive_hits = 0
                            pitcher_state.consecutive_baserunners = 0
                            catcher_fs = self._get_fielder(defense, "C")
                            if catcher_fs:
                                self._add_fielding_stat(catcher_fs, "po", position="C")
                            p_fs = defense.fielding_stats.get(pitcher_state.player.player_id)
                            if p_fs:
                                self._add_fielding_stat(p_fs, "a")
                            self._add_stat(
                                batter_state, "pitches", pitcher_state.pitches_thrown - start_pitches
                            )
                            self._credit_pitcher_outs(pitcher_state, outs)
                            run_diff = offense.runs - defense.runs
                            self.subs.maybe_warm_reliever(
                                defense,
                                inning=inning,
                                run_diff=run_diff,
                                home_team=home_team,
                            )
                            self._queue_batter_decision(**decision_data, immediate=True)
                            return self._complete_plate_appearance(
                                result="strikeout_swinging",
                                outs=outs,
                                outs_from_pick=outs_from_pick,
                            )
                        self._queue_batter_decision(**decision_data, immediate=False)
                        continue
                    else:
                        balls += 1
                        self._record_ball(pitcher_state)

            self._maybe_passed_ball(offense, defense, catcher_fs)

            if not seen_two_strike and strikes >= 2:
                seen_two_strike = True
                self.two_strike_counts += 1
            if not seen_three_ball and balls >= 3:
                seen_three_ball = True
                self.three_ball_counts += 1

            if balls >= 4:
                decision_data["walk"] = True
                self._add_stat(batter_state, "bb")
                pitcher_state.bb += 1
                pitcher_state.walks += 1
                pitcher_state.toast += self.config.get("pitchScoringWalk", 0)
                pitcher_state.consecutive_hits = 0
                pitcher_state.consecutive_baserunners += 1
                self._advance_walk(offense, defense, batter_state)
                self._add_stat(
                    batter_state, "pitches", pitcher_state.pitches_thrown - start_pitches
                )
                self._credit_pitcher_outs(pitcher_state, outs)
                run_diff = offense.runs - defense.runs
                self.subs.maybe_warm_reliever(
                    defense, inning=inning, run_diff=run_diff, home_team=home_team
                )
                self._queue_batter_decision(**decision_data, immediate=True)
                return self._complete_plate_appearance(
                    result="walk",
                    outs=outs,
                    outs_from_pick=outs_from_pick,
                )
            if strikes >= 3:
                decision_data["strikeout"] = True
                self.logged_strikeouts += 1
                self._add_stat(batter_state, "ab")
                self._add_stat(batter_state, "so")
                if swing:
                    self._add_stat(batter_state, "so_swinging")
                    pitcher_state.so_swinging += 1
                else:
                    self._add_stat(batter_state, "so_looking")
                    pitcher_state.so_looking += 1
                pitcher_state.so += 1
                outs += 1
                pitcher_state.toast += self.config.get("pitchScoringOut", 0)
                pitcher_state.toast += self.config.get("pitchScoringStrikeOut", 0)
                pitcher_state.consecutive_hits = 0
                pitcher_state.consecutive_baserunners = 0
                catcher_fs = self._get_fielder(defense, "C")
                if catcher_fs:
                    self._add_fielding_stat(catcher_fs, "po", position="C")
                p_fs = defense.fielding_stats.get(pitcher_state.player.player_id)
                if p_fs:
                    self._add_fielding_stat(p_fs, "a")
                self._add_stat(
                    batter_state, "pitches", pitcher_state.pitches_thrown - start_pitches
                )
                self._credit_pitcher_outs(pitcher_state, outs)
                run_diff = offense.runs - defense.runs
                self.subs.maybe_warm_reliever(
                    defense, inning=inning, run_diff=run_diff, home_team=home_team
                )
                self._queue_batter_decision(**decision_data, immediate=True)
                return self._complete_plate_appearance(
                    result="strikeout_swinging" if swing else "strikeout_looking",
                    outs=outs,
                    outs_from_pick=outs_from_pick,
                )

            self._queue_batter_decision(**decision_data, immediate=False)


    # ------------------------------------------------------------------
    # Pinch hitting
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Swing outcome
    # ------------------------------------------------------------------
    def _foul_probability(
        self,
        batter: Player,
        pitcher: Pitcher,
        *,
        balls: int = 0,
        dist: float = 0.0,
        strikes: int = 0,
        misread: bool = False,
        contact_prob: float | None = None,
    ) -> float:
        """Return foul ball probability derived from configuration and ratings.

        ``foulPitchBasePct`` is the league-wide percentage of pitches that end
        in a foul ball while ``foulStrikeBasePct`` expresses that rate on a
        per-strike basis (~36% of strikes become fouls). ``ballInPlayPitchPct``
        represents the share of all pitches put in play and is used together
        with ``foulPitchBasePct`` to determine the overall contact rate. The
        resulting conversion yields roughly half of contacted pitches as balls
        in play and preserves the strike-based foul percentage without forcing
        a 1:1 split.

        ``foulContactTrendPct`` adds roughly ``+1.5`` percentage points for
        every 20 point edge in batter contact over pitcher movement. ``dist``
        allows far out-of-zone pitches to reduce foul likelihood while
        ``misread`` boosts the chance so complete misreads produce foul tips
        instead of whiffs.
        """

        cfg = self.config
        strike_base_pct = float(cfg.get("foulStrikeBasePct", 36.4)) / 100.0
        pitch_base_pct = float(cfg.get("foulPitchBasePct", 24.0)) / 100.0
        bip_pitch_pct = float(cfg.get("ballInPlayPitchPct", 25.0)) / 100.0
        bip_pitch_scale = float(cfg.get("ballInPlayScale", 1.0) or 1.0)
        bip_pitch_pct *= max(0.0, bip_pitch_scale)
        trend_pct = float(cfg.get("foulContactTrendPct", 1.5)) / 100.0

        strike_rate = pitch_base_pct / strike_base_pct if strike_base_pct else 0.0
        if strike_rate > 1.0:
            strike_rate = 1.0

        contact_delta = getattr(batter, "ch", 50) - getattr(pitcher, "movement", 50)
        foul_rate = strike_base_pct + (contact_delta / 20.0) * trend_pct
        foul_rate = max(0.0, min(0.95, foul_rate))

        foul_per_pitch = strike_rate * foul_rate
        balance = float(cfg.get("foulBIPBalance", 0.94))
        if strikes >= 2:
            balance *= float(cfg.get("twoStrikeBIPScale", 1.0) or 1.0)

        if contact_prob is not None:
            contact_rate = max(0.01, min(0.99, float(contact_prob)))
        else:
            contact_rate = foul_per_pitch + bip_pitch_pct * balance
        if contact_rate <= 0.0:
            return 0.0
        prob = foul_per_pitch / contact_rate
        foul_scale = float(cfg.get("foulProbabilityScale", 1.0) or 1.0)
        prob *= max(0.0, foul_scale)
        count_multiplier = float(
            getattr(
                cfg,
                f"foulCountMultiplier{balls}{strikes}",
                getattr(cfg, "foulCountMultiplierDefault", 1.0),
            )
            or 1.0
        )
        prob *= max(0.0, count_multiplier)
        prob = max(0.05, min(0.95, prob))

        if dist > 0:
            prob *= max(0.0, 1.0 - dist * 0.1)
        if misread:
            prob *= 1.5
        # Two-strike resilience: give high-contact hitters more chances to spoil pitches
        if strikes >= 2:
            resilience = float(cfg.get("twoStrikeFoulResilience", 2.5))
            resilience += max(0.0, contact_delta) / float(cfg.get("twoStrikeFoulResilienceDiv", 60.0))
            prob *= resilience
            bonus_pct = float(cfg.get("twoStrikeFoulBonusPct", 0.0)) / 100.0
            if bonus_pct > 0:
                prob *= 1.0 + bonus_pct
            floor = float(cfg.get("twoStrikeFoulFloor", 0.0))
            if floor > 0:
                prob = max(prob, floor)
        return max(0.0, min(1.0, prob))

    def _attempt_foul_catch(
        self,
        batter: Player,
        pitcher: Pitcher,
        defense: TeamState,
        *,
        pitch_speed: float,
        rand: float,
        swing_type: str = "normal",
    ) -> bool:
        """Return ``True`` if a foul ball is caught for an out."""

        bat_speed = self.physics.bat_speed(
            batter.ph, swing_type=swing_type, pitch_speed=pitch_speed
        )
        bat_speed, _ = self.bat_impact(bat_speed, rand=rand)
        swing_angle = self.physics.swing_angle(batter.gf, swing_type=swing_type)
        vert_angle = self.physics.vertical_hit_angle(
            swing_type=swing_type, gf=batter.gf
        )
        vx, vy, vz = self.physics.launch_vector(
            getattr(batter, "ph", 50),
            getattr(batter, "pl", 50),
            swing_angle,
            vert_angle,
            swing_type=swing_type,
        )
        x, y, hang_time = self.physics.landing_point(vx, vy, vz)
        if self.rng.random() < 0.5:
            x = -abs(x)
        else:
            y = -abs(y)
        landing_dist = math.hypot(x, y)

        fielders = {p.primary_position.upper(): p for p in defense.lineup}
        fielders["P"] = pitcher
        for pos, (fx, fy) in DEFAULT_POSITIONS.items():
            fielder = fielders.get(pos)
            if not fielder:
                continue
            sp = getattr(fielder, "sp", 50)
            fa = getattr(fielder, "fa", 50)
            distance = math.hypot(fx - x, fy - y)
            run_time = (
                distance / self.physics.player_speed(sp)
                + self.physics.reaction_delay(pos, fa)
            )
            action = self.fielding_ai.catch_action(
                hang_time,
                run_time,
                position=pos,
                distance=distance,
                dist_from_home=landing_dist,
            )
            if action == "no_attempt":
                continue
            if self.fielding_ai.resolve_fly_ball(pos, fa, hang_time, action):
                fs = defense.fielding_stats.setdefault(
                    fielder.player_id, FieldingState(fielder)
                )
                self._add_fielding_stat(fs, "po", position=pos)
                self.debug_log.append("Foul ball caught")
                return True
        return False

    def _swing_result(
        self,
        batter: Player,
        pitcher: Pitcher,
        defense: TeamState,
        batter_state: BatterState,
        pitcher_state: PitcherState,
        *,
        pitch_speed: float,
        contact_quality: float = 1.0,
        swing_type: str = "normal",
        is_third_strike: bool = False,
        start_pitches: int | None = None,
    ) -> tuple[Optional[int], bool]:
        if start_pitches is None:
            start_pitches = getattr(pitcher_state, "pitches_thrown", 0)
        self._last_swing_strikeout = False
        forced_hit_and_run = getattr(self, "_hit_and_run_active", False)
        force_hit_and_run_grounder = getattr(self, "_force_hit_and_run_grounder", False)
        self._hit_and_run_active = False
        self._force_hit_and_run_grounder = False
        if forced_hit_and_run and not force_hit_and_run_grounder:
            # Reward aggressive hit-and-run decisions with a guaranteed ball in play.
            self.last_batted_ball_type = "line"
            self.last_batted_ball_angles = (0.0, 12.0)
            return 1, False
        if contact_quality <= 0:
            if is_third_strike:
                self._last_swing_strikeout = True
                self.logged_strikeouts += 1
                catcher_fs = self._get_fielder(defense, "C")
                if catcher_fs:
                    self._add_fielding_stat(catcher_fs, "po", position="C")
            return None, False
        bat_speed = self.physics.bat_speed(
            batter.ph, swing_type=swing_type, pitch_speed=pitch_speed
        )
        bat_speed, _ = self.bat_impact(bat_speed, rand=self.rng.random())
        # Calculate and store angles for potential future physics steps.
        swing_method = self.physics.swing_angle
        swing_params = inspect.signature(swing_method).parameters
        if "rand" in swing_params:
            swing_angle = swing_method(batter.gf, swing_type=swing_type, rand=0.5)
        else:
            swing_angle = swing_method(batter.gf, swing_type=swing_type)
        vangle_method = self.physics.vertical_hit_angle
        vangle_params = inspect.signature(vangle_method).parameters
        if "rand" in vangle_params:
            vert_base = abs(vangle_method(swing_type=swing_type, rand=0.5))
        else:
            vert_base = abs(vangle_method(swing_type=swing_type))
        power_adjust = (getattr(batter, "ph", 50) - 50) * 0.1
        # ------------------------------------------------------------------
        # Determine batted ball distribution.  Baseline rates are pulled from
        # configuration but are modified by player and pitcher attributes.
        # Sluggers with loft in their swings should generate more fly balls,
        # while pitchers with strong movement tend to induce more grounders.
        # Each component is weighted so the impact can be tuned through
        # ``PlayBalance`` configuration.
        # ------------------------------------------------------------------
        base_gb = self.config.ground_ball_base_rate
        base_ld = self.config.line_drive_base_rate
        base_fb = self.config.fly_ball_base_rate
        power_factor = (
            getattr(batter, "ph", 50) - 50
        ) * self.config.bip_power_weight
        launch_factor = (
            getattr(batter, "gf", 50) - 50
        ) * self.config.bip_launch_weight
        movement_factor = (
            getattr(pitcher, "movement", 50) - 50
        ) * self.config.bip_movement_weight
        gb = base_gb - power_factor - launch_factor + movement_factor
        fb = base_fb + power_factor + launch_factor - movement_factor
        gb = max(0.0, gb)
        fb = max(0.0, fb)
        ld = max(0.0, base_gb + base_ld + base_fb - gb - fb)
        total = max(1.0, gb + ld + fb)
        bip_bucket = "ground"
        if force_hit_and_run_grounder:
            vert_angle = -abs(vert_base + swing_angle + power_adjust + 1)
        else:
            roll = self.rng.random() * total
            self._last_bip_roll = roll
            if roll < gb:
                vert_angle = -abs(vert_base + swing_angle + power_adjust + 1)
                bip_bucket = "ground"
            elif roll < gb + ld:
                vert_angle = max(0.0, vert_base - 4)
                launch = swing_angle + vert_angle + power_adjust
                if launch > 15:
                    vert_angle -= launch - 15
                bip_bucket = "line"
            else:
                vert_angle = max(0.0, vert_base - 4)
                launch = swing_angle + vert_angle + power_adjust
                if launch <= 15:
                    vert_angle += 16 - launch
                bip_bucket = "fly"
        base_vangle_method = getattr(type(self.physics), "vertical_hit_angle", None)
        current_vangle = getattr(self.physics.vertical_hit_angle, "__func__", None)
        vertical_angle_patched = not (
            base_vangle_method is not None and current_vangle is base_vangle_method
        )
        launch_angle = swing_angle + vert_angle + power_adjust
        if bip_bucket == "ground" and launch_angle > 0:
            vert_angle = -abs(vert_base + swing_angle + power_adjust + 1)
            launch_angle = swing_angle + vert_angle + power_adjust
        elif bip_bucket == "fly" and launch_angle <= 20:
            loft_bonus = (
                (getattr(batter, "gf", 50) - 50) / 5.0
                + (getattr(batter, "ph", 50) - 50) / 10.0
                + (50 - getattr(pitcher, "movement", 50)) / 5.0
            )
            loft_bonus = max(0.0, loft_bonus)
            if loft_bonus <= 0 and not vertical_angle_patched:
                loft_bonus = max(0.0, 21 - launch_angle)
            elif loft_bonus > 0:
                loft_bonus = max(loft_bonus, 21 - launch_angle)
            if loft_bonus > 0:
                vert_angle += loft_bonus
                launch_angle = swing_angle + vert_angle + power_adjust
        if launch_angle <= 0:
            outcome = "ground"
        elif launch_angle <= 20:
            outcome = "line"
        else:
            outcome = "fly"
        # Early estimate: if ball clears the wall in the air, it's a home run
        vx, vy, vz = self.physics.launch_vector(
            getattr(batter, "ph", 50),
            getattr(batter, "pl", 50),
            swing_angle,
            vert_angle,
            swing_type=swing_type,
        )
        air = self.physics.air_resistance(
            altitude=self.altitude,
            temperature=self.temperature,
            wind_speed=self.wind_speed,
        )
        carry = getattr(self.config, "ballCarryPct", 65) / 100.0
        vx *= air * carry
        vy *= air * carry
        vz *= air
        x_hr, y_hr, _ = self.physics.landing_point(vx, vy, vz)
        landing_dist_hr = math.hypot(x_hr, y_hr)
        angle_hr = math.atan2(abs(y_hr), abs(x_hr))
        pf = getattr(self, "park_factor", 1.0) or 1.0
        wall_eff_hr = (
            self.stadium.wall_distance(angle_hr) / pf if pf != 1.0 else self.stadium.wall_distance(angle_hr)
        )
        self.last_batted_ball_type = outcome
        self.last_batted_ball_angles = (swing_angle, vert_angle)
        if outcome == "ground":
            self._add_stat(batter_state, "gb")
            pitcher_state.gb += 1
        elif outcome == "line":
            self._add_stat(batter_state, "ld")
            pitcher_state.ld += 1
        else:
            self._add_stat(batter_state, "fb")
            pitcher_state.fb += 1
        # Fallback: hard-hit high launches are HRs in this simplified model
        if landing_dist_hr >= wall_eff_hr or (vert_base >= 19.9 and bat_speed >= 100):
            return 4, False

        offense = self.away if defense is self.home else self.home

        movement_factor = max(
            self.config.movement_factor_min,
            ((100 - pitcher.movement) / 120)
            * self.config.movement_impact_scale,
        )
        ch_rating = getattr(batter, "ch", 50)
        # Center around an average rating of 50 so only above-average
        # contact skills provide a positive boost.
        contact_factor = (
            self.config.contact_factor_base
            + (ch_rating - 50) / self.config.contact_factor_div
        )
        hit_prob = max(
            0.0,
            min(
                self.config.get("hitProbCap", 0.95),
                (
                    (bat_speed / 100.0)
                    * contact_quality
                    * contact_factor
                    * movement_factor
                )
                + self.config.hit_prob_base,  # value scaled in PlayBalanceConfig
            ),
        )
        slow_cutoff = float(self.config.get("hitProbSlowSpeed", 30.0))
        fast_cutoff = float(self.config.get("hitProbFastSpeed", 70.0))
        if fast_cutoff > slow_cutoff:
            speed_norm = (bat_speed - slow_cutoff) / (fast_cutoff - slow_cutoff)
            if speed_norm > 0:
                hit_prob = max(hit_prob, min(1.0, speed_norm))
        hit_prob_limit = float(self.config.get("maxHitProb", 0.95))
        hit_prob = min(hit_prob, hit_prob_limit)
        self._last_hit_prob = hit_prob
        # Modify hit probability based on current defensive alignment.
        infield_pos = self.current_field_positions.get("infield", {})
        if (
            self.current_infield_situation in infield_pos
            and "normal" in infield_pos
            and infield_pos["normal"]
        ):
            def _avg_depth(pos: Dict[str, Tuple[float, float]]) -> float:
                return sum(d for d, _ in pos.values()) / len(pos)

            normal_depth = _avg_depth(infield_pos["normal"])
            cur_depth = _avg_depth(infield_pos[self.current_infield_situation])
            if normal_depth > 0:
                hit_prob *= cur_depth / normal_depth

        hit_roll = 0.0 if hit_prob >= 0.99 else self.rng.random()
        self._last_hit_roll = hit_roll
        if hit_roll >= hit_prob:
            if is_third_strike:
                self._last_swing_strikeout = True
                self.logged_strikeouts += 1
                catcher_fs = self._get_fielder(defense, "C")
                if catcher_fs:
                    self._add_fielding_stat(catcher_fs, "po", position="C")
            return None, False
        if is_third_strike and all(base is None for base in offense.bases):
            self._last_swing_strikeout = True
            self.logged_strikeouts += 1
            catcher_fs = self._get_fielder(defense, "C")
            if catcher_fs:
                self._add_fielding_stat(catcher_fs, "po", position="C")
            desired_pitches = start_pitches + 3
            if pitcher_state.pitches_thrown > desired_pitches:
                pitcher_state.pitches_thrown = desired_pitches
            return None, False
        if getattr(self.config, "hitHRProb", 0) >= 100:
            return 4, False

        out_prob = {
            "ground": self.config.get("groundOutProb", 0.0),
            "line": self.config.get("lineOutProb", 0.0),
            "fly": self.config.get("flyOutProb", 0.0),
        }[self.last_batted_ball_type]

        roll_dist = self.physics.ball_roll_distance(
            bat_speed,
            self.surface,
            altitude=self.altitude,
            temperature=self.temperature,
            wind_speed=self.wind_speed,
        )
        bounce_vert, bounce_horiz = self.physics.ball_bounce(
            bat_speed / 2.0,
            bat_speed / 2.0,
            surface=self.surface,
            wet=self.wet,
            temperature=self.temperature,
        )

        # Recompute with same values for downstream fielding logic
        x, y, hang_time = self.physics.landing_point(vx, vy, vz)
        landing_dist = math.hypot(x, y)
        angle = math.atan2(abs(y), abs(x))

        # Record likely fielder side for grounders to aid DP logic
        infield_grounder_max = float(self.config.get("infieldGrounderMaxDist", 160.0))
        if self.last_batted_ball_type == "ground" and landing_dist <= infield_grounder_max:
            abs_x, abs_y = abs(x), abs(y)
            if abs_y > abs_x * 1.35:
                self.last_ground_fielder = "3B"
            elif abs_x > abs_y * 1.35:
                self.last_ground_fielder = "1B"
            else:
                self.last_ground_fielder = "SS" if abs_y >= abs_x else "2B"

        # Fast-path for routine infield grounders: attempt out at first.
        # Always evaluate this so batter-out DP timing can trigger when R1.
        if self.last_batted_ball_type == "ground" and landing_dist <= infield_grounder_max:
            abs_x, abs_y = abs(x), abs(y)
            # Strong pull to 3B line, or push to 1B line, else middle infield.
            if landing_dist <= 70:
                primary_pos = "P"
            elif abs_y > abs_x * 1.35:
                primary_pos = "3B"
            elif abs_x > abs_y * 1.35:
                primary_pos = "1B"
            else:
                primary_pos = "SS" if abs_y >= abs_x else "2B"
            self.last_ground_fielder = primary_pos
            fielder_fs = self._get_fielder(defense, primary_pos)
            if fielder_fs is None:
                # Fallbacks: prefer middle infielders if corner not available
                order = [
                    p for p in ("SS", "2B", "3B", "1B") if p != primary_pos
                ]
                for alt in order:
                    fielder_fs = self._get_fielder(defense, alt)
                    if fielder_fs is not None:
                        primary_pos = alt
                        break
            if fielder_fs is not None:
                fa = getattr(fielder_fs.player, "fa", 50)
                arm = getattr(fielder_fs.player, "arm", 50)
                batter_sp = getattr(batter, "sp", 50)
                batter_time = 90 / self.physics.player_speed(batter_sp)
                if primary_pos == "1B":
                    # Unassisted groundout at first: quick step or short toss
                    fielder_time = (
                        self.physics.reaction_delay("1B", fa)
                        + self.physics.throw_time(arm, 10.0, "1B")
                    )
                else:
                    # Use geometric distance from fielder's default spot to 1B
                    fx, fy = DEFAULT_POSITIONS.get(primary_pos, (90.0, 0.0))
                    d = math.hypot(FIRST_BASE[0] - fx, FIRST_BASE[1] - fy)
                    fielder_time = (
                        self.physics.reaction_delay(primary_pos, fa)
                        + self.physics.throw_time(arm, d, primary_pos)
                    )
                oneb_player = (
                    self._get_fielder(defense, "1B") or self._get_fielder(defense, "P")
                )
                oneb_fa = getattr(oneb_player.player, "fa", 50) if oneb_player else 50
                attempt_throw = self.fielding_ai.should_run_to_bag(fielder_time, batter_time)
                if primary_pos == "P":
                    attempt_throw = True
                if attempt_throw:
                    # Resolve a routine throw to first using fielding AI paths so tests
                    # see catch_probability/resolve_throw calls.
                    if force_hit_and_run_grounder:
                        caught, error = True, False
                    elif primary_pos == "P":
                        base_prob = self.fielding_ai.catch_probability("1B", oneb_fa, hang_time, "throw")
                        prob = min(1.0, base_prob * out_prob)
                        if self.rng.random() < prob:
                            caught, error = self.fielding_ai.resolve_throw("1B", oneb_fa, hang_time)
                        else:
                            caught, error = False, True
                        if out_prob >= 1.0:
                            caught, error = True, False
                    else:
                        prob = self.fielding_ai.catch_probability("1B", oneb_fa, hang_time, "throw")
                        if self.rng.random() < min(1.0, prob):
                            caught, error = self.fielding_ai.resolve_throw("1B", oneb_fa, hang_time)
                        else:
                            caught, error = False, False
                    if caught:
                        if primary_pos == "1B":
                            self._add_fielding_stat(fielder_fs, "po", position="1B")
                        else:
                            self._add_fielding_stat(fielder_fs, "a")
                            if oneb_player is not None:
                                self._add_fielding_stat(oneb_player, "po", position="1B")
                        return 0, False
                    if error:
                        if fielder_fs is not None:
                            self._add_fielding_stat(fielder_fs, "e")
                        return 1, True
                elif force_hit_and_run_grounder:
                    if primary_pos == "1B":
                        self._add_fielding_stat(fielder_fs, "po", position="1B")
                    else:
                        self._add_fielding_stat(fielder_fs, "a")
                        if oneb_player is not None:
                            self._add_fielding_stat(oneb_player, "po", position="1B")
                        else:
                            self._add_fielding_stat(fielder_fs, "po", position="1B")
                    self.debug_log.append("Hit and run forced grounder")
                    return 0, False
                    # If probability check fails, treat as safe (no out here)

        if (
            self.current_outs < 2
            and offense.bases[0] is not None
            and offense.bases[1] is not None
            and landing_dist <= 160
            and vert_angle >= 50
        ):
            self.infield_fly = True
            self.debug_log.append("Infield fly rule applied")
            return 0, False

        fielders = {p.primary_position.upper(): p for p in defense.lineup}
        fielders["P"] = pitcher
        for pos, (fx, fy) in DEFAULT_POSITIONS.items():
            fielder = fielders.get(pos)
            if not fielder:
                continue
            sp = getattr(fielder, "sp", 50)
            fa = getattr(fielder, "fa", 50)
            distance = math.hypot(fx - x, fy - y)
            run_time = (
                distance / self.physics.player_speed(sp)
                + self.physics.reaction_delay(pos, fa)
            )
            action = self.fielding_ai.catch_action(
                hang_time,
                run_time,
                position=pos,
                distance=distance,
                dist_from_home=landing_dist,
            )
            if action == "no_attempt":
                continue
            prob = self.fielding_ai.catch_probability(pos, fa, hang_time, action)
            prob *= out_prob * (1 + self.config.get("ballInPlayOuts", 0))
            prob = min(prob, 1.0)
            if self.rng.random() < prob:
                caught, error = self.fielding_ai.resolve_throw(pos, fa, hang_time)
                if caught:
                    # Record putout on the catching fielder
                    fs = defense.fielding_stats.setdefault(
                        fielder.player_id, FieldingState(fielder)
                    )
                    self._add_fielding_stat(fs, "po", position=pos)
                    # Sacrifice fly / tag-up logic: allow R3 to score with <2 outs
                    if self.current_outs < 2 and offense.bases[2] is not None:
                        runner_state = offense.bases[2]
                        # Runner time from 3B to home
                        runner_sp = self.physics.player_speed(runner_state.player.sp)
                        runner_time = 90 / runner_sp if runner_sp > 0 else float("inf")
                        # Fielder throw time from default position to home
                        fx, fy = DEFAULT_POSITIONS.get(pos, (0.0, 0.0))
                        from math import hypot
                        from playbalance.field_geometry import HOME
                        dist_home = hypot(HOME[0] - fx, HOME[1] - fy)
                        arm_rating = getattr(fielder, "arm", 50)
                        fielder_time = (
                            self.physics.reaction_delay(pos, fa)
                            + self.physics.throw_time(arm_rating, dist_home, pos)
                        )
                        # If the defense cannot tag in time, runner scores
                        if not self.fielding_ai.should_tag_runner(
                            fielder_time, runner_time
                        ):
                            self._score_runner(
                                offense,
                                defense,
                                2,
                                batter_state=batter_state,
                            )
                            self._add_stat(batter_state, "sf")
                    return 0, False
                # Missed or offline throw results in a live-ball error
                fs = defense.fielding_stats.setdefault(
                    fielder.player_id, FieldingState(fielder)
                )
                self._add_fielding_stat(fs, "e")
                return 1, True

        total_dist = landing_dist + bounce_horiz + roll_dist
        self._last_hit_distance = total_dist
        wall = self.stadium.wall_distance(angle)
        # Apply park factor by scaling effective thresholds (pf>1 means easier to reach wall)
        pf = getattr(self, "park_factor", 1.0) or 1.0
        if pf != 1.0:
            wall_eff = wall / pf
            triple_eff = self.stadium.triple_distance(angle) / pf
            double_eff = self.stadium.double_distance(angle) / pf
        else:
            wall_eff = wall
            triple_eff = self.stadium.triple_distance(angle)
            double_eff = self.stadium.double_distance(angle)

        if total_dist >= wall_eff:
            distance_base = 4
        elif total_dist >= triple_eff:
            distance_base = 3
        elif total_dist >= double_eff:
            distance_base = 2
        else:
            distance_base = 1

        if getattr(self.config, "hitHRProb", 0) >= 100:
            return 4, False

        # If the ball clears the wall it's always a home run regardless of
        # hit-distribution probabilities.
        if distance_base >= 4:
            base = 4
        else:
            hit1 = max(0, getattr(self.config, "hit1BProb", 65))
            hit2 = max(0, getattr(self.config, "hit2BProb", 20))
            hit3 = max(0, getattr(self.config, "hit3BProb", 2))
            hit4 = max(0, 100 - hit1 - hit2 - hit3)
            roll = self.rng.random() * 100
            if roll < hit1:
                target_base = 1
            elif roll < hit1 + hit2:
                target_base = 2
            elif roll < hit1 + hit2 + hit3:
                target_base = 3
            else:
                target_base = 4
            base = max(distance_base, target_base)
            if target_base == 4:
                base = 4
            base = max(1, min(4, base))
        return base, False

    def _advance_runners(
        self,
        offense: TeamState,
        defense: TeamState,
        batter_state: BatterState,
        *,
        bases: int,
        error: bool = False,
    ) -> None:
        b = offense.bases
        bp = offense.base_pitchers
        new_bases: List[Optional[BatterState]] = [None, None, None]
        new_bp: List[Optional[PitcherState]] = [None, None, None]
        runs_scored = 0
        outs = 0
        aggression = float(self.config.get("baserunningAggression", 0.5))
        # Fallback arm strength used for generic throws when a specific fielder
        # is not referenced. Use a neutral default instead of 0 to avoid
        # unrealistic infinite/very slow throws suppressing DP chances.
        arm = getattr(defense.lineup[0], "arm", 50) if defense.lineup else 50

        if error:
            self._add_stat(batter_state, "roe")

        if bases == 1:
            runner_on_first_out = False
            force_runner_time: Optional[float] = None
            force_fielder_time: Optional[float] = None
            if b[2]:
                runner_time = 90 / self.physics.player_speed(b[2].player.sp)
                fielder_time = self.physics.reaction_delay("LF", 0) + self.physics.throw_time(arm, 90, "LF")
                if self.fielding_ai.should_tag_runner(fielder_time, runner_time):
                    outs += 1
                    self._register_contact_play(b[2], offense, defense, trigger="collision", fielder_positions=["LF"])
            else:
                self._score_runner(offense, defense, 2)
                runs_scored += 1
            if b[1]:
                spd = self.physics.player_speed(b[1].player.sp)
                roll_dist = self.physics.ball_roll_distance(
                    spd,
                    self.surface,
                    altitude=self.altitude,
                    temperature=self.temperature,
                    wind_speed=self.wind_speed,
                )
                _, bounce_dist = self.physics.ball_bounce(
                    spd / 2.0,
                    spd / 2.0,
                    surface=self.surface,
                    wet=self.wet,
                    temperature=self.temperature,
                )
                travel = roll_dist + bounce_dist
                travel_thresh = float(self.config.get("singleSendHomeDistance", 28))
                attempt_home = travel >= travel_thresh
                if not attempt_home:
                    speed_factor = max(0.25, min(1.0, b[1].player.sp / 100.0))
                    aggression_factor = max(0.0, min(1.0, aggression * speed_factor))
                    attempt_home = self.rng.random() >= 1.0 - aggression_factor
                if attempt_home:
                    runner_time = 180 / spd
                    fielder_time = (
                        self.physics.reaction_delay("LF", 0)
                        + self.physics.throw_time(arm, 180, "LF")
                    )
                    if self.fielding_ai.should_tag_runner(fielder_time, runner_time):
                        outs += 1
                        self._register_contact_play(b[1], offense, defense, trigger="collision", fielder_positions=["LF"])
                    else:
                        self._score_runner(offense, defense, 1)
                        runs_scored += 1
                else:
                    new_bases[2] = b[1]
                    new_bp[2] = bp[1]
            if b[0]:
                # Runner on first; attempt force at 2B using geometry and bag-step timing
                runner_spd = self.physics.player_speed(b[0].player.sp)
                # Default: move runner safely if not a grounder scenario
                moved_runner = False
                # Treat as grounder when type is unknown to support direct-unit tests
                if (
                    not error
                    and self.last_batted_ball_type in ("ground", None)
                ):
                    # Count DP candidate on grounder with runner on first
                    self.dp_candidates += 1
                    primary = self.last_ground_fielder or "SS"
                    if primary not in {"SS", "2B", "3B", "1B"}:
                        primary = "SS"
                    ffs = self._get_fielder(defense, primary)
                    fa = getattr(ffs.player, "fa", 50) if ffs else 50
                    arm_f = getattr(ffs.player, "arm", 50) if ffs else arm
                    # Compute times to second base and attempt the force when timing is
                    # favorable or within a small grace window.
                    rx, ry = DEFAULT_POSITIONS.get(primary, (90.0, 0.0))
                    sx, sy = SECOND_BASE
                    dist2 = math.hypot(sx - rx, sy - ry)
                    runner_time = 90 / runner_spd
                    fielder_time = (
                        self.physics.reaction_delay(primary, fa)
                        + self.physics.throw_time(arm_f, dist2, primary)
                    )
                    # Always attempt the force on grounders with R1 to drive DP turns
                    can_force = True
                    if can_force:
                        self.dp_attempts += 1
                        outs += 1
                        runner_on_first_out = True
                        force_runner_time = runner_time
                        force_fielder_time = fielder_time
                        pivot_pos = "2B" if primary in {"SS", "3B"} else "SS"
                        pivot_fs = self._get_fielder(defense, pivot_pos)
                        if pivot_fs is not None:
                            self._add_fielding_stat(pivot_fs, "po", position=pivot_pos)
                        # Clear runner on first after force
                        b[0] = None
                        bp[0] = None
                        moved_runner = True
                if not moved_runner and b[0] is not None:
                    runner_speed = runner_spd
                    third_speed_thresh = float(
                        self.config.get("firstToThirdSpeedThreshold", 28.0)
                    )
                    attempt_third = runner_speed >= third_speed_thresh
                    if not attempt_third:
                        travel = getattr(self, "_last_hit_distance", 0.0)
                        dist_thresh = float(
                            self.config.get("singleFirstToThirdDistance", 210.0)
                        )
                        attempt_third = travel >= dist_thresh
                    if attempt_third:
                        moved_runner = True
                        if runner_speed >= third_speed_thresh:
                            new_bases[2] = b[0]
                            new_bp[2] = bp[0]
                        else:
                            runner_time = (
                                180 / runner_speed if runner_speed > 0 else float("inf")
                            )
                            fielder_time = self.physics.reaction_delay(
                                "RF", 0
                            ) + self.physics.throw_time(arm, 180, "RF")
                            if self.fielding_ai.should_tag_runner(
                                fielder_time, runner_time
                            ):
                                outs += 1
                                b[0] = None
                                bp[0] = None
                            else:
                                new_bases[2] = b[0]
                                new_bp[2] = bp[0]
                    if not moved_runner and b[0] is not None:
                        # No force; advance runner by default
                        new_bases[1] = b[0]
                        new_bp[1] = bp[0]

            if runner_on_first_out:
                batter_time = 90 / self.physics.player_speed(batter_state.player.sp)
                # Compute geometric relay from pivot to 1B using pivot's ratings
                piv = self.last_ground_fielder or "SS"
                pivot_pos = "2B" if piv in {"SS", "3B"} else "SS"
                piv_fs = self._get_fielder(defense, pivot_pos)
                piv_fa = getattr(piv_fs.player, "fa", 50) if piv_fs else 50
                piv_arm = getattr(piv_fs.player, "arm", 50) if piv_fs else arm
                px, py = DEFAULT_POSITIONS.get(pivot_pos, (90.0, 90.0))
                bx, by = FIRST_BASE
                relay_dist = math.hypot(bx - px, by - py)
                relay_time = (
                    self.physics.reaction_delay(pivot_pos, piv_fa)
                    + self.physics.throw_time(piv_arm, relay_dist, pivot_pos)
                )
                dp_prob = float(self.config.get("doublePlayProb", 0))
                hard_min = float(self.config.get("dpHardMinProb", 0.35))
                if self.config.get("dpAlwaysTurn", 0):
                    dp_success = True
                else:
                    if dp_prob > 0:
                        dp_prob = max(dp_prob, hard_min)
                    margin = (force_runner_time - force_fielder_time) if (force_runner_time and force_fielder_time) else None
                    time_margin = batter_time - relay_time
                    force_auto = (margin is not None) and margin >= float(self.config.get("dpForceAutoSec", 0.25))
                    relay_auto = time_margin >= float(self.config.get("dpRelayAutoSec", 0.30))
                    if dp_prob <= 0:
                        dp_success = bool(margin and margin > 0 and time_margin > 0)
                    else:
                        dp_success = False
                        if time_margin > 0:
                            if force_auto and relay_auto:
                                dp_success = True
                            else:
                                if margin is not None and margin > 0:
                                    dp_prob = min(
                                        1.0,
                                        dp_prob
                                        + margin
                                        * float(self.config.get("dpForceBoostPerSec", 0.10)),
                                    )
                                if time_margin > 0:
                                    dp_prob = min(
                                        1.0,
                                        dp_prob
                                        + time_margin
                                        * float(self.config.get("dpRelayBoostPerSec", 0.12)),
                                    )
                                dp_success = self.rng.random() < dp_prob
                        else:
                            dp_success = self.rng.random() < dp_prob
                if dp_success:
                    outs += 1
                    self._add_stat(batter_state, "gidp")
                    self.dp_made += 1
                    self._register_contact_play(batter_state, offense, defense, trigger="collision", fielder_positions=["1B"])
                    # Second out at first: 4-3 on the relay (2B -> 1B)
                    two_fs = self._get_fielder(defense, "2B")
                    oneb_fs = self._get_fielder(defense, "1B")
                    if oneb_fs is not None:
                        self._add_fielding_stat(oneb_fs, "po", position="1B")
                    if two_fs is not None:
                        self._add_fielding_stat(two_fs, "a")
                elif (
                    dp_prob > 0
                    and (
                        self.fielding_ai.should_relay_throw(relay_time, batter_time)
                        and self.fielding_ai.should_tag_runner(relay_time, batter_time)
                    )
                ):
                    outs += 1
                    self._add_stat(batter_state, "gidp")
                    self._register_contact_play(batter_state, offense, defense, trigger="collision", fielder_positions=["1B"])
                    # Second out at first on relay: credit as above
                    two_fs = self._get_fielder(defense, "2B")
                    oneb_fs = self._get_fielder(defense, "1B")
                    if oneb_fs is not None:
                        self._add_fielding_stat(oneb_fs, "po", position="1B")
                    if two_fs is not None:
                        self._add_fielding_stat(two_fs, "a")
                else:
                    new_bases[0] = batter_state
                    new_bp[0] = defense.current_pitcher_state
                    self._add_stat(batter_state, "fc")
            else:
                new_bases[0] = batter_state
                new_bp[0] = defense.current_pitcher_state

            offense.bases = new_bases
            offense.base_pitchers = new_bp
            return outs

        for idx in range(2, -1, -1):
            runner = b[idx]
            if runner is None:
                continue
            target = idx + bases
            if target >= 3:
                self._score_runner(
                    offense,
                    defense,
                    idx,
                    batter_state=batter_state,
                    credit_rbi=not error,
                )
                runs_scored += 1
            else:
                new_bases[target] = runner
                new_bp[target] = bp[idx]

        offense.bases = new_bases
        offense.base_pitchers = new_bp

        if bases >= 4:
            offense.runs += 1
            self._add_stat(batter_state, "r")
            pitcher = defense.current_pitcher_state
            if pitcher is not None:
                pitcher.r += 1
                pitcher.er += 1
                pitcher.toast += self.config.get("pitchScoringRun", 0)
                pitcher.toast += self.config.get("pitchScoringER", 0)
            runs_scored += 1
        else:
            base_idx = bases - 1
            offense.bases[base_idx] = batter_state
            offense.base_pitchers[base_idx] = defense.current_pitcher_state

        return outs

    def _advance_walk(
        self, offense: TeamState, defense: TeamState, batter_state: BatterState
    ) -> None:
        b = offense.bases
        bp = offense.base_pitchers
        new_bases: List[Optional[BatterState]] = [None, None, None]
        new_bp: List[Optional[PitcherState]] = [None, None, None]
        runs_scored = 0
        if b[2] and b[1] and b[0]:
            self._score_runner(
                offense,
                defense,
                2,
                batter_state=batter_state,
            )
            runs_scored += 1
        if b[1] and b[0]:
            new_bases[2] = b[1]
            new_bp[2] = bp[1]
        elif b[2]:
            new_bases[2] = b[2]
            new_bp[2] = bp[2]
        if b[0]:
            new_bases[1] = b[0]
            new_bp[1] = bp[0]
        new_bases[0] = batter_state
        new_bp[0] = defense.current_pitcher_state
        offense.bases = new_bases
        offense.base_pitchers = new_bp

    def _advance_passed_ball(
        self, offense: TeamState, defense: TeamState
    ) -> None:
        """Advance all runners one base on a passed ball."""

        b = offense.bases
        bp = offense.base_pitchers
        if b[2]:
            self._score_runner(
                offense,
                defense,
                2,
            )
        if b[1]:
            offense.bases[2] = b[1]
            offense.base_pitchers[2] = bp[1]
            offense.bases[1] = None
            offense.base_pitchers[1] = None
        if b[0]:
            offense.bases[1] = b[0]
            offense.base_pitchers[1] = bp[0]
            offense.bases[0] = None
            offense.base_pitchers[0] = None

    def _maybe_passed_ball(
        self,
        offense: TeamState,
        defense: TeamState,
        catcher_fs: Optional[FieldingState],
    ) -> bool:
        """Return ``True`` if a passed ball occurs."""

        if catcher_fs is None or not any(offense.bases):
            return False
        fa = catcher_fs.player.fa
        pb_chance = max(0.0, 0.01 - fa / 10000)
        if pb_chance <= 1e-4 and fa >= 90:
            return False
        if self.rng.random() < pb_chance:
            self._add_fielding_stat(catcher_fs, "pb")
            self._advance_passed_ball(offense, defense)
            return True
        return False

    def _maybe_catcher_interference(
        self,
        offense: TeamState,
        defense: TeamState,
        batter_state: BatterState,
        catcher_fs: Optional[FieldingState],
        pitcher_state: PitcherState,
        start_pitches: int,
    ) -> bool:
        """Return ``True`` if catcher's interference is called."""

        if catcher_fs is None:
            return False
        fa = catcher_fs.player.fa
        ci_chance = max(0.0, 0.001 - fa / 100000)
        if self.rng.random() < ci_chance:
            self._add_fielding_stat(catcher_fs, "ci")
            self._add_stat(batter_state, "ci")
            self._advance_walk(offense, defense, batter_state)
            self._add_stat(
                batter_state, "pitches", pitcher_state.pitches_thrown - start_pitches
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Steal attempts
    # ------------------------------------------------------------------
    def _attempt_steal(
        self,
        offense: TeamState,
        defense: TeamState,
        pitcher: Pitcher,
        *,
        force: bool = False,
        batter: Player | None = None,
        balls: int = 0,
        strikes: int = 0,
        outs: int = 0,
        runner_on: int = 1,
        batter_ch: int = 50,
        pitcher_is_wild: bool = False,
        pitcher_in_windup: bool = False,
        run_diff: int = 0,
    ) -> Optional[bool]:
        base_idx = runner_on - 1
        if base_idx not in (0, 1):
            return None
        runner_state = offense.bases[base_idx]
        if not runner_state:
            return None
        force_hit_and_run = force and getattr(self, "_hit_and_run_active", False)
        self._last_steal_forced = force_hit_and_run
        if runner_state.lead < 2 and not force_hit_and_run:
            return None
        if runner_on == 2 and offense.bases[2] is not None:
            return None
        attempt = force
        if not attempt:
            if batter is not None:
                batter_ch = batter.ch
            chance = self.offense.calculate_steal_chance(
                balls=balls,
                strikes=strikes,
                runner_sp=runner_state.player.sp,
                pitcher_hold=pitcher.hold_runner,
                pitcher_is_left=pitcher.bats == "L",
                pitcher_is_wild=pitcher_is_wild,
                pitcher_in_windup=pitcher_in_windup,
                outs=outs,
                runner_on=runner_on,
                batter_ch=batter_ch,
                run_diff=run_diff,
            )
            try:
                attempt_scale = float(self.config.get("stealAttemptAggressionScale", 1.0))
            except Exception:
                attempt_scale = 1.0
            if attempt_scale <= 0:
                chance = 0.0
            else:
                chance = min(1.0, chance * attempt_scale)
            # Apply configurable minimum attempt probability gate
            try:
                min_attempt = float(self.config.get("stealAttemptMinProb", 0.0))
            except Exception:
                min_attempt = 0.0
            if chance <= 0.0 or chance < min_attempt:
                attempt = False
            elif chance >= 1.0:
                attempt = True
            else:
                attempt = self.rng.random() < chance
        if attempt:
            catcher_fs = self._get_fielder(defense, "C")
            if catcher_fs and self._maybe_passed_ball(offense, defense, catcher_fs):
                self._add_stat(runner_state, "sb")
                return True
            # Determine success probability; invert prior logic which used a tag-out chance as success.
            catcher_arm = catcher_fs.player.arm if catcher_fs else 50
            catcher_fa = catcher_fs.player.fa if catcher_fs else 50
            runner_sp = runner_state.player.sp
            base_success = self.config.get("stealSuccessBasePct", 72) / 100.0
            base_success = max(0.55, min(0.92, base_success))
            speed_adj = (runner_sp - 50) / 250.0
            catcher_penalty = max(0.0, (catcher_arm - 50) / 220.0)
            catcher_bonus = max(0.0, (50 - catcher_arm) / 260.0)
            pitcher_penalty = max(0.0, (pitcher.arm - 50) / 380.0)
            pitcher_bonus = max(0.0, (50 - pitcher.arm) / 420.0)
            hold_penalty = max(0.0, (pitcher.hold_runner - 50) / 280.0)
            hold_bonus = max(0.0, (50 - pitcher.hold_runner) / 320.0)
            reaction_penalty = 0.0
            self._last_steal_terms = {
                "catcher_penalty": catcher_penalty,
                "catcher_bonus": catcher_bonus,
                "pitcher_penalty": pitcher_penalty,
                "pitcher_bonus": pitcher_bonus,
                "hold_penalty": hold_penalty,
                "hold_bonus": hold_bonus,
            }
            try:
                penalty_scale = float(self.config.get("stealDefensivePenaltyScale", 1.0))
            except Exception:
                penalty_scale = 1.0
            penalty_scale = max(0.0, penalty_scale)
            if catcher_fs:
                reaction_penalty = max(0.0, (catcher_fa - 50) / 320.0)
                if force_hit_and_run and reaction_penalty > 0:
                    reaction_penalty *= 0.5
                delay_base = self.config.get("delayBaseCatcher", 0)
                delay_pct = self.config.get("delayFAPctCatcher", 0)
                if delay_base or delay_pct:
                    reaction_delay = self.physics.reaction_delay("C", catcher_fa)
                    # Treat quicker catchers (shorter delay) as more likely to record the out.
                    # Scale against a mid-range reaction window so tests can tune catcher delays.
                    reaction_penalty += max(0.0, (15.0 - reaction_delay) / 10.0)
            catcher_penalty *= penalty_scale
            pitcher_penalty *= penalty_scale
            hold_penalty *= penalty_scale
            reaction_penalty *= penalty_scale
            lead_bonus = 0.02 if runner_state.lead >= 2 else 0.0
            if force_hit_and_run:
                lead_bonus += 0.0
            self._last_lead_bonus = lead_bonus
            success_prob = (
                base_success
                + speed_adj
                + lead_bonus
                + catcher_bonus
                + pitcher_bonus
                + hold_bonus
            )
            success_prob -= catcher_penalty + pitcher_penalty + hold_penalty + reaction_penalty
            max_success = 0.95 if not force_hit_and_run else 0.97
            self._last_max_success = max_success
            try:
                success_prob += float(self.config.get("stealSuccessAdjustment", 0.0))
            except Exception:
                pass
            success_prob = max(0.28, min(max_success, success_prob))
            # Apply configurable minimum success probability gate for attempts (non-forced)
            if not force and success_prob < float(self.config.get("stealMinSuccessProb", 0.0)):
                return None
            if force_hit_and_run:
                hnr_bonus = self.config.get("hnrChance3BallsAdjust", 0) / 500.0
                self._last_hnr_bonus = hnr_bonus
                success_prob = min(max_success, success_prob + hnr_bonus)
                force_hit_and_run = False
            self._last_steal_prob = success_prob
            steal_roll = self.rng.random()
            if steal_roll < success_prob:
                ps_runner = offense.base_pitchers[base_idx]
                offense.bases[base_idx] = None
                offense.base_pitchers[base_idx] = None
                offense.bases[base_idx + 1] = runner_state
                offense.base_pitchers[base_idx + 1] = ps_runner
                self._add_stat(runner_state, "sb")
                if catcher_fs:
                    self._add_fielding_stat(catcher_fs, "sba")
                return True
            # Caught stealing
            offense.bases[base_idx] = None
            offense.base_pitchers[base_idx] = None
            self._add_stat(runner_state, "cs")
            if catcher_fs:
                self._add_fielding_stat(catcher_fs, "sba")
                self._add_fielding_stat(catcher_fs, "cs")
                self._add_fielding_stat(catcher_fs, "a")
            if runner_on == 1:
                tagger = self._get_fielder(defense, "2B") or self._get_fielder(defense, "SS")
            else:
                tagger = self._get_fielder(defense, "3B")
            if tagger:
                self._add_fielding_stat(
                    tagger,
                    "po",
                    position=getattr(tagger.player, "primary_position", None),
                )
            return False
        return None

    # ------------------------------------------------------------------
    # Pitching changes
    # ------------------------------------------------------------------

GameSimulation._original_foul_probability = GameSimulation._foul_probability

def generate_boxscore(home: TeamState, away: TeamState) -> Dict[str, Dict[str, object]]:
    """Return a simplified box score for ``home`` and ``away`` teams."""

    def team_section(team: TeamState) -> Dict[str, object]:
        batting = []
        for bs in team.lineup_stats.values():
            line = {
                "player": bs.player,
                "pa": bs.pa,
                "ab": bs.ab,
                "r": bs.r,
                "h": bs.h,
                "1b": bs.b1,
                "2b": bs.b2,
                "3b": bs.b3,
                "hr": bs.hr,
                "rbi": bs.rbi,
                "bb": bs.bb,
                "ibb": bs.ibb,
                "hbp": bs.hbp,
                "so": bs.so,
                "sh": bs.sh,
                "sf": bs.sf,
                "roe": bs.roe,
                "fc": bs.fc,
                "ci": bs.ci,
                "gidp": bs.gidp,
                "sb": bs.sb,
                "cs": bs.cs,
                "po": bs.po,
                "pocs": bs.pocs,
            }
            line.update(compute_batting_derived(bs))
            line.update(compute_batting_rates(bs))
            batting.append(line)
        pitching = []
        for ps in team.pitcher_stats.values():
            sim_pitches = getattr(ps, "simulated_pitches", 0)
            sim_strikes = getattr(ps, "simulated_strikes", 0)
            sim_balls = getattr(ps, "simulated_balls", 0)
            total_pitches = max(0, getattr(ps, "pitches_thrown", 0) - sim_pitches)
            actual_strikes = max(0, getattr(ps, "strikes_thrown", 0) - sim_strikes)
            actual_balls = max(0, getattr(ps, "balls_thrown", 0) - sim_balls)
            extra_balls = max(0, total_pitches - actual_strikes)
            walk_balls = getattr(ps, "bb", 0) * 4 + getattr(ps, "hbp", 0)
            counted_balls = min(extra_balls, walk_balls)
            line = {
                "player": ps.player,
                "g": getattr(ps, "g", 0),
                "gs": getattr(ps, "gs", 0),
                "bf": getattr(ps, "bf", 0),
                "outs": getattr(ps, "outs", 0),
                "r": getattr(ps, "r", 0),
                "er": getattr(ps, "er", 0),
                "h": getattr(ps, "h", 0),
                "1b": getattr(ps, "b1", 0),
                "2b": getattr(ps, "b2", 0),
                "3b": getattr(ps, "b3", 0),
                "hr": getattr(ps, "hr", 0),
                "bb": getattr(ps, "bb", 0),
                "ibb": getattr(ps, "ibb", 0),
                "hbp": getattr(ps, "hbp", 0),
                "so": getattr(ps, "so", 0),
                "wp": getattr(ps, "wp", 0),
                "bk": getattr(ps, "bk", 0),
                "pk": getattr(ps, "pk", 0),
                "pocs": getattr(ps, "pocs", 0),
                "ir": getattr(ps, "ir", 0),
                "irs": getattr(ps, "irs", 0),
                "gf": getattr(ps, "gf", 0),
                "sv": getattr(ps, "sv", 0),
                "bs": getattr(ps, "bs", 0),
                "hld": getattr(ps, "hld", 0),
                "svo": getattr(ps, "svo", 0),
                "pitches": total_pitches,
                "strikes": actual_strikes,
                "balls": actual_balls,
            }
            line.update(compute_pitching_derived(ps))
            line.update(compute_pitching_rates(ps))
            pitching.append(line)
        fielding = []
        for fs in team.fielding_stats.values():
            line = {
                "player": fs.player,
                "g": fs.g,
                "gs": fs.gs,
                "po": fs.po,
                "a": fs.a,
                "e": fs.e,
                "dp": fs.dp,
                "tp": fs.tp,
                "pk": fs.pk,
                "pb": fs.pb,
                "ci": fs.ci,
                "cs": fs.cs,
                "sba": fs.sba,
            }
            line.update(compute_fielding_derived(fs))
            line.update(compute_fielding_rates(fs))
            fielding.append(line)
        return {
            "score": team.runs,
            "batting": batting,
            "pitching": pitching,
            "fielding": fielding,
            "inning_runs": team.inning_runs,
        }

    return {"home": team_section(home), "away": team_section(away)}


# ---------------------------------------------------------------------------
# Box score HTML rendering / saving
# ---------------------------------------------------------------------------
from datetime import datetime
from pathlib import Path


def render_boxscore_html(
    box: Dict[str, Dict[str, object]],
    home_name: str = "Home",
    away_name: str = "Away",
    league: str = "League",
    home_abbr: str | None = None,
    away_abbr: str | None = None,
) -> str:
    """Render ``box`` using the ``espn_boxscore_template.html`` sample."""

    if str(os.getenv("PB_SKIP_BOXSCORE_HTML", "")).lower() in {"1", "true", "yes", "on"}:
        return ""

    home_abbr = home_abbr or home_name
    away_abbr = away_abbr or away_name

    template_path = get_base_dir() / "samples" / "espn_boxscore_template.html"
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError:
        # Template missing from a packaged build — degrade gracefully so
        # the season sim doesn't bubble [Errno 2] up into the UI. The
        # box dict still drives the in-app boxscore card; only the
        # exported HTML view is unavailable.
        return ""

    repl: Dict[str, object] = {
        "league": league,
        "home.name": home_name,
        "away.name": away_name,
        "home.abbr": home_abbr,
        "away.abbr": away_abbr,
        "home.score": box["home"]["score"],
        "away.score": box["away"]["score"],
    }

    def totals(side: str) -> tuple[int, int, int]:
        hits = sum(e["h"] for e in box[side]["batting"])
        errors = sum(e["e"] for e in box[side]["fielding"])
        return box[side]["score"], hits, errors

    for side in ("home", "away"):
        r, h, e = totals(side)
        repl[f"totals.{side}.r"] = r
        repl[f"totals.{side}.h"] = h
        repl[f"totals.{side}.e"] = e

    for i in range(9):
        repl[f"linescore.home[{i}]"] = (
            box["home"]["inning_runs"][i] if i < len(box["home"]["inning_runs"]) else ""
        )
        repl[f"linescore.away[{i}]"] = (
            box["away"]["inning_runs"][i] if i < len(box["away"]["inning_runs"]) else ""
        )

    import re

    def replace_loop(var: str, key: str, entries: list[dict]) -> None:
        nonlocal template
        pattern = re.compile(rf"{{{{#for {var} in {key}}}}}(.*?){{{{/for}}}}", re.DOTALL)
        m = pattern.search(template)
        if not m:
            return
        block = m.group(1)
        rows: list[str] = []
        for entry in entries:
            row = block
            p = entry["player"]
            name = f"{p.first_name} {p.last_name}"
            if var == "batter":
                mapping = {
                    "name": name,
                    "pos": getattr(p, "position", ""),
                    "AB": entry.get("ab", 0),
                    "R": entry.get("r", 0),
                    "H": entry.get("h", 0),
                    "RBI": entry.get("rbi", 0),
                    "BB": entry.get("bb", 0),
                    "K": entry.get("so", 0),
                    "HR": entry.get("hr", 0),
                    "AVG": f"{entry.get('avg', 0):.3f}",
                    "OBP": f"{entry.get('obp', 0):.3f}",
                    "SLG": f"{entry.get('slg', 0):.3f}",
                }
            else:
                outs = entry.get("outs", 0)
                ip = f"{outs // 3}.{outs % 3}"
                mapping = {
                    "name": name,
                    "IP": ip,
                    "H": entry.get("h", 0),
                    "R": entry.get("r", 0),
                    "ER": entry.get("er", 0),
                    "BB": entry.get("bb", 0),
                    "K": entry.get("so", 0),
                    "HR": entry.get("hr", 0),
                    "PC-ST": f"{entry.get('pitches', 0)}-{entry.get('strikes', 0)}",
                    "ERA": f"{entry.get('era', 0):.2f}",
                }
            for k, v in mapping.items():
                row = row.replace(f"{{{{{var}.{k}}}}}", str(v))
            rows.append(row)
        template = pattern.sub("".join(rows), template)

    replace_loop("batter", "batting.home", box["home"]["batting"])
    replace_loop("batter", "batting.away", box["away"]["batting"])
    replace_loop("pitcher", "pitching.home", box["home"]["pitching"])
    replace_loop("pitcher", "pitching.away", box["away"]["pitching"])

    def batting_totals(side: str) -> tuple[int, int, int, int, int, int, int]:
        entries = box[side]["batting"]
        ab = sum(e["ab"] for e in entries)
        r = sum(e["r"] for e in entries)
        h = sum(e["h"] for e in entries)
        rbi = sum(e["rbi"] for e in entries)
        bb = sum(e["bb"] for e in entries)
        k = sum(e["so"] for e in entries)
        hr = sum(e["hr"] for e in entries)
        return ab, r, h, rbi, bb, k, hr

    for side in ("home", "away"):
        ab, r, h, rbi, bb, k, hr = batting_totals(side)
        repl[f"batting_totals.{side}.AB"] = ab
        repl[f"batting_totals.{side}.R"] = r
        repl[f"batting_totals.{side}.H"] = h
        repl[f"batting_totals.{side}.RBI"] = rbi
        repl[f"batting_totals.{side}.BB"] = bb
        repl[f"batting_totals.{side}.K"] = k
        repl[f"batting_totals.{side}.HR"] = hr
        repl[f"notes.{side}.batting"] = ""
        repl[f"notes.{side}.risp"] = ""
        repl[f"notes.{side}.fielding"] = ""

    for key, value in repl.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))

    # Remove any unreplaced placeholders to avoid leaking template tokens
    template = re.sub(r"{{[^{}]+}}", "", template)
    return template


def save_boxscore_html(game_type: str, html: str, game_id: str | None = None) -> str:
    """Persist ``html`` to the appropriate box score directory.

    Parameters
    ----------
    game_type:
        Either ``"exhibition"`` or ``"season"``.
    html:
        The HTML to write.
    game_id:
        Optional file name stem.  If not provided a timestamp is used.

    Returns
    -------
    str
        Full path of the written file.
    """

    base = get_data_dir() / "boxscores" / game_type
    base.mkdir(parents=True, exist_ok=True)
    if game_id is None:
        game_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = base / f"{game_id}.html"
    path.write_text(html, encoding="utf-8")
    return str(path)


__all__ = [
    "BatterState",
    "FieldingState",
    "TeamState",
    "GameSimulation",
    "generate_boxscore",
    "render_boxscore_html",
    "save_boxscore_html",
]
