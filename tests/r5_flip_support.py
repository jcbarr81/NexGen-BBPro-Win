"""Scratch leagues for the Release 5 switch-on tests (test_r5_flip_*.py).

Never a real league: every league here lives under pytest's ``tmp_path``,
built from the calibration fixture. The recipe is the project's safe one --
teams.csv, players.csv, users.txt and the rosters are written BEFORE
anything resolves the data dir (a league folder missing those three is
seeded with a copy of the repo's ``data/``), then ``NEXGEN_DATA_ROOT`` and
the request league point at it.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
LEAGUE = "r5flip"
ADMIN = {"u": "commish", "r": "admin"}
NEW_SEASON_ENGINE_ENV = "NEXGEN_NEW_SEASON_ENGINE"


def copy_fixture(source: Path, dest: Path) -> Path:
    """A fixture's league files (teams, players, rosters, lineups) in ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    _copy_players(source / "players.csv", dest / "players.csv")
    shutil.copy(source / "teams.csv", dest / "teams.csv")
    shutil.copytree(source / "rosters", dest / "rosters")
    shutil.copytree(source / "lineups", dest / "lineups")
    return dest


def make_league(
    tmp_path,
    monkeypatch,
    league_id: str = LEAGUE,
    *,
    activate=True,
    source: Path = CALIBRATION,
) -> Path:
    """A scratch league's data dir; with ``activate`` it is the request league.

    The suite pins new seasons to the legacy engine (tests/conftest.py); a
    league made here follows the product's rule instead.
    """
    from utils import path_utils

    monkeypatch.delenv(NEW_SEASON_ENGINE_ENV, raising=False)
    root = tmp_path / "root"
    data = root / "leagues" / league_id / "data"
    data.mkdir(parents=True)
    (root / "players.csv").write_text("player_id\n", encoding="utf-8")
    copy_fixture(source, data)
    (data / "users.txt").write_text("", encoding="utf-8")
    if activate:
        monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
        monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
        path_utils._DATA_DIR_CACHE.clear()
        activate_league(monkeypatch, league_id)
        assert path_utils.get_data_dir().resolve() == data.resolve()
        seeded = {p.name for p in data.iterdir()}
        assert not seeded & {
            "schedule.csv", "season_progress.json", "standings.json",
            "career_index.json", "rating_centers.json",
            "physics_tuning_overrides.json",
        }, sorted(seeded)
    return data


def activate_league(monkeypatch, league_id: str = LEAGUE) -> None:
    """Make ``league_id`` the request league (the ``league`` fixture clears
    it when the test ends)."""
    from utils import path_utils

    path_utils.set_request_league(league_id)


@pytest.fixture
def league(tmp_path, monkeypatch):
    """The scratch league, active, with no schedule yet."""
    from utils import path_utils

    data = make_league(tmp_path, monkeypatch)
    yield data
    path_utils._REQUEST_LEAGUE.set(None)
    path_utils._DATA_DIR_CACHE.clear()


def _copy_players(src: Path, dest: Path) -> None:
    """The calibration players with blank pitch ratings filled in (the
    league loader requires a number where the KPI harness reads a blank)."""
    with src.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        for key in ("fb", "cu", "cb", "sl", "si", "scb", "kn"):
            if key in row and row[key] == "":
                row[key] = "0"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def team_ids(data: Path) -> list[str]:
    lines = (data / "teams.csv").read_text(encoding="utf-8").splitlines()[1:]
    return [line.split(",")[0] for line in lines if line.strip()]


def write_schedule(data: Path, year: int, *, days: int = 6, played: int = 0) -> None:
    """A short ``schedule.csv`` for ``year`` with ``played`` days finished,
    and the progress and standings files a season in that state has."""
    teams = team_ids(data)
    rows = ["date,home,away,result,played,boxscore"]
    for day in range(days):
        done = day < played
        rows.append(
            f"{year}-04-{day + 1:02d},{teams[0]},{teams[1]},"
            f"{'5-3' if done else ''},{'1' if done else ''},"
        )
    (data / "schedule.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    # As the product writes season_progress.json outside a rollover: the
    # keys it sets are changed and everything else in the file is kept (the
    # season's engine generation witness is in there).
    progress_path = data / "season_progress.json"
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        progress = {}
    if not isinstance(progress, dict):
        progress = {}
    progress.update({"preseason_done": {"schedule": True}, "sim_index": played})
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    standings = {}
    if played:
        standings = {
            teams[0]: {"wins": played, "losses": 0},
            teams[1]: {"wins": 0, "losses": played},
        }
    (data / "standings.json").write_text(json.dumps(standings), encoding="utf-8")


def play_days(data: Path, days: int) -> None:
    """Mark the first ``days`` days of the current schedule played, as the
    season router does when a sim call ends."""
    year = int((data / "schedule.csv").read_text().splitlines()[1][:4])
    total = len((data / "schedule.csv").read_text().splitlines()) - 1
    write_schedule(data, year, days=total, played=days)


def roll_over(data: Path, year: int) -> None:
    """End the ``year`` season the way the product does: archive it in the
    season context and run the rollover's own reset of the active state
    (schedule deleted, stats, standings and the schedule cursor cleared)."""
    from playbalance.season_context import SeasonContext
    from services.league_rollover import LeagueRolloverService

    ctx = SeasonContext.load()
    ctx.ensure_league(name="Scratch", league_id=LEAGUE)
    ctx.ensure_current_season(league_year=year)
    service = LeagueRolloverService(ctx)
    ctx.archive_current_season()
    service._reset_active_state(year)
    assert not (data / "schedule.csv").exists()
    assert json.loads((data / "career_index.json").read_text())["seasons"]


def witness(data: Path):
    """The season's generation as ``season_progress.json`` records it:
    ``(season key, generation)``, or None when it records none."""
    path = data / "season_progress.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8")).get("engine_generation")
    if record is None:
        return None
    return record["season"], record["generation"]


def drop_witness(data: Path) -> None:
    """Take the generation witness out of ``season_progress.json``, leaving
    the rest of the file as it is."""
    path = data / "season_progress.json"
    progress = json.loads(path.read_text(encoding="utf-8"))
    progress.pop("engine_generation", None)
    path.write_text(json.dumps(progress), encoding="utf-8")


def stored_generation(data: Path, season: str | int):
    """What ``rating_centers.json`` records for a season: the number, None
    for an entry without one, or "no entry"."""
    path = data / "rating_centers.json"
    if not path.exists():
        return "no entry"
    entry = json.loads(path.read_text(encoding="utf-8"))["seasons"].get(str(season))
    if entry is None:
        return "no entry"
    return entry.get("engine_generation")


class _Captured(Exception):
    pass


def game_tuning(monkeypatch, date_token: str | None = None) -> dict:
    """The tuning ``playbalance.game_runner`` hands the engine for a game of
    the active league right now (every league getter is the real one; only
    the player loading and the engine itself are stubbed).

    ``date_token`` is the game's date: a season game has one, an exhibition
    (the default here) has none."""
    import physics_sim.data_loader as loader
    import physics_sim.engine as engine
    import playbalance.game_runner as gr

    batters = {f"B{i}": SimpleNamespace(player_id=f"B{i}") for i in range(18)}
    arms = {f"P{i}": SimpleNamespace(player_id=f"P{i}") for i in range(2)}
    seen: dict = {}

    def fake_simulate_game(**kwargs):
        seen.update(kwargs)
        raise _Captured

    def state(offset):
        return SimpleNamespace(
            lineup=[
                SimpleNamespace(player_id=f"B{i + offset}", position="CF")
                for i in range(9)
            ],
            bench=[],
            pitchers=[
                SimpleNamespace(
                    player_id=f"P{offset // 9}", assigned_pitching_role="SP1"
                )
            ],
            team=None,
        )

    with monkeypatch.context() as patch:
        patch.setattr(loader, "load_players_by_id", lambda path: (batters, arms))
        patch.setattr(engine, "simulate_game", fake_simulate_game)
        with pytest.raises(_Captured):
            gr._run_physics_game(
                home_id="H", away_id="A", home_state=state(0), away_state=state(9),
                players_file=str(CALIBRATION / "players.csv"), roster_dir="rosters",
                seed=1, date_token=date_token, tracker=None, players_lookup={},
                persist_stats=False, postseason=False,
            )
    return seen["tuning_overrides"]
