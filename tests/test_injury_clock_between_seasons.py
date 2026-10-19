"""8.2.1: between seasons the injured list counts to next opening day.

The rollover deletes the schedule, so there is no sim date in the offseason,
and the injured list fell back to the wall clock: alpha-test's COL had two
60-day stints that ended in January on the league's calendar (the rollover's
heal had found them over, as of opening day) showing "85" and "102 days
left" in October, and they could not be activated.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from tests.test_reset_keeps_playoff_config import league_root  # noqa: F401 (fixture)


def _between_seasons(root, year=2027):
    (root / "schedule.csv").unlink(missing_ok=True)
    (root / "career_index.json").write_text(
        json.dumps({"current": {"season_id": f"test-{year}", "league_year": year}}),
        encoding="utf-8",
    )


@pytest.fixture
def offseason(league_root):  # noqa: F811
    from utils.file_cache import invalidate

    _between_seasons(league_root)
    invalidate()
    return league_root


def _stint(eligible: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        player_id="P1", injured=True, injury_list="il60",
        injury_start_date="2026-11-13", injury_eligible_date=eligible,
        return_date=eligible,
    )


def test_the_league_clock_reads_next_opening_day(offseason):
    from services.injury_manager import league_today

    assert league_today() == date(2027, 4, 1)


def test_a_stint_that_ended_in_january_is_over(offseason):
    from services.injury_manager import disabled_list_days_remaining, is_player_dl_eligible

    player = _stint("2027-01-12")
    assert disabled_list_days_remaining(player) == 0
    assert is_player_dl_eligible(player)


def test_a_stint_past_opening_day_still_counts_from_it(offseason):
    from services.injury_manager import disabled_list_days_remaining

    assert disabled_list_days_remaining(_stint("2027-07-31")) == (date(2027, 7, 31) - date(2027, 4, 1)).days


def test_the_injuries_page_and_the_daily_step_use_the_same_clock(offseason):
    from api.routers import injuries
    from services import dl_automation

    assert injuries._sim_today() == date(2027, 4, 1)
    assert dl_automation._coerce_date(None) == date(2027, 4, 1)


def test_in_season_the_sim_date_still_rules(league_root):  # noqa: F811
    from services.injury_manager import league_today

    # The fixture's schedule has 2026-04-01 played, so the sim date is that day
    # or the next scheduled one; never opening day of a later year.
    assert league_today().year == 2026


def test_free_agents_carry_their_age():
    from types import SimpleNamespace

    from api.routers.free_agency import _age

    assert _age(SimpleNamespace(birthdate="")) is None
    age = _age(SimpleNamespace(birthdate="1990-05-20"))
    assert isinstance(age, int) and 30 <= age <= 45
