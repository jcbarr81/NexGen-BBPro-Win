"""Backlog #35: a commissioner picks their own club in the league wizard.

The wizard only knows each club's city and name (team ids are assigned
when the league is built), so it sends ``team: {city, name}`` and the
server matches it against the new league's teams.csv.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import api.routers.league_create as LC
from services import firestore_store, memberships

DIVISIONS = {
    "East": [{"city": "Boston", "name": "Pilgrims"}, {"city": "Austin", "name": "Bats"}],
    "West": [{"city": "Denver", "name": "Peaks"}],
}


@pytest.fixture
def created(tmp_path, monkeypatch):
    calls = {"built": 0, "member": None, "provision": None}
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "BOS,Pilgrims,Boston,BOS,East,Park,#000000,#ffffff,\n"
        "AUS,Bats,Austin,AUS,East,Park,#000000,#ffffff,\n"
        "DEN,Peaks,Denver,DEN,West,Park,#000000,#ffffff,\n",
        encoding="utf-8",
    )

    def build(payload):
        calls["built"] += 1
        return {"league_id": "new-league", "display_name": "New", "warnings": []}

    monkeypatch.setattr(LC, "_build_league", build)
    monkeypatch.setattr(
        LC.league_registry, "get_league_data_dir", lambda league_id, create=False: data_dir
    )
    monkeypatch.setattr(
        firestore_store, "get_account", lambda uid: {"package": "commissioner", "handle": "jb"}
    )
    monkeypatch.setattr(firestore_store, "upsert_league", lambda *a, **k: None)
    monkeypatch.setattr(
        firestore_store, "set_member", lambda *a, **k: calls.__setitem__("member", k)
    )
    monkeypatch.setattr(
        memberships, "provision_user", lambda *a: calls.__setitem__("provision", a)
    )
    return calls, data_dir


def _create(team=None):
    payload = {"display_name": "New", "divisions": DIVISIONS}
    if team is not None:
        payload["team"] = team
    return LC.create_league_as_commissioner(payload, account={"uid": "u1"})


def test_the_picked_club_becomes_the_commissioners(created):
    calls, _ = created
    result = _create({"city": "Austin", "name": "Bats"})
    assert result["team_id"] == "AUS"
    assert calls["member"]["team_id"] == "AUS"
    assert calls["provision"] == ("u1", "commissioner", "AUS")


def test_no_pick_means_no_club(created):
    calls, _ = created
    assert _create()["team_id"] == ""
    assert calls["member"]["team_id"] == ""


def test_a_club_not_in_the_league_is_refused_before_anything_is_built(created):
    calls, _ = created
    with pytest.raises(HTTPException) as err:
        _create({"city": "Austin", "name": "Nope"})
    assert err.value.status_code == 400
    assert calls["built"] == 0


def test_a_pick_the_new_league_lacks_is_a_warning_not_a_failure(created):
    calls, data_dir = created
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n",
        encoding="utf-8",
    )
    result = _create({"city": "Austin", "name": "Bats"})
    assert result["team_id"] == ""
    assert any("Members & Email" in w for w in result["warnings"])
    assert calls["member"]["team_id"] == ""
