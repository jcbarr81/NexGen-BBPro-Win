from __future__ import annotations

from models.player import Player
from services import unified_data_service
from services.players_repository import save_players
from services.unified_data_service import get_unified_data_service
from utils.player_loader import load_players_from_csv


def _make_player(player_id: str, first_name: str) -> Player:
    return Player(
        player_id=player_id,
        first_name=first_name,
        last_name="Tester",
        birthdate="1990-01-01",
        height=72,
        weight=190,
        bats="R",
        primary_position="1B",
        other_positions=[],
        gf=50,
        ch=55,
        ph=60,
        sp=45,
        eye=54,
        pl=58,
        vl=56,
        sc=52,
        fa=53,
        arm=57,
    )


def test_save_players_refreshes_cache_without_manual_clear(tmp_path, monkeypatch):
    players_path = tmp_path / "players.csv"

    # Isolate this test from process-global service state.
    monkeypatch.setattr(unified_data_service, "_SERVICE", None)
    service = get_unified_data_service()
    service.invalidate_players()

    save_players([_make_player("P1", "Old")], players_path)
    initial = load_players_from_csv(players_path)
    assert initial[0].first_name == "Old"

    # Second save should replace the cached players payload automatically.
    save_players([_make_player("P1", "New")], players_path)
    refreshed = load_players_from_csv(players_path)
    assert refreshed[0].first_name == "New"


def test_save_players_emits_players_updated_event(tmp_path, monkeypatch):
    players_path = tmp_path / "players.csv"

    monkeypatch.setattr(unified_data_service, "_SERVICE", None)
    service = get_unified_data_service()
    service.invalidate_players()

    observed_paths = []
    unsubscribe = service.events.subscribe(
        "players.updated",
        lambda payload: observed_paths.append(payload.get("path")),
    )
    try:
        save_players([_make_player("P2", "Event")], players_path)
    finally:
        unsubscribe()

    assert observed_paths
    assert observed_paths[-1].resolve(strict=False) == players_path.resolve(strict=False)
