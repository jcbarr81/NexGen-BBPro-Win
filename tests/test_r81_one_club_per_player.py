"""8.1.1 hotfix: a player belongs to one club; parallel days play exactly.

1. A player on a club's injured list was listed as a free agent (free agency
   counted only ACT / AAA / LOW), signed by another club -- his contract
   overwritten -- and, once healthy, activated by both clubs. Every level of
   a club's roster file (and a contract with a club) now makes him that
   club's: the free-agent list, the sign / offer / evaluate endpoints, CPU
   signings and negotiations leave him alone, and ``save_roster`` refuses a
   write that would put him on a second club.
2. With ``PB_PARALLEL_GAMES`` a player in two of a day's games (two clubs'
   active rosters) kept only one game's line: every worker starts from the
   day's opening state and journals cumulative lines. Such a day now plays
   serially, and box-score positions no longer depend on process history.
"""
from __future__ import annotations

import ast
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from models.roster import Roster
from utils.roster_loader import load_roster, save_roster, save_rosters
from utils.roster_ownership import (
    DoubleRosterError,
    check_roster_writes,
    club_owned_players,
    owning_club,
)

BASE_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_placeholder_arms(monkeypatch):
    """These toy rosters have no pitchers; loading one would pad it with
    placeholder arms from the repo's sample league."""

    import utils.roster_loader as rl

    monkeypatch.setattr(rl, "_ensure_pitcher_depth", lambda roster, **k: False)
    rl.load_roster.cache_clear()
    yield
    rl.load_roster.cache_clear()

_TEAMS = (
    "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
    "AAA,CPU Club,City,AAA,East,Park,#112233,#445566,cpu\n"
    "BBB,Other Club,Town,BBB,West,Park,#221133,#665544,cpu\n"
)
_PLAYER_HEADER = (
    "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,"
    "other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
)


def _player_row(pid: str, quality: int = 60) -> str:
    return (
        f"{pid},First,{pid},2000-01-01,72,190,R,1B,,50,{quality},{quality},50,55,"
        f"55,55,55,{quality},56,0\n"
    )


def _league(tmp_path: Path) -> Path:
    """Two CPU clubs. BBB holds a player on every level; P900 is free.

    P400 is BBB's injured player with two contract years left (the case the
    rehearsal found: Demarcus Thissen on SEA's 15-day list).
    """

    data = tmp_path / "league"
    (data / "rosters").mkdir(parents=True)
    (data / "teams.csv").write_text(_TEAMS, encoding="utf-8")
    ids = ["P100", "P200", "P300", "P400", "P500", "P600", "P700", "P800", "P900"]
    (data / "players.csv").write_text(
        _PLAYER_HEADER + "".join(_player_row(pid, 70 if pid == "P400" else 55) for pid in ids),
        encoding="utf-8",
    )
    (data / "rosters" / "AAA.csv").write_text("", encoding="utf-8")
    (data / "rosters" / "BBB.csv").write_text(
        "P100,ACT\nP200,AAA\nP300,LOW\nP400,DL15\nP500,IR\nP600,DL45\nP700,DL\n",
        encoding="utf-8",
    )
    (data / "contracts.json").write_text(
        json.dumps({"version": 1, "players": {
            "P400": {"team_id": "BBB", "years_left": 2, "annual_salary": 9_000_000},
            # Under contract, on no roster file: still BBB's.
            "P800": {"team_id": "BBB", "years_left": 1, "annual_salary": 1_000_000},
        }}),
        encoding="utf-8",
    )
    return data


# ---------------------------------------------------------------------------
# Who owns a player
# ---------------------------------------------------------------------------
def test_every_roster_level_and_a_contract_make_a_player_a_clubs(tmp_path):
    data = _league(tmp_path)
    owned = club_owned_players(data)
    assert set(owned) == {"P100", "P200", "P300", "P400", "P500", "P600", "P700", "P800"}
    assert owned["P400"] == ("BBB", "DL15")
    assert owned["P800"] == ("BBB", "CONTRACT")
    assert owning_club("P900", data) is None
    # A staff file only labels roles: it never makes a player a club's.
    (data / "rosters" / "AAA_pitching.csv").write_text("P900,SP1\n", encoding="utf-8")
    assert owning_club("P900", data) is None


def test_free_agent_list_leaves_out_injured_and_contracted_players(tmp_path):
    from services.free_agency import list_unsigned_players_from_files

    data = _league(tmp_path)
    free = [p.player_id for p in list_unsigned_players_from_files(data_dir=data)]
    assert free == ["P900"]


# ---------------------------------------------------------------------------
# Signing paths
# ---------------------------------------------------------------------------
def test_cpu_free_agency_never_signs_another_clubs_injured_player(tmp_path):
    from services.finance_settings import ensure_financial_defaults, update_financial_settings
    from services.free_agency import run_cpu_free_agency_round

    data = _league(tmp_path)
    ensure_financial_defaults(data_dir=data, league_id="test")
    update_financial_settings(
        preset="standard", path=data / "league_financial_settings.json", league_id="test"
    )
    (data / "standings.json").write_text(
        json.dumps({"AAA": {"wins": 86, "losses": 76}, "BBB": {"wins": 74, "losses": 88}}),
        encoding="utf-8",
    )
    summary = run_cpu_free_agency_round(
        data_dir=data, league_id="test", max_signings=10, rng=random.Random(7)
    )
    signed = {s["player_id"] for s in summary["signings"]}
    assert signed <= {"P900"}
    assert "P400" not in (data / "rosters" / "AAA.csv").read_text(encoding="utf-8")
    contracts = json.loads((data / "contracts.json").read_text(encoding="utf-8"))["players"]
    assert contracts["P400"]["team_id"] == "BBB"
    assert contracts["P400"]["annual_salary"] == 9_000_000


def test_cpu_roster_placement_refuses_an_owned_player(tmp_path):
    from services.free_agency import _add_player_to_team_roster

    data = _league(tmp_path)
    for pid in ("P100", "P400", "P500", "P800"):
        assert _add_player_to_team_roster("AAA", pid, data_dir=data) is None
    assert _add_player_to_team_roster("AAA", "P900", data_dir=data) == "ACT"


def _point_services_at(monkeypatch, data: Path) -> None:
    import services.free_agency as fa

    roster_dir = data / "rosters"
    monkeypatch.setattr(fa, "get_data_dir", lambda: data)
    monkeypatch.setattr(fa, "load_roster", lambda tid, *a, **k: load_roster(tid, roster_dir=roster_dir))
    monkeypatch.setattr(
        fa, "save_roster", lambda tid, r, *a, **k: save_roster(tid, r, roster_dir=roster_dir)
    )
    monkeypatch.setattr(fa, "sign_free_agent_contract", lambda *a, **k: {})
    monkeypatch.setattr(fa, "record_transaction", lambda **k: None)


def test_negotiation_signing_refuses_another_clubs_injured_player(tmp_path, monkeypatch):
    import services.free_agency as fa

    data = _league(tmp_path)
    _point_services_at(monkeypatch, data)
    assert fa.finalize_fa_signing("AAA", "P400", level="ACT", cpu_placement=False) is False
    assert "P400" not in (data / "rosters" / "AAA.csv").read_text(encoding="utf-8")
    assert fa.finalize_fa_signing("AAA", "P900", level="ACT", cpu_placement=False) is True


def test_open_negotiation_on_an_owned_player_closes_without_a_deal(tmp_path):
    import services.fa_negotiations as neg

    data = _league(tmp_path)
    neg.save_negotiations({"negotiations": {
        "P400": {"player_id": "P400", "status": "open", "deadline_date": "2026-01-01",
                 "offers": [{"team_id": "AAA", "annual_salary": 9_000_000, "years": 2}]},
    }}, data_dir=data)
    calls = []
    summary = neg.process_negotiations(
        "2026-06-01", data_dir=data, sign_fn=lambda **k: calls.append(k) or True
    )
    assert calls == []
    assert summary["not_a_free_agent"] == ["P400"]
    state = neg.load_negotiations(data_dir=data)["negotiations"]["P400"]
    assert state["status"] == "resolved"
    assert state["resolution"]["outcome"] == "not_a_free_agent"
    assert state["resolution"]["team_id"] == "BBB"


def _point_router_at(monkeypatch, data: Path):
    import api.routers.free_agency as router

    _point_services_at(monkeypatch, data)
    roster_dir = data / "rosters"
    monkeypatch.setattr(router, "_phase_gate_for_fa", lambda: None)
    monkeypatch.setattr(router, "load_roster", lambda tid: load_roster(tid, roster_dir=roster_dir))
    monkeypatch.setattr(router, "save_roster", lambda tid, r: save_roster(tid, r, roster_dir=roster_dir))
    monkeypatch.setattr(router, "_find_player", lambda pid: SimpleNamespace(player_id=pid))
    monkeypatch.setattr(router, "sign_free_agent_contract", lambda *a, **k: {})
    monkeypatch.setattr(router, "record_transaction", lambda **k: None)
    monkeypatch.setattr(
        router, "evaluate_free_agent_signing",
        lambda *a, **k: SimpleNamespace(allowed=True, warning=False, violations=[], mode="off", level="off"),
    )
    return router


@pytest.mark.parametrize("pid,level", [("P100", "ACT"), ("P400", "DL15"), ("P500", "IR"), ("P800", "CONTRACT")])
def test_sign_endpoint_refuses_a_player_another_club_owns(tmp_path, monkeypatch, pid, level):
    data = _league(tmp_path)
    router = _point_router_at(monkeypatch, data)
    admin = {"r": "admin", "t": ""}
    # Even the commissioner's force (which skips the negotiation) is refused.
    with pytest.raises(HTTPException) as exc:
        router.sign_free_agent("AAA", {"player_id": pid, "level": "ACT", "force": True}, admin)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "not_a_free_agent"
    assert exc.value.detail["team_id"] == "BBB" and exc.value.detail["level"] == level
    assert "BBB" in exc.value.detail["message"]
    assert pid not in (data / "rosters" / "AAA.csv").read_text(encoding="utf-8")


def test_sign_endpoint_still_signs_a_free_agent(tmp_path, monkeypatch):
    data = _league(tmp_path)
    router = _point_router_at(monkeypatch, data)
    out = router.sign_free_agent(
        "AAA", {"player_id": "P900", "level": "ACT", "force": True}, {"r": "admin", "t": ""}
    )
    assert out["signed"] is True
    assert "P900,ACT" in (data / "rosters" / "AAA.csv").read_text(encoding="utf-8")


def test_offer_and_evaluate_endpoints_refuse_an_owned_player(tmp_path, monkeypatch):
    data = _league(tmp_path)
    router = _point_router_at(monkeypatch, data)
    owner = {"r": "owner", "t": "AAA"}
    with pytest.raises(HTTPException) as exc:
        router.submit_fa_offer("P400", {"team_id": "AAA", "years": 1, "annual_salary": 1}, owner)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "not_a_free_agent"
    with pytest.raises(HTTPException) as exc:
        router.evaluate_fa_offer("P400", {"years": 1, "annual_salary": 1}, owner)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# The write guard
# ---------------------------------------------------------------------------
def test_save_roster_refuses_a_player_on_another_clubs_injured_list(tmp_path):
    data = _league(tmp_path)
    roster_dir = data / "rosters"
    roster = load_roster("AAA", roster_dir=roster_dir)
    roster.act.append("P400")
    with pytest.raises(DoubleRosterError) as exc:
        save_roster("AAA", roster, roster_dir=roster_dir)
    assert isinstance(exc.value, ValueError)
    assert exc.value.conflicts == [("P400", "BBB", "DL15")]
    assert "P400 is already on BBB's roster (DL15)" in str(exc.value)
    # Nothing written, and the cached copy the caller edited is dropped.
    assert (roster_dir / "AAA.csv").read_text(encoding="utf-8") == ""
    assert "P400" not in load_roster("AAA", roster_dir=roster_dir).act


def test_save_roster_keeps_working_for_a_club_already_holding_a_shared_player(tmp_path):
    """A league written by an older build can hold a player on two clubs;
    both clubs must still save (the sim must not stop) -- the diagnostic
    script lists those for the owner."""

    data = _league(tmp_path)
    roster_dir = data / "rosters"
    (roster_dir / "AAA.csv").write_text("P400,ACT\n", encoding="utf-8")
    load_roster.cache_clear()
    aaa = load_roster("AAA", roster_dir=roster_dir)
    aaa.aaa.append("P900")
    save_roster("AAA", aaa, roster_dir=roster_dir)
    bbb = load_roster("BBB", roster_dir=roster_dir)
    bbb.dl.remove("P400")
    bbb.act.append("P400")  # activated on the old club: no new club for him
    save_roster("BBB", bbb, roster_dir=roster_dir)


def test_a_swap_saves_both_clubs_together(tmp_path):
    roster_dir = tmp_path / "rosters"
    roster_dir.mkdir()
    save_roster("AAA", Roster("AAA", act=["a1", "a2"]), roster_dir=roster_dir)
    save_roster("BBB", Roster("BBB", act=["b1", "b2"]), roster_dir=roster_dir)
    aaa = Roster("AAA", act=["b1", "a2"])
    bbb = Roster("BBB", act=["a1", "b2"])
    # One club at a time, the first save is a second club for b1.
    with pytest.raises(DoubleRosterError):
        check_roster_writes({"AAA": aaa.act}, roster_dir)
    save_rosters([("AAA", aaa), ("BBB", bbb)], roster_dir=roster_dir)
    assert (roster_dir / "AAA.csv").read_text(encoding="utf-8").split() == ["b1,ACT", "a2,ACT"]
    assert (roster_dir / "BBB.csv").read_text(encoding="utf-8").split() == ["a1,ACT", "b2,ACT"]


def test_trade_commit_swaps_players_and_refuses_a_third_clubs_player(tmp_path, monkeypatch):
    from models.trade import Trade
    from services.trade_execution import commit_trade

    roster_dir = tmp_path / "rosters"
    roster_dir.mkdir()
    # x1 is on AAA and on CCC's injured list: a double an older build wrote
    # (the guard would refuse to write it now).
    (roster_dir / "AAA.csv").write_text("a1,ACT\nx1,ACT\n", encoding="utf-8")
    (roster_dir / "BBB.csv").write_text("b1,ACT\n", encoding="utf-8")
    (roster_dir / "CCC.csv").write_text("x1,DL15\n", encoding="utf-8")
    load_roster.cache_clear()
    monkeypatch.setattr("services.trade_execution.record_transaction", lambda **k: None)
    monkeypatch.setattr("services.trade_execution.claim_players", lambda *a, **k: None)
    commit_trade(Trade("t1", "AAA", "BBB", ["a1"], ["b1"]), data_dir=tmp_path)
    assert (roster_dir / "AAA.csv").read_text(encoding="utf-8").split() == ["x1,ACT", "b1,ACT"]
    assert (roster_dir / "BBB.csv").read_text(encoding="utf-8").split() == ["a1,ACT"]
    # Trading x1 to BBB would leave him on CCC's list too: refused, unwritten.
    with pytest.raises(DoubleRosterError):
        commit_trade(Trade("t2", "AAA", "BBB", ["x1"], []), data_dir=tmp_path)
    assert (roster_dir / "BBB.csv").read_text(encoding="utf-8").split() == ["a1,ACT"]
    assert "x1" in (roster_dir / "AAA.csv").read_text(encoding="utf-8")


def test_draft_assignment_refuses_a_player_another_club_holds(tmp_path, monkeypatch):
    import services.draft_assignment as da

    roster_dir = tmp_path / "rosters"
    roster_dir.mkdir()
    save_roster("AAA", Roster("AAA", act=["a1"]), roster_dir=roster_dir)
    save_roster("BBB", Roster("BBB", ir=["D1"]), roster_dir=roster_dir)
    monkeypatch.setattr(da, "load_roster", lambda tid, *a, **k: load_roster(tid, roster_dir=roster_dir))
    monkeypatch.setattr(da, "save_roster", lambda tid, r, *a, **k: save_roster(tid, r, roster_dir=roster_dir))
    ok, note, _ = da._assign_to_low("AAA", "D1")
    assert ok is False and "BBB" in str(note)
    ok, _, _ = da._assign_to_low("AAA", "D2")
    assert ok is True


# Every product module that writes a roster file, and why it cannot put a
# player on a second club. A new writer fails this test until it is added
# here (and checked): save_roster's guard covers it either way.
_ROSTER_WRITERS = {
    # cross-club: the guard (save_roster / save_rosters) is the backstop
    "services/free_agency.py": "FA signings: owning_club checked first",
    "api/routers/free_agency.py": "sign endpoint: _refuse_if_owned first",
    "services/trade_execution.py": "trades: save_rosters checks both clubs",
    "services/draft_assignment.py": "draftees to Low-A: guarded",
    "playbalance/draft_manager.py": "draft picks to Low-A: guarded",
    "utils/roster_backfill.py": "CPU fill from free agents: all levels + contracts excluded",
    # within one club (moves between its own levels, releases)
    "api/routers/admin_league.py": "clears a club's injured lists",
    "api/routers/injuries.py": "injury moves within the club",
    "api/routers/roster.py": "level moves / swaps within the club",
    "api/routers/season.py": "roster prep within each club",
    "playbalance/game_runner.py": "injury placement within the club",
    "services/contracts_service.py": "releases",
    "services/cpu_trade_proposals.py": "CPU upkeep within the club",
    "services/dl_automation.py": "injured-list moves within the club",
    "services/inseason_callups.py": "call-ups within the organisation",
    "services/prospect_promotion.py": "promotions within the organisation",
    "services/roster_auto_assign.py": "auto-assign within the organisation",
    "services/roster_fill.py": "fills within the organisation",
    "services/roster_moves.py": "level moves within the club",
}


def _calls(path: Path, names: set[str]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in names:
                found.append(name)
    return found


def test_every_roster_writer_is_known_and_goes_through_the_guard():
    product = []
    for top in ("api", "services", "utils", "playbalance", "physics_sim", "models"):
        product.extend(sorted((BASE_DIR / top).rglob("*.py")))
    writers = set()
    for path in product:
        rel = path.relative_to(BASE_DIR).as_posix()
        calls = _calls(path, {"save_roster", "save_rosters", "write_roster_csv"})
        if "write_roster_csv" in calls:
            # The raw writer is only ever called behind the guard.
            assert rel == "utils/roster_loader.py", f"{rel} writes a roster file unguarded"
        if rel == "utils/roster_loader.py":
            continue
        if {"save_roster", "save_rosters"} & set(calls):
            writers.add(rel)
    assert writers == set(_ROSTER_WRITERS), (
        "roster writers changed; review each new one for a second club: "
        f"new={sorted(writers - set(_ROSTER_WRITERS))} gone={sorted(set(_ROSTER_WRITERS) - writers)}"
    )


# ---------------------------------------------------------------------------
# The read-only diagnostic
# ---------------------------------------------------------------------------
def test_diagnostic_lists_doubles_with_a_proposal_and_writes_nothing(tmp_path):
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    try:
        import find_double_rostered_players as diag
    finally:
        sys.path.pop(0)

    data = tmp_path / "data"
    (data / "rosters").mkdir(parents=True)
    # P1 was on BAL's injured list when COL signed him "as a free agent".
    (data / "rosters" / "BAL.csv").write_text("P1,DL15\nP2,ACT\n", encoding="utf-8")
    (data / "rosters" / "COL.csv").write_text("P1,ACT\nP3,ACT\nP4,AAA\n", encoding="utf-8")
    (data / "rosters" / "COL_pitching.csv").write_text("P3,SP1\n", encoding="utf-8")
    (data / "contracts.json").write_text(json.dumps({"players": {
        "P1": {"team_id": "COL", "years_left": 5, "annual_salary": 8_688_241},
    }}), encoding="utf-8")
    (data / "players.csv").write_text(
        "player_id,first_name,last_name,injured\nP1,Cedric,White,True\n", encoding="utf-8"
    )
    (data / "transactions.csv").write_text(
        "timestamp,season_date,team_id,player_id,player_name,action,from_level,to_level,counterparty,details\n"
        "2026-10-11 07:58:57,2026-09-16,COL,P1,Cedric White,sign,FA,ACT,,via negotiation\n",
        encoding="utf-8",
    )
    (data / "users.txt").write_text("u1,pw,owner,COL\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}

    report = diag.find(data)

    assert {p: p.read_bytes() for p in data.rglob("*") if p.is_file()} == before
    [item] = report["double_rostered"]
    assert item["player_id"] == "P1" and item["name"] == "Cedric White"
    assert [(c["team_id"], c["level"]) for c in item["clubs"]] == [("BAL", "DL15"), ("COL", "ACT")]
    proposal = item["proposal"]
    assert proposal["keep_with"] == "BAL"
    assert "COL signed him as a free agent" in proposal["reason"]
    [removal] = proposal["remove_from"]
    assert removal["team_id"] == "COL" and removal["owner_club"] is True
    assert (removal["before"]["ACT"], removal["after"]["ACT"]) == (2, 1)
    assert (removal["before"]["org"], removal["after"]["org"]) == (3, 2)


# ---------------------------------------------------------------------------
# Parallel day
# ---------------------------------------------------------------------------
def test_players_in_two_games_finds_shared_players_and_clubs_playing_twice(tmp_path, monkeypatch):
    import playbalance.season_simulator as ss

    roster_dir = tmp_path / "rosters"
    roster_dir.mkdir()
    # Written directly: the guard would refuse the shared players.
    (roster_dir / "A.csv").write_text("p1,ACT\np2,ACT\n", encoding="utf-8")
    (roster_dir / "B.csv").write_text("p3,ACT\np2,ACT\np1,DL15\n", encoding="utf-8")
    (roster_dir / "C.csv").write_text("p4,ACT\n", encoding="utf-8")
    (roster_dir / "D.csv").write_text("p5,ACT\n", encoding="utf-8")
    load_roster.cache_clear()
    monkeypatch.setattr(ss, "get_data_dir", lambda: tmp_path)
    find = ss.SeasonSimulator._players_in_two_games
    # p2 is active for A and B; p1 (B's injured list) cannot play for B.
    assert find([{"home": "A", "away": "C"}, {"home": "B", "away": "D"}]) == ["p2"]
    assert find([{"home": "C", "away": "D"}, {"home": "C", "away": "A"}]) == ["club C"]
    assert find([{"home": "A", "away": "C"}, {"home": "D", "away": "B"}][:1]) == []


def test_a_day_with_a_shared_player_is_played_serially(tmp_path, monkeypatch):
    import playbalance.season_simulator as ss

    monkeypatch.setenv("PB_PARALLEL_GAMES", "2")
    monkeypatch.setattr(ss.SeasonSimulator, "_parallel_eligible", lambda self: True)
    monkeypatch.setattr(ss.SeasonSimulator, "_players_in_two_games", staticmethod(lambda games: ["P1"]))

    def _no_parallel(*a, **k):
        raise AssertionError("the day must play serially")

    monkeypatch.setattr(ss.SeasonSimulator, "_simulate_day_parallel", _no_parallel)
    played = []

    def game(home, away, seed=None, game_date=None):
        played.append((home, away))
        return 1, 0

    sim = ss.SeasonSimulator(
        [{"date": "2026-04-01", "home": "A", "away": "B"},
         {"date": "2026-04-01", "home": "C", "away": "D"}],
        game,
    )
    random.seed(1)
    assert sim.simulate_next_day() == 2
    assert played == [("A", "B"), ("C", "D")]


def test_box_score_position_comes_from_the_game_not_the_player_object():
    from playbalance.game_runner import _hydrate_physics_boxscore

    starter = SimpleNamespace(player_id="s1", first_name="S", last_name="One",
                              primary_position="LF", position="LF")
    # A substitute whose object still carries an earlier game's position.
    sub = SimpleNamespace(player_id="b1", first_name="B", last_name="One",
                          primary_position="LF", position="RF")
    box = {"home": {"batting": [{"player_id": "s1"}, {"player_id": "b1"}],
                    "pitching": [], "fielding": []},
           "away": {"batting": [], "pitching": [], "fielding": []}}
    out = _hydrate_physics_boxscore(
        box, {"s1": starter, "b1": sub},
        lineup_positions={"home": {"s1": "CF"}, "away": {}},
    )
    rows = out["home"]["batting"]
    assert [r["pos"] for r in rows] == ["CF", "LF"]


@pytest.mark.parametrize("with_shared_player", [False, True])
def test_parallel_matches_serial_with_a_player_on_two_clubs(tmp_path, with_shared_player):
    """The same days from the same state, serial versus two workers: the
    same scores, season stats, recovery, rest state and box scores.

    Without a shared player the days really run in two worker processes.
    With a starter on two clubs' active rosters (the state that lost lines)
    every such day is played serially BY DESIGN, so that case compares
    serial with serial and checks the fallback keeps every game's line.
    """

    source = BASE_DIR / "data" / "leagues" / "cbl" / "data"
    if not source.exists():
        pytest.skip("cbl fixture league not present")
    league = tmp_path / "source"
    shutil.copytree(
        source, league, ignore=shutil.ignore_patterns("boxscores", "season_history", "*.bak", "logs")
    )
    shared = _share_a_starter(league) if with_shared_player else None

    def run(workers: int, sandbox: Path) -> dict:
        env = dict(os.environ)
        if workers:
            env["PB_PARALLEL_GAMES"] = str(workers)
        else:
            env.pop("PB_PARALLEL_GAMES", None)
        out = subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "benchmark_sim_days.py"),
             "--source", str(league), "--sandbox", str(sandbox),
             "--days", "2", "--seed", "321", "--json"],
            env=env, capture_output=True, text=True, cwd=str(BASE_DIR),
        )
        assert out.returncode == 0, out.stderr
        result = json.loads(out.stdout)
        # Both days go to the workers unless a player is shared.
        expected = 0 if not workers or shared else 2
        assert result["parallel_days"] == expected, (workers, shared, out.stderr[-2000:])
        return result["digests"]

    serial = run(0, tmp_path / "serial")
    parallel = run(2, tmp_path / "parallel")
    assert serial == parallel
    if shared is None:
        return
    # He started for both clubs each day; serial play counts every game
    # (on the base commit two workers kept one game's line a day).
    lines = [
        json.loads((tmp_path / name / "season_stats.json").read_text(encoding="utf-8"))
        ["players"][shared]
        for name in ("serial", "parallel")
    ]
    assert lines[0] == lines[1]


def _share_a_starter(league: Path) -> str:
    """Put a starter of club X in club Y's active roster and saved lineups.

    X and Y do not meet on the harness's first two days (it pairs the
    sorted clubs, rotating by one a day), so he starts in two games a day.
    """

    import csv

    with (league / "teams.csv").open(encoding="utf-8", newline="") as fh:
        teams = sorted(r["team_id"] for r in csv.DictReader(fh))
    paired = set()
    for day in range(2):
        rot = teams[day:] + teams[:day]
        for i in range(0, len(rot) - 1, 2):
            paired.add(frozenset((rot[i], rot[i + 1])))
    with_lineups = [t for t in teams if (league / "lineups" / f"{t}_vs_rhp.csv").exists()]
    x, y = next(
        (a, b) for a in with_lineups for b in with_lineups
        if a != b and frozenset((a, b)) not in paired
    )
    with (league / "lineups" / f"{x}_vs_rhp.csv").open(encoding="utf-8", newline="") as fh:
        first = next(csv.DictReader(fh))
    star, pos = first["player_id"], first["position"]
    with (league / "rosters" / f"{y}.csv").open("a", encoding="utf-8") as fh:
        fh.write(f"{star},ACT\n")
    for side in ("rhp", "lhp"):
        path = league / "lineups" / f"{y}_vs_{side}.csv"
        with path.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        for row in rows:
            if row["position"] == pos:
                row["player_id"] = star
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["order", "player_id", "position"])
            writer.writeheader()
            writer.writerows(rows)
    return star
