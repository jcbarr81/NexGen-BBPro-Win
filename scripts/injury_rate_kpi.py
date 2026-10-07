#!/usr/bin/env python3
"""Measure the physics-sim injury rate against its calibration targets.

The standard KPI harness (``physics_sim_season_kpis.py``) validates offensive
and pitching rates but tracks NO injury metric, even though the engine runs with
injuries enabled by default. This script fills that gap: it runs a physics
season with injuries on and reports the metrics needed to calibrate injuries --

  * injured-list (IL) stints per team per 162-game season, all and pitchers
  * pitcher share of IL stints
  * average days per IL stint
  * every injury event (IL + day-to-day) per team-season, for information
  * a per-trigger / per-severity / per-tier breakdown
  * Release 3 (pitcher arm hazard): the starters' share of pitcher IL, the
    mean pitcher stint after the list minimum, the 60-day share and the
    bottom-vs-top durability quintile hazard ratio
  * report-only: hitter IL and the fatigue-linked hitter injuries (owner Q14)

Audit M15 (2026-10-06): the targets are injured-list stints, so only events
that put a player on an injured list (``dl_tier`` other than ``none``) are
compared with them. Day-to-day knocks are reported separately.

Two modes:

``--mode static`` (default)
    The calibration harness loop: ``simulate_matchup_from_files`` over a
    generated schedule with static rosters. An injured player is never
    removed and can be hurt again, and the facilities void/recovery factors
    are not applied, so read the IL numbers as an upper bound.

``--mode game_runner``
    The live path: the fixture is copied into a scratch league (never a real
    one), the schedule runs through ``SeasonSimulator`` +
    ``game_runner.simulate_game_scores``, injuries go through
    ``_apply_injury_events`` (the real IL placements and CPU call-ups) and
    ``services.dl_automation`` activates returners after every day. Use a
    live-format fixture with minor leaguers (``data/calibration_league``) so
    injured players can be replaced; ``data/calibration``'s players.csv is
    engine-only and is refused. ``--batching daily`` drops the in-process sim
    state between days the way a fresh process would.

Targets. Owner decision (2026-10-07): pitcher injuries at about 3/4 of MLB's
rate -- 9-10 pitcher IL stints per team-season (band 8.5-11); starters
0.35-0.50 of them; 40-65 days per stint after the list minimum; a 60-day
share of 0.25-0.35; and a bottom-vs-top durability quintile hazard ratio of
at least 1.8. MLB references (``calc_injury_baseline.py`` over the
roster-resource injury workbook; audit M15): ~11.4 pitcher IL stints per team
in-season (~15.3 counting offseason stints); pitchers are ~51% of in-season
stints; ~27.3 IL stints per team and ~78 days per stint including offseason
stints.

Examples:
    python scripts/injury_rate_kpi.py --seed 1
    python scripts/injury_rate_kpi.py --mode game_runner \\
        --base-dir data/calibration_league --seed 1 --work-dir <scratch dir>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from playbalance.schedule_generator import generate_mlb_schedule
from physics_sim.engine import simulate_matchup_from_files
from physics_sim.usage import UsageState

# Reuse the calibration harness's fixture/lineup setup + player helpers so this
# script measures the same league the KPI harness does.
import physics_sim_season_kpis as kpi

SEASON_GAMES = 162
SEASON_START = date(2025, 4, 1)


class ScheduleError(Exception):
    """The schedule generator rejected the requested season length."""


DEFAULT_BASE_DIR = Path("data") / "calibration"

# Real-MLB baselines (audit M15; calc_injury_baseline.py over the
# roster-resource workbook). In-season figures.
MLB_PITCHER_IL_PER_TEAM = 11.4  # in-season
MLB_PITCHER_IL_PER_TEAM_WITH_OFFSEASON = 15.3
MLB_PITCHER_IL_BAND = (11.0, 15.0)
MLB_PITCHER_SHARE = 0.51  # in-season
MLB_PITCHER_SHARE_WITH_OFFSEASON = 0.557
MLB_IL_PER_TEAM_WITH_OFFSEASON = 27.3
MLB_DAYS_PER_STINT = 78.0

# Release 3 calibration targets (owner, 2026-10-07: ~3/4 of MLB's rate).
TARGET_PITCHER_IL_PER_TEAM = 9.5
TARGET_PITCHER_IL_BAND = (8.5, 11.0)
TARGET_SP_SHARE_BAND = (0.35, 0.50)
TARGET_DAYS_AFTER_FLOOR_BAND = (40.0, 65.0)
TARGET_IL60_SHARE_BAND = (0.25, 0.35)
TARGET_DURABILITY_RATIO_MIN = 1.8

# Tiers that are NOT an injured-list placement (game_runner treats these as
# day-to-day and never calls place_on_injury_list).
_NON_IL_TIERS = {"", "none"}
_IL60_TIERS = {"il60", "ir", "dl45", "45", "45-day", "45 day"}
_ARM_TRIGGER = "pitcher_arm"
_FATIGUE_TRIGGER = "batter_fatigue"


def _is_pitcher(pid: str, positions: Mapping[str, str]) -> bool:
    return str(positions.get(pid, "")).upper() in {"P", "SP", "RP"}


def is_il_stint(event: Mapping[str, object]) -> bool:
    """True when the injury event puts the player on an injured list."""
    return str(event.get("dl_tier") or "").strip().lower() not in _NON_IL_TIERS


def _is_il60(event: Mapping[str, object]) -> bool:
    return str(event.get("dl_tier") or "").strip().lower() in _IL60_TIERS


def stint_days_after_floor(event: Mapping[str, object], *, pitcher: bool) -> int:
    """Days on the list: the injury's duration, never under the list minimum.

    60 days on the 60-day list; otherwise 15 for a pitcher and 10 for a
    position player (``services.injury_manager``: the minimum is a floor).
    """

    floor = 60 if _is_il60(event) else (15 if pitcher else 10)
    tier = str(event.get("dl_tier") or "").strip().lower()
    if tier in {"il7", "7-day"}:
        floor = 7
    elif tier in {"il10", "10-day"}:
        floor = 10
    try:
        days = int(event.get("days") or 0)
    except (TypeError, ValueError):
        days = 0
    return max(floor, days)


def _per_team_season(count: int, total_team_games: int) -> float:
    if not total_team_games:
        return 0.0
    return count / total_team_games * SEASON_GAMES


def durability_quintile_ratio(
    events: Iterable[Mapping[str, object]],
    appearances: Mapping[str, int],
    durability: Mapping[str, float],
) -> float | None:
    """Arm-injury rate per appearance, bottom vs top durability quintile.

    Pitchers who appeared are split into quintiles by durability; the ratio
    is (arm IL stints / appearances) in the bottom fifth over the top fifth.
    ``None`` when durability does not vary (e.g. every pitcher at 50) or the
    top fifth had no injuries.
    """

    pitched = [pid for pid, n in appearances.items() if n > 0 and pid in durability]
    if len(pitched) < 10:
        return None
    values = sorted(durability[pid] for pid in pitched)
    if values[0] == values[-1]:
        return None
    cuts = statistics.quantiles(values, n=5)
    low = {pid for pid in pitched if durability[pid] <= cuts[0]}
    high = {pid for pid in pitched if durability[pid] > cuts[-1]}
    arm = Counter(
        str(e.get("player_id"))
        for e in events
        if is_il_stint(e) and e.get("trigger") == _ARM_TRIGGER
    )

    def _rate(group: set) -> float:
        apps = sum(appearances[pid] for pid in group)
        hurt = sum(arm[pid] for pid in group)
        return hurt / apps if apps else 0.0

    top = _rate(high)
    if top <= 0.0:
        return None
    return round(_rate(low) / top, 2)


def summarize_events(
    events: Iterable[Mapping[str, object]],
    *,
    total_team_games: int,
    positions: Mapping[str, str],
    appearances: Mapping[str, int] | None = None,
    durability: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """Reduce engine injury events to per-team-season IL metrics.

    Rates are per team-game scaled to 162, so a short run is comparable with
    a full season. An event is a pitcher's when the player is a pitcher or
    the trigger is a pitcher-only one.
    """
    events = list(events)
    il = [e for e in events if is_il_stint(e)]

    def _pitcher_event(e: Mapping[str, object]) -> bool:
        return _is_pitcher(str(e.get("player_id")), positions) or e.get("trigger") in {
            _ARM_TRIGGER,
            "pitcher_overuse",
        }

    il_pitcher = [e for e in il if _pitcher_event(e)]
    days = [int(e.get("days") or 0) for e in il if e.get("days")]
    pitcher_days = [stint_days_after_floor(e, pitcher=True) for e in il_pitcher]
    starters = [e for e in il_pitcher if e.get("starter") is not None]
    fatigue = [e for e in events if e.get("trigger") == _FATIGUE_TRIGGER]
    return {
        "il_stints_total": len(il),
        "il_stints_per_team_season": round(
            _per_team_season(len(il), total_team_games), 2
        ),
        "pitcher_il_stints_per_team_season": round(
            _per_team_season(len(il_pitcher), total_team_games), 2
        ),
        "hitter_il_stints_per_team_season": round(
            _per_team_season(len(il) - len(il_pitcher), total_team_games), 2
        ),
        "pitcher_share_of_il": (
            round(len(il_pitcher) / len(il), 3) if il else None
        ),
        "avg_days_per_il_stint": (
            round(sum(days) / len(days), 1) if days else None
        ),
        # Release 3 pitcher-hazard targets.
        "pitcher_il_by_trigger": dict(
            Counter(str(e.get("trigger")) for e in il_pitcher)
        ),
        "sp_share_of_pitcher_il": (
            round(sum(1 for e in starters if e.get("starter")) / len(starters), 3)
            if starters
            else None
        ),
        "pitcher_il_days_after_floor": (
            round(sum(pitcher_days) / len(pitcher_days), 1) if pitcher_days else None
        ),
        "pitcher_il60_share": (
            round(sum(1 for e in il_pitcher if _is_il60(e)) / len(il_pitcher), 3)
            if il_pitcher
            else None
        ),
        "durability_quintile_hazard_ratio": (
            durability_quintile_ratio(events, appearances, durability)
            if appearances is not None and durability is not None
            else None
        ),
        # Report-only (owner Q10/Q14): tired hitters' injuries.
        "fatigue_injuries_per_team_season": round(
            _per_team_season(len(fatigue), total_team_games), 2
        ),
        "fatigue_il_stints_per_team_season": round(
            _per_team_season(sum(1 for e in fatigue if is_il_stint(e)), total_team_games),
            2,
        ),
        # Informational: every injury, day-to-day included (NOT comparable
        # with the IL-only MLB targets).
        "all_injury_events_total": len(events),
        "all_injury_events_per_team_season": round(
            _per_team_season(len(events), total_team_games), 2
        ),
        "il_by_trigger": dict(Counter(str(e.get("trigger")) for e in il)),
        "il_by_severity": dict(Counter(str(e.get("severity")) for e in il)),
        "all_by_tier": dict(
            Counter(str(e.get("dl_tier") or "none") for e in events)
        ),
    }


def _load_durability(players_path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    with Path(players_path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid = row.get("player_id")
            if not pid:
                continue
            try:
                out[pid] = float(row.get("durability") or 50.0)
            except ValueError:
                out[pid] = 50.0
    return out


def _calendar_day(token: str, day_map: dict[str, int]) -> int:
    """The rest-clock day for a schedule date.

    Release 3 item A moves the engine onto calendar days and adds
    ``physics_sim.usage.calendar_day``; use it when present so this harness
    runs on the same clock as the KPI harness. Until then, the index of the
    date among the season's game dates (the old clock).
    """

    try:
        from physics_sim.usage import calendar_day  # type: ignore[attr-defined]
    except ImportError:
        calendar_day = None
    if calendar_day is not None:
        try:
            return calendar_day(date.fromisoformat(token), SEASON_START)
        except ValueError:
            pass
    if token not in day_map:
        day_map[token] = len(day_map)
    return day_map[token]


def _record_game(
    meta: Mapping[str, object],
    appearances: Counter,
    events: list,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Tally appearances and collect the game's injury events.

    Events missing a ``starter`` flag (the in-game overuse roll) get one from
    the game's pitching lines.
    """

    starters: set[str] = set()
    for side_lines in (meta.get("pitcher_lines") or {}).values():
        for line in side_lines or []:
            if int(line.get("gs", 0) or 0) > 0:
                starters.add(str(line.get("player_id")))
    for side_usage in (meta.get("pitcher_usage") or {}).values():
        for usage in side_usage or []:
            if int(usage.get("pitches") or 0) > 0:
                appearances[str(usage.get("player_id"))] += 1
    for event in meta.get("injury_events", []) or []:
        if isinstance(event, dict) and "starter" not in event and event.get(
            "trigger"
        ) in {"pitcher_overuse", _ARM_TRIGGER}:
            event["starter"] = str(event.get("player_id")) in starters
        if extra is not None:
            event.update(extra)
        events.append(event)


def _report(
    *,
    mode: str,
    games_per_team: int,
    seed: int,
    n_teams: int,
    total_team_games: int,
    measured: dict,
    extra_config: Mapping[str, object] | None = None,
) -> dict:
    pitcher_rate = measured["pitcher_il_stints_per_team_season"]
    lo, hi = TARGET_PITCHER_IL_BAND

    def _in(value, band) -> bool | None:
        if value is None:
            return None
        return band[0] <= value <= band[1]

    ratio = measured["durability_quintile_hazard_ratio"]
    config = {
        "mode": mode,
        "games_per_team": games_per_team,
        "seed": seed,
        "teams": n_teams,
        "total_team_games": total_team_games,
    }
    config.update(extra_config or {})
    return {
        "config": config,
        "measured": measured,
        "targets": {
            "pitcher_il_stints_per_team_season": TARGET_PITCHER_IL_PER_TEAM,
            "pitcher_il_band": list(TARGET_PITCHER_IL_BAND),
            "sp_share_band": list(TARGET_SP_SHARE_BAND),
            "pitcher_il_days_after_floor_band": list(TARGET_DAYS_AFTER_FLOOR_BAND),
            "pitcher_il60_share_band": list(TARGET_IL60_SHARE_BAND),
            "durability_quintile_hazard_ratio_min": TARGET_DURABILITY_RATIO_MIN,
        },
        "mlb_targets": {
            "pitcher_il_stints_per_team_season": MLB_PITCHER_IL_PER_TEAM,
            "pitcher_il_stints_per_team_season_with_offseason": (
                MLB_PITCHER_IL_PER_TEAM_WITH_OFFSEASON
            ),
            "pitcher_il_band": list(MLB_PITCHER_IL_BAND),
            "pitcher_share_of_il": MLB_PITCHER_SHARE,
            "pitcher_share_of_il_with_offseason": MLB_PITCHER_SHARE_WITH_OFFSEASON,
            "il_stints_per_team_season_with_offseason": MLB_IL_PER_TEAM_WITH_OFFSEASON,
            "avg_days_per_il_stint": MLB_DAYS_PER_STINT,
        },
        "pitcher_il_in_band": lo <= pitcher_rate <= hi,
        "checks": {
            "pitcher_il": lo <= pitcher_rate <= hi,
            "sp_share": _in(measured["sp_share_of_pitcher_il"], TARGET_SP_SHARE_BAND),
            "days_after_floor": _in(
                measured["pitcher_il_days_after_floor"], TARGET_DAYS_AFTER_FLOOR_BAND
            ),
            "il60_share": _in(measured["pitcher_il60_share"], TARGET_IL60_SHARE_BAND),
            "durability_ratio": (
                None if ratio is None else ratio >= TARGET_DURABILITY_RATIO_MIN
            ),
        },
    }


def _schedule(teams: list[str], games_per_team: int) -> list[dict]:
    try:
        return generate_mlb_schedule(teams, SEASON_START, games_per_team)
    except ValueError as exc:
        raise ScheduleError(str(exc)) from exc


def measure(games_per_team: int, seed: int, players_path: Path, base_dir: Path | None):
    """Static mode: the calibration harness loop (rosters never change)."""

    teams_csv = (Path(base_dir) / "teams.csv") if base_dir is not None else None
    teams = kpi._team_ids(teams_csv)
    parks_by_team = kpi._team_parks(teams_csv)
    positions = kpi._load_player_positions(players_path)
    durability = _load_durability(players_path)
    schedule = _schedule(teams, games_per_team)

    # The arm hazard reads durability against the league's own ACT pitcher
    # mean (decision 2), which the live path gets from injury_settings.
    tuning_overrides = None
    if base_dir is not None:
        from services.injury_settings import active_pitcher_mean_durability

        center = active_pitcher_mean_durability(Path(base_dir))
        if center is not None:
            tuning_overrides = {"pitcher_arm_durability_center": center}

    usage_state = UsageState()
    rng = random.Random(seed)
    team_games: Counter = Counter()
    appearances: Counter = Counter()
    events: list[dict] = []
    day_map: dict[str, int] = {}
    for idx, game in enumerate(schedule):
        date_token = str(game.get("date") or idx)
        result = simulate_matchup_from_files(
            away_team=game["away"],
            home_team=game["home"],
            players_path=players_path,
            base_dir=base_dir,
            park_name=parks_by_team.get(game["home"]),
            seed=rng.randrange(2**32),
            tuning_overrides=tuning_overrides,
            usage_state=usage_state,
            game_day=_calendar_day(date_token, day_map),
        )
        meta = result.metadata or {}
        teams_meta = meta.get("teams", {})
        for side in ("away", "home"):
            team_id = teams_meta.get(side, game.get(side))
            if team_id:
                team_games[team_id] += 1
        _record_game(meta, appearances, events)

    total_team_games = sum(team_games.values())
    n_teams = len([t for t in team_games if team_games[t] > 0]) or len(teams)
    measured = summarize_events(
        events,
        total_team_games=total_team_games,
        positions=positions,
        appearances=appearances,
        durability=durability,
    )
    return _report(
        mode="static",
        games_per_team=games_per_team,
        seed=seed,
        n_teams=n_teams,
        total_team_games=total_team_games,
        measured=measured,
        extra_config={
            "durability_center": (tuning_overrides or {}).get(
                "pitcher_arm_durability_center"
            )
        },
    )


# ---------------------------------------------------------------------------
# game_runner mode
# ---------------------------------------------------------------------------

_KPI_LEAGUE_ID = "injury-kpi"


def _prepare_scratch_league(work_dir: Path, base_dir: Path) -> Path:
    """Copy the fixture into ``<work_dir>/leagues/injury-kpi/data``.

    Pre-creates ``leagues/`` and the league's own teams/players/users files so
    the data-root resolver never seeds a copy of the repository's data.
    """

    work_dir = Path(work_dir).resolve()
    league_data = work_dir / "leagues" / _KPI_LEAGUE_ID / "data"
    if league_data.exists():
        shutil.rmtree(league_data)
    league_data.mkdir(parents=True)
    for name in ("teams.csv", "players.csv"):
        shutil.copy2(base_dir / name, league_data / name)
    for folder in ("rosters", "lineups"):
        if (base_dir / folder).is_dir():
            shutil.copytree(base_dir / folder, league_data / folder)
    (league_data / "users.txt").write_text("", encoding="utf-8")
    catalog = ROOT / "data" / "injury_catalog.json"
    if catalog.exists():
        shutil.copy2(catalog, league_data / "injury_catalog.json")
    return league_data


def _write_schedule_csv(path: Path, schedule: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "home", "away", "result", "played"])
        for game in schedule:
            result = str(game.get("result") or "")
            writer.writerow(
                [game["date"], game["home"], game["away"], result, "1" if result else ""]
            )


def _fresh_process_state() -> None:
    """Drop the in-process sim state a new process would not have."""

    from playbalance import game_runner
    from utils import path_utils
    from utils.pitcher_recovery import PitcherRecoveryTracker
    from utils.roster_loader import load_roster

    for name, value in (
        ("_PHYSICS_USAGE_STATE", None),
        ("_PHYSICS_USAGE_DAY_MAP", {}),
        ("_PHYSICS_USAGE_YEAR", None),
        ("_PHYSICS_USAGE_LAST_DATE", None),
        ("_PHYSICS_USAGE_LEAGUE_KEY", None),
    ):
        if hasattr(game_runner, name):
            setattr(game_runner, name, value)
    try:  # Release 3 item A: the persisted usage store's in-process cache.
        from playbalance import usage_store  # type: ignore[attr-defined]

        usage_store.clear_cache()
    except Exception:
        pass
    try:
        game_runner._teams_by_id.cache_clear()
    except Exception:
        pass
    PitcherRecoveryTracker._instance = None
    load_roster.cache_clear()
    path_utils._DATA_DIR_CACHE.clear()


def measure_game_runner(
    games_per_team: int,
    seed: int,
    base_dir: Path,
    *,
    work_dir: Path | None = None,
    batching: str = "persistent",
) -> dict:
    """Live-path mode: real IL placements, call-ups and activations.

    Runs in a scratch data root (``NEXGEN_DATA_ROOT`` + ``set_request_league``)
    and asserts every write stays under it.
    """

    base_dir = Path(base_dir).resolve()
    owns_work_dir = work_dir is None
    work_dir = Path(work_dir or tempfile.mkdtemp(prefix="injury_kpi_")).resolve()
    repo_data = (ROOT / "data").resolve()
    if work_dir == repo_data or repo_data in work_dir.parents:
        raise SystemExit("--work-dir must be outside the repository's data/ folder")
    # Fail on a bad season length or a fixture the live loader can't read
    # (data/calibration's players.csv is engine-only) before anything is
    # written.
    _schedule(kpi._team_ids(base_dir / "teams.csv"), games_per_team)
    try:
        from utils.player_loader import load_players_from_csv

        load_players_from_csv(base_dir / "players.csv")
    except Exception as exc:
        raise SystemExit(
            f"{base_dir} is not a live-format league ({exc}); game_runner mode "
            "needs one such as data/calibration_league."
        ) from exc
    league_data = _prepare_scratch_league(work_dir, base_dir)

    for key in ("NEXGEN_DISCORD_WEBHOOK_URL", "NEXGEN_WORKING_COPY", "SENDGRID_API_KEY",
                "PB_PARALLEL_GAMES", "NEXGEN_ACTIVE_LEAGUE"):
        os.environ.pop(key, None)
    os.environ["NEXGEN_DATA_ROOT"] = str(work_dir)
    from utils import path_utils

    path_utils._DATA_DIR_CACHE.clear()
    path_utils.set_request_league(_KPI_LEAGUE_ID)
    data_dir = path_utils.get_data_dir().resolve()
    if data_dir != league_data.resolve():
        raise SystemExit(f"scratch league did not resolve: {data_dir}")

    from physics_sim import engine
    from playbalance import game_runner
    from playbalance.season_simulator import SeasonSimulator
    from services.dl_automation import process_disabled_lists

    try:
        from api.routers.season import _prepare_rosters_for_date as prepare_rosters
    except Exception:  # pragma: no cover - the API layer is optional here
        prepare_rosters = None

    teams = kpi._team_ids(league_data / "teams.csv")
    positions = kpi._load_player_positions(league_data / "players.csv")
    durability = _load_durability(league_data / "players.csv")
    schedule = _schedule(teams, games_per_team)
    for game in schedule:
        game["date"] = str(game["date"])
    _write_schedule_csv(league_data / "schedule.csv", schedule)
    dates = sorted({g["date"] for g in schedule})

    appearances: Counter = Counter()
    engine_events: list[dict] = []
    applied: list[dict] = []
    real_simulate_game = engine.simulate_game
    real_apply = game_runner._apply_injury_events
    current = {"date": None}

    def _recording_simulate_game(*args, **kwargs):
        result = real_simulate_game(*args, **kwargs)
        _record_game(result.metadata or {}, appearances, engine_events)
        return result

    def _recording_apply(events, **kwargs):
        real_apply(events, **kwargs)
        for event in events or []:
            if isinstance(event, dict):
                applied.append(dict(event, date=current["date"]))

    engine.simulate_game = _recording_simulate_game
    game_runner._apply_injury_events = _recording_apply
    # Box-score HTML is irrelevant here and the slowest part of a game.
    real_render = game_runner.render_boxscore_html
    game_runner.render_boxscore_html = lambda *a, **k: ""
    moves = Counter()
    try:
        random.seed(seed)
        sim = SeasonSimulator(schedule, game_runner.simulate_game_scores)
        seed_rng = None
        for day in dates:
            if batching == "daily":
                _fresh_process_state()
                path_utils.set_request_league(_KPI_LEAGUE_ID)
                sim = SeasonSimulator(schedule, game_runner.simulate_game_scores)
                sim._seed_rng = seed_rng
                sim._index = dates.index(day)
            current["date"] = day
            if prepare_rosters is not None:
                # The season router's pre-day step: emergency call-ups and the
                # CPU clubs' roster upkeep.
                prepare_rosters(sim, day)
            while sim.simulate_next_day() == 0:
                pass
            seed_rng = sim._seed_rng
            _write_schedule_csv(league_data / "schedule.csv", schedule)
            next_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
            summary = process_disabled_lists(today=next_day, auto_activate=True)
            moves["activated"] += len(summary.activated)
            moves["blocked"] += len(summary.blocked)
            done = dates.index(day) + 1
            if done % 20 == 0 or done == len(dates):
                print(
                    f"  {done}/{len(dates)} days, {len(applied)} injuries applied",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        engine.simulate_game = real_simulate_game
        game_runner._apply_injury_events = real_apply
        game_runner.render_boxscore_html = real_render

    played = [g for g in schedule if str(g.get("result") or "").strip()]
    total_team_games = 2 * len(played)
    measured = summarize_events(
        applied,
        total_team_games=total_team_games,
        positions=positions,
        appearances=appearances,
        durability=durability,
    )
    measured["engine_events_total"] = len(engine_events)
    measured["activations"] = moves["activated"]
    measured["activations_blocked"] = moves["blocked"]
    report = _report(
        mode="game_runner",
        games_per_team=games_per_team,
        seed=seed,
        n_teams=len(teams),
        total_team_games=total_team_games,
        measured=measured,
        extra_config={
            "batching": batching,
            "work_dir": None if owns_work_dir else str(work_dir),
            "durability_center": _read_center(league_data),
        },
    )
    if owns_work_dir:
        shutil.rmtree(work_dir, ignore_errors=True)
    return report


def _read_center(league_data: Path) -> float | None:
    from services.injury_settings import DURABILITY_CENTER_FILENAME

    try:
        payload = json.loads((league_data / DURABILITY_CENTER_FILENAME).read_text())
        seasons = payload.get("seasons") or {}
        return next(iter(seasons.values())) if seasons else None
    except (OSError, ValueError):
        return None


def _fmt(value: object) -> str:
    return "n/a" if value is None else str(value)


def _print_report(report: dict) -> None:
    cfg, m = report["config"], report["measured"]
    t, mlb = report["targets"], report["mlb_targets"]
    print(
        f"[{cfg.get('mode', 'static')}] Ran {cfg['games_per_team']} games/team over "
        f"{cfg['teams']} teams ({cfg['total_team_games']} team-games), seed {cfg['seed']}."
    )
    print("Injured-list stints only; rates per team per 162 games.")
    print("")
    print(f"{'metric':<36}{'measured':>10}{'target':>22}")
    print("-" * 68)
    lo, hi = t["pitcher_il_band"]
    rows = [
        (
            "pitcher IL stints / team",
            m["pitcher_il_stints_per_team_season"],
            f"{t['pitcher_il_stints_per_team_season']} ({lo:g}-{hi:g})",
        ),
        (
            "starters' share of pitcher IL",
            m["sp_share_of_pitcher_il"],
            "{:g}-{:g}".format(*t["sp_share_band"]),
        ),
        (
            "pitcher days / stint (after floor)",
            m["pitcher_il_days_after_floor"],
            "{:g}-{:g}".format(*t["pitcher_il_days_after_floor_band"]),
        ),
        (
            "pitcher 60-day share",
            m["pitcher_il60_share"],
            "{:g}-{:g}".format(*t["pitcher_il60_share_band"]),
        ),
        (
            "durability Q1/Q5 hazard ratio",
            m["durability_quintile_hazard_ratio"],
            f">= {t['durability_quintile_hazard_ratio_min']:g}",
        ),
        (
            "pitcher share of IL stints",
            m["pitcher_share_of_il"],
            f"MLB ~{mlb['pitcher_share_of_il']}",
        ),
        (
            "all IL stints / team",
            m["il_stints_per_team_season"],
            f"MLB {mlb['il_stints_per_team_season_with_offseason']} w/ off",
        ),
        ("hitter IL stints / team", m["hitter_il_stints_per_team_season"], "report"),
        ("fatigue injuries / team", m["fatigue_injuries_per_team_season"], "report"),
        (
            "avg days / IL stint",
            m["avg_days_per_il_stint"],
            f"MLB {mlb['avg_days_per_il_stint']} w/ off",
        ),
    ]
    for label, value, target in rows:
        print(f"{label:<36}{_fmt(value):>10}{target:>22}")
    print("")
    print(
        f"pitcher IL in target band: {'yes' if report['pitcher_il_in_band'] else 'NO'}"
    )
    print(f"checks: {report['checks']}")
    print(
        f"all injury events (incl. day-to-day): {m['all_injury_events_total']} "
        f"({m['all_injury_events_per_team_season']} / team-season)"
    )
    print(f"pitcher IL by trigger: {m['pitcher_il_by_trigger']}")
    print(f"IL by trigger:  {m['il_by_trigger']}")
    print(f"IL by severity: {m['il_by_severity']}")
    print(f"all by tier:    {m['all_by_tier']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure physics-sim injury rate vs targets.")
    parser.add_argument(
        "--games", type=int, default=SEASON_GAMES, help="Games per team (default 162)."
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--mode",
        choices=("static", "game_runner"),
        default="static",
        help="static: calibration harness loop; game_runner: the live path in "
        "a scratch league (real IL placements, call-ups and activations).",
    )
    parser.add_argument(
        "--batching",
        choices=("persistent", "daily"),
        default="persistent",
        help="game_runner mode: keep in-process sim state across days, or drop "
        "it between days like a fresh process.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="game_runner mode: scratch data root (default: a temp dir, removed "
        "afterwards). Never point this at a real league.",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=DEFAULT_BASE_DIR,
        help="League folder with teams.csv/rosters/lineups (default: the "
        "calibration fixture).",
    )
    parser.add_argument(
        "--players",
        type=Path,
        default=None,
        help="players.csv (default: <base-dir>/players.csv).",
    )
    parser.add_argument("--ensure-lineups", action="store_true")
    parser.add_argument("--output", type=Path, default=None, help="Write JSON report here.")
    args = parser.parse_args(argv)

    base_dir = args.base_dir
    if base_dir is not None and not base_dir.is_absolute():
        base_dir = (kpi.BASE_DIR / base_dir).resolve()
    players_path = args.players
    if players_path is None:
        candidate = base_dir / "players.csv" if base_dir is not None else None
        players_path = (
            candidate
            if candidate is not None and candidate.exists()
            else kpi._default_players_path()
        )
    if not players_path.is_absolute():
        players_path = (kpi.BASE_DIR / players_path).resolve()

    if args.ensure_lineups:
        teams_csv = (base_dir / "teams.csv") if base_dir is not None else None
        for team_id in kpi._team_ids(teams_csv):
            kpi._ensure_team_files(
                team_id, players_path=players_path,
                base_dir=base_dir if base_dir is not None else kpi.BASE_DIR,
            )

    try:
        if args.mode == "game_runner":
            report = measure_game_runner(
                args.games,
                args.seed,
                base_dir,
                work_dir=args.work_dir,
                batching=args.batching,
            )
        else:
            report = measure(args.games, args.seed, players_path, base_dir)
    except ScheduleError as exc:
        # e.g. --games below the schedule generator's minimum for the league.
        parser.error(str(exc))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
