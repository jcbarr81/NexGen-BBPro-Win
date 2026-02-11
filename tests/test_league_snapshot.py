import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    import utils.path_utils as path_utils
    path_utils._DATA_DIR = None
    import playbalance.season_context as season_context
    importlib.reload(season_context)
    return data_root


def _write_career_index(path: Path, league_id: str) -> None:
    payload = {
        "version": 1,
        "league": {"id": league_id, "name": "Test League"},
        "current": {},
        "seasons": [],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_export_and_import_snapshot(data_dir):
    (data_dir / "teams.csv").write_text("team_id,name\nTST,Test\n", encoding="utf-8")
    (data_dir / "players.csv").write_text("player_id,first,last\nP1,A,B\n", encoding="utf-8")
    _write_career_index(data_dir / "career_index.json", "testleague")

    import services.league_snapshot as league_snapshot
    importlib.reload(league_snapshot)

    result = league_snapshot.export_league_snapshot(output_dir=data_dir / "exports")
    assert result.get("status") == "success"
    snapshot_path = Path(str(result.get("path")))
    assert snapshot_path.exists()

    (data_dir / "teams.csv").write_text("team_id,name\nOLD,Old\n", encoding="utf-8")

    import_result = league_snapshot.import_league_snapshot(snapshot_path)
    assert import_result.get("status") == "success"
    assert (data_dir / "teams.csv").read_text(encoding="utf-8") == "team_id,name\nTST,Test\n"


def test_import_rejects_mismatched_league(data_dir):
    (data_dir / "teams.csv").write_text("team_id,name\nTST,Test\n", encoding="utf-8")
    _write_career_index(data_dir / "career_index.json", "remote")

    import services.league_snapshot as league_snapshot
    importlib.reload(league_snapshot)

    result = league_snapshot.export_league_snapshot(output_dir=data_dir / "exports")
    snapshot_path = Path(str(result.get("path")))

    _write_career_index(data_dir / "career_index.json", "local")

    import_result = league_snapshot.import_league_snapshot(snapshot_path)
    assert import_result.get("status") == "error"
