from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from ui.analytics.quick_metrics import gather_owner_quick_metrics


def test_gather_owner_quick_metrics_handles_missing(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "standings.json").write_text(json.dumps({}), encoding="utf-8")
    (data_dir / "schedule.csv").write_text(
        "date,home,away,result,played\n", encoding="utf-8"
    )

    roster = SimpleNamespace(dl=[], ir=[], act=[])
    players: dict[str, object] = {}

    metrics = gather_owner_quick_metrics(
        "TST", base_path=tmp_path, roster=roster, players=players
    )

    assert metrics["record"] == "--"
    assert metrics["calibration"]["enabled"] is False
    assert metrics["bullpen"]["total"] == 0
    assert metrics["matchup"]["opponent"] == "--"
    assert metrics["batting_leaders"] == {
        "avg": "--",
        "hr": "--",
        "rbi": "--",
    }
    assert metrics["pitching_leaders"] == {
        "wins": "--",
        "so": "--",
        "saves": "--",
    }
    meta = metrics.get("leader_meta", {})
    assert meta.get("batting") == {}
    assert meta.get("pitching") == {}


def test_gather_owner_quick_metrics_team_leader_rows(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "standings.json").write_text(json.dumps({}), encoding="utf-8")
    (data_dir / "schedule.csv").write_text(
        "date,home,away,result,played\n", encoding="utf-8"
    )
    season_stats = {
        "players": {
            "BAT1": {"ab": 100, "h": 30, "avg": 0.300, "hr": 12, "rbi": 40},
            "BAT2": {"ab": 80, "h": 35, "avg": 0.438, "hr": 10, "rbi": 30},
            "PIT1": {"ip": 95.0, "w": 12, "so": 150, "sv": 0},
            "PIT2": {"ip": 60.0, "w": 2, "so": 65, "sv": 22},
        },
        "teams": {},
        "history": [],
    }
    (data_dir / "season_stats.json").write_text(
        json.dumps(season_stats), encoding="utf-8"
    )

    roster = SimpleNamespace(
        dl=[],
        ir=[],
        act=["BAT1", "BAT2", "PIT1", "PIT2"],
    )
    players = {
        "BAT1": SimpleNamespace(
            player_id="BAT1",
            first_name="Slugger",
            last_name="One",
            is_pitcher=False,
            primary_position="RF",
        ),
        "BAT2": SimpleNamespace(
            player_id="BAT2",
            first_name="Slugger",
            last_name="Two",
            is_pitcher=False,
            primary_position="CF",
        ),
        "PIT1": SimpleNamespace(
            player_id="PIT1",
            first_name="Ace",
            last_name="Starter",
            is_pitcher=True,
            primary_position="SP",
        ),
        "PIT2": SimpleNamespace(
            player_id="PIT2",
            first_name="Closer",
            last_name="Guy",
            is_pitcher=True,
            primary_position="RP",
        ),
    }

    metrics = gather_owner_quick_metrics(
        "TST", base_path=tmp_path, roster=roster, players=players
    )

    assert metrics["batting_leaders"]["avg"] == "Slugger Two .438"
    assert metrics["batting_leaders"]["hr"] == "Slugger One 12"
    assert metrics["batting_leaders"]["rbi"] == "Slugger One 40"
    assert metrics["pitching_leaders"]["wins"] == "Ace Starter 12"
    assert metrics["pitching_leaders"]["so"] == "Ace Starter 150"
    assert metrics["pitching_leaders"]["saves"] == "Closer Guy 22"
    leader_meta = metrics["leader_meta"]
    assert leader_meta["batting"]["avg"]["player_id"] == "BAT2"
    assert leader_meta["batting"]["hr"]["player_id"] == "BAT1"
    assert leader_meta["batting"]["rbi"]["player_id"] == "BAT1"
    assert leader_meta["pitching"]["wins"]["player_id"] == "PIT1"
    assert leader_meta["pitching"]["so"]["player_id"] == "PIT1"
    assert leader_meta["pitching"]["saves"]["player_id"] == "PIT2"


def test_gather_owner_quick_metrics_bullpen_available_pct(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "standings.json").write_text(json.dumps({}), encoding="utf-8")
    (data_dir / "schedule.csv").write_text(
        "date,home,away,result,played\n", encoding="utf-8"
    )
    today = datetime.utcnow().strftime("%Y-%m-%d")
    tracker = SimpleNamespace(
        data={
            "teams": {
                "TST": {
                    "pitchers": {
                        "RP1": {
                            "available_on": today,
                            "last_used": "2026-02-20",
                            "last_pitches": 24,
                            "max_pitches": 40,
                            "available_pitches": 20,
                        }
                    }
                }
            }
        },
        ensure_team=lambda *args, **kwargs: None,
        bullpen_game_status=lambda *args, **kwargs: {
            "RP1": {
                "available_on": today,
                "last_pitches": 24,
                "available_pct": 0.5,
            }
        },
    )

    class _DummyRecovery:
        @staticmethod
        def instance():
            return tracker

    monkeypatch.setattr("ui.analytics.quick_metrics.PitcherRecoveryTracker", _DummyRecovery)

    roster = SimpleNamespace(dl=[], ir=[], act=["RP1"])
    players = {
        "RP1": SimpleNamespace(
            player_id="RP1",
            first_name="Relief",
            last_name="One",
            role="MR",
            is_pitcher=True,
            primary_position="RP",
        )
    }

    metrics = gather_owner_quick_metrics(
        "TST", base_path=tmp_path, roster=roster, players=players
    )

    bullpen = metrics["bullpen"]
    assert bullpen["total"] == 1
    assert bullpen["avg_available_pct"] == pytest.approx(0.5)
    assert "Avg budget 50%" in bullpen["headline"]
    detail = bullpen["detail"][0]
    assert detail["available_pct"] == pytest.approx(0.5)


def test_gather_owner_quick_metrics_loads_usage_calibration_summary(tmp_path):
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True)
    (data_dir / "standings.json").write_text(json.dumps({}), encoding="utf-8")
    (data_dir / "schedule.csv").write_text(
        "date,home,away,result,played\n", encoding="utf-8"
    )
    payload = {
        "generated_at": "2026-02-23T15:20:00Z",
        "summary": "3/4 role targets in range.",
        "targets": {
            "CL": {"all_in_range": True},
            "SU": {"all_in_range": True},
            "MR": {"all_in_range": True},
            "LR": {"all_in_range": False},
        },
        "roles": {"CL": {"avg_g": 64.0, "avg_ip": 62.0}},
    }
    (reports_dir / "usage_calibration_summary.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    metrics = gather_owner_quick_metrics(
        "TST",
        base_path=tmp_path,
        roster=SimpleNamespace(dl=[], ir=[], act=[]),
        players={},
    )

    usage = metrics["usage_calibration"]
    assert usage["available"] is True
    assert usage["summary"] == "3/4 role targets in range."
    assert usage["target_groups"] == 4
    assert usage["target_groups_in_range"] == 3
    assert usage["target_pass_rate"] == pytest.approx(0.75)
