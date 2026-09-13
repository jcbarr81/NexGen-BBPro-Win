"""A team's totals are the sum of the players currently on its roster.

Season stats belong to the player and travel with him on a trade. That is the
league's chosen model, so these totals deliberately need not tie out to the
club's game log: DAL shows 53 starts across 43 games because it acquired a
pitcher who had made ten of them elsewhere. The club's own W-L-G record is a
separate fact and is not computed here.

The thing most easily got wrong is rates. Averaging a column of averages is
wrong whenever the denominators differ, which across a roster is always.
"""

import pytest

from services.team_totals import (
    BATTING_TOTALS,
    PITCHING_TOTALS,
    batting_totals,
    pitching_totals,
    roster_totals,
)


# --- rates are recomputed, never averaged ----------------------------------


def test_batting_average_is_recomputed_from_components():
    """Two hitters, .500 on 2 AB and .100 on 100 AB. The mean of the averages
    is .300; the team actually hit .118."""
    totals = batting_totals([
        {"ab": 2, "h": 1, "avg": 0.5},
        {"ab": 100, "h": 11, "avg": 0.11},
    ])
    assert totals["ab"] == 102
    assert totals["h"] == 12
    assert totals["avg"] == pytest.approx(12 / 102, abs=0.001)


def test_era_is_recomputed_from_earned_runs_and_innings():
    """One inning of batting practice must not drag a staff's ERA to its own."""
    totals = pitching_totals([
        {"outs": 3, "er": 9, "era": 81.0},
        {"outs": 600, "er": 60, "era": 2.7},
    ])
    innings = 603 / 3
    assert totals["ip"] == pytest.approx(innings, abs=0.1)
    assert totals["era"] == pytest.approx(9 * 69 / innings, abs=0.01)


def test_whip_is_recomputed():
    totals = pitching_totals([
        {"outs": 300, "h": 90, "bb": 30},
        {"outs": 150, "h": 60, "bb": 20},
    ])
    assert totals["whip"] == pytest.approx(200 / 150, abs=0.001)


def test_on_base_uses_the_full_denominator():
    """OBP is (H+BB+HBP)/(AB+BB+HBP+SF) -- sacrifice flies count against you."""
    totals = batting_totals([{"ab": 100, "h": 25, "bb": 10, "hbp": 2, "sf": 3}])
    assert totals["obp"] == pytest.approx(37 / 115, abs=0.001)


def test_slugging_uses_total_bases():
    totals = batting_totals([{"ab": 10, "h": 4, "2b": 1, "3b": 1, "hr": 1, "tb": 9}])
    assert totals["slg"] == pytest.approx(0.9, abs=0.001)


def test_total_bases_is_reconstructed_when_absent():
    """Older blocks may not carry tb: 1 single + 1 double + 1 HR = 7."""
    totals = batting_totals([{"ab": 10, "h": 3, "2b": 1, "3b": 0, "hr": 1}])
    assert totals["slg"] == pytest.approx(0.7, abs=0.001)


def test_ops_is_obp_plus_slg():
    totals = batting_totals([{"ab": 100, "h": 30, "bb": 10, "tb": 50}])
    assert totals["ops"] == pytest.approx(totals["obp"] + totals["slg"], abs=0.001)


# --- counting stats sum straight across ------------------------------------


def test_counting_stats_add_up():
    totals = batting_totals([
        {"ab": 10, "h": 3, "hr": 1, "rbi": 2, "sb": 1},
        {"ab": 20, "h": 6, "hr": 2, "rbi": 5, "sb": 0},
    ])
    assert (totals["ab"], totals["h"], totals["hr"], totals["rbi"], totals["sb"]) == (30, 9, 3, 7, 1)


def test_starts_are_summed_even_past_the_games_played():
    """The whole point of the model: a pitcher acquired mid-season brings his
    earlier starts, so a 43-game team can show 53."""
    totals = pitching_totals([
        {"gs": 43, "outs": 1000},
        {"gs": 10, "outs": 180},  # acquired in a trade
    ])
    assert totals["gs"] == 53


def test_doubles_and_triples_are_read_under_either_spelling():
    """Blocks carry "2b"/"3b" in some places and "b2"/"b3" in others."""
    a = batting_totals([{"ab": 10, "h": 2, "2b": 2}])
    b = batting_totals([{"ab": 10, "h": 2, "b2": 2}])
    assert a["2b"] == b["2b"] == 2


def test_innings_prefer_exact_outs_over_the_accumulated_float():
    """``ip`` is a float that drifts; ``outs`` is exact."""
    totals = pitching_totals([{"outs": 211, "ip": 70.33333333333333}])
    assert totals["ip"] == pytest.approx(70.3, abs=0.05)


def test_a_block_without_outs_still_contributes_its_innings():
    totals = pitching_totals([{"ip": 9.0, "er": 3}])
    assert totals["ip"] == pytest.approx(9.0, abs=0.05)
    assert totals["era"] == pytest.approx(3.0, abs=0.01)


# --- nothing to report yet -------------------------------------------------


def test_an_empty_roster_reports_no_rate_rather_than_zero():
    """".000" is a claim about hitting; a team that has not batted made none."""
    totals = batting_totals([])
    assert totals["ab"] == 0
    assert totals["avg"] is None and totals["obp"] is None and totals["ops"] is None


def test_a_staff_with_no_innings_has_no_era():
    totals = pitching_totals([{"gs": 0}])
    assert totals["era"] is None and totals["whip"] is None


def test_junk_values_do_not_raise():
    totals = batting_totals([{"ab": "", "h": None, "hr": "x"}])
    assert totals["ab"] == 0 and totals["hr"] == 0


# --- shape -----------------------------------------------------------------


def test_every_advertised_column_is_present():
    batting = batting_totals([{"ab": 1, "h": 1}])
    pitching = pitching_totals([{"outs": 3}])
    assert set(batting) == set(BATTING_TOTALS)
    assert set(pitching) == set(PITCHING_TOTALS)


def test_games_played_is_not_summed():
    """Adding G over 25 players answers nothing; the club's own count is right
    beside it on the page."""
    assert "g" not in BATTING_TOTALS and "g" not in PITCHING_TOTALS


def test_roster_totals_groups_both_sides():
    out = roster_totals([{"ab": 4, "h": 1}], [{"outs": 3, "er": 1}])
    assert set(out) == {"batting", "pitching"}
    assert out["batting"]["h"] == 1 and out["pitching"]["er"] == 1
