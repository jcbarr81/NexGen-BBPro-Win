"""Tell owners when free-agent bidding opens and as it moves (8.2.0).

The FA bidding window (:mod:`services.fa_window`) opened lazily in the
offseason with no news item and no notification, so an owner who did not
happen to open the Season page could miss days of bidding. This posts:

* when the window opens: one league news item and a notification to each
  human-owned club;
* each time a day advances: a short news line with the day's signings and a
  notification to each owner who is now outbid on someone (by name).

Notifications go to the owner's Notifications page under the ``fa_bidding``
rule (on by default; the owner can mute it). Only clubs a person owns hear
(``services.team_ownership.human_owned_team_ids_strict``); when ownership
cannot be read the notifications stand down (the league news still posts).

Best effort and after the fact: these run once the window state is saved,
read only the negotiations, and swallow every error, so they never fail a
window step and never change what any club, CPU or human, does.
"""

from __future__ import annotations

import logging

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

_LOGGER = logging.getLogger(__name__)

RULE_ID = "fa_bidding"

__all__ = ["RULE_ID", "window_opened", "day_advanced", "format_utc"]


def format_utc(value: Any) -> str:
    """"Oct 19, 2026 18:00 UTC" for an ISO instant ('' when unreadable)."""

    from services.fa_schedule import parse_iso_utc

    dt = parse_iso_utc(value)
    if dt is None:
        return ""
    return f"{dt.strftime('%b')} {dt.day}, {dt.year} {dt.strftime('%H:%M')} UTC"


def _active_league(base: Path) -> bool:
    """Notifications are filed under the active league (notification_engine
    and notification_settings read ``get_data_dir()``); a window run on some
    other directory (a test, a tool) posts nothing rather than misfile."""

    try:
        from utils.path_utils import get_data_dir

        return Path(get_data_dir()).resolve() == Path(base).resolve()
    except Exception:
        return False


def _owners(base: Path) -> Optional[List[str]]:
    try:
        from services.team_ownership import human_owned_team_ids_strict

        owners = human_owned_team_ids_strict(base)
    except Exception:
        owners = None
    if owners is None:
        _LOGGER.warning("fa notices: team ownership unreadable; no owner notifications")
        return None
    return sorted(owners)


def _news(base: Path, message: str) -> None:
    try:
        from utils.news_logger import log_news_event

        log_news_event(message, category="free_agency", file_path=base / "news_feed.txt")
    except Exception:
        _LOGGER.exception("fa notices: could not post the news item")


def _notify(team_id: str, title: str, message: str, payload: Dict[str, Any]) -> bool:
    try:
        from services.notification_engine import NotificationEvent, append_history
        from services.notification_settings import load_notification_settings

        rule = load_notification_settings(team_id).rule(RULE_ID)
        if not rule.enabled:
            return False
        event = NotificationEvent(
            rule_id=RULE_ID,
            severity="info",
            title=title,
            message=message,
            payload={"team_id": team_id, **payload},
            notify=bool(rule.notify),
        )
        append_history(team_id, [event])
        return True
    except Exception:
        _LOGGER.exception("fa notices: could not notify %s", team_id)
        return False


def _due_text(base: Path, *, after_advance: bool) -> str:
    """When the current day's bids are due, as owners should read it.

    After an advance the callers re-arm the clock (``fa_schedule.
    roll_after_advance``: now plus the day length, only when a deadline was
    set), so the next deadline is predicted the same way.
    """

    try:
        from services import fa_schedule

        sched = fa_schedule.read_schedule(data_dir=base)
        deadline = sched.get("deadline")
        if deadline and after_advance:
            deadline = fa_schedule.next_deadline_from_now(sched["advance_hours"])
        text = format_utc(deadline) if deadline else ""
        if not text:
            return "before the commissioner advances the day"
        if sched.get("auto_advance"):
            return f"by {text}, when the day advances on its own"
        return f"by {text}"
    except Exception:
        return "before the commissioner advances the day"


def window_opened(state: Mapping[str, Any], *, data_dir: Path | str) -> Dict[str, Any]:
    """The window has just opened: one news item, one notification per owner.

    Returns ``{"news": text, "notified": [team ids]}``. Never raises.
    """

    out: Dict[str, Any] = {"news": "", "notified": []}
    try:
        base = Path(data_dir)
        if not _active_league(base):
            return out
        total = int(state.get("total_days") or 14)
        # No calendar end date: a bidding day ends when the commissioner
        # advances it (or at its deadline), not on the window's own dates.
        through = ""
        due = _due_text(base, after_advance=False)
        news = (
            f"Free-agent bidding is open: {total} bidding days; "
            f"bids for day 1 are due {due}."
        )
        _news(base, news)
        out["news"] = news
        owners = _owners(base)
        if not owners:
            return out
        seeded = 0
        log = state.get("log") or []
        if log:
            seeded = int((log[0] or {}).get("cpu_seeded") or 0)
        message = (
            f"Bidding runs {total} bidding days{through}. Bids for day 1 are due {due}. "
            f"CPU clubs have posted opening offers on {seeded} "
            f"player{'s' if seeded != 1 else ''}. Make your offers on the Free "
            "Agency page; each day the market moves and players sign."
        )
        for tid in owners:
            if _notify(tid, "Free-agent bidding is open", message, {"day": 1, "total_days": total}):
                out["notified"].append(tid)
    except Exception:
        _LOGGER.exception("fa notices: window-open notices failed")
    return out


def _outbid_by_team(base: Path, owners: List[str]) -> Dict[str, List[str]]:
    """``{team: [player names]}``: open negotiations where the owner has an
    offer and another club leads."""

    from services import fa_negotiations

    names = _player_names(base)
    owned = set(owners)
    out: Dict[str, List[str]] = {}
    negs = fa_negotiations.load_negotiations(data_dir=base)["negotiations"]
    for pid, neg in negs.items():
        if not isinstance(neg, dict) or neg.get("status") != "open":
            continue
        offers = neg.get("offers", []) or []
        if not offers:
            continue
        leader = str(max(offers, key=fa_negotiations._offer_value).get("team_id") or "")
        for offer in offers:
            tid = str(offer.get("team_id") or "").strip().upper()
            if tid in owned and not offer.get("is_cpu") and tid != leader.strip().upper():
                out.setdefault(tid, []).append(names.get(str(pid), str(pid)))
    for tid in out:
        out[tid] = sorted(set(out[tid]))
    return out


def _player_names(base: Path) -> Dict[str, str]:
    import csv

    try:
        with (base / "players.csv").open(encoding="utf-8", newline="") as fh:
            return {
                str(r.get("player_id") or ""): (
                    f"{r.get('first_name', '')} {r.get('last_name', '')}".strip()
                    or str(r.get("player_id") or "")
                )
                for r in csv.DictReader(fh)
            }
    except Exception:
        return {}


def day_advanced(
    state: Mapping[str, Any],
    *,
    day: int,
    signed: List[Mapping[str, Any]],
    data_dir: Path | str,
) -> Dict[str, Any]:
    """A window day has just ended (``state`` saved after it): a news line
    with the day's signings and a notification to each outbid owner.

    Returns ``{"news": text, "notified": {team: [names]}}``. Never raises.
    """

    out: Dict[str, Any] = {"news": "", "notified": {}}
    try:
        base = Path(data_dir)
        if not _active_league(base):
            return out
        total = int(state.get("total_days") or 14)
        n = len(signed or [])
        signings = f"{n} signing{'s' if n != 1 else ''}"
        closed = state.get("status") == "closed"
        if closed:
            early = state.get("closed_early_on_day")
            when = (
                f"closed early on day {early} of {total}"
                if early
                else f"has closed: {signings} on day {day} of {total}"
            )
            news = (
                f"Free-agent bidding {when}"
                + (f" ({signings} at the close)" if early else "")
                + "; the remaining players took their best offer."
            )
        else:
            news = (
                f"Free agency day {day} of {total}: {signings}. "
                f"Day {day + 1} is open."
            )
        _news(base, news)
        out["news"] = news
        if closed:
            return out
        owners = _owners(base)
        if not owners:
            return out
        due = _due_text(base, after_advance=True)
        for tid, names in _outbid_by_team(base, owners).items():
            shown = ", ".join(names[:6]) + (
                f" and {len(names) - 6} more" if len(names) > 6 else ""
            )
            message = (
                f"You've been outbid on {shown}. Day {day + 1} of {total} is open: "
                f"counter on the Free Agency page; bids are due {due}."
            )
            if _notify(
                tid,
                f"Outbid on {len(names)} free agent{'s' if len(names) != 1 else ''}",
                message,
                {"day": day + 1, "total_days": total, "players": names},
            ):
                out["notified"][tid] = names
    except Exception:
        _LOGGER.exception("fa notices: day-advance notices failed")
    return out
