"""Injured lists run once per played date, so batching can't change a league.

Release 3 live-path verification (2026-10-07): ``api.routers.season._simulate_n``
ran its post-day automations once per CALL. A player whose injured-list stint
ended on day 3 of a "Sim month" waited until the call ended (up to 29 days; the
rest of the season on "To Playoffs"), and the same league simmed one day at a
time, a week at a time or a month at a time played different games from the
first activation on (164-169 of 525 games differed in the live run).

The injured-list step (with the monthly call-up check and the FA negotiation
day) now runs after every played date, inside the day loop, and a CPU club's
depth chart is rebuilt before every date rather than when a call starts (a
call-up or a return changed it mid-call only in batched runs). These tests sim
one small league through the PRODUCT path -- ``_build_manager_and_simulator``
+ ``_simulate_n``, league files on disk, every call after a simulated fresh
process -- as one 10-day call, ten 1-day calls and a 7+3 split, with injured
players on a CPU club and on two owner clubs (one activates automatically,
one doesn't) whose stints end mid-run. Games, injured-list events and the
persisted league state must be identical.

Instrumentation, as in the live verification harness: the per-game seeds are
pinned to the date (the product draws them from an unseeded generator in each
new process) and the global RNG is reseeded per date before roster prep and
the injured-list step. The CPU trade proposal cycle is stubbed: it runs once
per call with its own unseeded generator, so it is batching-dependent by
design (documented in ``_simulate_n``).
"""
from __future__ import annotations

import csv
import json
import random
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

LEAGUE = "ilbatch"
SEED = 20261007
DAYS = 10
START = date(2026, 4, 1)
DIVISIONS = {
    "East": [("CityA", "Cats"), ("CityB", "Dogs"), ("CityC", "Owls"), ("CityD", "Elks")]
}
# Injury start dates: a 10-day stint ends on the 4th (CPU club), the 6th
# (owner club, auto-activate on; the league is off on the 5th) and the 3rd
# (owner club, auto-activate off).
INJURIES = {"cpu": "2026-03-25", "owner_auto": "2026-03-27", "owner_manual": "2026-03-24"}

_NEWS_STAMP = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")


def _fresh_process_state() -> None:
    """Drop every in-process cache a new process would not have."""

    from playbalance import game_runner, usage_store
    from utils import path_utils
    from utils.pitcher_recovery import PitcherRecoveryTracker
    from utils.player_loader import load_players_from_csv
    from utils.roster_loader import load_roster

    usage_store.clear_cache()
    game_runner._teams_by_id.cache_clear()
    PitcherRecoveryTracker._instance = None
    load_roster.cache_clear()
    load_players_from_csv.cache_clear()
    path_utils._DATA_DIR_CACHE.clear()


def _schedule(team_ids: list[str]) -> list[dict[str, str]]:
    a, b, c, d = team_ids
    pairings = [((a, b), (c, d)), ((a, c), (b, d)), ((a, d), (b, c))]
    rows: list[dict[str, str]] = []
    for day in range(DAYS):
        # Every 4th calendar day is a league off day.
        token = (START + timedelta(days=day + day // 4)).isoformat()
        for home, away in pairings[(day // 3) % 3]:
            if day % 2:
                home, away = away, home
            rows.append({"date": token, "home": home, "away": away})
    return rows


_HITTING = ("ch", "ph", "sp", "eye", "gf", "pl", "vl", "sc", "fa", "arm")


def _injure(data: Path, team_id: str, start: str, *, star_call_up: bool = False) -> str:
    """Put one of *team_id*'s active regulars on the 10-day list on *start*.

    ``star_call_up`` (a CPU club) first makes an AAA hitter a better player
    at the same position, so he is the one called up to cover and tops the
    position's depth chart while the regular is listed -- until the regular
    comes back and he goes down again. The CPU depth chart then changes in
    the middle of the run.
    """

    from services.injury_manager import place_on_injury_list
    from services.players_repository import save_players
    from utils.player_loader import load_players_from_csv
    from utils.roster_loader import load_roster, save_roster

    load_roster.cache_clear()
    load_players_from_csv.cache_clear()
    players = list(load_players_from_csv(str(data / "players.csv")))
    by_id = {p.player_id: p for p in players}
    roster = load_roster(team_id)
    pid = next(
        pid
        for pid in roster.act
        if str(getattr(by_id[pid], "primary_position", "")).upper() in {"SS", "CF", "2B"}
    )
    player = by_id[pid]
    star = None
    if star_call_up:
        star = next(
            p for p in roster.aaa if not getattr(by_id[p], "is_pitcher", False)
        )
        by_id[star].primary_position = player.primary_position
        by_id[star].other_positions = []
        for key in _HITTING:
            setattr(by_id[star], key, min(99, int(getattr(player, key, 50) or 50) + 15))
    player.injury_description = "Hamstring strain"
    player.injury_minimum_days = 10
    place_on_injury_list(
        player, roster, "il10", today=date.fromisoformat(start), players_by_id=by_id
    )
    if star is not None:
        assert star in roster.act, "the better AAA player covers for him"
    save_roster(team_id, roster)
    save_players(players, data / "players.csv")
    load_roster.cache_clear()
    load_players_from_csv.cache_clear()
    return pid


def _league_state(data: Path) -> dict[str, object]:
    """The league files every batching must leave identical."""

    files: dict[str, object] = {}
    for sub in ("rosters", "lineups", "depth_charts"):
        for path in sorted((data / sub).glob("*")):
            if path.is_file():
                files[f"{sub}/{path.name}"] = path.read_text(encoding="utf-8")
    for name in (
        "players.csv",
        "season_stats.json",
        "standings.json",
        "physics_usage.json",
        "pitcher_recovery.json",
        "injury_replacements.json",
        "il_returns_awaiting_room.json",
    ):
        path = data / name
        if path.exists():
            files[name] = path.read_text(encoding="utf-8")
    with (data / "schedule.csv").open(newline="", encoding="utf-8") as fh:
        files["schedule"] = [
            (r.get("date"), r.get("home"), r.get("away"), r.get("result"), r.get("played"))
            for r in csv.DictReader(fh)
        ]
    news = data / "news_feed.txt"
    if news.exists():
        files["news_feed.txt"] = [
            _NEWS_STAMP.sub("", line)
            for line in news.read_text(encoding="utf-8").splitlines()
        ]
    tx = data / "transactions.csv"
    if tx.exists():
        with tx.open(newline="", encoding="utf-8") as fh:
            files["transactions.csv"] = [
                {k: v for k, v in row.items() if k != "timestamp"}
                for row in csv.DictReader(fh)
            ]
    return files


def _run_league(tmp_path: Path, monkeypatch, calls: tuple[int, ...]) -> dict[str, object]:
    """Build the league under a fresh data root and sim it in *calls* calls."""

    import api.routers.season as season
    from playbalance import game_runner
    from playbalance.league_creator import create_league
    from playbalance.schedule_generator import save_schedule
    from playbalance.season_simulator import SeasonSimulator
    from utils import path_utils

    assert sum(calls) == DAYS
    root = tmp_path / "root"
    (root / "leagues").mkdir(parents=True)
    # Sentinel: nothing seeds the repo's player pool into this data root.
    (root / "players.csv").write_text("player_id\n", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    data = root / "leagues" / LEAGUE / "data"
    random.seed(SEED)
    create_league(str(data), DIVISIONS, "IL Batching League")
    with (data / "teams.csv").open(newline="", encoding="utf-8") as fh:
        team_ids = [row["team_id"] for row in csv.DictReader(fh)]
    owner_auto, owner_manual, cpu = team_ids[0], team_ids[1], team_ids[2]
    (data / "users.txt").write_text(
        "admin,pass,admin,\n"
        f"owner1,pw,owner,{owner_auto}\n"
        f"owner2,pw,owner,{owner_manual}\n",
        encoding="utf-8",
    )
    token = path_utils.set_request_league(LEAGUE)
    try:
        _fresh_process_state()
        assert Path(path_utils.get_data_dir()).resolve() == data.resolve()
        (data / "season_state.json").write_text(
            json.dumps({"phase": "REGULAR_SEASON"}), encoding="utf-8"
        )
        save_schedule(_schedule(team_ids), data / "schedule.csv")
        from services.team_play_settings import save_team_play_settings

        save_team_play_settings(owner_auto, {"il_auto_activate_15": True})
        save_team_play_settings(owner_manual, {"il_auto_activate_15": False})
        injured = {
            "cpu": _injure(data, cpu, INJURIES["cpu"], star_call_up=True),
            "owner_auto": _injure(data, owner_auto, INJURIES["owner_auto"]),
            "owner_manual": _injure(data, owner_manual, INJURIES["owner_manual"]),
        }

        # Instrumentation (see the module docstring).
        real_next_day = SeasonSimulator.simulate_next_day

        def _pinned_next_day(self):
            if self._index < len(self.dates):
                self._seed_rng = random.Random(f"{SEED}|{self.dates[self._index]}")
            return real_next_day(self)

        monkeypatch.setattr(SeasonSimulator, "simulate_next_day", _pinned_next_day)
        real_prep = season._prepare_rosters_for_date

        def _seeded_prep(simulator, day):
            random.seed(f"prep|{day}")
            return real_prep(simulator, day)

        monkeypatch.setattr(season, "_prepare_rosters_for_date", _seeded_prep)
        from services import dl_automation

        real_il = dl_automation.process_disabled_lists
        il_events: list[dict[str, object]] = []

        def _recording_il(today=None, **kwargs):
            random.seed(f"il|{today}")
            summary = real_il(today=today, **kwargs)
            il_events.append(
                {
                    "today": str(today),
                    "activated": sorted(summary.activated),
                    "awaiting_owner": sorted(summary.awaiting_owner),
                    "awaiting_room": sorted(summary.awaiting_room),
                }
            )
            return summary

        monkeypatch.setattr(dl_automation, "process_disabled_lists", _recording_il)
        monkeypatch.setattr(
            "services.cpu_trade_proposals.run_cpu_trade_proposal_cycle",
            lambda **kwargs: {"applied": False, "reason": "stubbed"},
        )

        played: list[str] = []
        for index, ndays in enumerate(calls):
            if index:
                _fresh_process_state()
            manager, simulator, draft_date = season._build_manager_and_simulator()
            result = season._simulate_n(
                manager, simulator, ndays, draft_date=draft_date, team_id=None
            )
            assert not result["errors"], result["errors"]
            played += result["played_dates"]
        assert len(played) == DAYS
        _fresh_process_state()
        state = _league_state(data)
    finally:
        path_utils.reset_request_league(token)
        path_utils._DATA_DIR_CACHE.clear()
    return {
        "played": played,
        "il_events": [e for e in il_events if e["activated"] or e["awaiting_owner"]],
        "state": state,
        "injured": injured,
        "teams": {"cpu": cpu, "owner_auto": owner_auto, "owner_manual": owner_manual},
    }


@pytest.fixture
def _serial_env(monkeypatch):
    from playbalance import game_runner, usage_store

    monkeypatch.delenv("PB_PARALLEL_GAMES", raising=False)
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    monkeypatch.delenv("PB_SIM_DATE", raising=False)
    monkeypatch.delenv("PB_SIM_YEAR", raising=False)
    monkeypatch.setattr(game_runner, "render_boxscore_html", lambda *a, **k: "")
    yield
    usage_store.clear_cache()


def _levels(state: dict, team_id: str) -> dict[str, list[str]]:
    levels: dict[str, list[str]] = {}
    for line in str(state[f"rosters/{team_id}.csv"]).splitlines():
        parts = line.split(",")
        if len(parts) >= 2:
            levels.setdefault(parts[1].strip().upper(), []).append(parts[0].strip())
    return levels


def test_one_day_and_weekly_calls_match_one_multi_day_call(tmp_path, monkeypatch, _serial_env):
    month = _run_league(tmp_path / "month", monkeypatch, (DAYS,))
    daily = _run_league(tmp_path / "daily", monkeypatch, (1,) * DAYS)
    weekly = _run_league(tmp_path / "weekly", monkeypatch, (7, 3))

    assert month["played"] == daily["played"] == weekly["played"]
    teams, injured = month["teams"], month["injured"]

    # The stints that end mid-run end on their date, in the 10-day call too:
    # the CPU club's regular (eligible the 4th) and the auto-activating owner
    # club's (eligible the 6th) come back for that day's games.
    activations = {
        event["today"]: event["activated"] for event in month["il_events"] if event["activated"]
    }
    assert any(f"({teams['cpu']})" in m for m in activations.get("2026-04-04", [])), activations
    assert any(
        f"({teams['owner_auto']})" in m for m in activations.get("2026-04-06", [])
    ), activations
    final = _levels(month["state"], teams["cpu"])
    assert injured["cpu"] in final.get("ACT", [])
    # A CPU club's depth chart is rebuilt before every date, in the 10-day
    # call too: back from the list, the regular tops his position again
    # (it was rebuilt only when a call started).
    chart = json.loads(month["state"][f"depth_charts/{teams['cpu']}.json"])
    assert any(ids[:1] == [injured["cpu"]] for ids in chart.values()), chart
    assert injured["owner_auto"] in _levels(month["state"], teams["owner_auto"]).get("ACT", [])
    # The owner who activates by hand keeps his player listed, every day.
    manual = _levels(month["state"], teams["owner_manual"])
    assert injured["owner_manual"] not in manual.get("ACT", [])
    assert any(
        f"({teams['owner_manual']})" in m
        for event in month["il_events"]
        for m in event["awaiting_owner"]
    )

    # Same games, same injured-list events, same league files -- however the
    # days were batched.
    assert daily["il_events"] == month["il_events"]
    assert weekly["il_events"] == month["il_events"]
    for key in month["state"]:
        assert daily["state"].get(key) == month["state"][key], f"daily: {key}"
        assert weekly["state"].get(key) == month["state"][key], f"weekly: {key}"
    assert daily["state"].keys() == month["state"].keys()
    assert weekly["state"].keys() == month["state"].keys()
