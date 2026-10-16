"""8.1.1 hotfix, review round: trades are all or nothing; a contracted player
on no roster is his club's to place; the repair mode of the diagnostic.

1. A refused trade (a player who would land on a second club) used to keep
   its draft picks moved: picks were transferred before the rosters were
   checked. Now nothing moves -- owner trades stay pending, CPU trades are
   dropped -- and a commissioner reversal still works.
2. A qualifying offer accepted after the rollover took the player off his
   roster restored only his contract. Now he goes back on the roster; a club
   holding such a player can put him back (sign endpoint, auto-assign, CPU
   fill) and nobody else can sign him. A draft pick that cannot be placed is
   not signed; a cut whose contract cannot be released is undone.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from models.roster import Roster
from models.trade import Trade
from utils.roster_loader import load_roster, save_roster
from utils.roster_ownership import DoubleRosterError, owning_club, unrostered_contracts

from tests.test_r3_lpfix_cpu_trade_roster_shape import league  # noqa: F401 (fixture)
from tests.test_r81_one_club_per_player import (  # noqa: F401 (fixture)
    _PLAYER_HEADER,
    _TEAMS,
    _no_placeholder_arms,
    _player_row,
)

BASE_DIR = Path(__file__).resolve().parents[1]


class _Ledger:
    """In-memory draft-pick ledger standing in for draft_pick_ledger.json."""

    def __init__(self, owners):
        self.owners = dict(owners)
        self.writes = 0

    def owner(self, year, round_no, original):
        return self.owners.get(f"{year}|{round_no}|{original}", original)

    def transfer(self, pick_id, from_team, to_team):
        if self.owners.get(pick_id, pick_id.split("|")[2]) != from_team:
            raise ValueError(f"{pick_id} is owned by {self.owners.get(pick_id)}, not {from_team}.")
        self.owners[pick_id] = to_team
        self.writes += 1


def _patch_ledger(monkeypatch, ledger):
    monkeypatch.setattr("services.trade_execution.get_pick_owner", ledger.owner)
    monkeypatch.setattr("services.trade_execution.transfer_pick", ledger.transfer)
    monkeypatch.setattr("services.trade_execution.record_transaction", lambda **k: None)
    monkeypatch.setattr("services.trade_execution.claim_players", lambda *a, **k: None)


def _three_clubs(roster_dir: Path) -> None:
    # x1 is on AAA and on CCC's injured list (an older build's double).
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "AAA.csv").write_text("a1,ACT\nx1,ACT\n", encoding="utf-8")
    (roster_dir / "BBB.csv").write_text("b1,ACT\n", encoding="utf-8")
    (roster_dir / "CCC.csv").write_text("x1,DL15\n", encoding="utf-8")
    load_roster.cache_clear()


def _files(roster_dir: Path) -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(roster_dir.glob("*.csv"))}


# ---------------------------------------------------------------------------
# 1. Trades: all or nothing
# ---------------------------------------------------------------------------
def test_a_refused_trade_moves_no_pick_and_no_player(tmp_path, monkeypatch):
    from services.trade_execution import commit_trade

    roster_dir = tmp_path / "rosters"
    _three_clubs(roster_dir)
    ledger = _Ledger({"2027|1|AAA": "AAA", "2027|2|BBB": "BBB"})
    _patch_ledger(monkeypatch, ledger)
    before = _files(roster_dir)
    trade = Trade("t1", "AAA", "BBB", ["x1"], ["b1"],
                  give_pick_ids=["2027|1|AAA"], receive_pick_ids=["2027|2|BBB"])
    with pytest.raises(DoubleRosterError):
        commit_trade(trade, data_dir=tmp_path)
    assert ledger.owners == {"2027|1|AAA": "AAA", "2027|2|BBB": "BBB"}
    assert ledger.writes == 0
    assert _files(roster_dir) == before
    # The cache holds no half-applied trade either.
    assert "b1" not in load_roster("AAA", roster_dir=roster_dir).act
    # Retrying gives the same refusal, not "pick owned by BBB".
    with pytest.raises(DoubleRosterError):
        commit_trade(trade, data_dir=tmp_path)


def test_a_pick_the_club_no_longer_holds_moves_nothing(tmp_path, monkeypatch):
    from services.trade_execution import commit_trade

    roster_dir = tmp_path / "rosters"
    _three_clubs(roster_dir)
    # The second pick is no longer BBB's: the first must not move either.
    ledger = _Ledger({"2027|1|AAA": "AAA", "2027|2|BBB": "CCC"})
    _patch_ledger(monkeypatch, ledger)
    before = _files(roster_dir)
    with pytest.raises(ValueError, match="owned by CCC"):
        commit_trade(Trade("t2", "AAA", "BBB", ["a1"], ["b1"],
                           give_pick_ids=["2027|1|AAA"], receive_pick_ids=["2027|2|BBB"]),
                     data_dir=tmp_path)
    assert ledger.owners["2027|1|AAA"] == "AAA" and ledger.writes == 0
    assert _files(roster_dir) == before


def test_a_trade_and_its_commissioner_reversal_move_everything_back(tmp_path, monkeypatch):
    from services.trade_execution import commit_trade

    roster_dir = tmp_path / "rosters"
    _three_clubs(roster_dir)
    ledger = _Ledger({"2027|1|AAA": "AAA"})
    _patch_ledger(monkeypatch, ledger)
    before = _files(roster_dir)
    trade = Trade("t3", "AAA", "BBB", ["a1"], ["b1"], give_pick_ids=["2027|1|AAA"])
    commit_trade(trade, data_dir=tmp_path)
    assert ledger.owners["2027|1|AAA"] == "BBB"
    assert (roster_dir / "BBB.csv").read_text(encoding="utf-8").split() == ["a1,ACT"]
    # api.routers.trades.reverse_trade commits this mirror trade.
    reverse = Trade("t3", "BBB", "AAA", ["a1"], ["b1"], give_pick_ids=["2027|1|AAA"])
    commit_trade(reverse, data_dir=tmp_path)
    assert ledger.owners["2027|1|AAA"] == "AAA"
    assert sorted(_files(roster_dir)["AAA.csv"].split()) == sorted(before["AAA.csv"].split())
    assert _files(roster_dir)["BBB.csv"].split() == ["b1,ACT"]


def test_owner_accept_of_a_refused_trade_returns_400_and_stays_pending(tmp_path, monkeypatch):
    import api.routers.trades as router

    root = tmp_path / "data"
    (root / "users.txt").parent.mkdir(parents=True)
    (root / "users.txt").write_text("", encoding="utf-8")
    (root / "players.csv").write_text("player_id,first_name,last_name\n", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    _three_clubs(root / "rosters")
    ledger = _Ledger({"2027|1|AAA": "AAA"})
    _patch_ledger(monkeypatch, ledger)
    trade = Trade("t4", "AAA", "BBB", ["x1"], [], give_pick_ids=["2027|1|AAA"])
    saved = []
    monkeypatch.setattr(router, "_find_trade", lambda tid: trade)
    monkeypatch.setattr(router, "save_trade", lambda t, *a, **k: saved.append(t.status))
    monkeypatch.setattr("services.trade_execution.announce_trade", lambda *a, **k: None)
    try:
        with pytest.raises(HTTPException) as exc:
            router.accept_trade("t4", {"r": "admin", "t": ""})
        assert exc.value.status_code == 400
        assert "x1 is already on CCC's roster" in str(exc.value.detail)
        assert saved == []  # never written as accepted: still pending on disk
        assert ledger.owners["2027|1|AAA"] == "AAA"
        assert "x1" not in (root / "rosters" / "BBB.csv").read_text(encoding="utf-8")
    finally:
        path_utils._DATA_DIR_CACHE.clear()


def test_cpu_trade_refused_by_the_guard_is_dropped_and_moves_no_pick(league, monkeypatch, caplog):  # noqa: F811
    from services.cpu_trade_proposals import _CandidateOffer, run_cpu_trade_proposal_cycle

    root = league.root
    # CPUA's hitter is also on a third club's injured list.
    (root / "rosters" / "CPUC.csv").write_text("CPUA_h12,DL15\n", encoding="utf-8")
    load_roster.cache_clear()
    ledger = _Ledger({"2027|1|CPUA": "CPUA"})
    monkeypatch.setattr("services.trade_execution.get_pick_owner", ledger.owner)
    monkeypatch.setattr("services.trade_execution.transfer_pick", ledger.transfer)

    def _offer(**kwargs):
        targets = list(kwargs.get("target_team_ids") or [])
        if not targets or not kwargs.get("return_ranked"):
            return [] if kwargs.get("return_ranked") else None
        proposer, receiver = kwargs["cpu_team_id"], targets[0]
        if proposer != "CPUA":
            return []
        trade = Trade(trade_id="cpu1", from_team=proposer, to_team=receiver,
                      give_player_ids=["CPUA_h12"], receive_player_ids=[f"{receiver}_p12"],
                      give_pick_ids=["2027|1|CPUA"], initiated_by="cpu")
        return [_CandidateOffer(trade=trade, score_margin=0.5,
                                cpu_team_id=proposer, target_team_id=receiver)]

    monkeypatch.setattr("services.cpu_trade_proposals._build_best_offer", _offer)
    monkeypatch.setattr("services.roster_validation.validate_trade",
                        lambda **k: SimpleNamespace(ok=True, errors=[], warnings=[]))
    before = _files(root / "rosters")
    with caplog.at_level("WARNING"):
        result = run_cpu_trade_proposal_cycle(
            simulated_dates=["2026-07-15"], data_dir=root, rng=random.Random(1),
        )
    lane = result["cpu_cpu_trades"]
    assert lane["executed"] == []
    assert lane["filtered"]["commit_failed"] == 1
    assert ledger.owners == {"2027|1|CPUA": "CPUA"} and ledger.writes == 0
    assert _files(root / "rosters") == before
    assert "dropped, nothing moved" in caplog.text


# ---------------------------------------------------------------------------
# 2. A contracted player on no roster belongs to his club
# ---------------------------------------------------------------------------
def _qo_league(tmp_path: Path) -> Path:
    data = tmp_path / "league"
    (data / "rosters").mkdir(parents=True)
    (data / "teams.csv").write_text(_TEAMS, encoding="utf-8")
    (data / "players.csv").write_text(
        _PLAYER_HEADER + "".join(_player_row(p) for p in ("P1", "P2", "Q1")), encoding="utf-8"
    )
    (data / "rosters" / "AAA.csv").write_text("P1,ACT\n", encoding="utf-8")
    (data / "rosters" / "BBB.csv").write_text("P2,ACT\n", encoding="utf-8")
    (data / "contracts.json").write_text(json.dumps({"version": 1, "players": {}}), encoding="utf-8")
    return data


def test_accepted_qualifying_offer_puts_him_back_on_the_roster(tmp_path):
    from services.qualifying_offers import QO_VALUE, _resign_on_qo

    data = _qo_league(tmp_path)  # Q1 just came off AAA's roster at the rollover
    assert _resign_on_qo("Q1", "AAA", data_dir=data) is True
    contract = json.loads((data / "contracts.json").read_text(encoding="utf-8"))["players"]["Q1"]
    assert contract["team_id"] == "AAA" and contract["annual_salary"] == QO_VALUE
    assert "Q1,ACT" in (data / "rosters" / "AAA.csv").read_text(encoding="utf-8")
    assert unrostered_contracts(data) == {}
    assert owning_club("Q1", data) == ("AAA", "ACT")


def test_qualifying_offer_does_not_take_a_player_another_club_signed(tmp_path):
    from services.qualifying_offers import _resign_on_qo

    data = _qo_league(tmp_path)
    (data / "rosters" / "BBB.csv").write_text("P2,ACT\nQ1,ACT\n", encoding="utf-8")
    assert _resign_on_qo("Q1", "AAA", data_dir=data) is False
    assert json.loads((data / "contracts.json").read_text(encoding="utf-8"))["players"] == {}
    assert "Q1" not in (data / "rosters" / "AAA.csv").read_text(encoding="utf-8")


def _orphan(data: Path, pid="Q1", team="AAA") -> None:
    (data / "contracts.json").write_text(json.dumps({"version": 1, "players": {
        pid: {"team_id": team, "years_left": 1, "annual_salary": 18_000_000},
    }}), encoding="utf-8")


def test_own_club_restores_a_contracted_player_others_get_409(tmp_path, monkeypatch):
    from tests.test_r81_one_club_per_player import _point_router_at

    data = _qo_league(tmp_path)
    _orphan(data)
    router = _point_router_at(monkeypatch, data)
    monkeypatch.setattr("services.free_agency.record_transaction", lambda **k: None)
    with pytest.raises(HTTPException) as exc:
        router.sign_free_agent("BBB", {"player_id": "Q1", "level": "ACT", "force": True},
                               {"r": "admin", "t": ""})
    assert exc.value.status_code == 409 and exc.value.detail["team_id"] == "AAA"
    with pytest.raises(HTTPException) as exc:
        router.submit_fa_offer("Q1", {"team_id": "AAA", "years": 1, "annual_salary": 1},
                               {"r": "owner", "t": "AAA"})
    assert exc.value.detail["code"] == "own_contract"
    out = router.sign_free_agent("AAA", {"player_id": "Q1", "level": "AAA"},
                                 {"r": "owner", "t": "AAA"})
    assert out["restored_under_contract"] is True and out["level"] == "AAA"
    assert "Q1,AAA" in (data / "rosters" / "AAA.csv").read_text(encoding="utf-8")
    # His contract is the one he had, not a new one.
    assert json.loads((data / "contracts.json").read_text(encoding="utf-8"))["players"]["Q1"][
        "annual_salary"] == 18_000_000


def test_auto_assign_places_the_clubs_contracted_player(tmp_path, monkeypatch):
    import services.roster_auto_assign as ra

    data = _qo_league(tmp_path)
    _orphan(data)
    players = {pid: SimpleNamespace(player_id=pid, primary_position="1B", other_positions=[],
                                    is_pitcher=False, injured=False, birthdate="1998-01-01",
                                    ch=50, ph=50, sp=50, fa=50, arm=50, sc=50, eye=50)
               for pid in ("P1", "Q1")}
    assert ra._unrostered_contracted("AAA", str(data / "rosters"), players) == ["Q1"]
    assert ra._unrostered_contracted("BBB", str(data / "rosters"), players) == []


def test_cpu_fill_places_a_cpu_clubs_contracted_player(tmp_path, monkeypatch):
    from utils.roster_backfill import ensure_active_rosters
    from utils.player_loader import load_players_from_csv

    data = _qo_league(tmp_path)
    _orphan(data)
    monkeypatch.setattr("utils.roster_backfill.load_teams",
                        lambda *a, **k: [SimpleNamespace(team_id="AAA", owner_id="cpu"),
                                         SimpleNamespace(team_id="BBB", owner_id="cpu")])
    players = {p.player_id: p for p in load_players_from_csv(str(data / "players.csv"))}
    ensure_active_rosters(players=players, roster_dir=data / "rosters", data_dir=data)
    assert owning_club("Q1", data)[0] == "AAA"
    assert owning_club("Q1", data)[1] in {"ACT", "AAA", "LOW"}
    assert "Q1" not in (data / "rosters" / "BBB.csv").read_text(encoding="utf-8")


def test_unplaced_draft_pick_gets_no_contract(tmp_path, monkeypatch):
    import services.draft_assignment as da

    calls = []
    monkeypatch.setattr(da, "_load_pool_map", lambda year: {})
    monkeypatch.setattr(da, "_players_index", lambda: {"D9": {"first_name": "D", "last_name": "Nine"}})
    monkeypatch.setattr(da, "_assign_to_low", lambda team, pid: (False, "AAA: roster file not found", False))
    monkeypatch.setattr(da, "record_transaction", lambda **k: None)
    monkeypatch.setattr(da, "log_news_event", lambda *a, **k: None)
    monkeypatch.setattr(da, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr("services.contracts_service.upsert_contract",
                        lambda *a, **k: calls.append(("contract", a, k)))
    monkeypatch.setattr("services.owner_finance_engine.charge_team_one_time_cost",
                        lambda *a, **k: calls.append(("bonus", a, k)) or {"applied": True, "amount": 1})
    monkeypatch.setattr("services.finance_settings.load_financial_settings",
                        lambda **k: SimpleNamespace(enabled=True, module_level=lambda m: "basic"))
    out = da.commit_single_pick(2027, team_id="AAA", player_id="D9", round_number=1, overall_pick=3)
    assert out["assigned"] is False
    assert calls == []
    assert "no contract signed" in out["note"]


def test_cut_is_undone_when_the_contract_cannot_be_released(tmp_path, monkeypatch):
    import api.routers.roster as rr

    roster_dir = tmp_path / "rosters"
    roster_dir.mkdir()
    (roster_dir / "AAA.csv").write_text("P1,ACT\nP2,ACT\n", encoding="utf-8")
    load_roster.cache_clear()
    monkeypatch.setattr(rr, "load_roster", lambda tid, *a, **k: load_roster(tid, roster_dir=roster_dir))
    monkeypatch.setattr(rr, "save_roster", lambda tid, r, *a, **k: save_roster(tid, r, roster_dir=roster_dir))
    import services.roster_moves as rm

    monkeypatch.setattr(rm, "load_roster", lambda tid, *a, **k: load_roster(tid, roster_dir=roster_dir))
    monkeypatch.setattr(rm, "save_roster", lambda tid, r, *a, **k: save_roster(tid, r, roster_dir=roster_dir))
    monkeypatch.setattr(rm, "record_transaction", lambda **k: None)

    def _boom(ids, **k):
        raise OSError("contracts.json is read-only")

    monkeypatch.setattr("services.contracts_service.release_contracts_to_free_agency", _boom)
    with pytest.raises(HTTPException) as exc:
        rr.cut_roster("AAA", {"player_id": "P2"}, {"r": "admin", "t": ""})
    assert exc.value.status_code == 500 and "undone" in exc.value.detail
    assert (roster_dir / "AAA.csv").read_text(encoding="utf-8").split() == ["P1,ACT", "P2,ACT"]


# ---------------------------------------------------------------------------
# 5. The diagnostic's repair mode
# ---------------------------------------------------------------------------
def _diag():
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    try:
        import find_double_rostered_players as diag
    finally:
        sys.path.pop(0)
    return diag


def _double_league(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "rosters").mkdir(parents=True)
    (data / "rosters" / "BAL.csv").write_text("P1,DL15\nP2,ACT\n", encoding="utf-8")
    (data / "rosters" / "COL.csv").write_text("P1,ACT\nP3,ACT\nP4,ACT\n", encoding="utf-8")
    (data / "rosters" / "OKL.csv").write_text("P4,ACT\n", encoding="utf-8")
    (data / "rosters" / "COL_pitching.csv").write_text("P1,RP\nP3,SP1\n", encoding="utf-8")
    (data / "contracts.json").write_text(json.dumps({"version": 1, "players": {
        "P1": {"team_id": "COL", "years_left": 5, "annual_salary": 8_688_241},
        "P4": {"team_id": "OKL", "years_left": 5, "annual_salary": 8_247_671},
    }}, indent=2), encoding="utf-8")
    return data


def test_repair_writes_only_into_the_output_folder(tmp_path):
    diag = _diag()
    data = _double_league(tmp_path)
    older = tmp_path / "older_contracts.json"
    older.write_text(json.dumps({"players": {
        "P1": {"team_id": "BAL", "years_left": 2, "annual_salary": 3_000_000},
    }}), encoding="utf-8")
    before = {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}
    out = tmp_path / "repaired"

    code = diag.main([str(data), "--repair", "P1=BAL", "--repair", "P4=COL",
                      "--contracts-from", str(older), "--output", str(out)])

    assert code == 0
    assert {p: p.read_bytes() for p in data.rglob("*") if p.is_file()} == before
    assert (out / "rosters" / "COL.csv").read_text(encoding="utf-8") == "P3,ACT\nP4,ACT\n"
    assert (out / "rosters" / "COL_pitching.csv").read_text(encoding="utf-8") == "P3,SP1\n"
    assert (out / "rosters" / "OKL.csv").read_text(encoding="utf-8") == ""
    assert not (out / "rosters" / "BAL.csv").exists()  # unchanged files are not copied
    contracts = json.loads((out / "contracts.json").read_text(encoding="utf-8"))["players"]
    assert contracts["P1"] == {"team_id": "BAL", "years_left": 2, "annual_salary": 3_000_000}
    assert contracts["P4"]["team_id"] == "OKL"  # no earlier COL contract given
    text = (out / "REPAIR.txt").read_text(encoding="utf-8")
    assert "P4 still names OKL" in text and "restored to BAL" in text
    # The repaired copy has no doubles left.
    merged = tmp_path / "merged"
    import shutil

    shutil.copytree(data, merged)
    shutil.copytree(out, merged, dirs_exist_ok=True)
    assert diag.find(merged)["double_rostered"] == []


def test_repair_refuses_in_place_or_a_wrong_club(tmp_path):
    diag = _diag()
    data = _double_league(tmp_path)
    assert diag.main([str(data), "--repair", "P1=BAL", "--output", str(data)]) == 2
    assert diag.main([str(data), "--repair", "P1=BAL", "--output", str(data / "x")]) == 2
    assert diag.main([str(data), "--repair", "P1=OKL", "--output", str(tmp_path / "o")]) == 2
    assert diag.main([str(data), "--repair", "P3=COL", "--output", str(tmp_path / "o")]) == 2
    assert diag.main([str(data), "--repair", "P1=BAL"]) == 2
