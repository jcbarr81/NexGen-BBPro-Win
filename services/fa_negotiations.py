"""Multi-day free-agent negotiation windows (#12).

Instead of signing a free agent instantly, an owner *submits an offer*, which
opens (or joins) a negotiation window for that player. Over the window
(``NEGOTIATION_WINDOW_DAYS`` in-game days) CPU teams submit and raise real
competing offers, and at the deadline the player evaluates every offer and signs
the best acceptable one — or a clearly market-beating offer can win early.

State lives in ``fa_negotiations.json`` under the league data dir. The daily
processor is called once per simulated day from the season automations; the
actual roster+contract signing is injected via ``sign_fn`` so the core logic is
unit-testable without a full league on disk.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from utils.path_utils import get_data_dir

NEGOTIATION_WINDOW_DAYS = 14
# An offer whose total guaranteed value is this far above the player's
# fair-market total can win before the deadline ("blow-away" early accept).
EARLY_ACCEPT_MULTIPLE = 1.15
# During the preseason bidding window (which advances one explicit day at a
# time) a genuinely blow-away offer signs the player immediately, while a merely
# acceptable offer only signs once the player's own patience day arrives — so
# signings stagger across the window (some day 1, some day 8, some at the
# deadline) instead of all landing at once.
WINDOW_BLOWAWAY_MULTIPLE = 1.30
_FILENAME = "fa_negotiations.json"


def _patience_day(player_id: str, total_days: int) -> int:
    """Deterministic per-player "ready to decide" day in ``1..total_days``.

    Seeded from the player id so it's stable across a window's days and across
    parallel byte-parity runs. A player will accept a merely-acceptable leading
    offer once the window reaches this day; a true blow-away offer can still sign
    them earlier, and the deadline signs everyone regardless.
    """
    total = max(1, int(total_days or 1))
    seed = int(hashlib.md5(f"patience:{player_id}".encode("utf-8")).hexdigest()[:8], 16)
    return (seed % total) + 1


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _path(data_dir: Path | str | None) -> Path:
    base = get_data_dir() if data_dir is None else Path(data_dir)
    return base / _FILENAME


def load_negotiations(*, data_dir: Path | str | None = None) -> Dict[str, Any]:
    path = _path(data_dir)
    if not path.exists():
        return {"version": 1, "negotiations": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "negotiations": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "negotiations": {}}
    payload.setdefault("version", 1)
    negs = payload.get("negotiations")
    if not isinstance(negs, dict):
        payload["negotiations"] = {}
    return payload


def save_negotiations(payload: Dict[str, Any], *, data_dir: Path | str | None = None) -> None:
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value: str | None) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).split("T", 1)[0], "%Y-%m-%d").date()
    except Exception:
        return None


def _offer_value(offer: Dict[str, Any]) -> int:
    """Total guaranteed money — how the player ranks competing offers."""
    salary = max(0, int(offer.get("annual_salary", 0) or 0))
    years = max(1, int(offer.get("years", 1) or 1))
    bonus = max(0, int(offer.get("signing_bonus", 0) or 0))
    return salary * years + bonus


def _new_negotiation(player_id: str, opened: str) -> Dict[str, Any]:
    opened_date = _parse_date(opened) or date.today()
    deadline = opened_date + timedelta(days=NEGOTIATION_WINDOW_DAYS)
    return {
        "player_id": player_id,
        "opened_date": opened_date.isoformat(),
        "deadline_date": deadline.isoformat(),
        "status": "open",
        "offers": [],
        "resolution": None,
    }


def _upsert_offer(negotiation: Dict[str, Any], offer: Dict[str, Any]) -> None:
    """Add or replace a team's offer (one active offer per team)."""
    offers = negotiation.setdefault("offers", [])
    team_id = str(offer.get("team_id"))
    for idx, existing in enumerate(offers):
        if str(existing.get("team_id")) == team_id:
            offers[idx] = offer
            return
    offers.append(offer)


# ---------------------------------------------------------------------------
# Public API — owner actions
# ---------------------------------------------------------------------------

def submit_offer(
    player_id: str,
    team_id: str,
    *,
    years: int,
    annual_salary: int,
    signing_bonus: int = 0,
    level: str = "ACT",
    sim_date: str,
    is_cpu: bool = False,
    data_dir: Path | str | None = None,
) -> Dict[str, Any]:
    """Submit (or update) a team's offer, opening the window if needed."""

    pid = str(player_id or "").strip()
    tid = str(team_id or "").strip()
    payload = load_negotiations(data_dir=data_dir)
    negs = payload["negotiations"]
    negotiation = negs.get(pid)
    if not isinstance(negotiation, dict) or negotiation.get("status") != "open":
        negotiation = _new_negotiation(pid, sim_date)
        negs[pid] = negotiation
    _upsert_offer(
        negotiation,
        {
            "team_id": tid,
            "years": max(1, int(years)),
            "annual_salary": max(0, int(annual_salary)),
            "signing_bonus": max(0, int(signing_bonus or 0)),
            "level": str(level or "ACT").upper(),
            "date": str(sim_date),
            "is_cpu": bool(is_cpu),
        },
    )
    save_negotiations(payload, data_dir=data_dir)
    return negotiation


def withdraw_offer(
    player_id: str, team_id: str, *, data_dir: Path | str | None = None
) -> bool:
    payload = load_negotiations(data_dir=data_dir)
    negotiation = payload["negotiations"].get(str(player_id))
    if not isinstance(negotiation, dict):
        return False
    offers = negotiation.get("offers", [])
    kept = [o for o in offers if str(o.get("team_id")) != str(team_id)]
    if len(kept) == len(offers):
        return False
    negotiation["offers"] = kept
    # An empty window just closes — nothing left to resolve.
    if not kept and negotiation.get("status") == "open":
        negotiation["status"] = "resolved"
        negotiation["resolution"] = {"outcome": "withdrawn"}
    save_negotiations(payload, data_dir=data_dir)
    return True


def get_negotiation(
    player_id: str, *, data_dir: Path | str | None = None
) -> Optional[Dict[str, Any]]:
    return load_negotiations(data_dir=data_dir)["negotiations"].get(str(player_id))


def has_open_negotiation(player_id: str, *, data_dir: Path | str | None = None) -> bool:
    neg = get_negotiation(player_id, data_dir=data_dir)
    return bool(neg and neg.get("status") == "open")


def open_negotiation_player_ids(*, data_dir: Path | str | None = None) -> set[str]:
    """Player ids with an open window — used to lock them out of the instant
    CPU free-agency cycle while a negotiation is live."""
    return {
        pid
        for pid, neg in load_negotiations(data_dir=data_dir)["negotiations"].items()
        if isinstance(neg, dict) and neg.get("status") == "open"
    }


def list_team_negotiations(
    team_id: str, *, data_dir: Path | str | None = None
) -> List[Dict[str, Any]]:
    """Negotiations this team is (or was) party to, newest first, with the
    team's own offer and the current leading offer surfaced for the UI."""
    tid = str(team_id or "").strip()
    out: List[Dict[str, Any]] = []
    for neg in load_negotiations(data_dir=data_dir)["negotiations"].values():
        if not isinstance(neg, dict):
            continue
        offers = neg.get("offers", []) or []
        mine = next((o for o in offers if str(o.get("team_id")) == tid), None)
        resolution = neg.get("resolution") or {}
        involved = mine is not None or str(resolution.get("signed_team")) == tid
        if not involved:
            continue
        leader = max(offers, key=_offer_value) if offers else None
        out.append(
            {
                "player_id": neg.get("player_id"),
                "status": neg.get("status"),
                "deadline_date": neg.get("deadline_date"),
                "your_offer": mine,
                "leading_offer": leader,
                "offer_count": len(offers),
                "resolution": neg.get("resolution"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Daily processing — CPU bidding + resolution
# ---------------------------------------------------------------------------

_FA_SERVICE_DAYS = 6 * 172


def _fair_market_total(player: Any) -> int:
    """Fair-market guaranteed money the player expects (salary x years)."""
    if player is None:
        return 0
    try:
        from services.contract_negotiator import fair_market_salary, fair_market_years

        salary = int(fair_market_salary(player, service_time_days=_FA_SERVICE_DAYS))
        years = max(1, int(fair_market_years(player, service_time_days=_FA_SERVICE_DAYS)))
        return salary * years
    except Exception:
        return 0


def _player_accepts(offer: Dict[str, Any], player: Any) -> bool:
    """Would the player accept this offer's terms right now?"""
    if player is None:
        return True
    try:
        from services.contract_negotiator import evaluate_extension_offer

        ev = evaluate_extension_offer(
            player,
            offered_years=max(1, int(offer.get("years", 1))),
            offered_annual_salary=max(0, int(offer.get("annual_salary", 0))),
            service_time_days=_FA_SERVICE_DAYS,
        )
        return ev.decision == "accepted"
    except Exception:
        return True


def _cpu_bid_round(
    negotiation: Dict[str, Any],
    player_id: str,
    player: Any,
    teams: Any,
    ai_level: str,
    sim_date: str,
    *,
    max_bidders: int = 3,
) -> int:
    """Ensure the top CPU bidders have a live offer at their bid-book value.
    Idempotent within a window (won't lower an existing offer). Returns how many
    offers were added or raised this round."""
    if player is None or not teams:
        return 0
    try:
        from services.finance_ai import build_cpu_free_agent_bid_book
    except Exception:
        return 0
    seed = int(hashlib.md5(str(player_id).encode("utf-8")).hexdigest()[:8], 16)
    try:
        book = build_cpu_free_agent_bid_book(
            player, teams, ai_level=ai_level, rng=random.Random(seed)
        )
    except Exception:
        return 0
    if not book:
        return 0
    ranked = sorted(
        ((tid, int(amt)) for tid, amt in book.items() if int(amt) > 0),
        key=lambda kv: -kv[1],
    )[:max_bidders]
    try:
        from services.contract_negotiator import fair_market_years

        years = max(1, int(fair_market_years(player, service_time_days=_FA_SERVICE_DAYS)))
    except Exception:
        years = 2
    offers = negotiation.setdefault("offers", [])
    existing = {str(o.get("team_id")): o for o in offers}
    added = 0
    for tid, amt in ranked:
        cur = existing.get(tid)
        if cur is not None and int(cur.get("annual_salary", 0)) >= amt:
            continue  # already bidding at/above — don't lower it
        _upsert_offer(
            negotiation,
            {
                "team_id": tid,
                "years": years,
                "annual_salary": amt,
                "signing_bonus": 0,
                "level": "ACT",
                "date": str(sim_date),
                "is_cpu": True,
            },
        )
        added += 1
    return added


def _resolve(
    negotiation: Dict[str, Any],
    player_id: str,
    player: Any,
    sign_fn: Optional[Callable[..., bool]],
    notify_fn: Optional[Callable[[Dict[str, Any]], None]],
    sim_date: str,
    *,
    forced: bool,
) -> Dict[str, Any]:
    """Pick the best acceptable offer and sign it; else close with no deal."""
    offers = negotiation.get("offers", []) or []
    acceptable = [o for o in offers if _player_accepts(o, player)]
    winner = max(acceptable, key=_offer_value) if acceptable else None

    if winner is None:
        negotiation["status"] = "resolved"
        negotiation["resolution"] = {"outcome": "no_deal", "date": str(sim_date)}
        if notify_fn:
            notify_fn({"type": "fa_no_deal", "player_id": player_id})
        return {"signed_team": None, "player_id": player_id}

    team_id = str(winner.get("team_id"))
    signed = True
    if sign_fn is not None:
        try:
            signed = bool(
                sign_fn(team_id=team_id, player_id=player_id, offer=winner, player=player)
            )
        except Exception:
            signed = False
    if not signed:
        # Signing failed (e.g. roster full) — drop that offer and leave the
        # window open for another day rather than losing the player silently.
        negotiation["offers"] = [
            o for o in offers if str(o.get("team_id")) != team_id
        ]
        return {"signed_team": None, "player_id": player_id, "sign_failed": True}

    negotiation["status"] = "resolved"
    negotiation["resolution"] = {
        "outcome": "signed",
        "signed_team": team_id,
        "years": int(winner.get("years", 1)),
        "annual_salary": int(winner.get("annual_salary", 0)),
        "signing_bonus": int(winner.get("signing_bonus", 0)),
        "is_cpu": bool(winner.get("is_cpu")),
        "date": str(sim_date),
        "early": not forced,
    }
    if notify_fn:
        losing = sorted({str(o.get("team_id")) for o in offers} - {team_id})
        notify_fn(
            {
                "type": "fa_signed",
                "player_id": player_id,
                "signed_team": team_id,
                "losing_teams": losing,
            }
        )
    return {
        "signed_team": team_id,
        "player_id": player_id,
        "years": int(winner.get("years", 1)),
        "annual_salary": int(winner.get("annual_salary", 0)),
    }


def process_negotiations(
    sim_date: str,
    *,
    data_dir: Path | str | None = None,
    sign_fn: Optional[Callable[..., bool]] = None,
    players_by_id: Optional[Dict[str, Any]] = None,
    teams: Any = None,
    ai_level: str = "basic",
    notify_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
    window_day: Optional[int] = None,
    window_total: Optional[int] = None,
) -> Dict[str, Any]:
    """Advance every open negotiation by one sim day: CPU teams bid, blow-away
    offers can win early, and windows that hit their deadline resolve.

    ``window_day`` / ``window_total`` opt into the preseason bidding-window
    behavior: resolution is driven by the explicit window day (not the calendar)
    so signings stagger by each player's patience day, and the final window day
    forces every remaining player to take the best offer available. When both are
    ``None`` (the regular-season daily hook) the original calendar-deadline +
    1.15x early-accept behavior is preserved exactly.
    """

    in_window = window_day is not None and window_total is not None
    today = _parse_date(sim_date) or date.today()
    payload = load_negotiations(data_dir=data_dir)
    negs = payload["negotiations"]
    summary: Dict[str, Any] = {
        "processed": 0,
        "cpu_offers": 0,
        "signed": [],
        "no_deal": [],
    }
    changed = False

    for pid, neg in list(negs.items()):
        if not isinstance(neg, dict) or neg.get("status") != "open":
            continue
        summary["processed"] += 1
        player = (players_by_id or {}).get(pid)

        added = _cpu_bid_round(neg, pid, player, teams, ai_level, sim_date)
        if added:
            summary["cpu_offers"] += added
            changed = True

        offers = neg.get("offers", []) or []
        if not offers:
            continue

        deadline = _parse_date(neg.get("deadline_date"))
        at_deadline_date = deadline is not None and today >= deadline
        # In the preseason window the final window day is the hard deadline
        # (rather than the calendar), so day 14 signs everyone to the best
        # available offer regardless of the stored deadline date.
        final_window_day = in_window and int(window_day) >= int(window_total)
        at_deadline = at_deadline_date or final_window_day

        early = False
        if not at_deadline:
            leader = max(offers, key=_offer_value)
            fm = _fair_market_total(player)
            if _player_accepts(leader, player) and fm > 0:
                if in_window:
                    # Blow-away offers sign now; otherwise the player waits for
                    # their own patience day before accepting a fair offer.
                    blowaway = _offer_value(leader) >= WINDOW_BLOWAWAY_MULTIPLE * fm
                    ripe = int(window_day) >= _patience_day(pid, int(window_total))
                    early = blowaway or ripe
                else:
                    early = _offer_value(leader) >= EARLY_ACCEPT_MULTIPLE * fm

        if at_deadline or early:
            result = _resolve(
                neg, pid, player, sign_fn, notify_fn, sim_date, forced=at_deadline
            )
            changed = True
            if result.get("signed_team"):
                summary["signed"].append(result)
            elif not result.get("sign_failed"):
                summary["no_deal"].append(pid)

    if changed:
        save_negotiations(payload, data_dir=data_dir)
    return summary


def seed_cpu_negotiations(
    sim_date: str,
    free_agents: List[Any],
    teams: Any,
    *,
    ai_level: str = "basic",
    top_n: int = 60,
    data_dir: Path | str | None = None,
) -> int:
    """Open CPU-initiated negotiations so the market is alive from day 1.

    CPU teams never *start* a negotiation on their own during the daily hook —
    they only counter inside a window a human opened. For the preseason bidding
    window we seed one here: for the top ``top_n`` free agents by fair-market
    value, any CPU team whose strategy + roster needs make it a real bidder posts
    an opening offer (via the existing bid-book). Players no CPU team wants get no
    negotiation and fall through to the post-window "list unsigned players" sweep,
    which is exactly the "top-tier + fill needs, not everyone" behavior we want.

    Returns the number of players that received at least one CPU opening offer.
    Idempotent: re-running won't lower a standing offer or duplicate a window.
    """

    if not free_agents or not teams:
        return 0
    ranked = sorted(free_agents, key=_fair_market_total, reverse=True)[: max(0, top_n)]
    payload = load_negotiations(data_dir=data_dir)
    negs = payload["negotiations"]
    seeded = 0
    changed = False
    for player in ranked:
        pid = str(getattr(player, "player_id", "") or "").strip()
        if not pid:
            continue
        neg = negs.get(pid)
        existed = isinstance(neg, dict) and neg.get("status") == "open"
        if not existed:
            neg = _new_negotiation(pid, sim_date)
        added = _cpu_bid_round(neg, pid, player, teams, ai_level, sim_date)
        # Only persist a *new* negotiation if a CPU team actually bid; otherwise
        # we'd leave an empty open window that never resolves.
        if existed:
            if added:
                seeded += 1
                changed = True
        elif neg.get("offers"):
            negs[pid] = neg
            seeded += 1
            changed = True
    if changed:
        save_negotiations(payload, data_dir=data_dir)
    return seeded
