"""What pauses the sim, and the roster/lineup alerts (Release 3, owner Q8).

- The lineup / pitching-staff / roster-cap validators actually run: the staff
  check passes ``active_ids`` (it used to pass a keyword the validator does not
  take, and the TypeError was swallowed), and the season runner asks for them.
- New defaults: an empty staff slot and 10/15-day IL placements notify
  without stopping; an invalid lineup, a roster over the cap, the 60-day IL
  and season-ending injuries still stop.
- Saved settings files keep an owner's changed values; only values still at
  the old default move to the new one.

Every test runs in a tmp data dir; nothing touches a real league.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.staff_roles import REQUIRED_PITCHING_ROLES, STAFF_ROLES

TEAM = "T1"
AUGUST = "2026-08-15"


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir(parents=True)
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


def _players(n_pitchers: int):
    return [
        SimpleNamespace(
            player_id=f"P{i}", first_name="Arm", last_name=str(i),
            primary_position="P", other_positions=[], is_pitcher=True,
        )
        for i in range(n_pitchers)
    ]


def _setup(root: Path, monkeypatch, *, staff_roles, aaa=()):
    """13 pitchers P0..P12, active unless listed in ``aaa``; staff = P0.. in order."""
    pids = [f"P{i}" for i in range(13)]
    lines = [f"{pid},{'AAA' if pid in aaa else 'ACT'}" for pid in pids]
    (root / "rosters" / f"{TEAM}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = [f"P{i},{role}" for i, role in enumerate(staff_roles)]
    (root / "rosters" / f"{TEAM}_pitching.csv").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "utils.player_loader.load_players_from_csv",
        lambda *a, **k: _players(13),
    )


def _staff_events(sim_date=AUGUST):
    import services.notification_engine as engine
    from services.notification_settings import load_notification_settings

    events = engine._detect_lineup_validity(TEAM, load_notification_settings(TEAM), sim_date)
    return [e for e in events if e.rule_id == "pitching_staff_invalid"]


# --- the staff check fires ---------------------------------------------------------


def test_staff_missing_mr2_fires_notify_only(data_dir, monkeypatch):
    roles = [r for r in REQUIRED_PITCHING_ROLES if r != "MR2"]
    _setup(data_dir, monkeypatch, staff_roles=roles)
    events = _staff_events()
    assert len(events) == 1
    event = events[0]
    assert "Role MR2 is not assigned." in event.payload["errors"]
    assert event.stop_sim is False and event.notify is True
    assert event.title == "Pitching staff has an empty slot"


def test_full_staff_with_optional_slots_is_quiet(data_dir, monkeypatch):
    _setup(data_dir, monkeypatch, staff_roles=STAFF_ROLES)
    assert _staff_events() == []


def test_slot_held_by_a_pitcher_sent_down_reads_as_empty(data_dir, monkeypatch):
    # SP1..CL held by P0..P10; P5 (LR) was optioned to AAA.
    _setup(data_dir, monkeypatch, staff_roles=REQUIRED_PITCHING_ROLES, aaa=("P5",))
    events = _staff_events()
    assert len(events) == 1
    assert events[0].payload["errors"] == ["LR: Arm 5 is not on the active roster."]


def test_staff_problem_is_reported_once_until_it_changes(data_dir, monkeypatch):
    roles = [r for r in REQUIRED_PITCHING_ROLES if r != "MR2"]
    _setup(data_dir, monkeypatch, staff_roles=roles)
    assert len(_staff_events()) == 1
    assert _staff_events() == []  # the next sim day: same problem, no repeat

    _setup(data_dir, monkeypatch, staff_roles=STAFF_ROLES)
    assert _staff_events() == []  # fixed: clears the record
    _setup(data_dir, monkeypatch, staff_roles=roles)
    assert len(_staff_events()) == 1  # broken again: reported again


def test_missing_roster_does_not_fire_or_write_one(data_dir, monkeypatch):
    import services.notification_engine as engine
    from services.notification_settings import load_notification_settings

    monkeypatch.setattr("utils.player_loader.load_players_from_csv", lambda *a, **k: [])
    events = engine._detect_lineup_validity("NOFILE", load_notification_settings("NOFILE"), AUGUST)
    assert [e for e in events if e.rule_id == "pitching_staff_invalid"] == []
    assert not (data_dir / "rosters" / "NOFILE.csv").exists()


def test_lineup_problem_still_stops_the_sim(data_dir, monkeypatch):
    import services.notification_engine as engine
    from services.notification_settings import load_notification_settings

    _setup(data_dir, monkeypatch, staff_roles=STAFF_ROLES)
    lineups = data_dir / "lineups"
    lineups.mkdir()
    (lineups / f"{TEAM}_vs_lhp.csv").write_text(
        "order,player_id,position\n1,P0,C\n", encoding="utf-8"
    )
    events = engine._detect_lineup_validity(TEAM, load_notification_settings(TEAM), AUGUST)
    lineup = [e for e in events if e.rule_id == "lineup_invalid"]
    assert len(lineup) == 1 and lineup[0].stop_sim is True
    assert lineup[0].payload["vs"] == "lhp"


# --- when the validators run ----------------------------------------------------------


def _news(root: Path, *lines: str) -> int:
    path = root / "news_feed.txt"
    before = path.stat().st_size if path.exists() else 0
    with path.open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")
    return before


def _detect(root, **kwargs):
    import services.notification_engine as engine
    from services.notification_settings import load_notification_settings

    pre = engine.DaySnapshot(news_size=kwargs.pop("news_size", 0))
    return engine.detect_events(
        TEAM, load_notification_settings(TEAM), pre, sim_date=AUGUST, **kwargs
    )


def test_validators_run_on_team_roster_news(data_dir, monkeypatch):
    roles = [r for r in REQUIRED_PITCHING_ROLES if r != "MR2"]
    _setup(data_dir, monkeypatch, staff_roles=roles)
    size = _news(data_dir, "[2026-08-15 10:00:00] [game_recap] [T1] Won 5-3.")
    assert "pitching_staff_invalid" not in [
        e.rule_id for e in _detect(data_dir, news_size=size, validate_on_roster_news=True)
    ]
    size = _news(
        data_dir,
        "[2026-08-15 10:00:00] [injury] [T1] Arm 1 placed on the 15-day IL.",
    )
    rule_ids = [
        e.rule_id for e in _detect(data_dir, news_size=size, validate_on_roster_news=True)
    ]
    assert "pitching_staff_invalid" in rule_ids


def test_other_teams_news_does_not_trigger_the_validators(data_dir, monkeypatch):
    roles = [r for r in REQUIRED_PITCHING_ROLES if r != "MR2"]
    _setup(data_dir, monkeypatch, staff_roles=roles)
    size = _news(data_dir, "[2026-08-15 10:00:00] [transaction] [T2] Signed a reliever.")
    events = _detect(data_dir, news_size=size, validate_on_roster_news=True)
    assert "pitching_staff_invalid" not in [e.rule_id for e in events]


def test_run_lineup_validators_runs_them_without_news(data_dir, monkeypatch):
    roles = [r for r in REQUIRED_PITCHING_ROLES if r != "MR2"]
    _setup(data_dir, monkeypatch, staff_roles=roles)
    events = _detect(data_dir, run_lineup_validators=True)
    assert "pitching_staff_invalid" in [e.rule_id for e in events]


def test_season_runner_asks_for_the_validators():
    import api.routers.season as season

    source = inspect.getsource(season)
    assert "run_lineup_validators=(" in source
    assert "days_done == 1 or post_phase != pre_phase" in source
    assert "validate_on_roster_news=True" in source


# --- stop defaults -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_id,stop",
    [
        ("injury_dl15", False),
        ("pitching_staff_invalid", False),
        ("injury_day_to_day", False),
        ("lineup_invalid", True),
        ("roster_cap_violation", True),
        ("injury_ir60", True),
        ("injury_dl45", True),
        ("injury_season_ending", True),
    ],
)
def test_default_stop_rules(data_dir, rule_id, stop):
    from services.notification_settings import load_notification_settings

    rule = load_notification_settings(TEAM).rule(rule_id)
    assert rule.enabled and rule.notify
    assert rule.stop_sim is stop


@pytest.mark.parametrize(
    "line,rule_id,stop",
    [
        ("Arm 1 placed on the 15-day IL.", "injury_dl15", False),
        ("Bat 2 placed on the 10-day IL.", "injury_dl15", False),
        ("Arm 3 placed on the 60-day IL.", "injury_ir60", True),
        ("Bat 4 suffers a season-ending knee injury.", "injury_season_ending", True),
    ],
)
def test_injury_news_stops_only_for_serious_tiers(data_dir, line, rule_id, stop):
    size = _news(data_dir, f"[2026-08-15 10:00:00] [injury] [T1] {line}")
    events = [e for e in _detect(data_dir, news_size=size) if e.rule_id.startswith("injury_")]
    assert [(e.rule_id, e.stop_sim) for e in events] == [(rule_id, stop)]


# --- saved settings files -----------------------------------------------------------------


def _old_file(root: Path, rules: dict, version=None) -> None:
    notif = root / "notifications"
    notif.mkdir(exist_ok=True)
    payload = {"team_id": TEAM, "rules": rules}
    if version is not None:
        payload["version"] = version
    (notif / f"{TEAM}.json").write_text(json.dumps(payload), encoding="utf-8")


def _rule(stop, notify=True, enabled=True):
    return {"enabled": enabled, "notify": notify, "stop_sim": stop}


def test_untouched_old_defaults_move_to_the_new_defaults(data_dir):
    from services.notification_settings import load_notification_settings

    # A pre-Release-3 save writes every rule; these still hold the old defaults.
    _old_file(data_dir, {
        "injury_dl15": _rule(True),
        "pitching_staff_invalid": _rule(True),
        "injury_ir60": _rule(True),
        "lineup_invalid": _rule(True),
    })
    settings = load_notification_settings(TEAM)
    assert settings.rule("injury_dl15").stop_sim is False
    assert settings.rule("pitching_staff_invalid").stop_sim is False
    assert settings.rule("injury_ir60").stop_sim is True
    assert settings.rule("lineup_invalid").stop_sim is True


def test_owner_changed_values_are_kept(data_dir):
    from services.notification_settings import load_notification_settings

    _old_file(data_dir, {
        "injury_dl15": _rule(True, notify=False),   # owner muted the banner
        "lineup_invalid": _rule(False),             # owner turned the stop off
        "injury_ir60": _rule(False),                # owner turned the stop off
        "injury_day_to_day": _rule(True),           # owner turned a stop on
    })
    settings = load_notification_settings(TEAM)
    assert settings.rule("injury_dl15").notify is False
    assert settings.rule("injury_dl15").stop_sim is False  # stop untouched: migrates
    assert settings.rule("lineup_invalid").stop_sim is False
    assert settings.rule("injury_ir60").stop_sim is False
    assert settings.rule("injury_day_to_day").stop_sim is True


def test_a_current_file_keeps_an_explicit_stop(data_dir):
    """After the migration an owner may switch the stop back on; it sticks."""
    from services.notification_settings import (
        SETTINGS_VERSION,
        load_notification_settings,
        save_notification_settings,
    )

    _old_file(data_dir, {"injury_dl15": _rule(True)})
    assert load_notification_settings(TEAM).rule("injury_dl15").stop_sim is False
    save_notification_settings(TEAM, {"rules": {"injury_dl15": _rule(True)}})
    stored = json.loads((data_dir / "notifications" / f"{TEAM}.json").read_text("utf-8"))
    assert stored["version"] == SETTINGS_VERSION
    assert load_notification_settings(TEAM).rule("injury_dl15").stop_sim is True


def test_saving_another_rule_persists_the_migrated_defaults(data_dir):
    from services.notification_settings import (
        load_notification_settings,
        save_notification_settings,
    )

    _old_file(data_dir, {
        "injury_dl15": _rule(True),
        "pitching_staff_invalid": _rule(True),
    })
    save_notification_settings(TEAM, {"rules": {"win_streak": {"enabled": False}}})
    settings = load_notification_settings(TEAM)
    assert settings.rule("injury_dl15").stop_sim is False
    assert settings.rule("pitching_staff_invalid").stop_sim is False
    assert settings.rule("win_streak").enabled is False


def test_schema_reports_the_new_defaults():
    from services.notification_settings import rules_index

    specs = {r["id"]: r for cat in rules_index() for r in cat["rules"]}
    assert specs["injury_dl15"]["default_stop"] is False
    assert specs["pitching_staff_invalid"]["default_stop"] is False
    assert specs["lineup_invalid"]["default_stop"] is True
    assert specs["injury_ir60"]["default_stop"] is True
