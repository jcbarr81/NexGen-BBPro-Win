"""Commissioner's rule: no draft pick is released just because there is no room,
and an owner's team is never trimmed by the CPU unless the owner asks.

After the 2026 draft, auto-assign released BAL's pick #47 for being over the
organisation cap. It ran in full mode from the deadline's CPU-fill, on an
OWNER's team, and full mode ranks the organisation and cuts whoever doesn't
fit -- which is the newest draft picks first, since their current ratings are
low.
"""

from types import SimpleNamespace

import pytest

import services.roster_auto_assign as A


# --- who counts as this year's draft class ---------------------------------


@pytest.mark.parametrize(
    "pid, expected",
    [("D20260013", True), ("D20260100", True), ("D20250013", False), ("P1234", False), ("", False)],
)
def test_draft_class_is_recognised_by_id(pid, expected):
    assert A._is_current_draft_pick(pid, 2026) is expected


def test_without_a_league_year_nobody_is_protected():
    assert A._is_current_draft_pick("D20260013", None) is False


# --- a released pick swaps with the weakest non-draftee --------------------


def _roster(low, aaa):
    return SimpleNamespace(low=list(low), aaa=list(aaa))


@pytest.fixture
def scores(monkeypatch):
    table = {}
    monkeypatch.setattr(A, "_overall_score", lambda p: table[p.player_id])

    def players(**ratings):
        table.update(ratings)
        return {pid: SimpleNamespace(player_id=pid) for pid in ratings}

    return players


def test_a_pick_that_would_be_cut_takes_the_weakest_slot_instead(scores):
    players = scores(D20260047=30, V1=50, V2=35, A1=60)
    roster = _roster(low=["V1", "V2"], aaa=["A1"])
    released = A._protect_draft_picks(roster, ["D20260047"], players, year=2026)
    assert released == ["V2"]                 # the weakest non-draftee goes
    assert "D20260047" in roster.low          # the pick takes his slot
    assert "V2" not in roster.low


def test_the_victim_can_come_from_aaa(scores):
    players = scores(D20260047=30, L1=70, A1=40, A2=65)
    roster = _roster(low=["L1"], aaa=["A1", "A2"])
    released = A._protect_draft_picks(roster, ["D20260047"], players, year=2026)
    assert released == ["A1"]
    assert "D20260047" in roster.aaa


def test_other_draft_picks_are_never_the_victim(scores):
    players = scores(D20260047=30, D20260048=10, V1=45)
    roster = _roster(low=["D20260048", "V1"], aaa=[])
    released = A._protect_draft_picks(roster, ["D20260047"], players, year=2026)
    assert released == ["V1"]
    assert {"D20260047", "D20260048"} <= set(roster.low)


def test_with_nobody_to_swap_the_pick_is_kept_not_released(scores):
    """Over the limit is the owner's problem; losing the pick is not."""
    players = scores(D20260047=30, D20260048=20)
    roster = _roster(low=["D20260048"], aaa=[])
    released = A._protect_draft_picks(roster, ["D20260047"], players, year=2026)
    assert released == []
    assert "D20260047" in roster.aaa


def test_non_draftees_released_for_room_are_unaffected(scores):
    players = scores(V1=50, V2=35)
    roster = _roster(low=["V1"], aaa=[])
    assert A._protect_draft_picks(roster, ["V2"], players, year=2026) == ["V2"]


def test_last_years_class_is_not_protected(scores):
    players = scores(D20250047=30, V1=50)
    roster = _roster(low=["V1"], aaa=[])
    assert A._protect_draft_picks(roster, ["D20250047"], players, year=2026) == ["D20250047"]


# --- the CPU never trims an owner's team -----------------------------------


def test_deadline_cpu_fill_uses_gaps_mode(monkeypatch):
    """Gaps mode fixes what is illegal and never releases anyone."""
    import api.routers.season as S

    calls = []
    monkeypatch.setattr(A, "auto_assign_team", lambda tid, **kw: calls.append((tid, kw)))
    monkeypatch.setattr("utils.lineup_autofill.auto_fill_lineup_for_team", lambda *a, **k: None)
    S._cpu_fill_team("BAL")
    assert calls == [("BAL", {"mode": "gaps"})]
