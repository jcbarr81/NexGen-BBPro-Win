from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def prospect_event_log_module(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))

    import utils.path_utils as path_utils

    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None

    import services.prospect_event_log as prospect_event_log

    importlib.reload(prospect_event_log)
    return prospect_event_log


def test_append_and_load_prospect_events(prospect_event_log_module):
    record = prospect_event_log_module.append_prospect_event(
        {
            "event_type": prospect_event_log_module.EVENT_TYPE_PROMOTION,
            "team_id": "AAA",
            "player_id": "P100",
            "player_name": "Test Player",
            "actor": "user",
            "trigger": "manual_reassign_save",
            "from_level": "aaa",
            "to_level": "act",
            "details": {"source": "test"},
        },
        season_id="season-2035",
    )

    path = prospect_event_log_module.events_path_for_season("season-2035")
    assert path.exists()
    assert record["event_type"] == prospect_event_log_module.EVENT_TYPE_PROMOTION

    rows = prospect_event_log_module.load_prospect_events(
        season_id="season-2035",
        team_id="AAA",
        player_id="P100",
        event_types=[prospect_event_log_module.EVENT_TYPE_PROMOTION],
    )
    assert len(rows) == 1
    assert rows[0]["trigger"] == "manual_reassign_save"
    assert rows[0]["from_level"] == "aaa"
    assert rows[0]["to_level"] == "act"


def test_record_roster_level_movements_promotion_and_demotion(
    prospect_event_log_module,
):
    before = {"P1": "aaa", "P2": "act", "P3": "low"}
    after = {"P1": "act", "P2": "aaa", "P3": "low"}

    events = prospect_event_log_module.record_roster_level_movements(
        before,
        after,
        team_id="BBB",
        player_names={"P1": "Up Guy", "P2": "Down Guy"},
        actor="system",
        trigger="test_movement",
        details={"reason": "test"},
        season_id="season-2036",
    )

    assert len(events) == 2
    event_types = {event["event_type"] for event in events}
    assert prospect_event_log_module.EVENT_TYPE_PROMOTION in event_types
    assert prospect_event_log_module.EVENT_TYPE_DEMOTION in event_types

    rows = prospect_event_log_module.load_prospect_events(
        season_id="season-2036",
        team_id="BBB",
    )
    assert len(rows) == 2
    assert all(row.get("trigger") == "test_movement" for row in rows)


def test_option_and_protection_event_helpers(prospect_event_log_module):
    prospect_event_log_module.record_option_decision_event(
        team_id="CCC",
        player_id="P900",
        decision="exercised",
        option_type="team",
        option_index=0,
        actor="system",
        trigger="season_rollover",
        season_id="season-2037",
    )
    prospect_event_log_module.record_protection_event(
        team_id="CCC",
        player_id="P901",
        status="protected",
        actor="commissioner",
        trigger="roster_protection_update",
        season_id="season-2037",
    )

    rows = prospect_event_log_module.load_prospect_events(season_id="season-2037")
    event_types = {str(row.get("event_type")) for row in rows}
    assert prospect_event_log_module.EVENT_TYPE_OPTION_DECISION in event_types
    assert prospect_event_log_module.EVENT_TYPE_PROTECTION_CHANGE in event_types
