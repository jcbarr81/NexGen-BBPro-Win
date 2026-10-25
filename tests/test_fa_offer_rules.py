"""Free-agent offers under rules 2 (8.6.0): an asking price above a hidden
minimum, as in extension talks; no accept/reject preview; a negotiation
keeps the rules it opened under, and a window opened before 8.6.0 keeps
rules 1 for its whole run.
"""

from __future__ import annotations

import json

import pytest

from tests.test_r812_free_agency_fixes import _player, _point_router_at, league  # noqa: F401

OWNER = {"r": "owner", "t": "AAA"}


def _terms(league_dir, years):
    from services.extension_talks import fa_terms

    return fa_terms(_player(league_dir, "P800"), "P800", years=years)


def test_preview_shows_his_ask_and_never_an_answer(league, monkeypatch):
    router, _ = _point_router_at(monkeypatch, league)
    monkeypatch.setattr(router, "_competing_bids", lambda *a, **k: [])
    out = router.evaluate_fa_offer("P800", {"years": 2, "annual_salary": 900_000}, OWNER)
    assert out["rules"] == 2
    assert out["ask_salary"] == _terms(league, 2)["ask"]
    for leak in ("decision", "fair_market_salary", "counter_salary", "reason"):
        assert leak not in out


def test_his_ask_signs_him_and_a_short_offer_gets_his_ask_back(league, monkeypatch):
    from fastapi import HTTPException

    router, signed = _point_router_at(monkeypatch, league)
    terms = _terms(league, 2)
    assert terms["ask"] > terms["minimum"]
    with pytest.raises(HTTPException) as exc:
        router.sign_free_agent(
            "AAA", {"player_id": "P800", "level": "ACT", "years": 2,
                    "annual_salary": int(terms["minimum"]) - 50_000}, OWNER)
    assert exc.value.status_code == 409 and exc.value.detail["code"] == "countered"
    neg = exc.value.detail["negotiation"]
    assert neg["counter_salary"] == terms["ask"]  # never the minimum
    out = router.sign_free_agent(
        "AAA", {"player_id": "P800", "level": "ACT", "years": 2}, OWNER)
    assert out["signed"] is True and out["annual_salary"] == terms["ask"]


def test_an_offer_at_his_minimum_is_acceptable_in_the_auction(league):
    from services.fa_negotiations import _player_accepts

    player = _player(league, "P800")
    terms = _terms(league, 2)
    at_min = {"years": 2, "annual_salary": int(terms["minimum"]) + 1}
    under = {"years": 2, "annual_salary": int(terms["minimum"]) - 50_000}
    assert _player_accepts(at_min, player, rules=2)
    assert not _player_accepts(under, player, rules=2)


def test_a_window_opened_before_rules_2_keeps_rules_1(league):
    from services import fa_negotiations as neg

    # No window: rules 2.
    assert neg.current_offer_rules(data_dir=league) == 2
    # alpha-test's window of 2026-10: open, with no offer_rules stamp.
    (league / "fa_window.json").write_text(json.dumps(
        {"status": "open", "day": 5, "total_days": 14, "start_date": "2026-10-18"}),
        encoding="utf-8")
    assert neg.current_offer_rules(data_dir=league) == 1
    opened = neg.submit_offer("P800", "AAA", years=2, annual_salary=5_000_000,
                              sim_date="2026-10-22", data_dir=league)
    assert opened["rules"] == 1
    # A window opened under 8.6.0 is stamped with rules 2.
    (league / "fa_window.json").write_text(json.dumps(
        {"status": "open", "offer_rules": 2, "day": 1}), encoding="utf-8")
    assert neg.current_offer_rules(data_dir=league) == 2
    # The negotiation keeps the rules it opened under.
    assert neg.offer_rules_for("P800", data_dir=league) == 1


def test_an_unreadable_window_file_reads_as_rules_1(league):
    from services import fa_negotiations as neg

    (league / "fa_window.json").write_text("{half-writ", encoding="utf-8")
    assert neg.current_offer_rules(data_dir=league) == 1


def test_early_signing_looks_at_the_best_acceptable_offer(league, monkeypatch):
    from services import fa_negotiations as neg

    player = _player(league, "P800")
    terms = _terms(league, 2)
    # The biggest total is a long offer below his minimum; a shorter one is
    # acceptable. On his patience day the acceptable one signs.
    neg.save_negotiations({"version": 1, "negotiations": {"P800": {
        "player_id": "P800", "rules": 2, "status": "open", "opened_day": 1,
        "opened_date": "2027-11-01", "deadline_date": "2027-11-15",
        "offers": [
            {"team_id": "CPU1", "years": 6, "is_cpu": False,
             "annual_salary": int(terms["minimum"] * 0.7)},
            {"team_id": "AAA", "years": 2, "is_cpu": False,
             "annual_salary": int(terms["ask"])},
        ]}}}, data_dir=league)
    monkeypatch.setattr(neg, "_window_patience", lambda pid, total: 1)
    signed = []
    out = neg.process_negotiations(
        "2027-11-03", data_dir=league, players_by_id={"P800": player}, teams=[],
        sign_fn=lambda **kw: signed.append(kw["team_id"]) or True,
        window_day=3, window_total=14,
    )
    assert signed == ["AAA"] and out["signed"][0]["signed_team"] == "AAA"
