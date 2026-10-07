"""Owner play settings on the Team Settings API (Release 3, Q11/Q13/Q14).

GET /teams/{team_id}/settings carries a ``play`` block (resolved values,
defaults, the owner's explicit choices and whether an owner runs the club);
PUT /teams/{team_id}/settings/play stores choices through
services.team_play_settings, owner-only. Runs in a tmp data dir.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from services.team_play_settings import (
    AUTO_REST_DAYS,
    IL_AUTO_ACTIVATE_15,
    IL_AUTO_ACTIVATE_60,
    REST_SUBS_SIMILAR_POSITIONS,
    SETTINGS_FILENAME,
    TEAM_PLAY_SETTING_KEYS,
)

TEAM = "T1"
OWNER = {"u": "owner1", "r": "user", "t": TEAM}
RIVAL = {"u": "rival", "r": "user", "t": "T2"}
ADMIN = {"u": "commish", "r": "admin", "t": ""}


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "rosters").mkdir(parents=True)
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,"
        "primary_color,secondary_color,owner_id\n"
        f"{TEAM},Cats,City,{TEAM},East,Cat Park,#112233,#FFFFFF,\n"
        "T2,Dogs,Town,T2,East,Dog Park,#332211,#FFFFFF,\n",
        encoding="utf-8",
    )
    (root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\n",
        encoding="utf-8",
    )
    (root / "users.txt").write_text(
        f"owner1,pw,user,{TEAM}\ncommish,pw,admin,\n", encoding="utf-8"
    )
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    try:
        from utils.team_loader import load_teams

        load_teams.cache_clear()  # type: ignore[attr-defined]
    except AttributeError:
        pass
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def _router():
    import api.routers.team_settings as ts

    return ts


def test_get_settings_carries_the_play_defaults(data_dir):
    play = _router().get_settings(TEAM)["play"]
    assert play["keys"] == list(TEAM_PLAY_SETTING_KEYS)
    assert play["overrides"] == {}
    assert play["settings"] == play["defaults"]
    assert play["defaults"][AUTO_REST_DAYS] is True
    assert play["defaults"][REST_SUBS_SIMILAR_POSITIONS] is True
    assert play["defaults"][IL_AUTO_ACTIVATE_60] is False
    assert play["owner_managed"] is True


def test_the_15_day_default_follows_the_league_il_setting(data_dir):
    from utils.league_settings import auto_activate_il, load_league_settings

    play = _router().get_play_settings(TEAM)
    assert play["defaults"][IL_AUTO_ACTIVATE_15] is bool(
        auto_activate_il(load_league_settings(data_dir / "league_settings.json"))
    )


def test_cpu_club_is_reported_as_not_owner_managed(data_dir):
    assert _router().get_play_settings("T2")["owner_managed"] is False


def test_owner_saves_choices_and_default_clears_them(data_dir):
    ts = _router()
    out = ts.save_play_settings(
        TEAM,
        {"settings": {AUTO_REST_DAYS: False, IL_AUTO_ACTIVATE_60: True}},
        identity=OWNER,
    )
    assert out["overrides"] == {AUTO_REST_DAYS: False, IL_AUTO_ACTIVATE_60: True}
    assert out["settings"][AUTO_REST_DAYS] is False
    assert out["settings"][IL_AUTO_ACTIVATE_60] is True
    stored = json.loads((data_dir / SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert stored["teams"][TEAM] == {AUTO_REST_DAYS: False, IL_AUTO_ACTIVATE_60: True}

    # Keys left out keep their value; "default" clears a choice.
    out = ts.save_play_settings(TEAM, {"settings": {AUTO_REST_DAYS: "default"}}, identity=OWNER)
    assert out["overrides"] == {IL_AUTO_ACTIVATE_60: True}
    assert ts.get_settings(TEAM)["play"]["settings"][AUTO_REST_DAYS] is True


def test_a_bare_map_is_accepted(data_dir):
    out = _router().save_play_settings(TEAM, {REST_SUBS_SIMILAR_POSITIONS: "off"}, identity=ADMIN)
    assert out["overrides"] == {REST_SUBS_SIMILAR_POSITIONS: False}


def test_another_owner_is_refused_and_nothing_is_written(data_dir):
    with pytest.raises(HTTPException) as exc:
        _router().save_play_settings(TEAM, {"settings": {AUTO_REST_DAYS: False}}, identity=RIVAL)
    assert exc.value.status_code == 403
    assert not (data_dir / SETTINGS_FILENAME).exists()


@pytest.mark.parametrize(
    "settings",
    [{"no_such_setting": True}, {AUTO_REST_DAYS: "sometimes"}],
)
def test_bad_input_is_a_400_and_writes_nothing(data_dir, settings):
    with pytest.raises(HTTPException) as exc:
        _router().save_play_settings(TEAM, {"settings": settings}, identity=OWNER)
    assert exc.value.status_code == 400
    assert not (data_dir / SETTINGS_FILENAME).exists()


def test_settings_must_be_an_object(data_dir):
    with pytest.raises(HTTPException) as exc:
        _router().save_play_settings(TEAM, {"settings": [AUTO_REST_DAYS]}, identity=OWNER)
    assert exc.value.status_code == 400


def test_unknown_team_is_a_404(data_dir):
    with pytest.raises(HTTPException) as exc:
        _router().save_play_settings("ZZZ", {"settings": {}}, identity=ADMIN)
    assert exc.value.status_code == 404


def test_play_write_is_in_the_ownership_sweep():
    """The router-table sweep (test_team_scoped_write_ownership) covers it."""
    import inspect

    ts = _router()
    paths = {
        (route.path, tuple(sorted(route.methods)))
        for route in ts.router.routes
    }
    assert ("/teams/{team_id}/settings/play", ("PUT",)) in paths
    assert "require_team_owner(" in inspect.getsource(ts.save_play_settings)
