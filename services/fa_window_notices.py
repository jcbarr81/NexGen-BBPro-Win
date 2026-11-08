"""Tell owners when free-agent bidding opens and as it moves (8.2.0).

The FA bidding window (:mod:`services.fa_window`) opened lazily in the
offseason with no news item and no notification, so an owner who did not
happen to open the Season page could miss days of bidding. This posts:

* when the window opens: one league news item and a notification to each
  human-owned club;
* each time a day advances: a short news line with the day's signings and a
  notification to each owner who is now outbid on someone (by name);
* (8.8.0) each time a negotiation an owner bid in ends: who signed him and
  for what (``fa_signed_elsewhere``), "you signed X", "X took no deal", or
  that the owner's own signing could not be completed (``fa_bidding``).

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
SIGNED_ELSEWHERE_RULE_ID = "fa_signed_elsewhere"

__all__ = [
    "RULE_ID",
    "SIGNED_ELSEWHERE_RULE_ID",
    "window_opened",
    "day_advanced",
    "owner_notifier",
    "format_utc",
]


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


def _notify(
    team_id: str,
    title: str,
    message: str,
    payload: Dict[str, Any],
    *,
    rule_id: str = RULE_ID,
) -> bool:
    try:
        from services.notification_engine import NotificationEvent, append_history
        from services.notification_settings import load_notification_settings

        rule = load_notification_settings(team_id).rule(rule_id)
        if not rule.enabled:
            return False
        event = NotificationEvent(
            rule_id=rule_id,
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
    offer and another club's offer, one the player would accept, beats it
    (8.8.0: ``fa_negotiations.team_standing``, the rule the signing uses)."""

    from services import fa_negotiations

    names = _player_names(base)
    owned = set(owners)
    out: Dict[str, List[str]] = {}
    negs = fa_negotiations.load_negotiations(data_dir=base)["negotiations"]
    players = None
    for pid, neg in negs.items():
        if not isinstance(neg, dict) or neg.get("status") != "open":
            continue
        for offer in neg.get("offers", []) or []:
            tid = str(offer.get("team_id") or "").strip().upper()
            if tid not in owned or offer.get("is_cpu"):
                continue
            if players is None:
                players = fa_negotiations._players_by_id(base)
            standing = fa_negotiations.team_standing(
                neg, str(offer.get("team_id") or ""), players.get(str(pid))
            ).get("standing")
            if standing == "outbid":
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
        elif day >= total:
            # 8.9.1: the deciding pass had to hold some players back; the
            # window stays open until they settle.
            left = int(state.get("settling") or 0)
            news = (
                f"Free agency day {day} of {total}: {signings}. Bidding stays "
                f"open until the last {left} player{'s' if left != 1 else ''} "
                "settle."
            )
        else:
            news = (
                f"Free agency day {day} of {total}: {signings}. "
                f"Day {day + 1} is open."
            )
        _news(base, news)
        out["news"] = news
        out["signings"] = _signing_news(base, signed)
        if closed or day >= total:
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


def _signing_news(base: Path, signed: List[Mapping[str, Any]]) -> List[str]:
    """One team-tagged news line per signing (8.13.0), so it shows in that
    club's own news. The day's line above only counts them. Contract terms
    are public (the Contracts page shows them), so this reveals nothing new."""

    lines: List[str] = []
    names: Optional[Dict[str, str]] = None
    for entry in signed or []:
        team = str(entry.get("team_id") or "").strip().upper()
        pid = str(entry.get("player_id") or "").strip()
        name = str(entry.get("player_name") or "").strip()
        if not name or name == pid:
            if names is None:
                names = _player_names(base)
            name = names.get(pid) or pid
        if not team or not name:
            continue
        text = f"{team} signed free agent {name}: {_terms(entry)}."
        try:
            from utils.news_logger import log_news_event

            log_news_event(
                text,
                category="free_agency",
                team_id=team,
                file_path=base / "news_feed.txt",
            )
        except Exception:
            _LOGGER.exception("fa notices: could not post a signing")
            continue
        lines.append(text)
    return lines


def _money(value: Any) -> str:
    try:
        amount = int(value or 0)
    except (TypeError, ValueError):
        return "$0"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.2f}M".replace(".00M", "M")
    return f"${amount:,}"


def _terms(offer: Mapping[str, Any]) -> str:
    years = int(offer.get("years", 1) or 1)
    text = f"{years} yr{'s' if years != 1 else ''} at {_money(offer.get('annual_salary'))}/yr"
    if int(offer.get("signing_bonus", 0) or 0):
        text += f" + {_money(offer.get('signing_bonus'))} bonus"
    return text


def owner_notifier(base: Path | str, players_by_id: Mapping[str, Any]):
    """A ``notify_fn`` for ``fa_negotiations.process_negotiations`` (8.8.0):
    each owner whose club bid hears how the negotiation ended.

    * he signed elsewhere: every other owner who bid
      (``fa_signed_elsewhere``), with the deal and, when that was why, that
      the owner's own offer was one he would not take;
    * he signed with you; he took no deal; your signing could not be
      completed (``fa_bidding``).

    None when run on a directory that is not the active league
    (notifications are filed under it) or ownership cannot be read. The
    function it returns never raises, so it cannot fail a window step.
    """

    base = Path(base)
    if not _active_league(base):
        return None
    owners = _owners(base)
    if not owners:
        return None
    owned = set(owners)

    def _name(pid: str) -> str:
        p = players_by_id.get(pid)
        if p is None:
            return pid
        text = f"{getattr(p, 'first_name', '')} {getattr(p, 'last_name', '')}".strip()
        return text or pid

    def _owner_bids(event: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
        # Owners whose own signing failed were told so (fa_sign_failed).
        failed = {str(t) for t in event.get("failed_teams") or []}
        out: Dict[str, Mapping[str, Any]] = {}
        for offer in event.get("bids") or []:
            tid = str(offer.get("team_id") or "").strip()
            if tid.upper() in owned and not offer.get("is_cpu") and tid not in failed:
                out[tid] = offer
        return out

    def _notify_fn(event: Dict[str, Any]) -> None:
        try:
            kind = event.get("type")
            pid = str(event.get("player_id") or "")
            name = _name(pid)
            payload = {"player_id": pid, "player_name": name}
            if kind == "fa_signed":
                winner = str(event.get("signed_team") or "")
                deal = _terms(event.get("offer") or {})
                for tid, offer in _owner_bids(event).items():
                    if tid == winner:
                        _notify(tid, f"You signed {name}",
                                f"{name} signed with you: {deal}.", payload)
                        continue
                    # Not whether he would have taken yours: below his ask
                    # that would give his hidden minimum away.
                    _notify(
                        tid,
                        f"{name} signed with {winner}",
                        f"{name} signed with {winner}: {deal}. Your offer was "
                        f"{_terms(offer)}. He signs the biggest total among the "
                        "offers he would take.",
                        {**payload, "signed_team": winner},
                        rule_id=SIGNED_ELSEWHERE_RULE_ID,
                    )
            elif kind == "fa_no_deal":
                for tid in _owner_bids(event):
                    _notify(
                        tid,
                        f"{name} took no deal",
                        f"{name} would not take any offer on the table, yours "
                        "included, and stays a free agent.",
                        payload,
                    )
            elif kind == "fa_sign_failed":
                tid = str(event.get("team_id") or "")
                if tid.upper() in owned:
                    _notify(
                        tid,
                        f"Could not sign {name}",
                        f"{name} chose your offer ({_terms(event.get('offer') or {})}), "
                        "but the signing could not be completed (roster or payroll "
                        "limits), so your offer was withdrawn.",
                        payload,
                    )
        except Exception:
            _LOGGER.exception("fa notices: could not tell owners about %s", event)

    return _notify_fn
