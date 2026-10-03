"""A file whose copy fails must be retried by the next push, not forgotten.

Under the old time-cutoff sync, advancing the "saved up to here" marker past a
failed copy hid the file forever (this is what stranded a 2-hour avatar run
under a 503). Sync is per file now: a failed copy keeps the file's old recorded
signature, so the next push sees it as still changed.
"""

import api.working_copy as wc


def _reset(monkeypatch, tmp_path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    (local / "leagues" / "alpha" / "data").mkdir(parents=True)
    remote.mkdir()
    monkeypatch.setenv("NEXGEN_WORKING_COPY", "1")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(local))
    monkeypatch.setenv("NEXGEN_SYNC_REMOTE", str(remote))
    monkeypatch.setattr(wc, "_synced", {})
    f = local / "leagues" / "alpha" / "data" / "x.png"
    f.write_bytes(b"\x89PNG-avatar")
    return local, remote


def test_a_failed_copy_is_retried_by_the_next_push(monkeypatch, tmp_path):
    _, remote = _reset(monkeypatch, tmp_path)
    landed = remote / "leagues" / "alpha" / "data" / "x.png"

    real_copy = wc._copy_one
    remote_up = {"ok": False}
    monkeypatch.setattr(wc, "_copy_one", lambda pair: real_copy(pair) if remote_up["ok"] else 0)

    # The remote/FUSE is unavailable: nothing copies.
    assert wc.push_changes(None) == 0
    assert not landed.exists()
    assert "leagues/alpha/data/x.png" not in wc._synced

    # It comes back: the same file is pushed without anyone rewriting it.
    remote_up["ok"] = True
    assert wc.push_changes(None) == 1
    assert landed.read_bytes() == b"\x89PNG-avatar"


def test_a_successful_copy_is_recorded_and_not_repeated(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    assert wc.push_changes(None) == 1
    assert "leagues/alpha/data/x.png" in wc._synced
    assert wc.push_changes(None) == 0  # unchanged since: nothing to push
