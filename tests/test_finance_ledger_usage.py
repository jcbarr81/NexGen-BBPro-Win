from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _source_text(relative_path: str) -> str:
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_contracts_service_uses_typed_buyout_event_helper():
    source = _source_text("services/contracts_service.py")
    assert "post_contract_buyout(" in source
    assert '"contract_buyout"' not in source
    assert "'contract_buyout'" not in source


def test_offseason_finance_flow_uses_typed_arb_award_event_helper():
    source = _source_text("services/offseason_finance_flow.py")
    assert "post_arb_award(" in source
    assert '"arb_award"' not in source
    assert "'arb_award'" not in source


def test_owner_finance_engine_uses_typed_finance_cycle_marker_helper():
    source = _source_text("services/owner_finance_engine.py")
    assert "build_finance_cycle_marker_row(" in source
    assert "build_team_revenue_row(" in source
    assert "build_team_expense_row(" in source
    assert '"finance_cycle"' not in source
    assert "'finance_cycle'" not in source
    assert '"__system__"' not in source
    assert "'__system__'" not in source
    assert '"revenue_"' not in source
    assert "'revenue_'" not in source
    assert '"expense_"' not in source
    assert "'expense_'" not in source
