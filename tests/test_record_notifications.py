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
    data_root.mkdir(parents=True, exist_ok=True)
    # Sentinels: get_data_dir()'s first-run auto-seed does a FULL copy of the
    # bundled repo data/ (which carries a populated special_events.json + careers/)
    # only when teams/players/users are missing. Pre-create them so the test
    # starts from a genuinely clean data dir.
    (data_root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,"
        "primary_color,secondary_color,owner_id\n",
        encoding="utf-8",
    )
    (data_root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\n",
        encoding="utf-8",
    )
    (data_root / "users.txt").write_text("", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(data_root))
    # No active-league binding so get_data_dir() resolves to the bare tmp root.
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils
    # get_data_dir() now caches in _DATA_DIR_CACHE (a dict), not _DATA_DIR.
    path_utils._DATA_DIR_CACHE.clear()
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
