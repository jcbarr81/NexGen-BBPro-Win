"""S2-02: slot-weighted batting order."""
from types import SimpleNamespace

from utils.lineup_autofill import (
    _assign_batting_order,
    _platoon_adjustment,
    _slot_components,
)


def _p(pid, ch, ph, sp, eye, *, bats="R", vl=50):
    return SimpleNamespace(
        player_id=pid, ch=ch, ph=ph, sp=sp, eye=eye, vl=vl,
        fa=50, arm=50, bats=bats,
    )


# Roster archetypes (fa=arm=50 for all so defense doesn't reorder overall).
ROSTER = {
    "OB1": _p("OB1", 78, 45, 88, 92),  # leadoff: top OBP+speed
    "BE2": _p("BE2", 90, 82, 60, 80),  # best overall
    "PW4": _p("PW4", 62, 96, 30, 48),  # pure slugger
    "PW3": _p("PW3", 70, 88, 45, 60),  # second power
    "AV5": _p("AV5", 80, 70, 50, 55),  # contact/power blend
    "MD6": _p("MD6", 65, 60, 55, 55),  # mid
    "MD7": _p("MD7", 60, 55, 50, 50),  # mid-low
    "WK8": _p("WK8", 45, 40, 40, 40),  # weak
    "WK9": _p("WK9", 40, 35, 75, 35),  # weakest bat, fast
}
PAIRS = [(pid, "DH") for pid in ROSTER]


def _overall(players):
    def score(pid):
        p = players.get(pid)
        if not p:
            return -1.0
        off = 0.5 * p.ch + 0.5 * p.ph
        defense = 0.5 * p.fa + 0.5 * p.arm
        return (0.6 * off) + (0.2 * p.sp) + (0.2 * defense)
    return score


def _order(players=None, pairs=None, vs_hand="R"):
    players = players or ROSTER
    pairs = pairs if pairs is not None else PAIRS
    result = _assign_batting_order(
        pairs, players, vs_hand=vs_hand, overall_score=_overall(players)
    )
    return [pid for pid, _ in result]


def _obp(pid, vs_hand="R"):
    return _slot_components(ROSTER[pid], vs_hand=vs_hand)["obp"]


def test_leadoff_is_obp_speed():
    order = _order()
    assert order[0] == "OB1"
    obps = sorted((_obp(p) for p in order), reverse=True)
    assert _obp("OB1") in obps[:2]


def test_two_is_best_overall():
    assert _order()[1] == "BE2"


def test_cleanup_is_top_power():
    order = _order()
    assert order[3] == "PW4"
    powers = sorted((ROSTER[p].ph for p in order), reverse=True)
    assert ROSTER[order[3]].ph in powers[:2]


def test_three_five_are_run_producers():
    order = _order()
    assert {"PW3", "AV5"} <= {order[2], order[4]}


def test_worst_bat_hits_eighth_or_ninth():
    order = _order()
    assert {order[7], order[8]} == {"WK8", "WK9"}
    # Criterion 2: the worst OVERALL bat hits 8th/9th. Fill order fills slot 8
    # before 9 (keeps mid bats out of 9), so slot 9 lands the worst-overall bat.
    assert order[8] == "WK8"


def test_deterministic_on_ties():
    ident = {f"P{i}": _p(f"P{i}", 50, 50, 50, 50) for i in range(1, 10)}
    pairs = [(f"P{i}", "DH") for i in range(1, 10)]
    o1 = _order(ident, pairs)
    o2 = _order(ident, pairs)
    assert o1 == o2  # deterministic
    assert sorted(o1) == [f"P{i}" for i in range(1, 10)]  # pure permutation


def test_partial_lineup_short_roster():
    pairs = PAIRS[:6]
    order = _order(pairs=pairs)
    assert len(order) == 6
    assert len(set(order)) == 6


def test_platoon_shifts_order():
    # Use a platoon-aware overall (like the real hitter_score) so the handedness
    # swing reorders the near-equal AV5 (lefty) and PW3 (righty) run producers.
    players = dict(ROSTER)
    players["AV5"] = _p("AV5", 80, 70, 50, 55, bats="L", vl=20)
    players["OB1"] = _p("OB1", 78, 45, 88, 92, vl=80)

    def overall_factory(pl):
        base = _overall(pl)
        return lambda pid, hand: base(pid) + _platoon_adjustment(pl[pid], vs_hand=hand)

    ov = overall_factory(players)
    pairs = [(pid, "DH") for pid in players]
    vs_l = [
        p for p, _ in _assign_batting_order(
            pairs, players, vs_hand="L", overall_score=lambda pid: ov(pid, "L")
        )
    ]
    vs_r = [
        p for p, _ in _assign_batting_order(
            pairs, players, vs_hand="R", overall_score=lambda pid: ov(pid, "R")
        )
    ]
    assert vs_l != vs_r
