"""The KPI harness reads park data from the repository, not the active league.

The park lookup starts with the active league's folder. The altitude file
(`Parks.csv`) used to be tracked only inside three league folders, so a
harness run found altitude only while one of those was active; a run that
began while a test or a scratch league had switched the active league played
a whole season with no altitude (home runs about 5% lower, nothing else
changed). The harness now pins the lookup to `data/` and fails if a park
file is missing; the product's own games are unaffected.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from utils import park_utils

REPO = Path(__file__).resolve().parents[1]


def _harness():
    path = REPO / "scripts" / "physics_sim_season_kpis.py"
    spec = importlib.util.spec_from_file_location("kpis_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_repository_holds_all_three_park_files():
    assert park_utils.missing_park_data_files(REPO / "data") == []
    # Tracked, not just present in one developer's checkout.
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    for name in park_utils.PARK_DATA_FILES:
        assert f"!data/parks/{name}" in ignore, name


def test_a_pinned_root_is_the_only_place_looked(tmp_path, monkeypatch):
    elsewhere = tmp_path / "league"
    (elsewhere / "parks").mkdir(parents=True)
    (elsewhere / "parks" / "Parks.csv").write_text("PARKID,NAME\n", encoding="utf-8")
    monkeypatch.setattr(park_utils, "get_data_dir", lambda: elsewhere)
    monkeypatch.setattr(park_utils, "get_data_root", lambda: elsewhere)

    monkeypatch.delenv(park_utils.PARK_DATA_ROOT_ENV, raising=False)
    assert park_utils._parks_master_path() == elsewhere / "parks" / "Parks.csv"

    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(REPO / "data"))
    assert park_utils._park_data_roots() == [(REPO / "data").resolve()]
    assert park_utils._parks_master_path() == (REPO / "data").resolve() / "parks" / "Parks.csv"
    assert park_utils._park_config_path().parent == (REPO / "data").resolve() / "parks"


def test_a_pinned_root_without_the_file_does_not_fall_back(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(empty))
    assert park_utils._parks_master_path() == empty.resolve() / "parks" / "Parks.csv"
    assert park_utils._load_parks_master() == ({}, {})
    assert park_utils.missing_park_data_files(empty) == list(park_utils.PARK_DATA_FILES)


def test_the_product_lookup_is_unchanged_without_the_pin(tmp_path, monkeypatch):
    monkeypatch.delenv(park_utils.PARK_DATA_ROOT_ENV, raising=False)
    league = tmp_path / "league"
    root = tmp_path / "root"
    for folder in (league, root):
        folder.mkdir()
    (root / "parks").mkdir()
    (root / "parks" / "ParkConfig.csv").write_text("Year,NAME\n", encoding="utf-8")
    monkeypatch.setattr(park_utils, "get_data_dir", lambda: league)
    monkeypatch.setattr(park_utils, "get_data_root", lambda: root)
    monkeypatch.setattr(park_utils, "get_base_dir", lambda: tmp_path / "base")
    # League folder first, then the data root (where live leagues keep them).
    assert park_utils._park_data_roots()[:2] == [league.resolve(), root.resolve()]
    assert park_utils._park_config_path() == root.resolve() / "parks" / "ParkConfig.csv"


def test_the_harness_pins_the_lookup_and_refuses_missing_park_data(
    tmp_path, monkeypatch, capsys
):
    kpis = _harness()
    # Set (to "unset") through monkeypatch, so the value main() writes into
    # the environment is rolled back when the test ends.
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, "")
    seen = {}

    def fake_run_sim(*args, **kwargs):
        import os

        seen["root"] = os.environ.get(park_utils.PARK_DATA_ROOT_ENV)
        raise KeyboardInterrupt

    monkeypatch.setattr(kpis, "run_sim", fake_run_sim)
    monkeypatch.setattr(kpis.sys, "argv", ["kpis", "--games", "162"])
    with pytest.raises(KeyboardInterrupt):
        kpis.main()
    assert Path(seen["root"]).resolve() == (REPO / "data").resolve()

    # A checkout without the park files is an error, not a generic-park run.
    monkeypatch.setattr(kpis, "BASE_DIR", tmp_path)
    with pytest.raises(SystemExit):
        kpis.main()
    assert "park data missing" in capsys.readouterr().err


def test_the_product_fixture_is_what_the_harness_needs():
    fixture = REPO / "data" / "calibration_product"
    assert (fixture / "players.csv").exists() and (fixture / "teams.csv").exists()
    teams = [
        line.split(",")[0]
        for line in (fixture / "teams.csv").read_text(encoding="utf-8").splitlines()[1:]
        if line.strip()
    ]
    assert len(teams) == 30
    for team in teams:
        assert (fixture / "rosters" / f"{team}.csv").exists(), team
        assert (fixture / "rosters" / f"{team}_pitching.csv").exists(), team
        for hand in ("lhp", "rhp"):
            assert (fixture / "lineups" / f"{team}_vs_{hand}.csv").exists(), (team, hand)
