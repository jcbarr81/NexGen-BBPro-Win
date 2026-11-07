"""Only the commissioner advances a multi-owner league, whatever file says so (8.12.3).

The sim and phase guards asked ``league_settings.json`` whether a league is
multi-owner, but no production path ever writes that file: a cloud league
records ``owner_league`` only in the league registry. Every league therefore
read as single-player and any owner could sim the whole league from the
header's +1 day / +1 wk / +1 mo buttons (reproduced on a copy of alpha-test's
setup, 2026-11-07). The permission check now also reads the registry; the
finance flows that ask ``is_owner_league`` keep reading the file only.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from utils import league_settings as LS


def _registry(monkeypatch, mode, *, league_id="alpha-test"):
    import services.league_registry as reg
    import utils.path_utils as pu

    monkeypatch.setattr(pu, "get_active_league_id", lambda **kw: league_id)
    if mode is None:
        monkeypatch.setattr(reg, "get_league", lambda lid: None)
    elif mode == "boom":
        def _boom(lid):
            raise OSError("registry unreadable")
        monkeypatch.setattr(reg, "get_league", _boom)
    else:
        monkeypatch.setattr(reg, "get_league", lambda lid: SimpleNamespace(id=lid, mode=mode))


SOLO_FILE = {"mode": "single_player"}


def test_a_registered_owner_league_stops_owners_without_a_settings_file(monkeypatch):
    _registry(monkeypatch, "owner_league")
    assert LS.can_run_season_progression("owner", settings=SOLO_FILE) is False
    assert LS.can_run_season_progression("", settings=SOLO_FILE) is False


def test_the_commissioner_still_advances_a_registered_owner_league(monkeypatch):
    _registry(monkeypatch, "owner_league")
    assert LS.can_run_season_progression("admin", settings=SOLO_FILE) is True
    assert LS.can_run_season_progression("commissioner", settings=SOLO_FILE) is True


def test_a_registered_single_player_league_lets_the_owner_sim(monkeypatch):
    _registry(monkeypatch, "single_player")
    assert LS.can_run_season_progression("owner", settings=SOLO_FILE) is True


@pytest.mark.parametrize("mode", [None, "boom"])
def test_without_a_registry_answer_the_settings_file_decides(monkeypatch, mode):
    _registry(monkeypatch, mode)
    assert LS.can_run_season_progression("owner", settings=SOLO_FILE) is True
    assert LS.can_run_season_progression("owner", settings={"mode": "owner_league"}) is False


def test_the_finance_flag_still_reads_only_the_settings_file(monkeypatch):
    # GM finance review and the offseason finance flow ask is_owner_league;
    # switching them on for live leagues would be a separate decision.
    _registry(monkeypatch, "owner_league")
    assert LS.is_owner_league(SOLO_FILE) is False


def test_the_sim_endpoint_guard_refuses_an_owner(monkeypatch):
    from api.routers import season

    _registry(monkeypatch, "owner_league")
    monkeypatch.setattr(LS, "load_league_settings", lambda path=None: dict(SOLO_FILE))
    with pytest.raises(HTTPException) as err:
        season._require_season_progression({"r": "owner", "t": "WAS"})
    assert err.value.status_code == 403
    season._require_season_progression({"r": "admin", "t": ""})
