"""Making a file writable must not take away the right to read or enter it.

``os.chmod(path, stat.S_IWRITE)`` is a Windows idiom for "clear read-only".
On Linux it REPLACES the mode with 0o200: no read, no execute. Applied across a
league's data tree it left every directory impossible to enter, and the KPI
harness died on import with "Permission denied" on GitHub's runner. Cloud Run
hid it by running as root, which ignores permission bits.

These tests assert the exact mode handed to ``chmod``, so the Linux behaviour is
checked on any platform.
"""

import stat

import pytest

import utils.path_utils as P


@pytest.fixture
def chmods(monkeypatch):
    calls = []
    monkeypatch.setattr(P.os, "chmod", lambda path, mode: calls.append((str(path), mode)))
    return calls


def _with_mode(monkeypatch, mode):
    class _St:
        st_mode = mode

    monkeypatch.setattr(P.os, "stat", lambda path: _St())


def test_a_read_only_file_gains_owner_write_and_keeps_read(monkeypatch, chmods):
    _with_mode(monkeypatch, stat.S_IFREG | 0o444)
    P.ensure_writable("f.csv")
    assert chmods == [("f.csv", 0o644)]


def test_a_directory_keeps_execute_so_it_can_still_be_entered(monkeypatch, chmods):
    """The regression: S_IWRITE alone left directories at 0o200."""
    _with_mode(monkeypatch, stat.S_IFDIR | 0o555)
    P.ensure_writable("leagues/cbl/data")
    assert chmods == [("leagues/cbl/data", 0o755)]
    assert chmods[0][1] & stat.S_IXUSR


def test_an_already_writable_path_is_left_alone(monkeypatch, chmods):
    """No syscall at all -- and certainly no mode rewritten to 0o200."""
    _with_mode(monkeypatch, stat.S_IFDIR | 0o755)
    P.ensure_writable("data")
    assert chmods == []


def test_the_mode_is_never_reduced_to_write_only(monkeypatch, chmods):
    for mode in (0o400, 0o444, 0o500, 0o555, 0o600, 0o700):
        _with_mode(monkeypatch, stat.S_IFREG | mode)
        P.ensure_writable("x")
    assert all(m & stat.S_IRUSR for _, m in chmods), chmods
    assert 0o200 not in [m for _, m in chmods]


def test_a_missing_path_is_quietly_ignored(monkeypatch, chmods):
    def boom(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(P.os, "stat", boom)
    P.ensure_writable("nope")
    assert chmods == []


def test_clearing_a_real_tree_leaves_it_readable(tmp_path):
    """End to end on the real filesystem, whatever it is."""
    league = tmp_path / "leagues" / "cbl" / "data"
    league.mkdir(parents=True)
    (league / "players.csv").write_text("id\n", encoding="utf-8")
    P._clear_readonly_tree(tmp_path / "leagues")
    assert (league / "players.csv").read_text(encoding="utf-8") == "id\n"
    assert [p.name for p in league.iterdir()] == ["players.csv"]


def test_league_creator_no_longer_uses_the_windows_idiom():
    import inspect

    import playbalance.league_creator as LC

    assert "stat.S_IWRITE" not in inspect.getsource(LC)
