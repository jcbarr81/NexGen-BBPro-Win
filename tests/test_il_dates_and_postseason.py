"""Injured-list steps act on the league date they are run for.

Release 3 live-path verification (2026-10-07):

* nobody came off an injured list in the postseason -- the playoff sim had no
  injured-list step at all;
* the step itself re-checked eligibility, and read the roster caps, against
  the date in the league files, which inside a multi-day sim call is still
  the call's first day and all postseason is the last regular-season date:
  a player due on the date asked for stayed listed, and an owner's returner
  in early September met the 26-man cap instead of September's 28;
* call-ups made in the postseason were logged on the last regular-season
  date.

Each test runs in a throwaway league (``NEXGEN_DATA_ROOT`` +
``set_request_league``, as the server resolves a league).
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import playbalance.playoffs as pf
from playbalance.playoffs import (
    Matchup,
    PlayoffBracket,
    PlayoffTeam,
    Round,
    SeriesConfig,
    simulate_next_game,
)

LEAGUE = "ildates"
DIVISIONS = {"East": [("CityA", "Cats"), ("CityB", "Dogs")]}


@pytest.fixture
def league(tmp_path, monkeypatch):
    from playbalance.league_creator import create_league
    from utils import path_utils
    from utils.player_loader import load_players_from_csv
    from utils.roster_loader import load_roster

    root = tmp_path / "root"
    (root / "leagues").mkdir(parents=True)
    (root / "players.csv").write_text("player_id\n", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    for key in ("NEXGEN_ACTIVE_LEAGUE", "PB_SIM_DATE", "PB_SIM_YEAR"):
        monkeypatch.delenv(key, raising=False)
    data = root / "leagues" / LEAGUE / "data"
    random.seed(20261007)
    create_league(str(data), DIVISIONS, "Dates League")
    with (data / "teams.csv").open(newline="", encoding="utf-8") as fh:
        owner, cpu = [row["team_id"] for row in csv.DictReader(fh)]
    (data / "users.txt").write_text(
        f"admin,pass,admin,\nowner1,pw,owner,{owner}\n", encoding="utf-8"
    )
    monkeypatch.setattr("utils.news_logger.log_news_event", lambda *a, **k: None)
    token = path_utils.set_request_league(LEAGUE)
    path_utils._DATA_DIR_CACHE.clear()
    load_roster.cache_clear()
    load_players_from_csv.cache_clear()
    try:
        assert Path(path_utils.get_data_dir()).resolve() == data.resolve()
        yield SimpleNamespace(data=data, owner=owner, cpu=cpu)
    finally:
        load_roster.cache_clear()
        load_players_from_csv.cache_clear()
        path_utils.reset_request_league(token)
        path_utils._DATA_DIR_CACHE.clear()


def _league_files_on(data: Path, dates: list[str], *, played: bool, phase: str) -> None:
    """Schedule + phase that put the league files' sim date on ``dates``."""

    with (data / "schedule.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "home", "away", "result", "played"])
        writer.writeheader()
        for day in dates:
            writer.writerow(
                {
                    "date": day,
                    "home": "X",
                    "away": "Y",
                    "result": "1-0" if played else "",
                    "played": "1" if played else "",
                }
            )
    (data / "season_state.json").write_text(json.dumps({"phase": phase}), encoding="utf-8")


def _players(data: Path):
    from utils.player_loader import load_players_from_csv

    load_players_from_csv.cache_clear()
    players = list(load_players_from_csv(str(data / "players.csv")))
    return players, {p.player_id: p for p in players}


def _injure(league, team_id: str, start: str, *, cpu_owned: bool) -> str:
    """Put an active regular of *team_id* on the 10-day list on *start*."""

    from services.injury_manager import place_on_injury_list
    from services.players_repository import save_players
    from utils.roster_loader import load_roster, save_roster

    players, by_id = _players(league.data)
    load_roster.cache_clear()
    roster = load_roster(team_id)
    pid = next(
        pid
        for pid in roster.act
        if str(getattr(by_id[pid], "primary_position", "")).upper() in {"SS", "CF", "2B"}
    )
    by_id[pid].injury_description = "Hamstring strain"
    by_id[pid].injury_minimum_days = 10
    place_on_injury_list(
        by_id[pid],
        roster,
        "il10",
        today=date.fromisoformat(start),
        players_by_id=by_id,
        cpu_owned=cpu_owned,
    )
    save_roster(team_id, roster)
    save_players(players, league.data / "players.csv")
    load_roster.cache_clear()
    return pid


def _levels(team_id: str) -> dict[str, list[str]]:
    from utils.roster_loader import load_roster

    load_roster.cache_clear()
    roster = load_roster(team_id)
    return {lvl: list(getattr(roster, lvl)) for lvl in ("act", "aaa", "low", "dl", "ir")}


def _transactions(data: Path) -> list[dict[str, str]]:
    path = data / "transactions.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --- the injured-list step acts on its own date -------------------------------


def test_a_stint_over_on_the_date_asked_for_ends_though_the_files_lag(league):
    """Inside a multi-day call the league files still hold the call's first
    day: activation must not re-check eligibility against that date."""
    from services.dl_automation import process_disabled_lists

    pid = _injure(league, league.cpu, "2026-03-31", cpu_owned=True)  # due 04-10
    _league_files_on(
        league.data, [f"2026-04-{d:02d}" for d in range(1, 13)],
        played=False, phase="REGULAR_SEASON",
    )
    from utils.sim_date import get_current_sim_date

    assert get_current_sim_date() == "2026-04-01"

    summary = process_disabled_lists(today="2026-04-10", auto_activate=True)

    assert pid in _levels(league.cpu)["act"], summary
    assert any(f"({league.cpu})" in line for line in summary.activated)
    assert not summary.alerts


def test_an_owner_returner_gets_the_september_cap_of_the_date_asked_for(league):
    """Sept 2 with the league files still on Aug 31: the owner's returner
    joins a 26-man active roster (the September cap is 28) and nobody else is
    moved."""
    from services.dl_automation import process_disabled_lists
    from services.team_play_settings import save_team_play_settings
    from utils.roster_loader import load_roster, save_roster

    pid = _injure(league, league.owner, "2026-08-10", cpu_owned=False)  # due 08-20
    save_team_play_settings(league.owner, {"il_auto_activate_15": True})
    # The owner filled the open spot himself: 26 active again.
    _, by_id = _players(league.data)
    load_roster.cache_clear()
    roster = load_roster(league.owner)
    filler = next(p for p in roster.aaa if not getattr(by_id[p], "is_pitcher", False))
    roster.aaa.remove(filler)
    roster.act.append(filler)
    save_roster(league.owner, roster)
    assert len(_levels(league.owner)["act"]) == 26
    _league_files_on(
        league.data, ["2026-08-31", "2026-09-02"], played=False, phase="REGULAR_SEASON"
    )

    process_disabled_lists(today="2026-09-02", auto_activate=True)

    levels = _levels(league.owner)
    assert pid in levels["act"]
    assert filler in levels["act"]
    assert len(levels["act"]) == 27


# --- the postseason -------------------------------------------------------------


def _ws() -> PlayoffBracket:
    matchup = Matchup(
        high=PlayoffTeam(team_id="H", seed=1, league="L", wins=90),
        low=PlayoffTeam(team_id="W", seed=2, league="L", wins=80),
        config=SeriesConfig(length=7, pattern=[2, 3, 2]),
    )
    return PlayoffBracket(year=2025, rounds=[Round(name="WS", matchups=[matchup])])


@pytest.fixture
def season_end(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "get_data_dir", lambda: tmp_path)
    (tmp_path / "schedule.csv").write_text(
        "date,home,away\n2025-04-01,A1,N1\n2025-09-28,A2,N2\n", encoding="utf-8"
    )


def test_a_playoff_day_processes_the_injured_lists_on_its_date(season_end, monkeypatch):
    import playbalance.game_runner as gr
    import services.roster_fill as roster_fill
    from services import dl_automation, transaction_log

    order: list[tuple] = []
    monkeypatch.setattr(
        dl_automation,
        "process_disabled_lists",
        lambda **kwargs: order.append(("il", kwargs.get("today"), kwargs.get("auto_activate"))),
    )
    # The playoff call-up step, and the date a transaction it logs would get.
    monkeypatch.setattr(
        roster_fill,
        "prepare_teams_for_game",
        lambda teams: order.append(("prep", transaction_log.get_current_sim_date())),
    )
    # The league files hold the last regular-season date.
    monkeypatch.setattr("utils.file_cache.cached_read", lambda *a, **k: "2025-09-28")

    def fake_scores(home_id, away_id, **kwargs):
        order.append(("game", kwargs.get("game_date")))
        return (2, 1, "<html/>", {})

    monkeypatch.setattr(gr, "simulate_game_scores", fake_scores)
    simulate_next_game(_ws(), persist_cb=lambda b: None)

    assert order == [
        ("il", "2025-09-30", True),
        ("prep", "2025-09-30"),
        ("game", "2025-09-30"),
    ]


def test_a_stubbed_playoff_sim_runs_no_injured_list_step(season_end, monkeypatch):
    from services import dl_automation

    calls = []
    monkeypatch.setattr(
        dl_automation, "process_disabled_lists", lambda **kwargs: calls.append(kwargs)
    )
    simulate_next_game(
        _ws(),
        simulate_game=lambda home, away, seed=None: (1, 0, "<html/>", {}),
        persist_cb=lambda b: None,
    )
    assert calls == []


def test_a_postseason_injury_call_up_is_logged_on_the_game_date(league):
    """The in-game injury call-up (a CPU club calls up a like-for-like
    replacement) is logged on the date of the game, not on the date the
    league files hold -- the last regular-season date, all postseason."""
    _league_files_on(league.data, ["2026-09-27", "2026-09-28"], played=True, phase="PLAYOFFS")
    from utils.sim_date import get_current_sim_date

    assert get_current_sim_date() == "2026-09-28"

    before = len(_transactions(league.data))
    pid = _injure(league, league.cpu, "2026-10-02", cpu_owned=True)

    call_ups = [
        row
        for row in _transactions(league.data)[before:]
        if row["details"].startswith("Called up to cover the injured")
    ]
    assert call_ups, "the CPU club calls up a replacement"
    assert {row["season_date"] for row in call_ups} == {"2026-10-02"}
    assert pid in _levels(league.cpu)["dl"]
