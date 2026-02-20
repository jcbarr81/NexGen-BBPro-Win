from __future__ import annotations

from ui.admin_dashboard.pages.home import (
    _build_overview_values,
    _format_gm_queue_status,
)


def test_build_overview_values_includes_gm_queue_metric():
    values = _build_overview_values(
        {
            "pending_trades": 4,
            "gm_queue_pending": 2,
            "teams": 30,
            "players": 1200,
            "season_phase": "OFFSEASON",
        }
    )
    assert values["Pending Trades"] == "4"
    assert values["Pending GM Queue"] == "2"
    assert values["Teams"] == "30"
    assert values["Players"] == "1200"
    assert values["Season Phase"] == "OFFSEASON"


def test_format_gm_queue_status_for_owner_league():
    text = _format_gm_queue_status(
        {
            "gm_queue_required": True,
            "gm_queue_pending": 3,
            "gm_queue_approved_unapplied": 1,
        }
    )
    assert "pending review 3" in text
    assert "approved-not-applied 1" in text


def test_format_gm_queue_status_for_single_player():
    text = _format_gm_queue_status({"gm_queue_required": False})
    assert "Single-player mode" in text
