"""Working-copy sync: every local change reaches the durable remote.

Two ways writes used to be lost:

* a write that landed DURING a push could fall below the advanced time cutoff
  (this is how the playoff bracket vanished);
* a COPY keeps its source's mtime, so a file copied to a new path -- the
  season-end archive, a cloned league, the roster-lock snapshot, a backup
  restored over a live file -- was older than the cutoff and never pushed at
  all, and disappeared at the next restart.

Sync now compares each file's (mtime, size) with what it was at its last sync.
"""

import os
import shutil
import time

import api.working_copy as wc


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _age(path, seconds=3600):
    """Back-date a file, as a file untouched since an earlier push would be."""
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def _setup(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    monkeypatch.setenv("NEXGEN_WORKING_COPY", "1")
    monkeypatch.setenv("NEXGEN_SYNC_REMOTE", str(remote))
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(local))
    monkeypatch.setattr(wc, "_synced", {})
    monkeypatch.setattr(wc, "_busy", {})
    return remote, local


def _league(remote, league="alpha"):
    """A league on the remote whose files were last changed an hour ago."""
    data = remote / "leagues" / league / "data"
    for name, text in {
        "teams.csv": "teams",
        "players.csv": "players",
        "rosters/HOU.csv": "P1,ACT",
    }.items():
        _write(data / name, text)
        _age(data / name)
    return data


def _remote_files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


# --- basics ----------------------------------------------------------------


def test_round_trip_push(tmp_path, monkeypatch):
    remote, local = _setup(tmp_path, monkeypatch)
    wc.bulk_pull()
    _write(local / "a.txt", "A")
    assert wc.push_changes() == 1
    assert (remote / "a.txt").read_text(encoding="utf-8") == "A"


def test_a_pull_is_not_pushed_back(tmp_path, monkeypatch):
    remote, _ = _setup(tmp_path, monkeypatch)
    _league(remote)
    wc.bulk_pull()
    assert wc.push_changes() == 0


def test_a_write_during_a_push_is_flushed_by_the_next(tmp_path, monkeypatch):
    """The signature is the one seen at SCAN time; a rewrite while the copy
    runs leaves the file different from it, so the next push copies again."""
    remote, local = _setup(tmp_path, monkeypatch)
    wc.bulk_pull()
    target = local / "bracket.json"
    _write(target, "v1")

    real_copy = wc._copy_one

    def copy_then_rewrite(pair):
        result = real_copy(pair)
        _write(target, "v2-written-mid-push")
        return result

    monkeypatch.setattr(wc, "_copy_one", copy_then_rewrite)
    wc.push_changes()
    monkeypatch.setattr(wc, "_copy_one", real_copy)
    wc.push_changes()
    assert (remote / "bracket.json").read_text(encoding="utf-8") == "v2-written-mid-push"


def test_scoped_push_persists_new_league(tmp_path, monkeypatch):
    remote, local = _setup(tmp_path, monkeypatch)
    wc.bulk_pull()
    league_dir = local / "leagues" / "L1" / "data"
    _write(league_dir / "contracts.json", '{"players":{}}')
    wc.push_changes("L1")
    assert (remote / "leagues" / "L1" / "data" / "contracts.json").exists()


def test_a_local_delete_reaches_the_remote(tmp_path, monkeypatch):
    remote, local = _setup(tmp_path, monkeypatch)
    data = _league(remote)
    wc.bulk_pull()
    (local / "leagues" / "alpha" / "data" / "rosters" / "HOU.csv").unlink()
    wc.push_changes("alpha")
    assert not (data / "rosters" / "HOU.csv").exists()


def test_a_league_missing_locally_is_never_deleted_remotely(tmp_path, monkeypatch):
    remote, local = _setup(tmp_path, monkeypatch)
    data = _league(remote)
    wc.bulk_pull()
    shutil.rmtree(local / "leagues" / "alpha")  # e.g. a partial pull
    wc.push_changes()
    assert (data / "teams.csv").exists()


# --- copies keep their source's mtime: the cases that used to be lost -------


def test_a_cloned_league_is_pushed(tmp_path, monkeypatch):
    """admin_league / league_lifecycle clone with shutil.copytree."""
    remote, local = _setup(tmp_path, monkeypatch)
    _league(remote)
    wc.bulk_pull()
    leagues = local / "leagues"
    shutil.copytree(leagues / "alpha", leagues / "beta")
    wc.push_changes("alpha")
    assert _remote_files(remote / "leagues" / "beta") == [
        "data/players.csv", "data/rosters/HOU.csv", "data/teams.csv",
    ]


def test_an_archive_copy_into_the_league_is_pushed(tmp_path, monkeypatch):
    """The season-end rollover copies (copy2) last season's files into
    careers/<season>/; those sources were last pushed long before."""
    remote, local = _setup(tmp_path, monkeypatch)
    data = _league(remote)
    wc.bulk_pull()
    ldata = local / "leagues" / "alpha" / "data"
    (ldata / "careers" / "2026").mkdir(parents=True)
    shutil.copy2(ldata / "players.csv", ldata / "careers" / "2026" / "players.csv")
    wc.push_changes("alpha")
    assert (data / "careers" / "2026" / "players.csv").read_text(encoding="utf-8") == "players"


def test_a_backup_restored_over_a_live_file_is_pushed(tmp_path, monkeypatch):
    """Overwriting a synced file with an OLDER copy: same path, older mtime."""
    remote, local = _setup(tmp_path, monkeypatch)
    data = _league(remote)
    wc.bulk_pull()
    ldata = local / "leagues" / "alpha" / "data"
    backup = tmp_path / "backup_teams.csv"
    _write(backup, "teams-from-backup")
    _age(backup, seconds=7200)          # older than the live file
    shutil.copy2(backup, ldata / "teams.csv")
    wc.push_changes("alpha")
    assert (data / "teams.csv").read_text(encoding="utf-8") == "teams-from-backup"


def test_pending_changes_in_another_league_wait_for_their_push(tmp_path, monkeypatch):
    """A push scoped to alpha neither pushes nor forgets beta's change."""
    remote, local = _setup(tmp_path, monkeypatch)
    _league(remote, "alpha")
    beta = _league(remote, "beta")
    wc.bulk_pull()
    _write(local / "leagues" / "beta" / "data" / "teams.csv", "beta-changed")
    wc.push_changes("alpha")
    assert (beta / "teams.csv").read_text(encoding="utf-8") == "teams"
    wc.push_changes("beta")
    assert (beta / "teams.csv").read_text(encoding="utf-8") == "beta-changed"


# --- shutdown flush -----------------------------------------------------------


def test_shutdown_flushes_unsaved_writes(tmp_path, monkeypatch):
    """A write made during a READ request is never pushed by the middleware."""
    remote, local = _setup(tmp_path, monkeypatch)
    data = _league(remote)
    wc.bulk_pull()
    _write(local / "leagues" / "alpha" / "data" / "rosters" / "_placeholder_registry.json", "{}")
    assert wc.flush_on_shutdown() == 1
    assert (data / "rosters" / "_placeholder_registry.json").exists()


def test_shutdown_ignores_the_request_league_and_walks_everything(tmp_path, monkeypatch):
    remote, local = _setup(tmp_path, monkeypatch)
    _league(remote, "alpha")
    beta = _league(remote, "beta")
    wc.bulk_pull()
    _write(local / "leagues" / "beta" / "data" / "teams.csv", "beta-changed")
    monkeypatch.setattr(wc, "_request_league_id", lambda: "alpha")
    wc.flush_on_shutdown()
    assert (beta / "teams.csv").read_text(encoding="utf-8") == "beta-changed"


def test_shutdown_stands_down_while_a_background_job_is_writing(tmp_path, monkeypatch):
    """Pushing a sim halfway through a day would leave results without stats."""
    remote, local = _setup(tmp_path, monkeypatch)
    data = _league(remote)
    wc.bulk_pull()
    _write(local / "leagues" / "alpha" / "data" / "schedule.csv", "half-written")
    with wc.background_writer("sim-day"):
        assert wc.flush_on_shutdown() == 0
    assert not (data / "schedule.csv").exists()
    # Once the job is done, the flush goes ahead.
    assert wc.flush_on_shutdown() == 1


def test_background_writer_counts_overlapping_jobs(monkeypatch):
    monkeypatch.setattr(wc, "_busy", {})
    with wc.background_writer("sim"):
        with wc.background_writer("sim"):
            assert wc._busy == {"sim": 2}
        assert wc._busy == {"sim": 1}
    assert wc._busy == {}


def test_a_failing_job_still_clears_its_mark(monkeypatch):
    monkeypatch.setattr(wc, "_busy", {})
    job = wc.as_background_writer("cpu-free-agency", lambda: 1 / 0)
    try:
        job()
    except ZeroDivisionError:
        pass
    assert wc._busy == {}


def test_shutdown_flush_is_a_no_op_off_cloud(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXGEN_WORKING_COPY", raising=False)
    assert wc.flush_on_shutdown() == 0
