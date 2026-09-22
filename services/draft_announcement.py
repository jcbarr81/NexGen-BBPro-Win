"""Tell a league's Discord channel that an owner is on the clock.

An owner cannot act on a deadline he never saw. The draft page shows a
countdown, but nobody sits on the draft page for a day, so the moment a human
team goes on the clock it is announced — once per pick, with the deadline as a
Discord timestamp so every owner reads it in their own local time.

Separated from the posting transport (``services.discord_notify``) and from the
tick that calls it, so the wording can be checked without a network call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


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


__all__ = ["build_on_the_clock_message", "league_display_name", "team_display_name"]
