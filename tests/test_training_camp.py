from playbalance.training_camp import run_training_camp
from playbalance.player_development import TrainingWeights
from models.player import Player


def make_player(pid: str) -> Player:
    return Player(
        player_id=pid,
        first_name="Test",
        last_name="Player",
        birthdate="2000-01-01",
        height=72,
        weight=180,
        bats="R",
        primary_position="P",
        other_positions=[],
        gf=0,
        ch=40,
        ph=30,
        pot_ch=70,
        pot_ph=65,
    )


def test_training_camp_returns_reports_and_sets_ready(monkeypatch) -> None:
    calls = {}

    def _capture_reports(reports, **kwargs):
        calls["count"] = len(list(reports))

    monkeypatch.setattr("playbalance.training_camp.record_training_session", _capture_reports)

    players = [make_player("p1"), make_player("p2")]
    assert all(not p.ready for p in players)

    reports = run_training_camp(players)
    assert len(reports) == len(players)
    assert all(p.ready for p in players)
    assert any(report.changes for report in reports)
    assert calls.get("count") == len(players)


def test_training_camp_respects_custom_allocations(monkeypatch) -> None:
    player = make_player("custom")
    player.ch = 70
    player.pot_ch = 72
    player.ph = 55
    player.pot_ph = 90

    default_pitcher_weights = {
        "command": 25,
        "movement": 20,
        "stamina": 20,
        "velocity": 20,
        "hold": 5,
        "pitch_lab": 10,
    }

    allocations = {
        player.player_id: TrainingWeights(
            hitters={
                "contact": 5,
                "power": 55,
                "speed": 10,
                "discipline": 15,
                "defense": 15,
            },
            pitchers=default_pitcher_weights,
        )
    }

    monkeypatch.setattr(
        "playbalance.training_camp.record_training_session",
        lambda reports, **_: None,
    )

    reports = run_training_camp([player], allocations=allocations)
    assert reports[0].focus == "Strength & Lift"


def test_training_camp_applies_intensity_multiplier(monkeypatch) -> None:
    monkeypatch.setattr(
        "playbalance.training_camp.record_training_session",
        lambda reports, **_: None,
    )
    low = make_player("low")
    high = make_player("high")
    low.is_pitcher = False
    high.is_pitcher = False
    low.primary_position = "1B"
    high.primary_position = "1B"
    low.ch = 35
    high.ch = 35
    low.pot_ch = 90
    high.pot_ch = 90
    low.ph = 35
    high.ph = 35
    low.pot_ph = 90
    high.pot_ph = 90

    reports = run_training_camp(
        [low, high],
        intensity_by_player={"low": 0.80, "high": 1.25},
    )
    by_id = {report.player_id: report for report in reports}
    low_gain = sum(by_id["low"].changes.values())
    high_gain = sum(by_id["high"].changes.values())
    assert high_gain >= low_gain
