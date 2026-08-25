"""The sync marker must NOT advance when a copy fails — otherwise un-saved
files fall below the "saved up to here" line forever (this is what stranded a
2-hour avatar run under a 503). A failed push must leave the marker so the next
push retries."""

import api.working_copy as wc


def _reset(monkeypatch, tmp_path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    (local / "leagues" / "alpha" / "data").mkdir(parents=True)
    remote.mkdir()
    monkeypatch.setenv("NEXGEN_WORKING_COPY", "1")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(local))
    monkeypatch.setenv("NEXGEN_SYNC_REMOTE", str(remote))
    monkeypatch.setattr(wc, "_last_sync", 0.0)
    monkeypatch.setattr(wc, "_scope_sync", {})
    monkeypatch.setattr(wc, "_known", set())
    # A local file that will show up as "changed" (mtime > cutoff 0).
    f = local / "leagues" / "alpha" / "data" / "x.png"
    f.write_bytes(b"\x89PNG-avatar")
    return local, remote


def test_marker_not_advanced_when_copy_fails(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    # Simulate the remote/FUSE being unavailable: nothing actually copies.
    monkeypatch.setattr(wc, "_parallel_copy", lambda pairs: 0)
    wc.push_changes(None)
    # Copy failed → the global cutoff must stay put so the file is retried.
    assert wc._last_sync == 0.0


def test_marker_advances_when_copy_succeeds(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    # Real copy into the temp remote — succeeds.
    wc.push_changes(None)
    assert wc._last_sync > 0.0
    # And the file actually landed remotely.
    assert (tmp_path / "remote" / "leagues" / "alpha" / "data" / "x.png").exists()
