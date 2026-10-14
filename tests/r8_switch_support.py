"""Scratch leagues for the 8.0.0 switch tests (test_r8_switch_*.py).

Built on the Release 5 switch-on support (tests/r5_flip_support.py): every
league lives under pytest's ``tmp_path`` (teams, players, users and rosters
are written before the data dir is resolved), and is made the request
league. Nothing here touches a real league.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tests.r5_flip_support import (  # noqa: F401  (re-exported)
    CALIBRATION,
    LEAGUE,
    game_tuning,
    make_league,
    play_days,
    roll_over,
    stored_generation,
    witness,
    write_schedule,
)
from utils.rating_scale import GENERATION6_SWITCH_ENV

REPO = Path(__file__).resolve().parents[1]
CALIBRATION_LEAGUE = REPO / "data" / "calibration_league"
SWITCH = GENERATION6_SWITCH_ENV


def switch_on(monkeypatch) -> None:
    monkeypatch.setenv(SWITCH, "1")
    _clear()


def switch_off(monkeypatch) -> None:
    monkeypatch.delenv(SWITCH, raising=False)
    _clear()


def _clear() -> None:
    from services import league_rating_centers as centers
    from services import rating_scale_migration as migration

    centers.clear_rating_center_cache()
    migration.clear_caches()


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """A scratch league (the calibration fixture), active, no schedule, the
    switch OFF; the caches cleared before and after."""
    from utils import path_utils

    monkeypatch.delenv(SWITCH, raising=False)
    data = make_league(tmp_path, monkeypatch)
    _clear()
    yield data
    _clear()
    path_utils._REQUEST_LEAGUE.set(None)
    path_utils._DATA_DIR_CACHE.clear()


def read_rows(path: Path) -> tuple[list[str], list[dict]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def header(path: Path) -> list[str]:
    return read_rows(path)[0]


def scale_log(data: Path) -> dict:
    path = data / "rating_scale.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def news(data: Path) -> str:
    path = data / "news_feed.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def archive_a_season(data: Path) -> None:
    """Give the league a finished season on record (career_index.json), as a
    league that has played before has."""
    (data / "career_index.json").write_text(
        json.dumps({"seasons": [{"season_id": "2025"}]}), encoding="utf-8"
    )


def clip_an_active_player(data: Path) -> str:
    """Give one ACT hitter an Eye of 20 (stored 50 + 3 * (20 - 50) < 1 on
    scale 2); his id."""
    fields, rows = read_rows(data / "players.csv")
    active = set()
    for roster in (data / "rosters").glob("*.csv"):
        if roster.stem.endswith("_pitching"):
            continue
        for line in roster.read_text(encoding="utf-8").splitlines():
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip() == "ACT":
                active.add(parts[0].strip())
    for row in rows:
        if row["player_id"] in active and row["is_pitcher"] in ("0", "False", "false"):
            row["eye"] = "20"
            target = row["player_id"]
            break
    with (data / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return target
