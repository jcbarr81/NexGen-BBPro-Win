from __future__ import annotations

from types import SimpleNamespace

import services.league_command_center as command_center


def _card_map(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    cards = payload.get("cards", [])
    if not isinstance(cards, list):
        return {}
    mapped: dict[str, dict[str, object]] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        mapped[str(card.get("card_id") or "")] = card
    return mapped


def test_build_command_center_snapshot_aggregates_attention_items(monkeypatch):
    monkeypatch.setattr(command_center, "_resolve_phase", lambda _data_dir: "REGULAR_SEASON")
    monkeypatch.setattr(command_center, "_resolve_current_sim_date", lambda _data_dir: "2026-07-20")
    monkeypatch.setattr(
        command_center,
        "build_commissioner_projection_report",
        lambda **_: {
            "league_id": "alpha",
            "offseason": {
                "can_run_now": True,
                "next_stage_label": "Review Contract Expirations",
            },
        },
    )
    monkeypatch.setattr(
        command_center,
        "build_finance_alerts",
        lambda **_: [
            {
                "severity": "critical",
                "title": "AAA: Cashflow Risk",
                "message": "Cash trend negative.",
                "next_step": "Reduce payroll.",
            },
            {
                "severity": "warning",
                "title": "BBB: Near Threshold",
                "message": "Near threshold.",
                "next_step": "Review queue.",
            },
        ],
    )
    monkeypatch.setattr(
        command_center,
        "load_players_from_csv",
        lambda _path: [
            SimpleNamespace(player_id="P1", injured=True, injury_list="", team_id="AAA"),
            SimpleNamespace(player_id="P2", injured=False, injury_list="dl15", team_id="BBB"),
            SimpleNamespace(player_id="P3", injured=False, injury_list="", team_id="BBB"),
        ],
    )
    monkeypatch.setattr(
        command_center,
        "load_trades",
        lambda _path: [
            SimpleNamespace(status="pending"),
            SimpleNamespace(status="owner_accepted"),
            SimpleNamespace(status="accepted"),
        ],
    )
    monkeypatch.setattr(
        command_center,
        "list_requests",
        lambda **_: [{"request_id": "R1"}, {"request_id": "R2"}],
    )
    monkeypatch.setattr(
        command_center,
        "summarize_queue_decisions",
        lambda **_: {"pending": 1, "approved_unapplied": 1},
    )
    monkeypatch.setattr(
        command_center,
        "load_teams",
        lambda _path: [SimpleNamespace(team_id="AAA"), SimpleNamespace(team_id="BBB")],
    )
    monkeypatch.setattr(
        command_center,
        "load_roster",
        lambda team_id, _root: SimpleNamespace(team_id=team_id, act=["P1", "P2"]),
    )
    monkeypatch.setattr(
        command_center,
        "missing_positions",
        lambda roster, _players: ["SS"] if getattr(roster, "team_id", "") == "BBB" else [],
    )

    payload = command_center.build_league_command_center_snapshot()
    cards = _card_map(payload)

    assert payload["league_id"] == "alpha"
    assert payload["phase"] == "REGULAR_SEASON"
    assert payload["sim_date"] == "2026-07-20"
    assert cards["injuries"]["count"] == 2
    assert cards["pending_approvals"]["count"] == 6  # 2 trades + 2 CR + 2 GM queue
    assert cards["roster_conflicts"]["count"] == 1
    assert cards["deadlines"]["count"] >= 2
    assert cards["deadlines"]["severity"] == "warning"
    assert "Open Offseason Finance Workflow" in cards["deadlines"]["actions"]
    assert any(
        str(item.get("label") or "") == "Trade Deadline"
        and str(item.get("status") or "") in {"near", "urgent", "today"}
        for item in cards["deadlines"]["items"]
        if isinstance(item, dict)
    )
    assert cards["finance_risks"]["count"] == 2
    assert cards["finance_risks"]["severity"] == "critical"
    assert "Open Finance Hub" in cards["finance_risks"]["actions"]

    overview = payload.get("overview", {})
    assert isinstance(overview, dict)
    assert int(overview.get("total_attention_items", 0)) >= 12


def test_build_command_center_snapshot_returns_info_when_clean(monkeypatch):
    monkeypatch.setattr(command_center, "_resolve_phase", lambda _data_dir: "PRESEASON")
    monkeypatch.setattr(command_center, "_resolve_current_sim_date", lambda _data_dir: "2026-04-01")
    monkeypatch.setattr(
        command_center,
        "build_commissioner_projection_report",
        lambda **_: {"league_id": "alpha", "offseason": {"can_run_now": False}},
    )
    monkeypatch.setattr(
        command_center,
        "build_finance_alerts",
        lambda **_: [
            {
                "severity": "info",
                "title": "No Immediate Finance Alerts",
                "message": "No issues.",
                "next_step": "None",
            }
        ],
    )
    monkeypatch.setattr(command_center, "load_players_from_csv", lambda _path: [])
    monkeypatch.setattr(command_center, "load_trades", lambda _path: [])
    monkeypatch.setattr(command_center, "list_requests", lambda **_: [])
    monkeypatch.setattr(
        command_center,
        "summarize_queue_decisions",
        lambda **_: {"pending": 0, "approved_unapplied": 0},
    )
    monkeypatch.setattr(command_center, "load_teams", lambda _path: [])
    monkeypatch.setattr(command_center, "load_roster", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(command_center, "missing_positions", lambda *_args, **_kwargs: [])

    payload = command_center.build_league_command_center_snapshot()
    cards = _card_map(payload)

    assert cards["injuries"]["severity"] == "info"
    assert cards["pending_approvals"]["severity"] == "info"
    assert cards["roster_conflicts"]["severity"] == "info"
    assert cards["deadlines"]["severity"] == "info"
    assert cards["finance_risks"]["severity"] == "info"
    assert cards["finance_risks"]["count"] == 0


def test_build_command_center_snapshot_deadlines_include_finance_workload(monkeypatch):
    monkeypatch.setattr(command_center, "_resolve_phase", lambda _data_dir: "OFFSEASON")
    monkeypatch.setattr(
        command_center, "_resolve_current_sim_date", lambda _data_dir: "2026-08-05"
    )
    monkeypatch.setattr(command_center, "_is_draft_completed", lambda *_: True)
    monkeypatch.setattr(
        command_center,
        "build_commissioner_projection_report",
        lambda **_: {
            "league_id": "alpha",
            "modules": {
                "gm_arbitration": "advanced",
                "gm_free_agency": "advanced",
            },
            "offseason": {
                "can_run_now": True,
                "next_stage_label": "Review Contract Expirations",
                "arbitration_candidates": 3,
                "unsigned_players": 12,
            },
        },
    )
    monkeypatch.setattr(
        command_center,
        "build_finance_alerts",
        lambda **_: [
            {
                "severity": "info",
                "title": "No Immediate Finance Alerts",
                "message": "No issues.",
                "next_step": "None",
            }
        ],
    )
    monkeypatch.setattr(command_center, "load_players_from_csv", lambda _path: [])
    monkeypatch.setattr(command_center, "load_trades", lambda _path: [])
    monkeypatch.setattr(command_center, "list_requests", lambda **_: [])
    monkeypatch.setattr(
        command_center,
        "summarize_queue_decisions",
        lambda **_: {"pending": 0, "approved_unapplied": 0},
    )
    monkeypatch.setattr(command_center, "load_teams", lambda _path: [])
    monkeypatch.setattr(command_center, "load_roster", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(command_center, "missing_positions", lambda *_args, **_kwargs: [])

    payload = command_center.build_league_command_center_snapshot()
    cards = _card_map(payload)

    deadlines = cards["deadlines"]
    items = [item for item in deadlines["items"] if isinstance(item, dict)]
    labels = {str(item.get("label") or "") for item in items}

    assert deadlines["severity"] == "warning"
    assert deadlines["count"] >= 3
    assert "Offseason Finance Workflow" in labels
    assert "Arbitration Decisions" in labels
    assert "Free-Agency Market" in labels
