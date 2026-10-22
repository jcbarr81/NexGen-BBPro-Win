"""What an owner's club must fill before Opening Day (backlog #50, 8.1.2).

At the rollover, expiring contracts release players from every roster
(``services.contracts_service._release_players_from_rosters``): in the
alpha-test rehearsal 134 of 509 active players became free agents. The CPU
refills its own clubs; an owner's club is the owner's, and the CPU never
signs for it. Owners used to learn their club was short only when the
preseason readiness check refused to start the season.

:func:`roster_compliance_errors` IS the roster part of that check: the
multi-owner readiness board (``api.routers.season._league_readiness``), the
commissioner's CPU fill and the sim gate all read it, so the report here can
never disagree with them. Everything else in the report is advisory. There
is no active-roster minimum (26-man roster, 7.46.0): an open active spot is
legal and never holds up the season, so it is reported as open spots, not as
a blocking problem. A short club is one with either.

Read-only throughout: roster files are read with ``load_team_levels``, which
never writes (``load_roster`` writes a placeholder roster for a missing file).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "roster_compliance_errors",
    "team_roster_shortfall",
    "shortfall_message",
    "notify_owner_shortfalls",
]


def _inputs(
    team_id: str, sim_date: Optional[str]
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]], Dict[str, int]]:
    """players.csv, the club's roster levels and the caps in force, read the
    way the roster endpoints and the sim gate read them."""

    from api.routers.validation import effective_caps, load_players_map, load_team_levels

    return load_players_map(), load_team_levels(team_id), effective_caps(sim_date)


def _errors(
    levels: Mapping[str, List[str]],
    players: Mapping[str, Mapping[str, Any]],
    caps: Mapping[str, int],
) -> List[str]:
    from api.routers.validation import level_caps_only
    from services.roster_validation import validate_roster_state

    result = validate_roster_state(
        current_levels=levels,
        players=players,
        level_caps=level_caps_only(caps),
        pitcher_cap=caps["act_pitchers"],
    )
    return list(result.errors)


def roster_compliance_errors(team_id: str, *, sim_date: Optional[str] = None) -> List[str]:
    """The readiness check's roster errors for ``team_id`` (no team prefix).

    The caps in force on ``sim_date`` (default: the league's sim date): 26
    active / 13 pitchers, or 28 / 14 from Sept 1 in the regular season. Any
    error blocks the club's games. Raises when the league's files cannot be
    read, so the sim gate can fail closed.
    """

    players, levels, caps = _inputs(team_id, sim_date)
    return _errors(levels, players, caps)


def team_roster_shortfall(team_id: str, *, sim_date: Optional[str] = None) -> Dict[str, Any]:
    """What ``team_id`` is short of, for the readiness check and the owner.

    ``blocking`` is :func:`roster_compliance_errors` (the readiness check);
    ``open_spots`` is the active cap less the active roster (legal, never
    blocking); ``notes`` is the readiness check's advisory catcher note.
    ``short`` is True when either ``blocking`` or ``open_spots`` is set.
    Counts come from ``services.roster_validation.active_roster_shape``, the
    numbers the check judges. Raises when the league's files cannot be read.
    """

    from services.roster_validation import (
        MIN_POSITION_PLAYERS_ACT,
        active_roster_shape,
        validate_catcher_depth,
    )
    from utils.roster_rules import ORG_LIMIT

    tid = str(team_id or "").strip()
    players, levels, caps = _inputs(tid, sim_date)
    blocking = _errors(levels, players, caps)
    act = list(levels.get("act", []) or [])
    shape = active_roster_shape(act, players)
    active_cap = int(caps["act"])
    open_spots = max(0, active_cap - len(act))
    position_players = int(shape["position_players"])
    org_count = sum(len(levels.get(lvl, []) or []) for lvl in ("act", "aaa", "low"))
    report: Dict[str, Any] = {
        "team_id": tid,
        "active": len(act),
        "active_cap": active_cap,
        "open_spots": open_spots,
        "pitchers": int(shape["pitchers"]),
        "pitcher_cap": int(caps["act_pitchers"]),
        "position_players": position_players,
        "min_position_players": MIN_POSITION_PLAYERS_ACT,
        "position_players_short": max(0, MIN_POSITION_PLAYERS_ACT - position_players),
        "missing_positions": list(shape["missing_positions"]),
        "org_count": org_count,
        "org_limit": ORG_LIMIT,
        "blocking": blocking,
        "ready": not blocking,
        "notes": list(validate_catcher_depth(act, players).warnings),
        "short": bool(blocking) or open_spots > 0,
    }
    report["message"] = shortfall_message(report)
    return report


def shortfall_message(report: Mapping[str, Any], *, reason: str = "") -> str:
    """One line for the news feed and the owner's notifications.

    "BAL: 5 active-roster spots to fill (contracts expired): 21 of 26 active
    (9 pitchers, 12 position players). ..." Blocking problems are named as
    what must be fixed before Opening Day; open spots alone are said to be
    optional, as they are. Empty when the club is not short.
    """

    if not report.get("short"):
        return ""
    team = str(report.get("team_id") or "").strip()
    open_spots = int(report.get("open_spots") or 0)
    why = f" ({reason})" if reason else ""
    if open_spots:
        noun = "spot" if open_spots == 1 else "spots"
        head = f"{open_spots} active-roster {noun} to fill{why}"
    else:
        head = f"roster not ready for Opening Day{why}"
    counts = (
        f"{report.get('active')} of {report.get('active_cap')} active "
        f"({report.get('pitchers')} pitchers, "
        f"{report.get('position_players')} position players)"
    )
    blocking = [str(e) for e in (report.get("blocking") or [])]
    if blocking:
        tail = "Fix before Opening Day: " + " ".join(blocking)
    else:
        tail = (
            "An open spot does not hold up the season; sign free agents or "
            "promote from AAA to fill it."
        )
    prefix = f"{team}: " if team else ""
    return f"{prefix}{head}: {counts}. {tail}"


def notify_owner_shortfalls(
    *,
    expired_teams: Iterable[str] = (),
    reason_expired: str = "contracts expired",
) -> Dict[str, Any]:
    """Post one news item, and a notification, per short human-owned club.

    Run by the rollover after its roster steps (contract expirations,
    retirements, promotions), on the active league (``get_data_dir()``, the
    directory every reader here uses). ``expired_teams`` are the clubs the
    contract step released players from; their notice says so. Only clubs a
    person owns
    (``services.team_ownership.human_owned_team_ids_strict``); when ownership
    cannot be read it stands down and posts nothing. A club with no roster
    file is skipped. The notification goes to the owner's Notifications page
    under the "Active roster spot open" rule: honoured when the club is only
    short of open spots, always sent when something blocks Opening Day.
    Nothing on any roster is changed. Per-club failures are logged and
    skipped; the caller still wraps this, as it must never fail a rollover.

    Returns ``{"status", "teams": [team ids notified]}``.
    """

    from services.offseason_departures import departures_text, load_departures
    from services.team_ownership import human_owned_team_ids_strict
    from utils.news_logger import log_news_event
    from utils.path_utils import get_data_dir

    root = Path(get_data_dir())
    owners = human_owned_team_ids_strict(root)
    if owners is None:
        _LOGGER.warning("roster shortfall: team ownership unreadable; no notices posted")
        return {"status": "ownership_unknown", "teams": []}
    expired = {str(t or "").strip().upper() for t in expired_teams or ()}
    notified: List[str] = []
    for tid in sorted(owners):
        if not (root / "rosters" / f"{tid}.csv").exists():
            continue
        try:
            report = team_roster_shortfall(tid)
        except Exception:
            _LOGGER.exception("roster shortfall: could not read %s", tid)
            continue
        # 8.1.3: name who left (retired, or contract expired), from the
        # rollover's departures record; a club that is not short but lost
        # players still hears who.
        try:
            left = departures_text(load_departures(tid, data_dir=root))
        except Exception:
            _LOGGER.exception("roster shortfall: could not read %s's departures", tid)
            left = ""
        if not report.get("short") and not left:
            continue
        reason = reason_expired if tid in expired else ""
        if report.get("short"):
            message = shortfall_message(report, reason=reason)
            if left:
                message = f"{message} {left}"
        else:
            message = f"{tid}: left the club this offseason. {left}"
        # 8.4.1: the saved lineups and staff still name them.
        try:
            from services.lineup_checks import stale_assignments_text

            stale = stale_assignments_text(tid)
        except Exception:
            _LOGGER.exception("roster shortfall: could not check %s's lineups", tid)
            stale = ""
        if stale:
            message = f"{message} {stale}"
        try:
            log_news_event(
                message,
                category="roster",
                team_id=tid,
                file_path=root / "news_feed.txt",
            )
        except Exception:
            _LOGGER.exception("roster shortfall: could not post the news item for %s", tid)
            continue
        notified.append(tid)
        _notify_owner(tid, report, message)
    return {"status": "ok", "teams": notified}


def _notify_owner(team_id: str, report: Mapping[str, Any], message: str) -> None:
    """Add the notice to the owner's notification history. Never raises."""

    try:
        from services.notification_engine import NotificationEvent, append_history
        from services.notification_settings import load_notification_settings

        blocking = bool(report.get("blocking"))
        rule = load_notification_settings(team_id).rule("roster_spot_open")
        if not blocking and not (rule.enabled and rule.notify):
            return
        event = NotificationEvent(
            rule_id="roster_spot_open",
            severity="warning" if blocking else "info",
            title=(
                "Roster not ready for Opening Day"
                if blocking
                else "Active roster spots to fill"
                if report.get("short")
                else "Players who left your club"
            ),
            message=message,
            payload={
                "team_id": team_id,
                "active": report.get("active"),
                "cap": report.get("active_cap"),
                "open_spots": report.get("open_spots"),
                "blocking": list(report.get("blocking") or []),
            },
        )
        append_history(team_id, [event])
    except Exception:
        _LOGGER.exception("roster shortfall: could not notify the owner of %s", team_id)
