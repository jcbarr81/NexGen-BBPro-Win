"""Positions a player can cover without listing them (8.15.2, owner rule).

A center fielder can play either corner and a right fielder can play left:
CF is the hardest outfield spot, and RF needs the stronger arm of the two
corners. The reverse does not hold (a left fielder is not a center fielder).

This is the *coverage* rule only -- who counts for a legal active roster
(every required position covered), auto-assign, the depth chart, injury
replacements and the lineup's "not listed at" warning. How well a player
fields a spot he does not list is the engine's business
(``utils.position_fit``: the out-of-position table), and it is unchanged:
a center fielder in left is still charged the CF -> LF move.
"""

from __future__ import annotations

from typing import Iterable, List, Mapping, Set, Tuple

# listed position -> the positions it also covers
IMPLIED_COVERAGE: Mapping[str, Tuple[str, ...]] = {
    "CF": ("LF", "RF"),
    "RF": ("LF",),
}


def implied_positions(listed: Iterable[str]) -> List[str]:
    """Positions ``listed`` covers that it does not name, in a stable order."""

    names = [str(p or "").strip().upper() for p in listed]
    have = set(names)
    out: List[str] = []
    for pos in names:
        for extra in IMPLIED_COVERAGE.get(pos, ()):
            if extra not in have and extra not in out:
                out.append(extra)
    return out


def with_implied(listed: Iterable[str]) -> Set[str]:
    """``listed`` (upper-cased) plus every position it implies."""

    names = {str(p or "").strip().upper() for p in listed if str(p or "").strip()}
    return names | set(implied_positions(names))


__all__ = ["IMPLIED_COVERAGE", "implied_positions", "with_implied"]
