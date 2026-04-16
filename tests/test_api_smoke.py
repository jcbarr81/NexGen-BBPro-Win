"""Smoke tests for the Phase 1 FastAPI sidecar.

Exercises the paths Electron hits on startup:

- ``GET /healthz`` reports version + data root.
- ``POST /auth/login`` authenticates against ``users.txt`` (bcrypt or
  legacy plaintext ``pass``).
- Protected routes reject missing/invalid tokens and accept signed ones.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point the sidecar at a temp data root BEFORE importing anything that caches
# the path (utils.path_utils does module-level caching via env-keyed keys).
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="nexgen-api-test-"))
os.environ["NEXGEN_DATA_ROOT"] = str(_TMP_ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    # Seed a minimal users.txt with the legacy default admin credentials so
    # verify_user_password accepts the plaintext fallback.
    users_file = _TMP_ROOT / "users.txt"
    users_file.parent.mkdir(parents=True, exist_ok=True)
    users_file.write_text("admin,pass,admin,\n", encoding="utf-8")
    return TestClient(create_app())


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["data_root"]


def test_login_success_and_protected_route(client: TestClient) -> None:
    response = client.post("/auth/login", json={"username": "admin", "password": "pass"})
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    assert token

    # Protected endpoint rejects anonymous calls.
    anon = client.get("/leagues")
    assert anon.status_code == 401

    # And accepts the signed token.
    authed = client.get("/leagues", headers={"Authorization": f"Bearer {token}"})
    assert authed.status_code == 200
    assert isinstance(authed.json(), list)


def test_login_rejects_bad_password(client: TestClient) -> None:
    response = client.post("/auth/login", json={"username": "admin", "password": "nope"})
    assert response.status_code == 401
