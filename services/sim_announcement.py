"""Build the "a simulation finished" message posted to Discord.

Several leagues will run at once, so every post has to say which league it is
about. Beyond that an owner wants three things at a glance: how much baseball
just happened, where the league now sits, and when the next batch is coming.

Kept apart from the posting transport (``services.discord_notify``) and from the
season router so the wording can be tested without a network call or a sim.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

# Discord renders <t:unix:F> as the reader's own local time, which matters when
# a league's owners are in different countries.
def _discord_time(when: datetime) -> str:
    return f"<t:{int(when.timestamp())}:F>"


def _relative(when: datetime) -> str:
    return f"<t:{int(when.timestamp())}:R>"


def league_display_name(league_id: str) -> str:
    """The league's human name, falling back to its id."""

    try:
        from services.league_registry import get_league

        record = get_league(league_id)
        name = str(getattr(record, "display_name", "") or "").strip()
        if name:
            return name
    except Exception:  # pragma: no cover - defensive
        pass
    return league_id or "Unknown league"


def count_games(schedule: Iterable[Dict[str, Any]], played_dates: Sequence[str]) -> int:
    """Games on the simulated dates. Counts what was PLAYED, not what was
    scheduled, so a partially-simulated day is not overstated."""

    wanted = {str(d) for d in played_dates}
    total = 0
    for game in schedule or []:
        if str(game.get("date", "")) not in wanted:
            continue
        played = str(game.get("played", "")).strip()
        if played in {"1", "true", "True"} or str(game.get("result", "")).strip():
            total += 1
    return total


def _plural(count: int, singular: str, plural: Optional[str] = None) -> str:
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_message(
    *,
    league_id: str,
    played_dates: Sequence[str],
    games: int,
    current_sim_date: Optional[str] = None,
    next_deadline: Optional[str] = None,
    next_run_label: Optional[str] = None,
    auto_run: bool = False,
    stopped_reason: Optional[str] = None,
    phase: Optional[str] = None,
) -> Optional[str]:
    """Compose the post, or ``None`` when there is nothing worth saying.

    A sim that played no days (a draft pause, an empty schedule, a no-op) is
    not an event; posting it would just be noise in a shared channel.
    """

    days = len(played_dates or [])
    if days <= 0:
        return None

    name = league_display_name(league_id)
    lines: List[str] = [
        f"⚾ **{name}** — {_plural(days, 'day')} simulated ({_plural(games, 'game')})"
    ]

    where: List[str] = []
    if current_sim_date:
        where.append(f"Now at **{current_sim_date}**")
    if phase:
        pretty = str(phase).replace("_", " ").title()
        where.append(pretty)
    if where:
        lines.append(" · ".join(where))

    if stopped_reason:
        # The owner asked to be interrupted; say so rather than letting the day
        # count look like the sim simply ran short.
        lines.append(f"⏸️ Stopped early — {stopped_reason}")

    deadline = _parse_iso(next_deadline)
    if deadline is not None:
        action = next_run_label or "next simulation"
        if auto_run:
            lines.append(f"⏭️ Next: {action} {_discord_time(deadline)} ({_relative(deadline)})")
        else:
            lines.append(
                f"⏭️ Next deadline {_discord_time(deadline)} ({_relative(deadline)}) "
                "— the commissioner runs it from there"
            )
    else:
        lines.append("⏭️ No next simulation scheduled yet")

    return "\n".join(lines)


__all__ = ["build_message", "count_games", "league_display_name"]
