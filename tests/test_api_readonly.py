"""Read-only endpoint smoke tests.

Verifies each router at least serves a 200 against a seeded temp data
root. These are happy-path sanity checks -- not deep behavioral tests --
but they catch import errors and basic schema regressions.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path

import pytest

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="nexgen-readonly-test-"))
os.environ["NEXGEN_DATA_ROOT"] = str(_TMP_ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402


def _seed(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "users.txt").write_text("admin,pass,admin,\n", encoding="utf-8")

    with (root / "teams.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "team_id",
            "name",
            "city",
            "abbreviation",
            "division",
            "stadium",
            "primary_color",
            "secondary_color",
            "owner_id",
        ])
        writer.writerow(
            ["TST", "Testers", "Testville", "TST", "East", "Test Park", "#123456", "#ABCDEF", ""]
        )

    (root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\n",
        encoding="utf-8",
    )
    (root / "schedule.csv").write_text(
        "date,home,away,result,played,boxscore\n",
        encoding="utf-8",
    )
    (root / "standings.json").write_text(
        json.dumps({"teams": []}),
        encoding="utf-8",
    )
    (root / "season_stats.json").write_text(
        json.dumps({"players": {}, "teams": {}}),
        encoding="utf-8",
    )
    (root / "news_feed.txt").write_text("", encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    _seed(_TMP_ROOT)
    c = TestClient(create_app())
    token = c.post(
        "/auth/login", json={"username": "admin", "password": "pass"}
    ).json()["token"]
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


@pytest.mark.parametrize(
    "path",
    [
        "/leagues",
        "/teams",
        "/standings",
        "/standings/league",
        "/schedule",
        "/players?limit=10",
        "/news?limit=10",
        "/activity?limit=10",
        "/league/leaders?limit=5",
        "/league/stats",
        "/league/history",
        "/playoffs/years",
    ],
)
def test_readonly_endpoint(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200, f"{path} -> {response.status_code} {response.text}"


def test_teams_detail(client: TestClient) -> None:
    # Seeded team above
    response = client.get("/teams/TST")
    assert response.status_code == 200
    body = response.json()
    assert body["team_id"] == "TST"
    assert body["city"] == "Testville"
