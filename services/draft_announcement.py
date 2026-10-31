"""Tell a league's Discord channel that an owner is on the clock, and who
each club picked (8.6.6).

An owner cannot act on a deadline he never saw. The draft page shows a
countdown, but nobody sits on the draft page for a day, so the moment a human
team goes on the clock it is announced — once per pick, with the deadline as a
Discord timestamp so every owner reads it in their own local time.

Separated from the posting transport (``services.discord_notify``) and from the
tick that calls it, so the wording can be checked without a network call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Mapping, Optional, Sequence


def _discord_time(when: datetime) -> str:
    return f"<t:{int(when.timestamp())}:F>"


def _relative(when: datetime) -> str:
    return f"<t:{int(when.timestamp())}:R>"


def team_display_name(team_id: str) -> str:
    """The club's name, falling back to its id."""

    try:
        import csv

        from utils.path_utils import get_data_dir

        path = get_data_dir() / "teams.csv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("team_id", "")).strip().upper() == str(team_id).strip().upper():
                    name = " ".join(
                        part
                        for part in [row.get("city", ""), row.get("name", "")]
                        if str(part or "").strip()
                    ).strip()
                    return name or str(team_id)
    except Exception:  # pragma: no cover - defensive
        pass
    return str(team_id)


def league_display_name(league_id: str) -> str:
    try:
        from services.sim_announcement import league_display_name as _name

        return _name(league_id)
    except Exception:  # pragma: no cover - defensive
        return league_id or "Unknown league"


def build_on_the_clock_message(
    *,
    league_id: str,
    team_id: str,
    round_no: int,
    overall_pick: int,
    deadline: Optional[datetime] = None,
) -> Optional[str]:
    """Compose the post, or ``None`` when there is nothing to say."""

    if not str(team_id or "").strip():
        return None

    league = league_display_name(league_id)
    team = team_display_name(team_id)
    lines = [
        f"⏰ **{league}** — {team} is on the clock",
        f"Round {int(round_no)}, pick {int(overall_pick)} overall.",
    ]
    if deadline is not None:
        lines.append(
            f"Pick by {_discord_time(deadline)} ({_relative(deadline)}) "
            "or the CPU will pick for you."
        )
    else:
        # No clock configured: say so rather than implying a deadline exists.
        lines.append("No pick deadline is set — the draft waits for you.")
    return "\n".join(lines)


def _pick_line(pick: Mapping[str, Any]) -> str:
    name = str(pick.get("name") or pick.get("player_id") or "?").strip()
    position = str(pick.get("position") or "").strip()
    who = f"{name} ({position})" if position else name
    # A pick made for an owner says so (8.7.0); the reason is his alone.
    how = _SOURCE_TEXT.get(str(pick.get("source") or ""), "")
    return (
        f"Round {int(pick.get('round', 1) or 1)}, pick {int(pick.get('overall', 0) or 0)}: "
        f"{team_display_name(str(pick.get('team_id') or ''))} select {who}{how}"
    )


_SOURCE_TEXT = {
    "board": " (from their draft board)",
    "clock": " (auto-pick: the clock ran out)",
}


def build_pick_messages(
    *,
    league_id: str,
    year: int,
    picks: Sequence[Mapping[str, Any]],
    draft_complete: bool = False,
    limit: int = 1900,
) -> List[str]:
    """The posts announcing ``picks`` (each ``{round, overall, team_id, name,
    position}``), in order: one line per pick under one header, split into
    as few posts as fit Discord's length limit. A run of CPU picks is one
    post, not one per pick (Discord rate-limits a webhook). Empty when there
    are no picks."""

    if not picks:
        return []
    league = league_display_name(league_id)
    header = (
        f"🧢 **{league}**: {int(year)} draft pick"
        if len(picks) == 1
        else f"🧢 **{league}**: {int(year)} draft, {len(picks)} picks"
    )
    lines = [_pick_line(p) for p in picks]
    if draft_complete:
        lines.append(f"That completes the {int(year)} draft.")
    posts: List[str] = []
    current = header
    for line in lines:
        if len(current) + 1 + len(line) > limit:
            posts.append(current)
            current = f"🧢 **{league}**: {int(year)} draft (continued)"
        current = f"{current}\n{line}"
    posts.append(current)
    return posts


__all__ = [
    "build_on_the_clock_message",
    "build_pick_messages",
    "league_display_name",
    "team_display_name",
]
