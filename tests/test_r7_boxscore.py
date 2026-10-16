"""Round 5: owners see the foul-outs. A generation 7 box score's fielding
note names who caught each foul pop-up ("Foul outs: Diaz 2."), beside the
errors; no earlier generation has a foul-out, so its box score is as
before."""

from __future__ import annotations

from pathlib import Path

import pytest

import physics_sim.engine as engine
import scripts.physics_sim_season_kpis as kpis
from physics_sim import ballflight
from physics_sim.engine_generation import engine_profile
from playbalance.simulation import boxscore_foul_outs, fielding_note, foul_out_note
from utils import park_utils

REPO = Path(__file__).resolve().parents[1]
CAL = REPO / "data" / "calibration"
PLAYERS = CAL / "players.csv"


@pytest.fixture(autouse=True)
def _pinned_parks(monkeypatch):
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(REPO / "data"))
    ballflight.clear_fence_cache()


def _game(generation, seed):
    profile = engine_profile(generation, development=True)
    overrides = kpis.with_rating_centers(dict(profile), PLAYERS, CAL) if profile else None
    return engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", base_dir=CAL, players_path=PLAYERS,
        seed=seed, tuning_overrides=dict(overrides) if overrides else None,
    )


def test_a_foul_out_names_its_catcher_on_the_fielding_side():
    game = _game(7, 2)
    caught = [e for e in game.pitch_log if e.get("foul_out")]
    assert caught and all(e.get("foul_out_fielder") for e in caught)
    starting = game.play_records["starting_positions"]
    by_side = boxscore_foul_outs(game.pitch_log, game.metadata["fielding_lines"])
    assert sum(len(v) for v in by_side.values()) == len(caught)
    for side, items in by_side.items():
        for item in items:
            # The catcher is on the fielding side, at the position logged.
            assert starting[side].get(item["player_id"]) == item["position"]
    notes = {side: foul_out_note(items) for side, items in by_side.items()}
    assert any(note.startswith("Foul outs: ") for note in notes.values())


def test_the_note_counts_each_fielder_once():
    items = [
        {"player_id": "A", "name": "Ann Diaz", "position": "C"},
        {"player_id": "B", "name": "Bo Lopez", "position": "3B"},
        {"player_id": "A", "name": "Ann Diaz", "position": "C"},
    ]
    assert foul_out_note(items) == "Foul outs: Ann Diaz 2, Bo Lopez."
    assert foul_out_note([]) == ""
    assert fielding_note([]) == ""


@pytest.mark.parametrize("generation", [4, 6])
def test_no_earlier_generation_has_a_foul_out(generation):
    game = _game(generation, 2)
    assert not any("foul_out_fielder" in e or e.get("foul_out") for e in game.pitch_log)
    by_side = boxscore_foul_outs(game.pitch_log, game.metadata["fielding_lines"])
    assert by_side == {"home": [], "away": []}
