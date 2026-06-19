from __future__ import annotations

from services.draft_state import build_pick_sequence
from api.routers.draft import _team_on_clock, _draft_complete


def test_build_pick_sequence_no_comp_is_plain_repeat():
    seq = build_pick_sequence(["A", "B", "C"], 3)
    assert [e["team_id"] for e in seq] == ["A", "B", "C"] * 3
    # rounds advance every len(order) picks
    assert [e["round"] for e in seq] == [1, 1, 1, 2, 2, 2, 3, 3, 3]


def test_build_pick_sequence_comp_and_forfeit():
    seq = build_pick_sequence(["A", "B", "C"], 3, supplemental=["A"], forfeited=["B"])
    r1 = [e["team_id"] for e in seq if e["round"] == 1]
    r2 = [e["team_id"] for e in seq if e["round"] == 2]
    r3 = [e["team_id"] for e in seq if e["round"] == 3]
    # Round 1 gains A's compensation pick at the end; B forfeits its round-2 pick.
    assert r1 == ["A", "B", "C", "A"]
    assert r2 == ["A", "C"]
    assert r3 == ["A", "B", "C"]
    assert len(seq) == 4 + 2 + 3


def test_on_clock_and_complete_follow_the_sequence():
    seq = build_pick_sequence(["A", "B", "C"], 2, supplemental=["A"], forfeited=["B"])
    # picks: A,B,C,A (round 1) then A,C (round 2) => 6 picks total
    state = {"order": ["A", "B", "C"], "pick_sequence": seq, "overall_pick": 1}

    expected = ["A", "B", "C", "A", "A", "C"]
    for i, team in enumerate(expected, start=1):
        state["overall_pick"] = i
        assert _team_on_clock(state) == team, f"overall {i}"
        assert not _draft_complete(state, 2)

    state["overall_pick"] = 7  # past the last pick
    assert _team_on_clock(state) is None
    assert _draft_complete(state, 2) is True


def test_legacy_state_without_sequence_uses_modulo():
    state = {"order": ["A", "B", "C"], "overall_pick": 4}  # no pick_sequence
    assert _team_on_clock(state) == "A"  # (4-1) % 3 == 0 -> "A"
    assert _draft_complete({"order": ["A", "B", "C"], "round": 3}, 2) is True
