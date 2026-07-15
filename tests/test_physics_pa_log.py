"""S2-01: per-PA result tagging on the physics pitch log."""
from pathlib import Path

from physics_sim.engine import _pa_result_token, simulate_matchup_from_files

CAL = Path("data/calibration")


def test_pa_result_token_priority():
    # hr wins over h/ab; ibb wins over bb; hits over so/out; fc/gidp -> out.
    assert _pa_result_token({"hr": 1, "h": 1, "ab": 1}) == "hr"
    assert _pa_result_token({"b3": 1, "h": 1, "ab": 1}) == "3b"
    assert _pa_result_token({"b2": 1, "h": 1, "ab": 1}) == "2b"
    assert _pa_result_token({"h": 1, "ab": 1}) == "1b"
    assert _pa_result_token({"ibb": 1, "bb": 1}) == "ibb"
    assert _pa_result_token({"bb": 1}) == "bb"
    assert _pa_result_token({"hbp": 1}) == "hbp"
    assert _pa_result_token({"so": 1, "ab": 1}) == "so"
    assert _pa_result_token({"sf": 1}) == "sf"
    assert _pa_result_token({"sh": 1}) == "sh"
    assert _pa_result_token({"roe": 1}) == "roe"
    assert _pa_result_token({"ab": 1}) == "out"
    assert _pa_result_token({"fc": 1}) == "out"
    assert _pa_result_token({"gidp": 1}) == "out"
    assert _pa_result_token({}) is None


def test_pitch_log_tags_nearly_all_pas():
    result = simulate_matchup_from_files(
        away_team="CAL02",
        home_team="CAL01",
        players_path=CAL / "players.csv",
        base_dir=CAL,
        park_name="Fenway Park",
        seed=7,
    )
    pa = result.totals.get("pa", 0)
    tagged = sum(1 for e in result.pitch_log if "pa_result" in e)
    assert pa > 0
    assert tagged >= 0.98 * pa
