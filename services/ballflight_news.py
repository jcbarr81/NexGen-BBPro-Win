"""The league news for the move to engine generation 7 (the ball-flight
engine), in plain language, with the league's own ballparks.

Posted once, when a league's first season on generation 7 is recorded
(``services.league_rating_centers``): on its own for a league already on
the full rating scale, or folded into the engine-and-scale item of a league
that is converted to the full scale in the same move
(``services.rating_scale_migration.engine_and_scale_news``), so a league is
told once. Nothing here is posted while generation 7's operations switch is
off.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import List, Optional, Tuple

__all__ = [
    "BALLFLIGHT_ENGINE_TEXT",
    "ballflight_paragraph",
    "ballflight_switch_news",
    "league_parks_sentence",
]

_LOGGER = logging.getLogger(__name__)

# What changes, for owners. The numbers are the engine's measured ones
# (RELEASE6_PLAN section 9): MLB-like rates, not promises for a league.
BALLFLIGHT_ENGINE_TEXT = (
    "Every batted ball now flies: how hard it is hit and at what angle "
    "decide how far it carries, with the air thinner at altitude, and it "
    "becomes a home run only if it clears that park's own fence and wall. "
    "Real major-league ballparks play with their real dimensions and walls, "
    "and each park's home runs are matched to what MLB's parks give up, "
    "separately for left- and right-handed batters. Balls in play come off "
    "the bat as ground balls, line drives, fly balls and pop-ups at about "
    "MLB's rates, and a foul pop-up can be caught for an out. Fielders run "
    "balls down: whether a ball is an out, a single, a double or a triple "
    "depends on where it lands and who can get there, so range and speed "
    "show up on every ball. Ground-ball pitchers get more ground balls and "
    "give up fewer home runs. Scoring stays at about MLB's level."
)


def ballflight_switch_news(base: Path | str, *, season: object = None) -> str:
    """The news item for a league whose season starts on generation 7."""

    lead = "The league now plays on the newest game engine, with real ball flight"
    if season not in (None, "", "default"):
        lead = f"Season {season}: " + lead[0].lower() + lead[1:]
    return lead + ", starting this season. " + ballflight_paragraph(base)


def ballflight_paragraph(base: Path | str) -> str:
    """What the ball-flight engine changes, the league's own parks and the
    two sliders: the body of :func:`ballflight_switch_news`, and the part a
    league converted to the full scale in the same move gets in that
    move's item."""

    text = BALLFLIGHT_ENGINE_TEXT
    parks = league_parks_sentence(base)
    if parks:
        text += " " + parks
    return text + (
        " The commissioner's Home Run Rate and Launch Angle sliders now set "
        "how far fly balls carry and how high the ball comes off the bat; "
        "a setting made for the earlier engine starts this season back at "
        "normal."
    )


def league_parks_sentence(base: Path | str) -> str:
    """One sentence on the league's own ballparks: how many of its clubs
    play in a real park on that park's fences, and the rest in the average
    park. ``""`` when the clubs cannot be read."""

    parks = _home_parks(Path(base))
    if not parks:
        return ""
    real = sorted({name for name, is_real in parks if is_real and name})
    clubs = len(parks)
    in_real = sum(1 for _, is_real in parks if is_real)
    if in_real == 0:
        return (
            f"None of the league's {clubs} clubs plays in a real major-league "
            "park, so every club plays in the average major-league park."
        )
    named = ", ".join(real[:6]) + (" and others" if len(real) > 6 else "")
    if in_real == clubs:
        return (
            f"All {clubs} of the league's clubs play in real major-league "
            f"parks ({named}), each on its own fences."
        )
    return (
        f"{in_real} of the league's {clubs} clubs play in real major-league "
        f"parks ({named}), each on its own fences; the other "
        f"{clubs - in_real} play in the average major-league park."
    )


def _home_parks(base: Path) -> List[Tuple[str, bool]]:
    """(park name, has its own fences) of each club in ``teams.csv``."""

    from physics_sim import ballflight

    try:
        with (base / "teams.csv").open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return []
    out: List[Tuple[str, bool]] = []
    for row in rows:
        name = _park_name(row)
        fence = None
        try:
            fence = ballflight._real_fence(name) if name else None
        except Exception:  # pragma: no cover - news must never stop a game
            _LOGGER.exception("could not read the fences of %s", name)
        out.append((name, fence is not None))
    return out


def _park_name(row: dict) -> str:
    from utils.park_utils import park_lookup_name

    stadium = str(row.get("stadium") or "").strip()
    # No park_id column: the old name lookup; an empty one: the generic
    # park (utils.park_utils.park_lookup_name, audit L13).
    park_id: Optional[str] = (
        str(row.get("park_id") or "").strip() if "park_id" in row else None
    )
    try:
        return str(park_lookup_name(stadium, park_id) or "")
    except Exception:  # pragma: no cover - defensive
        return ""
