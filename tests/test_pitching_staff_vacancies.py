"""The staff screen shows a role whose pitcher can't pitch as vacant.

Trades never touched the old team's ``{team}_pitching.csv``: HOU kept Erich
Zenk as its closer after trading him, and seven alpha-test clubs listed a
pitcher they no longer had. The screen put him in the slot, the sim silently
ignored him, and saving failed validation until the owner found and removed
him. Pitchers sent down or hurt are in the same position: games only use the
active roster.
"""

import csv

import pytest

import api.routers.lineups as L
from models.roster import Roster


@pytest.fixture
def staff_file(tmp_path, monkeypatch):
    def build(rows, roster):
        path = tmp_path / "TST_pitching.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        monkeypatch.setattr(L, "_pitching_path", lambda team_id: path)
        monkeypatch.setattr(L, "load_roster", lambda team_id: roster)
        monkeypatch.setattr(
            "api.routers.validation.load_players_map",
            lambda: {"P9": {"first_name": "Erich", "last_name": "Zenk"}},
        )
        return path

    return build


def test_departed_demoted_and_injured_pitchers_are_listed_as_vacancies(staff_file):
    roster = Roster("TST", act=["P1", "P2"], aaa=["P3"], low=["P4"], dl=["P5"])
    staff_file(
        [("P1", "SP1"), ("P2", "SP2"), ("P3", "SP3"), ("P4", "SP4"), ("P5", "SU"), ("P9", "CL")],
        roster,
    )
    out = L.get_pitching_staff("TST")
    assert out["staff"] == [
        {"player_id": "P1", "role": "SP1"},
        {"player_id": "P2", "role": "SP2"},
    ]
    reasons = {e["role"]: e["reason"] for e in out["inactive"]}
    assert reasons == {
        "SP3": "in AAA",
        "SP4": "in Low-A",
        "SU": "on the injured list",
        "CL": "no longer with the team",
    }
    names = {e["player_id"]: e["name"] for e in out["inactive"]}
    assert names["P9"] == "Erich Zenk"
    assert names["P3"] == "P3"           # unknown to players.csv: fall back to the id


def test_reading_leaves_the_file_alone(staff_file):
    """A pitcher recalled before the owner's next save gets his role back."""
    path = staff_file([("P1", "SP1"), ("P3", "SP2")], Roster("TST", act=["P1"], aaa=["P3"]))
    before = path.read_text()
    L.get_pitching_staff("TST")
    assert path.read_text() == before


def test_a_fully_active_staff_has_no_vacancies(staff_file):
    staff_file([("P1", "SP1"), ("P2", "CL")], Roster("TST", act=["P1", "P2"]))
    out = L.get_pitching_staff("TST")
    assert len(out["staff"]) == 2
    assert out["inactive"] == []
