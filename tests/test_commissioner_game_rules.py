"""Commissioner "Game rules" card: the extra-innings runner toggle (decision 11).

GET /commissioner/settings reports it, PUT /commissioner/settings/rules sets
it (admin only), and the value lands in the league's league_settings.json,
which game_runner reads before every game.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    # Sentinels so get_data_dir()'s first-run seed does not copy repo data/.
    (data_root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,"
        "primary_color,secondary_color,owner_id\n",
        encoding="utf-8",
    )
    (data_root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\n",
        encoding="utf-8",
    )
    (data_root / "users.txt").write_text("", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir() == data_root
    return data_root


def _client(role: str):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routers import commissioner
    from api.security import require_bearer

    app = FastAPI()
    app.include_router(commissioner.router)
    app.dependency_overrides[require_bearer] = lambda: {"r": role, "t": ""}
    return TestClient(app)


def test_runner_is_on_by_default_and_reported(data_dir):
    resp = _client("admin").get("/commissioner/settings")
    assert resp.status_code == 200
    assert resp.json()["rules"] == {"extra_innings_runner": True}


def test_admin_can_turn_the_runner_off_and_on(data_dir):
    client = _client("admin")
    resp = client.put("/commissioner/settings/rules", json={"extra_innings_runner": False})
    assert resp.status_code == 200
    assert resp.json()["rules"]["extra_innings_runner"] is False
    stored = json.loads((data_dir / "league_settings.json").read_text(encoding="utf-8"))
    assert stored["extra_innings_runner"] is False

    from playbalance.game_runner import _extra_innings_runner_enabled

    assert _extra_innings_runner_enabled() is False
    resp = client.put("/commissioner/settings/rules", json={"extra_innings_runner": True})
    assert resp.json()["rules"]["extra_innings_runner"] is True
    assert _extra_innings_runner_enabled() is True


def test_rules_write_rejects_a_non_boolean(data_dir):
    resp = _client("admin").put("/commissioner/settings/rules", json={"extra_innings_runner": "off"})
    assert resp.status_code == 400
    assert not (data_dir / "league_settings.json").exists()


@pytest.mark.parametrize("role", ["owner", "commissioner", ""])
def test_rules_are_admin_only(data_dir, role):
    client = _client(role)
    assert client.get("/commissioner/settings").status_code == 403
    resp = client.put("/commissioner/settings/rules", json={"extra_innings_runner": False})
    assert resp.status_code == 403
    assert not (data_dir / "league_settings.json").exists()
