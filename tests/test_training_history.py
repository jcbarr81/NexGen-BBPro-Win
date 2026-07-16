from services import training_history
from playbalance.player_development import TrainingReport


def _report(player_id: str, focus: str, *, changes=None) -> TrainingReport:
    return TrainingReport(
        player_id=player_id,
        player_name="Test Player",
        focus=focus,
        tier="prospect",
        attributes=("ch", "vl"),
        note=f"{focus} drills",
        changes=changes or {"ch": 2},
    )


def test_record_and_load_training_history(tmp_path, monkeypatch) -> None:
    # Reports dir is resolved via _reports_dir() now (no _REPORTS_DIR constant).
    monkeypatch.setattr(training_history, "_reports_dir", lambda: tmp_path)

    training_history.record_training_session(
        [_report("p1", "Barrel Control")],
        season_id="season-2025",
        run_at="2025-03-01T12:00:00Z",
    )
    training_history.record_training_session(
        [_report("p1", "Strength & Lift"), _report("p2", "Command Clinic")],
        season_id="season-2025",
        run_at="2025-02-20T12:00:00Z",
    )

    history = training_history.load_player_training_history("p1", limit=10)
    assert len(history) == 2
    assert history[0]["focus"] == "Barrel Control"
    assert history[0]["season_id"] == "season-2025"
    assert "run_at" in history[0]

    limited = training_history.load_player_training_history("p1", limit=1)
    assert len(limited) == 1
    assert limited[0]["focus"] == "Barrel Control"

    other = training_history.load_player_training_history("p2", limit=5)
    assert len(other) == 1
    assert other[0]["focus"] == "Command Clinic"
