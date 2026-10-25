"""Contract-extension talks: haggling, patience, shutdowns and refusals (8.5.0).

Before this, a player's exact price was on screen (offering it was always
accepted) and an offer under 80% of it locked him out for a flat 30 sim
days. Owners asked for a negotiation instead (backlog, 2026-10-16). Here:

* **An asking price above what he'll take.** Each player has a fixed
  temperament (easy / normal / hard, from his id, so it never changes). His
  minimum is a share of the fair price for the years offered -- the
  free-agent market price, less a little for a long deal
  (:func:`fair_price`); his opening ask is above it. Any offer at or above the
  minimum is accepted -- he never says where that is, only his current ask.
* **Haggling costs patience.** An offer below his minimum gets a counter
  (his ask moves part of the way down to the minimum) and costs a point of
  patience; a lowball (under 80% of the minimum) costs two and does not move
  him. With no patience left he **shuts down talks** for 7-30 days (longer
  for a hard temperament and for lowballs); then talks reopen with his
  patience restored. The owner hears about it (news and a notification).
* **Walk-year veterans may refuse in-season talks.** Once per season, on the
  first approach in the regular season or playoffs, a player in the last
  year of his deal with six or more years of service (27 or older where the
  league tracks no service time) may decide to test free
  agency (more likely for stars and players in their prime). He declines
  everything -- except a **crazy offer**: anything at or above
  :data:`CRAZY_OFFER_RATIO` x his fair price is accepted, refusal or
  shutdown notwithstanding (owner's call, 2026-10-25).
* **The clock.** In the season a shutdown counts sim days. During the
  offseason free-agency window it counts window days, at 7 sim days to one
  window day (owner's call). A shutdown ends when the clock changes kind --
  the season gives way to the offseason or the other way round -- or the
  season changes.

The same rules answer CPU clubs' offers (``services.cpu_extensions``).
State lives in ``extension_talks.json`` keyed by player id, for the club
that held the talks; a different club, or a new season, starts fresh.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

_LOGGER = logging.getLogger(__name__)
# One offer at a time per process: two offers at once (a double click, two
# tabs, an owner's offer during the CPU pass) must not both read the same
# state and lose a patience point.
_LOCK = threading.RLock()

FILENAME = "extension_talks.json"
RULE_ID = "contract_talks"

TEMPERAMENTS = ("easy", "normal", "hard")
# Share of players with each temperament (cumulative cut points).
_TEMPERAMENT_CUTS = ((0.30, "easy"), (0.80, "normal"), (1.01, "hard"))
# Hidden minimum, opening ask and patience, as shares of the fair price.
MINIMUM_RATIO = {"easy": 0.92, "normal": 0.96, "hard": 1.00}
OPENING_RATIO = {"easy": 1.08, "normal": 1.15, "hard": 1.22}
PATIENCE = {"easy": 6, "normal": 4, "hard": 3}
SHUTDOWN_BASE_DAYS = {"easy": 7, "normal": 10, "hard": 14}
SHUTDOWN_MAX_DAYS = 30
# Each counter moves his ask about this share of the way down to his
# minimum (varied per player and offer, see :func:`_step`, so two asks in a
# row do not give his minimum away).
ASK_STEP = 0.40
ASK_STEP_SPREAD = 0.12
# His opening ask varies by up to this share either side of his
# temperament's figure, so the ask does not reveal the minimum either.
OPENING_SPREAD = 0.04
# An offer under this share of his minimum is a lowball.
LOWBALL_RATIO = 0.80
# An offer at or above this multiple of his fair price is always accepted.
CRAZY_OFFER_RATIO = 1.5
# Sim days per free-agency window day, for a shutdown in the window.
SIM_DAYS_PER_FA_DAY = 7

IN_SEASON_PHASES = {"REGULAR_SEASON", "PLAYOFFS"}
WALK_YEAR_SERVICE_DAYS = 6 * 172
# Stand-in for six years of service where none is tracked.
VETERAN_AGE = 27


@dataclass
class TalksResponse:
    """The player's answer to one offer."""

    decision: str  # accepted | countered | shutdown | refused | blocked
    reason: str
    ask_salary: int  # his current ask for the years offered
    preferred_years: int
    counter_years: Optional[int] = None
    mood: str = ""
    shutdown_days: Optional[int] = None  # length, in the clock's units
    shutdown_unit: str = ""  # "days" | "free-agency days"
    service_tier: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Fixed per-player traits


def _unit(*parts: object) -> float:
    """A stable number in [0, 1) from the parts (never ``hash()``, which
    changes between processes)."""

    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _opening_ratio(player_id: str, kind: str) -> float:
    spread = (2 * _unit(player_id, "opening") - 1) * OPENING_SPREAD
    return OPENING_RATIO[kind] + spread


def _step(player_id: str, offers: int) -> float:
    return ASK_STEP + (2 * _unit(player_id, offers, "step") - 1) * ASK_STEP_SPREAD


def temperament(player_id: str) -> str:
    u = _unit(player_id, "temperament")
    for cut, name in _TEMPERAMENT_CUTS:
        if u < cut:
            return name
    return "normal"


# ---------------------------------------------------------------------------
# State and the clock


def _data_dir(data_dir: Path | str | None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    from utils.path_utils import get_data_dir

    return Path(get_data_dir())


def _load(base: Path) -> Dict[str, Dict[str, Any]]:
    path = base / FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _save(base: Path, state: Dict[str, Dict[str, Any]]) -> None:
    from utils.atomic_write import atomic_text_writer

    with atomic_text_writer(base / FILENAME, encoding="utf-8") as fh:
        fh.write(json.dumps(state, indent=2, sort_keys=True))


def season_key(base: Path) -> str:
    try:
        from services.fa_window import current_season_key

        return current_season_key(data_dir=base) or ""
    except Exception:
        return ""


def talks_clock(base: Path) -> Tuple[str, str]:
    """``(kind, value)``: ``("window", "<day>")`` while the free-agency window is
    open, ``("sim", "<date>")`` when the league has a sim date, else
    ``("none", "")``."""

    try:
        from services.fa_window import is_open, load_window

        if is_open(data_dir=base):
            state = load_window(data_dir=base) or {}
            return ("window", str(int(state.get("day") or 0)))
    except Exception:
        pass
    try:
        from utils.sim_date import get_current_sim_date

        date = get_current_sim_date()
    except Exception:
        date = None
    if date:
        return ("sim", str(date)[:10])
    return ("none", "")


def _clock_elapsed(start: Tuple[str, str], now: Tuple[str, str]) -> Optional[int]:
    """Units elapsed between two readings of the same kind, else None."""

    if start[0] != now[0]:
        return None
    if start[0] == "window":
        return int(now[1]) - int(start[1])
    if start[0] == "sim":
        from datetime import date

        try:
            return (date.fromisoformat(now[1]) - date.fromisoformat(start[1])).days
        except ValueError:
            return None
    return 0


def _shutdown_length(days: int, kind: str) -> int:
    if kind == "window":
        return max(1, math.ceil(days / SIM_DAYS_PER_FA_DAY))
    return days


def _shutdown_remaining(entry: Mapping, now: Tuple[str, str]) -> Optional[int]:
    """Units of shutdown left (>0), or None when talks are open."""

    shut = entry.get("shutdown")
    if not isinstance(shut, dict):
        return None
    start = (str(shut.get("kind") or ""), str(shut.get("start") or ""))
    elapsed = _clock_elapsed(start, now)
    if elapsed is None:  # the clock changed kind: the shutdown is over
        return None
    length = _shutdown_length(int(shut.get("days") or 0), start[0])
    left = length - elapsed
    if start[0] == "none":
        return length  # no clock to run: it waits for the next phase
    return left if left > 0 else None


def _entry(state: Dict[str, Dict[str, Any]], player_id: str, team_id: str,
           season: str) -> Dict[str, Any]:
    """The player's talks with this club this season (fresh if not)."""

    entry = state.get(player_id) or {}
    if entry.get("team_id") != team_id or entry.get("season") != season:
        kind = temperament(player_id)
        entry = {
            "team_id": team_id,
            "season": season,
            "ask_ratio": _opening_ratio(player_id, kind),
            "patience": PATIENCE[kind],
            "offers": 0,
            "lowballs": 0,
            "shutdown": None,
            "refuses": None,  # decided on the first in-season approach
        }
    return entry


# ---------------------------------------------------------------------------
# Pricing


# Up to this much off the market price for the security of a long deal
# (2.5% a year past the first).
SECURITY_DISCOUNT_PER_YEAR = 0.025
SECURITY_DISCOUNT_MAX = 0.10


def fair_price(player: object, *, years: int, service_time_days: int,
               current_annual_salary: int, current_years_left: int) -> int:
    """What an extension of ``years`` more seasons is worth a year.

    The free-agent market price (owner's call, 2026-10-25): every expiring
    contract goes to free agency at the rollover, and no league tracks
    service time (all contracts read 0 days), so pricing a young player's
    new seasons at pre-arbitration rates (``contract_negotiator.
    asking_salary``) quoted a walk-year 19-year-old worth $12.5M on the open
    market at $1.3M. Less up to 10% for a long deal's security, less the
    usual discount past 33 (5% a year, at most 40%); never below his current
    salary, which the extension replaces for the rest of his deal.
    """

    from services.contract_negotiator import _age_of, _market_value

    market = float(_market_value(player))
    age = _age_of(player)
    if age is not None and age >= 33:
        market *= 1.0 - min(0.4, (age - 33) * 0.05)
    discount = min(SECURITY_DISCOUNT_MAX,
                   SECURITY_DISCOUNT_PER_YEAR * (max(1, int(years)) - 1))
    return int(max(800_000, int(current_annual_salary or 0), round(market * (1 - discount))))


def _round_money(value: float) -> int:
    return int(round(value / 50_000.0) * 50_000)


def _refusal_chance(player: object, kind: str) -> float:
    from services.contract_negotiator import QUALITY_GOOD, QUALITY_STAR, _age_of, _talent_score

    chance = 0.25
    quality = _talent_score(player)
    if quality >= QUALITY_STAR:
        chance += 0.20
    elif quality >= QUALITY_GOOD:
        chance += 0.10
    age = _age_of(player)
    if age is not None and 27 <= age <= 31:
        chance += 0.10
    chance += {"easy": -0.10, "normal": 0.0, "hard": 0.10}[kind]
    return max(0.0, min(0.60, chance))


def _veteran(player: object, service_time_days: int) -> bool:
    """Six or more years of service; where the league tracks none (every
    contract reads 0 days), 27 or older -- six seasons for a player who
    arrived at 21."""

    if service_time_days > 0:
        return service_time_days >= WALK_YEAR_SERVICE_DAYS
    from services.contract_negotiator import _age_of

    age = _age_of(player)
    return age is not None and age >= VETERAN_AGE


def _refuses(player: object, player_id: str, entry: Dict[str, Any], *, phase: str,
             service_time_days: int, current_years_left: int, season: str) -> bool:
    """Decide (once per season, on the first in-season approach) whether a
    walk-year veteran will test free agency instead of negotiating."""

    if entry.get("refuses") is not None:
        return bool(entry["refuses"])
    if str(phase or "").upper() not in IN_SEASON_PHASES:
        return False
    if current_years_left != 1 or not _veteran(player, service_time_days):
        entry["refuses"] = False
        return False
    kind = temperament(player_id)
    entry["refuses"] = _unit(player_id, season, "refuse") < _refusal_chance(player, kind)
    return bool(entry["refuses"])


def _mood(entry: Mapping, player_id: str) -> str:
    full = PATIENCE[temperament(player_id)]
    share = float(entry.get("patience", full)) / max(1, full)
    if share >= 0.67:
        return "open"
    if share >= 0.34:
        return "impatient"
    return "about to walk away"


def _too_long(player: object, years: int, preferred: int) -> bool:
    from services.contract_negotiator import _age_of

    age = _age_of(player)
    return age is not None and age >= 33 and years > preferred + 1


def talks_status(player_id: str, team_id: str, *,
                 data_dir: Path | str | None = None) -> Dict[str, Any]:
    """``{status, left, unit}`` without pricing: "refuses" (won't negotiate
    in season), "shutdown" (``left`` units to go) or "open"."""

    base = _data_dir(data_dir)
    entry = _load(base).get(str(player_id)) or {}
    if entry.get("team_id") != team_id or entry.get("season") != season_key(base):
        return {"status": "open", "left": None, "unit": ""}
    if entry.get("refuses"):
        return {"status": "refuses", "left": None, "unit": ""}
    now = talks_clock(base)
    left = _shutdown_remaining(entry, now)
    if left is not None:
        unit = "free-agency days" if now[0] == "window" else "days"
        return {"status": "shutdown", "left": left, "unit": unit}
    return {"status": "open", "left": None, "unit": ""}


# ---------------------------------------------------------------------------
# Free agency (8.6.0): the same price, hidden minimum and temperament


FA_SERVICE_DAYS = 6 * 172


def fa_terms(player: object, player_id: str, *, years: int) -> Dict[str, Any]:
    """A free agent's terms for ``years``: ``{ask, minimum, preferred_years,
    too_long}``. His fair price is the free-agent market (:func:`fair_price`,
    no current salary); his ask and his hidden minimum use his temperament,
    as in extension talks. Only ``ask`` and ``preferred_years`` may be shown."""

    from services.contract_negotiator import fair_market_years

    kind = temperament(player_id)
    years = max(1, int(years))
    fair = fair_price(player, years=years, service_time_days=FA_SERVICE_DAYS,
                      current_annual_salary=0, current_years_left=0)
    preferred = fair_market_years(player, service_time_days=FA_SERVICE_DAYS)
    return {
        "ask": max(_round_money(fair * _opening_ratio(player_id, kind)), 800_000),
        "minimum": fair * MINIMUM_RATIO[kind],
        "preferred_years": preferred,
        "too_long": _too_long(player, years, preferred),
    }


def fa_accepts(player: object, player_id: str, *, years: int, salary: int) -> bool:
    """Would the free agent take ``salary`` a year for ``years``? At or above
    his hidden minimum, and not too long for his age."""

    terms = fa_terms(player, player_id, years=years)
    return int(salary) >= terms["minimum"] and not terms["too_long"]


# ---------------------------------------------------------------------------
# The two entry points


def talks_view(player: object, player_id: str, *, team_id: str, years: int,
               service_time_days: int, current_annual_salary: int,
               current_years_left: int, phase: Optional[str] = None,
               data_dir: Path | str | None = None) -> Dict[str, Any]:
    """What the owner may see before offering: his ask for ``years``, the
    length he wants, his mood, and whether talks are shut down or refused.
    A read: decides nothing (a refusal not yet rolled reads as open)."""

    from services.contract_negotiator import _service_tier, fair_market_years

    base = _data_dir(data_dir)
    season = season_key(base)
    entry = _entry(_load(base), player_id, team_id, season)
    fair = fair_price(player, years=years, service_time_days=service_time_days,
                      current_annual_salary=current_annual_salary,
                      current_years_left=current_years_left)
    now = talks_clock(base)
    left = _shutdown_remaining(entry, now)
    status = "open"
    if entry.get("refuses"):
        status = "refuses"
    elif left is not None:
        status = "shutdown"
    elif entry.get("shutdown"):
        # Over: his next offer restores his patience, so read it as full.
        entry = {**entry, "patience": PATIENCE[temperament(player_id)]}
    # No temperament here: with his ask it would give his minimum away.
    return {
        "ask_salary": max(_round_money(fair * float(entry["ask_ratio"])), 800_000),
        "preferred_years": fair_market_years(player, service_time_days=service_time_days),
        "mood": _mood(entry, player_id),
        "status": status,
        "shutdown_left": left,
        "shutdown_unit": "free-agency days" if now[0] == "window" else "days",
        "offers": int(entry.get("offers") or 0),
        "service_tier": _service_tier(service_time_days),
    }


def respond_to_offer(player: object, player_id: str, *, team_id: str, years: int,
                     salary: int, service_time_days: int, current_annual_salary: int,
                     current_years_left: int, phase: Optional[str] = None,
                     data_dir: Path | str | None = None, commit: bool = True,
                     notify_owner: bool = True) -> TalksResponse:
    """The player's answer to an offer of ``years`` more seasons at
    ``salary`` a year from ``team_id``. With ``commit`` the talks state is
    saved (an accepted offer clears it); the caller writes the contract."""

    with _LOCK:
        return _respond(player, player_id, team_id=team_id, years=years,
                        salary=salary, service_time_days=service_time_days,
                        current_annual_salary=current_annual_salary,
                        current_years_left=current_years_left, phase=phase,
                        data_dir=data_dir, commit=commit, notify_owner=notify_owner)


def _respond(player: object, player_id: str, *, team_id: str, years: int,
             salary: int, service_time_days: int, current_annual_salary: int,
             current_years_left: int, phase: Optional[str],
             data_dir: Path | str | None, commit: bool,
             notify_owner: bool) -> TalksResponse:
    from services.contract_negotiator import _service_tier, fair_market_years

    base = _data_dir(data_dir)
    season = season_key(base)
    state = _load(base)
    entry = _entry(state, player_id, team_id, season)
    kind = temperament(player_id)
    tier = _service_tier(service_time_days)
    years = max(1, int(years))
    salary = max(800_000, int(salary))
    fair = fair_price(player, years=years, service_time_days=service_time_days,
                      current_annual_salary=current_annual_salary,
                      current_years_left=current_years_left)
    preferred = fair_market_years(player, service_time_days=service_time_days)
    # Never below his current salary: the extension replaces it for the
    # rest of his deal too, so taking less would be a pay cut from today.
    minimum = max(fair * MINIMUM_RATIO[kind], float(current_annual_salary or 0))
    now = talks_clock(base)

    def ask() -> int:
        return max(_round_money(fair * float(entry["ask_ratio"])), 800_000)

    def done(response: TalksResponse) -> TalksResponse:
        response.mood = _mood(entry, player_id)
        response.service_tier = tier
        if commit:
            if response.decision == "accepted":
                state.pop(player_id, None)
            else:
                state[player_id] = entry
            _save(base, state)
        return response

    name = _player_name(player, player_id)

    # A crazy offer is taken whatever else is going on.
    if salary >= fair * CRAZY_OFFER_RATIO and not _too_long(player, years, preferred):
        return done(TalksResponse("accepted", f"{name} jumps at the offer.", ask(), preferred))

    undecided = entry.get("refuses") is None
    if _refuses(player, player_id, entry, phase=str(phase or ""),
                service_time_days=service_time_days,
                current_years_left=current_years_left, season=season):
        if undecided and commit and notify_owner:
            record_refusal_notice(base, team_id, player_id, name)
        return done(TalksResponse(
            "refused",
            f"{name} won't negotiate during the season: he intends to test free agency.",
            ask(), preferred))

    left = _shutdown_remaining(entry, now)
    if left is not None:
        unit = "free-agency day" if now[0] == "window" else "day"
        return done(TalksResponse(
            "blocked",
            f"{name} has broken off talks; try again in {left} {unit}{'s' if left != 1 else ''}.",
            ask(), preferred, shutdown_days=left,
            shutdown_unit="free-agency days" if now[0] == "window" else "days"))
    if entry.get("shutdown"):
        # The shutdown has run its course: talks reopen, patience restored.
        entry["shutdown"] = None
        entry["patience"] = PATIENCE[kind]
        entry["lowballs"] = 0

    entry["offers"] = int(entry.get("offers") or 0) + 1

    if salary >= minimum:
        if _too_long(player, years, preferred):
            return done(TalksResponse(
                "countered",
                f"{name} likes the money but not {years} more years at his age; "
                f"he'd sign for {preferred}.",
                ask(), preferred, counter_years=preferred))
        return done(TalksResponse("accepted", f"{name} accepts.", ask(), preferred))

    lowball = salary < minimum * LOWBALL_RATIO
    entry["patience"] = int(entry.get("patience", PATIENCE[kind])) - (2 if lowball else 1)
    if lowball:
        entry["lowballs"] = int(entry.get("lowballs") or 0) + 1
    else:
        ratio = float(entry["ask_ratio"])
        step = _step(player_id, int(entry["offers"]))
        entry["ask_ratio"] = MINIMUM_RATIO[kind] + (ratio - MINIMUM_RATIO[kind]) * (1 - step)

    if entry["patience"] <= 0:
        gap = max(0.0, 1.0 - salary / max(1.0, minimum))
        days = SHUTDOWN_BASE_DAYS[kind] + 4 * int(entry.get("lowballs") or 0) + round(20 * gap)
        days = int(min(SHUTDOWN_MAX_DAYS, max(7, days)))
        entry["shutdown"] = {"kind": now[0], "start": now[1], "days": days}
        length = _shutdown_length(days, now[0])
        unit = "free-agency days" if now[0] == "window" else "days"
        response = TalksResponse(
            "shutdown",
            f"{name} has had enough and breaks off talks for {length} {unit}.",
            ask(), preferred, shutdown_days=length, shutdown_unit=unit)
        if commit and notify_owner:
            _tell_owner(base, team_id, player_id, name,
                        f"{name} broke off contract talks with {team_id} for "
                        f"{length} {unit}.")
        return done(response)

    if lowball:
        why = (f"{name} is insulted by ${salary:,}/yr and won't move from "
               f"${ask():,}/yr.")
    else:
        why = f"{name} comes down to ${ask():,}/yr."
    return done(TalksResponse("countered", why, ask(), preferred,
                              counter_years=years))


def record_refusal_notice(base: Path, team_id: str, player_id: str, name: str) -> None:
    _tell_owner(base, team_id, player_id, name,
                f"{name} ({team_id}) won't negotiate an extension during the "
                "season and plans to test free agency.")


def _player_name(player: object, player_id: str) -> str:
    name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip()
    return name or player_id


def _tell_owner(base: Path, team_id: str, player_id: str, name: str, message: str) -> None:
    """A news item and a notification for an owner's club. Never raises."""

    try:
        from services.team_ownership import human_owned_team_ids_strict

        owners = human_owned_team_ids_strict(base)
    except Exception:
        return
    if not owners or str(team_id).upper() not in owners:
        return
    try:
        from utils.news_logger import log_news_event

        log_news_event(message, category="contract", team_id=team_id,
                       file_path=base / "news_feed.txt")
    except Exception:
        _LOGGER.exception("extension talks: could not post news for %s", team_id)
    try:
        from services.notification_engine import NotificationEvent, append_history
        from services.notification_settings import load_notification_settings

        rule = load_notification_settings(team_id).rule(RULE_ID)
        if not rule.enabled:
            return
        append_history(team_id, [NotificationEvent(
            rule_id=RULE_ID,
            severity="info",
            title="Contract talks",
            message=message,
            payload={"team_id": team_id, "player_id": player_id},
            notify=bool(rule.notify),
        )])
    except Exception:
        _LOGGER.exception("extension talks: could not notify %s", team_id)

