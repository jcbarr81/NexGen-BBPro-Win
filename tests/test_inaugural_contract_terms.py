"""Inaugural contract-length spread.

Regression for the "every player on a 1-year deal" bug: a brand-new league used
to seed years_left=1 for the whole roster, so the entire league hit free agency
after year one. The seeder now spreads lengths 1-6yr by age + quality with a
deterministic per-player jitter.
"""

from statistics import mean
from types import SimpleNamespace

from services import contracts_service as cs

YEAR = 2026


def _player(pid, age, ovr):
    return SimpleNamespace(
        player_id=pid,
        birthdate=f"{YEAR - age}-06-15",
        is_pitcher=False,
        primary_position="1B",
        ch=ovr, ph=ovr, sp=ovr, eye=ovr, fa=ovr, arm=ovr,
    )


def _years(pid, age, ovr):
    p = _player(pid, age, ovr)
    sal = cs.estimate_salary_for_player(p)
    return cs._seed_contract_years(p, pid, season_year=YEAR, annual_salary=sal)


PIDS = [f"P{i:04d}" for i in range(300)]


def test_always_in_1_to_6_range():
    for pid in PIDS:
        for age in (20, 25, 30, 35, 40):
            for ovr in (40, 55, 70, 85):
                y = _years(pid, age, ovr)
                assert 1 <= y <= 6


def test_deterministic():
    # Same player id + inputs -> identical length every call (idempotent reseed).
    for pid in PIDS[:20]:
        a = _years(pid, 27, 60)
        b = _years(pid, 27, 60)
        assert a == b


def test_not_all_one_year_and_real_spread():
    # A cohort of mixed players must produce a genuine spread of lengths, not the
    # old all-1-year behavior.
    lengths = [_years(pid, age, ovr)
               for pid in PIDS
               for age, ovr in ((22, 65), (28, 60), (34, 55))]
    distinct = set(lengths)
    assert len(distinct) >= 5, f"expected a wide spread, got {sorted(distinct)}"
    assert lengths.count(1) < len(lengths), "everyone still on 1-year deals"


def test_age_trend_young_longer_than_old():
    young = mean(_years(pid, 22, 60) for pid in PIDS)
    old = mean(_years(pid, 35, 60) for pid in PIDS)
    assert young > old + 1.0, f"young={young:.2f} old={old:.2f}"


def test_quality_trend_stars_longer_than_fringe():
    star = mean(_years(pid, 28, 85) for pid in PIDS)
    fringe = mean(_years(pid, 28, 42) for pid in PIDS)
    assert star > fringe, f"star={star:.2f} fringe={fringe:.2f}"


def test_crossover_from_randomness():
    # The jitter must let SOME veterans land multi-year deals and SOME youngsters
    # land short ones (the user's explicit ask).
    vets_long = [pid for pid in PIDS if _years(pid, 35, 58) >= 2]
    kids_short = [pid for pid in PIDS if _years(pid, 22, 62) <= 3]
    assert vets_long, "no veteran got a multi-year deal"
    assert kids_short, "no young player got a short deal"


def test_build_seed_contract_uses_spread_and_sets_fa_year():
    # End-to-end through the actual builder used by the inaugural seeder.
    years_seen = set()
    for pid in PIDS[:50]:
        contract, meta = cs._build_seed_contract(
            team_id="AAA", player_id=pid, player=_player(pid, 26, 63), season_year=YEAR
        )
        assert contract["years_left"] == meta["years_left"]
        assert contract["fa_year"] == YEAR + contract["years_left"]
        assert 1 <= contract["years_left"] <= 6
        years_seen.add(contract["years_left"])
    assert len(years_seen) >= 2, "builder produced no variation"
