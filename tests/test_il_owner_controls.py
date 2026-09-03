"""Owners can work their own injured list.

Both sides of the list used to be entirely machine-driven: the sim placed
players, the automation activated them, and the Injury page was read-only. In
MLB both are team decisions. These pin the rules that keep that from being
abusable — and the default that keeps existing leagues behaving exactly as
they did before owners could touch anything.
"""

from datetime import date

import pytest

from utils import league_settings as ls


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "league_settings.json"
    monkeypatch.setattr(ls, "_settings_path", lambda p=None: path)
    return path


# --- the toggle -------------------------------------------------------------


def test_auto_activation_is_on_by_default(settings_file):
    """A league that has never heard of this setting must behave exactly as it
    did before it existed."""
    assert ls.auto_activate_il() is True
    assert ls.auto_activate_il({}) is True


def test_toggle_roundtrips(settings_file):
    ls.set_auto_activate_il(False)
    assert ls.auto_activate_il() is False
    ls.set_auto_activate_il(True)
    assert ls.auto_activate_il() is True


def test_toggle_leaves_other_settings_alone(settings_file):
    ls.save_league_settings({"mode": "owner_league", "commissioner_password": "x"})
    ls.set_auto_activate_il(False)
    payload = ls.load_league_settings()
    assert payload["mode"] == "owner_league"
    assert payload["commissioner_password"] == "x"
    assert payload[ls.AUTO_ACTIVATE_IL_KEY] is False


# --- who the automation holds back -----------------------------------------


@pytest.fixture
def automation(monkeypatch, tmp_path):
    import services.dl_automation as dl

    monkeypatch.setattr(dl, "get_data_dir", lambda: tmp_path)
    return dl


def test_nobody_is_held_back_while_the_setting_is_on(automation, monkeypatch):
    monkeypatch.setattr("utils.league_settings.auto_activate_il", lambda: True)
    monkeypatch.setattr(
        "services.finance_ai._human_owned_team_ids", lambda d: {"HUM"}
    )
    assert automation._teams_managing_their_own_il(None) == set()


def test_only_human_teams_are_held_back(automation, monkeypatch):
    """CPU clubs must keep activating themselves — nobody is watching them, and
    a stranded player would sit there for the rest of the season."""
    monkeypatch.setattr("utils.league_settings.auto_activate_il", lambda: False)
    monkeypatch.setattr(
        "services.finance_ai._human_owned_team_ids", lambda d: {"HUM", "HUM2"}
    )
    held = automation._teams_managing_their_own_il(None)
    assert held == {"HUM", "HUM2"}
    assert "CPU" not in held


def test_a_broken_settings_read_fails_open(automation, monkeypatch):
    """If the setting can't be read, keep activating — the old behaviour — so a
    bad file can't quietly strand every injured player in the league."""

    def boom():
        raise RuntimeError("no settings")

    monkeypatch.setattr("utils.league_settings.auto_activate_il", boom)
    assert automation._teams_managing_their_own_il(None) == set()


def test_batch_runs_ignore_the_setting(automation, monkeypatch):
    """The long-run sim harness has no owner to wait on."""
    monkeypatch.setattr("utils.league_settings.auto_activate_il", lambda: False)
    monkeypatch.setattr("services.finance_ai._human_owned_team_ids", lambda d: {"HUM"})
    monkeypatch.setattr(automation, "load_players_from_csv", lambda *a, **k: [])
    monkeypatch.setattr(automation, "load_teams", lambda *a, **k: [])

    summary = automation.process_disabled_lists(force_auto_activate=True)
    assert summary.awaiting_owner == []


# --- the endpoints ----------------------------------------------------------


def test_place_requires_team_ownership():
    """Another owner must not be able to shelve your players."""
    from fastapi import HTTPException

    from api.security import require_team_owner

    with pytest.raises(HTTPException) as exc:
        require_team_owner({"u": "someone", "r": "user", "t": "OTHER"}, "MINE")
    assert exc.value.status_code == 403


def test_admin_may_act_for_any_team():
    from api.security import require_team_owner

    require_team_owner({"u": "commish", "r": "admin", "t": ""}, "ANY")


def test_owner_may_act_for_their_own_team():
    from api.security import require_team_owner

    require_team_owner({"u": "owner", "r": "user", "t": "MINE"}, "MINE")


def test_endpoints_are_registered():
    import api.routers.injuries as inj

    paths = {(tuple(sorted(r.methods)), r.path) for r in inj.router.routes}
    assert (("POST",), "/teams/{team_id}/injuries/{player_id}/place") in paths
    assert (("POST",), "/teams/{team_id}/injuries/{player_id}/activate") in paths


def test_il_settings_endpoints_are_registered():
    import api.routers.season as season

    paths = [r.path for r in season.router.routes if r.path.endswith("il-settings")]
    assert len(paths) == 2  # GET for everyone, POST for the commissioner


# --- the rules the endpoints enforce ---------------------------------------


class _Player:
    def __init__(self, injured=True, position="CF"):
        self.player_id = "p1"
        self.first_name = "A"
        self.last_name = "B"
        self.injured = injured
        self.primary_position = position
        self.is_pitcher = position == "P"
        self.injury_list = None
        self.injury_minimum_days = None


def test_a_healthy_player_cannot_be_shelved(monkeypatch):
    """MLB needs a medical reason; without this an owner could park a slumping
    bat on the list to free an active-roster spot."""
    import api.routers.injuries as inj
    from fastapi import HTTPException
    from models.roster import Roster

    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    monkeypatch.setattr(inj, "_load_team", lambda tid: (roster, lambda *a: None))
    monkeypatch.setattr(inj, "_find_player", lambda pid: _Player(injured=False))

    with pytest.raises(HTTPException) as exc:
        inj.place_on_list("T", "p1", payload={}, identity={"r": "admin", "t": ""})
    assert exc.value.status_code == 409
    assert "isn't injured" in str(exc.value.detail)


def test_only_an_active_player_can_be_placed(monkeypatch):
    import api.routers.injuries as inj
    from fastapi import HTTPException
    from models.roster import Roster

    roster = Roster(team_id="T", act=[], aaa=["p1"], low=[])
    monkeypatch.setattr(inj, "_load_team", lambda tid: (roster, lambda *a: None))
    monkeypatch.setattr(inj, "_find_player", lambda pid: _Player())

    with pytest.raises(HTTPException) as exc:
        inj.place_on_list("T", "p1", payload={}, identity={"r": "admin", "t": ""})
    assert exc.value.status_code == 409


def test_activate_rejects_a_player_who_is_not_on_a_list(monkeypatch):
    import api.routers.injuries as inj
    from fastapi import HTTPException
    from models.roster import Roster

    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    monkeypatch.setattr(inj, "_load_team", lambda tid: (roster, lambda *a: None))
    monkeypatch.setattr(inj, "_find_player", lambda pid: _Player())

    with pytest.raises(HTTPException) as exc:
        inj.activate_from_list("T", "p1", payload={}, identity={"r": "admin", "t": ""})
    assert exc.value.status_code == 409


def test_activate_rejects_a_bad_destination(monkeypatch):
    import api.routers.injuries as inj
    from fastapi import HTTPException
    from models.roster import Roster

    roster = Roster(team_id="T", act=[], aaa=[], low=[])
    roster.dl = ["p1"]
    monkeypatch.setattr(inj, "_load_team", lambda tid: (roster, lambda *a: None))
    monkeypatch.setattr(inj, "_find_player", lambda pid: _Player())

    with pytest.raises(HTTPException) as exc:
        inj.activate_from_list(
            "T", "p1", payload={"destination": "moon"}, identity={"r": "admin", "t": ""}
        )
    assert exc.value.status_code == 400
