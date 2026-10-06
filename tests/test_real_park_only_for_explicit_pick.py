"""Audit L13: real-park geometry only for an explicitly chosen park.

Generated stadium names are "{mascot} Stadium", so a club named the Royals got
"Royals Stadium" -- an exact ParkConfig name -- and silently played in
Kauffman's 1973-93 dimensions. Real-park data now applies only when a park was
explicitly chosen (the team's ``park_id``); leagues whose teams.csv predates
the column keep the old name lookup.
"""

from __future__ import annotations

import csv
import random

import pytest
from fastapi import HTTPException

from models.team import Team
from physics_sim.park import load_park
from playbalance.field_geometry import Stadium
from utils import park_utils
from utils.park_utils import park_lookup_name, park_lookup_name_for_team
from utils.team_loader import load_teams, save_team_settings

HEADER = (
    "team_id,name,city,abbreviation,division,stadium,"
    "primary_color,secondary_color,owner_id"
)


@pytest.fixture
def park_catalog(tmp_path, monkeypatch):
    """A tiny ParkConfig: KAN06 under both of its names, plus Fenway."""

    parks_dir = tmp_path / "parks"
    parks_dir.mkdir()
    (parks_dir / "ParkConfig.csv").write_text(
        "parkID,NAME,Year,LF_Dim,CF_Dim,RF_Dim,Foul\n"
        "KAN06,Royals Stadium,1992,330,410,330,S\n"
        "KAN06,Kauffman Stadium,2024,330,410,330,N\n"
        "BOS07,Fenway Park,2024,310,390,302,S\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(park_utils, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(park_utils, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(park_utils, "get_base_dir", lambda: tmp_path)
    return tmp_path


def _team(stadium: str, park_id: str | None, name: str = "Royals") -> Team:
    return Team(
        team_id="FOR",
        name=name,
        city="Forest",
        abbreviation="FOR",
        division="East",
        stadium=stadium,
        primary_color="#112233",
        secondary_color="#445566",
        owner_id="",
        park_id=park_id,
    )


# --- the collision ---------------------------------------------------------


def test_generated_name_colliding_with_real_park_gets_generic_park(park_catalog):
    team = _team("Royals Stadium", park_id="")

    assert park_lookup_name_for_team(team) is None
    park = load_park(park_lookup_name_for_team(team))
    generic = Stadium()
    assert (park.stadium.left, park.stadium.center, park.stadium.right) == (
        generic.left,
        generic.center,
        generic.right,
    )
    assert park.foul_territory_scale == 1.0


def test_new_league_writes_empty_park_ids_so_mascot_stadiums_are_generic(
    tmp_path, park_catalog
):
    from playbalance.league_creator import create_league

    random.seed(0)
    league_dir = tmp_path / "league"
    create_league(
        str(league_dir),
        {"East": [("Kansas City", "Royals"), ("Boston", "Pilgrims")]},
        "Collision League",
    )

    with (league_dir / "teams.csv").open(newline="") as fh:
        reader = csv.DictReader(fh)
        assert "park_id" in (reader.fieldnames or [])
        rows = list(reader)
    assert {row["park_id"] for row in rows} == {""}

    teams = {t.name: t for t in load_teams(league_dir / "teams.csv")}
    royals = teams["Royals"]
    assert royals.stadium == "Royals Stadium"
    assert royals.park_id == ""
    assert park_lookup_name_for_team(royals) is None


# --- an explicit pick -------------------------------------------------------


def test_explicit_park_id_applies_that_parks_geometry(park_catalog):
    picked = _team("Fenway Park", park_id="BOS07", name="Pilgrims")

    assert park_lookup_name_for_team(picked) == "Fenway Park"
    park = load_park(park_lookup_name_for_team(picked))
    assert (park.stadium.left, park.stadium.center, park.stadium.right) == (
        310,
        390,
        302,
    )


def test_explicit_park_id_prefers_the_matching_name_then_latest_year(
    park_catalog,
):
    # KAN06 carries two names; the team's stadium name decides which era.
    assert park_lookup_name("Royals Stadium", "KAN06") == "Royals Stadium"
    assert park_lookup_name("Kauffman Stadium", "kan06") == "Kauffman Stadium"
    # A custom display name on an explicit pick gets the latest configuration.
    assert park_lookup_name("The Fountains", "KAN06") == "Kauffman Stadium"
    # An ID no longer in the catalog falls back to the generic park.
    assert park_lookup_name("Royals Stadium", "ZZZ99") is None


def test_legacy_league_without_park_id_column_keeps_name_lookup(
    tmp_path, park_catalog
):
    teams_csv = tmp_path / "teams.csv"
    teams_csv.write_text(
        HEADER + "\nFOR,Royals,Forest,FOR,East,Royals Stadium,#112233,#445566,\n",
        encoding="utf-8",
    )
    (team,) = load_teams(teams_csv)

    assert team.park_id is None
    # No record of what was picked vs generated: behaviour is unchanged.
    assert park_lookup_name_for_team(team) == "Royals Stadium"


# --- persistence ------------------------------------------------------------


def test_save_team_settings_persists_an_explicit_pick(tmp_path, park_catalog):
    teams_csv = tmp_path / "teams.csv"
    teams_csv.write_text(
        HEADER + ",park_id\n"
        "FOR,Royals,Forest,FOR,East,Royals Stadium,#112233,#445566,,\n"
        "BOS,Pilgrims,Boston,BOS,East,Pilgrims Stadium,#111111,#222222,,\n",
        encoding="utf-8",
    )
    (team, _) = load_teams(teams_csv)
    team.stadium = "Kauffman Stadium"
    team.park_id = "KAN06"
    save_team_settings(team, teams_csv)

    reloaded = {t.team_id: t for t in load_teams(teams_csv)}
    assert reloaded["FOR"].park_id == "KAN06"
    assert park_lookup_name_for_team(reloaded["FOR"]) == "Kauffman Stadium"
    assert reloaded["BOS"].park_id == ""


def test_save_team_settings_does_not_add_column_to_legacy_league(tmp_path):
    teams_csv = tmp_path / "teams.csv"
    teams_csv.write_text(
        HEADER + "\nFOR,Royals,Forest,FOR,East,Royals Stadium,#112233,#445566,\n",
        encoding="utf-8",
    )
    (team,) = load_teams(teams_csv)
    team.primary_color = "#abcdef"
    save_team_settings(team, teams_csv)

    with teams_csv.open(newline="") as fh:
        assert "park_id" not in (csv.DictReader(fh).fieldnames or [])
    assert load_teams(teams_csv)[0].park_id is None


# --- the settings endpoint decides what counts as a pick --------------------


def test_settings_resolve_park_id(park_catalog):
    from api.routers.team_settings import _resolve_park_id

    generated = _team("Royals Stadium", park_id="")
    # A colors-only save (stadium echoed back unchanged) is not a pick.
    assert _resolve_park_id(generated, "Royals Stadium", {}) == ""
    # The catalog browser sends the park id explicitly.
    assert (
        _resolve_park_id(generated, "Royals Stadium", {"park_id": "KAN06"})
        == "KAN06"
    )
    # Renaming to an exact catalog name (the suggestion list) picks it...
    assert _resolve_park_id(generated, "Fenway Park", {}) == "BOS07"
    # ...and renaming to anything else clears a pick.
    picked = _team("Fenway Park", park_id="BOS07")
    assert _resolve_park_id(picked, "Our Yard", {}) == ""
    assert _resolve_park_id(picked, "Fenway Park", {"park_id": ""}) == ""
    with pytest.raises(HTTPException) as exc:
        _resolve_park_id(generated, "Royals Stadium", {"park_id": "ZZZ99"})
    assert exc.value.status_code == 400
    # Legacy leagues stay on the name lookup.
    assert _resolve_park_id(_team("Royals Stadium", None), "Fenway Park", {}) is None


def test_settings_endpoint_saves_and_reports_the_pick(
    tmp_path, park_catalog, monkeypatch
):
    from api.routers import team_settings

    teams_csv = tmp_path / "teams.csv"
    teams_csv.write_text(
        HEADER + ",park_id\n"
        "FOR,Royals,Forest,FOR,East,Royals Stadium,#112233,#445566,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(team_settings, "load_teams", lambda: load_teams(teams_csv))
    monkeypatch.setattr(
        team_settings,
        "save_team_settings",
        lambda team: save_team_settings(team, teams_csv),
    )

    class _Resolved:
        profile = label = description = source = "default"
        enabled = False

    monkeypatch.setattr(
        team_settings, "resolve_team_strategy_profile", lambda _tid: _Resolved()
    )
    monkeypatch.setattr(
        team_settings, "resolve_team_auto_reassign", lambda _tid: _Resolved()
    )
    admin = {"r": "admin", "t": ""}

    before = team_settings.get_settings("FOR")
    assert before["park_id"] == "" and before["park"] is None

    after = team_settings.save_settings(
        "FOR",
        {"stadium": "Royals Stadium", "park_id": "KAN06"},
        identity=admin,
    )
    assert after["park_id"] == "KAN06"
    assert after["park"] == {
        "park_id": "KAN06",
        "name": "Royals Stadium",
        "year": 1992,
    }
