from __future__ import annotations

from models.player import Player
from services.contract_negotiator import evaluate_free_agent_bids


def _make_player() -> Player:
    return Player(
        player_id="P1",
        first_name="Test",
        last_name="FA",
        birthdate="2000-01-01",
        height=72,
        weight=180,
        bats="R",
        primary_position="1B",
        other_positions=[],
        gf=0,
    )


def test_evaluate_free_agent_bids_accepts_team_id_keys() -> None:
    player = _make_player()
    winner = evaluate_free_agent_bids(
        player,
        {
            "AAA": 1_600_000,
            "BBB": 2_100_000,
        },
    )
    assert winner == "BBB"
    assert player.team_id == "BBB"
    assert int(player.salary) == 2_100_000
