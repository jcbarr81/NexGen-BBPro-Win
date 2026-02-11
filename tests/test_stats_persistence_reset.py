import json

from utils import path_utils
from utils.stats_persistence import load_stats, reset_stats


def test_reset_stats_overwrites_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "get_base_dir", lambda: tmp_path)
    monkeypatch.setattr(path_utils, "get_data_dir", lambda: tmp_path / "data")
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    stats_path = data_dir / "season_stats.json"
    stats_path.write_text(
        json.dumps({"players": {"P1": {"pa": 42}}, "teams": {"T1": {"w": 12}}, "history": [{"date": "2025-04-01"}]}, indent=2),
        encoding="utf-8",
    )

    handle = stats_path.open("r", encoding="utf-8")
    try:
        reset_stats(stats_path)
    finally:
        handle.close()

    payload = json.loads(stats_path.read_text(encoding="utf-8"))
    assert payload == {"players": {}, "teams": {}, "history": []}


def test_reset_stats_with_default_path(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "get_base_dir", lambda: tmp_path)
    monkeypatch.setattr(path_utils, "get_data_dir", lambda: tmp_path / "data")
    stats_path = tmp_path / "data" / "season_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(
        json.dumps({"players": {"P2": {"pa": 10}}, "teams": {}, "history": []}, indent=2),
        encoding="utf-8",
    )

    reset_stats()
    payload = load_stats()
    assert payload == {"players": {}, "teams": {}, "history": []}
