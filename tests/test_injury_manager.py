from datetime import date, timedelta

import pytest

from models.player import Player
from models.roster import Roster
from services.injury_manager import place_on_injury_list, recover_from_injury
from services.prospect_event_log import (
    EVENT_TYPE_DEMOTION,
    EVENT_TYPE_PROMOTION,
    load_prospect_events,
)
from services.prospect_rules import is_player_protected, update_prospect_rules
from utils import path_utils


def _make_player(pid: str) -> Player:
    return Player(
        player_id=pid,
        first_name="A",
        last_name="B",
        birthdate="2000-01-01",
        height=72,
        weight=180,
        bats="R",
        primary_position="P",
        other_positions=[],
        gf=0,
    )


def test_injury_and_recovery_flow(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None

    p1 = _make_player("p1")
    p2 = _make_player("p2")
    roster = Roster(team_id="T", act=["p1"], aaa=["p2"], low=[])

    start_day = date(2025, 4, 1)
    place_on_injury_list(p1, roster, list_name="dl15", today=start_day)

    assert p1.injured is True
    assert p1.injury_list == "dl15"
    assert p1.injury_start_date == start_day.isoformat()
    assert p1.injury_eligible_date == (start_day + timedelta(days=15)).isoformat()
    assert roster.dl_tiers["p1"] == "dl15"
    assert p1.ready is False
    assert "p2" in roster.act  # replacement promoted

    with pytest.raises(ValueError):
        recover_from_injury(p1, roster, today=start_day + timedelta(days=5))

    recover_from_injury(p1, roster, today=start_day + timedelta(days=20))

    assert p1.injured is False
    assert p1.ready is True
    assert "p1" in roster.act
    assert "p2" in roster.aaa  # replacement returned to AAA
    assert "p1" not in roster.dl
    assert roster.dl_tiers == {}

    events = load_prospect_events(
        team_id="T",
        data_dir=data_root,
    )
    event_types = [str(event.get("event_type")) for event in events]
    assert EVENT_TYPE_PROMOTION in event_types
    assert EVENT_TYPE_DEMOTION in event_types


def test_injury_replacement_respects_protection_rules(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None

    update_prospect_rules(
        enabled=True,
        auto_protect_on_promotion=False,
    )
    p1 = _make_player("p1")
    p2 = _make_player("p2")
    roster = Roster(team_id="T", act=["p1"], aaa=["p2"], low=[])

    place_on_injury_list(p1, roster, list_name="dl15", today=date(2025, 4, 1))

    assert "p1" in roster.dl
    assert "p2" in roster.aaa
    assert "p2" not in roster.act


def test_injury_replacement_auto_protects_when_enabled(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None

    update_prospect_rules(
        enabled=True,
        auto_protect_on_promotion=True,
    )
    p1 = _make_player("p1")
    p2 = _make_player("p2")
    roster = Roster(team_id="T", act=["p1"], aaa=["p2"], low=[])

    place_on_injury_list(p1, roster, list_name="dl15", today=date(2025, 4, 1))

    assert "p2" in roster.act
    assert is_player_protected("T", "p2") is True
