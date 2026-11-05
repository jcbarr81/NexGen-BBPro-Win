"""Backlog #48: a configured data root that can't be used is an error, and
seeding a league dir never copies a tree into itself.

A NEXGEN_DATA_ROOT that couldn't be created used to fall back to the
repository's data/ without a word, and seeding data/leagues/<x>/data from
data/ copied data/leagues into itself (146 files in one incident, plus
data/leagues/<x>/data/leagues/... trees).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import utils.path_utils as P


@pytest.fixture
def repo(tmp_path, monkeypatch):
    base = tmp_path / "repo"
    data = base / "data"
    (data / "leagues" / "alpha" / "data").mkdir(parents=True)
    (data / "teams.csv").write_text("id\n", encoding="utf-8")
    (data / "parks").mkdir()
    (data / "parks" / "p.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(P, "get_base_dir", lambda: base)
    monkeypatch.delenv("NEXGEN_DATA_DIR", raising=False)
    return base


def test_a_root_that_is_a_file_is_an_error(repo, tmp_path, monkeypatch):
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(blocker))
    with pytest.raises(P.DataRootError, match="not_a_folder"):
        P._resolve_data_root()


def test_a_root_that_cant_be_created_is_an_error(repo, tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(blocker / "below" / "root"))
    with pytest.raises(P.DataRootError, match="can't be used"):
        P._resolve_data_root()


def test_a_usable_root_is_returned_and_seeded(repo, tmp_path, monkeypatch):
    root = tmp_path / "root"
    monkeypatch.setenv("NEXGEN_DATA_ROOT", f"  {root}  ")
    assert P._resolve_data_root() == root
    assert (root / "teams.csv").exists()


def test_seeding_a_league_dir_never_copies_the_tree_into_itself(repo):
    data = repo / "data"
    target = data / "leagues" / "alpha" / "data"
    P._seed_data_dir(data, target)
    assert (target / "teams.csv").exists()
    assert (target / "parks" / "p.json").exists()
    assert not (target / "leagues").exists()


def test_seeding_a_folder_from_itself_does_nothing(repo):
    data = repo / "data"
    before = sorted(p.name for p in data.iterdir())
    P._seed_data_dir(data, data)
    assert sorted(p.name for p in data.iterdir()) == before


def test_the_contains_check():
    base = Path("/a/b")
    assert P._contains(base, base / "c" / "d")
    assert not P._contains(base / "c", base)
