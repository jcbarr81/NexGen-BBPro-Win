from __future__ import annotations

import json

from services.finance_settings import (
    apply_financial_preset,
    ensure_financial_defaults,
)
from services.qualifying_offers import (
    QO_VALUE,
    apply_draft_compensation,
    compensation_for_draft,
    list_team_qualifying_offers,
    load_qo_state,
    process_qualifying_offers,
    resolve_qualifying_offer,
    snapshot_qo_candidates,
    track_qo_signing,
)


def _enable_finance(data_dir) -> None:
    ensure_financial_defaults(data_dir=data_dir, league_id="t")
    apply_financial_preset(
        "mlb_like", path=data_dir / "league_financial_settings.json", league_id="t"
    )


def _write_contracts(data_dir, players) -> None:
    (data_dir / "contracts.json").write_text(
        json.dumps({"version": 1, "players": players}, indent=2), encoding="utf-8"
    )


def test_snapshot_captures_only_expiring_optionless_contracts(tmp_path):
    d = tmp_path
    _write_contracts(
        d,
        {
            "EXPIRING": {"team_id": "AAA", "years_left": 1, "annual_salary": 12_000_000, "service_time_days": 900},
            "MULTIYEAR": {"team_id": "AAA", "years_left": 3, "annual_salary": 10_000_000},
            "HAS_OPTION": {"team_id": "BBB", "years_left": 1, "annual_salary": 9_000_000, "options": [{"type": "team"}]},
        },
    )
    cands = snapshot_qo_candidates(data_dir=d)
    assert set(cands) == {"EXPIRING"}
    assert cands["EXPIRING"]["team_id"] == "AAA"
    # Snapshot credits the finished season (+172) toward service.
    assert cands["EXPIRING"]["service_time_days"] == 900 + 172


def test_process_tenders_accepts_and_declines(tmp_path):
    d = tmp_path
    _enable_finance(d)
    candidates = {
        # Full FA (>=1032 service), quality salary, at/under QO -> accepts.
        "ACCEPT": {"team_id": "AAA", "service_time_days": 1100, "salary": 15_000_000},
        # Full FA, expensive star (> QO) -> declines, bets on the market.
        "DECLINE": {"team_id": "AAA", "service_time_days": 1300, "salary": 28_000_000},
        # Not full FA yet -> ineligible, no QO.
        "YOUNG": {"team_id": "BBB", "service_time_days": 600, "salary": 10_000_000},
        # Quality too low -> ineligible.
        "FRINGE": {"team_id": "BBB", "service_time_days": 1300, "salary": 2_000_000},
    }
    result = process_qualifying_offers(2031, candidates=candidates, data_dir=d, league_id="t")
    assert result["applied"] is True
    assert result["tendered"] == 2
    assert result["accepted"] == 1
    assert result["declined"] == 1

    state = load_qo_state(2031, data_dir=d)
    assert set(state["players"]) == {"ACCEPT", "DECLINE"}
    assert state["players"]["ACCEPT"]["decision"] == "accepted"
    assert state["players"]["DECLINE"]["decision"] == "declined"

    # Accepted player got a one-year QO contract restored.
    contracts = json.loads((d / "contracts.json").read_text(encoding="utf-8"))
    assert contracts["players"]["ACCEPT"]["annual_salary"] == QO_VALUE
    assert contracts["players"]["ACCEPT"]["years_left"] == 1


def test_process_noop_when_finance_disabled(tmp_path):
    d = tmp_path  # no finance settings -> disabled
    result = process_qualifying_offers(
        2031,
        candidates={"X": {"team_id": "AAA", "service_time_days": 1300, "salary": 15_000_000}},
        data_dir=d,
        league_id="t",
    )
    assert result["applied"] is False


def test_track_signing_awards_comp_only_when_signed_elsewhere(tmp_path):
    d = tmp_path
    _enable_finance(d)
    process_qualifying_offers(
        2031,
        candidates={
            "STAR": {"team_id": "AAA", "service_time_days": 1300, "salary": 28_000_000},
            "MID": {"team_id": "CCC", "service_time_days": 1300, "salary": 26_000_000},
        },
        data_dir=d,
        league_id="t",
    )
    # Declined star signs with a different team -> AAA owed compensation.
    assert track_qo_signing("STAR", "BBB", year=2031, data_dir=d) is True
    # Re-signing the SAME team -> no compensation.
    assert track_qo_signing("MID", "CCC", year=2031, data_dir=d) is False

    state = load_qo_state(2031, data_dir=d)
    assert state["players"]["STAR"]["comp_awarded"] is True
    assert state["players"]["STAR"]["signed_with"] == "BBB"
    assert state["players"]["MID"]["comp_awarded"] is False


def test_owner_team_qo_is_pending_until_resolved(tmp_path):
    d = tmp_path
    _enable_finance(d)
    candidates = {
        "OWN_ACCEPT": {"team_id": "AAA", "service_time_days": 1100, "salary": 15_000_000},
        "OWN_DECLINE": {"team_id": "AAA", "service_time_days": 1300, "salary": 28_000_000},
        "CPU_STAR": {"team_id": "ZZZ", "service_time_days": 1300, "salary": 28_000_000},
    }
    res = process_qualifying_offers(
        2031, candidates=candidates, data_dir=d, league_id="t", owner_teams={"AAA"}
    )
    assert res["pending"] == 2  # AAA's two players await the owner
    assert res["declined"] == 1  # the CPU team auto-resolved

    offers = list_team_qualifying_offers("AAA", 2031, data_dir=d)
    assert {o["player_id"] for o in offers} == {"OWN_ACCEPT", "OWN_DECLINE"}
    assert all(o["decision"] == "pending" for o in offers)

    # Owner tenders the affordable vet -> he accepts and re-signs.
    r1 = resolve_qualifying_offer("AAA", "OWN_ACCEPT", 2031, tender=True, data_dir=d)
    assert r1["decision"] == "accepted"
    # Owner declines to tender the pricey star -> he walks, no compensation.
    r2 = resolve_qualifying_offer("AAA", "OWN_DECLINE", 2031, tender=False, data_dir=d)
    assert r2["decision"] == "not_tendered"
    assert track_qo_signing("OWN_DECLINE", "BBB", year=2031, data_dir=d) is False

    state = load_qo_state(2031, data_dir=d)
    assert state["players"]["OWN_ACCEPT"]["decision"] == "accepted"
    assert state["players"]["OWN_DECLINE"]["decision"] == "not_tendered"


def test_draft_compensation_moves_comp_team_ahead_of_signer(tmp_path):
    d = tmp_path
    _enable_finance(d)
    process_qualifying_offers(
        2031,
        candidates={"STAR": {"team_id": "AAA", "service_time_days": 1300, "salary": 28_000_000}},
        data_dir=d,
        league_id="t",
    )
    track_qo_signing("STAR", "BBB", year=2031, data_dir=d)

    comp = compensation_for_draft(2032, data_dir=d)
    assert comp["comp_teams"] == ["AAA"]
    assert comp["forfeit_teams"] == ["BBB"]

    # AAA currently drafts AFTER BBB; compensation moves AAA just ahead of BBB.
    order = ["BBB", "CCC", "AAA", "DDD"]
    new_order = apply_draft_compensation(order, 2032, data_dir=d)
    assert len(new_order) == len(order)
    assert set(new_order) == set(order)  # no added/removed picks
    assert new_order.index("AAA") < new_order.index("BBB")
