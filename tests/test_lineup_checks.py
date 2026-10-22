"""Lineups, staff and depth charts naming players a club no longer has, and a
club with no catcher (8.4.1, ``services.lineup_checks``).

Advisory only: the readiness board gets notes, the Spotlight gets items, the
rollover notice a sentence. Nothing marks a club unready (the not-ready list
drives the scheduled runs' CPU fill) and nothing writes a file.
"""

from __future__ import annotations

import csv
import hashlib
import json
from types import SimpleNamespace

import pytest

TEAMS_CSV = (
    "team_id,name,city,abbreviation,division,stadium,primary_color,"
    "secondary_color,owner_id\n"
    "BAL,Orioles,Baltimore,BAL,East,Camden,#000000,#FFFFFF,\n"
    "NYY,Yankees,New York,NYY,East,Stadium,#000000,#FFFFFF,\n"
)

# pid: (position, is_pitcher, injured)
PLAYERS = {
    "C1": ("C", 0, 0),
    "C2": ("C", 0, 0),
    "B1": ("1B", 0, 0), "B2": ("2B", 0, 0), "B3": ("3B", 0, 0),
    "B4": ("SS", 0, 0), "B5": ("LF", 0, 0), "B6": ("CF", 0, 0),
    "B7": ("RF", 0, 0), "B8": ("1B", 0, 0),
    "GONE": ("SS", 0, 0),      # contract expired: on no roster
    "RET": ("CF", 0, 0),       # retired
    "TRADED": ("2B", 0, 0),    # now with NYY
    "MINOR": ("LF", 0, 0),     # in BAL's AAA
    "SP1": ("P", 1, 0), "SP2": ("P", 1, 0), "CLX": ("P", 1, 0),
}


def _write_players(root, overrides=None):
    rows = dict(PLAYERS)
    rows.update(overrides or {})
    with (root / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["player_id", "first_name", "last_name", "primary_position",
                    "other_positions", "is_pitcher", "injured"])
        for pid, (pos, pitcher, hurt) in rows.items():
            w.writerow([pid, "Pat", pid, pos, "", pitcher, hurt])


def _write_roster(root, team, levels):
    with (root / "rosters" / f"{team}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for level, ids in levels.items():
            for pid in ids:
                w.writerow([pid, level])


def _write_lineup(root, team, vs, rows):
    with (root / "lineups" / f"{team}_vs_{vs}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["order", "player_id", "position"])
        for i, (pid, pos) in enumerate(rows, start=1):
            w.writerow([i, pid, pos])


GOOD_LINEUP = [("C1", "C"), ("B1", "1B"), ("B2", "2B"), ("B3", "3B"), ("B4", "SS"),
               ("B5", "LF"), ("B6", "CF"), ("B7", "RF"), ("B8", "DH")]


@pytest.fixture
def league(tmp_path, monkeypatch):
    root = tmp_path / "data"
    for sub in ("rosters", "lineups", "depth_charts"):
        (root / sub).mkdir(parents=True)
    (root / "teams.csv").write_text(TEAMS_CSV, encoding="utf-8")
    (root / "users.txt").write_text(
        "commish,pass,admin,\nbal_owner,pass,owner,BAL\nnyy_owner,pass,owner,NYY\n",
        encoding="utf-8",
    )
    _write_players(root)
    (root / "retired_players.json").write_text(
        json.dumps({"RET": {"player_id": "RET"}}), encoding="utf-8"
    )
    _write_roster(root, "BAL", {
        "ACT": ["C1", "C2", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "SP1", "SP2"],
        "AAA": ["MINOR"],
    })
    _write_roster(root, "NYY", {"ACT": ["TRADED"]})
    for vs in ("lhp", "rhp"):
        _write_lineup(root, "BAL", vs, GOOD_LINEUP)
    (root / "rosters" / "BAL_pitching.csv").write_text("SP1,SP1\nSP2,SP2\n", encoding="utf-8")

    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()

    import api.routers.season as season

    monkeypatch.setattr(season, "_read_season_deadline", lambda: None)
    monkeypatch.setattr("utils.trade_utils.load_trades", lambda: [])
    set_phase(monkeypatch, "PRESEASON")
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def set_phase(monkeypatch, phase):
    import api.routers.season as season

    manager = SimpleNamespace(
        phase=SimpleNamespace(value=phase),
        phase_after_draft=lambda: SimpleNamespace(value="REGULAR_SEASON"),
    )
    monkeypatch.setattr(season, "SeasonManager", lambda: manager)


def _stale_lineups(root):
    """BAL's lineups after the rollover: four players it no longer has."""
    lhp = [("C1", "C"), ("B1", "1B"), ("TRADED", "2B"), ("B3", "3B"), ("GONE", "SS"),
           ("MINOR", "LF"), ("RET", "CF"), ("B7", "RF"), ("B8", "DH")]
    rhp = [("C1", "C"), ("B1", "1B"), ("B2", "2B"), ("B3", "3B"), ("GONE", "SS"),
           ("B5", "LF"), ("B6", "CF"), ("B7", "RF"), ("B8", "DH")]
    _write_lineup(root, "BAL", "lhp", lhp)
    _write_lineup(root, "BAL", "rhp", rhp)


def _items(team="BAL"):
    import api.routers.season as season

    return {i["kind"]: i for i in season.team_action_items(team)}


def _hashes(root):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# --- the report ----------------------------------------------------------------


def test_clean_club_has_nothing_to_report(league):
    from services.lineup_checks import catcher_report, stale_assignments

    report = stale_assignments("BAL")
    assert report["lineups"] == [] and report["staff"] == [] and report["depth_chart"] == []
    assert catcher_report("BAL")["healthy_active"] == 2
    assert "lineup_stale" not in _items() and "no_catcher" not in _items()


def test_lineup_players_are_named_with_where_they_are_now(league):
    from services.lineup_checks import stale_assignments

    _stale_lineups(league)
    got = {e["player_id"]: e for e in stale_assignments("BAL")["lineups"]}
    assert got["GONE"]["note"] == "left the club"
    assert got["GONE"]["sides"] == ["LHP", "RHP"]  # listed once, both sides
    assert got["RET"]["note"] == "retired"
    assert got["TRADED"]["note"] == "now with NYY"
    assert got["MINOR"]["note"] == "in AAA"
    assert got["RET"]["sides"] == ["LHP"]
    assert set(got) == {"GONE", "RET", "TRADED", "MINOR"}


def test_staff_roles_held_by_inactive_pitchers(league):
    from services.lineup_checks import stale_assignments

    (league / "rosters" / "BAL_pitching.csv").write_text(
        "SP1,SP1\nSP2,SP2\nCLX,CL\n", encoding="utf-8"
    )
    staff = stale_assignments("BAL")["staff"]
    assert [(e["player_id"], e["position"], e["note"]) for e in staff] == [
        ("CLX", "CL", "left the club")
    ]


def test_depth_chart_flags_only_players_who_left_the_organisation(league):
    from services.lineup_checks import stale_assignments

    (league / "depth_charts" / "BAL.json").write_text(
        json.dumps({"SS": ["B4", "GONE"], "LF": ["B5", "MINOR"], "CF": ["RET"]}),
        encoding="utf-8",
    )
    gone = {e["player_id"]: e["note"] for e in stale_assignments("BAL")["depth_chart"]}
    # A minor leaguer listed as depth is the owner's choice, not an error.
    assert gone == {"GONE": "left the club", "RET": "retired"}


# --- the Spotlight ---------------------------------------------------------------


def test_spotlight_item_before_opening_day(league, monkeypatch):
    _stale_lineups(league)
    (league / "rosters" / "BAL_pitching.csv").write_text(
        "SP1,SP1\nSP2,SP2\nCLX,CL\n", encoding="utf-8"
    )
    item = _items()["lineup_stale"]
    assert item["title"] == "Update your lineups and pitching staff"
    assert item["href"] == "/lineup"
    assert "Open staff roles: CL." in item["detail"]
    assert item["count"] == 5
    assert {p["player_id"] for p in item["players"]} == {"GONE", "RET", "TRADED", "MINOR", "CLX"}

    set_phase(monkeypatch, "OFFSEASON")
    assert "lineup_stale" in _items()
    # In season a game rebuilds the lineup and posts its own news item.
    set_phase(monkeypatch, "REGULAR_SEASON")
    assert "lineup_stale" not in _items()


def test_only_owner_clubs_get_the_items(league):
    (league / "users.txt").write_text(
        "commish,pass,admin,\nnyy_owner,pass,owner,NYY\n", encoding="utf-8"
    )
    _stale_lineups(league)
    assert "lineup_stale" not in _items("BAL")


def test_no_catcher_item_in_every_phase(league, monkeypatch):
    # C1 hurt on the active roster, C2 on the injured list: no one to catch.
    _write_players(league, {"C1": ("C", 0, 1)})
    _write_roster(league, "BAL", {
        "ACT": ["C1", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "SP1", "SP2"],
        "DL15": ["C2"],
    })
    for phase, severity in (("PLAYOFFS", "action"), ("REGULAR_SEASON", "action"),
                            ("PRESEASON", "action"), ("OFFSEASON", "warning")):
        set_phase(monkeypatch, phase)
        item = _items()["no_catcher"]
        assert item["severity"] == severity
        assert {p["player_id"]: p["note"] for p in item["players"]} == {
            "C1": "injured", "C2": "on the injured list"
        }
        assert "None of your other catchers can play yet" in item["detail"]
        # No free-agent advice in the playoffs.
        assert ("sign a free agent" in item["detail"]) == (phase != "PLAYOFFS")


def test_no_catcher_names_one_to_promote(league):
    _write_roster(league, "BAL", {
        "ACT": ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "SP1", "SP2"],
        "DL15": ["C1"], "AAA": ["C2"],
    })
    item = _items()["no_catcher"]
    assert "Promote Pat C2 from the minors, or sign a free agent." in item["detail"]


def test_no_catcher_anywhere_says_sign_one(league):
    _write_roster(league, "BAL", {
        "ACT": ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "SP1", "SP2"],
    })
    item = _items()["no_catcher"]
    assert item["players"] == []
    assert "There is no other catcher in your organization; sign a free agent." in item["detail"]


# --- the readiness board: notes, never issues -----------------------------------


def test_readiness_notes_but_still_ready(league, monkeypatch):
    import api.routers.season as season

    _stale_lineups(league)
    _write_players(league, {"C1": ("C", 0, 1)})
    _write_roster(league, "BAL", {
        "ACT": ["C1", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "SP1", "SP2"],
        "AAA": ["MINOR"], "DL15": ["C2"],
    })
    notes = season._team_readiness_notes("BAL")
    assert any("no healthy catcher" in n for n in notes)
    assert any("Lineups name players not on the active roster" in n and "GONE" in n
               for n in notes)
    # A stale lineup is not a readiness issue: the not-ready list drives the
    # scheduled runs' CPU fill of an owner's roster.
    issues = season._team_lineup_issues("BAL")
    assert not any("GONE" in i for i in issues)


def test_reading_writes_nothing(league):
    import api.routers.season as season
    from services.lineup_checks import catcher_report, stale_assignments

    _stale_lineups(league)
    before = _hashes(league)
    stale_assignments("BAL")
    catcher_report("BAL")
    season.team_action_items("BAL")
    season._team_readiness_notes("BAL")
    assert _hashes(league) == before


# --- the rollover notice ------------------------------------------------------------


def test_rollover_notice_mentions_stale_lineups(league, monkeypatch):
    from services import roster_shortfall

    _stale_lineups(league)
    (league / "offseason_departures.json").write_text(
        json.dumps({"year": 2027, "teams": {"BAL": {
            "retired": [{"player_id": "RET", "name": "Pat RET", "position": "CF"}],
            "contract_expired": [{"player_id": "GONE", "name": "Pat GONE", "position": "SS"}],
        }}}),
        encoding="utf-8",
    )
    posted = []
    monkeypatch.setattr(
        "utils.news_logger.log_news_event", lambda msg, **k: posted.append(msg)
    )
    monkeypatch.setattr(roster_shortfall, "_notify_owner", lambda *a, **k: None)
    roster_shortfall.notify_owner_shortfalls()
    bal = [m for m in posted if m.startswith("BAL")]
    assert bal and "Your lineups still name players who are not on your active roster" in bal[0]
