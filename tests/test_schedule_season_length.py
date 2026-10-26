"""The regular season ends in the autumn, so the postseason does too.

Both live leagues' 2026 schedules were generated before Release 3 made the
layout dense (a league-wide off day after every series): 162 game dates ran
from April 1 to December 30, and the 2026 World Series was played in January
2027. The new-season schedule (``league_presets.generate_schedule_from_template``
with ``mlb_162``, what the preseason step generates) must keep 162 games inside
MLB's calendar.
"""

from datetime import date

import pytest

from services.league_presets import generate_schedule_from_template


@pytest.mark.parametrize("clubs", [20, 30])
def test_mlb_162_ends_by_mid_october(clubs):
    teams = [f"T{i:02d}" for i in range(clubs)]
    schedule = generate_schedule_from_template("mlb_162", teams, year=2027)
    dates = sorted({g["date"] for g in schedule})
    assert dates[0] == "2027-04-01"
    assert date.fromisoformat(dates[-1]) <= date(2027, 10, 15)
    assert len(schedule) == clubs * 162 // 2
