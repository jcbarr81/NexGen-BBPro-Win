import json
from playbalance.season_manager import SeasonManager, SeasonPhase


def test_cycle_phases(tmp_path):
    path = tmp_path / "state.json"
    manager = SeasonManager(path, enable_rollover=False)
    # Advance-phase order skips AMATEUR_DRAFT: the draft is a mid-regular-
    # season interruption entered via the sim's draft-day intercept, not a
    # phase you advance INTO. So PRESEASON → REGULAR_SEASON → PLAYOFFS → …
    assert manager.phase == SeasonPhase.PRESEASON
    assert manager.advance_phase() == SeasonPhase.REGULAR_SEASON
    assert manager.advance_phase() == SeasonPhase.PLAYOFFS
    assert manager.advance_phase() == SeasonPhase.OFFSEASON
    assert manager.advance_phase() == SeasonPhase.PRESEASON


def test_advance_from_amateur_draft_resumes_regular_season(tmp_path):
    # The sim's draft-day intercept sets AMATEUR_DRAFT directly; advancing
    # from there must RESUME the regular season (so Aug/Sep games still play),
    # not jump to the playoffs.
    path = tmp_path / "state.json"
    manager = SeasonManager(path, enable_rollover=False)
    manager.phase = SeasonPhase.AMATEUR_DRAFT
    assert manager.advance_phase() == SeasonPhase.REGULAR_SEASON


def test_state_persistence(tmp_path):
    path = tmp_path / "state.json"
    manager = SeasonManager(path, enable_rollover=False)
    manager.advance_phase()
    assert path.exists()
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["phase"] == "REGULAR_SEASON"
    new_manager = SeasonManager(path, enable_rollover=False)
    assert new_manager.phase == SeasonPhase.REGULAR_SEASON


def test_phase_handlers(tmp_path):
    path = tmp_path / "state.json"
    manager = SeasonManager(path, enable_rollover=False)
    assert "Preseason" in manager.handle_phase()
    manager.advance_phase()  # → REGULAR_SEASON
    assert "Regular Season" in manager.handle_phase()
    # AMATEUR_DRAFT is reached via the sim intercept, not advance_phase.
    manager.phase = SeasonPhase.AMATEUR_DRAFT
    assert "Amateur Draft" in manager.handle_phase()
    manager.phase = SeasonPhase.REGULAR_SEASON
    manager.advance_phase()  # → PLAYOFFS
    assert "Playoffs" in manager.handle_phase()
    manager.advance_phase()  # → OFFSEASON
    assert "Offseason" in manager.handle_phase()
