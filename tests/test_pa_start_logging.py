"""Audit L18 (2026-10-06): base-out state on the first pitch_log entry of a PA.

The engine adds ``pa_start``, ``inning``, ``half``, ``outs_before``,
``bases_before`` (1 = first, 2 = second, 4 = third), ``bat_score_before`` and
``fld_score_before`` to the first entry each plate appearance writes. The
situational KPIs (RE24, late & close, runs on inning-ending plays) read them.
"""
from pathlib import Path

import pytest

from physics_sim.engine import (
    BaseState,
    _bases_mask,
    _pa_start_context,
    simulate_matchup_from_files,
)

CAL = Path("data/calibration")
PA_START_KEYS = {
    "pa_start",
    "inning",
    "half",
    "outs_before",
    "bases_before",
    "bat_score_before",
    "fld_score_before",
}


def _runner(pid: str):
    class _R:
        player_id = pid

    return _R()


def test_bases_mask_bits():
    assert _bases_mask(BaseState()) == 0
    assert _bases_mask(BaseState(first=_runner("a"))) == 1
    assert _bases_mask(BaseState(second=_runner("b"))) == 2
    assert _bases_mask(BaseState(third=_runner("c"))) == 4
    loaded = BaseState(first=_runner("a"), second=_runner("b"), third=_runner("c"))
    assert _bases_mask(loaded) == 7
    assert _bases_mask(BaseState(first=_runner("a"), third=_runner("c"))) == 5


def test_pa_start_context_fields():
    ctx = _pa_start_context(
        inning=7,
        batting_team="home",
        outs=2,
        bases=BaseState(second=_runner("b")),
        bat_score=3,
        fld_score=4,
    )
    assert ctx == {
        "pa_start": True,
        "inning": 7,
        "half": "bottom",
        "outs_before": 2,
        "bases_before": 2,
        "bat_score_before": 3,
        "fld_score_before": 4,
    }
    top = _pa_start_context(
        inning=1, batting_team="away", outs=0, bases=BaseState(),
        bat_score=0, fld_score=0,
    )
    assert top["half"] == "top"


@pytest.mark.parametrize("seed", [3, 11, 29])
def test_every_pa_logs_its_start_state_once(seed):
    result = simulate_matchup_from_files(
        away_team="CAL04",
        home_team="CAL09",
        players_path=CAL / "players.csv",
        base_dir=CAL,
        seed=seed,
    )
    starts = [e for e in result.pitch_log if e.get("pa_start")]
    # One tagged entry per plate appearance, IBB and bunt PAs included.
    assert len(starts) == result.totals["pa"]
    for entry in starts:
        assert PA_START_KEYS <= set(entry)
        assert entry["half"] in {"top", "bottom"}
        assert entry["outs_before"] in (0, 1, 2)
        assert 0 <= entry["bases_before"] <= 7
        assert entry["inning"] >= 1
    # Untagged entries (later pitches of a PA) carry none of the keys.
    for entry in result.pitch_log:
        if not entry.get("pa_start"):
            assert not (PA_START_KEYS & set(entry))

    # Each half-inning opens with no outs; outs never go down within it.
    inning_runs = result.metadata["inning_runs"]
    halves: dict[tuple[int, str], list[dict]] = {}
    for entry in starts:
        halves.setdefault((entry["inning"], entry["half"]), []).append(entry)
    for (inning, half), entries in halves.items():
        assert entries[0]["outs_before"] == 0
        outs = [e["outs_before"] for e in entries]
        assert outs == sorted(outs)
        # The batting team's score entering the half equals its line score
        # through the previous inning; the fielding team's likewise.
        bat_side, fld_side = ("away", "home") if half == "top" else ("home", "away")
        fld_innings = inning - 1 if half == "top" else inning
        assert entries[0]["bat_score_before"] == sum(
            inning_runs[bat_side][: inning - 1]
        )
        assert entries[0]["fld_score_before"] == sum(
            inning_runs[fld_side][:fld_innings]
        )
    # The game opens with the bases empty, 0-0.
    first = starts[0]
    assert (first["inning"], first["half"], first["bases_before"]) == (1, "top", 0)
    assert (first["bat_score_before"], first["fld_score_before"]) == (0, 0)
