"""8.0.0 switch: the independent review's defects, one test (or more) each.

1 clipping rule; 2 repair re-applies the re-spread; 3 a leftover lock
never costs a season; 4 backup rollback and pools made after the move;
5 no fake "converted" events; 6 one players-file lock for every writer;
7 potentials raised are counted; 8 pool clips are logged; 9 rollback edge
cases. Scratch leagues only (``tmp_path``).
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

from services import league_rating_centers as centers
from services import rating_scale_migration as migration
from tests import rating_scale_support as support
from tests.r8_switch_support import (  # noqa: F401  (scratch is a fixture)
    game_tuning,
    news,
    read_rows,
    roll_over,
    scale_log,
    scratch,
    stored_generation,
    switch_on,
    witness,
    write_schedule,
)
from utils.players_file_lock import lock_path_for
from utils.rating_scale import engine_row, players_file_rating_scale

FLAT = support.FIXTURES["calibration_flat"]


def _game(monkeypatch, year=2026, day=1):
    return game_tuning(monkeypatch, f"{year}-04-{day:02d}")


def _levels(data):
    out = {}
    for roster in (data / "rosters").glob("*.csv"):
        if roster.stem.endswith("_pitching"):
            continue
        for row in csv.reader(roster.open(encoding="utf-8")):
            if len(row) >= 2:
                out[row[0].strip()] = row[1].strip()
    return out


def _set(data, pid, **values):
    fields, rows = read_rows(data / "players.csv")
    for row in rows:
        if row["player_id"] == pid:
            row.update({k: str(v) for k, v in values.items()})
    support.write_player_rows(data / "players.csv", fields, rows)


def _set_level(data, pid, level):
    for roster in (data / "rosters").glob("*.csv"):
        if roster.stem.endswith("_pitching"):
            continue
        lines = roster.read_text(encoding="utf-8").splitlines()
        hit = False
        for i, line in enumerate(lines):
            parts = line.split(",")
            if parts and parts[0].strip() == pid:
                parts[1] = level
                lines[i] = ",".join(parts)
                hit = True
        if hit:
            roster.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise AssertionError(pid)


def _drop_from_rosters(data, pid):
    for roster in (data / "rosters").glob("*.csv"):
        lines = roster.read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if line.split(",")[0].strip() != pid]
        if kept != lines:
            roster.write_text("\n".join(kept) + "\n", encoding="utf-8")


def _a_hitter(data):
    levels = _levels(data)
    for row in read_rows(data / "players.csv")[1]:
        if levels.get(row["player_id"]) == "ACT" and row["is_pitcher"] in ("0", "False", "false"):
            return row["player_id"], f"{row['first_name']} {row['last_name']}"
    raise AssertionError("no hitter")


# --- 1. the clipping rule -------------------------------------------------------


@pytest.mark.parametrize("level", ["DL15", "IR", "AAA", "LOW", None])
def test_a_top_clip_refuses_the_move_for_any_player(scratch, monkeypatch, level):
    """Contact 92 would be held at 99 (engine 73): he would play worse for
    good. Refused whether he is injured, a minor leaguer or a free agent."""
    data = scratch
    pid, name = _a_hitter(data)
    _set(data, pid, ch=92)
    if level is None:
        _drop_from_rosters(data, pid)  # a free agent
    else:
        _set_level(data, pid, level)
    original = (data / "players.csv").read_bytes()
    plan = migration.plan_move(data, respread=False)
    assert plan.blocker and pid in plan.blocker and name in plan.blocker
    (item,) = plan.blocking
    assert item["clip"] == "top" and item["rating"] == "ch" and item["engine"] == 92
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _game(monkeypatch)
    assert stored_generation(data, 2026) == 5
    assert (data / "players.csv").read_bytes() == original
    (event,) = scale_log(data)["events"]
    assert event["event"] == "refused"
    assert event["blocking"][0]["player_id"] == pid
    feed = news(data)
    assert name in feed and "Contact 92 would be held at 99 and play worse" in feed
    assert "operator runbook" in feed


@pytest.mark.parametrize("level,refused", [("LOW", False), ("AAA", False), ("IR", True), ("DL15", True), ("ACT", True)])
def test_a_bottom_clip_refuses_only_for_major_leaguers(scratch, level, refused):
    data = scratch
    pid, _ = _a_hitter(data)
    _set(data, pid, eye=20)  # stored 50 + 3 * (20 - 50) < 1: raised to 1
    _set_level(data, pid, level)
    plan = migration.plan_move(data, respread=False)
    assert bool(plan.blocker) == refused
    clip = next(c for c in plan.clips if c.player_id == pid and c.key == "eye")
    assert clip.unclipped < 1
    if not refused:
        assert clip in plan.allowed_clips


def test_the_runbooks_remedies_unblock_or_quietly_hold_a_league(scratch, monkeypatch):
    """Runbook section 3: set the rating to the scale's limit (he plays as
    a clip would make him play; the league moves), or hold the league on
    scale 1 (recorded each season, the commissioner is not told again)."""
    data = scratch
    pid, _ = _a_hitter(data)
    _set(data, pid, ch=92)
    assert migration.plan_move(data, respread=False).blocker
    _set(data, pid, ch=73)  # the top of what scale 2 holds for Contact
    assert migration.plan_move(data, respread=False).blocker is None
    _set(data, pid, ch=92)
    (data / "rating_scale.json").write_text(
        json.dumps({"version": 1, "events": [], "hold": {"reason": "kept on scale 1"}}),
        encoding="utf-8",
    )
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _game(monkeypatch)
    assert stored_generation(data, 2026) == 5
    assert [e["event"] for e in scale_log(data)["events"]] == ["refused"]
    assert "[commissioner]" not in news(data)


def test_an_allowed_bottom_clip_is_logged(scratch):
    data = scratch
    pid, _ = _a_hitter(data)
    _set(data, pid, eye=20)
    _set_level(data, pid, "LOW")
    migration.convert_league(data, "2026", respread=False, announce=False)
    (event,) = scale_log(data)["events"]
    assert any(c["player_id"] == pid and c["key"] == "eye" for c in event["clips"])


# --- 2. the repair re-applies the re-spread --------------------------------------


def _flat_league(data):
    shutil.copy(FLAT / "players.csv", data / "players.csv")
    for folder in ("rosters", "lineups"):
        shutil.rmtree(data / folder)
        shutil.copytree(FLAT / folder, data / folder)
    fields, rows = read_rows(data / "players.csv")
    for row in rows:
        for key in support.PITCH_KEYS:
            if row.get(key) == "":
                row[key] = "0"
    support.write_player_rows(data / "players.csv", fields, rows)


def test_a_reverted_respread_league_is_repaired_to_the_same_file(scratch, monkeypatch):
    data = scratch
    _flat_league(data)
    monkeypatch.setenv(migration.RESPREAD_LEAGUES_ENV, "r5flip")
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _game(monkeypatch)
    moved = (data / "players.csv").read_bytes()
    (move,) = scale_log(data)["events"]
    assert move["respread"]["inputs"]["rotation_ids"]
    # The rosters change (a call-up) and the re-spread list is emptied: the
    # repair re-applies the MOVE's re-spread, from its record.
    pid, _ = _a_hitter(data)
    _set_level(data, pid, "AAA")
    monkeypatch.delenv(migration.RESPREAD_LEAGUES_ENV)
    shutil.copy(data / move["backup"], data / "players.csv")  # a stale copy
    _game(monkeypatch, 2026, 2)
    assert (data / "players.csv").read_bytes() == moved
    events = scale_log(data)["events"]
    assert [e["event"] for e in events] == ["converted", "repaired"]
    assert events[1]["respread_replayed"] is True


def test_a_changed_row_keeps_the_respread_shift(scratch, monkeypatch):
    data = scratch
    _flat_league(data)
    monkeypatch.setenv(migration.RESPREAD_LEAGUES_ENV, "r5flip")
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _game(monkeypatch)
    after = {r["player_id"]: dict(engine_row(r)) for r in read_rows(data / "players.csv")[1]}
    (move,) = scale_log(data)["events"]
    shutil.copy(data / move["backup"], data / "players.csv")
    fields, rows = read_rows(data / "players.csv")
    pitcher = next(r for r in rows if r["is_pitcher"] in ("1", "True"))
    old = float(pitcher["movement"])
    _set(data, pitcher["player_id"], movement=int(old) + 2)
    _game(monkeypatch, 2026, 2)
    now = {r["player_id"]: dict(engine_row(r)) for r in read_rows(data / "players.csv")[1]}
    pid = pitcher["player_id"]
    assert float(now[pid]["movement"]) == float(after[pid]["movement"]) + 2


def test_after_a_rollback_and_unhold_the_next_conversion_is_a_fresh_move(scratch, monkeypatch):
    data = scratch
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _game(monkeypatch)
    migration.rollback_league(data, mode="inverse")
    payload = scale_log(data)
    del payload["hold"]
    (data / "rating_scale.json").write_text(json.dumps(payload), encoding="utf-8")
    centers.clear_rating_center_cache()
    _game(monkeypatch, 2026, 3)
    events = scale_log(data)["events"]
    assert [e["event"] for e in events] == ["converted", "rolled_back", "converted"]
    assert events[2]["backup"] == "players.scale1.2026.2.csv"
    assert players_file_rating_scale(data / "players.csv") == 2
    assert news(data).count("full 1-99 scale") == 2
    # The default rollback now takes the second move's backup.
    migration.rollback_league(data, mode="backup")
    assert (data / "players.csv").read_bytes() == (data / "players.scale1.2026.2.csv").read_bytes()


# --- 3. a leftover lock never costs a season --------------------------------------


def _dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_a_leftover_lock_of_a_dead_process_is_broken(scratch, monkeypatch):
    data = scratch
    lock = lock_path_for(data / "players.csv")
    import socket

    lock.write_text(json.dumps({"pid": _dead_pid(), "host": socket.gethostname(), "at": 0}))
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    started = time.monotonic()
    _game(monkeypatch)
    assert time.monotonic() - started < 10
    assert stored_generation(data, 2026) == 6
    assert not lock.exists()


def test_an_old_unowned_lock_is_broken(scratch, monkeypatch):
    data = scratch
    lock = lock_path_for(data / "players.csv")
    lock.write_text("12345 earlier", encoding="utf-8")
    old = time.time() - 120
    os.utime(lock, (old, old))
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _game(monkeypatch)
    assert stored_generation(data, 2026) == 6


def test_a_live_holder_makes_the_game_retry_and_settles_nothing(scratch, monkeypatch):
    data = scratch
    monkeypatch.setattr(centers, "_BUSY_PAUSE_SECONDS", 0.1)
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        import socket

        lock = lock_path_for(data / "players.csv")
        lock.write_text(json.dumps({"pid": holder.pid, "host": socket.gethostname(), "at": 0}))
        switch_on(monkeypatch)
        write_schedule(data, 2026)
        started = time.monotonic()
        with pytest.raises(migration.MoveBusy):
            centers.league_engine_generation()
        assert time.monotonic() - started < 15
        assert stored_generation(data, 2026) == "no entry"
        assert witness(data) is None
        assert not (data / "rating_scale.json").exists()
    finally:
        holder.kill()
        holder.wait()
    _game(monkeypatch)  # the holder is gone: the move happens now
    assert stored_generation(data, 2026) == 6


# --- 4. backup rollback and pools made after the move ----------------------------


def test_backup_rollback_puts_later_pools_back_on_scale_1(scratch, monkeypatch):
    data = scratch
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _game(monkeypatch)
    from playbalance import draft_pool
    from services import draft_assignment

    pool = draft_pool.generate_draft_pool(2026, size=12, seed=7)
    draft_pool.save_draft_pool(2026, pool)
    assert {r["rating_scale"] for r in json.loads((data / "draft_pool_2026.json").read_text())} == {2}
    event = migration.rollback_league(data, mode="backup")
    assert "draft_pool_2026.json" in event["draft_pools"]
    records = json.loads((data / "draft_pool_2026.json").read_text())
    assert all("rating_scale" not in r for r in records)
    rows = read_rows(data / "draft_pool_2026.csv")[1]
    assert all(not r.get("rating_scale") for r in rows)
    # A pick from that pool now goes into the scale 1 file.
    monkeypatch.setattr(draft_assignment, "_players_csv_path", lambda: data / "players.csv")
    row = draft_assignment._default_row_from_pool(rows[0])
    draft_assignment._append_players([row])
    assert players_file_rating_scale(data / "players.csv") == 1


# --- 5. no fake "converted" events -------------------------------------------------


def test_later_seasons_write_no_conversion_and_rollback_finds_the_real_one(scratch, monkeypatch):
    data = scratch
    original = (data / "players.csv").read_bytes()
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _game(monkeypatch, 2026)
    roll_over(data, 2026)
    write_schedule(data, 2027)
    centers.clear_rating_center_cache()
    _game(monkeypatch, 2027)
    assert stored_generation(data, 2027) == 6
    assert [e["event"] for e in scale_log(data)["events"]] == ["converted"]
    event = migration.rollback_league(data, mode="backup")
    assert event["season"] == "2026"
    assert (data / "players.csv").read_bytes() == original


# --- 6. one players-file lock for every writer -------------------------------------


def test_an_update_during_a_move_waits_for_it_and_is_kept(scratch, monkeypatch):
    data = scratch
    from services.players_repository import load_players, update_players

    pid, _ = _a_hitter(data)
    reading = threading.Event()
    real_plan = migration.plan_move

    def slow_plan(*args, **kwargs):
        plan = real_plan(*args, **kwargs)
        reading.set()
        time.sleep(0.5)  # the move holds the lock across this
        return plan

    monkeypatch.setattr(migration, "plan_move", slow_plan)
    mover = threading.Thread(
        target=lambda: migration.convert_league(data, "2026", respread=False, announce=False)
    )
    mover.start()
    assert reading.wait(5)
    player = next(p for p in load_players(data / "players.csv") if p.player_id == pid)
    player.injured = True
    update_players([player], data / "players.csv")  # blocks until the move is done
    mover.join(10)
    rows = {r["player_id"]: r for r in read_rows(data / "players.csv")[1]}
    # Kept, not lost. The caller's object was loaded before the move, so
    # its row is written on scale 1 (correct on its own scale) ...
    assert rows[pid]["injured"] == "True" and rows[pid]["rating_scale"] in ("", "1")
    assert players_file_rating_scale(data / "players.csv") == "mixed"
    # ... and the next storing game of a generation 6 season repairs it.
    migration.repair_league(data, "2026")
    rows = {r["player_id"]: r for r in read_rows(data / "players.csv")[1]}
    assert rows[pid]["injured"] == "True"
    assert players_file_rating_scale(data / "players.csv") == 2
    assert [e["event"] for e in scale_log(data)["events"]] == ["converted", "repaired"]


def test_a_write_that_skips_the_lock_is_seen_before_the_replace(scratch, monkeypatch):
    """A writer that does not take the lock (an older build) changes the
    file between the move's read and its replace: the move reads it again,
    plans again, and the change is in the converted file."""
    data = scratch
    real_plan = migration.plan_move
    calls = []

    def plan_then_someone_writes(*args, **kwargs):
        plan = real_plan(*args, **kwargs)
        if not calls:
            fields, rows = read_rows(data / "players.csv")
            extra = dict(rows[0], player_id="X0000001")
            support.write_player_rows(data / "players.csv", fields, rows + [extra])
        calls.append(1)
        return plan

    monkeypatch.setattr(migration, "plan_move", plan_then_someone_writes)
    migration.convert_league(data, "2026", respread=False, announce=False)
    assert len(calls) == 2
    ids = [r["player_id"] for r in read_rows(data / "players.csv")[1]]
    assert "X0000001" in ids
    assert players_file_rating_scale(data / "players.csv") == 2


def test_a_file_that_keeps_changing_makes_the_move_busy(scratch, monkeypatch):
    data = scratch
    original = (data / "players.csv").read_bytes()
    real_plan = migration.plan_move

    def always_changing(*args, **kwargs):
        plan = real_plan(*args, **kwargs)
        # A writer outside the lock changes the bytes every time.
        (data / "players.csv").write_bytes((data / "players.csv").read_bytes() + b"\n")
        return plan

    monkeypatch.setattr(migration, "plan_move", always_changing)
    with pytest.raises(migration.MoveBusy):
        migration.convert_league(data, "2026", respread=False, announce=False)
    assert players_file_rating_scale(data / "players.csv") == 1
    assert len(original) > 0


# --- 7 and 8. potentials raised and pool clips are logged -----------------------------


def test_potentials_raised_and_pool_clips_are_logged(scratch):
    data = scratch
    from playbalance import draft_pool

    pool = draft_pool.generate_draft_pool(2026, size=300, seed=11)
    draft_pool.save_draft_pool(2026, pool)
    migration.convert_league(data, "2026", respread=False, announce=False)
    (event,) = scale_log(data)["events"]
    raised = event["potentials_raised_to_current"]
    by_rating = event["potentials_raised_by_rating"]
    assert raised == sum(by_rating.values())
    fields, rows = read_rows(data / "players.scale1.2026.csv")
    expected = sum(
        1
        for row in rows
        for key, value in row.items()
        if key.startswith("pot_") and value not in ("", None)
        and row.get(key[4:]) not in ("", None)
        and 0 < float(value) < float(row[key[4:]])
    )
    assert raised == expected
    clips = event["draft_pool_clips"]
    assert clips and {c["file"] for c in clips} == {"draft_pool_2026.json", "draft_pool_2026.csv"}


# --- 9. rollback edge cases --------------------------------------------------------


def test_the_hold_is_written_before_the_rollback_touches_anything(scratch, monkeypatch):
    data = scratch
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _game(monkeypatch)
    converted = (data / "players.csv").read_bytes()
    real = migration._write_bytes_atomic

    def fail_on_players(path, data_bytes):
        if path.name == "players.csv":
            raise OSError("disk gone")
        return real(path, data_bytes)

    monkeypatch.setattr(migration, "_write_bytes_atomic", fail_on_players)
    with pytest.raises(OSError):
        migration.rollback_league(data, mode="backup")
    monkeypatch.setattr(migration, "_write_bytes_atomic", real)
    assert scale_log(data)["hold"]["reason"].startswith("rolling back")
    assert (data / "players.csv").read_bytes() == converted
    # The next game neither repairs nor moves anything while held.
    _game(monkeypatch, 2026, 2)
    assert [e["event"] for e in scale_log(data)["events"]] == ["converted"]


def test_inverse_needs_a_recorded_move_unless_told_otherwise(scratch, monkeypatch):
    data = scratch
    with pytest.raises(migration.MoveRefused, match="no conversion"):
        migration.rollback_league(data, mode="inverse", season="2026")
    assert not (data / "rating_scale.json").exists()
    # A league created on scale 2: explicit.
    fields, rows = read_rows(data / "players.csv")
    original = {r["player_id"]: r for r in rows}
    migration._write_players(
        data / "players.csv", fields,
        [__import__("utils.rating_scale", fromlist=["stretch_row"]).stretch_row(r, 2)[0] for r in rows],
    )
    migration.rollback_league(data, mode="inverse", season="2026", allow_unrecorded=True)
    after = {r["player_id"]: r for r in read_rows(data / "players.csv")[1]}
    for pid, row in list(original.items())[:50]:
        assert after[pid]["ch"] == row["ch"]


def test_a_later_seasons_witness_is_never_overwritten(scratch, monkeypatch):
    data = scratch
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _game(monkeypatch)
    roll_over(data, 2026)
    write_schedule(data, 2027)
    centers.clear_rating_center_cache()
    _game(monkeypatch, 2027)
    assert witness(data) == ("2027", 6)
    event = migration.set_recorded_generation(data, "2026", 5)
    assert witness(data) == ("2027", 6)
    assert "belongs to season 2027" in event["witness_kept"]
    assert stored_generation(data, 2026) == 5
