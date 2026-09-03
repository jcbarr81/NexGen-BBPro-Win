"""Utilities for handling contract decisions during the offseason.

The functions in this module provide abstractions for common contract
related tasks in simulations:

* :func:`find_expiring_contracts` identifies which players need new deals.
* :func:`evaluate_free_agent_bids` picks the winning team for an unsigned
  player based on competing salary offers.
* :func:`fair_market_salary` projects what a player would expect to earn
  on the open market, factoring in talent, age, and service time.
* :func:`evaluate_extension_offer` decides whether a player accepts,
  counters, or rejects an extension offer from their current team.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Iterable, List, Mapping, Optional

from models.player import Player

try:
    from playbalance.aging import calculate_age
except Exception:  # pragma: no cover - aging is sim-only
    def calculate_age(_birthdate: str) -> Optional[int]:
        return None


def find_expiring_contracts(
    players: Iterable[Player], current_year: int
) -> List[Player]:
    """Return players whose contracts expire in *current_year*.

    A player is considered to have an expiring contract if they have an
    attribute ``contract_expiration`` equal to ``current_year``.  Players
    lacking the attribute are ignored.
    """

    return [
        player
        for player in players
        if getattr(player, "contract_expiration", -1) == current_year
    ]


def evaluate_free_agent_bids(
    player: Player, bids: Mapping[object, float]
) -> object:
    """Select the winning bid for a free agent.

    Parameters
    ----------
    player:
        The free agent being bid on.
    bids:
        Mapping of team-like keys to salary offers. Keys can be
        :class:`~models.team.Team` objects or team-id strings.

    Returns
    -------
    object
        The key that wins the bidding. The player's ``team_id`` attribute
        is updated to reflect the winning team id.
    """

    if not bids:
        raise ValueError("No bids submitted")

    max_offer = max(bids.values())
    top_teams = [team for team, offer in bids.items() if offer == max_offer]
    winner = random.choice(top_teams)

    winner_team_id = str(getattr(winner, "team_id", winner) or "").strip()
    player.team_id = winner_team_id
    player.salary = max_offer
    return winner


# ---------------------------------------------------------------------------
# Extension negotiation
#
# Models a player's response to an extension offer from their current team.
# The owner picks years + annual salary; this module decides whether the
# player accepts, counters, or rejects, based on:
#
#   - Talent (their projected fair-market value)
#   - Age + remaining career window (older players want shorter deals)
#   - Service time (pre-arb players accept low salaries; FA-pending
#     players demand market value)
#   - Length vs salary tradeoff (a star may take a discount for security)
#
# These rules are deliberately simple — readable, tunable, and good enough
# to make the negotiation feel real without modeling agent psychology.

# Service-time tiers (in days; MLB uses 172 days = 1 year of service).
# A service YEAR is 172 days, matching contracts_service, qualifying_offers and
# fa_negotiations. This module used to say 162 (a schedule length, not a service
# year), which mattered once salaries started coming from the shared model: a
# player this module called a free agent at 6*162=972 days is still short of the
# model's 6*172=1032, so he would have been priced as an arbitration case at 70%
# of market every time free agency asked what he was worth.
PRE_ARB_SERVICE_DAYS = 3 * 172  # under 3 years: pre-arbitration
FA_SERVICE_DAYS = 6 * 172  # 6+ years: free agency-pending

# Extension-eligibility guidelines.
MAX_YEARS_LEFT_FOR_EXTENSION = 2  # arbs/FAs only renegotiate in last 2 years
REJECTION_COOLDOWN_DAYS = 30  # cool-off after a rejected offer
# The extension deadline is the END of the playoffs (#9): owners can re-sign
# walk-year players right through the postseason, and only lose them at the
# offseason rollover. So the playoffs are NOT blocked — only the amateur draft
# (a mid-season interruption) pauses extension talks.
PHASES_BLOCKED_FOR_EXTENSION = {"AMATEUR_DRAFT"}


@dataclass(frozen=True)
class ExtensionEligibility:
    """Whether a player can currently entertain an extension offer."""

    eligible: bool
    reason: str = ""
    code: str = ""  # short machine code for the UI to switch on
    cooldown_days_remaining: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_iso_date(value: object) -> Optional["date"]:
    from datetime import date as _date

    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return _date.fromisoformat(s[:10])
    except Exception:
        return None


def check_extension_eligibility(
    *,
    service_time_days: int,
    current_years_left: int,
    current_phase: Optional[str] = None,
    last_rejected_iso: Optional[str] = None,
    sim_date_iso: Optional[str] = None,
) -> ExtensionEligibility:
    """Apply the four house rules for when a player will negotiate.

    1. Phase gating: AMATEUR_DRAFT + PLAYOFFS are no-go. The owner is
       supposed to be focused on the bracket / pick selection.
    2. FA-year lockout: ``years_left <= 0`` means the contract is up;
       wait for free agency.
    3. Years-remaining cap: arb / FA-tier players who still have more
       than ``MAX_YEARS_LEFT_FOR_EXTENSION`` years on their deal won't
       renegotiate (otherwise owners would compound extensions every
       year). Pre-arb players are exempt — team-friendly early
       extensions are realistic at any service-time level.
    4. Rejection cooldown: ``REJECTION_COOLDOWN_DAYS`` sim days have to
       pass after a rejected offer before the same player will hear a
       new pitch.
    """

    if current_phase and str(current_phase).upper() in PHASES_BLOCKED_FOR_EXTENSION:
        return ExtensionEligibility(
            eligible=False,
            code="phase_blocked",
            reason=(
                f"Extension talks pause during {current_phase.replace('_', ' ').title()}. "
                "Try again in the regular season or offseason."
            ),
        )

    if current_years_left <= 0:
        return ExtensionEligibility(
            eligible=False,
            code="fa_year_lockout",
            reason=(
                "This contract has expired or is in its walk year — the "
                "player is heading to free agency. Re-sign them as a free "
                "agent instead."
            ),
        )

    tier = _service_tier(service_time_days)
    if tier != "pre_arb" and current_years_left > MAX_YEARS_LEFT_FOR_EXTENSION:
        return ExtensionEligibility(
            eligible=False,
            code="too_many_years_left",
            reason=(
                f"Player still has {current_years_left} years on the current "
                f"deal. Extensions only happen in the last "
                f"{MAX_YEARS_LEFT_FOR_EXTENSION} years for arbitration / "
                "free-agent-tier players."
            ),
        )

    if last_rejected_iso:
        from datetime import date as _date

        last = _parse_iso_date(last_rejected_iso)
        today = _parse_iso_date(sim_date_iso) or _date.today()
        if last is not None:
            days_since = (today - last).days
            if days_since < REJECTION_COOLDOWN_DAYS:
                remaining = REJECTION_COOLDOWN_DAYS - days_since
                return ExtensionEligibility(
                    eligible=False,
                    code="cooldown",
                    reason=(
                        f"Player turned down an offer "
                        f"{days_since} day(s) ago — give them "
                        f"{remaining} more day(s) before approaching again."
                    ),
                    cooldown_days_remaining=remaining,
                )

    return ExtensionEligibility(eligible=True)


@dataclass(frozen=True)
class ExtensionEvaluation:
    """Player's response to an extension offer."""

    decision: str  # "accepted" | "countered" | "rejected"
    fair_market_salary: int
    fair_market_years: int
    counter_salary: Optional[int]
    counter_years: Optional[int]
    reason: str
    service_tier: str  # "pre_arb" | "arbitration" | "free_agent"

    def to_dict(self) -> dict:
        return asdict(self)


def _talent_score(player: object) -> float:
    """Star-weighted quality on the rating scale (~20..80).

    This is the SAME score the salary model prices off
    (:func:`services.contracts_service._player_quality_score`), so a player's
    asking price and the length of deal they want can never disagree about how
    good he is.

    It used to read ``overall_display`` / ``overall_raw`` and claim it matched
    what the profile page shows. Those attributes are computed in the
    presentation layer and never set on ``Player``, so it always fell through
    to a six-rating average on a different scale from the displayed overall —
    three different numbers for the same player, and the one nobody could see
    was the one that set his price.
    """

    from services.contracts_service import _player_quality_score

    try:
        quality = _player_quality_score(player)
    except Exception:  # pragma: no cover - defensive
        quality = None
    if quality is None:
        return 50.0
    return max(0.0, min(100.0, float(quality)))


def _age_of(player: object) -> Optional[int]:
    birthdate = getattr(player, "birthdate", None)
    if not birthdate:
        return None
    try:
        return calculate_age(str(birthdate))
    except Exception:  # pragma: no cover - defensive
        return None


def _service_tier(service_time_days: int) -> str:
    if service_time_days < PRE_ARB_SERVICE_DAYS:
        return "pre_arb"
    if service_time_days < FA_SERVICE_DAYS:
        return "arbitration"
    return "free_agent"


# A player signing away cost-controlled years trades upside for guaranteed
# money, so an extension is cheaper per year than buying those seasons one at a
# time. The discount scales with how much team control he's giving up: a pure
# free-agent extension is priced at market (no discount at all).
EXTENSION_MAX_SECURITY_DISCOUNT = 0.20

# Deal-length cutoffs on the star-weighted quality scale (~20..80). Live leagues
# run roughly 37..63 with a mean near 51, so "good" and "star" sit where the top
# quarter and the top handful of players actually are.
QUALITY_GOOD = 55.0
QUALITY_STAR = 60.0


# What a player whose ratings can't be read is assumed to be worth. The salary
# model floors an unratable player at the league minimum, which is right for
# seeding a contract but wrong at a negotiating table: it would let anyone sign
# a player for the minimum whenever his ratings failed to load. Value him at a
# non-committal middle instead, which is what this module always did.
UNRATED_MARKET_VALUE = 1_500_000


def _market_value(player: object) -> int:
    """Open-market annual value, with a safe default for an unratable player."""

    from services.contracts_service import (
        _player_quality_score,
        estimate_market_value_for_player,
    )

    try:
        if _player_quality_score(player) is None:
            return UNRATED_MARKET_VALUE
        return int(estimate_market_value_for_player(player))
    except Exception:  # pragma: no cover - defensive
        return UNRATED_MARKET_VALUE


def _season_value(
    market_value: int, *, service_time_days: int, age: Optional[int]
) -> int:
    """What one season costs at the tier the player is in for that season."""

    from services.contracts_service import (
        _apply_service_time_tier,
        _career_stage,
    )

    stage, arb_year = _career_stage(service_time_days=service_time_days, age=age)
    return int(_apply_service_time_tier(market_value, stage, arb_year))


def extension_annual_value(
    player: object,
    *,
    covered_years: int,
    service_time_days: int = 0,
    current_annual_salary: int = 0,
) -> int:
    """The annual salary an extension covering *covered_years* seasons is worth.

    Priced per season and then annualized, because an extension buys seasons the
    player has not reached yet: a 23-year-old signing six years sells two pre-arb
    seasons, three arbitration seasons, and a free-agent season, and the last of
    those is worth many times the first. Pricing every year at his CURRENT tier
    — which is what both older models did — quotes six years of pre-arb minimum
    for a player who will be a free agent partway through the deal.

    Two floors apply. League minimum, obviously; and his existing salary, because
    ``extend_contract`` overwrites ``annual_salary`` for the whole contract, so a
    quote below the current figure would retroactively cut money he has already
    been guaranteed.
    """

    covered_years = max(1, int(covered_years))
    market_value = _market_value(player)
    age = _age_of(player)
    service = max(0, int(service_time_days or 0))

    # Advance whichever clock the player actually has. _career_stage falls back
    # to age only when service time is zero, so handing it a fabricated
    # 172/344/516 for a player with no service history flips him out of the
    # age path and back to "rookie" — which priced a 30-year-old free agent's
    # second extension year at the pre-arb minimum and made a four-year deal
    # cheaper per year than a two-year one.
    has_service = service > 0

    season_values: List[int] = []
    controlled = 0
    for offset in range(covered_years):
        season_service = service + (172 * offset) if has_service else 0
        season_age = None if age is None else age + offset
        value = _season_value(
            market_value, service_time_days=season_service, age=season_age
        )
        season_values.append(value)
        if value < market_value:
            controlled += 1

    annual = sum(season_values) / len(season_values)

    # Security discount, proportional to the share of the deal that is bought-out
    # team control. All-FA years => no discount.
    discount = EXTENSION_MAX_SECURITY_DISCOUNT * (controlled / covered_years)
    annual *= 1.0 - discount

    floor = max(800_000, int(current_annual_salary or 0))
    return int(max(floor, round(annual)))


def fair_market_salary(
    player: object,
    *,
    service_time_days: int = 0,
) -> int:
    """Estimate the annual salary *player* commands for a SINGLE season.

    Delegates to the league's one salary model
    (:func:`services.contracts_service.estimate_contract_salary`): a convex
    quality->market curve, discounted by career stage (pre-arb / arbitration
    year 1-3 / free agent). This module used to carry a second, coarser ladder
    of its own, so what a player was worth depended on which code path asked.

    For multi-year extensions use :func:`extension_annual_value`, which prices
    each covered season at the tier the player will actually be in that year.
    """

    age = _age_of(player)
    salary = _season_value(
        _market_value(player),
        service_time_days=max(0, int(service_time_days or 0)),
        age=age,
    )

    # Aging discount: players over 33 expect shorter, smaller deals.
    if age is not None and age >= 33:
        salary = int(salary * (1.0 - min(0.4, (age - 33) * 0.05)))

    return max(800_000, int(salary))


def fair_market_years(player: object, *, service_time_days: int = 0) -> int:
    """How many years a player would expect, balancing security vs. age.

    Thresholds are on the star-weighted quality scale (~20..80, see
    :func:`_talent_score`), not a 0-100 display overall — the old 70/75/80 cuts
    were written for a scale this function never actually received, so in a real
    league they never fired and everyone wanted the same short deal.

    A pre-arb player no longer anchors on one year. Signing away arbitration and
    free-agent seasons for guaranteed money is precisely what a young player
    wants out of an extension; it's the team that pays for the privilege.
    """

    age = _age_of(player)
    quality = _talent_score(player)
    tier = _service_tier(service_time_days)

    if age is None:
        if tier == "pre_arb":
            return 5
        return 3 if tier == "arbitration" else 4

    if age >= 36:
        return 1
    if age >= 33:
        return 2
    if age >= 30:
        return 3 if quality >= QUALITY_GOOD else 2
    if age >= 27:
        return 5 if quality >= QUALITY_STAR else 4
    # Under 27: long deals if the talent is there.
    return 7 if quality >= QUALITY_STAR else 5


def evaluate_extension_offer(
    player: object,
    *,
    offered_years: int,
    offered_annual_salary: int,
    service_time_days: int = 0,
    current_annual_salary: int = 0,
    current_years_left: int = 0,
) -> ExtensionEvaluation:
    """Decide whether *player* accepts the offer.

    Decision tree:
      1. Price the extension across every season it covers (the player's current
         remaining years plus the years being added), since ``extend_contract``
         applies one salary to the whole deal.
      2. Salary check: offered/fair ratio.
         >= 0.95 → "accepted" (player likes the deal)
         0.80-0.95 → "countered" with fair_market salary at the offered length
         < 0.80 → "rejected" (lowball)
      3. Length sanity: if the player is 33+ and the deal is 5+ years,
         counter to the player's preferred length even if salary was fine.

    Pre-arbitration players used to short-circuit here and accept ANY offer at
    or above the league minimum — regardless of talent, of how many arbitration
    and free-agent seasons the extension bought out, and of what they were
    already earning. That let a team re-sign a good 23-year-old on $1.2M for
    $800k, cutting his guaranteed money while buying his best years. They now
    negotiate on the same terms as everyone else; being cheap to extend comes
    from the per-season tier pricing, not from a rule that says they cannot say
    no.
    """

    offered_years = max(1, int(offered_years))
    offered_annual_salary = max(800_000, int(offered_annual_salary))
    tier = _service_tier(service_time_days)

    # The new salary applies to the seasons still on the deal as well as the
    # ones being added, so price all of them.
    covered_years = max(1, int(current_years_left or 0) + offered_years)
    fair_salary = extension_annual_value(
        player,
        covered_years=covered_years,
        service_time_days=service_time_days,
        current_annual_salary=current_annual_salary,
    )
    fair_years = fair_market_years(player, service_time_days=service_time_days)

    salary_ratio = offered_annual_salary / max(1, fair_salary)
    age = _age_of(player)

    # Length sanity check for older players.
    length_too_long = (
        age is not None and age >= 33 and offered_years > fair_years + 1
    )

    if salary_ratio >= 0.95 and not length_too_long:
        return ExtensionEvaluation(
            decision="accepted",
            fair_market_salary=fair_salary,
            fair_market_years=fair_years,
            counter_salary=None,
            counter_years=None,
            reason=(
                f"Offer at ${offered_annual_salary:,}/yr × {offered_years} "
                f"is in line with market value (~${fair_salary:,})."
            ),
            service_tier=tier,
        )

    if salary_ratio < 0.80:
        return ExtensionEvaluation(
            decision="rejected",
            fair_market_salary=fair_salary,
            fair_market_years=fair_years,
            counter_salary=fair_salary,
            counter_years=fair_years,
            reason=(
                f"Offer at ${offered_annual_salary:,}/yr is well below the "
                f"player's market value (~${fair_salary:,}/yr). Rebuild from "
                f"~${fair_salary:,} × {fair_years}."
            ),
            service_tier=tier,
        )

    # Counter-offer: meet at fair-market salary, prefer player's preferred length.
    counter_years = fair_years if length_too_long else offered_years
    return ExtensionEvaluation(
        decision="countered",
        fair_market_salary=fair_salary,
        fair_market_years=fair_years,
        counter_salary=fair_salary,
        counter_years=counter_years,
        reason=(
            f"Player would accept ${fair_salary:,}/yr × {counter_years} — "
            f"the offer is close but undervalues their market"
            + (" and the term is too long for their age" if length_too_long else "")
            + "."
        ),
        service_tier=tier,
    )
