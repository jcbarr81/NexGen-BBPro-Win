import os
from pathlib import Path

from models.roster import Roster
from utils import path_utils
from utils.recovery_manager import (
    clear_recovery,
    needs_recovery,
    recovery_path_for_data_file,
    write_recovery_csv,
)
from utils.roster_io import read_roster_csv, write_roster_csv


def _set_data_dir(monkeypatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_dir))
    path_utils._DATA_DIR = None
    return data_dir


def test_recovery_path_for_data_file(monkeypatch, tmp_path):
    data_dir = _set_data_dir(monkeypatch, tmp_path)
    target = recovery_path_for_data_file("data/lineups/test.csv")
    assert target == data_dir / "recovery" / "lineups" / "test.csv"


def test_needs_recovery_when_newer(monkeypatch, tmp_path):
    data_dir = _set_data_dir(monkeypatch, tmp_path)
    data_path = data_dir / "lineups" / "team_vs_lhp.csv"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text("saved", encoding="utf-8")

    write_recovery_csv(data_path, [("1", "P1", "SS")], header=("order", "player_id", "position"))
    assert needs_recovery(data_path) is True


def test_needs_recovery_when_missing_data(monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    data_path = Path("data/lineups/team_vs_rhp.csv")
    write_recovery_csv(data_path, [("1", "P2", "CF")], header=("order", "player_id", "position"))
    assert needs_recovery(data_path) is True


def test_clear_recovery_removes_file(monkeypatch, tmp_path):
    _set_data_dir(monkeypatch, tmp_path)
    data_path = Path("data/lineups/team_vs_rhp.csv")
    recovery_path = write_recovery_csv(data_path, [("1", "P2", "CF")])
    assert recovery_path.exists()
    clear_recovery(data_path)
    assert not recovery_path.exists()


def test_roster_csv_roundtrip(tmp_path):
    roster = Roster(
        team_id="T1",
        act=["A1", "A2"],
        aaa=["A3"],
        low=["A4"],
        dl=["A5"],
        ir=["A6"],
        dl_tiers={"A5": "dl15"},
    )
    path = tmp_path / "roster.csv"
    write_roster_csv(roster, path)
    loaded = read_roster_csv(path, "T1")
    assert loaded.act == roster.act
    assert loaded.aaa == roster.aaa
    assert loaded.low == roster.low
    assert loaded.dl == roster.dl
    assert loaded.ir == roster.ir
    assert loaded.dl_tiers == roster.dl_tiers
