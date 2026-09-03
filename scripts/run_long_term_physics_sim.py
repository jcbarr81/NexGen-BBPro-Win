#!/usr/bin/env python3
"""Run a multi-season physics-sim league with aging, drafts, and playoffs."""
from __future__ import annotations

import argparse
import csv
import faulthandler
import json
import os
import random
import shutil
import signal
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover
    def tqdm(iterable, **kwargs):
        return iterable


DEFAULT_TOLERANCES: dict[str, float] = {
    "pitches_per_pa": 0.05,
    "zone_pct": 0.03,
    "swing_pct": 0.03,
    "z_swing_pct": 0.03,
    "o_swing_pct": 0.03,
    "pitches_put_in_play_pct": 0.03,
    "bb_pct": 0.01,
    "k_pct": 0.02,
    "hr_per_fb_pct": 0.02,
    "babip": 0.015,
    "sb_pct": 0.05,
    "sba_per_pa": 0.01,
    "bip_double_play_pct": 0.01,
}


def _resolve_output_dir(args: argparse.Namespace, repo_root: Path) -> Path:
    if args.output_dir:
        out = Path(args.output_dir).expanduser()
        if not out.is_absolute():
            out = repo_root / out
        return out
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return repo_root / "tmp" / "long_term_runs" / f"run_{stamp}"


def _link_or_copy(src: Path, dest: Path) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.symlink_to(src, target_is_directory=src.is_dir())
        return
    except Exception:
        pass
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _prepare_output_dir(
    out_dir: Path,
    repo_root: Path,
    *,
    force: bool,
    resume: bool,
) -> None:
    if out_dir.exists():
        if force:
            shutil.rmtree(out_dir)
        elif resume:
            return
        elif any(out_dir.iterdir()):
            raise RuntimeError(
                f"Output directory {out_dir} is not empty. Use --force to overwrite."
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "data", out_dir / "data", dirs_exist_ok=True)
    _link_or_copy(repo_root / "playbalance" / "PBINI.txt", out_dir / "playbalance" / "PBINI.txt")
    _link_or_copy(repo_root / "samples", out_dir / "samples")


def _restore_parks(repo_root: Path, data_dir: Path) -> None:
    parks_src = repo_root / "data" / "parks"
    if not parks_src.exists():
        return
    parks_dst = data_dir / "parks"
    if parks_dst.exists():
        shutil.rmtree(parks_dst)
    shutil.copytree(parks_src, parks_dst, dirs_exist_ok=True)


def _set_sim_date(target: date) -> None:
    os.environ["PB_SIM_DATE"] = target.isoformat()
    os.environ["PB_SIM_YEAR"] = str(target.year)


def _compute_draft_date(first_date: str | None) -> str | None:
    if not first_date:
        return None
    try:
        year = int(str(first_date).split("-")[0])
    except Exception:
        return None
    d = date(year, 7, 1)
    while d.weekday() != 1:
        d += timedelta(days=1)
    d += timedelta(days=14)
    return d.isoformat()


def _save_progress(
    path: Path,
    *,
    sim_index: int | None = None,
    preseason_done: dict[str, bool] | None = None,
    playoffs_done: bool | None = None,
) -> None:
    payload: dict[str, object] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            payload = {}
    if preseason_done is not None:
        payload["preseason_done"] = preseason_done
    if sim_index is not None:
        payload["sim_index"] = sim_index
    if playoffs_done is not None:
        payload["playoffs_done"] = playoffs_done
    if "auto_activate_dl" not in payload:
        # A batch run has no owner to wait on, so it must never honour the
        # league's manual-activation setting or players would pile up on the
        # injured list across simulated seasons.
        payload["auto_activate_dl"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _write_heartbeat(path: Path, payload: dict[str, object]) -> None:
    payload = dict(payload)
    payload["timestamp"] = _now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_benchmarks(path: Path) -> dict[str, float]:
    benchmarks: dict[str, float] = {}
    if not path.exists():
        return benchmarks
    with path.open() as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = row.get("metric_key")
            raw = row.get("value")
            if not key:
                continue
            try:
                benchmarks[str(key)] = float(raw)
            except (TypeError, ValueError):
                continue
    return benchmarks


def _aggregate_stats(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
    players = payload.get("players", {}) or {}
    batting = {
        "pa": 0.0,
        "ab": 0.0,
        "h": 0.0,
        "b1": 0.0,
        "b2": 0.0,
        "b3": 0.0,
        "hr": 0.0,
        "bb": 0.0,
        "hbp": 0.0,
        "sf": 0.0,
        "so": 0.0,
        "sb": 0.0,
        "cs": 0.0,
        "gidp": 0.0,
        "pitches": 0.0,
        "gb": 0.0,
        "ld": 0.0,
        "fb": 0.0,
    }
    pitching = {
        "bf": 0.0,
        "outs": 0.0,
        "h": 0.0,
        "hr": 0.0,
        "bb": 0.0,
        "so": 0.0,
        "pitches_thrown": 0.0,
        "balls_thrown": 0.0,
        "strikes_thrown": 0.0,
        "first_pitch_strikes": 0.0,
        "zone_pitches": 0.0,
        "o_zone_pitches": 0.0,
        "zone_swings": 0.0,
        "o_zone_swings": 0.0,
        "zone_contacts": 0.0,
        "o_zone_contacts": 0.0,
        "so_looking": 0.0,
        "so_swinging": 0.0,
        "gb": 0.0,
        "ld": 0.0,
        "fb": 0.0,
    }

    def _as_float(value: Any) -> float:
        if value in (None, ""):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    for stats in players.values():
        if stats.get("pa") is not None:
            for key in batting:
                batting[key] += _as_float(stats.get(key))
        if stats.get("bf") is not None or stats.get("outs") is not None:
            for key in pitching:
                pitching[key] += _as_float(stats.get(key))

    return {"batting": batting, "pitching": pitching}


def _rate(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _compute_metrics(totals: dict[str, dict[str, float]]) -> dict[str, float]:
    bat = totals["batting"]
    pit = totals["pitching"]

    pa = bat["pa"]
    ab = bat["ab"]
    h = bat["h"]
    hr = bat["hr"]
    so = bat["so"]
    bb = bat["bb"]
    hbp = bat["hbp"]
    sf = bat["sf"]
    b1 = bat["b1"]
    b2 = bat["b2"]
    b3 = bat["b3"]
    tb = b1 + 2 * b2 + 3 * b3 + 4 * hr

    bip = bat["gb"] + bat["ld"] + bat["fb"]
    pitches = bat["pitches"]

    swings = pit["zone_swings"] + pit["o_zone_swings"]
    contacts = pit["zone_contacts"] + pit["o_zone_contacts"]
    zone_pitches = pit["zone_pitches"]
    o_zone_pitches = pit["o_zone_pitches"]

    metrics = {
        "pitches_per_pa": _rate(pitches, pa),
        "avg": _rate(h, ab),
        "obp": _rate(h + bb + hbp, ab + bb + hbp + sf),
        "slg": _rate(tb, ab),
        "ops": _rate(h + bb + hbp, ab + bb + hbp + sf) + _rate(tb, ab),
        "iso": _rate(tb, ab) - _rate(h, ab),
        "babip": _rate(h - hr, ab - so - hr + sf),
        "k_pct": _rate(so, pa),
        "bb_pct": _rate(bb, pa),
        "k_minus_bb_pct": _rate(so - bb, pa),
        "swing_pct": _rate(swings, zone_pitches + o_zone_pitches),
        "z_swing_pct": _rate(pit["zone_swings"], zone_pitches),
        "o_swing_pct": _rate(pit["o_zone_swings"], o_zone_pitches),
        "contact_pct": _rate(contacts, swings),
        "z_contact_pct": _rate(pit["zone_contacts"], pit["zone_swings"]),
        "o_contact_pct": _rate(pit["o_zone_contacts"], pit["o_zone_swings"]),
        "first_pitch_strike_pct": _rate(pit["first_pitch_strikes"], pit["bf"]),
        "zone_pct": _rate(zone_pitches, zone_pitches + o_zone_pitches),
        "pitches_put_in_play_pct": _rate(bip, pitches),
        "bip_gb_pct": _rate(bat["gb"], bip),
        "bip_ld_pct": _rate(bat["ld"], bip),
        "bip_fb_pct": _rate(bat["fb"], bip),
        "hr_per_fb_pct": _rate(hr, bat["fb"] + hr),
        "sb_pct": _rate(bat["sb"], bat["sb"] + bat["cs"]),
        "sba_per_pa": _rate(bat["sb"] + bat["cs"], pa),
        "bip_double_play_pct": _rate(bat["gidp"], bip),
        "called_third_strike_share_of_so": _rate(
            pit["so_looking"], pit["so_looking"] + pit["so_swinging"]
        ),
    }
    return metrics


def _build_team_lookup(load_roster, load_teams) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for team in load_teams():
        try:
            roster = load_roster(team.team_id)
        except Exception:
            continue
        for pid in (roster.act + roster.aaa + roster.low + roster.dl + roster.ir):
            mapping[str(pid)] = team.team_id
    return mapping


def _ensure_active_rosters(
    *,
    players: dict[str, object],
    roster_dir: Path,
    load_roster,
    save_roster,
    load_teams,
    min_hitters: int = 9,
    min_pitchers: int = 1,
    active_max: int = 25,
) -> dict[str, int]:
    from utils.roster_backfill import ensure_active_rosters

    return ensure_active_rosters(
        players=players,
        roster_dir=roster_dir,
        min_hitters=min_hitters,
        min_pitchers=min_pitchers,
        active_max=active_max,
    )


def _ensure_free_agent_buffer(
    *,
    players: dict[str, object],
    roster_dir: Path,
    load_roster,
    load_teams,
    target_free_agents: int,
    year: int,
    rating_profile: str = "normalized",
) -> dict[str, int]:
    rostered: set[str] = set()
    for team in load_teams():
        roster = load_roster(team.team_id, roster_dir=roster_dir)
        rostered.update(roster.act + roster.aaa + roster.low + roster.dl + roster.ir)

    free_agents = [pid for pid in players.keys() if pid not in rostered]
    if len(free_agents) >= target_free_agents:
        return {"generated": 0, "free_agents": len(free_agents)}

    from playbalance import player_generator as pg
    from services import draft_assignment as draft_assign

    needed = target_free_agents - len(free_agents)
    existing_ids = set(players.keys())
    max_num = 0
    for pid in existing_ids:
        if pid.startswith("P") and pid[1:].isdigit():
            max_num = max(max_num, int(pid[1:]))

    def next_id() -> str:
        nonlocal max_num
        max_num += 1
        pid = f"P{max_num}"
        while pid in existing_ids:
            max_num += 1
            pid = f"P{max_num}"
        existing_ids.add(pid)
        return pid

    rows: list[dict[str, object]] = []
    for _ in range(needed):
        is_pitcher = random.random() < 0.45
        player = pg.generate_player(
            is_pitcher=is_pitcher,
            for_draft=False,
            rating_profile=rating_profile,
        )
        player["player_id"] = next_id()
        player["is_pitcher"] = bool(is_pitcher)
        rows.append(draft_assign._default_row_from_pool(player))

    draft_assign._append_players(rows)
    return {"generated": needed, "free_agents": len(free_agents) + needed}


def _leaders_for(
    players: Iterable[object],
    *,
    key: str,
    pitcher_only: bool,
    descending: bool,
    limit: int,
    min_pa: int,
    min_ip: float,
    team_lookup: dict[str, str],
) -> list[dict[str, object]]:
    entries: list[tuple[object, float]] = []
    for player in players:
        stats = getattr(player, "season_stats", {}) or {}
        if bool(getattr(player, "is_pitcher", False)) != pitcher_only:
            continue
        if pitcher_only:
            ip = stats.get("ip")
            if ip is None:
                outs = stats.get("outs", 0)
                try:
                    ip = float(outs) / 3.0
                except Exception:
                    ip = 0.0
            if key in {"era", "whip"} and min_ip and (ip or 0.0) < min_ip:
                continue
        else:
            pa = stats.get("pa", 0) or 0
            if key in {"avg", "obp", "slg", "ops"} and min_pa and pa < min_pa:
                continue
        value = stats.get(key)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        entries.append((player, numeric))
    entries.sort(key=lambda item: item[1], reverse=descending)
    leaders: list[dict[str, object]] = []
    for player, value in entries[:limit]:
        pid = str(getattr(player, "player_id", ""))
        name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip()
        leaders.append(
            {
                "player_id": pid,
                "name": name or pid,
                "team_id": team_lookup.get(pid, ""),
                "value": value,
            }
        )
    return leaders


def _summarize_season(
    *,
    stats_payload: dict[str, Any],
    benchmarks: dict[str, float],
    tolerances: dict[str, float],
    players_lookup: dict[str, object],
    team_lookup: dict[str, str],
    games_per_team: int,
) -> dict[str, object]:
    totals = _aggregate_stats(stats_payload)
    metrics = _compute_metrics(totals)
    deltas = {
        key: metrics[key] - benchmarks[key]
        for key in metrics
        if key in benchmarks
    }
    flags = [
        {
            "metric": key,
            "delta": deltas[key],
            "tolerance": tolerances[key],
        }
        for key in deltas
        if key in tolerances and abs(deltas[key]) > tolerances[key]
    ]

    players = list(players_lookup.values())
    min_pa = int(round(games_per_team * 3.1))
    min_ip = float(round(games_per_team * 1.0, 2))

    leaders = {
        "batting": {
            "avg": _leaders_for(
                players,
                key="avg",
                pitcher_only=False,
                descending=True,
                limit=3,
                min_pa=min_pa,
                min_ip=min_ip,
                team_lookup=team_lookup,
            ),
            "hr": _leaders_for(
                players,
                key="hr",
                pitcher_only=False,
                descending=True,
                limit=3,
                min_pa=0,
                min_ip=min_ip,
                team_lookup=team_lookup,
            ),
            "rbi": _leaders_for(
                players,
                key="rbi",
                pitcher_only=False,
                descending=True,
                limit=3,
                min_pa=0,
                min_ip=min_ip,
                team_lookup=team_lookup,
            ),
            "sb": _leaders_for(
                players,
                key="sb",
                pitcher_only=False,
                descending=True,
                limit=3,
                min_pa=0,
                min_ip=min_ip,
                team_lookup=team_lookup,
            ),
            "ops": _leaders_for(
                players,
                key="ops",
                pitcher_only=False,
                descending=True,
                limit=3,
                min_pa=min_pa,
                min_ip=min_ip,
                team_lookup=team_lookup,
            ),
        },
        "pitching": {
            "era": _leaders_for(
                players,
                key="era",
                pitcher_only=True,
                descending=False,
                limit=3,
                min_pa=min_pa,
                min_ip=min_ip,
                team_lookup=team_lookup,
            ),
            "so": _leaders_for(
                players,
                key="so",
                pitcher_only=True,
                descending=True,
                limit=3,
                min_pa=min_pa,
                min_ip=min_ip,
                team_lookup=team_lookup,
            ),
            "wins": _leaders_for(
                players,
                key="w",
                pitcher_only=True,
                descending=True,
                limit=3,
                min_pa=min_pa,
                min_ip=min_ip,
                team_lookup=team_lookup,
            ),
            "saves": _leaders_for(
                players,
                key="sv",
                pitcher_only=True,
                descending=True,
                limit=3,
                min_pa=min_pa,
                min_ip=min_ip,
                team_lookup=team_lookup,
            ),
        },
    }

    return {
        "metrics": metrics,
        "mlb_deltas": deltas,
        "flags": flags,
        "leaders": leaders,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a long-term physics engine sim with aging, draft, and playoffs."
    )
    parser.add_argument("--seasons", type=int, default=75)
    parser.add_argument("--teams", type=int, default=14)
    parser.add_argument("--games", type=int, default=162)
    parser.add_argument("--start-year", type=int, default=date.today().year)
    parser.add_argument("--league-name", type=str, default="NexGen Long Run")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--save-boxscores", action="store_true")
    parser.add_argument("--include-playoff-stats", action="store_true")
    parser.add_argument("--draft-rounds", type=int, default=None)
    parser.add_argument("--draft-pool-size", type=int, default=None)
    parser.add_argument("--heartbeat-every", type=int, default=1)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = _resolve_output_dir(args, repo_root)
    _prepare_output_dir(out_dir, repo_root, force=args.force, resume=args.resume)

    sys._MEIPASS = str(out_dir)
    sys.path.append(str(repo_root))

    os.environ.setdefault("PB_GAME_ENGINE", "physics")
    os.environ.setdefault("PB_RATING_PROFILE", "normalized")
    if not args.save_boxscores:
        os.environ["PB_SKIP_BOXSCORE_HTML"] = "1"

    from playbalance.league_creator import create_league
    from playbalance.team_name_generator import random_team, reset_name_pool
    from playbalance.schedule_generator import generate_mlb_schedule, save_schedule
    from playbalance.season_simulator import SeasonSimulator
    from playbalance.game_runner import simulate_game_scores
    from playbalance.season_context import SeasonContext
    from playbalance.playoffs import load_bracket, save_bracket, generate_bracket, simulate_playoffs
    from playbalance.playoffs_config import load_playoffs_config
    from playbalance.aging_model import age_and_retire
    from playbalance.training_camp import run_training_camp
    from playbalance.draft_pool import generate_draft_pool, save_draft_pool
    from playbalance.draft_config import load_draft_config
    from services.draft_state import compute_order_from_season_stats, initialize_state, append_result
    from services.draft_ai import compute_team_needs, score_prospect
    from services.draft_assignment import commit_draft_results
    from services.league_rollover import LeagueRolloverService
    from services.roster_auto_assign import auto_assign_all_teams
    from services.season_progress_flags import mark_draft_completed, mark_playoffs_completed
    from services.standings_repository import save_standings, load_standings
    from services.training_settings import load_training_settings
    from utils.player_loader import load_players_from_csv
    from utils.player_writer import save_players_to_csv
    from utils.roster_loader import load_roster, save_roster
    from utils.standings_utils import default_record, update_record
    from utils.team_loader import load_teams
    from playbalance.simulation import save_boxscore_html
    from utils.exceptions import DraftRosterError

    data_dir = out_dir / "data"
    analysis_dir = out_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    heartbeat_path = analysis_dir / "heartbeat.json"
    stack_path = analysis_dir / "stacktrace.log"
    stack_file = stack_path.open("a", encoding="utf-8")
    faulthandler.enable(file=stack_file)
    try:
        faulthandler.register(signal.SIGUSR1, file=stack_file, all_threads=True)
    except (ValueError, AttributeError):
        pass

    def log_phase(phase: str, **fields: object) -> None:
        _write_heartbeat(heartbeat_path, {"phase": phase, **fields})
        details = " ".join(f"{k}={v}" for k, v in fields.items())
        line = f"[{_now_iso()}] {phase}"
        if details:
            line = f"{line} {details}"
        print(line, flush=True)

    if not args.resume:
        reset_name_pool()
        team_count = max(args.teams, 2)
        teams_per_div = max(1, team_count // 2)
        teams = [random_team() for _ in range(team_count)]
        divisions = {
            "League East": teams[:teams_per_div],
            "League West": teams[teams_per_div:],
        }

        create_league(
            str(data_dir),
            divisions,
            args.league_name,
            rating_profile="normalized",
        )
        _restore_parks(repo_root, data_dir)
        log_phase("league_created", teams=team_count)
    else:
        log_phase("resume_run", output_dir=str(out_dir))

    benchmarks = _read_benchmarks(
        data_dir / "MLB_avg" / "mlb_league_benchmarks_2025_filled.csv"
    )
    tolerances = dict(DEFAULT_TOLERANCES)

    summaries_path = analysis_dir / "season_summaries.jsonl"
    completed_years: set[int] = set()
    if summaries_path.exists():
        if not args.resume:
            summaries_path.unlink()
        else:
            for line in summaries_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    completed_years.add(int(json.loads(line).get("year")))
                except Exception:
                    continue

    years = list(range(args.start_year, args.start_year + args.seasons))
    for year in years:
        if args.resume and year in completed_years:
            continue
        season_offset = year - args.start_year
        season_seed = None if args.seed is None else args.seed + season_offset
        if season_seed is not None:
            random.seed(season_seed)

        log_phase("season_start", year=year)
        if season_offset > 0:
            _set_sim_date(date(year, 1, 15))
            players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
            log_phase("aging_start", year=year, players=len(players))
            retired = age_and_retire(players)
            retired_ids = {p.player_id for p in retired}
            log_phase(
                "aging_done",
                year=year,
                retired=len(retired_ids),
                remaining=len(players),
            )
            if retired_ids:
                roster_dir = data_dir / "rosters"
                for team in load_teams():
                    team_id = team.team_id
                    try:
                        roster = load_roster(team_id, roster_dir=roster_dir)
                    except Exception:
                        continue
                    roster.act = [pid for pid in roster.act if pid not in retired_ids]
                    roster.aaa = [pid for pid in roster.aaa if pid not in retired_ids]
                    roster.low = [pid for pid in roster.low if pid not in retired_ids]
                    roster.dl = [pid for pid in roster.dl if pid not in retired_ids]
                    roster.ir = [pid for pid in roster.ir if pid not in retired_ids]
                    roster.dl_tiers = {
                        pid: tier
                        for pid, tier in (roster.dl_tiers or {}).items()
                        if pid not in retired_ids
                    }
                    save_roster(team_id, roster)
            save_players_to_csv(players.values(), "data/players.csv")
            try:
                load_players_from_csv.cache_clear()
            except Exception:
                pass
            try:
                load_roster.cache_clear()
            except Exception:
                pass
            auto_assign_all_teams(players_file="data/players.csv", roster_dir="data/rosters")
            try:
                load_roster.cache_clear()
            except Exception:
                pass
            try:
                team_count = len(load_teams())
                fa_target = max(200, team_count * 25)
                fa_summary = _ensure_free_agent_buffer(
                    players=players,
                    roster_dir=data_dir / "rosters",
                    load_roster=load_roster,
                    load_teams=load_teams,
                    target_free_agents=fa_target,
                    year=year,
                )
                if fa_summary.get("generated"):
                    log_phase(
                        "free_agents_generated",
                        year=year,
                        generated=fa_summary.get("generated"),
                        free_agents=fa_summary.get("free_agents"),
                    )
                    try:
                        load_players_from_csv.cache_clear()
                    except Exception:
                        pass
            except Exception as exc:
                log_phase("free_agents_failed", year=year, error=str(exc))

        _set_sim_date(date(year, 3, 1))
        players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
        log_phase("training_camp_start", year=year, players=len(players))
        try:
            settings = load_training_settings()
            roster_map = _build_team_lookup(load_roster, load_teams)
            allocations = {
                pid: settings.for_team(roster_map.get(pid))
                for pid in players.keys()
            }
        except Exception:
            allocations = {}
        run_training_camp(players.values(), allocations=allocations)
        save_players_to_csv(players.values(), "data/players.csv")
        try:
            load_players_from_csv.cache_clear()
        except Exception:
            pass
        log_phase("training_camp_done", year=year)

        try:
            roster_fix = _ensure_active_rosters(
                players=players,
                roster_dir=data_dir / "rosters",
                load_roster=load_roster,
                save_roster=save_roster,
                load_teams=load_teams,
            )
            log_phase(
                "roster_backfill",
                year=year,
                adjustments=roster_fix.get("adjustments"),
                free_agents_left=roster_fix.get("free_agents_left"),
            )
        except Exception as exc:
            log_phase("roster_backfill_failed", year=year, error=str(exc))

        team_ids = [team.team_id for team in load_teams()]
        start_date = date(year, 4, 1)
        schedule = generate_mlb_schedule(team_ids, start_date, games_per_team=args.games)
        save_schedule(schedule, data_dir / "schedule.csv")
        first_date = schedule[0]["date"] if schedule else ""
        draft_date = _compute_draft_date(first_date)
        log_phase("schedule_ready", year=year, games=len(schedule))

        ctx = SeasonContext.load()
        ctx.ensure_league(name=args.league_name)
        ctx.ensure_current_season(league_year=year, started_on=first_date)
        ctx.save()

        standings = {tid: default_record() for tid in team_ids}
        save_standings(standings, base_path=data_dir)
        team_divisions = {team.team_id: team.division for team in load_teams()}

        progress_path = data_dir / "season_progress.json"
        _save_progress(
            progress_path,
            sim_index=0,
            preseason_done={
                "free_agency": True,
                "training_camp": True,
                "schedule": True,
            },
            playoffs_done=False,
        )
        log_phase("season_sim_start", year=year)

        def simulate_game(home_id: str, away_id: str, seed: int | None = None, game_date: str | None = None):
            return simulate_game_scores(
                home_id,
                away_id,
                seed=seed,
                game_date=game_date,
                engine="physics",
            )

        def record_game(game: dict[str, str]) -> None:
            game["played"] = "1"
            html = game.pop("boxscore_html", None)
            if args.save_boxscores and html:
                game_id = f"{game.get('date','')}_{game.get('away','')}_at_{game.get('home','')}"
                path = save_boxscore_html("season", html, game_id)
                game["boxscore"] = path
            save_schedule(simulator.schedule, data_dir / "schedule.csv")

            result = game.get("result")
            if result and "-" in result:
                try:
                    home_score, away_score = map(int, result.split("-", 1))
                except ValueError:
                    home_score = away_score = 0
                home_id = game.get("home", "")
                away_id = game.get("away", "")
                meta = game.get("extra") or {}
                one_run = abs(home_score - away_score) == 1
                extra_innings = bool(meta.get("extra_innings"))
                home_hand = str(meta.get("home_starter_hand", "") or "").upper()
                away_hand = str(meta.get("away_starter_hand", "") or "").upper()
                division_game = (
                    team_divisions.get(home_id) == team_divisions.get(away_id)
                    if home_id and away_id
                    else False
                )
                if home_id:
                    record = standings.setdefault(home_id, default_record())
                    update_record(
                        record,
                        won=home_score > away_score,
                        runs_for=home_score,
                        runs_against=away_score,
                        home=True,
                        opponent_hand=away_hand,
                        division_game=division_game,
                        one_run=one_run,
                        extra_innings=extra_innings,
                    )
                if away_id:
                    record = standings.setdefault(away_id, default_record())
                    update_record(
                        record,
                        won=away_score > home_score,
                        runs_for=away_score,
                        runs_against=home_score,
                        home=False,
                        opponent_hand=home_hand,
                        division_game=division_game,
                        one_run=one_run,
                        extra_innings=extra_innings,
                    )
            save_standings(standings, base_path=data_dir)

        def on_draft_day(date_token: str) -> None:
            draft_year = int(str(date_token).split("-")[0])
            log_phase("draft_day_start", year=draft_year, date=date_token)
            cfg = load_draft_config()
            rounds = args.draft_rounds or int(cfg.get("rounds", 10) or 10)
            pool_size = args.draft_pool_size or int(cfg.get("pool_size", 200) or 200)
            pool_seed = cfg.get("seed")
            pool = generate_draft_pool(
                draft_year,
                size=pool_size,
                seed=pool_seed,
                rating_profile="normalized",
            )
            save_draft_pool(draft_year, pool)
            order = compute_order_from_season_stats(seed=pool_seed)
            if not order:
                order = list(team_ids)
            initialize_state(draft_year, order=order, seed=pool_seed)

            pool_map = {p.player_id: p for p in pool}
            available = list(pool_map.keys())
            overall = 1
            for rnd in range(1, rounds + 1):
                for team_id in order:
                    if not available:
                        break
                    needs = compute_team_needs(team_id)
                    best_id = max(
                        available,
                        key=lambda pid: score_prospect(pool_map[pid].__dict__, needs),
                    )
                    available.remove(best_id)
                    append_result(
                        draft_year,
                        team_id=team_id,
                        player_id=best_id,
                        rnd=rnd,
                        overall=overall,
                    )
                    overall += 1
                if not available:
                    break

            draft_summary: dict[str, object] | None = None
            try:
                draft_summary = commit_draft_results(draft_year, season_date=date_token)
            except DraftRosterError as exc:
                draft_summary = exc.summary or {"failures": exc.failures}
            finally:
                auto_assign_all_teams(players_file="data/players.csv", roster_dir="data/rosters")
                try:
                    load_roster.cache_clear()
                except Exception:
                    pass
                try:
                    load_players_from_csv.cache_clear()
                except Exception:
                    pass
                try:
                    players_for_backfill = {
                        p.player_id: p for p in load_players_from_csv("data/players.csv")
                    }
                    roster_fix = _ensure_active_rosters(
                        players=players_for_backfill,
                        roster_dir=data_dir / "rosters",
                        load_roster=load_roster,
                        save_roster=save_roster,
                        load_teams=load_teams,
                    )
                    log_phase(
                        "roster_backfill",
                        year=draft_year,
                        adjustments=roster_fix.get("adjustments"),
                        free_agents_left=roster_fix.get("free_agents_left"),
                    )
                except Exception as exc:
                    log_phase("roster_backfill_failed", year=draft_year, error=str(exc))
            if draft_summary and draft_summary.get("compliance_issues"):
                (analysis_dir / f"draft_{draft_year}.json").write_text(
                    json.dumps(
                        {
                            "year": draft_year,
                            "summary": draft_summary,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            log_phase(
                "draft_day_done",
                year=draft_year,
                added=draft_summary.get("players_added") if draft_summary else None,
                assigned=draft_summary.get("roster_assigned") if draft_summary else None,
            )
            mark_draft_completed(draft_year, progress_path=progress_path)

        simulator = SeasonSimulator(
            schedule,
            simulate_game,
            draft_date=draft_date,
            on_draft_day=on_draft_day,
            after_game=record_game,
        )

        season_bar = tqdm(range(len(simulator.dates)), desc=f"Season {year}")
        for _ in season_bar:
            simulator.simulate_next_day()
            _save_progress(progress_path, sim_index=simulator._index)
            if args.heartbeat_every > 0 and simulator._index % args.heartbeat_every == 0:
                current_date = (
                    simulator.dates[simulator._index]
                    if simulator._index < len(simulator.dates)
                    else None
                )
                _write_heartbeat(
                    heartbeat_path,
                    {
                        "phase": "simulate_day",
                        "year": year,
                        "day_index": simulator._index,
                        "total_days": len(simulator.dates),
                        "date": str(current_date) if current_date else None,
                    },
                )

        log_phase("season_sim_done", year=year)
        bracket = None
        try:
            bracket = load_bracket()
        except Exception:
            bracket = None
        if bracket is None or not getattr(bracket, "champion", None):
            cfg = load_playoffs_config()
            bracket = generate_bracket(load_standings(), load_teams(), cfg)
        if bracket and getattr(bracket, "rounds", None):
            prev_persist = os.environ.get("PB_PERSIST_STATS")
            if not args.include_playoff_stats:
                os.environ["PB_PERSIST_STATS"] = "0"
            try:
                bracket = simulate_playoffs(bracket, simulate_game=simulate_game, persist_cb=save_bracket)
            finally:
                if prev_persist is None:
                    os.environ.pop("PB_PERSIST_STATS", None)
                else:
                    os.environ["PB_PERSIST_STATS"] = prev_persist
        mark_playoffs_completed(progress_path=progress_path)
        _save_progress(progress_path, playoffs_done=True)
        log_phase("playoffs_done", year=year)

        rollover = LeagueRolloverService(ctx).archive_season(
            ended_on=str(simulator.dates[-1]) if simulator.dates else None,
            next_league_year=year + 1,
        )
        log_phase("season_archived", year=year, season_id=rollover.season_id)

        stats_path = out_dir / (rollover.artifacts.get("stats") or "")
        if stats_path.exists():
            stats_payload = json.loads(stats_path.read_text(encoding="utf-8"))
        else:
            stats_payload = {"players": {}, "teams": {}}

        players_lookup = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
        for pid, season in stats_payload.get("players", {}).items():
            if pid in players_lookup:
                players_lookup[pid].season_stats = season

        team_lookup = _build_team_lookup(load_roster, load_teams)
        summary = _summarize_season(
            stats_payload=stats_payload,
            benchmarks=benchmarks,
            tolerances=tolerances,
            players_lookup=players_lookup,
            team_lookup=team_lookup,
            games_per_team=args.games,
        )
        summary.update(
            {
                "year": year,
                "season_id": rollover.season_id,
                "champion": getattr(bracket, "champion", None) if bracket else None,
                "runner_up": getattr(bracket, "runner_up", None) if bracket else None,
            }
        )

        summary_path = analysis_dir / f"season_{year}.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        with summaries_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary) + "\n")
        log_phase("season_summary_written", year=year, summary=str(summary_path))

    try:
        all_summaries = [
            json.loads(line)
            for line in summaries_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception:
        all_summaries = []

    anomalies: dict[str, Any] = {"seasons": [], "metric_totals": {}}
    totals: dict[str, dict[str, float]] = {}
    for entry in all_summaries:
        year = entry.get("year")
        flags = entry.get("flags", [])
        if flags:
            anomalies["seasons"].append({"year": year, "flags": flags})
        for metric, delta in (entry.get("mlb_deltas") or {}).items():
            totals.setdefault(metric, {"max": 0.0, "sum": 0.0, "count": 0.0})
            totals[metric]["max"] = max(totals[metric]["max"], abs(delta))
            totals[metric]["sum"] += abs(delta)
            totals[metric]["count"] += 1

    for metric, info in totals.items():
        count = info["count"] or 1.0
        anomalies["metric_totals"][metric] = {
            "max_abs_delta": info["max"],
            "avg_abs_delta": info["sum"] / count,
        }

    (analysis_dir / "anomalies.json").write_text(
        json.dumps(anomalies, indent=2),
        encoding="utf-8",
    )

    print(f"Output written to {out_dir}")
    print(f"Season summaries: {summaries_path}")
    print(f"Anomalies report: {analysis_dir / 'anomalies.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
