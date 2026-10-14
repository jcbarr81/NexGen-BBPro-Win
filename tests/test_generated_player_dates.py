"""Generated players are dated from the LEAGUE's year, not the calendar's.

Until 8.0 ``player_generator.generate_birthdate`` counted every age back
from the real date, and ``draft_pool`` kept that birthdate over its own: a
league whose year had run ahead of the calendar drafted "19-year-olds" who
were 19 plus the difference. Now the reference day is today moved into the
league's year (a draft class: into the draft year). A league whose year IS
the real year generates exactly what it did (golden hash taken with the
04364883a generator and draft pool on the same scenario).
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import asdict
from datetime import date, datetime as _dt

import pytest

from playbalance import draft_pool, player_generator as pg


class _FakeToday(_dt):
    """``datetime.today()`` is 5 May 2026."""

    @classmethod
    def today(cls):
        return _dt(2026, 5, 5, 12, 0)


@pytest.fixture
def may_2026(monkeypatch):
    monkeypatch.setattr(pg, "datetime", _FakeToday)
    logging.disable(logging.WARNING)
    yield
    logging.disable(logging.NOTSET)


# Scale 1, league year 2026 = the (faked) real year: 40 players and an
# 80-prospect class, identical to 04364883a.
GOLDEN_SCALE_1 = "184b6e075afb978f96074e2b8e070043ca808a5f461e67e09fe6cf83dd62c659"


def test_scale_1_generation_in_a_league_of_this_year_is_unchanged(may_2026, monkeypatch):
    monkeypatch.setenv("PB_SIM_YEAR", "2026")
    out = []
    pg.reset_name_cache()
    random.seed(5)
    for i in range(40):
        out.append(pg.generate_player(is_pitcher=bool(i % 2), for_draft=bool(i % 3 == 0)))
    pg.reset_name_cache()
    out += [asdict(p) for p in draft_pool.generate_draft_pool(2026, size=80, seed=7, rating_scale=1)]
    digest = hashlib.sha256(json.dumps(out, sort_keys=True, default=str).encode()).hexdigest()
    assert digest == GOLDEN_SCALE_1


def test_the_reference_day_is_today_in_the_leagues_year(may_2026, monkeypatch):
    assert pg.reference_datetime(2026) == _FakeToday.today()
    # A league with no sim date: today moved into its year.
    monkeypatch.setattr(pg, "_league_sim_date", lambda: None)
    assert pg.reference_datetime(2031).date() == date(2031, 5, 5)


def test_the_reference_day_is_the_leagues_sim_date(may_2026, monkeypatch):
    """Fix-up 8: a league ahead of the calendar dates players from its own
    sim date (today's month and day moved into its year could date a draft
    class months after its draft: a 16-year-old draftee). A class made for
    a later year than the sim date's is dated 1 January of that year. A
    league in the real year is unchanged."""

    monkeypatch.setenv("PB_SIM_DATE", "2031-03-02")
    assert pg.reference_datetime(2031).date() == date(2031, 3, 2)
    assert pg.reference_datetime().date() == date(2031, 3, 2)
    assert pg.reference_datetime(2032).date() == date(2032, 1, 1)
    monkeypatch.setenv("PB_SIM_DATE", "2026-03-02")
    assert pg.reference_datetime(2026) == _FakeToday.today()
    monkeypatch.delenv("PB_SIM_DATE")
    monkeypatch.setenv("PB_SIM_YEAR", "2034")
    assert pg.reference_datetime().date() == date(2034, 7, 1)


def test_a_draft_class_made_during_the_season_has_no_16_year_olds(may_2026, monkeypatch):
    # Today is 5 May; the league's draft is in March of 2031 (a preseason
    # draft): every prospect is at least 17 on the league's own date.
    monkeypatch.setenv("PB_SIM_DATE", "2031-03-02")
    pg.reset_name_cache()
    pool = draft_pool.generate_draft_pool(2031, size=200, seed=11, rating_scale=1)
    youngest = max(date.fromisoformat(str(p.birthdate)[:10]) for p in pool)
    # Born on or before 2 March 2014: 17 on the league's date.
    assert youngest <= date(2014, 3, 2), youngest


@pytest.mark.parametrize("year", [2026, 2033])
def test_a_draft_class_is_17_to_22_in_its_own_year(may_2026, year):
    pg.reset_name_cache()
    pool = draft_pool.generate_draft_pool(year, size=120, seed=3, rating_scale=1)
    ages = [year - int(p.birthdate[:4]) for p in pool]
    assert 17 <= min(ages) and max(ages) <= 23, sorted(set(ages))


def test_a_draft_class_does_not_depend_on_the_real_date(monkeypatch):
    """With an explicit reference day (what the population sim passes) a
    class is the same whatever the calendar says."""

    def pool(today):
        class Fake(_dt):
            @classmethod
            def today(cls):
                return today

        monkeypatch.setattr(pg, "datetime", Fake)
        pg.reset_name_cache()
        return [
            asdict(p)
            for p in draft_pool.generate_draft_pool(
                2030, size=60, seed=9, rating_scale=2, reference=_dt(2030, 7, 1)
            )
        ]

    assert pool(_dt(2026, 2, 14)) == pool(_dt(2027, 9, 1))


def test_eye_is_marked_down_less_only_for_a_scale_2_class():
    from utils.rating_scale import engine_rating

    def eyes(scale):
        pg.reset_name_cache()
        return [
            engine_rating(asdict(p), "eye")
            for p in draft_pool.generate_draft_pool(
                2030, size=200, seed=4, rating_scale=scale, reference=_dt(2030, 7, 1)
            )
            if not p.is_pitcher
        ]

    one, two = eyes(1), eyes(2)
    assert len(one) == len(two) > 60
    # Marked down by a quarter of the age markdown, without the jitter.
    assert sum(two) / len(two) > sum(one) / len(one) + 5
    pg.reset_name_cache()
    plain = draft_pool.generate_draft_pool(2030, size=40, seed=4, rating_scale=1)
    pg.reset_name_cache()
    full = draft_pool.generate_draft_pool(2030, size=40, seed=4, rating_scale=2)
    # Same players otherwise: no random number depends on the scale.
    assert [p.player_id for p in plain] == [p.player_id for p in full]
    assert [p.birthdate for p in plain] == [p.birthdate for p in full]
    assert [p.fb for p in plain] == [p.fb for p in full]
