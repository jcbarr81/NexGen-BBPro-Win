"""Release 3 live-path fix: players.csv and roster files are written atomically.

``save_players_to_csv`` and ``write_roster_csv`` opened the target with
``"w"`` and refilled it row by row, so a parallel-day worker reading
``players.csv`` saw a torn file (16 of 525 games fell back to serial in the
live-path run) -- and a cut on a row boundary would parse cleanly, silently
dropping players. Both now write a temp file beside the target and swap it
in with ``os.replace``.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

import utils.atomic_write as atomic_write
from models.pitcher import Pitcher
from models.player import Player
from models.roster import Roster
from utils.atomic_write import atomic_text_writer
from utils.player_writer import save_players_to_csv
from utils.roster_io import read_roster_csv, write_roster_csv


def _hitter(i: int) -> Player:
    return Player(
        player_id=f"H{i:05d}", first_name="Pat", last_name=f"Hitter{i}",
        birthdate="1995-01-01", height=72, weight=190, bats="R",
        primary_position="CF", other_positions=["LF", "RF"], gf=50,
    )


def _pitcher(i: int) -> Pitcher:
    return Pitcher(
        player_id=f"P{i:05d}", first_name="Sam", last_name=f"Arm{i}",
        birthdate="1996-02-02", height=74, weight=200, bats="R",
        primary_position="P", other_positions=[], gf=50,
        endurance=60, control=55, movement=50, hold_runner=40,
        fb=60, cu=40, cb=45, sl=50, si=0, scb=0, kn=0, arm=60, fa=50,
    )


def _players(n: int) -> list:
    return [_hitter(i) if i % 2 else _pitcher(i) for i in range(n)]


@pytest.fixture
def replace_spy(monkeypatch):
    calls: list[tuple[Path, Path]] = []
    real = os.replace

    def _spy(src, dst):
        calls.append((Path(src), Path(dst)))
        return real(src, dst)

    monkeypatch.setattr(atomic_write.os, "replace", _spy)
    return calls


def _no_temp_left(directory: Path) -> bool:
    return not [p for p in directory.iterdir() if p.name.endswith(".tmp")]


def test_save_players_swaps_in_a_finished_file(tmp_path, replace_spy):
    target = tmp_path / "players.csv"
    target.write_text("player_id\nOLD\n", encoding="utf-8")
    save_players_to_csv(_players(20), str(target))

    assert len(replace_spy) == 1
    src, dst = replace_spy[0]
    assert dst == target
    assert src.parent == target.parent and src != target
    lines = target.read_text().splitlines()
    assert lines[0].startswith("player_id,")
    assert len(lines) == 21
    assert _no_temp_left(tmp_path)


def test_write_roster_swaps_in_a_finished_file(tmp_path, replace_spy):
    target = tmp_path / "rosters" / "AAA.csv"
    roster = Roster(team_id="AAA", act=["a1", "a2"], aaa=["b1"], low=["c1"],
                    dl=["d1"], ir=["e1"], dl_tiers={"d1": "il10"})
    write_roster_csv(roster, target)
    write_roster_csv(roster, target)

    assert [dst for _src, dst in replace_spy] == [target, target]
    back = read_roster_csv(target, "AAA")
    assert back.act == ["a1", "a2"] and back.aaa == ["b1"] and back.low == ["c1"]
    assert back.dl == ["d1"] and back.ir == ["e1"]
    assert _no_temp_left(target.parent)


def test_a_failed_write_leaves_the_old_file(tmp_path):
    target = tmp_path / "players.csv"
    target.write_text("player_id\nOLD\n", encoding="utf-8")

    class _Broken:
        player_id = "X"

    with pytest.raises(Exception):
        save_players_to_csv(_players(4) + [_Broken()], str(target))
    assert target.read_text(encoding="utf-8") == "player_id\nOLD\n"
    assert _no_temp_left(tmp_path)


def test_concurrent_reader_never_sees_a_partial_players_file(tmp_path, monkeypatch):
    fallbacks: list[Path] = []
    real_copy = atomic_write.shutil.copyfile

    def _copy(src, dst, *a, **k):
        fallbacks.append(Path(dst))
        return real_copy(src, dst, *a, **k)

    monkeypatch.setattr(atomic_write.shutil, "copyfile", _copy)
    target = tmp_path / "players.csv"
    roster = _players(1500)
    save_players_to_csv(roster, str(target))
    expected = target.read_text()
    n_lines = expected.count("\n")
    assert n_lines == 1501

    stop = threading.Event()
    bad: list[int] = []
    reads = {"ok": 0}

    def _reader():
        # Workers load the file and let go of it (Windows refuses a swap
        # while any handle is open), so read in a loop with brief gaps.
        while not stop.is_set():
            time.sleep(0.002)
            try:
                with open(target, newline="") as fh:
                    text = fh.read()
            except (PermissionError, FileNotFoundError):
                continue  # Windows: the swap is in progress -- retry
            if text.count("\n") != n_lines:
                bad.append(text.count("\n"))
            else:
                reads["ok"] += 1

    threads = [threading.Thread(target=_reader) for _ in range(2)]
    for t in threads:
        t.start()
    try:
        for _ in range(25):
            save_players_to_csv(roster, str(target))
    finally:
        stop.set()
        for t in threads:
            t.join()

    assert not bad, f"reader saw partial files: {bad[:10]}"
    assert not fallbacks, "every write should have been swapped in"
    assert reads["ok"] > 0
    assert target.read_text() == expected
    assert _no_temp_left(tmp_path)


def test_replace_retries_a_windows_sharing_violation(tmp_path, monkeypatch):
    target = tmp_path / "f.csv"
    target.write_text("old\n", encoding="utf-8")
    real = os.replace
    attempts = {"n": 0}

    def _flaky(src, dst):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise PermissionError(32, "The process cannot access the file")
        return real(src, dst)

    monkeypatch.setattr(atomic_write.os, "replace", _flaky)
    monkeypatch.setattr(atomic_write.time, "sleep", lambda _s: None)
    with atomic_text_writer(target) as fh:
        fh.write("new\n")
    assert attempts["n"] == 3
    assert target.read_text(encoding="utf-8") == "new\n"
    assert _no_temp_left(tmp_path)


def test_replace_falls_back_to_an_in_place_copy(tmp_path, monkeypatch):
    target = tmp_path / "f.csv"
    target.write_text("old\n", encoding="utf-8")

    def _locked(_src, _dst):
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr(atomic_write.os, "replace", _locked)
    monkeypatch.setattr(atomic_write.time, "sleep", lambda _s: None)
    with atomic_text_writer(target) as fh:
        fh.write("new\n")
    assert target.read_text(encoding="utf-8") == "new\n"
    assert _no_temp_left(tmp_path)


def test_a_read_only_target_is_still_replaced(tmp_path, monkeypatch):
    import stat

    target = tmp_path / "f.csv"
    target.write_text("old\n", encoding="utf-8")
    os.chmod(target, stat.S_IREAD)
    monkeypatch.setattr(atomic_write.time, "sleep", lambda _s: None)
    try:
        with atomic_text_writer(target) as fh:
            fh.write("new\n")
        assert target.read_text(encoding="utf-8") == "new\n"
        assert _no_temp_left(tmp_path)
    finally:
        os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
