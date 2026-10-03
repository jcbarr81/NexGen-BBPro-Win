"""Every column on a player profile shows something.

An owner reported a 19-year-old with "a grand total of 0 strikeouts in 198 AB",
then noticed nobody had any. The profile reads strikeouts from ``k``; the
simulation records them as ``so``. The column was blank for every hitter and
every pitcher. Checking the rest of the table turned up three more pitching
columns blank for everyone: win percentage, opponents' average, and DERA.
"""

import pytest

from services.player_profile_view_model import (
    _BATTING_STATS,
    _PITCHING_STATS,
    _stats_to_dict,
    _sum_stat_rows,
)

HITTER = {"g": 52, "ab": 198, "h": 78, "hr": 20, "bb": 19, "so": 24, "2b": 14, "3b": 1}
PITCHER = {
    "g": 13, "gs": 13, "w": 6, "l": 5, "outs": 211, "h": 87, "er": 36, "bb": 41,
    "hbp": 11, "so": 88, "bf": 414, "fip": 4.6512,
}


# --- strikeouts ------------------------------------------------------------


def test_a_hitters_strikeouts_reach_the_k_column():
    assert _stats_to_dict(HITTER, False)["k"] == 24


def test_a_pitchers_strikeouts_reach_the_k_column():
    assert _stats_to_dict(PITCHER, True)["k"] == 88


def test_an_explicit_k_is_not_overwritten():
    """Some history rows may already carry k; trust it."""
    assert _stats_to_dict({**HITTER, "k": 30}, False)["k"] == 30


# --- the pitching rates nobody computed ------------------------------------


def test_win_pct_is_wins_over_decisions():
    assert _stats_to_dict(PITCHER, True)["pct"] == pytest.approx(6 / 11, abs=0.001)


def test_no_decisions_means_no_win_pct():
    """.000 would say he lost every decision; he has none."""
    row = _stats_to_dict({**PITCHER, "w": 0, "l": 0}, True)
    assert "pct" not in row


def test_opponents_average_uses_at_bats_not_batters_faced():
    """Walks and hit batters are plate appearances, not at-bats."""
    row = _stats_to_dict(PITCHER, True)
    assert row["oba"] == pytest.approx(87 / (414 - 41 - 11), abs=0.001)


def test_no_batters_faced_means_no_opponents_average():
    row = _stats_to_dict({k: v for k, v in PITCHER.items() if k != "bf"}, True)
    assert "oba" not in row


def test_fip_replaces_the_dera_column_nothing_produced():
    assert "dera" not in _PITCHING_STATS
    assert "fip" in _PITCHING_STATS
    assert _stats_to_dict(PITCHER, True)["fip"] == pytest.approx(4.65, abs=0.01)


# --- the career row --------------------------------------------------------


def test_career_rates_are_recomputed_not_summed():
    """Two identical seasons: counts double, rates stay put."""
    season = _stats_to_dict(PITCHER, True)
    career = _sum_stat_rows([season, dict(season)], is_pitcher=True)
    assert career["k"] == 176
    assert career["pct"] == pytest.approx(season["pct"], abs=0.001)
    assert career["oba"] == pytest.approx(season["oba"], abs=0.001)
    assert career["fip"] == pytest.approx(season["fip"], abs=0.01)


def test_career_fip_is_weighted_by_innings():
    """A 200-inning season outweighs a 10-inning one."""
    big = _stats_to_dict({**PITCHER, "outs": 600, "fip": 3.00}, True)
    small = _stats_to_dict({**PITCHER, "outs": 30, "fip": 9.00}, True)
    career = _sum_stat_rows([big, small], is_pitcher=True)
    assert career["fip"] == pytest.approx((3.00 * 200 + 9.00 * 10) / 210, abs=0.01)


# --- the regression guard --------------------------------------------------


@pytest.mark.parametrize(
    "columns, block, is_pitcher",
    [(_BATTING_STATS, HITTER, False), (_PITCHING_STATS, PITCHER, True)],
)
def test_no_column_the_profile_promises_is_left_blank(columns, block, is_pitcher):
    """The class of bug, not just this instance: a column whose key the
    simulation never writes. Some counting stats are legitimately absent from a
    minimal block, so check only the ones this block has the inputs for."""
    row = _stats_to_dict(block, is_pitcher)
    must_have = {"k"} | ({"pct", "oba", "fip"} if is_pitcher else set())
    missing = [c for c in columns if c in must_have and row.get(c) in (None, "")]
    assert missing == []
