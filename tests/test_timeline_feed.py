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


def _write_career_index(path: Path, season_id: str, league_year: int) -> None:
    payload = {
        "version": 1,
        "league": {"id": "nexgen", "name": "Test League"},
        "current": {
            "season_id": season_id,
            "league_year": league_year,
            "sequence": 1,
            "metadata": {},
            "rollover_complete": False,
        },
        "seasons": [],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_timeline_feed_sources(data_dir):
    season_id = "nexgen-2026"
    _write_career_index(data_dir / "career_index.json", season_id, 2026)

    events_payload = {
        "version": 1,
        "season_id": season_id,
        "events": [
            {
                "date": "2026-07-01",
                "label": "Hit for the Cycle",
                "category": "hitting",
                "player_id": "P1",
                "player_name": "Test Hitter",
            }
        ],
    }
    events_path = data_dir / "special_events.json"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(json.dumps(events_payload, indent=2), encoding="utf-8")

    awards_payload = {
        "awards": {
            "MVP": {"player_id": "P2", "player_name": "Award Winner"},
        },
        "generated_at": "2026-10-01T00:00:00Z",
    }
    awards_path = data_dir / "careers" / season_id / "awards.json"
    awards_path.parent.mkdir(parents=True, exist_ok=True)
    awards_path.write_text(json.dumps(awards_payload, indent=2), encoding="utf-8")

    hof_payload = {
        "version": 1,
        "settings": {"min_years_retired": 5, "score_threshold": 120},
        "inductees": [
            {
                "player_id": "P3",
                "player_name": "Hall Legend",
                "inducted_year": 2026,
                "score": 150,
            }
        ],
    }
    hof_path = data_dir / "hall_of_fame.json"
    hof_path.parent.mkdir(parents=True, exist_ok=True)
    hof_path.write_text(json.dumps(hof_payload, indent=2), encoding="utf-8")

    import services.special_events as special_events
    importlib.reload(special_events)
    import services.timeline_feed as timeline_feed
    importlib.reload(timeline_feed)

    entries = timeline_feed.build_timeline_feed(limit=None)
    labels = [entry.get("label") for entry in entries]
    assert any(label == "Hit for the Cycle" for label in labels)
    assert any(label == "Award: Mvp" or label == "Award: MVP" for label in labels)
    assert any(label == "Hall of Fame Induction" for label in labels)
