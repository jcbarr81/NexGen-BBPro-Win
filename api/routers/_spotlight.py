"""The owner dashboard's Spotlight: what needs this club now (8.2.0).

Free agency, the amateur draft and expiring contracts used to live only on
their own pages; an owner had to know to go looking. The Spotlight gathers,
for one club, the big items of the current phase:

* ``free_agency``: the FA bidding window (open: the day, when bids are due,
  where the club leads and where it has been outbid; just closed: who it
  signed), or a finance-off league's open market in the offseason.
* ``draft``: the amateur draft in progress (on the clock, the next pick), or
  the next draft and its scoutable class.
* ``expiring_contracts``: in season, the club's players in the last year of
  their deal and whether extensions are open.
* ``qualifying_offers``: in the offseason, tenders waiting on the owner.
* ``rollover_roster``: in the offseason and preseason, who left at the
  rollover and the active spots still to fill.
* the Season page's action items (:func:`api.routers.season.team_action_items`).

Read-only throughout: nothing here opens the FA window, starts a pick clock,
makes a pick or writes a roster. Every source is read best-effort; a source
that cannot be read drops its item, never the feed.
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from typing import Any, Dict, List, Mapping, Optional

from utils.path_utils import get_data_dir

_LOGGER = logging.getLogger(__name__)

SEVERITY_RANK = {"action": 0, "warning": 1, "info": 2}
# How many days out the July draft starts showing.
DRAFT_HEADS_UP_DAYS = 30
# Players listed per item (the card shows about five).
MAX_PLAYERS = 8

__all__ = ["build_spotlight", "SEVERITY_RANK"]


def _season():
    from . import season

    return season


def _phase() -> Optional[str]:
    try:
        return str(_season().SeasonManager().phase.value)
    except Exception:
        return None


def _sim_date() -> Optional[str]:
    try:
        from utils.sim_date import get_current_sim_date

        return get_current_sim_date()
    except Exception:
        return None


def _parse_day(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _money(amount: Any) -> str:
    try:
        value = int(amount or 0)
    except (TypeError, ValueError):
        return ""
    if value >= 1_000_000:
        text = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"${text}M"
    if value >= 1_000:
        return f"${value // 1_000}K"
    return f"${value}"


class _People:
    """players.csv names and positions, read once per request (plain CSV)."""

    def __init__(self) -> None:
        self._rows: Optional[Dict[str, Dict[str, str]]] = None

    def _load(self) -> Dict[str, Dict[str, str]]:
        if self._rows is None:
            try:
                path = get_data_dir() / "players.csv"
                with path.open(encoding="utf-8", newline="") as fh:
                    self._rows = {
                        str(r.get("player_id") or ""): r for r in csv.DictReader(fh)
                    }
            except Exception:
                self._rows = {}
        return self._rows

    def name(self, pid: str) -> str:
        row = self._load().get(str(pid)) or {}
        name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
        return name or str(pid)

    def position(self, pid: str) -> str:
        row = self._load().get(str(pid)) or {}
        return str(row.get("primary_position") or "")

    def entry(self, pid: str, note: str = "") -> Dict[str, Any]:
        return {
            "player_id": str(pid),
            "name": self.name(pid),
            "position": self.position(pid),
            "note": note,
        }


def _names(entries: List[Mapping[str, Any]], limit: int = 4) -> str:
    shown = [str(e.get("name") or e.get("player_id")) for e in entries[:limit]]
    extra = len(entries) - len(shown)
    return ", ".join(shown) + (f" and {extra} more" if extra > 0 else "")


# ---------------------------------------------------------------------------
# Free agency


def _free_agency_item(
    team_id: str, phase: Optional[str], people: _People
) -> Optional[Dict[str, Any]]:
    from services.fa_window import window_status

    try:
        win = window_status()
    except Exception:
        return None
    status = str(win.get("status") or "")
    if not win.get("finance_enabled"):
        # No bidding window: free agents sign on the spot.
        if phase == "OFFSEASON":
            return {
                "kind": "free_agency",
                "severity": "info",
                "title": "Free agency is open",
                "detail": (
                    "Players whose contracts expired are on the market. Sign "
                    "them on the Free Agency page; signings are immediate."
                ),
                "href": "/free-agency",
            }
        return None
    if win.get("exists") and status == "open":
        return _open_window_item(team_id, win, people)
    if phase != "OFFSEASON":
        return None
    # The window is keyed on the sim date it opened on (fa_window.open_window
    # reopens nothing with the same start date), so a window from this
    # offseason is one that started on today's sim date (the wall-clock date
    # when there is none, as there).
    sim_day = _parse_day(_sim_date()) or date.today()
    start = _parse_day(win.get("start_date"))
    this_offseason = bool(win.get("exists") and start and start == sim_day)
    if this_offseason and status == "closed":
        return _closed_window_item(team_id, win)
    if not this_offseason:
        return {
            "kind": "free_agency",
            "severity": "info",
            "title": "Free-agent bidding opens this offseason",
            "detail": (
                f"Bidding runs for {int(win.get('total_days') or 14)} days. "
                "You'll get a notification when it opens; look over the free "
                "agents now."
            ),
            "href": "/free-agency",
        }
    return None


def _open_window_item(
    team_id: str, win: Mapping[str, Any], people: _People
) -> Dict[str, Any]:
    from services.fa_negotiations import list_team_negotiations

    day = win.get("day")
    total = win.get("total_days")
    leading: List[Dict[str, Any]] = []
    outbid: List[Dict[str, Any]] = []
    try:
        negotiations = list_team_negotiations(team_id)
    except Exception:
        negotiations = []
    tid = team_id.strip().upper()
    for neg in negotiations:
        mine = neg.get("your_offer")
        if neg.get("status") != "open" or not isinstance(mine, dict):
            continue
        leader = neg.get("leading_offer") or {}
        pid = str(neg.get("player_id") or "")
        terms = f"{int(mine.get('years', 1) or 1)}y / {_money(mine.get('annual_salary'))}"
        if str(leader.get("team_id") or "").strip().upper() == tid:
            leading.append(people.entry(pid, f"leading ({terms})"))
        else:
            top = f"{int(leader.get('years', 1) or 1)}y / {_money(leader.get('annual_salary'))}"
            outbid.append(people.entry(pid, f"outbid: top offer {top}"))

    try:
        schedule = _season()._fa_schedule_view(dict(win))
    except Exception:
        schedule = {}
    deadline = schedule.get("deadline_utc")
    if deadline:
        when = (
            "The day closes automatically at the deadline."
            if schedule.get("will_auto_advance")
            else "Bids for today are due by the deadline."
        )
    else:
        when = "The commissioner advances the day."

    parts: List[str] = []
    if outbid:
        parts.append(f"Outbid on {len(outbid)}: {_names(outbid)}. Counter to stay in.")
    if leading:
        parts.append(f"You lead for {len(leading)}: {_names(leading)}.")
    if not outbid and not leading:
        parts.append("You have no live bid.")
    parts.append(when)
    count = len(outbid) + len(leading)
    item: Dict[str, Any] = {
        "kind": "free_agency",
        "severity": "action" if outbid or not leading else "info",
        "title": (
            f"Free-agent bidding is open: day {day} of {total}"
            if day and total
            else "Free-agent bidding is open"
        ),
        "detail": " ".join(parts),
        "href": "/free-agency",
        "count": count,
        "players": (outbid + leading)[:MAX_PLAYERS],
    }
    if deadline:
        item["deadline_utc"] = deadline
    return item


def _closed_window_item(team_id: str, win: Mapping[str, Any]) -> Dict[str, Any]:
    from services.fa_window import load_window

    tid = team_id.strip().upper()
    signed: List[Dict[str, Any]] = []
    try:
        log = (load_window() or {}).get("log") or []
    except Exception:
        log = []
    for entry in log:
        for s in (entry or {}).get("signed") or []:
            if str(s.get("team_id") or "").strip().upper() == tid:
                signed.append(
                    {
                        "player_id": str(s.get("player_id") or ""),
                        "name": str(s.get("player_name") or s.get("player_id") or ""),
                        "position": "",
                        "note": f"{int(s.get('years', 1) or 1)}y / {_money(s.get('annual_salary'))}",
                    }
                )
    if signed:
        detail = f"You signed {len(signed)}: {_names(signed)}."
    else:
        detail = "You signed nobody in the window."
    detail += " Players still unsigned can be signed on the Free Agency page."
    return {
        "kind": "free_agency",
        "severity": "info",
        "title": "Free-agent bidding has closed",
        "detail": detail,
        "href": "/free-agency",
        "count": len(signed),
        "players": signed[:MAX_PLAYERS],
    }


# ---------------------------------------------------------------------------
# Amateur draft


def _pick_slots(state: Mapping[str, Any], rounds: int) -> List[Dict[str, Any]]:
    """Every pick of the draft in order: ``{overall, round, team_id}``."""

    seq = state.get("pick_sequence")
    if isinstance(seq, list) and seq:
        return [
            {
                "overall": i + 1,
                "round": int((e or {}).get("round", 1) or 1),
                "team_id": str((e or {}).get("team_id") or "").strip().upper(),
            }
            for i, e in enumerate(seq)
        ]
    order = [str(t).strip().upper() for t in (state.get("order") or [])]
    if not order:
        return []
    return [
        {"overall": n + 1, "round": n // len(order) + 1, "team_id": order[n % len(order)]}
        for n in range(len(order) * max(1, int(rounds or 1)))
    ]


def _pool_size(year: int) -> int:
    path = get_data_dir() / f"draft_pool_{year}.csv"
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return sum(1 for _ in csv.DictReader(fh))
    except Exception:
        return 0


def _scout_line(year: int) -> str:
    size = _pool_size(year)
    if size:
        return f"The class of {size} prospects is ready to scout on the Draft page."
    return "The draft class is posted on the Draft page when it is generated."


def _draft_item(team_id: str, phase: Optional[str]) -> Optional[Dict[str, Any]]:
    if phase == "AMATEUR_DRAFT":
        return _draft_in_progress_item(team_id)
    try:
        from services.draft_settings import DRAFT_TIMING_PRESEASON, load_draft_settings

        timing = load_draft_settings().timing
    except Exception:
        return None
    season = _season()
    if timing == DRAFT_TIMING_PRESEASON:
        if phase == "OFFSEASON":
            try:
                from .draft import _upcoming_preseason_draft_year

                year = _upcoming_preseason_draft_year()
            except Exception:
                year = None
            if not year or not _pool_size(year):
                return None
            return {
                "kind": "draft",
                "severity": "info",
                "title": f"The {year} amateur draft opens when the preseason begins",
                "detail": (
                    f"It runs before spring training. {_scout_line(year)}"
                ),
                "href": "/draft",
            }
        if phase == "PRESEASON":
            try:
                status = season._preseason_draft_status(season.SeasonManager())
            except Exception:
                return None
            if not status.get("due"):
                return None
            year = season._current_draft_year()
            return {
                "kind": "draft",
                "severity": "info",
                "title": f"The {year} amateur draft opens with training camp",
                "detail": (
                    "It runs before spring training; the season waits for the "
                    f"last pick. {_scout_line(int(year)) if year else ''}"
                ).strip(),
                "href": "/draft",
            }
        return None
    if phase != "REGULAR_SEASON":
        return None
    try:
        schedule = season._load_schedule()
        draft_date = season._compute_draft_date(
            schedule[0].get("date") if schedule else None
        )
        if not draft_date:
            return None
        if (
            season._draft_completed_for_current_year()
            or season._draft_skipped_for_current_year()
            or season._draft_held_in_preseason()
        ):
            return None
    except Exception:
        return None
    today = _parse_day(_sim_date())
    when = _parse_day(draft_date)
    if not today or not when:
        return None
    days = (when - today).days
    if days < 0 or days > DRAFT_HEADS_UP_DAYS:
        return None
    away = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
    return {
        "kind": "draft",
        "severity": "info",
        "title": f"Amateur draft on {when.strftime('%B %d').replace(' 0', ' ')}, {away}",
        "detail": (
            "The regular season pauses for it until the last pick. "
            + _scout_line(when.year)
        ),
        "href": "/draft",
    }


def _draft_in_progress_item(team_id: str) -> Optional[Dict[str, Any]]:
    from services import draft_clock, draft_state
    from services.draft_settings import load_draft_settings

    from .draft import _resolve_year, _team_on_clock

    try:
        year = _resolve_year(None)
        state = draft_state.load_state(year) or {}
        settings = load_draft_settings()
    except Exception:
        return None
    if not state or draft_state.state_is_complete(state, settings.rounds):
        return None
    tid = team_id.strip().upper()
    current = int(state.get("overall_pick", 1) or 1)
    slots = _pick_slots(state, settings.rounds)
    total = len(slots)
    made = sum(
        1
        for s in state.get("selected") or []
        if isinstance(s, dict) and str(s.get("team_id") or "").strip().upper() == tid
    )
    on_clock = str(_team_on_clock(state) or "").strip().upper()
    nxt = next(
        (s for s in slots if s["overall"] >= current and s["team_id"] == tid), None
    )
    made_text = f"You've made {made} pick{'s' if made != 1 else ''}."
    if on_clock == tid and nxt is not None:
        # Read only: the Draft page starts the clock; never start it here.
        due = draft_clock.deadline(state, tid, settings.pick_clock_hours)
        detail = f"Round {nxt['round']}, pick {nxt['overall']} of {total}. "
        detail += (
            "If you haven't picked by the deadline, the CPU picks for you. "
            if due is not None
            else "The draft waits for your pick. "
        )
        item: Dict[str, Any] = {
            "kind": "draft",
            "severity": "action",
            "title": f"You're on the clock in the {year} amateur draft",
            "detail": (detail + made_text).strip(),
            "href": "/draft",
        }
        if due is not None:
            item["deadline_utc"] = due.isoformat()
        return item
    if nxt is not None:
        away = nxt["overall"] - current
        detail = (
            f"Pick {current} of {total} is up. Your next pick: round "
            f"{nxt['round']}, pick {nxt['overall']} "
            f"({away} pick{'s' if away != 1 else ''} away). {made_text}"
        )
    else:
        detail = f"Pick {current} of {total} is up. You have no picks left. {made_text}"
    return {
        "kind": "draft",
        "severity": "info",
        "title": f"The {year} amateur draft is under way",
        "detail": detail,
        "href": "/draft",
    }


# ---------------------------------------------------------------------------
# Contracts


def _expiring_item(
    team_id: str, phase: Optional[str], people: _People
) -> Optional[Dict[str, Any]]:
    from services.contract_negotiator import check_extension_eligibility
    from services.contracts_service import load_contracts_payload

    if phase == "AMATEUR_DRAFT":
        try:
            after = _season().SeasonManager().phase_after_draft().value
        except Exception:
            after = None
        if after != "REGULAR_SEASON":
            return None
    elif phase not in ("REGULAR_SEASON", "PLAYOFFS"):
        return None
    tid = team_id.strip().upper()
    try:
        contracts = load_contracts_payload().get("players") or {}
    except Exception:
        return None
    expiring: Dict[str, Mapping[str, Any]] = {}
    for pid, raw in contracts.items():
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("team_id") or "").strip().upper() != tid:
            continue
        try:
            years = int(raw.get("years_left", 0) or 0)
        except (TypeError, ValueError):
            continue
        if years <= 1:
            expiring[str(pid)] = raw
    if not expiring:
        return None

    scores: Dict[str, float] = {}
    try:
        from utils.player_loader import load_players_from_csv
        from utils.player_overall import player_overall_score

        for p in load_players_from_csv(str(get_data_dir() / "players.csv")):
            pid = str(getattr(p, "player_id", ""))
            if pid in expiring:
                scores[pid] = float(player_overall_score(p) or 0.0)
    except Exception:
        scores = {}
    try:
        from .contracts import _last_rejected_iso

        last_rejected = _last_rejected_iso
    except Exception:  # pragma: no cover - defensive
        last_rejected = lambda _pid: None  # noqa: E731
    sim_day = _sim_date()

    rows: List[Dict[str, Any]] = []
    open_count = 0
    for pid in sorted(expiring, key=lambda p: (-scores.get(p, 0.0), people.name(p))):
        raw = expiring[pid]
        try:
            ok = check_extension_eligibility(
                service_time_days=int(raw.get("service_time_days", 0) or 0),
                current_years_left=int(raw.get("years_left", 0) or 0),
                current_phase=phase,
                last_rejected_iso=last_rejected(pid),
                sim_date_iso=sim_day,
            )
        except Exception:
            ok = None
        salary = _money(raw.get("annual_salary"))
        if ok is not None and ok.eligible:
            open_count += 1
            note = f"{salary}; can extend"
        elif ok is not None and ok.code == "cooldown":
            note = f"{salary}; turned down an offer, {ok.cooldown_days_remaining} more days"
        elif ok is not None and ok.code == "phase_blocked":
            note = f"{salary}; talks paused"
        else:
            note = f"{salary}; heading to free agency"
        rows.append(people.entry(pid, note))

    n = len(rows)
    if phase == "AMATEUR_DRAFT":
        window = "Extension talks pause during the amateur draft and resume after it."
    else:
        window = (
            "Extensions are open until the end of the playoffs; anyone not "
            "re-signed becomes a free agent at the rollover."
        )
    near = phase == "PLAYOFFS"
    if phase == "REGULAR_SEASON":
        try:
            from .finance import EXTEND_REMINDER_DAYS, _regular_season_days_remaining

            left = _regular_season_days_remaining(get_data_dir())
            near = left is not None and 0 < left <= EXTEND_REMINDER_DAYS
        except Exception:
            near = False
    detail = f"Best first: {_names(rows)}. {window}"
    if phase != "AMATEUR_DRAFT" and open_count < n:
        detail += f" {open_count} of {n} can be offered an extension today."
    return {
        "kind": "expiring_contracts",
        "severity": "warning" if near else "info",
        "title": (
            f"{n} player{'s' if n != 1 else ''} in the final year of "
            f"{'their contracts' if n != 1 else 'his contract'}"
        ),
        "detail": detail,
        "href": "/contracts?mine=1&expiring=1",
        "count": n,
        "players": rows[:MAX_PLAYERS],
    }


def _qualifying_offers_item(
    team_id: str, phase: Optional[str], people: _People
) -> Optional[Dict[str, Any]]:
    if phase != "OFFSEASON":
        return None
    try:
        from services.qualifying_offers import QO_VALUE, list_team_qualifying_offers

        from .finance import _current_qo_year

        offers = list_team_qualifying_offers(team_id, _current_qo_year())
    except Exception:
        return None
    pending = [o for o in offers if o.get("decision") == "pending"]
    if not pending:
        return None
    rows = [
        people.entry(
            str(o.get("player_id")), f"earned {_money(o.get('salary'))} last season"
        )
        for o in pending
    ]
    n = len(rows)
    return {
        "kind": "qualifying_offers",
        "severity": "action",
        "title": (
            f"{n} qualifying-offer decision{'s' if n != 1 else ''} waiting on you"
        ),
        "detail": (
            f"Tender a one-year {_money(QO_VALUE)} offer, or let him walk with no "
            f"draft compensation: {_names(rows)}. Decide on the Free Agency page."
        ),
        "href": "/free-agency",
        "count": n,
        "players": rows[:MAX_PLAYERS],
    }


# ---------------------------------------------------------------------------
# The rollover: who left, what to fill


def _rollover_item(
    team_id: str, phase: Optional[str], *, readiness_listed: bool
) -> Optional[Dict[str, Any]]:
    if phase not in ("OFFSEASON", "PRESEASON"):
        return None
    tid = team_id.strip().upper()
    if not (get_data_dir() / "rosters" / f"{tid}.csv").exists():
        return None
    try:
        from services.roster_shortfall import team_roster_shortfall

        report = team_roster_shortfall(tid)
    except Exception:
        _LOGGER.exception("spotlight: could not read %s's roster", tid)
        return None
    try:
        from services.offseason_departures import load_departures

        deps = load_departures(tid)
    except Exception:
        deps = {"retired": [], "contract_expired": []}
    retired = list(deps.get("retired") or [])
    expired = list(deps.get("contract_expired") or [])
    # The readiness item already names what blocks Opening Day.
    blocking = [] if readiness_listed else list(report.get("blocking") or [])
    open_spots = int(report.get("open_spots") or 0)
    left = len(retired) + len(expired)
    if not blocking and not open_spots and not left:
        return None

    parts: List[str] = []
    if left:
        bits = []
        if retired:
            bits.append(f"{len(retired)} retired")
        if expired:
            bits.append(
                f"{len(expired)} contract{'s' if len(expired) != 1 else ''} expired"
            )
        parts.append(f"{left} left the club at the rollover ({', '.join(bits)}).")
    if open_spots or blocking:
        parts.append(
            f"{report.get('active')} of {report.get('active_cap')} active "
            f"({report.get('pitchers')} pitchers, "
            f"{report.get('position_players')} position players)."
        )
    if blocking:
        parts.append("Fix before Opening Day: " + " ".join(str(b) for b in blocking))
    elif open_spots:
        parts.append(
            "Sign free agents or promote from AAA; an open spot does not hold "
            "up the season."
        )
    if blocking:
        severity, title = "action", "Your roster isn't ready for Opening Day"
    elif open_spots:
        severity = "warning"
        title = (
            f"{open_spots} active-roster spot{'s' if open_spots != 1 else ''} to fill"
        )
    else:
        severity = "info"
        title = f"{left} player{'s' if left != 1 else ''} left your club this offseason"

    players = [
        {
            "player_id": str(e.get("player_id") or ""),
            "name": str(e.get("name") or e.get("player_id") or ""),
            "position": str(e.get("position") or ""),
            "note": "retired",
        }
        for e in retired
    ] + [
        {
            "player_id": str(e.get("player_id") or ""),
            "name": str(e.get("name") or e.get("player_id") or ""),
            "position": str(e.get("position") or ""),
            "note": "contract expired",
        }
        for e in expired
    ]
    return {
        "kind": "rollover_roster",
        "severity": severity,
        "title": title,
        "detail": " ".join(parts),
        "href": "/roster",
        # With names listed, ``count`` is how many there are (the card shows
        # "+N more" past the first few); otherwise the spots to fill.
        "count": left or open_spots,
        "players": players[:MAX_PLAYERS],
    }


# ---------------------------------------------------------------------------
# The feed


def build_spotlight(team_id: str) -> Dict[str, Any]:
    """``{team_id, phase, items}``: one club's Spotlight, most urgent first."""

    tid = str(team_id or "").strip()
    phase = _phase()
    people = _People()
    try:
        action_items = list(_season().team_action_items(tid))
    except Exception:
        _LOGGER.exception("spotlight: action items failed for %s", tid)
        action_items = []
    readiness_listed = any(i.get("kind") == "roster_not_ready" for i in action_items)

    items: List[Dict[str, Any]] = []
    builders = (
        lambda: _draft_item(tid, phase),
        lambda: _free_agency_item(tid, phase, people),
        lambda: _qualifying_offers_item(tid, phase, people),
        lambda: _rollover_item(tid, phase, readiness_listed=readiness_listed),
        lambda: _expiring_item(tid, phase, people),
    )
    for build in builders:
        try:
            item = build()
        except Exception:
            _LOGGER.exception("spotlight: an item failed for %s", tid)
            item = None
        if item:
            items.append(item)

    kinds = {i["kind"] for i in items}
    for item in action_items:
        kind = item.get("kind")
        # The Spotlight's own rows say the same thing, with more.
        if kind == "fa_bid_needed" and "free_agency" in kinds:
            continue
        if kind == "roster_spot_open" and "rollover_roster" in kinds:
            continue
        items.append(dict(item))

    for item in items:
        item.setdefault("detail", "")
        item.setdefault("count", len(item.get("players") or []))
    items.sort(key=lambda i: SEVERITY_RANK.get(str(i.get("severity")), 3))
    return {"team_id": tid, "phase": phase, "items": items}
