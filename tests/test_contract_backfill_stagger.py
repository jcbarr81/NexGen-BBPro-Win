"""Backfilled contracts must be STAGGERED across seasons so a realistic slice of
the league reaches free agency each year — including this one. The old logic only
gave a walk year to players with 3+ years of accrued service time, so a freshly
backfilled league (zero service time) handed everyone a 2-3 year deal and nobody
ever expired.
"""

from types import SimpleNamespace

from services.contracts_service import _infer_backfill_years_left


def _player(pid, age):
    return SimpleNamespace(player_id=pid, birthdate=f"{2026 - age}-06-15")


def test_backfill_years_left_are_staggered_including_walk_years():
    years = [
        _infer_backfill_years_left(
            _player(f"P{i}", 20 + (i % 20)),  # ages 20-39
            service_time_days=0,  # fresh league: no accrued service time
            season_year=2026,
            player_id=f"P{i}",
        )
        for i in range(400)
    ]
    assert all(1 <= y <= 6 for y in years)
    # A real spread: multiple distinct lengths, and a meaningful walk-year slice.
    assert len(set(years)) >= 4
    expiring = sum(1 for y in years if y == 1)
    assert expiring > 0, "no contracts expire this year"
    # Not everyone expires either.
    assert expiring < len(years)


def test_backfill_years_left_is_deterministic():
    a = _infer_backfill_years_left(
        _player("P1", 30), service_time_days=0, season_year=2026, player_id="P1"
    )
    b = _infer_backfill_years_left(
        _player("P1", 30), service_time_days=0, season_year=2026, player_id="P1"
    )
    assert a == b
