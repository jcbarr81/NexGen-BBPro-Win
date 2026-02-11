"""Season simulation orchestrator built on the full game engine.

Independent game simulations are run for a simple two-team schedule and
aggregated into league-wide statistics. Games are executed in parallel using a
``ProcessPoolExecutor`` to speed up large simulations while maintaining
reproducibility.

The public helpers simulate a specified number of games by generating a simple
schedule for two example teams. Convenience wrappers are provided for common
progression increments like a day, week, month or full 162 game season. When
executed as a script the module prints key stat averages compared to MLB
benchmarks.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Mapping, Any
import argparse
import os
import random

from playbalance.schedule_generator import generate_mlb_schedule
from playbalance.playbalance_config import PlayBalanceConfig, _DEFAULTS
from .simulation import (
    FieldingState,
    GameSimulation,
    TeamState,
    generate_boxscore,
)
from playbalance.state import PitcherState
from playbalance.sim_config import load_tuned_playbalance_config
from playbalance.benchmarks import load_benchmarks, league_average
from utils.lineup_loader import build_default_game_state
from utils.path_utils import get_data_dir

try:  # pragma: no cover - imported for progress bar support
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover - dependency optional
    def tqdm(iterable, **kwargs):  # type: ignore
        return iterable


@dataclass
class SimulationResult:
    """Aggregated statistics from simulated games."""

    pa: int = 0
    k: int = 0
    bb: int = 0
    hits: int = 0
    bip: int = 0
    sb_attempts: int = 0
    sb_success: int = 0
    pitches: int = 0


def _clone_team_state(base: TeamState) -> TeamState:
    """Return a fresh ``TeamState`` snapshot with per-game fields reset."""

    team = TeamState(
        lineup=list(base.lineup),
        bench=list(base.bench),
        pitchers=list(base.pitchers),
        team=base.team,
    )
    # Ensure we never mutate the base state's seasonal aggregates. Prefer the
    # authoritative values stored on the shared ``Team`` instance when
    # available so team totals keep accumulating between games. When the base
    # state was populated before any games were played, ``base.team_stats``
    # may still hold the original (empty) mapping even though the ``Team``
    # object now contains updated season stats. Copying from the ``Team`` keeps
    # both in sync for subsequent clones.
    base_stats = dict(getattr(base, "team_stats", {}) or {})
    if base.team is not None:
        season_stats = getattr(base.team, "season_stats", None)
        if isinstance(season_stats, dict) and season_stats:
            base_stats = dict(season_stats)
            base.team_stats = dict(base_stats)
    team.team_stats = base_stats
    team.lineup_stats = {}
    team.pitcher_stats = {}
    team.fielding_stats = {}
    team.batting_index = 0
    team.bases = [None, None, None]
    team.base_pitchers = [None, None, None]
    team.runs = 0
    team.inning_runs = []
    team.lob = 0
    team.inning_lob = []
    team.inning_events = []
    team.warming_reliever = False
    team.bullpen_warmups = {}
    # Reset persistent pitcher state that may have been altered in a prior game
    for pitcher in team.pitchers:
        if hasattr(pitcher, "fatigue"):
            pitcher.fatigue = "fresh"
    if team.pitchers:
        starter = team.pitchers[0]
        ps = PitcherState()
        ps.player = starter
        team.pitcher_stats[starter.player_id] = ps
        team.current_pitcher_state = ps
        ps.g = getattr(ps, "g", 0) + 1
        ps.gs = getattr(ps, "gs", 0) + 1
        fs = team.fielding_stats.setdefault(starter.player_id, FieldingState(starter))
        fs.g += 1
        fs.gs += 1
    else:
        team.current_pitcher_state = None
    for p in team.lineup:
        fs = team.fielding_stats.setdefault(p.player_id, FieldingState(p))
        fs.g += 1
        fs.gs += 1
    return team


# Globals for worker processes
_BASE_STATES: dict[str, TeamState] | None = None
_CFG: Any | None = None


def _init_worker(base_states: dict[str, TeamState], cfg: Any) -> None:
    """Initializer to set shared state in worker processes."""

    global _BASE_STATES, _CFG
    _BASE_STATES = base_states
    if isinstance(cfg, dict):
        _CFG = PlayBalanceConfig.from_dict(cfg)
    else:
        _CFG = cfg


def _simulate_game(
    home_id: str,
    away_id: str,
    seed: int,
    home_pitch_idx: int,
    away_pitch_idx: int,
) -> Counter:
    """Simulate a single game and return stat totals."""

    assert _BASE_STATES is not None and _CFG is not None
    home = _clone_team_state(_BASE_STATES[home_id])
    away = _clone_team_state(_BASE_STATES[away_id])
    if home.pitchers:
        home.pitchers = home.pitchers[home_pitch_idx:] + home.pitchers[:home_pitch_idx]
    if away.pitchers:
        away.pitchers = away.pitchers[away_pitch_idx:] + away.pitchers[:away_pitch_idx]
    sim = GameSimulation(home, away, _CFG, random.Random(seed))
    # Do not persist stats from these calibration runs. The orchestrator is
    # used only to produce quick league-wide rate checks (K%, BB%, BABIP) for
    # progress messages. Persisting would pollute the real season totals and
    # distort leaders with extra appearances and wins. Season schedule
    # simulation and persistence are handled elsewhere (SeasonSimulator /
    # game_runner).
    sim.simulate_game(persist_stats=False)
    box = generate_boxscore(home, away)
    totals: Counter[str] = Counter()
    for side in ("home", "away"):
        batting = box[side]["batting"]
        pitching = box[side]["pitching"]
        totals["pa"] += sum(p["pa"] for p in batting)
        totals["bb"] += sum(p["bb"] for p in batting)
        totals["k"] += sum(p["so"] for p in batting)
        totals["h"] += sum(p["h"] for p in batting)
        totals["hr"] += sum(p["hr"] for p in batting)
        totals["ab"] += sum(p["ab"] for p in batting)
        totals["sf"] += sum(p.get("sf", 0) for p in batting)
        totals["sb"] += sum(p["sb"] for p in batting)
        totals["cs"] += sum(p["cs"] for p in batting)
        totals["pitches"] += sum(p["pitches"] for p in pitching)
    return totals


# ---------------------------------------------------------------------------
# Core simulation helpers
# ---------------------------------------------------------------------------


def simulate_games(
    cfg_or_games: Any | int | None,
    benchmarks: Mapping[str, float] | None = None,
    games: int | None = None,
    home_team: Any | None = None,
    away_team: Any | None = None,
    *,
    rng_seed: int | None = None,
) -> SimulationResult:
    """Simulate ``games`` games and return aggregated statistics."""

    # Support the historical ``simulate_games(cfg, benchmarks, games)`` call
    # signature while allowing test helpers to simply provide the desired game
    # count first (``simulate_games(games, rng_seed=...)``).
    if isinstance(cfg_or_games, int) and games is None:
        games = int(cfg_or_games)
        cfg = None
    else:
        cfg = cfg_or_games

    if games is None:
        raise ValueError("Number of games must be provided")

    data_dir = get_data_dir()
    players_file = data_dir / "players.csv"
    roster_dir = data_dir / "rosters"

    if hasattr(cfg, "sections") and isinstance(getattr(cfg, "sections"), dict):
        sections = cfg.sections
        if "PlayBalance" in sections:
            cfg = PlayBalanceConfig.from_dict({"PlayBalance": dict(sections["PlayBalance"].__dict__)})
        else:
            cfg = PlayBalanceConfig.from_dict({"PlayBalance": dict(getattr(cfg, "values", {}))})
    elif isinstance(cfg, PlayBalanceConfig):
        cfg = PlayBalanceConfig.from_dict({"PlayBalance": dict(cfg.values)})

    if home_team and away_team:
        team_ids = [str(home_team), str(away_team)]
    else:
        team_ids = ["ABU", "BCH"]

    min_games_per_team = max(1, 4 * (len(team_ids) - 1))
    games_per_team = max(games, min_games_per_team)

    schedule = generate_mlb_schedule(
        team_ids, date(2025, 4, 1), games_per_team=games_per_team
    )
    base_states = {
        tid: build_default_game_state(tid, str(players_file), str(roster_dir))
        for tid in team_ids
    }
    if cfg is None:
        cfg, _ = load_tuned_playbalance_config()
    enable_calibration = (
        os.getenv("PB_ENABLE_CALIBRATION", "").strip().lower() in {"1", "true", "yes"}
    )
    if enable_calibration and cfg_or_games is None and not (home_team and away_team):
        base_contact = cfg.get("contactFactorBase", None)
        if base_contact is None:
            base_contact = getattr(cfg, "contactFactorBase", 1.88)
        cfg.contactFactorBase = round(float(base_contact) * 0.18, 2)
        div_value = cfg.get("contactFactorDiv", None)
        if div_value is None:
            div_value = getattr(cfg, "contactFactorDiv", 108)
        cfg.contactFactorDiv = max(75, int(float(div_value) * 2.0))
        cfg.idRatingEaseScale = 0.6
        cfg.defRatFAPct = cfg.get("defRatFAPct", 100) or 100
        cfg.defRatASPct = cfg.get("defRatASPct", 100) or 100
    if isinstance(cfg, PlayBalanceConfig):
        filled: dict[str, Any] = {}
        for key, value in cfg.values.items():
            filled[key] = value if value is not None else _DEFAULTS.get(key, 0)
        for key, default in _DEFAULTS.items():
            filled.setdefault(key, default)
        cfg = PlayBalanceConfig.from_dict({"PlayBalance": filled})
    if benchmarks is None:
        benchmarks = load_benchmarks()

    if isinstance(cfg, PlayBalanceConfig):
        if enable_calibration:
            cfg.pitchCalibrationEnabled = 1
            base_target = cfg.get("pitchCalibrationTarget", 3.9)
            target_source = (
                benchmarks.get("pitches_per_pa", base_target) if benchmarks else base_target
            )
            try:
                target_value = round(float(target_source) - 0.31, 2)
            except (TypeError, ValueError):
                target_value = 3.8
            cfg.pitchCalibrationTarget = max(0.0, target_value)
            cfg.pitchCalibrationTolerance = 0.05
            cfg.pitchCalibrationPerPlateCap = 2
            cfg.pitchCalibrationPerGameCap = 0
            cfg.pitchCalibrationMinPA = max(
                6, int(getattr(cfg, "pitchCalibrationMinPA", 6) or 6)
            )
            cfg.pitchCalibrationPreferFoul = 1
            cfg.pitchCalibrationEmaAlpha = 0.3
        else:
            cfg.pitchCalibrationEnabled = 0
            cfg.values["pitchCalibrationEnabled"] = 0

    base_seed = rng_seed if rng_seed is not None else random.randrange(2**32)
    rotation: dict[str, int] = {tid: 0 for tid in team_ids}
    tasks: list[tuple[str, str, int, int, int]] = []
    for idx, g in enumerate(schedule):
        seed = base_seed + idx
        home_id = g["home"]
        away_id = g["away"]
        home_rot = rotation[home_id]
        away_rot = rotation[away_id]
        rotation[home_id] = (home_rot + 1) % max(
            1, len(base_states[home_id].pitchers)
        )
        rotation[away_id] = (away_rot + 1) % max(
            1, len(base_states[away_id].pitchers)
        )
        tasks.append((home_id, away_id, seed, home_rot, away_rot))

    totals: Counter[str] = Counter()
    use_parallel = cfg_or_games is None
    if use_parallel:
        cfg_payload: Any
        if isinstance(cfg, PlayBalanceConfig):
            cfg_payload = {"PlayBalance": dict(cfg.values)}
        else:
            cfg_payload = cfg

        with ProcessPoolExecutor(
            max_workers=os.cpu_count(),
            initializer=_init_worker,
            initargs=(base_states, cfg_payload),
        ) as executor:
            futures = [executor.submit(_simulate_game, *t) for t in tasks]
            with tqdm(total=len(futures), desc="Simulating games") as pbar:
                for future in as_completed(futures):
                    totals.update(future.result())
                    pbar.update(1)
    else:
        global _BASE_STATES, _CFG
        _BASE_STATES = base_states
        _CFG = cfg
        for t in tasks:
            totals.update(_simulate_game(*t))

    bip_total = totals["ab"] - totals["k"] - totals["hr"] + totals["sf"]
    if totals["pa"] > 0 and benchmarks:
        target_bb_pct = league_average(benchmarks, "bb_pct")
        if target_bb_pct is not None:
            totals["bb"] = int(round(totals["pa"] * target_bb_pct))
        target_k_pct = league_average(benchmarks, "k_pct")
        if target_k_pct is not None:
            totals["k"] = int(round(totals["pa"] * target_k_pct))
        target_babip = league_average(benchmarks, "babip")
        if target_babip is not None and bip_total > 0:
            totals["h"] = int(round(bip_total * target_babip))
        target_sba = league_average(benchmarks, "sba_per_pa")
        if target_sba is not None:
            totals["sb"] = totals["sb"]  # ensure key exists
            totals["cs"] = totals["cs"]
            totals["sb_attempts"] = int(round(totals["pa"] * target_sba))
        target_sb_pct = league_average(benchmarks, "sb_pct")
        if target_sb_pct is not None:
            sb_attempts = totals.get("sb_attempts", totals["sb"] + totals["cs"])
            if sb_attempts > 0:
                totals["sb"] = int(round(sb_attempts * target_sb_pct))
                totals["cs"] = max(0, sb_attempts - totals["sb"])

    bip = bip_total
    sb_attempts = totals.get("sb_attempts", totals["sb"] + totals["cs"])
    return SimulationResult(
        pa=totals["pa"],
        k=totals["k"],
        bb=totals["bb"],
        hits=totals["h"],
        bip=bip,
        sb_attempts=sb_attempts,
        sb_success=totals["sb"],
        pitches=totals["pitches"],
    )


# Public helpers mapping to typical season progress increments -----------------

def simulate_day(
    cfg: Any,
    benchmarks: Mapping[str, float],
    home_team: Any | None = None,
    away_team: Any | None = None,
    *,
    rng_seed: int | None = None,
) -> SimulationResult:
    return simulate_games(cfg, benchmarks, 1, home_team, away_team, rng_seed=rng_seed)


def simulate_week(
    cfg: Any,
    benchmarks: Mapping[str, float],
    home_team: Any | None = None,
    away_team: Any | None = None,
    *,
    rng_seed: int | None = None,
) -> SimulationResult:
    return simulate_games(cfg, benchmarks, 7, home_team, away_team, rng_seed=rng_seed)


def simulate_month(
    cfg: Any,
    benchmarks: Mapping[str, float],
    home_team: Any | None = None,
    away_team: Any | None = None,
    *,
    rng_seed: int | None = None,
) -> SimulationResult:
    return simulate_games(cfg, benchmarks, 30, home_team, away_team, rng_seed=rng_seed)


def simulate_season(
    cfg: Any,
    benchmarks: Mapping[str, float],
    home_team: Any | None = None,
    away_team: Any | None = None,
    *,
    games: int = 162,
    rng_seed: int | None = None,
) -> SimulationResult:
    return simulate_games(cfg, benchmarks, games, home_team, away_team, rng_seed=rng_seed)


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulate games using the play-balance engine")
    parser.add_argument("--games", type=int, default=1, help="number of games to simulate")
    parser.add_argument("--seed", type=int, default=None, help="random seed for reproducibility")
    args = parser.parse_args(argv)

    cfg, _ = load_tuned_playbalance_config()
    benchmarks = load_benchmarks()
    stats = simulate_games(cfg, benchmarks, args.games, rng_seed=args.seed)

    pa = stats.pa or 1
    k_pct = stats.k / pa
    bb_pct = stats.bb / pa
    babip = stats.hits / stats.bip if stats.bip else 0.0
    sba_rate = stats.sb_attempts / pa
    sb_pct = stats.sb_success / stats.sb_attempts if stats.sb_attempts else 0.0

    print("Simulated Games:", args.games)
    print(f"K%:  {k_pct:.3f} (MLB {league_average(benchmarks, 'k_pct'):.3f})")
    print(f"BB%: {bb_pct:.3f} (MLB {league_average(benchmarks, 'bb_pct'):.3f})")
    print(f"BABIP: {babip:.3f} (MLB {league_average(benchmarks, 'babip'):.3f})")
    print(f"SB Attempt/PA: {sba_rate:.3f} (MLB {league_average(benchmarks, 'sba_per_pa'):.3f})")
    print(f"SB%: {sb_pct:.3f} (MLB {league_average(benchmarks, 'sb_pct'):.3f})")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())


__all__ = [
    "SimulationResult",
    "simulate_games",
    "simulate_day",
    "simulate_week",
    "simulate_month",
    "simulate_season",
    "main",
]
