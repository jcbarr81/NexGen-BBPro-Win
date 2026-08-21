"""Multi-day FA negotiation windows (#12): submit/withdraw offers, CPU bidding,
early accept on a blow-away offer, and deadline resolution to the best offer.
"""

from services import fa_negotiations as neg


class _Ev:
    def __init__(self, decision):
        self.decision = decision


def _accept_all(monkeypatch):
    monkeypatch.setattr(
        "services.contract_negotiator.evaluate_extension_offer",
        lambda p, **k: _Ev("accepted"),
    )


def test_submit_opens_window_with_14_day_deadline(tmp_path):
    n = neg.submit_offer(
        "P1", "AAA", years=3, annual_salary=5_000_000, sim_date="2025-06-01", data_dir=tmp_path
    )
    assert n["status"] == "open"
    assert n["deadline_date"] == "2025-06-15"  # opened + 14 days
    assert len(n["offers"]) == 1
    assert neg.has_open_negotiation("P1", data_dir=tmp_path)


def test_resubmit_replaces_same_team_offer(tmp_path):
    neg.submit_offer("P1", "AAA", years=3, annual_salary=5_000_000, sim_date="2025-06-01", data_dir=tmp_path)
    n = neg.submit_offer("P1", "AAA", years=4, annual_salary=6_000_000, sim_date="2025-06-02", data_dir=tmp_path)
    assert len(n["offers"]) == 1  # one active offer per team
    assert n["offers"][0]["annual_salary"] == 6_000_000


def test_withdraw_last_offer_closes_window(tmp_path):
    neg.submit_offer("P1", "AAA", years=3, annual_salary=5_000_000, sim_date="2025-06-01", data_dir=tmp_path)
    assert neg.withdraw_offer("P1", "AAA", data_dir=tmp_path) is True
    n = neg.get_negotiation("P1", data_dir=tmp_path)
    assert n["status"] == "resolved" and n["resolution"]["outcome"] == "withdrawn"


def test_resolve_at_deadline_signs_highest_value(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    neg.submit_offer("P1", "AAA", years=3, annual_salary=5_000_000, sim_date="2025-06-01", data_dir=tmp_path)
    neg.submit_offer("P1", "BBB", years=3, annual_salary=6_000_000, sim_date="2025-06-02", data_dir=tmp_path)
    signed = {}

    def sign_fn(*, team_id, player_id, offer, player):
        signed["team"] = team_id
        return True

    summary = neg.process_negotiations(
        "2025-06-15", data_dir=tmp_path, sign_fn=sign_fn, players_by_id={"P1": object()}
    )
    assert signed["team"] == "BBB"  # 18M total beats 15M
    assert len(summary["signed"]) == 1
    n = neg.get_negotiation("P1", data_dir=tmp_path)
    assert n["status"] == "resolved" and n["resolution"]["signed_team"] == "BBB"
    assert n["resolution"]["early"] is False


def test_before_deadline_no_resolution(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    neg.submit_offer("P1", "AAA", years=2, annual_salary=2_000_000, sim_date="2025-06-01", data_dir=tmp_path)
    summary = neg.process_negotiations(
        "2025-06-03", data_dir=tmp_path, sign_fn=lambda **k: True, players_by_id={"P1": object()}
    )
    assert summary["signed"] == []
    assert neg.has_open_negotiation("P1", data_dir=tmp_path)


def test_early_accept_on_blowaway_offer(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    monkeypatch.setattr("services.contract_negotiator.fair_market_salary", lambda p, **k: 3_000_000)
    monkeypatch.setattr("services.contract_negotiator.fair_market_years", lambda p, **k: 3)
    # fair-market total 9M; offer 3yr x 5M = 15M >= 1.15*9M -> signs early.
    neg.submit_offer("P1", "AAA", years=3, annual_salary=5_000_000, sim_date="2025-06-01", data_dir=tmp_path)
    signed = {}
    neg.process_negotiations(
        "2025-06-05",  # well before the 06-15 deadline
        data_dir=tmp_path,
        sign_fn=lambda **k: signed.__setitem__("t", k["team_id"]) or True,
        players_by_id={"P1": object()},
    )
    assert signed.get("t") == "AAA"
    assert neg.get_negotiation("P1", data_dir=tmp_path)["resolution"]["early"] is True


def test_cpu_teams_bid_during_window(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    monkeypatch.setattr(
        "services.finance_ai.build_cpu_free_agent_bid_book",
        lambda p, teams, **k: {"CPU1": 4_000_000, "CPU2": 3_000_000},
    )
    monkeypatch.setattr("services.contract_negotiator.fair_market_years", lambda p, **k: 2)
    neg.submit_offer("P1", "AAA", years=2, annual_salary=2_000_000, sim_date="2025-06-01", data_dir=tmp_path)
    summary = neg.process_negotiations(
        "2025-06-02", data_dir=tmp_path, players_by_id={"P1": object()}, teams=[object()]
    )
    assert summary["cpu_offers"] == 2
    tids = {o["team_id"] for o in neg.get_negotiation("P1", data_dir=tmp_path)["offers"]}
    assert {"CPU1", "CPU2"}.issubset(tids)


def test_no_acceptable_offer_closes_no_deal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.contract_negotiator.evaluate_extension_offer",
        lambda p, **k: _Ev("rejected"),
    )
    neg.submit_offer("P1", "AAA", years=1, annual_salary=800_000, sim_date="2025-06-01", data_dir=tmp_path)
    summary = neg.process_negotiations(
        "2025-06-15", data_dir=tmp_path, sign_fn=lambda **k: True, players_by_id={"P1": object()}
    )
    assert summary["no_deal"] == ["P1"]
    assert neg.get_negotiation("P1", data_dir=tmp_path)["resolution"]["outcome"] == "no_deal"
