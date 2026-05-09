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
PRE_ARB_SERVICE_DAYS = 3 * 162  # under 3 years: pre-arbitration
FA_SERVICE_DAYS = 6 * 162  # 6+ years: free agency-pending

# Extension-eligibility guidelines.
MAX_YEARS_LEFT_FOR_EXTENSION = 2  # arbs/FAs only renegotiate in last 2 years
REJECTION_COOLDOWN_DAYS = 30  # cool-off after a rejected offer
PHASES_BLOCKED_FOR_EXTENSION = {"AMATEUR_DRAFT", "PLAYOFFS"}


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
    """Crude 0-100 talent measure. Reuses display ratings for consistency
    with what the user sees on the player profile."""

    overall = getattr(player, "overall_display", None)
    if overall is None:
        overall = getattr(player, "overall_raw", None)
    if overall is None:
        # Fall back to averaged primary ratings.
        is_pitcher = bool(getattr(player, "is_pitcher", False))
        keys = (
            ("arm", "control", "movement", "endurance")
            if is_pitcher
            else ("ch", "ph", "sp", "eye", "fa", "arm")
        )
        values = []
        for key in keys:
            raw = getattr(player, key, None)
            if raw is None:
                continue
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                continue
        if not values:
            return 50.0
        overall = sum(values) / len(values)
    try:
        return max(0.0, min(100.0, float(overall)))
    except (TypeError, ValueError):
        return 50.0


def _service_tier(service_time_days: int) -> str:
    if service_time_days < PRE_ARB_SERVICE_DAYS:
        return "pre_arb"
    if service_time_days < FA_SERVICE_DAYS:
        return "arbitration"
    return "free_agent"


def fair_market_salary(
    player: object,
    *,
    service_time_days: int = 0,
) -> int:
    """Estimate the open-market annual salary for *player*.

    Curve (rough; tunable):
      <50 OVR : league min (~$800k)
      50-59  : $1.5M
      60-69  : $4M
      70-79  : $10M
      80-89  : $20M
      90+    : $32M

    Pre-arb tier multiplies by 0.15, arbitration by 0.55, FA by 1.0.
    Aging discount applied for players 33+.
    """

    talent = _talent_score(player)
    if talent >= 90:
        base = 32_000_000
    elif talent >= 80:
        base = 20_000_000
    elif talent >= 70:
        base = 10_000_000
    elif talent >= 60:
        base = 4_000_000
    elif talent >= 50:
        base = 1_500_000
    else:
        base = 800_000

    tier = _service_tier(service_time_days)
    if tier == "pre_arb":
        base = max(800_000, int(base * 0.15))
    elif tier == "arbitration":
        base = int(base * 0.55)
    # else free agent — full market

    # Aging discount: players over 33 expect shorter, smaller deals.
    age = None
    birthdate = getattr(player, "birthdate", None)
    if birthdate:
        age = calculate_age(str(birthdate))
    if age is not None and age >= 33:
        base = int(base * (1.0 - min(0.4, (age - 33) * 0.05)))

    return max(800_000, base)


def fair_market_years(player: object, *, service_time_days: int = 0) -> int:
    """How many years a player would expect, balancing security vs. age."""

    age = None
    birthdate = getattr(player, "birthdate", None)
    if birthdate:
        age = calculate_age(str(birthdate))
    talent = _talent_score(player)
    tier = _service_tier(service_time_days)

    # Pre-arb players don't really negotiate — they take what's offered
    # but anchor expectations on a 1-year deal.
    if tier == "pre_arb":
        return 1
    if age is None:
        # Fallback: arb tier wants ~3 years, FA wants ~4.
        return 3 if tier == "arbitration" else 4

    if age >= 36:
        return 1
    if age >= 33:
        return 2
    if age >= 30:
        return 3 if talent >= 70 else 2
    if age >= 27:
        return 5 if talent >= 75 else 4
    # Under 27: long deals if the talent is there.
    return 7 if talent >= 80 else 5


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
      1. Compute fair-market salary + length.
      2. Salary check: offered/fair ratio.
         >= 0.95 → "accepted" (player likes the deal)
         0.80-0.95 → "countered" with fair_market salary at the offered length
         < 0.80 → "rejected" (lowball)
      3. Length sanity: if the player is 33+ and the deal is 5+ years,
         counter to the player's preferred length even if salary was fine.
      4. Pre-arb players accept anything at or above league min.
    """

    offered_years = max(1, int(offered_years))
    offered_annual_salary = max(800_000, int(offered_annual_salary))
    fair_salary = fair_market_salary(player, service_time_days=service_time_days)
    fair_years = fair_market_years(player, service_time_days=service_time_days)
    tier = _service_tier(service_time_days)

    # Pre-arb players are easy.
    if tier == "pre_arb":
        if offered_annual_salary >= 800_000:
            return ExtensionEvaluation(
                decision="accepted",
                fair_market_salary=fair_salary,
                fair_market_years=fair_years,
                counter_salary=None,
                counter_years=None,
                reason="Pre-arbitration player accepts at or above league minimum.",
                service_tier=tier,
            )
        return ExtensionEvaluation(
            decision="rejected",
            fair_market_salary=fair_salary,
            fair_market_years=fair_years,
            counter_salary=800_000,
            counter_years=offered_years,
            reason="Cannot offer below the league minimum.",
            service_tier=tier,
        )

    salary_ratio = offered_annual_salary / max(1, fair_salary)
    age = None
    birthdate = getattr(player, "birthdate", None)
    if birthdate:
        age = calculate_age(str(birthdate))

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
