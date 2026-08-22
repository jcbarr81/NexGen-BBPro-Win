"""Working-copy sync: a write that lands DURING a push must not be permanently
dropped by the mtime cutoff (this is how the playoff bracket vanished)."""

import os
import time

import api.working_copy as wc


def _write(path, text):
    """Write a file with an mtime unambiguously after any prior sync cutoff
    (avoids the same-tick mtime granularity edge on Windows test runs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    stamp = time.time() + 2
    os.utime(path, (stamp, stamp))


def _setup(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    monkeypatch.setenv("NEXGEN_WORKING_COPY", "1")
    monkeypatch.setenv("NEXGEN_SYNC_REMOTE", str(remote))
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(local))
    # Reset module globals so the test is isolated.
    wc._last_sync = 0.0
    wc._known = set()
    wc._scope_sync = {}
    return remote, local


def test_round_trip_push(tmp_path, monkeypatch):
    remote, local = _setup(tmp_path, monkeypatch)
    wc.bulk_pull()
    _write(local / "a.txt", "A")
    assert wc.push_changes() >= 1
    assert (remote / "a.txt").read_text(encoding="utf-8") == "A"


def test_cutoff_is_pre_scan_not_post_copy(tmp_path, monkeypatch):
    """The advanced cutoff must be the pre-scan t0, not the post-copy 'now'.

    We slow the copy so the two differ clearly. A file written concurrently
    during the push (mtime between t0 and now) is then still > the recorded
    cutoff and gets flushed on the next push, instead of being dropped forever.
    """
    import time

    remote, local = _setup(tmp_path, monkeypatch)
    wc.bulk_pull()
    _write(local / "a.txt", "A")

    orig_copy = wc._parallel_copy

    def slow_copy(pairs):
        time.sleep(0.25)  # push now spans a measurable window
        return orig_copy(pairs)

    monkeypatch.setattr(wc, "_parallel_copy", slow_copy)

    t_before = time.time()
    wc.push_changes()
    # Cutoff pinned to pre-scan t0 (~t_before), NOT post-copy now (>= t_before+0.25).
    assert wc._last_sync < t_before + 0.1, (
        f"cutoff advanced past the scan window: "
        f"{wc._last_sync - t_before:.3f}s after start"
    )

    # A write that landed mid-push (mtime between t0 and post-copy now) survives.
    b = local / "b.txt"
    b.write_text("B", encoding="utf-8")
    os.utime(b, (t_before + 0.15, t_before + 0.15))
    monkeypatch.setattr(wc, "_parallel_copy", orig_copy)
    wc.push_changes()
    assert (remote / "b.txt").exists(), "write during a push was dropped"


def test_scoped_push_persists_new_league(tmp_path, monkeypatch):
    remote, local = _setup(tmp_path, monkeypatch)
    wc.bulk_pull()
    league_dir = local / "leagues" / "L1" / "data"
    league_dir.mkdir(parents=True)
    _write(league_dir / "contracts.json", '{"players":{}}')
    wc.push_changes("L1")
    assert (remote / "leagues" / "L1" / "data" / "contracts.json").exists()
