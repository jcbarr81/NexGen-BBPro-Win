"""A player who leaves a club comes off its lineups, depth chart and staff
the moment the roster write happens (8.4.1, ``services.departure_cleanup``).

Through ``save_roster`` / ``save_rosters`` (trades, releases, contract
expiry, CPU moves) and retirement's roster scrub. A move inside the
organisation (sent down, injured list) changes nothing.
"""

from __future__ import annotations

import csv
import json
from types import SimpleNamespace

import pytest

from models.roster import Roster

LINEUP = [("C1", "C"), ("B1", "1B"), ("B2", "2B"), ("B3", "3B"), ("SS1", "SS"),
          ("B5", "LF"), ("B6", "CF"), ("B7", "RF"), ("B8", "DH")]
ACT = ["C1", "C2", "B1", "B2", "B3", "SS1", "SS2", "B5", "B6", "B7", "B8", "U1",
       "P1", "P2", "P3"]


def _p(pid, pos, score=50, injured=False, other=()):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions=list(other),
        injured=injured, is_pitcher=(pos == "P"), ch=score, ph=score,
        first_name="Pat", last_name=pid,
    )


PLAYERS = {
    "C1": _p("C1", "C"), "C2": _p("C2", "C"),
    "B1": _p("B1", "1B"), "B2": _p("B2", "2B"), "B3": _p("B3", "3B"),
    "SS1": _p("SS1", "SS"), "SS2": _p("SS2", "SS", score=40),
    "B5": _p("B5", "LF"), "B6": _p("B6", "CF"), "B7": _p("B7", "RF"),
    "B8": _p("B8", "1B"), "U1": _p("U1", "LF", score=70),
    "P1": _p("P1", "P"), "P2": _p("P2", "P"), "P3": _p("P3", "P"),
}


def _write_lineup(root, team, vs, rows):
    with (root / "lineups" / f"{team}_vs_{vs}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["order", "player_id", "position"])
        for i, (pid, pos) in enumerate(rows, start=1):
            w.writerow([i, pid, pos])


def _read_lineup(root, team, vs):
    with (root / "lineups" / f"{team}_vs_{vs}.csv").open(newline="", encoding="utf-8") as fh:
        return [(r["player_id"], r["position"]) for r in csv.DictReader(fh)]


def _write_roster(root, team, levels):
    with (root / "rosters" / f"{team}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for level, ids in levels.items():
            for pid in ids:
                w.writerow([pid, level])


@pytest.fixture
def league(tmp_path, monkeypatch):
    root = tmp_path / "data"
    for sub in ("rosters", "lineups", "depth_charts"):
        (root / sub).mkdir(parents=True)
    (root / "users.txt").write_text(
        "commish,pass,admin,\nbal_owner,pass,owner,BAL\n", encoding="utf-8"
    )
    (root / "players.csv").write_text("player_id\n", encoding="utf-8")
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id\n"
        "BAL,O,B,BAL,E,S,#000000,#FFFFFF,\nNYY,Y,N,NYY,E,S,#000000,#FFFFFF,\n",
        encoding="utf-8",
    )
    _write_roster(root, "BAL", {"ACT": ACT, "AAA": ["M1"]})
    _write_roster(root, "NYY", {"ACT": ["N1"]})
    for vs in ("lhp", "rhp"):
        _write_lineup(root, "BAL", vs, LINEUP)
    (root / "rosters" / "BAL_pitching.csv").write_text(
        "P1,SP1\nP2,SP2\nP3,CL\n", encoding="utf-8"
    )
    (root / "depth_charts" / "BAL.json").write_text(
        json.dumps({"SS": ["SS1", "SS2"], "CF": ["B6", "SS1"], "C": ["C1", "C2"]}),
        encoding="utf-8",
    )
    (root / "depth_charts" / "_auto.json").write_text(json.dumps(["BAL"]), encoding="utf-8")

    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    import services.departure_cleanup as dc

    monkeypatch.setattr(dc, "_players_by_id", lambda data_dir: dict(PLAYERS))
    news = []
    monkeypatch.setattr(
        "utils.news_logger.log_news_event",
        lambda msg, **k: news.append((msg, k.get("team_id"))),
    )
    from utils.roster_loader import load_roster

    load_roster.cache_clear()
    yield SimpleNamespace(root=root, news=news)
    load_roster.cache_clear()
    path_utils._DATA_DIR_CACHE.clear()


def _save(root, team, levels, **extra):
    from utils.roster_loader import save_roster

    save_roster(team, Roster(team_id=team, **levels, **extra), roster_dir=root / "rosters")


def _bal_without(*gone, aaa=("M1",)):
    return {"act": [p for p in ACT if p not in gone], "aaa": list(aaa)}


# --- a release (save_roster) ---------------------------------------------------


def test_released_player_leaves_lineup_depth_chart_and_staff(league):
    root = league.root
    _save(root, "BAL", _bal_without("SS1", "P3"))
    for vs in ("lhp", "rhp"):
        rows = _read_lineup(root, "BAL", vs)
        assert ("SS2", "SS") in rows  # the depth chart's next shortstop
        assert "SS1" not in [pid for pid, _ in rows]
        # Only his slot changed: same order, same positions.
        assert [pos for _, pos in rows] == [pos for _, pos in LINEUP]
        assert [pid for pid, _ in rows if pid != "SS2"] == [
            pid for pid, _ in LINEUP if pid != "SS1"
        ]
    chart = json.loads((root / "depth_charts" / "BAL.json").read_text(encoding="utf-8"))
    assert chart["SS"] == ["SS2"] and chart["CF"] == ["B6"]
    # The chart is still automation's.
    assert json.loads((root / "depth_charts" / "_auto.json").read_text()) == ["BAL"]
    staff = (root / "rosters" / "BAL_pitching.csv").read_text(encoding="utf-8").split()
    assert staff == ["P1,SP1", "P2,SP2"]


def test_owner_hears_who_took_the_spot(league):
    _save(league.root, "BAL", _bal_without("SS1", "P3"))
    assert len(league.news) == 1
    msg, team = league.news[0]
    assert team == "BAL"
    assert "Pat SS2 replaces Pat SS1 at SS (vs LHP and vs RHP)" in msg
    assert "Open pitching-staff roles: CL." in msg


def test_cpu_club_is_cleaned_without_news(league):
    root = league.root
    (root / "users.txt").write_text("commish,pass,admin,\n", encoding="utf-8")
    _save(root, "BAL", _bal_without("SS1"))
    assert "SS1" not in [pid for pid, _ in _read_lineup(root, "BAL", "lhp")]
    assert league.news == []


def test_a_move_inside_the_organisation_changes_nothing(league):
    root = league.root
    before = {p.name: p.read_bytes() for p in root.rglob("*") if p.is_file()
              and p.parent.name in ("lineups", "depth_charts")}
    _save(root, "BAL", {"act": [p for p in ACT if p != "SS1"], "aaa": ["M1", "SS1"]})
    _save(root, "BAL", {"act": [p for p in ACT if p != "SS1"], "aaa": ["M1"], "dl": ["SS1"]})
    after = {p.name: p.read_bytes() for p in root.rglob("*") if p.is_file()
             and p.parent.name in ("lineups", "depth_charts")}
    assert after == before
    assert "P3,CL" in (root / "rosters" / "BAL_pitching.csv").read_text(encoding="utf-8")
    assert league.news == []


# --- a trade (save_rosters) ------------------------------------------------------


def test_traded_player_leaves_the_old_club_only(league):
    from utils.roster_loader import save_rosters

    root = league.root
    (root / "depth_charts" / "NYY.json").write_text(
        json.dumps({"C": ["N1"]}), encoding="utf-8"
    )
    save_rosters(
        {
            "BAL": Roster(team_id="BAL", act=[p for p in ACT if p != "SS1"] + ["N1"], aaa=["M1"]),
            "NYY": Roster(team_id="NYY", act=["SS1"]),
        },
        roster_dir=root / "rosters",
    )
    assert ("SS2", "SS") in _read_lineup(root, "BAL", "rhp")
    chart = json.loads((root / "depth_charts" / "BAL.json").read_text(encoding="utf-8"))
    assert "SS1" not in chart["SS"]
    # Each club loses the player it gave up, and only him.
    nyy = json.loads((root / "depth_charts" / "NYY.json").read_text(encoding="utf-8"))
    assert nyy["C"] == []


def test_no_one_can_cover_the_slot_rebuilds_that_lineup(league, monkeypatch):
    root = league.root
    calls = []

    def fake_fill(team_id, *, vs=None, **kw):
        calls.append((team_id, vs, kw["lineup_dir"]))
        _write_lineup(root, team_id, vs, [(p, pos) for p, pos in LINEUP if p != "C1"]
                      + [("C2", "C")])

    monkeypatch.setattr("utils.lineup_autofill.auto_fill_lineup_for_team", fake_fill)
    # Both catchers leave: nobody left can catch.
    _save(root, "BAL", _bal_without("C1", "C2"))
    assert [(t, vs) for t, vs, _ in calls] == [("BAL", "lhp"), ("BAL", "rhp")]
    assert calls[0][2] == root / "lineups"
    msg = league.news[0][0]
    assert "your lineup vs LHP and vs RHP was rebuilt by auto-fill without Pat C1, as no active player" in msg


# --- retirement's roster scrub ----------------------------------------------------


def test_retirement_scrub_clears_lineups(league):
    from services.player_retirement import _scrub_rosters

    root = league.root
    _scrub_rosters(root / "rosters", {"SS1", "P3"})
    assert "SS1" not in [pid for pid, _ in _read_lineup(root, "BAL", "lhp")]
    chart = json.loads((root / "depth_charts" / "BAL.json").read_text(encoding="utf-8"))
    assert "SS1" not in chart["SS"]
    assert "P3" not in (root / "rosters" / "BAL_pitching.csv").read_text(encoding="utf-8")


# --- the report now lists open roles --------------------------------------------


def test_open_roles_reach_the_spotlight_report(league, monkeypatch):
    from services.lineup_checks import stale_assignments

    root = league.root
    (root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\n"
        + "".join(f"{pid},Pat,{pid},{p.primary_position},{int(p.is_pitcher)}\n"
                  for pid, p in PLAYERS.items()),
        encoding="utf-8",
    )
    _save(root, "BAL", _bal_without("P3"))
    report = stale_assignments("BAL")
    assert report["staff"] == []
    assert "CL" in report["open_roles"]
