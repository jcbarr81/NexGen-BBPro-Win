"""Season-page items for an owner's healthy injured-list returners (R3, Q11).

When an owner's player comes off the injured list with no room on the active
roster he waits in AAA and the owner gets a "make room" item; a player whose
stint is over on a list the owner activates by hand gets a "can come off"
item. Both are read-only: nothing on the owner's roster is moved.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from models.player import Player
from utils.player_writer import save_players_to_csv

TEAM = "T1"
TODAY = "2026-08-15"


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir(parents=True)
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,"
        "primary_color,secondary_color,owner_id\n",
        encoding="utf-8",
    )
    (root / "users.txt").write_text("", encoding="utf-8")
    (root / "rosters").mkdir()
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def _player(pid: str, *, injury_list: str | None = None, eligible: str | None = None) -> Player:
    player = Player(
        player_id=pid,
        first_name="Pat",
        last_name=pid,
        birthdate="1995-01-01",
        height=72,
        weight=190,
        bats="R",
        primary_position="CF",
        other_positions=[],
        gf=0,
    )
    if injury_list:
        player.injured = True
        player.injury_list = injury_list
        player.injury_start_date = "2026-07-01"
        player.injury_eligible_date = eligible
    return player


def _action_items(monkeypatch):
    import api.routers.season as season

    monkeypatch.setattr(season, "_read_season_deadline", lambda: None)
    monkeypatch.setattr(
        season,
        "SeasonManager",
        lambda: SimpleNamespace(phase=SimpleNamespace(value="REGULAR_SEASON")),
    )
    monkeypatch.setattr("utils.trade_utils.load_trades", lambda: [])
    monkeypatch.setattr("services.fa_window.window_status", lambda: {"status": None})
    monkeypatch.setattr("utils.sim_date.get_current_sim_date", lambda: TODAY)
    return season.season_action_items(identity={"r": "owner", "t": TEAM})


def _kinds(out):
    return {item["kind"]: item for item in out["items"]}


def test_parked_returner_asks_the_owner_to_make_room(data_dir, monkeypatch):
    from services.dl_automation import AWAITING_ROOM_FILENAME

    save_players_to_csv([_player("H1"), _player("BACK")], str(data_dir / "players.csv"))
    roster = data_dir / "rosters" / f"{TEAM}.csv"
    roster.write_text("H1,ACT\nBACK,AAA\n", encoding="utf-8")
    (data_dir / AWAITING_ROOM_FILENAME).write_text(
        json.dumps(
            {
                "version": 1,
                "teams": {
                    TEAM: [
                        {"player_id": "BACK", "list": "10-Day IL", "level": "aaa",
                         "date": "2026-08-14"}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    before = roster.read_bytes()

    item = _kinds(_action_items(monkeypatch))["il_return_needs_room"]

    assert item["severity"] == "action"
    assert item["href"] == "/roster"
    assert "Pat BACK" in item["title"]
    assert "AAA" in item["detail"]
    assert roster.read_bytes() == before  # read-only


def test_no_make_room_item_once_he_is_up(data_dir, monkeypatch):
    from services.dl_automation import AWAITING_ROOM_FILENAME

    save_players_to_csv([_player("BACK")], str(data_dir / "players.csv"))
    (data_dir / "rosters" / f"{TEAM}.csv").write_text("BACK,ACT\n", encoding="utf-8")
    (data_dir / AWAITING_ROOM_FILENAME).write_text(
        json.dumps({"teams": {TEAM: [{"player_id": "BACK", "date": "2026-08-14"}]}}),
        encoding="utf-8",
    )
    assert "il_return_needs_room" not in _kinds(_action_items(monkeypatch))


def test_stint_over_on_a_manual_list_asks_the_owner_to_activate(data_dir, monkeypatch):
    done = (date.fromisoformat(TODAY) - timedelta(days=1)).isoformat()
    later = (date.fromisoformat(TODAY) + timedelta(days=20)).isoformat()
    save_players_to_csv(
        [
            _player("READY", injury_list="il60", eligible=done),
            _player("HURT", injury_list="il10", eligible=later),
        ],
        str(data_dir / "players.csv"),
    )
    (data_dir / "rosters" / f"{TEAM}.csv").write_text(
        "READY,IR\nHURT,DL15\n", encoding="utf-8"
    )

    item = _kinds(_action_items(monkeypatch))["il_return_ready"]

    assert item["count"] == 1
    assert "Pat READY" in item["title"]
    assert item["href"] == "/injuries"


def test_no_il_items_for_a_healthy_roster(data_dir, monkeypatch):
    save_players_to_csv([_player("H1")], str(data_dir / "players.csv"))
    (data_dir / "rosters" / f"{TEAM}.csv").write_text("H1,ACT\n", encoding="utf-8")
    kinds = _kinds(_action_items(monkeypatch))
    assert "il_return_ready" not in kinds and "il_return_needs_room" not in kinds
