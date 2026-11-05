"""8.11.0 (backlog #70): CPU clubs draft by need.

A CPU club took the best player left by overall, whatever its organization
held: in alpha-test's 2027 draft BOS, with no catcher at any level, took two
pitchers, a shortstop and a second baseman while fifteen catchers were in the
class. Now a position the club is thin at counts a little extra until it has
drafted one, and no position piles up in one draft. Replayed on a copy of
that draft, CPU clubs filled 12 of their 13 thin positions (2 before), and
28 of the top 30 prospects still went in the first 30 picks (29 before).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import api.routers.draft as D
from services import draft_board as B
from tests.test_draft_board import ADMIN, OWNER, POOL, _p, draft  # noqa: F401

AVG = {"P": 20.0, "C": 4.0, "1B": 3.0, "2B": 3.0, "3B": 3.0, "SS": 3.0, "LF": 3.0, "CF": 3.0, "RF": 3.0}
EVEN = {pos: int(n) for pos, n in AVG.items()}


def _plan(rounds=4, **depth):
    return B.cpu_plan(depth={**EVEN, **depth}, league_average=AVG, rounds=rounds)


def _pick(plan, pool, drafted=()):
    by_id = {p["player_id"]: p for p in pool}
    return B.cpu_choose(
        plan, pool=pool, taken=set(drafted), drafted=[by_id[d] for d in drafted]
    )


# --- the plan --------------------------------------------------------------------


def test_an_even_organization_has_no_needs():
    assert _plan()["needs"] == {}


def test_nobody_at_a_position_is_worth_more_than_a_thin_one():
    needs = _plan(C=0, SS=1)["needs"]
    assert needs == {"C": B.NEED_BONUS_NONE, "SS": B.NEED_BONUS_THIN}


def test_limits_scale_with_the_rounds_and_tighten_where_the_club_is_deep():
    four = _plan(rounds=4, RF=9)["limits"]
    assert four["SS"] == 2 and four["RF"] == 1 and four["P"] == 3
    ten = _plan(rounds=10, P=40)["limits"]
    assert ten["SS"] == 3 and ten["P"] == 5


# --- the pick --------------------------------------------------------------------


def test_with_no_needs_it_takes_the_best_player_available():
    assert _pick(_plan(), POOL) == "SS1"


def test_a_club_with_no_catcher_takes_one_close_to_the_best():
    pool = [_p("P1", "P", 52), _p("C1", "C", 50)]
    assert _pick(_plan(), pool) == "P1"
    assert _pick(_plan(C=0), pool) == "C1"


def test_a_need_never_reaches_far_down_the_class():
    pool = [_p("P1", "P", 60), _p("C1", "C", 45)]
    assert _pick(_plan(C=0), pool) == "P1"


def test_the_need_is_met_by_one_pick():
    pool = [_p("C1", "C", 50), _p("P1", "P", 52), _p("C2", "C", 50)]
    assert _pick(_plan(C=0), pool, drafted=["C1"]) == "P1"


def test_no_position_piles_up_in_one_draft():
    pool = [_p("SS1", "SS", 70), _p("SS2", "SS", 69), _p("SS3", "SS", 68), _p("CF1", "CF", 50)]
    assert _pick(_plan(), pool, drafted=["SS1", "SS2"]) == "CF1"


def test_when_every_position_left_is_full_somebody_is_still_taken():
    pool = [_p("SS1", "SS", 70), _p("SS2", "SS", 69), _p("SS3", "SS", 68)]
    assert _pick(_plan(), pool, drafted=["SS1", "SS2"]) == "SS3"


# --- the draft --------------------------------------------------------------------


def test_organization_depth_reads_the_rosters_and_leaves_the_class_out(draft, monkeypatch):
    state, _told, tmp_path = draft
    rosters = tmp_path / "rosters"
    rosters.mkdir()
    (rosters / "CHA.csv").write_text("h1,ACT\np1,AAA\nC1,LOW\n", encoding="utf-8")
    (rosters / "DAL.csv").write_text("h2,ACT\nh3,LOW\n", encoding="utf-8")
    players = [
        SimpleNamespace(player_id="h1", primary_position="SS", is_pitcher=False),
        SimpleNamespace(player_id="h2", primary_position="C", is_pitcher=False),
        SimpleNamespace(player_id="h3", primary_position="C", is_pitcher=False),
        SimpleNamespace(player_id="p1", primary_position="SP", is_pitcher=True),
        # A drafted prospect is on a roster already; the class is left out.
        SimpleNamespace(player_id="C1", primary_position="C", is_pitcher=False),
    ]
    monkeypatch.setattr(D, "get_data_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(D, "load_players_from_csv", lambda *a, **k: players)
    depth, average = D._org_depth(2027, state)
    assert depth["CHA"] == {"SS": 1, "P": 1}
    assert depth["DAL"] == {"C": 2}
    assert depth["BAL"] == {}  # no roster file: counted as empty, never generated
    assert not (rosters / "BAL.csv").exists()
    assert average["C"] == pytest.approx(2 / 3)


def test_a_cpu_club_drafts_by_need_in_the_draft(draft, monkeypatch):
    state, _told, _tmp = draft
    # CHA (CPU) picks first and has no catcher: C1 is a point short of
    # the best player left, within what the need is worth.
    pool = [_p("SS1", "SS", 60), _p("C1", "C", 59), _p("P1", "P", 50)]
    by_id = {p["player_id"]: p for p in pool}
    monkeypatch.setattr(D, "_prospect_lookup", lambda year: dict(by_id))
    depth = {"CHA": {**EVEN, "C": 0}, "BAL": dict(EVEN), "DAL": dict(EVEN)}
    monkeypatch.setattr(D, "_org_depth", lambda year, st: (depth, AVG))
    D.auto_advance({"year": 2027, "stop": "next_human"}, identity=ADMIN)
    assert state["selected"][0] == {"overall": 1, "round": 1, "team_id": "CHA", "player_id": "C1"}


@pytest.fixture
def short_at_catcher(draft, monkeypatch):
    """Every club has no catcher; SS1 is the best left, C1 a point behind."""

    pool = [_p("SS1", "SS", 60), _p("C1", "C", 59), _p("C2", "C", 58)]
    by_id = {p["player_id"]: p for p in pool}
    monkeypatch.setattr(D, "_prospect_lookup", lambda year: dict(by_id))
    depth = {team: {**EVEN, "C": 0} for team in ("CHA", "BAL", "DAL")}
    monkeypatch.setattr(D, "_org_depth", lambda year, st: (depth, AVG))
    monkeypatch.setattr(
        D, "_best_available", lambda year, st: next(
            p for p in pool if p["player_id"] not in D._selected_ids(st)
        )
    )
    return draft


def test_auto_pick_drafts_by_need_for_any_club_without_a_board(short_at_catcher):
    state, told, _tmp = short_at_catcher
    assert D.auto_pick({"year": 2027}, identity=ADMIN)["player_id"] == "C1"  # CHA, CPU
    # BAL is an owner's club with no board: picked by need too (owner's call,
    # 2026-11-04), so C2 rather than SS1.
    assert D.auto_pick({"year": 2027}, identity=OWNER)["player_id"] == "C2"
    assert told[-1][2]["why"] == "owner" and told[-1][2]["board"] is False


def test_the_commissioner_auto_picking_for_an_owner_without_a_board_tells_the_owner(
    short_at_catcher,
):
    state, told, _tmp = short_at_catcher
    state["overall_pick"] = 2  # BAL
    assert D.auto_pick({"year": 2027}, identity=ADMIN)["player_id"] == "C1"
    assert told[-1][0] == "BAL" and told[-1][2]["why"] == "commissioner"


def test_an_owner_without_a_board_whose_clock_ran_out_is_picked_for_by_need(
    short_at_catcher,
):
    state, told, _tmp = short_at_catcher
    state["overall_pick"] = 2  # BAL
    result = D._pick_for_owner(2027, state, "BAL", why="clock")
    assert result["player_id"] == "C1" and result["source"] == "clock"
    reason = told[-1][2]["reason"]
    assert "no draft board" in reason and "short at C" in reason


def test_finishing_the_draft_picks_by_need_for_an_owner_without_a_board(short_at_catcher):
    state, told, _tmp = short_at_catcher
    D.auto_advance(
        {"year": 2027, "stop": "end_of_round", "include_human_teams": True}, identity=ADMIN
    )
    picks = {s["team_id"]: s["player_id"] for s in state["selected"]}
    assert picks["CHA"] == "C1" and picks["BAL"] == "C2"


def test_the_reason_names_the_need_it_could_not_fill():
    plan = {"limits": {}, "needs": {"C": 3.0}}
    text = D._need_reason(_p("SS1", "SS", 60), plan, [])
    assert "best player available" in text and "short at C" in text
    assert "best player available" in D._need_reason(_p("SS1", "SS", 60), None, [])


def test_unreadable_depth_falls_back_to_the_best_player_available(draft, monkeypatch):
    state, _told, _tmp = draft
    monkeypatch.setattr(D, "_org_depth", lambda year, st: None)
    D.auto_advance({"year": 2027, "stop": "next_human"}, identity=ADMIN)
    assert state["selected"][0]["player_id"] == "SS1"
