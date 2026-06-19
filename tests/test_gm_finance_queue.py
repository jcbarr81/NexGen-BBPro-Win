from __future__ import annotations

from types import SimpleNamespace

from services import gm_finance_queue
from services.contracts_service import load_contracts_payload
from services.finance_settings import ensure_financial_defaults, update_financial_settings
from utils.league_settings import configure_league_settings


def _configure_finance_modules(data_dir, *, gm_arbitration: str, gm_free_agency: str):
    settings_path = data_dir / "league_financial_settings.json"
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    update_financial_settings(
        enabled=True,
        preset="custom",
        modules={
            "gm_contracts": "basic",
            "gm_arbitration": gm_arbitration,
            "gm_free_agency": gm_free_agency,
            "gm_finance_ai": "basic",
            "gm_payroll_rules": "basic",
            "owner_revenue": "basic",
            "owner_expenses": "basic",
            "owner_budgets": "basic",
        },
        path=settings_path,
        league_id="alpha",
    )


def test_arbitration_queue_and_recommended_decisions(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_finance_modules(
        data_dir,
        gm_arbitration="basic",
        gm_free_agency="off",
    )

    contracts_path = data_dir / "contracts.json"
    contracts_path.write_text(
        """{
  "version": 1,
  "players": {
    "P_ARB": {
      "team_id": "T1",
      "years_left": 1,
      "annual_salary": 5000000,
      "service_time_days": 520,
      "arb_eligible": true,
      "fa_year": 2028,
      "options": []
    },
    "P_NOT": {
      "team_id": "T1",
      "years_left": 2,
      "annual_salary": 3000000,
      "service_time_days": 300,
      "arb_eligible": false,
      "fa_year": 2029,
      "options": []
    }
  }
}
""",
        encoding="utf-8",
    )

    queue = gm_finance_queue.build_arbitration_queue(
        "T1",
        data_dir=data_dir,
        league_id="alpha",
    )
    assert len(queue) == 1
    assert queue[0]["player_id"] == "P_ARB"
    assert queue[0]["recommended_action"] in {
        "offer_raise",
        "hold",
        "non_tender",
    }

    result = gm_finance_queue.apply_recommended_arbitration_decisions(
        "T1",
        data_dir=data_dir,
    )
    assert result["queued_count"] == 1

    decisions = gm_finance_queue.list_team_queue_decisions(
        "T1",
        queue_type="arbitration",
        data_dir=data_dir,
    )
    assert len(decisions) == 1
    assert decisions[0]["item_id"] == "P_ARB"
    assert decisions[0]["review_status"] == "approved_local"
    assert result["review_status"] == "approved_local"


def test_free_agency_queue_and_recommended_targets(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_finance_modules(
        data_dir,
        gm_arbitration="off",
        gm_free_agency="basic",
    )

    fake_players = [
        SimpleNamespace(
            player_id="FA1",
            first_name="A",
            last_name="Star",
            primary_position="SS",
            birthdate="2001-01-01",
            ch=78,
            ph=76,
            sp=70,
            eye=74,
            fa=68,
            arm=72,
            is_pitcher=False,
        ),
        SimpleNamespace(
            player_id="FA2",
            first_name="B",
            last_name="Depth",
            primary_position="OF",
            birthdate="1998-01-01",
            ch=58,
            ph=57,
            sp=60,
            eye=55,
            fa=54,
            arm=56,
            is_pitcher=False,
        ),
    ]
    monkeypatch.setattr(
        gm_finance_queue,
        "list_unsigned_players_from_files",
        lambda data_dir=None: list(fake_players),
    )

    queue = gm_finance_queue.build_free_agency_queue("T1", data_dir=data_dir, limit=10)
    assert len(queue) == 2
    assert {row["player_id"] for row in queue} == {"FA1", "FA2"}
    assert all(
        row["recommended_action"] in {"target", "monitor", "pass"}
        for row in queue
    )

    result = gm_finance_queue.apply_recommended_free_agency_targets(
        "T1",
        data_dir=data_dir,
        limit=1,
    )
    assert result["queued_count"] == 1

    decisions = gm_finance_queue.list_team_queue_decisions(
        "T1",
        queue_type="free_agency",
        data_dir=data_dir,
    )
    assert len(decisions) == 1
    assert decisions[0]["action"] in {"target", "monitor", "pass"}
    assert decisions[0]["review_status"] == "approved_local"
    assert result["review_status"] == "approved_local"


def test_queue_respects_disabled_modules(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")

    assert gm_finance_queue.build_arbitration_queue("T1", data_dir=data_dir) == []
    assert gm_finance_queue.build_free_agency_queue("T1", data_dir=data_dir) == []


def test_advanced_arbitration_queue_includes_super_two_service_time(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_finance_modules(
        data_dir,
        gm_arbitration="advanced",
        gm_free_agency="off",
    )
    (data_dir / "contracts.json").write_text(
        """{
  "version": 1,
  "players": {
    "P_SUPER2": {
      "team_id": "T1",
      "years_left": 2,
      "annual_salary": 3500000,
      "service_time_days": 470,
      "arb_eligible": false,
      "fa_year": 2029,
      "options": []
    }
  }
}
""",
        encoding="utf-8",
    )

    queue = gm_finance_queue.build_arbitration_queue("T1", data_dir=data_dir)
    assert len(queue) == 1
    assert queue[0]["player_id"] == "P_SUPER2"

    _configure_finance_modules(
        data_dir,
        gm_arbitration="basic",
        gm_free_agency="off",
    )
    basic_queue = gm_finance_queue.build_arbitration_queue(
        "T1",
        data_dir=data_dir,
        league_id="alpha",
    )
    assert basic_queue == []


def test_queue_marks_pending_review_in_multi_owner_mode(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_finance_modules(
        data_dir,
        gm_arbitration="basic",
        gm_free_agency="off",
    )
    configure_league_settings(
        mode="owner_league",
        commissioner_password="secret",
        path=data_dir / "league_settings.json",
    )
    (data_dir / "contracts.json").write_text(
        """{
  "version": 1,
  "players": {
    "P_ARB": {
      "team_id": "T1",
      "years_left": 1,
      "annual_salary": 5000000,
      "service_time_days": 520,
      "arb_eligible": true,
      "fa_year": 2028,
      "options": []
    }
  }
}
""",
        encoding="utf-8",
    )

    result = gm_finance_queue.apply_recommended_arbitration_decisions(
        "T1",
        data_dir=data_dir,
    )
    decisions = gm_finance_queue.list_team_queue_decisions(
        "T1",
        queue_type="arbitration",
        data_dir=data_dir,
    )
    assert result["review_status"] == "pending_commissioner"
    assert decisions[0]["review_status"] == "pending_commissioner"
    pending = gm_finance_queue.list_pending_queue_decisions(data_dir=data_dir)
    assert len(pending) == 1
    assert pending[0]["team_id"] == "T1"

    updated = gm_finance_queue.set_queue_review_status(
        "T1",
        queue_type="arbitration",
        item_id="P_ARB",
        review_status="approved_commissioner",
        data_dir=data_dir,
    )
    assert updated is not None
    assert updated["review_status"] == "approved_commissioner"
    assert gm_finance_queue.list_pending_queue_decisions(data_dir=data_dir) == []


def test_apply_approved_queue_decisions_mixed_contract_updates(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_finance_modules(
        data_dir,
        gm_arbitration="basic",
        gm_free_agency="off",
    )
    (data_dir / "contracts.json").write_text(
        """{
  "version": 1,
  "players": {
    "P_RAISE": {
      "team_id": "T1",
      "years_left": 1,
      "annual_salary": 5000000,
      "service_time_days": 520,
      "arb_eligible": true,
      "fa_year": 2028,
      "options": []
    },
    "P_NONTENDER": {
      "team_id": "T1",
      "years_left": 1,
      "annual_salary": 4000000,
      "service_time_days": 520,
      "arb_eligible": true,
      "fa_year": 2028,
      "options": []
    }
  }
}
""",
        encoding="utf-8",
    )
    gm_finance_queue.save_team_queue_decision(
        "T1",
        queue_type="arbitration",
        item_id="P_RAISE",
        action="offer_raise",
        review_status="approved_commissioner",
        payload={"projected_salary": 6200000},
        data_dir=data_dir,
    )
    gm_finance_queue.save_team_queue_decision(
        "T1",
        queue_type="arbitration",
        item_id="P_NONTENDER",
        action="non_tender",
        review_status="approved_commissioner",
        payload={},
        data_dir=data_dir,
    )

    summary = gm_finance_queue.apply_approved_queue_decisions(
        team_id="T1",
        queue_type="arbitration",
        data_dir=data_dir,
    )
    assert summary["applied"] == 2
    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players") or {}
    assert players["P_RAISE"]["annual_salary"] == 6200000
    assert "P_NONTENDER" not in players

    decisions = gm_finance_queue.list_team_queue_decisions(
        "T1",
        queue_type="arbitration",
        data_dir=data_dir,
    )
    by_id = {row["item_id"]: row for row in decisions}
    assert by_id["P_RAISE"]["applied"] is True
    assert by_id["P_RAISE"]["payload"]["execution"] == "salary_updated"
    assert by_id["P_NONTENDER"]["applied"] is True
    assert by_id["P_NONTENDER"]["payload"]["execution"] == "non_tendered"


def test_apply_approved_queue_decisions_free_agency_target_signs_contract(
    tmp_path,
    monkeypatch,
):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_finance_modules(
        data_dir,
        gm_arbitration="off",
        gm_free_agency="basic",
    )
    gm_finance_queue.save_team_queue_decision(
        "T1",
        queue_type="free_agency",
        item_id="FA1",
        action="target",
        review_status="approved_commissioner",
        payload={"suggested_offer": 2750000},
        data_dir=data_dir,
    )
    monkeypatch.setattr(
        gm_finance_queue,
        "list_unsigned_players_from_files",
        lambda data_dir=None: [SimpleNamespace(player_id="FA1")],
    )
    monkeypatch.setattr(
        gm_finance_queue,
        "_add_player_to_team_roster",
        lambda team_id, player_id, data_dir=None: "ACT",
    )

    summary = gm_finance_queue.apply_approved_queue_decisions(
        team_id="T1",
        queue_type="free_agency",
        data_dir=data_dir,
    )
    assert summary["applied"] == 1
    players = load_contracts_payload(data_dir=data_dir).get("players") or {}
    assert players["FA1"]["team_id"] == "T1"
    assert players["FA1"]["annual_salary"] == 2750000

    decisions = gm_finance_queue.list_team_queue_decisions(
        "T1",
        queue_type="free_agency",
        data_dir=data_dir,
    )
    assert decisions[0]["applied"] is True
    assert decisions[0]["payload"]["execution"] == "signed"


def test_apply_approved_queue_decisions_applies_arbitration_raise_over_threshold(
    tmp_path,
):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_finance_modules(
        data_dir,
        gm_arbitration="basic",
        gm_free_agency="off",
    )
    update_financial_settings(
        modules={
            "gm_payroll_rules": "mlb_like",
            "gm_roster_cost_enforcement": "block",
        },
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "contracts.json").write_text(
        """{
  "version": 1,
  "players": {
    "P_RAISE": {
      "team_id": "T1",
      "years_left": 1,
      "annual_salary": 230000000,
      "service_time_days": 620,
      "arb_eligible": true,
      "fa_year": 2028,
      "options": []
    }
  }
}
""",
        encoding="utf-8",
    )
    gm_finance_queue.save_team_queue_decision(
        "T1",
        queue_type="arbitration",
        item_id="P_RAISE",
        action="offer_raise",
        review_status="approved_commissioner",
        payload={"projected_salary": 260000000},
        data_dir=data_dir,
    )

    summary = gm_finance_queue.apply_approved_queue_decisions(
        team_id="T1",
        queue_type="arbitration",
        data_dir=data_dir,
    )
    # Hybrid model: over-threshold arbitration raises are no longer blocked in
    # the offseason — they apply, and the over-threshold cost settles as tax.
    assert summary["applied"] == 1
    assert summary["skipped"] == 0
    players = load_contracts_payload(data_dir=data_dir).get("players") or {}
    assert players["P_RAISE"]["annual_salary"] == 260000000
    decisions = gm_finance_queue.list_team_queue_decisions(
        "T1",
        queue_type="arbitration",
        data_dir=data_dir,
    )
    assert decisions[0]["payload"].get("execution") != "policy_blocked"


def test_apply_approved_queue_decisions_applies_fa_target_over_threshold(
    tmp_path,
    monkeypatch,
):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_finance_modules(
        data_dir,
        gm_arbitration="off",
        gm_free_agency="basic",
    )
    update_financial_settings(
        modules={
            "gm_payroll_rules": "mlb_like",
            "gm_roster_cost_enforcement": "block",
        },
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )
    (data_dir / "contracts.json").write_text(
        """{
  "version": 1,
  "players": {
    "P_BIG": {
      "team_id": "T1",
      "years_left": 2,
      "annual_salary": 250000000,
      "service_time_days": 500,
      "arb_eligible": false,
      "fa_year": 2029,
      "options": []
    }
  }
}
""",
        encoding="utf-8",
    )
    gm_finance_queue.save_team_queue_decision(
        "T1",
        queue_type="free_agency",
        item_id="FA1",
        action="target",
        review_status="approved_commissioner",
        payload={"suggested_offer": 3000000},
        data_dir=data_dir,
    )
    monkeypatch.setattr(
        gm_finance_queue,
        "list_unsigned_players_from_files",
        lambda data_dir=None: [SimpleNamespace(player_id="FA1")],
    )
    monkeypatch.setattr(
        gm_finance_queue,
        "_add_player_to_team_roster",
        lambda team_id, player_id, data_dir=None: "ACT",
    )

    summary = gm_finance_queue.apply_approved_queue_decisions(
        team_id="T1",
        queue_type="free_agency",
        data_dir=data_dir,
    )
    # Hybrid model: over-threshold FA targets apply in the offseason (taxed),
    # not blocked.
    assert summary["applied"] == 1
    assert summary["skipped"] == 0
    decisions = gm_finance_queue.list_team_queue_decisions(
        "T1",
        queue_type="free_agency",
        data_dir=data_dir,
    )
    assert decisions[0]["payload"].get("execution") != "policy_blocked"


def test_summarize_queue_decisions_counts_by_status(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    gm_finance_queue.save_team_queue_decision(
        "T1",
        queue_type="arbitration",
        item_id="P1",
        action="hold",
        review_status="pending_commissioner",
        payload={},
        data_dir=data_dir,
    )
    gm_finance_queue.save_team_queue_decision(
        "T1",
        queue_type="arbitration",
        item_id="P2",
        action="hold",
        review_status="approved_commissioner",
        payload={},
        data_dir=data_dir,
    )
    gm_finance_queue.save_team_queue_decision(
        "T1",
        queue_type="free_agency",
        item_id="P3",
        action="monitor",
        review_status="approved_local",
        payload={"applied": True},
        data_dir=data_dir,
    )
    gm_finance_queue.save_team_queue_decision(
        "T2",
        queue_type="free_agency",
        item_id="P4",
        action="pass",
        review_status="rejected_commissioner",
        payload={},
        data_dir=data_dir,
    )

    summary = gm_finance_queue.summarize_queue_decisions(data_dir=data_dir)
    assert summary["total"] == 4
    assert summary["pending"] == 1
    assert summary["approved"] == 2
    assert summary["approved_unapplied"] == 1
    assert summary["approved_applied"] == 1
    assert summary["rejected"] == 1

    team_summary = gm_finance_queue.summarize_queue_decisions(
        data_dir=data_dir,
        team_id="T1",
    )
    assert team_summary["total"] == 3
    assert team_summary["rejected"] == 0


def test_list_queue_decisions_orders_pending_first(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    gm_finance_queue.save_team_queue_decision(
        "T1",
        queue_type="arbitration",
        item_id="P1",
        action="hold",
        review_status="approved_commissioner",
        payload={},
        data_dir=data_dir,
    )
    gm_finance_queue.save_team_queue_decision(
        "T2",
        queue_type="free_agency",
        item_id="P2",
        action="monitor",
        review_status="pending_commissioner",
        payload={},
        data_dir=data_dir,
    )
    gm_finance_queue.save_team_queue_decision(
        "T1",
        queue_type="free_agency",
        item_id="P3",
        action="pass",
        review_status="rejected_commissioner",
        payload={},
        data_dir=data_dir,
    )

    rows = gm_finance_queue.list_queue_decisions(data_dir=data_dir)
    assert len(rows) == 3
    assert rows[0]["review_status"] == "pending_commissioner"

    filtered = gm_finance_queue.list_queue_decisions(
        data_dir=data_dir,
        review_status="approved_commissioner",
    )
    assert len(filtered) == 1
    assert filtered[0]["item_id"] == "P1"
