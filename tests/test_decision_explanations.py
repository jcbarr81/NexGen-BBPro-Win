from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from services.decision_explanations import (
    append_decision_log,
    explanation,
    reason,
    summarize_decision_explanation,
)


def test_append_decision_log_writes_jsonl(tmp_path):
    payload = explanation(
        "trade_response",
        "rejected",
        actor="owner",
        team_id="AAA",
        subject_id="T-1",
        reasons=[reason("owner_response", "Owner rejected the proposal.")],
    )
    log_path = tmp_path / "decision_explanations.jsonl"
    written = append_decision_log(payload, path=log_path)

    assert written == log_path
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["decision_type"] == "trade_response"
    assert record["outcome"] == "rejected"
    assert record["team_id"] == "AAA"
    assert record["subject_id"] == "T-1"
    assert record["reasons"][0]["tag"] == "owner_response"


def test_lineup_autofill_sets_last_explanation(monkeypatch, tmp_path):
    from utils import lineup_autofill as lineup_mod

    players = []
    for idx, pos in enumerate(["C", "SS", "CF", "3B", "2B", "1B", "LF", "RF", "DH"], start=1):
        players.append(
            SimpleNamespace(
                player_id=f"P{idx}",
                first_name=f"F{idx}",
                last_name=f"L{idx}",
                is_pitcher=False,
                primary_position=pos if pos != "DH" else "LF",
                other_positions=[],
                ch=50 + idx,
                ph=50 + idx,
                sp=45 + idx,
                fa=45 + idx,
                arm=45 + idx,
            )
        )

    monkeypatch.setattr(lineup_mod, "resolve_app_path", lambda path: Path(path))
    monkeypatch.setattr(lineup_mod, "load_players_from_csv", lambda _path: players)
    monkeypatch.setattr(
        lineup_mod,
        "load_roster",
        lambda _team_id, _roster_root: SimpleNamespace(act=[p.player_id for p in players]),
    )
    monkeypatch.setattr(lineup_mod, "load_depth_chart", lambda _team_id: {})
    monkeypatch.setattr(lineup_mod, "should_persist_decision_logs", lambda: False)

    result = lineup_mod.auto_fill_lineup_for_team(
        "AAA",
        players_file=tmp_path / "players.csv",
        roster_dir=tmp_path / "rosters",
        lineup_dir=tmp_path / "lineups",
    )

    assert len(result) == 9
    payload = getattr(lineup_mod.auto_fill_lineup_for_team, "last_explanation", {})
    assert payload.get("decision_type") == "lineup_autofill"
    tags = {entry.get("tag") for entry in payload.get("reasons", [])}
    assert "coverage_first" in tags
    assert "depth_chart_preference" in tags
    assert "strategy_profile" in tags
    assert payload.get("context", {}).get("strategy_profile") == "balanced"


def test_bullpen_usage_order_sets_explanation(monkeypatch):
    from playbalance import game_runner

    class _Tracker:
        def bullpen_game_status(self, *_args, **_kwargs):
            return {
                "P1": {"available": True, "days_since_use": 3, "last_pitches": 14},
                "P2": {"available": False, "available_on": None, "last_pitches": 28},
                "P3": {"available": True, "days_since_use": 1, "last_pitches": 8},
            }

    monkeypatch.setattr(game_runner, "should_persist_decision_logs", lambda: False)
    state = SimpleNamespace(
        pitchers=[
            SimpleNamespace(player_id="SP1"),
            SimpleNamespace(player_id="P1"),
            SimpleNamespace(player_id="P2"),
            SimpleNamespace(player_id="P3"),
        ]
    )
    game_runner._apply_bullpen_usage_order(  # noqa: SLF001
        state,
        "AAA",
        _Tracker(),
        "2026-07-04",
        7,
        players_file="data/players.csv",
        roster_dir="data/rosters",
    )

    payload = getattr(state, "last_bullpen_decision_explanation", {})
    assert payload.get("decision_type") == "bullpen_usage_order"
    assert payload.get("outcome") == "reordered"
    tags = {entry.get("tag") for entry in payload.get("reasons", [])}
    assert "availability_gate" in tags
    assert "rest_priority" in tags


def test_summarize_decision_explanation_formats_reasons():
    payload = {
        "decision_type": "lineup_autofill",
        "outcome": "generated",
        "reasons": [
            {"tag": "coverage_first", "message": "Filled scarce positions first."},
            {"tag": "depth_chart_preference", "message": "Preferred depth chart order."},
            {"tag": "best_remaining_bat", "message": "Used hitter score fallback."},
            {"tag": "emergency_fill", "message": "Used emergency DH fill."},
        ],
    }

    summary = summarize_decision_explanation(payload, max_reasons=2)
    assert "Lineup Autofill Outcome: generated." in summary
    assert "Filled scarce positions first." in summary
    assert "Preferred depth chart order." in summary
    assert "+2 more reason(s)" in summary


def test_summarize_decision_explanation_fallback_for_missing_reasons():
    text = summarize_decision_explanation(
        {"decision_type": "lineup_autofill", "outcome": "generated"},
        fallback="No details",
    )
    assert text == "No details"


def test_summarize_decision_explanation_trade_response_rejection():
    payload = {
        "decision_type": "trade_response",
        "outcome": "rejected",
        "reasons": [
            {
                "tag": "owner_response",
                "message": "Owner explicitly rejected the incoming offer.",
            },
            {
                "tag": "roster_fit",
                "message": "Offer did not address current roster needs.",
            },
        ],
    }

    summary = summarize_decision_explanation(payload, max_reasons=2)
    assert "Trade Response Outcome: rejected." in summary
    assert "Owner explicitly rejected the incoming offer." in summary
    assert "Offer did not address current roster needs." in summary


def test_collect_bullpen_usage_reason_meta_compacts_entries():
    from playbalance import game_runner

    home_state = SimpleNamespace(
        last_bullpen_decision_explanation={
            "decision_type": "bullpen_usage_order",
            "outcome": "reordered",
            "reasons": [
                {
                    "tag": "availability_gate",
                    "message": "Unavailable pitchers moved behind available arms.",
                },
                {
                    "tag": "rest_priority",
                    "message": "Available relievers prioritized by rest/workload.",
                },
            ],
        }
    )
    away_state = SimpleNamespace(
        last_bullpen_decision_explanation={
            "decision_type": "bullpen_usage_order",
            "outcome": "reordered",
            "reasons": [
                {
                    "tag": "recovery_constraints",
                    "message": "Ordering respected readiness constraints.",
                }
            ],
        }
    )

    payload = game_runner._collect_bullpen_usage_reason_meta(  # noqa: SLF001
        "HME",
        home_state,
        "AWY",
        away_state,
    )

    assert "home" in payload and "away" in payload
    home_entry = payload["home"]
    away_entry = payload["away"]
    assert isinstance(home_entry, dict)
    assert isinstance(away_entry, dict)
    assert home_entry.get("team_id") == "HME"
    assert away_entry.get("team_id") == "AWY"
    assert "availability_gate" in home_entry.get("reason_tags", [])
    assert "recovery_constraints" in away_entry.get("reason_tags", [])
    assert "Outcome: reordered." in str(home_entry.get("summary") or "")
