"""Extension pricing: one salary model, priced across the years it buys.

The bug these guard against: a pre-arbitration player short-circuited the whole
negotiation and accepted ANY offer at or above the league minimum. A 23-year-old
on $1.255M could be re-signed for $800k — a pay cut, for his best seasons. The
properties below are the ones that make that structurally impossible.
"""

import pytest

from services import contract_negotiator as cn
from services.contract_negotiator import (
    evaluate_extension_offer,
    extension_annual_value,
    fair_market_salary,
    fair_market_years,
)
from services.contracts_service import estimate_market_value_for_player


class FakePlayer:
    """Minimal stand-in with the ratings the quality score reads."""

    def __init__(self, *, quality=60, age=25, is_pitcher=False):
        self.is_pitcher = is_pitcher
        self.primary_position = "P" if is_pitcher else "CF"
        # birthdate that yields `age` for the aging helper
        from datetime import date

        self.birthdate = f"{date.today().year - age}-01-01"
        if is_pitcher:
            self.arm = self.control = self.movement = self.endurance = quality
        else:
            self.ph = self.ch = self.eye = self.sp = self.fa = self.arm = quality


def test_service_year_matches_the_salary_model():
    """162 vs 172 days silently re-tiered every free agent as an arb case."""
    from services import contracts_service as cs

    assert cn.FA_SERVICE_DAYS == cs.FA_SERVICE_DAYS
    assert cn.PRE_ARB_SERVICE_DAYS == cs.ARB_SERVICE_DAYS


def test_free_agent_is_priced_at_full_market():
    p = FakePlayer(quality=60, age=29)
    assert fair_market_salary(p, service_time_days=cn.FA_SERVICE_DAYS) == (
        estimate_market_value_for_player(p)
    )


# --- the reported bug -------------------------------------------------------


def test_young_player_rejects_a_pay_cut():
    """The Schmoyer case: 23, mid-quality, 2 years left at $1.255M."""
    p = FakePlayer(quality=55, age=23)
    ev = evaluate_extension_offer(
        p,
        offered_years=4,
        offered_annual_salary=800_000,
        service_time_days=0,
        current_annual_salary=1_255_000,
        current_years_left=2,
    )
    assert ev.decision == "rejected"
    assert ev.counter_salary > 1_255_000


def test_quote_never_falls_below_the_current_salary():
    """extend_contract overwrites annual_salary for the WHOLE deal, so a lower
    quote would retroactively cut guaranteed money."""
    p = FakePlayer(quality=40, age=23)  # cheap player, expensive existing deal
    current = 9_000_000
    for years in range(1, 9):
        value = extension_annual_value(
            p,
            covered_years=years,
            service_time_days=0,
            current_annual_salary=current,
        )
        assert value >= current, f"{years}-year quote dipped under the current deal"


def test_pre_arb_no_longer_auto_accepts_the_minimum():
    p = FakePlayer(quality=62, age=23)
    ev = evaluate_extension_offer(
        p,
        offered_years=6,
        offered_annual_salary=800_000,
        service_time_days=0,
        current_annual_salary=0,
        current_years_left=1,
    )
    assert ev.decision != "accepted"


# --- pricing properties -----------------------------------------------------


def test_better_player_costs_more():
    values = [
        extension_annual_value(
            FakePlayer(quality=q, age=24), covered_years=5, service_time_days=0
        )
        for q in (35, 45, 55, 65, 75)
    ]
    assert values == sorted(values)
    assert values[-1] > values[0]


def test_longer_extension_costs_more_per_year_for_a_young_player():
    """Each added year buys a season closer to free agency, so the annualized
    price rises. A dip here means seasons are being mis-tiered."""
    p = FakePlayer(quality=60, age=23)
    values = [
        extension_annual_value(p, covered_years=n, service_time_days=0)
        for n in range(2, 9)
    ]
    assert values == sorted(values), values


def test_no_service_history_stages_by_age_for_every_covered_season():
    """Regression: fabricating 172/344/516 service days for a player with none
    flipped later seasons out of the age path and back to 'rookie', which made a
    veteran's four-year deal cheaper per year than his two-year deal."""
    vet = FakePlayer(quality=60, age=31)
    market = estimate_market_value_for_player(vet)
    # Every covered season is a free-agent season, so each is full market.
    for years in (1, 2, 4, 6):
        assert extension_annual_value(vet, covered_years=years, service_time_days=0) == (
            market
        )


def test_security_discount_only_applies_to_bought_out_control():
    """A pure free-agent extension is market price; buying out control is cheaper
    per year than the same seasons bought one at a time."""
    vet = FakePlayer(quality=60, age=31)
    assert extension_annual_value(vet, covered_years=4, service_time_days=0) == (
        estimate_market_value_for_player(vet)
    )

    young = FakePlayer(quality=60, age=23)
    market = estimate_market_value_for_player(young)
    assert extension_annual_value(young, covered_years=6, service_time_days=0) < market


def test_service_time_clock_advances_when_it_is_known():
    """A player with real service history is staged off that, not his age."""
    p = FakePlayer(quality=60, age=26)
    nearly_fa = cn.FA_SERVICE_DAYS - 172  # one season short of free agency
    short = extension_annual_value(p, covered_years=1, service_time_days=nearly_fa)
    long = extension_annual_value(p, covered_years=4, service_time_days=nearly_fa)
    assert long > short


# --- deal length ------------------------------------------------------------


def test_young_players_want_long_deals():
    """They used to anchor on one year, which is backwards: selling arbitration
    and free-agent seasons for security is the whole point of an extension."""
    assert fair_market_years(FakePlayer(quality=62, age=23), service_time_days=0) >= 5


def test_older_players_want_short_deals():
    assert fair_market_years(FakePlayer(quality=62, age=37), service_time_days=2000) == 1
    assert fair_market_years(FakePlayer(quality=62, age=34), service_time_days=2000) == 2


def test_length_thresholds_are_on_the_quality_scale():
    """The old 70/75/80 cuts were on a scale this function never received, so
    they never fired and every age bracket collapsed to one length."""
    star = fair_market_years(FakePlayer(quality=65, age=24), service_time_days=0)
    fringe = fair_market_years(FakePlayer(quality=40, age=24), service_time_days=0)
    assert star > fringe


# --- the same rules for CPU and human owners --------------------------------


def test_evaluation_does_not_depend_on_who_is_asking():
    """There is one negotiator; CPU and human offers run the identical path."""
    p = FakePlayer(quality=58, age=26)
    kwargs = dict(
        offered_years=3,
        offered_annual_salary=5_000_000,
        service_time_days=400,
        current_annual_salary=2_000_000,
        current_years_left=1,
    )
    first = evaluate_extension_offer(p, **kwargs)
    second = evaluate_extension_offer(p, **kwargs)
    assert first.to_dict() == second.to_dict()


@pytest.mark.parametrize("is_pitcher", [False, True])
def test_pitchers_and_hitters_both_price(is_pitcher):
    p = FakePlayer(quality=60, age=25, is_pitcher=is_pitcher)
    value = extension_annual_value(p, covered_years=4, service_time_days=0)
    assert value > 800_000
