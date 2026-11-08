"""The offer dialog's "Competing bids" lists the real CPU offers when there are some (8.13.0).

During the bidding window the CPU clubs' offers are on file from day one, but
the dialog showed a fresh prediction instead: the same amounts, paired with
other clubs (found on the demo league: DEN / ELP / MEM shown, DEN / OKL / SAN
actually bidding). The real offers win; other owners' offers are never listed;
with no CPU offer on file the prediction still runs.
"""

from __future__ import annotations

from types import SimpleNamespace

from api.routers import free_agency as fa


def _negotiation(monkeypatch, negotiation):
    import services.fa_negotiations as neg

    monkeypatch.setattr(neg, "get_negotiation", lambda pid, data_dir=None: negotiation)


def _offer(team, salary, *, cpu=True, years=4):
    return {"team_id": team, "annual_salary": salary, "years": years, "is_cpu": cpu}


PLAYER = SimpleNamespace(player_id="P4149")


def test_real_cpu_offers_are_listed_by_salary(monkeypatch):
    _negotiation(monkeypatch, {
        "status": "open",
        "offers": [_offer("SAN", 5_917_524), _offer("DEN", 6_118_339), _offer("OKL", 5_958_806)],
    })
    monkeypatch.setattr("services.finance_ai.build_cpu_free_agent_bid_book",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no prediction")))
    rows = fa._competing_bids(PLAYER, exclude_team_id="WAS")
    assert [r["team_id"] for r in rows] == ["DEN", "OKL", "SAN"]
    assert rows[0]["salary"] == 6_118_339 and rows[0]["years"] == 4


def test_owners_offers_and_the_callers_own_are_left_out(monkeypatch):
    _negotiation(monkeypatch, {
        "status": "open",
        "offers": [
            _offer("CHI", 9_000_000, cpu=False),
            _offer("WAS", 8_000_000, cpu=True),
            _offer("DEN", 6_000_000),
        ],
    })
    rows = fa._competing_bids(PLAYER, exclude_team_id="WAS")
    assert [r["team_id"] for r in rows] == ["DEN"]


def test_the_list_keeps_its_limit(monkeypatch):
    _negotiation(monkeypatch, {
        "status": "open",
        "offers": [_offer(t, 5_000_000 + i) for i, t in enumerate(["A", "B", "C", "D", "E"])],
    })
    assert len(fa._competing_bids(PLAYER)) == 3


def test_without_cpu_offers_on_file_the_prediction_runs(monkeypatch):
    for negotiation in (None, {"status": "signed", "offers": [_offer("DEN", 6_000_000)]},
                        {"status": "open", "offers": [_offer("CHI", 9_000_000, cpu=False)]}):
        _negotiation(monkeypatch, negotiation)
        assert fa._open_cpu_offers(PLAYER) == []
