import importlib
import json
from pathlib import Path

import pytest


def _write_career_players(path: Path, totals: dict) -> None:
    payload = {"version": 1, "players": {}}
    for pid, stats in totals.items():
        payload["players"][pid] = {"totals": stats, "seasons": {}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    import utils.path_utils as path_utils
    path_utils._DATA_DIR = None
    import playbalance.season_context as season_context
    importlib.reload(season_context)
    return data_root


def test_record_notifications_emit_event(data_dir, monkeypatch):
    _write_career_players(
        data_dir / "careers" / "career_players.json",
        {"P1": {"h": 100}},
    )

    import services.record_book as record_book

    monkeypatch.setattr(
        record_book,
        "_player_index",
        lambda: {"P1": {"name": "Test Player", "is_pitcher": False}},
    )
    monkeypatch.setattr(record_book, "_team_index", lambda: {})

    import services.record_notifications as record_notifications
    import services.special_events as special_events

    importlib.reload(record_notifications)
    importlib.reload(special_events)

    result = record_notifications.update_record_notifications(ended_on="2026-10-01")
    assert result["events"] == []
    assert not special_events.load_special_events()

    _write_career_players(
        data_dir / "careers" / "career_players.json",
        {"P1": {"h": 150}},
    )

    result = record_notifications.update_record_notifications(ended_on="2026-10-01")
    events = special_events.load_special_events()
    assert result["events"]
    assert any(event.get("type") == "record" for event in events)
