"""Unknown ownership never lets the CPU act for an owner's club (7.46.0).

The final review of the 26-man release found the CPU free-agent negotiation,
draft auto-pick and trade-evaluator paths still read ownership leniently: a
users.txt that couldn't be read looked like "no owners", so an owner's club
(blank owner_id in the cloud) was treated as CPU. Every mutating path now
uses ``team_ownership.human_owned_team_ids_strict`` and stands down on None,
and users.txt is written atomically so a reader never sees it half-written.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.test_roster_26_cpu_review_fixes import _fa_league, _p


@pytest.fixture
def isolated_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    import utils.path_utils as pu

    pu._DATA_DIR_CACHE.clear()
    yield root
    pu._DATA_DIR_CACHE.clear()


def _teams():
    return [SimpleNamespace(team_id="AAA", owner_id=""), SimpleNamespace(team_id="BBB", owner_id="")]


# --- CPU free-agent bid book ---------------------------------------------------


def test_bid_book_with_a_genuinely_unreadable_users_file(tmp_path, isolated_root):
    from services.finance_ai import build_cpu_free_agent_bid_book

    data_dir = _fa_league(tmp_path)
    (data_dir / "users.txt").unlink(missing_ok=True)
    (data_dir / "users.txt").mkdir()  # exists, can't be read as a file
    bids = build_cpu_free_agent_bid_book(
        _p("P100", "1B", 60), _teams(), ai_level="advanced", data_dir=data_dir
    )
    assert bids == {}


def test_bid_book_honours_a_lower_case_owner_team_id(tmp_path, isolated_root):
    from services.finance_ai import build_cpu_free_agent_bid_book

    data_dir = _fa_league(tmp_path)
    (data_dir / "users.txt").write_text("own,pw,owner,bbb\n", encoding="utf-8")
    bids = build_cpu_free_agent_bid_book(
        _p("P100", "1B", 60), _teams(), ai_level="advanced", data_dir=data_dir
    )
    assert "BBB" not in bids


# --- negotiations ---------------------------------------------------------------


def _negotiation(offers, deadline="2026-06-01"):
    return {"negotiations": {"P1": {
        "player_id": "P1", "status": "open", "deadline_date": deadline, "offers": offers,
    }}}


def test_resolution_reads_the_negotiations_own_league(tmp_path, isolated_root, monkeypatch):
    """Ownership comes from the league passed in, not the default data dir."""
    import services.fa_negotiations as neg

    league = tmp_path / "league"
    league.mkdir()
    (league / "users.txt").write_text("own,pw,owner,BBB\n", encoding="utf-8")
    monkeypatch.setattr(neg, "_player_accepts", lambda o, p: True)
    neg.save_negotiations(_negotiation([
        {"team_id": "BBB", "is_cpu": True, "annual_salary": 9_000_000, "years": 1},
        {"team_id": "AAA", "is_cpu": True, "annual_salary": 5_000_000, "years": 1},
    ]), data_dir=league)
    signed = []
    neg.process_negotiations(
        "2026-06-05", data_dir=league,
        sign_fn=lambda **k: signed.append(k["team_id"]) or True,
        players_by_id={"P1": object()},
    )
    assert signed == ["AAA"]


def test_a_deferred_negotiation_is_not_a_no_deal(tmp_path, monkeypatch):
    import services.fa_negotiations as neg

    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: None
    )
    monkeypatch.setattr(neg, "_player_accepts", lambda o, p: True)
    neg.save_negotiations(_negotiation([
        {"team_id": "AAA", "is_cpu": True, "annual_salary": 5_000_000, "years": 1},
    ]), data_dir=tmp_path)
    summary = neg.process_negotiations(
        "2026-06-05", data_dir=tmp_path, sign_fn=lambda **k: True,
        players_by_id={"P1": object()},
    )
    assert neg.has_open_negotiation("P1", data_dir=tmp_path)
    assert summary["no_deal"] == []
    assert summary.get("deferred") == ["P1"]


def test_dropping_a_bogus_cpu_leader_keeps_an_owners_bid_alive(tmp_path, monkeypatch):
    """Before the deadline, a CPU offer posted for owner club BBB triggered an
    early signing; dropping it must not close CCC's live (low) bid."""
    import services.fa_negotiations as neg

    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"BBB"}
    )
    monkeypatch.setattr(neg, "_player_accepts", lambda o, p: o["annual_salary"] >= 5_000_000)
    monkeypatch.setattr(neg, "_fair_market_total", lambda p: 1)
    neg.save_negotiations(_negotiation([
        {"team_id": "BBB", "is_cpu": True, "annual_salary": 9_000_000, "years": 1},
        {"team_id": "CCC", "annual_salary": 3_000_000, "years": 1},
    ], deadline="2026-12-01"), data_dir=tmp_path)
    neg.process_negotiations(
        "2026-06-05", data_dir=tmp_path, sign_fn=lambda **k: True,
        players_by_id={"P1": object()},
    )
    n = neg.get_negotiation("P1", data_dir=tmp_path)
    assert n["status"] == "open"
    assert [o["team_id"] for o in n["offers"]] == ["CCC"]


# --- draft and trades -------------------------------------------------------------


def test_draft_tick_stands_down_when_ownership_is_unreadable(monkeypatch):
    import api.routers.season as season
    from api.routers import draft as draft_router

    monkeypatch.setattr("services.trade_settings.current_league_year", lambda: 2026)
    monkeypatch.setattr("services.draft_state.load_state", lambda year: {"order": ["BBB"]})
    monkeypatch.setattr(
        "services.draft_settings.load_draft_settings",
        lambda: SimpleNamespace(rounds=5, pick_clock_hours=1),
    )
    monkeypatch.setattr(draft_router, "_draft_complete", lambda s, r: False)
    monkeypatch.setattr(draft_router, "_team_on_clock", lambda s: "BBB")
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: None
    )
    acted = []
    monkeypatch.setattr(draft_router, "auto_advance", lambda *a, **k: acted.append("advance") or {})
    monkeypatch.setattr(draft_router, "_do_pick", lambda *a, **k: acted.append("pick"))
    monkeypatch.setattr(draft_router, "_best_available", lambda *a, **k: {"player_id": "X"})
    monkeypatch.setattr(season, "_announce_draft_clock", lambda *a, **k: None)
    assert season._advance_draft_for_league("L1") is None
    assert acted == []


def test_trade_evaluator_never_answers_for_an_unknown_club(monkeypatch):
    from services import cpu_trade_evaluator as ev

    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: None
    )
    teams = {"BBB": SimpleNamespace(team_id="BBB", owner_id="")}
    assert ev.is_cpu_owned_team("BBB", teams_by_id=teams) is False


def test_is_cpu_owned_is_strict(monkeypatch):
    from services import team_ownership

    monkeypatch.setattr(team_ownership, "human_owned_team_ids_strict", lambda *a, **k: None)
    assert team_ownership.is_cpu_owned("AAA") is False
    monkeypatch.setattr(team_ownership, "human_owned_team_ids_strict", lambda *a, **k: {"BBB"})
    assert team_ownership.is_cpu_owned("AAA") is True
    assert team_ownership.is_cpu_owned("bbb") is False


# --- users.txt is written atomically --------------------------------------------


def test_users_file_is_replaced_atomically(tmp_path, monkeypatch):
    import os

    from utils import user_manager

    path = tmp_path / "users.txt"
    path.write_text("admin,x,admin,\n", encoding="utf-8")
    replaced = []
    real_replace = os.replace
    monkeypatch.setattr(
        user_manager.os, "replace", lambda a, b: (replaced.append((a, b)), real_replace(a, b))
    )
    user_manager._write_users(path, [
        {"username": "admin", "password": "x", "role": "admin", "team_id": ""},
        {"username": "own", "password": "y", "role": "owner", "team_id": "BBB"},
    ])
    assert replaced and replaced[0][1] == path
    assert path.read_text(encoding="utf-8").splitlines()[-1] == "own,y,owner,BBB"
    assert not list(tmp_path.glob(".users.txt.*.tmp"))
