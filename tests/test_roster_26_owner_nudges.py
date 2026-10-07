"""What owners see about the 26-man roster (owner decision 8, 7.46.0).

Notifications (the roster-cap rule and the new open-spot rule), the open-spot
action item, the roster_26_man tutorial, and a guard against stale "25-man"
copy in the tutorials and the manual. Every roster is sized from
``utils.roster_rules``; nothing here touches a real league.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.roster_rules import (
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    ORG_LIMIT,
    SEPTEMBER_MAX_ACTIVE_PITCHERS,
    SEPTEMBER_ROSTER_SIZE,
)

TEAM = "T1"
AUGUST = "2026-08-15"
SEPTEMBER = "2026-09-10"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir(parents=True)
    # Sentinels so get_data_dir() does not seed a full copy of the repo data.
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,"
        "primary_color,secondary_color,owner_id\n",
        encoding="utf-8",
    )
    (root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\n",
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


def _write_roster(root: Path, *, pitchers: int, hitters: int) -> None:
    rows = [f"P{i},ACT" for i in range(pitchers)]
    rows += [f"H{i},ACT" for i in range(hitters)]
    (root / "rosters" / f"{TEAM}.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _players(pitchers: int, hitters: int):
    out = [
        SimpleNamespace(
            player_id=f"P{i}", primary_position="P", other_positions=[], is_pitcher=True
        )
        for i in range(pitchers)
    ]
    out += [
        SimpleNamespace(
            player_id=f"H{i}", primary_position="SS", other_positions=[], is_pitcher=False
        )
        for i in range(hitters)
    ]
    return out


def _regular_season(monkeypatch):
    from playbalance import season_manager as sm

    monkeypatch.setattr(
        sm, "SeasonManager", lambda *a, **k: SimpleNamespace(phase=sm.SeasonPhase.REGULAR_SEASON)
    )


def _settings(rule_id: str, **kwargs):
    from services.notification_settings import NotificationRule, NotificationSettings

    return NotificationSettings(team_id=TEAM, rules={rule_id: NotificationRule(**kwargs)})


def _cap_events(monkeypatch, root, *, pitchers, hitters, sim_date):
    import services.notification_engine as engine

    _write_roster(root, pitchers=pitchers, hitters=hitters)
    monkeypatch.setattr(
        "utils.player_loader.load_players_from_csv",
        lambda *a, **k: _players(pitchers, hitters),
    )
    settings = _settings("roster_cap_violation", stop_sim=True)
    return engine._detect_lineup_validity(TEAM, settings, sim_date)


# --- roster_cap_violation -------------------------------------------------


def test_full_26_man_roster_in_season_does_not_fire(data_dir, monkeypatch):
    hitters = ACTIVE_ROSTER_SIZE - MAX_ACTIVE_PITCHERS
    events = _cap_events(
        monkeypatch, data_dir, pitchers=MAX_ACTIVE_PITCHERS, hitters=hitters, sim_date=AUGUST
    )
    assert events == []


def test_28_man_roster_in_september_does_not_fire(data_dir, monkeypatch):
    _regular_season(monkeypatch)
    hitters = SEPTEMBER_ROSTER_SIZE - SEPTEMBER_MAX_ACTIVE_PITCHERS
    events = _cap_events(
        monkeypatch,
        data_dir,
        pitchers=SEPTEMBER_MAX_ACTIVE_PITCHERS,
        hitters=hitters,
        sim_date=SEPTEMBER,
    )
    assert events == []


def test_27_active_in_august_fires(data_dir, monkeypatch):
    over = ACTIVE_ROSTER_SIZE + 1
    hitters = over - MAX_ACTIVE_PITCHERS
    events = _cap_events(
        monkeypatch, data_dir, pitchers=MAX_ACTIVE_PITCHERS, hitters=hitters, sim_date=AUGUST
    )
    assert [e.rule_id for e in events] == ["roster_cap_violation"]
    assert f"{over} players (max {ACTIVE_ROSTER_SIZE})" in events[0].message
    assert events[0].stop_sim is True


def test_14_pitchers_fires_with_the_pitcher_cap(data_dir, monkeypatch):
    pitchers = MAX_ACTIVE_PITCHERS + 1
    hitters = ACTIVE_ROSTER_SIZE - pitchers
    events = _cap_events(
        monkeypatch, data_dir, pitchers=pitchers, hitters=hitters, sim_date=AUGUST
    )
    assert [e.rule_id for e in events] == ["roster_cap_violation"]
    assert f"{pitchers} pitchers (max {MAX_ACTIVE_PITCHERS})" in events[0].message
    # The roster is at the size cap, so the pitcher count is the only problem.
    assert "players (max" not in events[0].message


def test_cap_check_never_writes_a_placeholder_roster(data_dir, monkeypatch):
    import services.notification_engine as engine

    monkeypatch.setattr(
        "utils.player_loader.load_players_from_csv", lambda *a, **k: []
    )
    settings = _settings("roster_cap_violation", stop_sim=True)
    assert engine._detect_lineup_validity("NOFILE", settings, AUGUST) == []
    assert not (data_dir / "rosters" / "NOFILE.csv").exists()


# --- roster_spot_open -----------------------------------------------------


def _spot_events(sim_date=AUGUST, **rule):
    import services.notification_engine as engine
    from services.notification_settings import load_notification_settings

    settings = load_notification_settings(TEAM)
    if rule:
        settings = _settings("roster_spot_open", **rule)
    return engine._detect_roster_spot_open(TEAM, settings, sim_date)


def test_open_spot_notifies_without_stopping_the_sim(data_dir):
    short = ACTIVE_ROSTER_SIZE - 1
    _write_roster(data_dir, pitchers=MAX_ACTIVE_PITCHERS, hitters=short - MAX_ACTIVE_PITCHERS)
    events = _spot_events()
    assert [e.rule_id for e in events] == ["roster_spot_open"]
    event = events[0]
    assert event.stop_sim is False and event.notify is True
    assert event.severity == "info"
    assert f"{short} of {ACTIVE_ROSTER_SIZE}" in event.message
    assert event.payload["open_spots"] == 1


def test_open_spot_fires_once_per_state_not_every_day(data_dir):
    short = ACTIVE_ROSTER_SIZE - 1
    _write_roster(data_dir, pitchers=MAX_ACTIVE_PITCHERS, hitters=short - MAX_ACTIVE_PITCHERS)
    assert len(_spot_events()) == 1
    assert _spot_events() == []  # the next sim day: same 25/26, no repeat

    # Filling the spot clears it; opening it again notifies again.
    full_hitters = ACTIVE_ROSTER_SIZE - MAX_ACTIVE_PITCHERS
    _write_roster(data_dir, pitchers=MAX_ACTIVE_PITCHERS, hitters=full_hitters)
    assert _spot_events() == []
    _write_roster(data_dir, pitchers=MAX_ACTIVE_PITCHERS, hitters=full_hitters - 2)
    events = _spot_events()
    assert len(events) == 1 and events[0].payload["open_spots"] == 2


def test_open_spot_respects_an_opted_in_stop(data_dir):
    _write_roster(data_dir, pitchers=MAX_ACTIVE_PITCHERS, hitters=1)
    events = _spot_events(stop_sim=True)
    assert events and events[0].stop_sim is True
    assert _spot_events(stop_sim=True) == []  # paused once, not every day


def test_full_roster_and_missing_roster_do_not_fire(data_dir):
    _write_roster(
        data_dir,
        pitchers=MAX_ACTIVE_PITCHERS,
        hitters=ACTIVE_ROSTER_SIZE - MAX_ACTIVE_PITCHERS,
    )
    assert _spot_events() == []
    (data_dir / "rosters" / f"{TEAM}.csv").unlink()
    assert _spot_events() == []
    assert not (data_dir / "rosters" / f"{TEAM}.csv").exists()


def test_detect_events_runs_the_open_spot_rule_daily(data_dir):
    import services.notification_engine as engine
    from services.notification_settings import load_notification_settings

    _write_roster(data_dir, pitchers=MAX_ACTIVE_PITCHERS, hitters=1)
    events = engine.detect_events(
        TEAM,
        load_notification_settings(TEAM),
        engine.DaySnapshot(news_size=0),
        sim_date=AUGUST,
    )
    assert "roster_spot_open" in [e.rule_id for e in events]
    assert not any(e.stop_sim for e in events if e.rule_id == "roster_spot_open")


def test_old_settings_file_picks_up_the_new_rule_default(data_dir):
    import services.notification_settings as ns

    notif_dir = data_dir / "notifications"
    notif_dir.mkdir()
    # A file saved before 7.46.0: no roster_spot_open key at all.
    (notif_dir / f"{TEAM}.json").write_text(
        json.dumps(
            {
                "team_id": TEAM,
                "rules": {
                    "roster_cap_violation": {"enabled": True, "notify": True, "stop_sim": False}
                },
            }
        ),
        encoding="utf-8",
    )
    settings = ns.load_notification_settings(TEAM)
    rule = settings.rule("roster_spot_open")
    assert rule.enabled is True and rule.notify is True and rule.stop_sim is False
    # The saved choice for an existing rule is kept.
    assert settings.rule("roster_cap_violation").stop_sim is False
    spec = next(
        r for cat in ns.rules_index() for r in cat["rules"] if r["id"] == "roster_spot_open"
    )
    assert spec["default_stop"] is False and spec["default_notify"] is True


# --- action items ---------------------------------------------------------


def _action_items(monkeypatch, team_id=TEAM):
    import api.routers.season as season

    monkeypatch.setattr(season, "_read_season_deadline", lambda: None)
    monkeypatch.setattr(
        season,
        "SeasonManager",
        lambda: SimpleNamespace(phase=SimpleNamespace(value="REGULAR_SEASON")),
    )
    monkeypatch.setattr("utils.trade_utils.load_trades", lambda: [])
    monkeypatch.setattr("services.fa_window.window_status", lambda: {"status": None})
    monkeypatch.setattr("utils.sim_date.get_current_sim_date", lambda: AUGUST)
    return season.season_action_items(identity={"r": "owner", "t": team_id})


def test_action_item_for_an_open_spot_moves_nobody(data_dir, monkeypatch):
    short = ACTIVE_ROSTER_SIZE - 1
    _write_roster(data_dir, pitchers=MAX_ACTIVE_PITCHERS, hitters=short - MAX_ACTIVE_PITCHERS)
    roster_file = data_dir / "rosters" / f"{TEAM}.csv"
    before = roster_file.read_bytes()

    out = _action_items(monkeypatch)
    item = next(i for i in out["items"] if i["kind"] == "roster_spot_open")
    assert item["severity"] == "info"
    assert item["href"] == "/roster"
    assert item["count"] == 1
    assert f"{short}/{ACTIVE_ROSTER_SIZE}" in item["title"]
    assert roster_file.read_bytes() == before


def test_no_action_item_for_a_full_roster_or_a_team_without_one(data_dir, monkeypatch):
    _write_roster(
        data_dir,
        pitchers=MAX_ACTIVE_PITCHERS,
        hitters=ACTIVE_ROSTER_SIZE - MAX_ACTIVE_PITCHERS,
    )
    out = _action_items(monkeypatch)
    assert not any(i["kind"] == "roster_spot_open" for i in out["items"])
    out = _action_items(monkeypatch, team_id="NOFILE")
    assert not any(i["kind"] == "roster_spot_open" for i in out["items"])
    assert not (data_dir / "rosters" / "NOFILE.csv").exists()


# --- tutorials and manual -------------------------------------------------

_STALE = re.compile(r"ACT 25\b|Active \(25\)|25-man", re.IGNORECASE)


@pytest.mark.parametrize(
    "rel", ["services/tutorials.py", "docs/manuals/electron_ui_guide.md"]
)
def test_no_stale_25_man_copy(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert not _STALE.findall(text), f"{rel} still describes the 25-man roster"


def test_roster_26_man_tutorial_is_served():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routers import help as help_router
    from api.security import require_bearer

    app = FastAPI()
    app.include_router(help_router.router)
    app.dependency_overrides[require_bearer] = lambda: {"r": "owner", "t": TEAM}
    client = TestClient(app)

    listing = client.get("/help/tutorials")
    assert listing.status_code == 200
    ids = [t["tutorial_id"] for t in listing.json()["tutorials"]]
    assert "roster_26_man" in ids
    # Sits right after the roster tutorial in the library.
    assert ids.index("roster_26_man") == ids.index("roster_and_depth") + 1

    detail = client.get("/help/tutorials/roster_26_man").json()
    assert detail["route"] is None  # library-only, never a first-visit popup
    body = " ".join(s["body_html"] for s in detail["steps"])
    for fact in (
        str(ACTIVE_ROSTER_SIZE),
        str(MAX_ACTIVE_PITCHERS),
        str(SEPTEMBER_ROSTER_SIZE),
        str(SEPTEMBER_MAX_ACTIVE_PITCHERS),
        str(ORG_LIMIT),
        "unslotted relievers",
    ):
        assert fact in body
    # MLB has no 26-man minimum and the game has none either.
    assert "minimum of 26" not in body.lower()
    assert "no minimum" in body.lower()
