"""CPU clubs extend the players they want to keep (8.5.0).

Before this a CPU club never extended anyone: every contract ran out and the
player went to free agency. Owner's call (2026-10-25): the CPU decides for
itself whom to re-sign, with logic, and has a ceiling it will pay.

Twice a month in the season (the first played date on or after the 1st and
the 16th; idempotent, ``cpu_extensions_state.json``) each CPU club looks at
its players who may be extended (``contract_negotiator.
check_extension_eligibility``) and are in the walk year
(every expiring contract goes to free agency at the rollover), best first:

* **Whom it wants.** His quality on the salary model's scale
  (``contract_negotiator._talent_score``, ~20-80, mean ~51), less 1.5 a year
  past 30, plus one for 26 and under and two when nobody else in the
  organisation at his position is within three points of him. A contender
  keeps anyone scoring 53 or more, a balanced club 55, a rebuilding club 57
  and, unless he is a star, only players under 30.
* **What it will pay** (its ceiling). The fair price for the years
  (``extension_talks.fair_price``) times the top of the club's free-agent
  salary band for its strategy and budget tone
  (``finance_ai.estimate_free_agent_salary_band``; +6% for a contender's
  star), cut to what keeps the club under its payroll target
  (``finance_ai._team_payroll_cap_target``). A ceiling below what the
  easiest player would take is not worth opening talks over.
* **How it negotiates.** Under the players' own rules
  (``services.extension_talks``): it opens at 90% of the fair price (never
  below his current salary), meets each counter halfway up to its ceiling,
  and stops -- at most five offers -- when he signs, refuses, breaks off,
  or is about to walk away (a CPU club does not burn its own player's
  patience to the end).

An extension is logged as a transaction and a news item. Owners' clubs are
never touched; with team ownership unreadable the pass stands down.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

_LOGGER = logging.getLogger(__name__)

STATE_FILE = "cpu_extensions_state.json"
KEEP_THRESHOLD = {"contend": 53.0, "balanced": 55.0, "rebuild": 57.0}
OPENING_SHARE = 0.90
MAX_OFFERS = 5
RUN_PHASES = {"REGULAR_SEASON", "PLAYOFFS"}


def _money(value: float) -> int:
    return int(round(value / 50_000.0) * 50_000)


def _window(date: str) -> str:
    """"2027-05a" for the 1st-15th, "2027-05b" for the 16th on."""

    return f"{date[:7]}{'a' if int(date[8:10]) < 16 else 'b'}"


def _load_state(base: Path) -> Dict[str, Any]:
    try:
        data = json.loads((base / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(base: Path, state: Mapping[str, Any]) -> None:
    from utils.atomic_write import atomic_text_writer

    with atomic_text_writer(base / STATE_FILE, encoding="utf-8") as fh:
        fh.write(json.dumps(state, indent=2, sort_keys=True))


def _org(base: Path, team_id: str) -> List[str]:
    from services.departure_cleanup import org_player_ids

    return sorted(org_player_ids(base / "rosters" / f"{team_id}.csv"))


def _position_group(player: object) -> str:
    from utils.roster_rules import counts_as_pitcher

    if counts_as_pitcher(player):
        return "P"
    return str(getattr(player, "primary_position", "") or "").strip().upper()


def keep_value(player: object, *, others: List[object]) -> float:
    """How much a club wants to keep ``player`` (``others``: the rest of its
    organisation)."""

    from services.contract_negotiator import _age_of, _talent_score

    quality = _talent_score(player)
    age = _age_of(player)
    value = quality
    if age is not None and age > 30:
        value -= 1.5 * (age - 30)
    if age is not None and age <= 26:
        value += 1.0
    group = _position_group(player)
    rivals = [o for o in others if _position_group(o) == group
              and _talent_score(o) >= quality - 3]
    # A staff has many arms: only short of comparable ones is a need.
    if (group == "P" and len(rivals) < 4) or (group != "P" and not rivals):
        value += 2.0
    return value


def wants_to_keep(player: object, *, profile: str, others: List[object]) -> bool:
    from services.contract_negotiator import QUALITY_STAR, _age_of, _talent_score

    profile = profile if profile in KEEP_THRESHOLD else "balanced"
    if profile == "rebuild":
        age = _age_of(player)
        if age is not None and age >= 30 and _talent_score(player) < QUALITY_STAR:
            return False
    return keep_value(player, others=others) >= KEEP_THRESHOLD[profile]


def offer_years(player: object, *, profile: str, service_time_days: int) -> int:
    from services.contract_negotiator import _age_of, fair_market_years

    years = fair_market_years(player, service_time_days=service_time_days)
    age = _age_of(player)
    if profile == "rebuild" and age is not None and age >= 28:
        years = min(years, 2)
    return max(1, min(6, years))


def ceiling(fair: int, *, strategy: object, ai_level: str, quality: float,
            current_salary: int, payroll_room: Optional[int]) -> int:
    """The most a club will pay a year: its free-agent band's top, held
    under its payroll target (``payroll_room``: how far below it is)."""

    from services.contract_negotiator import QUALITY_STAR
    from services.finance_ai import PROFILE_CONTEND, estimate_free_agent_salary_band

    _low, high = estimate_free_agent_salary_band(strategy, ai_level=ai_level)
    if getattr(strategy, "profile", "") == PROFILE_CONTEND and quality >= QUALITY_STAR:
        high += 0.06
    top = int(fair * high)
    if payroll_room is not None:
        top = min(top, current_salary + max(0, payroll_room))
    return top


def run_cpu_extension_pass(played_date: str, *, phase: Optional[str],
                           data_dir: Path | str | None = None,
                           force: bool = False) -> Dict[str, Any]:
    """Run the twice-monthly CPU extension pass. Never raises."""

    try:
        return _run(played_date, phase=phase, data_dir=data_dir, force=force)
    except Exception as exc:  # pragma: no cover - defensive
        _LOGGER.exception("cpu extensions: pass failed")
        return {"applied": False, "reason": "error", "error": str(exc)}


def _run(played_date: str, *, phase: Optional[str], data_dir: Path | str | None,
         force: bool) -> Dict[str, Any]:
    from services.contract_negotiator import _talent_score, check_extension_eligibility
    from services.contracts_service import extend_contract, load_contracts_payload
    from services.extension_talks import fair_price, respond_to_offer
    from services.finance_ai import (
        AI_LEVEL_ADVANCED,
        AI_LEVEL_BASIC,
        _merge_tuning,
        _team_payroll_cap_target,
        load_team_finance_strategies,
    )
    from services.finance_settings import load_financial_settings
    from services.team_ownership import human_owned_team_ids_strict
    from utils.path_utils import get_data_dir
    from utils.player_loader import load_players_from_csv

    base = Path(get_data_dir() if data_dir is None else data_dir)
    date = str(played_date or "")[:10]
    if str(phase or "").upper() not in RUN_PHASES or len(date) < 10:
        return {"applied": False, "reason": "phase"}
    window = _window(date)
    state = _load_state(base)
    if not force and state.get("last_window") == window:
        return {"applied": False, "reason": "already_ran", "window": window}

    settings = load_financial_settings(path=base / "league_financial_settings.json")
    ai_level = settings.module_level("gm_finance_ai")
    if not settings.enabled or ai_level not in {AI_LEVEL_BASIC, AI_LEVEL_ADVANCED}:
        return {"applied": False, "reason": "finance_ai_off"}
    owners = human_owned_team_ids_strict(base)
    if owners is None:
        return {"applied": False, "reason": "ownership_unknown"}

    contracts = load_contracts_payload(data_dir=base).get("players") or {}
    players = {str(p.player_id): p for p in load_players_from_csv(str(base / "players.csv"))}
    strategies = load_team_finance_strategies(data_dir=base)
    tuning = _merge_tuning(settings.finance_ai_tuning)

    by_club: Dict[str, List[str]] = {}
    for pid, raw in contracts.items():
        if not isinstance(raw, Mapping):
            continue
        club = str(raw.get("team_id") or "").strip()
        if club and club.upper() not in owners:
            by_club.setdefault(club, []).append(str(pid))

    extended: List[Dict[str, Any]] = []
    talks = 0
    for club in sorted(by_club):
        strategy = strategies.get(club)
        profile = str(getattr(strategy, "profile", "balanced") or "balanced")
        org = _org(base, club)
        org_players = [players[p] for p in org if p in players]
        payroll = int(getattr(strategy, "annual_payroll", 0) or 0)
        target = _team_payroll_cap_target(strategy, tuning=tuning) if strategy else None
        candidates = []
        for pid in by_club[club]:
            raw = contracts[pid]
            player = players.get(pid)
            if player is None or pid not in org:
                continue
            service = int(raw.get("service_time_days", 0) or 0)
            years_left = int(raw.get("years_left", 0) or 0)
            # Only the walk year: anyone with a year to spare can wait.
            if years_left != 1 or not check_extension_eligibility(
                service_time_days=service, current_years_left=years_left,
                current_phase=phase,
            ).eligible:
                continue
            others = [o for o in org_players if str(o.player_id) != pid]
            if not wants_to_keep(player, profile=profile, others=others):
                continue
            candidates.append((_talent_score(player), pid, player, raw))
        for quality, pid, player, raw in sorted(candidates, key=lambda c: (-c[0], c[1])):
            service = int(raw.get("service_time_days", 0) or 0)
            current = int(raw.get("annual_salary", 0) or 0)
            years_left = int(raw.get("years_left", 0) or 0)
            years = offer_years(player, profile=profile, service_time_days=service)
            fair = fair_price(player, years=years, service_time_days=service,
                              current_annual_salary=current, current_years_left=years_left)
            room = None if target is None else target - payroll
            top = ceiling(fair, strategy=strategy, ai_level=ai_level, quality=quality,
                          current_salary=current, payroll_room=room)
            if top < fair * 0.92:  # under what even an easy player takes
                continue
            talks += 1
            offer = max(current, _money(fair * OPENING_SHARE))
            signed = None
            for _ in range(MAX_OFFERS):
                offer = min(offer, top)
                answer = respond_to_offer(
                    player, pid, team_id=club, years=years, salary=offer,
                    service_time_days=service, current_annual_salary=current,
                    current_years_left=years_left, phase=phase, data_dir=base,
                    notify_owner=False,
                )
                if answer.decision == "accepted":
                    signed = offer
                    break
                if answer.decision != "countered" or offer >= top:
                    break
                if answer.mood == "about to walk away":
                    break
                if answer.counter_years:
                    years = answer.counter_years
                offer = _money((offer + answer.ask_salary) / 2)
            if signed is None:
                continue
            if extend_contract(pid, additional_years=years, annual_salary=signed,
                               data_dir=base) is None:
                continue
            payroll += max(0, signed - current)
            extended.append({"team_id": club, "player_id": pid, "years": years,
                             "annual_salary": signed})
            _announce(base, club, pid, player, years, signed)

    state["last_window"] = window
    _save_state(base, state)
    return {"applied": bool(extended), "window": window, "talks": talks,
            "extended": extended}


def _announce(base: Path, club: str, pid: str, player: object, years: int,
              salary: int) -> None:
    name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip() or pid
    money = f"${salary / 1_000_000:.1f}M"
    try:
        from services.transaction_log import record_transaction

        record_transaction(
            action="extension", team_id=club, player_id=pid, player_name=name,
            details=f"CPU extension: +{years} yr at {money}/yr",
            path=base / "transactions.csv",
        )
    except Exception:
        _LOGGER.exception("cpu extensions: could not log the transaction")
    try:
        from utils.news_logger import log_news_event

        log_news_event(
            f"{club} extended {name}: {years} more year{'s' if years != 1 else ''} "
            f"at {money} a year.",
            category="contract", team_id=club, file_path=base / "news_feed.txt",
        )
    except Exception:
        _LOGGER.exception("cpu extensions: could not post the news item")
