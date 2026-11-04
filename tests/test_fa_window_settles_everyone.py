"""8.9.1: every free-agent negotiation settles inside the bidding window.

alpha-test's 2027 window closed with 16 players still under negotiation
(signings that failed on the last day, fixed in 8.8.0), left to sign on the
first regular-season day. The one way left for a negotiation to outlive the
window was the deciding pass holding a player back because club ownership
couldn't be read. Now the window stays open on its last day until the pass
has settled every one, and the next advance runs it again.
"""

from __future__ import annotations

import pytest

import services.fa_window as w
from services import fa_negotiations as neg
from tests.test_fa_window_notices import _news, league  # noqa: F401 (fixture)


class _Ev:
    decision = "accepted"


@pytest.fixture
def market(tmp_path, monkeypatch):
    monkeypatch.setattr("services.fa_negotiations.OFFER_RULES", 1)
    monkeypatch.setattr(
        "services.contract_negotiator.evaluate_extension_offer", lambda p, **k: _Ev()
    )
    monkeypatch.setattr(
        "services.contract_negotiator.fair_market_salary", lambda p, **k: 2_000_000
    )
    monkeypatch.setattr(
        "services.contract_negotiator.fair_market_years", lambda p, **k: 2
    )
    monkeypatch.setattr(w, "finance_fa_enabled", lambda **k: True)
    monkeypatch.setattr(w, "_seed_cpu_for_day", lambda *a, **k: 0)
    monkeypatch.setattr(w, "_load_teams", lambda: [])
    monkeypatch.setattr(
        w, "_load_players_by_id", lambda base: {"PX": object(), "PY": object()}
    )
    monkeypatch.setattr(
        "services.cpu_extensions.run_cpu_extension_pass", lambda *a, **k: None
    )
    signed: dict = {}
    fails: set = set()

    def make_sign_fn(base):
        def _sign(*, team_id, player_id, offer, player):
            if player_id in fails:
                return False
            signed[player_id] = team_id
            return True

        return _sign

    monkeypatch.setattr(w, "_make_sign_fn", make_sign_fn)
    w.open_window("2025-03-01", data_dir=tmp_path)
    state = w.load_window(data_dir=tmp_path)
    state["day"] = state["total_days"]  # straight to the deciding pass
    w._save_window(state, data_dir=tmp_path)
    return {"dir": tmp_path, "signed": signed, "fails": fails}


def _cpu_offer(pid, team, data_dir):
    neg.submit_offer(pid, team, years=2, annual_salary=2_100_000,
                     sim_date="2025-03-01", is_cpu=True, window_day=1,
                     data_dir=data_dir)


def _ownership(monkeypatch, value):
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: value
    )


def test_the_window_waits_for_a_player_it_had_to_hold_back(market, monkeypatch):
    base = market["dir"]
    _cpu_offer("PX", "CPU1", base)
    _ownership(monkeypatch, None)  # ownership unreadable on the last day

    out = w.advance_day(data_dir=base)

    state = w.load_window(data_dir=base)
    assert out["ok"] is True
    assert state["status"] == "open"
    assert state["day"] == state["total_days"]
    assert state["settling"] == 1
    assert state["log"][-1]["unsettled"] == ["PX"]
    assert "still to settle" in state["log"][-1]["message"]
    assert neg.has_open_negotiation("PX", data_dir=base)
    assert w.window_status(data_dir=base)["settling"] == 1
    # The instant unsigned sweep stays locked: he is still the window's.
    assert w.unsigned_sweep_locked(data_dir=base) is True

    _ownership(monkeypatch, set())  # readable again
    w.advance_day(data_dir=base)

    state = w.load_window(data_dir=base)
    assert state["status"] == "closed"
    assert "settling" not in state
    assert market["signed"] == {"PX": "CPU1"}
    assert neg.open_negotiation_player_ids(data_dir=base) == set()


def test_the_deciding_pass_leaves_nothing_open(market, monkeypatch):
    base = market["dir"]
    _ownership(monkeypatch, set())
    _cpu_offer("PX", "CPU1", base)
    _cpu_offer("PY", "CPU2", base)
    market["fails"].add("PY")  # e.g. a full roster: no deal, not left open

    w.advance_day(data_dir=base)

    assert w.load_window(data_dir=base)["status"] == "closed"
    assert neg.open_negotiation_player_ids(data_dir=base) == set()
    assert neg.get_negotiation("PY", data_dir=base)["resolution"]["outcome"] == "no_deal"
    assert market["signed"] == {"PX": "CPU1"}


def test_the_news_says_bidding_stays_open(league):  # noqa: F811
    from services.fa_window_notices import day_advanced

    state = {"status": "open", "day": 14, "total_days": 14, "settling": 2}
    out = day_advanced(state, day=14, signed=[], data_dir=league)
    assert out["news"] == (
        "Free agency day 14 of 14: 0 signings. Bidding stays open until the "
        "last 2 players settle."
    )
    assert out["notified"] == {}
    assert _news(league)[-1].endswith(out["news"])


# --- leftovers from a window that closed before 8.9.1 -----------------------

def _close(base):
    state = w.load_window(data_dir=base)
    state["status"] = "closed"
    w._save_window(state, data_dir=base)


def test_a_closed_windows_leftovers_settle_and_later_offers_wait(market, monkeypatch):
    base = market["dir"]
    _ownership(monkeypatch, set())
    _cpu_offer("PX", "CPU1", base)      # left open by the window
    _cpu_offer("PY", "CPU2", base)      # left open, and his signing fails
    market["fails"].add("PY")
    _close(base)
    # An owner's offer after the window closed: an ordinary negotiation.
    neg.submit_offer("PZ", "BAL", years=1, annual_salary=900_000,
                     sim_date="2025-03-20", data_dir=base)
    assert w.leftover_player_ids(data_dir=base) == ["PX", "PY"]

    out = w.settle_leftovers(data_dir=base)

    assert out["ok"] is True and out["settled"] == 2 and out["remaining"] == []
    assert market["signed"] == {"PX": "CPU1"}
    assert neg.get_negotiation("PY", data_dir=base)["resolution"]["outcome"] == "no_deal"
    assert neg.has_open_negotiation("PZ", data_dir=base)  # untouched
    entry = w.load_window(data_dir=base)["log"][-1]
    assert entry["leftovers"] is True
    assert entry["date"] == "2025-03-14"  # the window's last day
    assert entry["message"] == (
        "2 free agents left over from bidding settled: 1 signed, 1 took no deal."
    )
    assert w.settle_leftovers(data_dir=base) == {"ok": False, "reason": "nothing_to_settle"}


def test_an_open_window_has_no_leftovers(market):
    base = market["dir"]
    _cpu_offer("PX", "CPU1", base)
    assert w.leftover_player_ids(data_dir=base) == []
    assert w.settle_leftovers(data_dir=base)["ok"] is False
    assert neg.has_open_negotiation("PX", data_dir=base)


@pytest.mark.parametrize("phase,settles", [
    ("PRESEASON", True), ("OFFSEASON", True), ("REGULAR_SEASON", True),
    ("AMATEUR_DRAFT", False), ("PLAYOFFS", False),
])
def test_the_tick_settles_them_only_when_signings_are_open(market, monkeypatch, phase, settles):
    import api.routers.season as S

    base = market["dir"]
    _ownership(monkeypatch, set())
    _cpu_offer("PX", "CPU1", base)
    _close(base)

    class _Mgr:
        def __init__(self):
            self.phase = type("P", (), {"value": phase})()

    monkeypatch.setattr(S, "SeasonManager", _Mgr)
    monkeypatch.setattr("services.fa_window.get_data_dir", lambda: base)

    out = S._settle_fa_leftovers("t")

    if settles:
        assert out == {"fa_leftovers_settled": 1, "signed": 1, "remaining": 0}
        assert market["signed"] == {"PX": "CPU1"}
    else:
        assert out is None
        assert neg.has_open_negotiation("PX", data_dir=base)
