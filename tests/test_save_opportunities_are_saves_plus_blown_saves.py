"""Audit L10: a save opportunity is a save or a blown save (SVO = SV + BS).

The engine used to add one SVO every time a pitcher entered a save situation,
including setup men in the 7th who left with a hold. A replicate season read
0.779 SVO per team-game against SV+BS of .434, so SV/SVO came out at .342.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from physics_sim.engine import simulate_matchup_from_files
from playbalance import game_runner

CAL = Path("data/calibration")


def _pitcher_lines(seed):
    result = simulate_matchup_from_files(
        away_team="CAL02",
        home_team="CAL01",
        players_path=CAL / "players.csv",
        base_dir=CAL,
        park_name="Fenway Park",
        seed=seed,
    )
    lines = result.metadata["pitcher_lines"]
    return [line for side in ("away", "home") for line in lines[side]]


def test_engine_publishes_svo_as_saves_plus_blown_saves():
    lines = [line for seed in range(1, 31) for line in _pitcher_lines(seed)]
    for line in lines:
        assert line["svo"] == line["sv"] + line["bs"], line
    # The fixture must exercise the cases that used to diverge: holds (a save
    # situation entered and handed on) and real saves.
    assert sum(line["hld"] for line in lines) > 0
    assert sum(line["sv"] for line in lines) > 0


def test_season_svo_is_rederived_from_saves_and_blown_saves(monkeypatch):
    """Persisting a game re-derives the season SVO, which also repairs the
    inflated totals older builds stored."""

    monkeypatch.setattr(game_runner, "active_journal", lambda: None)
    monkeypatch.setattr(
        "utils.stats_persistence.save_stats", lambda players, teams: None
    )
    pitcher = SimpleNamespace(
        season_stats={"g": 20, "sv": 5, "bs": 2, "hld": 6, "svo": 19}
    )
    metadata = {
        "pitcher_lines": {
            "home": [
                {"player_id": "p1", "g": 1, "sv": 1, "bs": 0, "hld": 0, "svo": 1}
            ]
        },
        "score": {"home": 3, "away": 2},
    }
    game_runner._persist_physics_stats(
        metadata=metadata,
        players_lookup={"p1": pitcher},
        home_team=None,
        away_team=None,
    )
    season = pitcher.season_stats
    assert season["sv"] == 6
    assert season["bs"] == 2
    assert season["svo"] == 8


@pytest.mark.parametrize("sv,bs", [(0, 0), (1, 0), (0, 1)])
def test_legacy_boxscore_svo_matches(sv, bs):
    from playbalance.simulation import TeamState, generate_boxscore
    from tests.test_simulation import make_pitcher

    def team(pid):
        state = TeamState(lineup=[], bench=[], pitchers=[make_pitcher(pid)])
        ps = state.current_pitcher_state
        ps.sv, ps.bs, ps.svo = sv, bs, 3
        state.pitcher_stats[pid] = ps
        return state

    box = generate_boxscore(team("hp"), team("ap"))
    for side in ("home", "away"):
        (line,) = box[side]["pitching"]
        assert line["svo"] == sv + bs
