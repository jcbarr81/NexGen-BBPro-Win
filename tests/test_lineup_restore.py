"""A returning starter goes back in the lineup when the depth chart says so.

Going on the injured list and coming off it were not symmetrical. The injury
dropped the player from the active roster, which left the stored lineup a man
short, so the sim rebuilt it and a replacement took the spot. Activation put
him back on the roster but left a valid nine in place, so nothing rebuilt the
lineup and the regular starter sat behind his own backup for good.
"""

import csv
from pathlib import Path

import pytest

from services.lineup_restore import positions_led_by, restore_depth_chart_starter
from utils import depth_chart as dc


LINEUP_POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]


@pytest.fixture
def team(tmp_path, monkeypatch):
    """A team with a depth chart, a lineup, and the starter displaced."""
    data_dir = tmp_path / "data"
    (data_dir / "lineups").mkdir(parents=True)
    monkeypatch.setattr(dc, "_chart_path", lambda tid: data_dir / f"{tid}_depth.json")

    # STAR tops centre field; BACKUP is second and currently playing there.
    chart = {pos: [] for pos in LINEUP_POSITIONS}
    chart["CF"] = ["STAR", "BACKUP"]
    dc.save_depth_chart("T", chart)

    def write_lineup(vs, cf_player="BACKUP"):
        path = data_dir / "lineups" / f"T_vs_{vs}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["order", "player_id", "position"])
            for i, pos in enumerate(LINEUP_POSITIONS, start=1):
                w.writerow([i, cf_player if pos == "CF" else f"P{i}", pos])
        return path

    return {"dir": data_dir, "lineups": data_dir / "lineups", "write": write_lineup}


def _read(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_returning_starter_takes_his_position_back(team):
    lhp = team["write"]("lhp")
    rhp = team["write"]("rhp")

    changed = restore_depth_chart_starter(
        "T", "STAR", lineup_dir=team["lineups"], active_ids=["STAR", "BACKUP"]
    )

    assert changed == {"lhp": "CF", "rhp": "CF"}
    for path in (lhp, rhp):
        rows = _read(path)
        cf = next(r for r in rows if r["position"] == "CF")
        assert cf["player_id"] == "STAR"
        assert "BACKUP" not in [r["player_id"] for r in rows]


def test_the_rest_of_the_batting_order_is_left_alone(team):
    """Surgical on purpose — regenerating the lineup would throw away an order
    the owner may have set by hand."""
    path = team["write"]("lhp")
    before = _read(path)

    restore_depth_chart_starter(
        "T", "STAR", lineup_dir=team["lineups"], active_ids=["STAR", "BACKUP"]
    )
    after = _read(path)

    assert [r["order"] for r in after] == [r["order"] for r in before]
    assert [r["position"] for r in after] == [r["position"] for r in before]
    # Exactly one seat changed hands.
    diffs = [
        (b["player_id"], a["player_id"])
        for b, a in zip(before, after)
        if b["player_id"] != a["player_id"]
    ]
    assert diffs == [("BACKUP", "STAR")]


def test_player_not_first_on_the_chart_stays_on_the_bench(team):
    """Only the depth chart's starter is reinstated — a backup coming off the
    list doesn't get to displace whoever is playing."""
    path = team["write"]("lhp", cf_player="STAR")

    changed = restore_depth_chart_starter(
        "T", "BACKUP", lineup_dir=team["lineups"], active_ids=["STAR", "BACKUP"]
    )

    assert changed == {}
    cf = next(r for r in _read(path) if r["position"] == "CF")
    assert cf["player_id"] == "STAR"


def test_already_in_the_lineup_is_a_no_op(team):
    path = team["write"]("lhp", cf_player="STAR")
    before = _read(path)

    assert restore_depth_chart_starter("T", "STAR", lineup_dir=team["lineups"]) == {}
    assert _read(path) == before


def test_missing_lineup_is_left_for_the_autofill(team):
    """No file means the sim will build one from scratch, honouring the chart."""
    assert restore_depth_chart_starter("T", "STAR", lineup_dir=team["lineups"]) == {}
    assert not (team["lineups"] / "T_vs_lhp.csv").exists()


def test_player_absent_from_the_chart_is_left_alone(team):
    team["write"]("lhp")
    assert positions_led_by("T", "NOBODY") == []
    assert restore_depth_chart_starter("T", "NOBODY", lineup_dir=team["lineups"]) == {}


def test_player_not_on_the_active_roster_is_not_installed(team):
    """Belt and braces: never put someone in the lineup who can't play."""
    path = team["write"]("lhp")
    changed = restore_depth_chart_starter(
        "T", "STAR", lineup_dir=team["lineups"], active_ids=["BACKUP"]
    )
    assert changed == {}
    cf = next(r for r in _read(path) if r["position"] == "CF")
    assert cf["player_id"] == "BACKUP"


def test_positions_led_by_reports_every_position_he_tops(team):
    chart = dc.load_depth_chart("T")
    chart["LF"] = ["STAR"]
    dc.save_depth_chart("T", chart)
    assert sorted(positions_led_by("T", "STAR")) == ["CF", "LF"]


def test_restoring_is_idempotent(team):
    path = team["write"]("lhp")
    first = restore_depth_chart_starter(
        "T", "STAR", lineup_dir=team["lineups"], active_ids=["STAR", "BACKUP"]
    )
    after_first = _read(path)
    second = restore_depth_chart_starter(
        "T", "STAR", lineup_dir=team["lineups"], active_ids=["STAR", "BACKUP"]
    )
    assert first and second == {}
    assert _read(path) == after_first
