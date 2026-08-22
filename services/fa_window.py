"""Preseason free-agent bidding window (multi-day).

Entering the preseason opens a 14-day bidding window (only when the league runs
the finance model). On day 1 every CPU team posts opening offers on the free
agents its strategy + roster needs make it a real bidder for; human owners then
bid and counter through the normal FA endpoints. The commissioner (multi-owner)
or the lone player (single-player) advances the window one day at a time; each
day CPU teams counter, blow-away offers sign immediately, and players sign on
their own patience day, so signings stagger across the window. Day 14 signs every
remaining player to the best offer still on the table. Only once the window has
closed does the "list unsigned players" CPU sweep unlock.

Preseason has no day-by-day game sim, so this window carries its OWN virtual
calendar and is driven explicitly by :func:`advance_day` — it never depends on
played game dates. State lives in ``fa_window.json`` beside ``fa_negotiations.json``
in the league data dir; the two share the same per-player negotiation store.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from utils.path_utils import get_data_dir

from services import fa_negotiations

TOTAL_DAYS = 14
_FILENAME = "fa_window.json"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _path(data_dir: Path | str | None) -> Path:
    base = get_data_dir() if data_dir is None else Path(data_dir)
    return base / _FILENAME


def load_window(*, data_dir: Path | str | None = None) -> Optional[Dict[str, Any]]:
    path = _path(data_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _save_window(state: Dict[str, Any], *, data_dir: Path | str | None = None) -> None:
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _parse_date(value: str | None) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).split("T", 1)[0], "%Y-%m-%d").date()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Finance-model gate
# ---------------------------------------------------------------------------

def finance_fa_enabled(*, data_dir: Path | str | None = None) -> bool:
    """True when the league runs the finance model with FA bidding on.

    When false there is no bidding window at all — free-agent signing keeps its
    old instant behavior and the "list unsigned players" button is never locked.
    """
    try:
        from services.finance_settings import (
            LEVEL_OFF,
            load_financial_settings,
        )

        base = get_data_dir() if data_dir is None else Path(data_dir)
        settings = load_financial_settings(
            path=base / "league_financial_settings.json",
        )
        if not settings.enabled:
            return False
        return settings.module_level("gm_free_agency") != LEVEL_OFF
    except Exception:
        return False


def _ai_level(*, data_dir: Path | str | None = None) -> str:
    try:
        from services.finance_settings import load_financial_settings

        base = get_data_dir() if data_dir is None else Path(data_dir)
        settings = load_financial_settings(
            path=base / "league_financial_settings.json",
        )
        return settings.module_level("gm_finance_ai") or "basic"
    except Exception:
        return "basic"


# ---------------------------------------------------------------------------
# Signing plumbing (shared with the regular-season daily hook)
# ---------------------------------------------------------------------------

def _load_players_by_id(data_dir: Path) -> Dict[str, Any]:
    try:
        from utils.player_loader import load_players_from_csv

        return {
            str(getattr(p, "player_id", "")): p
            for p in load_players_from_csv(str(data_dir / "players.csv"))
        }
    except Exception:
        return {}


def _load_teams():
    try:
        from utils.team_loader import load_teams

        return load_teams()
    except Exception:
        return []


def _make_sign_fn(data_dir: Path) -> Callable[..., bool]:
    from services.free_agency import finalize_fa_signing

    def _sign(*, team_id, player_id, offer, player) -> bool:
        return finalize_fa_signing(
            team_id,
            player_id,
            level=str(offer.get("level", "ACT")),
            years=int(offer.get("years", 1) or 1),
            annual_salary=int(offer.get("annual_salary", 0) or 0),
            signing_bonus=int(offer.get("signing_bonus", 0) or 0),
            player=player,
            data_dir=data_dir,
        )

    return _sign


def _seed_cpu_for_day(base: Path, start_iso: str, window_day: int, *, teams=None) -> int:
    """Seed CPU opening bids on the CURRENT unsigned pool for ``window_day``.

    Called on day 1 and again each day as players sign, so CPU teams re-target
    the free agents still available and pursue newly-attractive players — the
    market adapts instead of freezing after day 1. Uses the window start date so
    every negotiation shares the same deadline; the window day is stamped so
    freshly-opened negotiations still get a minimum exposure before signing.
    """
    if teams is None:
        teams = _load_teams()
    try:
        from services.free_agency import list_unsigned_players_from_files

        free_agents = list(list_unsigned_players_from_files(data_dir=base))
    except Exception:
        free_agents = []
    if not free_agents:
        return 0
    return fa_negotiations.seed_cpu_negotiations(
        start_iso,
        free_agents,
        teams,
        ai_level=_ai_level(data_dir=base),
        window_day=window_day,
        data_dir=base,
    )


def _player_name(players_by_id: Dict[str, Any], pid: str) -> str:
    p = players_by_id.get(pid)
    if p is None:
        return pid
    name = f"{getattr(p, 'first_name', '')} {getattr(p, 'last_name', '')}".strip()
    return name or pid


# ---------------------------------------------------------------------------
# Leader snapshot — "who do you need to counter"
# ---------------------------------------------------------------------------

def _open_leaders(players_by_id: Dict[str, Any], *, data_dir: Path) -> List[Dict[str, Any]]:
    """Current leading offer per still-open negotiation, for the day summary."""
    out: List[Dict[str, Any]] = []
    negs = fa_negotiations.load_negotiations(data_dir=data_dir)["negotiations"]
    for pid, neg in negs.items():
        if not isinstance(neg, dict) or neg.get("status") != "open":
            continue
        offers = neg.get("offers", []) or []
        if not offers:
            continue
        leader = max(offers, key=fa_negotiations._offer_value)
        out.append(
            {
                "player_id": pid,
                "player_name": _player_name(players_by_id, pid),
                "leader_team": str(leader.get("team_id", "")),
                "leader_is_cpu": bool(leader.get("is_cpu")),
                "leader_salary": int(leader.get("annual_salary", 0) or 0),
                "leader_years": int(leader.get("years", 1) or 1),
                "teams_offering": sorted(
                    {str(o.get("team_id", "")) for o in offers if o.get("team_id")}
                ),
            }
        )
    out.sort(key=lambda r: -r["leader_salary"])
    return out


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def open_window(
    sim_date: str,
    *,
    data_dir: Path | str | None = None,
    top_n: int = 60,
) -> Optional[Dict[str, Any]]:
    """Open (or return the already-open) preseason window for this preseason.

    Keyed on ``start_date`` (the current sim date), so a new season's preseason
    opens a fresh window while a window already closed this preseason stays
    closed. Returns ``None`` when the finance model / FA bidding is off.
    """
    base = get_data_dir() if data_dir is None else Path(data_dir)
    if not finance_fa_enabled(data_dir=base):
        return None

    start = _parse_date(sim_date) or date.today()
    start_iso = start.isoformat()

    existing = load_window(data_dir=base)
    if existing and existing.get("start_date") == start_iso:
        # Same preseason — don't reopen or re-seed.
        return existing

    deadline = start + timedelta(days=TOTAL_DAYS)
    players_by_id = _load_players_by_id(base)
    seeded = _seed_cpu_for_day(base, start_iso, 1)

    leaders = _open_leaders(players_by_id, data_dir=base)
    state = {
        "version": 1,
        "status": "open",
        "start_date": start_iso,
        "deadline_date": deadline.isoformat(),
        "day": 1,
        "total_days": TOTAL_DAYS,
        "current_date": start_iso,
        "log": [
            {
                "day": 0,
                "date": start_iso,
                "signed": [],
                "cpu_seeded": int(seeded),
                "leaders": leaders,
                "message": (
                    f"Free-agent bidding opened — CPU teams posted opening offers "
                    f"on {seeded} player{'s' if seeded != 1 else ''}."
                ),
            }
        ],
    }
    _save_window(state, data_dir=base)
    return state


def advance_day(
    *,
    data_dir: Path | str | None = None,
) -> Dict[str, Any]:
    """End the current window day: CPU counters, ripe/blow-away offers sign, and
    the final day signs everyone to the best available offer, then close.

    Returns ``{"ok": False, "reason": ...}`` when there's nothing to advance.
    """
    base = get_data_dir() if data_dir is None else Path(data_dir)
    state = load_window(data_dir=base)
    if not state:
        return {"ok": False, "reason": "no_window"}
    if state.get("status") == "closed":
        return {"ok": False, "reason": "already_closed", "window": state}

    day = int(state.get("day", 1) or 1)
    total = int(state.get("total_days", TOTAL_DAYS) or TOTAL_DAYS)
    start = _parse_date(state.get("start_date")) or date.today()
    day_date = (start + timedelta(days=max(0, day - 1))).isoformat()

    players_by_id = _load_players_by_id(base)
    teams = _load_teams()
    sign_fn = _make_sign_fn(base)

    summary = fa_negotiations.process_negotiations(
        day_date,
        data_dir=base,
        sign_fn=sign_fn,
        players_by_id=players_by_id,
        teams=teams,
        ai_level=_ai_level(data_dir=base),
        window_day=day,
        window_total=total,
    )

    signed = [
        {
            "player_id": s.get("player_id"),
            "player_name": _player_name(players_by_id, str(s.get("player_id"))),
            "team_id": s.get("signed_team"),
            "annual_salary": int(s.get("annual_salary", 0) or 0),
            "years": int(s.get("years", 1) or 1),
        }
        for s in (summary.get("signed") or [])
    ]

    is_final = day >= total
    if not is_final:
        # The market moved today — CPU teams re-target whoever is still available
        # for tomorrow (new negotiations get a day of exposure before they can
        # sign, so you can still counter or pivot onto them).
        _seed_cpu_for_day(base, str(state.get("start_date") or ""), day + 1, teams=teams)
    leaders = _open_leaders(players_by_id, data_dir=base)
    log_entry = {
        "day": day,
        "date": day_date,
        "signed": signed,
        "leaders": leaders,
        "message": (
            f"Day {day}: {len(signed)} signing{'s' if len(signed) != 1 else ''}."
            + ("" if not is_final else " Window closed — remaining players took their best offer.")
        ),
    }
    state.setdefault("log", []).append(log_entry)

    if is_final:
        state["status"] = "closed"
    else:
        state["day"] = day + 1
        state["current_date"] = (start + timedelta(days=day)).isoformat()

    _save_window(state, data_dir=base)
    return {"ok": True, "day": day, "signed": signed, "window": state}


def close_window(*, data_dir: Path | str | None = None) -> Dict[str, Any]:
    """Force the window to resolve everyone and close (e.g. on phase advance)."""
    base = get_data_dir() if data_dir is None else Path(data_dir)
    state = load_window(data_dir=base)
    if not state or state.get("status") == "closed":
        return {"ok": False, "reason": "no_open_window"}
    # Jump to the final day and resolve.
    state["day"] = int(state.get("total_days", TOTAL_DAYS) or TOTAL_DAYS)
    _save_window(state, data_dir=base)
    return advance_day(data_dir=base)


def is_open(*, data_dir: Path | str | None = None) -> bool:
    state = load_window(data_dir=data_dir)
    return bool(state and state.get("status") == "open")


def current_day(*, data_dir: Path | str | None = None) -> Optional[int]:
    """The open window's current day (for stamping human offers), else None."""
    state = load_window(data_dir=data_dir)
    if state and state.get("status") == "open":
        try:
            return int(state.get("day", 1) or 1)
        except (TypeError, ValueError):
            return 1
    return None


def unsigned_sweep_locked(*, data_dir: Path | str | None = None) -> bool:
    """Should the 'list unsigned players' CPU sweep be blocked right now?

    Only when the finance model is on AND a window exists that hasn't closed.
    Finance-off leagues (no bidding) are never locked.
    """
    base = get_data_dir() if data_dir is None else Path(data_dir)
    if not finance_fa_enabled(data_dir=base):
        return False
    state = load_window(data_dir=base)
    return bool(state and state.get("status") != "closed")


def _human_participation(base: Path) -> Dict[str, Any]:
    """Which human-owned teams have a live (non-CPU) bid in the open window —
    so a multi-owner league's commissioner can see who's engaged before
    advancing the day."""
    try:
        from services.finance_ai import _human_owned_team_ids

        human = sorted(_human_owned_team_ids(base))
    except Exception:
        human = []
    bidders: set[str] = set()
    if human:
        negs = fa_negotiations.load_negotiations(data_dir=base)["negotiations"]
        human_set = set(human)
        for neg in negs.values():
            if not isinstance(neg, dict) or neg.get("status") != "open":
                continue
            for offer in neg.get("offers", []) or []:
                tid = str(offer.get("team_id") or "").strip()
                if tid in human_set and not offer.get("is_cpu"):
                    bidders.add(tid)
    return {
        "human_teams": human,
        "participants": sorted(bidders),
        "waiting": [t for t in human if t not in bidders],
    }


def window_status(*, data_dir: Path | str | None = None) -> Dict[str, Any]:
    """UI-facing status payload for the Season page FA-window panel."""
    base = get_data_dir() if data_dir is None else Path(data_dir)
    enabled = finance_fa_enabled(data_dir=base)
    state = load_window(data_dir=base)
    log = (state or {}).get("log") or []
    return {
        "finance_enabled": enabled,
        "exists": state is not None,
        "status": (state or {}).get("status"),
        "day": (state or {}).get("day"),
        "total_days": (state or {}).get("total_days", TOTAL_DAYS),
        "start_date": (state or {}).get("start_date"),
        "deadline_date": (state or {}).get("deadline_date"),
        "latest": log[-1] if log else None,
        "sweep_locked": unsigned_sweep_locked(data_dir=base),
        **_human_participation(base),
    }
