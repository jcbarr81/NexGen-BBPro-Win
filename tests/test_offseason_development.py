"""The rollover's development step and spring camp, on scale 1 and scale 2.

Scale 1 must not move at all: the rollover step neither reads past the
header nor writes, and a scale 1 camp gives exactly the files 7.51.2's camp
gave (golden hashes taken from commit 04364883a's ``training_camp`` on the
same scenario). Scale 2 rows develop in place: only rating and potential
cells change, every other cell and every scale 1 row stays as it was.
"""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import random
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from playbalance.player_development import TrainingWeights
from services import league_rollover
from services import offseason_development as od
from tests import rating_scale_support as support
from utils.rating_scale import RATING_SCALE_FIELD

MOVED = ("ch", "ph", "eye", "fa", "arm", "sp", "control", "movement", "endurance",
         "hold_runner", "fb", "cu", "cb", "sl", "si", "scb", "kn")
DEVELOPED = set(MOVED) | {f"pot_{k}" for k in MOVED}


@pytest.fixture
def no_history(monkeypatch, tmp_path):
    """Training history goes to a temp folder, never the repo's data."""

    from services import training_history

    reports = tmp_path / "training_reports"
    monkeypatch.setattr(training_history, "_reports_dir", lambda: reports)
    monkeypatch.setattr(training_history, "_resolve_season_id", lambda: "test-2027")
    return reports


def _league(tmp_path, *, scale2: bool, rows: int = 200) -> Path:
    league = support.copy_league(support.FIXTURES["calibration_league"], tmp_path / "lg")
    fields, all_rows = support.read_player_rows(league / "players.csv")
    support.write_player_rows(league / "players.csv", fields, all_rows[:rows])
    if not scale2:
        return league
    twin = tmp_path / "twin"
    support.write_stretched_twin(league, twin)
    return twin


# --- scale 1: nothing moves ------------------------------------------------

def test_a_scale_1_league_is_neither_read_nor_written(tmp_path, no_history):
    league = _league(tmp_path, scale2=False)
    path = league / "players.csv"
    before, stamp = path.read_bytes(), path.stat().st_mtime_ns
    assert od.run_offseason_development(season_year=2027, data_dir=league) is None
    assert path.read_bytes() == before and path.stat().st_mtime_ns == stamp
    assert not (league / od.DEVELOPMENT_RECORD).exists()
    assert not no_history.exists()


def test_the_rollover_step_is_a_no_op_on_scale_1(tmp_path, monkeypatch, no_history):
    league = _league(tmp_path, scale2=False)
    monkeypatch.setattr(league_rollover, "_DATA_DIR", league)
    service = type("S", (), {"context": type("C", (), {"league_id": "t"})()})()
    before = (league / "players.csv").read_bytes()
    assert league_rollover.LeagueRolloverService._apply_yearly_development(service, 2027) is None
    league_rollover.LeagueRolloverService._apply_yearly_aging(service)  # paused
    assert (league / "players.csv").read_bytes() == before


def test_development_runs_after_the_archive_and_before_retirements():
    source = inspect.getsource(league_rollover.LeagueRolloverService.archive_season)
    archive = source.index("archive_current_season(")
    develop = source.index("_apply_yearly_development(")
    retire = source.index("run_yearly_retirements(")
    assert archive < develop < retire
    assert '"development_error"' in source  # a failure is reported, not swallowed


# Taken with playbalance/training_camp.py of 04364883a on this scenario.
GOLDEN_CAMP = (
    "a225faa6e2e6cd67c20625f6b3766c6aec82555720890d234431a4f4408dd741",
    "ce834177685eb5ab138b775fde03ce0b4e28a2e9952afa7ba2a08c6c835fe7ed",
    "81efd9bb538356673f671cfafb18271b685e9867609197c0d4093f943b94027e",
)


def test_a_scale_1_camp_gives_todays_files(tmp_path, monkeypatch):
    from playbalance import training_camp
    from utils.player_writer import save_players_to_csv

    monkeypatch.setenv("PB_SIM_DATE", "2026-03-01")
    league = support.copy_league(support.FIXTURES["calibration_league"], tmp_path / "lg")
    players = list(support.load_player_objects(league).values())[:120]
    recorded = []
    monkeypatch.setattr(training_camp, "record_training_session",
                        lambda reports: recorded.append(list(reports)))
    weights = TrainingWeights(
        hitters={"contact": 40, "power": 20, "speed": 10, "discipline": 15, "defense": 15},
        pitchers={"command": 20, "movement": 20, "stamina": 20, "velocity": 20,
                  "hold": 5, "pitch_lab": 15},
    )
    random.seed(11)
    reports = training_camp.run_training_camp(
        players,
        allocations={p.player_id: weights for p in players[::2]},
        intensity_by_player={p.player_id: 1.12 for p in players[::3]},
    )
    out = tmp_path / "players.csv"
    save_players_to_csv(players, str(out))
    got = (
        hashlib.sha256(out.read_bytes()).hexdigest(),
        hashlib.sha256(json.dumps([asdict(r) for r in reports], sort_keys=True).encode()).hexdigest(),
        hashlib.sha256(json.dumps([[asdict(r) for r in b] for b in recorded],
                                  sort_keys=True).encode()).hexdigest(),
    )
    assert got == GOLDEN_CAMP


# --- scale 2: rows develop in place ----------------------------------------

def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def test_scale_2_rows_develop_and_nothing_else_changes(tmp_path, no_history):
    league = _league(tmp_path, scale2=True)
    path = league / "players.csv"
    fields, rows = _rows(path)
    # Two rows put back on scale 1 (a mixed file): they must not move.
    plain = {rows[0]["player_id"], rows[1]["player_id"]}
    _, source_rows = _rows(tmp_path / "lg" / "players.csv")
    by_id = {r["player_id"]: r for r in source_rows}
    for i in (0, 1):
        rows[i] = {k: by_id[rows[i]["player_id"]].get(k, "") for k in fields}
        rows[i][RATING_SCALE_FIELD] = ""
    support.write_player_rows(path, fields, rows)
    before_fields, before = _rows(path)

    summary = od.run_offseason_development(
        season_year=2027, data_dir=league, as_of=date(2026, 10, 31)
    )
    assert summary and summary["players"] == len(before) - 2
    assert summary["improved"] > 20 and summary["declined"] > 20
    after_fields, after = _rows(path)
    assert after_fields == before_fields
    assert [r["player_id"] for r in after] == [r["player_id"] for r in before]
    changed = 0
    for old, new in zip(before, after):
        for key in before_fields:
            if old["player_id"] in plain or key not in DEVELOPED:
                assert new[key] == old[key], (old["player_id"], key)
            elif new[key] != old[key]:
                changed += 1
        if old["player_id"] in plain:
            continue
        for key in MOVED:
            value = new.get(key, "")
            if value in ("", "0"):
                assert value == old.get(key, "")  # no rating is invented
                continue
            assert 1 <= int(value) <= 99
            pot = new.get(f"pot_{key}", "")
            if pot not in ("", "0"):
                assert int(value) <= int(pot) <= 99
    assert changed > 100
    record = json.loads((league / od.DEVELOPMENT_RECORD).read_text(encoding="utf-8"))
    assert record["season"] == 2027 and record["players"]
    history = json.loads((no_history / "test-2027.json").read_text(encoding="utf-8"))
    assert history["runs"][0]["reports"][0]["tier"] == od.DEVELOPMENT_TIER


def test_the_same_rollover_gives_the_same_file(tmp_path, no_history):
    a = _league(tmp_path / "a", scale2=True)
    b = _league(tmp_path / "b", scale2=True)
    for league in (a, b):
        od.run_offseason_development(
            season_year=2027, data_dir=league, as_of=date(2026, 10, 31), record=False
        )
    assert (a / "players.csv").read_bytes() == (b / "players.csv").read_bytes()


def test_camp_reports_the_offseason_without_touching_a_scale_2_player(tmp_path, monkeypatch):
    from playbalance import training_camp

    league = _league(tmp_path, scale2=True, rows=12)
    players = list(support.load_player_objects(league).values())
    pid = players[0].player_id
    monkeypatch.setattr(training_camp, "_offseason_development",
                        lambda: {pid: {"focus": "Barrel Control", "changes": {"ch": 4}}})
    recorded = []
    monkeypatch.setattr(training_camp, "record_training_session",
                        lambda reports: recorded.append(list(reports)))
    before = [dict(vars(p)) for p in players]
    reports = training_camp.run_training_camp(players)
    assert reports[0].changes == {"ch": 4} and reports[0].focus == "Barrel Control"
    assert all(r.changes == {} for r in reports[1:])
    assert recorded == [[]]  # already in the history from the rollover
    for player, was in zip(players, before):
        assert player.ready
        assert {k: v for k, v in vars(player).items() if k != "ready"} == {
            k: v for k, v in was.items() if k != "ready"
        }
