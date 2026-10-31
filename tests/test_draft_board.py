"""8.7.0: owners' draft boards.

When an owner's pick clock ran out the CPU took the best player left by
overall, whatever the club needed. A draft board is the owner's ranked list
plus a few plain rules (not before round N, only one of a group, position
limits, position needs, what to take when the list runs dry), and it can be
told to pick the moment the club is up. It is private to the owner.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import api.routers.draft as D
from services import draft_board as B
from services.draft_announcement import build_pick_messages


def _p(pid, pos, level=50, pot=None, first="Joe"):
    """A prospect whose every rating is ``level``."""

    pitcher = pos == "P"
    row = {
        "player_id": pid,
        "first_name": first,
        "last_name": pid,
        "primary_position": pos,
        "is_pitcher": pitcher,
    }
    keys = (
        ("control", "movement", "endurance", "fb", "sl")
        if pitcher
        else ("ch", "ph", "sp", "eye", "fa", "arm")
    )
    for key in keys:
        row[key] = level
        if pot is not None:
            row[f"pot_{key}"] = pot
    return row


POOL = [
    _p("SS1", "SS", 70),
    _p("C1", "C", 65),
    _p("P1", "P", 68),
    _p("CF1", "CF", 60),
    _p("SS2", "SS", 55),
    _p("C2", "C", 52),
    _p("P2", "P", 50),
]
BY_ID = {p["player_id"]: p for p in POOL}


def _board(entries=(), **rules):
    raw = {"entries": [e if isinstance(e, dict) else {"player_id": e} for e in entries], **rules}
    return B.normalize_board(raw, team_id="BAL", year=2027)


def _choose(board, *, taken=(), drafted=(), round_no=1, pool=POOL):
    return B.choose(
        board,
        pool=pool,
        taken=set(taken) | set(drafted),
        drafted=[BY_ID[d] for d in drafted],
        round_no=round_no,
    )


# --- the ranked list ---------------------------------------------------------


def test_the_board_takes_its_highest_ranked_player_left():
    choice = _choose(_board(["CF1", "SS1"]))
    assert choice.player_id == "CF1"
    assert choice.source == "board"


def test_it_says_who_it_passed_over():
    choice = _choose(_board(["SS1", "C1", "CF1"]), taken={"SS1", "C1"})
    assert choice.player_id == "CF1"
    assert "#3 on your board" in choice.reason
    assert "#1 Joe SS1 (taken)" in choice.reason and "#2 Joe C1 (taken)" in choice.reason


def test_not_before_round_stops_a_reach():
    board = _board([{"player_id": "C2", "not_before_round": 3}, "P2"])
    assert _choose(board, round_no=2).player_id == "P2"
    assert _choose(board, round_no=3).player_id == "C2"


def test_only_one_of_a_group_is_taken():
    board = _board([
        {"player_id": "SS1", "group": "A"},
        {"player_id": "SS2", "group": "A"},
        "CF1",
    ])
    choice = _choose(board, taken={"SS1"}, drafted=["SS1"])
    assert choice.player_id == "CF1"
    assert "group A" in choice.reason


def test_a_full_position_is_skipped_and_every_pick_counts():
    """The two catchers were the owner's own picks; the limit still holds."""
    board = _board(["C1", "CF1"], position_limits={"C": 1})
    assert _choose(board, drafted=["C2"]).player_id == "CF1"
    assert _choose(board).player_id == "C1"


def test_a_family_limit_covers_its_positions():
    board = _board(["SS1", "CF1"], position_limits={"IF": 1})
    assert _choose(board, drafted=["SS2"]).player_id == "CF1"


def test_a_need_that_is_due_decides_the_position():
    board = _board(["P1", "CF1", "SS2"], needs=[{"position": "SS", "count": 1, "by_round": 2}])
    assert _choose(board, round_no=1).player_id == "P1"
    choice = _choose(board, round_no=2)
    assert choice.player_id == "SS2"
    assert "your SS need is due" in choice.reason


def test_a_met_need_is_not_forced():
    board = _board(["P1", "SS2"], needs=[{"position": "SS", "count": 1, "by_round": 1}])
    assert _choose(board, drafted=["SS1"], round_no=3).player_id == "P1"


def test_a_due_need_with_nobody_on_the_board_takes_the_best_at_the_position():
    board = _board(["P1"], needs=[{"position": "C", "count": 1, "by_round": 1}])
    choice = _choose(board)
    assert choice.player_id == "C1"
    assert choice.source == "fallback"
    assert "at C" in choice.reason


# --- tiers -------------------------------------------------------------------


def test_within_a_tier_a_need_wins():
    board = _board(
        [{"player_id": "P1", "tier": 1}, {"player_id": "C2", "tier": 1}, {"player_id": "SS1", "tier": 2}],
        use_tiers=True,
        needs=[{"position": "C", "count": 1, "by_round": 9}],
    )
    choice = _choose(board)
    assert choice.player_id == "C2"
    assert "fills a need" in choice.reason


def test_within_a_tier_the_best_overall_wins_otherwise():
    board = _board(
        [{"player_id": "P2", "tier": 1}, {"player_id": "SS1", "tier": 1}],
        use_tiers=True,
    )
    assert _choose(board).player_id == "SS1"


def test_without_tiers_the_order_is_the_order():
    board = _board([{"player_id": "P2", "tier": 1}, {"player_id": "SS1", "tier": 1}])
    assert _choose(board).player_id == "P2"


# --- when the board runs dry ---------------------------------------------------


@pytest.mark.parametrize(
    "fallback,expected",
    [
        ("best_available", "SS1"),
        ("best_pitcher", "P1"),
        ("best_hitter", "SS1"),
        ("best_need", "CF1"),
    ],
)
def test_the_fallback(fallback, expected):
    board = _board(["C1"], fallback=fallback, needs=[{"position": "OF", "count": 1, "by_round": 9}])
    choice = _choose(board, taken={"C1"})
    assert choice.player_id == expected
    assert choice.source == "fallback"
    assert "Nobody on your board could be taken" in choice.reason


def test_highest_ceiling_reads_potential():
    pool = [_p("NOW", "SS", 70, pot=72), _p("LATER", "SS", 55, pot=90)]
    board = _board([], fallback="highest_potential")
    assert B.choose(board, pool=pool, taken=set(), drafted=[], round_no=1).player_id == "LATER"
    assert B.choose(_board([]), pool=pool, taken=set(), drafted=[], round_no=1).player_id == "NOW"


def test_limits_give_way_when_nobody_else_is_left():
    pool = [_p("C1", "C", 60)]
    board = _board([], position_limits={"C": 0})
    choice = B.choose(board, pool=pool, taken=set(), drafted=[], round_no=1)
    assert choice.player_id == "C1"
    assert "every player left is at a position you limited" in choice.reason


def test_nobody_left_is_none():
    assert _choose(_board(["SS1"]), taken=set(BY_ID)) is None


# --- the stored board ----------------------------------------------------------


def test_bad_settings_are_refused_with_a_reason():
    with pytest.raises(ValueError, match="Unknown position"):
        _board(position_limits={"QB": 1})
    with pytest.raises(ValueError, match="fallback"):
        _board(fallback="vibes")
    with pytest.raises(ValueError, match="autodraft"):
        _board(autodraft="sometimes")
    with pytest.raises(ValueError, match="Group"):
        _board([{"player_id": "SS1", "group": "Z"}])


def test_unknown_and_repeated_players_are_dropped():
    board = B.normalize_board(
        {"entries": [{"player_id": "SS1"}, {"player_id": "GHOST"}, {"player_id": "SS1"}]},
        team_id="BAL",
        year=2027,
        pool_ids=set(BY_ID),
    )
    assert [e["player_id"] for e in board["entries"]] == ["SS1"]


def test_tiers_only_go_up_the_list():
    board = _board([{"player_id": "SS1", "tier": 2}, {"player_id": "C1", "tier": 1}])
    assert [e["tier"] for e in board["entries"]] == [2, 2]


def test_saving_keeps_the_picks_the_board_made(tmp_path):
    B.save_board(2027, "BAL", {"entries": [{"player_id": "SS1"}]}, data_dir=tmp_path)
    B.record_pick(2027, "BAL", {"overall": 4, "player_id": "SS1", "reason": "x"}, data_dir=tmp_path)
    B.save_board(2027, "BAL", {"entries": [], "made": []}, data_dir=tmp_path)
    board = B.load_board(2027, "BAL", data_dir=tmp_path)
    assert [m["player_id"] for m in board["made"]] == ["SS1"]
    assert (tmp_path / "draft_boards" / "2027" / "BAL.json").exists()


# --- the draft ------------------------------------------------------------------

ORDER = ["CHA", "BAL", "DAL"]  # BAL is an owner's club
OWNER = {"u": "o", "r": "owner", "mr": "owner", "t": "BAL"}
ADMIN = {"u": "commish", "r": "admin", "mr": "admin", "t": ""}


@pytest.fixture
def draft(monkeypatch, tmp_path):
    state = {"year": 2027, "round": 1, "overall_pick": 1, "order": list(ORDER), "selected": []}
    told = []

    def fake_do_pick(year, st, *, player_id, season_date=None, announce=True, source=None):
        team = D._team_on_clock(st)
        entry = {"overall": st["overall_pick"], "round": st["round"], "team_id": team, "player_id": player_id}
        if source:
            entry["source"] = source
        st["selected"] = list(st["selected"]) + [entry]
        st["overall_pick"] += 1
        if (st["overall_pick"] - 1) % len(ORDER) == 0:
            st["round"] += 1
        return dict(entry)

    def best(year, st):
        taken = D._selected_ids(st)
        left = [p for p in POOL if p["player_id"] not in taken]
        return max(left, key=B.prospect_score) if left else None

    monkeypatch.setattr("utils.path_utils.get_data_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(D.draft_state, "load_state", lambda year: state)
    monkeypatch.setattr(D.draft_state, "save_state", lambda year, st: None)
    monkeypatch.setattr(D, "_do_pick", fake_do_pick)
    monkeypatch.setattr(D, "_best_available", best)
    monkeypatch.setattr(D, "_prospect_lookup", lambda year: dict(BY_ID))
    monkeypatch.setattr(D, "_load_settings_rounds", lambda: 2)
    monkeypatch.setattr(D, "_announce_picks", lambda *a, **k: None)
    monkeypatch.setattr(
        D, "_tell_owner_of_pick", lambda year, team, result, **k: told.append((team, result, k))
    )
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"BAL"}
    )
    return state, told, tmp_path


def _save(tmp_path, **board):
    B.save_board(2027, "BAL", board, data_dir=tmp_path)


def test_an_autodrafting_owner_is_picked_for_and_the_draft_runs_on(draft):
    state, told, tmp_path = draft
    _save(tmp_path, entries=[{"player_id": "C2"}], autodraft="board")
    result = D.auto_advance({"year": 2027, "stop": "next_human"}, identity=ADMIN)
    bal = [s for s in state["selected"] if s["team_id"] == "BAL"]
    assert bal[0]["player_id"] == "C2" and bal[0]["source"] == "board"
    assert told[0][2]["why"] == "autodraft"
    # Round 2: C2 is gone, the board has nobody left and only picks from its
    # list, so the draft stops at BAL.
    assert result["stopped_reason"] == "human_on_clock"
    assert result["team_on_clock"] == "BAL"


def test_auto_draft_everything_keeps_going_past_an_empty_board(draft):
    state, told, tmp_path = draft
    _save(tmp_path, entries=[{"player_id": "C2"}], autodraft="all")
    result = D.auto_advance({"year": 2027, "stop": "next_human"}, identity=ADMIN)
    assert result["draft_complete"] is True
    assert len([s for s in state["selected"] if s["team_id"] == "BAL"]) == 2


def test_with_auto_draft_off_the_draft_waits_for_the_owner(draft):
    state, told, tmp_path = draft
    _save(tmp_path, entries=[{"player_id": "C2"}])
    result = D.auto_advance({"year": 2027, "stop": "next_human"}, identity=ADMIN)
    assert result["stopped_reason"] == "human_on_clock"
    assert [s["team_id"] for s in state["selected"]] == ["CHA"]


def test_finishing_the_draft_for_everyone_uses_the_owners_board(draft):
    state, told, tmp_path = draft
    _save(tmp_path, entries=[{"player_id": "C2"}, {"player_id": "P2"}])
    D.auto_advance(
        {"year": 2027, "stop": "end_of_draft", "include_human_teams": True}, identity=ADMIN
    )
    bal = [s["player_id"] for s in state["selected"] if s["team_id"] == "BAL"]
    assert bal == ["C2", "P2"]
    assert {t[2]["why"] for t in told} == {"commissioner"}


def test_auto_pick_uses_the_board(draft):
    state, told, tmp_path = draft
    state["overall_pick"] = 2  # BAL
    _save(tmp_path, entries=[{"player_id": "P2"}])
    result = D.auto_pick({"year": 2027}, identity=OWNER)
    assert result["player_id"] == "P2"
    assert told[0][2]["why"] == "owner"


def test_the_clock_running_out_picks_from_the_board(draft, monkeypatch):
    import api.routers.season as season
    from types import SimpleNamespace

    state, told, tmp_path = draft
    state["overall_pick"] = 2  # BAL
    _save(tmp_path, entries=[{"player_id": "C2"}])
    monkeypatch.setattr("services.trade_settings.current_league_year", lambda: 2027)
    monkeypatch.setattr("services.draft_state.load_state", lambda year: state)
    monkeypatch.setattr(
        "services.draft_settings.load_draft_settings",
        lambda: SimpleNamespace(rounds=2, pick_clock_hours=4),
    )
    monkeypatch.setattr("services.draft_clock.is_expired", lambda *a, **k: True)
    monkeypatch.setattr(season, "_announce_draft_clock", lambda *a, **k: None)
    advanced = []
    monkeypatch.setattr(D, "auto_advance", lambda *a, **k: advanced.append(1) or {})
    row = season._advance_draft_for_league("L1")
    assert row["action"] == "clock_expired"
    assert state["selected"][-1] == {
        "overall": 2, "round": 1, "team_id": "BAL", "player_id": "C2", "source": "board",
    }
    assert told[0][2]["why"] == "clock"
    assert advanced == [1]


def test_auto_draft_works_with_the_clock_off_but_leaves_the_cpu_to_the_commissioner(
    draft, monkeypatch
):
    import api.routers.season as season
    from types import SimpleNamespace

    state, told, tmp_path = draft
    state["overall_pick"] = 2  # BAL
    _save(tmp_path, entries=[{"player_id": "C2"}], autodraft="board")
    monkeypatch.setattr("services.trade_settings.current_league_year", lambda: 2027)
    monkeypatch.setattr("services.draft_state.load_state", lambda year: state)
    monkeypatch.setattr(
        "services.draft_settings.load_draft_settings",
        lambda: SimpleNamespace(rounds=2, pick_clock_hours=0),
    )
    monkeypatch.setattr(season, "_announce_draft_clock", lambda *a, **k: None)
    advanced = []
    monkeypatch.setattr(D, "auto_advance", lambda *a, **k: advanced.append(1) or {})
    row = season._advance_draft_for_league("L1")
    assert row["action"] == "board_autodraft"
    assert state["selected"][-1]["player_id"] == "C2"
    assert advanced == []


# --- privacy ----------------------------------------------------------------------


def test_the_owner_reads_and_saves_his_board(draft, monkeypatch):
    state, told, tmp_path = draft
    monkeypatch.setattr(D, "page_scale", lambda: None)
    out = D.draft_board_save(
        "BAL",
        {"year": 2027, "board": {"entries": [{"player_id": "C2"}, {"player_id": "GHOST"}]}},
        identity=OWNER,
    )
    assert [e["player_id"] for e in out["entries"]] == ["C2"]
    assert out["entries"][0]["prospect"]["primary_position"] == "C"
    # BAL picks second: the board would take C2 there.
    assert out["next_pick"] == {"overall": 2, "round": 1}
    assert out["preview"]["player_id"] == "C2"
    again = D.draft_board_view("BAL", year=2027, identity=OWNER)
    assert again["entries"][0]["player_id"] == "C2"


@pytest.mark.parametrize(
    "identity",
    [ADMIN, {"u": "c", "r": "admin", "mr": "commissioner", "t": "DAL"}, {"u": "x", "r": "owner", "t": "DAL"}],
    ids=["super-admin", "commissioner-with-another-club", "another-owner"],
)
def test_nobody_else_can_open_a_board(draft, identity):
    with pytest.raises(HTTPException) as exc:
        D.draft_board_view("BAL", year=2027, identity=identity)
    assert exc.value.status_code == 403


def test_a_bad_board_is_a_400(draft):
    with pytest.raises(HTTPException) as exc:
        D.draft_board_save(
            "BAL", {"year": 2027, "board": {"position_limits": {"QB": 1}}}, identity=OWNER
        )
    assert exc.value.status_code == 400


def test_the_public_draft_only_says_the_board_made_the_pick():
    posts = build_pick_messages(
        league_id="alpha-test",
        year=2027,
        picks=[{"round": 1, "overall": 2, "team_id": "BAL", "name": "Joe C2", "position": "C", "source": "board"}],
    )
    assert "(from their draft board)" in posts[0]
    assert "Passed over" not in posts[0]


def test_a_board_with_a_setting_no_longer_allowed_still_loads(tmp_path):
    path = B.board_path(2027, "BAL", data_dir=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "entries": [{"player_id": "SS1"}],
        "position_limits": {"QB": 2},
        "made": [{"player_id": "C1"}],
    }), encoding="utf-8")
    board = B.load_board(2027, "BAL", data_dir=tmp_path)
    assert [e["player_id"] for e in board["entries"]] == ["SS1"]
    assert board["position_limits"] == {}
    assert board["made"] == [{"player_id": "C1"}]
