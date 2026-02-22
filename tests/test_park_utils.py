from __future__ import annotations

from utils import park_utils


def test_list_ballpark_names_reads_park_config(tmp_path, monkeypatch):
    parks_dir = tmp_path / "parks"
    parks_dir.mkdir(parents=True)
    csv_path = parks_dir / "ParkConfig.csv"
    csv_path.write_text(
        "parkID,NAME,Year,LF_Dim,CF_Dim,RF_Dim\n"
        "AAA,Alpha Park,2001,330,400,330\n"
        "BBB,Beta Park,2002,335,405,335\n"
        "AAA,Alpha Park,2005,331,401,331\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(park_utils, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(park_utils, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(park_utils, "get_base_dir", lambda: tmp_path)

    names = park_utils.list_ballpark_names()

    assert names == ["Alpha Park", "Beta Park"]


def test_list_ballpark_names_returns_empty_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(park_utils, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(park_utils, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(park_utils, "get_base_dir", lambda: tmp_path)
    assert park_utils.list_ballpark_names() == []


def test_list_ballpark_names_falls_back_to_legacy_ballparks_module(tmp_path, monkeypatch):
    (tmp_path / "ballparks.py").write_text(
        "BALLPARKS = ['Old Park', 'River Field', 'Old Park']\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(park_utils, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(park_utils, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(park_utils, "get_base_dir", lambda: tmp_path)

    assert park_utils.list_ballpark_names() == ["Old Park", "River Field"]
