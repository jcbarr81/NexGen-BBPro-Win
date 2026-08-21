"""Preseason FA bidding window: staggered signings, CPU seeding, and the
lifecycle that locks the 'list unsigned players' sweep until the window closes.
"""

import services.fa_window as w
from services import fa_negotiations as neg


class _Ev:
    def __init__(self, decision):
        self.decision = decision


def _accept_all(monkeypatch):
    monkeypatch.setattr(
        "services.contract_negotiator.evaluate_extension_offer",
        lambda p, **k: _Ev("accepted"),
    )


def _fair(monkeypatch, salary, years):
    monkeypatch.setattr(
        "services.contract_negotiator.fair_market_salary", lambda p, **k: salary
    )
    monkeypatch.setattr(
        "services.contract_negotiator.fair_market_years", lambda p, **k: years
    )


# --- staggered resolution ---------------------------------------------------

def test_fair_offer_waits_for_patience_day(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    _fair(monkeypatch, 3_000_000, 3)  # fair total 9M
    pat = neg._patience_day("PX", 14)
    if pat == 1:  # pick an id that isn't ready on day 1
        pat = neg._patience_day("PY", 14)
        pid = "PY"
    else:
        pid = "PX"
    # 3yr x 3.2M = 9.6M: acceptable, but NOT a blow-away (< 1.30 * 9M = 11.7M).
    neg.submit_offer(pid, "AAA", years=3, annual_salary=3_200_000, sim_date="2025-03-01", data_dir=tmp_path)

    signed = {}
    sign_fn = lambda **k: signed.__setitem__("t", k["team_id"]) or True

    # A day before the player's patience day: still open, nobody signs.
    neg.process_negotiations(
        "2025-03-01", data_dir=tmp_path, sign_fn=sign_fn,
        players_by_id={pid: object()}, window_day=max(1, pat - 1), window_total=14,
    )
    assert "t" not in signed
    assert neg.has_open_negotiation(pid, data_dir=tmp_path)

    # On the patience day the acceptable leading offer signs.
    neg.process_negotiations(
        "2025-03-08", data_dir=tmp_path, sign_fn=sign_fn,
        players_by_id={pid: object()}, window_day=pat, window_total=14,
    )
    assert signed.get("t") == "AAA"


def test_blowaway_offer_signs_on_day_one(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    _fair(monkeypatch, 3_000_000, 3)  # fair total 9M
    # 3yr x 4M = 12M >= 1.30 * 9M = 11.7M -> blow-away, signs immediately.
    neg.submit_offer("PZ", "AAA", years=3, annual_salary=4_000_000, sim_date="2025-03-01", data_dir=tmp_path)
    signed = {}
    neg.process_negotiations(
        "2025-03-01", data_dir=tmp_path,
        sign_fn=lambda **k: signed.__setitem__("t", k["team_id"]) or True,
        players_by_id={"PZ": object()}, window_day=1, window_total=14,
    )
    assert signed.get("t") == "AAA"


def test_final_day_forces_resolution(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    _fair(monkeypatch, 3_000_000, 3)
    # A plain fair offer that never blows away and whose patience day is late:
    # the final window day must still sign it (best available offer).
    neg.submit_offer("PW", "AAA", years=2, annual_salary=2_000_000, sim_date="2025-03-01", data_dir=tmp_path)
    signed = {}
    neg.process_negotiations(
        "2025-03-14", data_dir=tmp_path,
        sign_fn=lambda **k: signed.__setitem__("t", k["team_id"]) or True,
        players_by_id={"PW": object()}, window_day=14, window_total=14,
    )
    assert signed.get("t") == "AAA"


# --- CPU seeding ------------------------------------------------------------

class _P:
    def __init__(self, pid):
        self.player_id = pid
        self.first_name = "F"
        self.last_name = pid


def test_seed_opens_windows_only_where_cpu_bids(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    _fair(monkeypatch, 2_000_000, 2)
    monkeypatch.setattr(
        "services.finance_ai.build_cpu_free_agent_bid_book",
        lambda p, teams, **k: {"CPU1": 4_000_000} if p.player_id == "P1" else {},
    )
    seeded = neg.seed_cpu_negotiations(
        "2025-03-01", [_P("P1"), _P("P2")], [object()], data_dir=tmp_path, top_n=10
    )
    assert seeded == 1
    assert neg.has_open_negotiation("P1", data_dir=tmp_path)
    # P2 (no CPU interest) must NOT get a dangling empty window.
    assert neg.get_negotiation("P2", data_dir=tmp_path) is None


# --- window lifecycle -------------------------------------------------------

def test_window_locks_sweep_until_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "finance_fa_enabled", lambda **k: True)
    state = w.open_window("2025-03-01", data_dir=tmp_path)
    assert state["status"] == "open" and state["day"] == 1
    assert w.unsigned_sweep_locked(data_dir=tmp_path) is True

    # Advancing the window one day at a time eventually closes it.
    for _ in range(w.TOTAL_DAYS):
        w.advance_day(data_dir=tmp_path)
    closed = w.load_window(data_dir=tmp_path)
    assert closed["status"] == "closed"
    assert w.unsigned_sweep_locked(data_dir=tmp_path) is False


def test_reopen_same_preseason_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "finance_fa_enabled", lambda **k: True)
    first = w.open_window("2025-03-01", data_dir=tmp_path)
    first["day"] = 5  # pretend some progress
    w._save_window(first, data_dir=tmp_path)
    again = w.open_window("2025-03-01", data_dir=tmp_path)
    assert again["day"] == 5  # not reset


def test_finance_off_never_locks(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "finance_fa_enabled", lambda **k: False)
    assert w.open_window("2025-03-01", data_dir=tmp_path) is None
    assert w.unsigned_sweep_locked(data_dir=tmp_path) is False
