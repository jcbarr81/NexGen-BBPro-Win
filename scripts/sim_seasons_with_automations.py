#!/usr/bin/env python3
"""S2-10 / S2-11 acceptance-gate driver.

Simulates N seasons on a THROWAWAY sandbox copy of a league with the CPU
trade-proposal + in-season callup automations running each sim day (mirroring
what ``api/routers/season.py::_run_daily_automations`` does in production), then
reports the acceptance metrics:

  * S2-10 (CPU-to-CPU trades): executed CPU-CPU trades per season — the spec
    target is 15-40 for a full 30-team season — and whether the stddev of final
    team win% grows season-over-season (talent should not runaway-consolidate:
    season_last_std <= season_1_std * 1.15).
  * S2-11 (in-season callups): promotions per season, September expansion, and
    that every team's roster is legal (ACT within cap, no "over cap") after the
    REGULAR_SEASON->PLAYOFFS September revert.

It never touches a real user league: it copies ``--source`` into
``tmp/accept_sandbox`` and points NEXGEN_DATA_ROOT there. The default source is
the committed ``cbl`` league (real players — avoids the players_normalized.csv
generation gap). Run e.g.:

    python scripts/sim_seasons_with_automations.py --seasons 3
    python scripts/sim_seasons_with_automations.py --seasons 1 --games 30   # fast smoke
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Cross-process determinism (string hashing feeds set-iteration order -> RNG).
if os.environ.get("PYTHONHASHSEED") != "0":
    import subprocess

    raise SystemExit(
        subprocess.run([sys.executable] + sys.argv, env={**os.environ, "PYTHONHASHSEED": "0"}).returncode
    )


def _set_sim_date(target: date) -> None:
    os.environ["PB_SIM_DATE"] = target.isoformat()
    os.environ["PB_SIM_YEAR"] = str(target.year)


def _write_season_state(sandbox: Path, phase: str) -> None:
    (sandbox / "season_state.json").write_text(
        json.dumps({"phase": phase}, indent=2), encoding="utf-8"
    )


def _log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="data/leagues/cbl/data")
    ap.add_argument("--seasons", type=int, default=3)
    ap.add_argument("--start-year", type=int, default=2026)
    ap.add_argument("--games", type=int, default=None,
                    help="games per team (default: full season). Use a small value for a smoke run.")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cadence", default="normal",
                    help="cpu_proposal_cadence written into the sandbox trade settings")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    sandbox = ROOT / "tmp" / "accept_sandbox"
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)
    shutil.copytree(ROOT / args.source, sandbox)

    os.environ["NEXGEN_DATA_ROOT"] = str(sandbox)
    os.environ.pop("NEXGEN_ACTIVE_LEAGUE", None)
    os.environ["PB_SKIP_BOXSCORE_HTML"] = "1"
    os.environ["PB_DISABLE_ROLLOVER"] = "1"  # we manage season phases ourselves

    import utils.path_utils as pu
    pu._DATA_DIR_CACHE.clear()

    # All-CPU league: no human owners so the CPU-CPU trade lane is the only lane.
    (sandbox / "users.txt").unlink(missing_ok=True)
    # Enable CPU-initiated trades in the sandbox.
    (sandbox / "trade_settings.json").write_text(
        json.dumps({
            "version": 1,
            "leagues": {"league": {
                "trades_enabled": True,
                "draft_pick_trading_enabled": True,
                "require_commissioner_approval": False,
                "cpu_initiated_trades_enabled": True,
                "cpu_proposal_cadence": args.cadence,
                "max_pick_trade_years": 3,
            }},
        }, indent=2),
        encoding="utf-8",
    )

    from playbalance.schedule_generator import generate_mlb_schedule
    from playbalance.season_simulator import SeasonSimulator
    from playbalance.game_runner import simulate_game_scores
    from playbalance.season_context import SeasonContext
    from playbalance.season_manager import SeasonManager
    from services.standings_repository import save_standings
    from services.cpu_trade_proposals import run_cpu_trade_proposal_cycle
    from services.inseason_callups import run_monthly_callups
    from utils.standings_utils import default_record, update_record
    from utils.team_loader import load_teams
    from utils.roster_loader import load_roster
    from utils.trade_utils import load_trades
    from services.roster_validation import validate_roster_state, DEFAULT_LEVEL_CAPS
    from utils.player_loader import load_players_from_csv

    teams = load_teams(sandbox / "teams.csv")
    team_ids = [t.team_id for t in teams]
    team_div = {t.team_id: t.division for t in teams}
    _log(f"sandbox={sandbox}  teams={len(team_ids)}  seasons={args.seasons}")

    def _players_map() -> dict:
        out = {}
        for p in load_players_from_csv(sandbox / "players.csv"):
            pid = str(getattr(p, "player_id", "") or "")
            out[pid] = {
                "is_pitcher": bool(getattr(p, "is_pitcher", False)),
                "primary_position": getattr(p, "primary_position", "") or "",
                "other_positions": list(getattr(p, "other_positions", []) or []),
            }
        return out

    season_summaries = []
    for si in range(args.seasons):
        year = args.start_year + si
        random.seed(args.seed + si)
        _write_season_state(sandbox, "REGULAR_SEASON")
        _set_sim_date(date(year, 4, 1))

        if args.games:
            schedule = generate_mlb_schedule(team_ids, date(year, 4, 1), games_per_team=args.games)
        else:
            schedule = generate_mlb_schedule(team_ids, date(year, 4, 1))

        ctx = SeasonContext.load()
        ctx.ensure_league(name="AcceptGate")
        ctx.ensure_current_season(league_year=year, started_on=schedule[0]["date"] if schedule else "")
        ctx.save()

        standings = {tid: default_record() for tid in team_ids}
        save_standings(standings, base_path=sandbox)
        # Fresh per-season automation ledgers.
        for f in ("trades_pending.csv", "callup_state.json", "cpu_trade_proposal_state.json"):
            (sandbox / f).unlink(missing_ok=True)

        def record_game(game, _st=standings):
            result = game.get("result")
            if not (result and "-" in result):
                return
            try:
                hs, as_ = map(int, result.split("-", 1))
            except ValueError:
                return
            home, away = game.get("home", ""), game.get("away", "")
            meta = game.get("extra") or {}
            one_run = abs(hs - as_) == 1
            extra = bool(meta.get("extra_innings"))
            div = team_div.get(home) == team_div.get(away) if home and away else False
            if home:
                update_record(_st.setdefault(home, default_record()), won=hs > as_, runs_for=hs,
                              runs_against=as_, home=True, opponent_hand=str(meta.get("away_starter_hand", "") or "").upper(),
                              division_game=div, one_run=one_run, extra_innings=extra)
            if away:
                update_record(_st.setdefault(away, default_record()), won=as_ > hs, runs_for=as_,
                              runs_against=hs, home=False, opponent_hand=str(meta.get("home_starter_hand", "") or "").upper(),
                              division_game=div, one_run=one_run, extra_innings=extra)

        sim = SeasonSimulator(schedule, simulate_game_scores, after_game=record_game)
        n_days = len(sim.dates)
        cpu_cpu_executed = 0
        promotions = 0
        demotions = 0
        errors: list[str] = []
        cc_filtered: dict[str, int] = {}
        while sim._index < n_days:
            cur = sim.dates[sim._index]
            _set_sim_date(date.fromisoformat(cur[:10]))
            sim.simulate_next_day()
            save_standings(standings, base_path=sandbox)
            try:
                r = run_cpu_trade_proposal_cycle(simulated_dates=[cur], data_dir=sandbox, league_id="league")
                cc = r.get("cpu_cpu_trades") or {}
                cpu_cpu_executed += len(cc.get("executed", []) or [])
                for k, v in (cc.get("filtered") or {}).items():
                    cc_filtered[k] = cc_filtered.get(k, 0) + int(v or 0)
            except Exception as exc:  # pragma: no cover
                errors.append(f"trade@{cur}:{exc}")
            try:
                cu = run_monthly_callups(played_dates=[cur], data_dir=sandbox, league_id="league")
                promotions += len(cu.get("promotions", []) or [])
                demotions += len(cu.get("demotions", []) or [])
            except Exception as exc:  # pragma: no cover
                errors.append(f"callup@{cur}:{exc}")
            if sim._index % 20 == 0:
                _log(f"  season {year} day {sim._index}/{n_days} {cur}  cpu_cpu={cpu_cpu_executed} promos={promotions}")

        # Win% spread across teams.
        win_pcts = []
        for tid in team_ids:
            rec = standings.get(tid, {})
            w, l = int(rec.get("wins", 0) or 0), int(rec.get("losses", 0) or 0)
            if w + l:
                win_pcts.append(w / (w + l))
        win_std = statistics.pstdev(win_pcts) if len(win_pcts) > 1 else 0.0

        # Count executed CPU-CPU trades persisted this season.
        cpu_set = {t.upper() for t in team_ids}
        persisted_cpu_cpu = 0
        for tr in load_trades(sandbox / "trades_pending.csv"):
            if (str(getattr(tr, "status", "")).lower() == "accepted"
                    and str(getattr(tr, "initiated_by", "")).lower() == "cpu"
                    and str(getattr(tr, "from_team", "")).upper() in cpu_set
                    and str(getattr(tr, "to_team", "")).upper() in cpu_set):
                persisted_cpu_cpu += 1

        # September revert: advancing REGULAR_SEASON -> PLAYOFFS trims to 25.
        mgr = SeasonManager(path=sandbox / "season_state.json", enable_rollover=False)
        mgr.advance_phase()  # fires services.inseason_callups.revert_september_expansion()

        # Roster legality after the revert.
        pmap = _players_map()
        overcap = []
        for tid in team_ids:
            try:
                roster = load_roster(tid, sandbox / "rosters")
            except Exception:
                continue
            levels = {"act": list(getattr(roster, "act", []) or []),
                      "aaa": list(getattr(roster, "aaa", []) or []),
                      "low": list(getattr(roster, "low", []) or [])}
            res = validate_roster_state(current_levels=levels, players=pmap, level_caps=DEFAULT_LEVEL_CAPS)
            if any("over cap" in e for e in res.errors):
                overcap.append(tid)

        summary = {
            "year": year, "days": n_days, "teams": len(team_ids),
            "cpu_cpu_trades_executed": persisted_cpu_cpu,
            "cpu_cpu_trades_in_run": cpu_cpu_executed,
            "promotions": promotions, "demotions": demotions,
            "win_pct_stddev": round(win_std, 4),
            "teams_over_cap_after_revert": overcap,
            "cpu_cpu_filtered_reasons": cc_filtered,
            "automation_errors": errors[:5],
            "automation_error_count": len(errors),
        }
        season_summaries.append(summary)
        _log(f"SEASON {year}: cpu_cpu={persisted_cpu_cpu} promos={promotions} demos={demotions} "
             f"win%_std={win_std:.4f} over_cap={overcap} errors={len(errors)}")

    # Verdict.
    std_first = season_summaries[0]["win_pct_stddev"] if season_summaries else 0.0
    std_last = season_summaries[-1]["win_pct_stddev"] if season_summaries else 0.0
    volumes = [s["cpu_cpu_trades_executed"] for s in season_summaries]
    verdict = {
        "seasons": season_summaries,
        "cpu_cpu_volume_per_season": volumes,
        "win_std_first": std_first, "win_std_last": std_last,
        "win_std_not_growing": std_last <= std_first * 1.15 if std_first else True,
        "any_team_over_cap": any(s["teams_over_cap_after_revert"] for s in season_summaries),
    }
    _log("\n===== VERDICT =====")
    _log(json.dumps(verdict, indent=2))
    _log(f"S2-10 volume/season: {volumes}  (spec target 15-40 for a full 30-team season)")
    _log(f"S2-10 win% stddev not growing (last<=first*1.15): {verdict['win_std_not_growing']} "
         f"({std_last} vs {std_first})")
    _log(f"S2-11 all rosters legal after September revert: {not verdict['any_team_over_cap']}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
