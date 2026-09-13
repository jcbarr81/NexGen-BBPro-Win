"""Total up a team's season from the players currently on its roster.

Season stats belong to the player and travel with him: a pitcher traded in June
brings his April starts along. That is the league's chosen model, so a team's
totals are the sum of whoever is on the roster right now — which deliberately
will NOT tie out to the club's game log. A team that traded for a starter with
ten starts shows 53 starts across 43 games, and that is the correct answer to
"what have my current players done this season", which is the question an owner
is actually asking when looking at his own team.

The club's W-L-G record is a different fact and is not computed here: it belongs
to the franchise, not to whoever happens to be wearing the uniform, and the
standings depend on it.

Rates are recomputed from their components. Averaging a column of averages is
wrong whenever the denominators differ, which for a roster is always.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

# Counting stats worth showing, summed straight across the roster. Games
# played is deliberately absent: summing it over 25 players answers nothing
# (it lands in the hundreds), and the club's own game count is right alongside.
BATTING_TOTALS: list[str] = [
    "pa", "ab", "r", "h", "2b", "3b", "hr", "rbi", "bb", "so", "sb",
    "avg", "obp", "slg", "ops",
]
PITCHING_TOTALS: list[str] = [
    "w", "l", "sv", "gs", "ip", "h", "r", "er", "bb", "so", "era", "whip",
]

_BATTING_COUNTS = (
    "pa", "ab", "r", "h", "2b", "3b", "hr", "rbi", "bb", "so", "sb",
    "hbp", "sf", "tb",
)
_PITCHING_COUNTS = ("w", "l", "sv", "gs", "h", "r", "er", "bb", "so", "outs")


def _number(block: Mapping[str, Any], key: str) -> float:
    value = block.get(key)
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _doubles(block: Mapping[str, Any]) -> float:
    # Written as "2b" in some blocks and "b2" in others.
    return _number(block, "2b") or _number(block, "b2")


def _triples(block: Mapping[str, Any]) -> float:
    return _number(block, "3b") or _number(block, "b3")


def _as_int(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(value, 3)


def _rate(numerator: float, denominator: float, places: int = 3) -> float | None:
    """A rate, or ``None`` when it has no meaning yet.

    Zero would read as "hit .000", which is a different claim from "has not
    batted".
    """

    if denominator <= 0:
        return None
    return round(numerator / denominator, places)


def batting_totals(blocks: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Sum a roster's batting lines, recomputing the rate stats."""

    sums = {key: 0.0 for key in _BATTING_COUNTS}
    for block in blocks:
        for key in _BATTING_COUNTS:
            if key == "2b":
                sums[key] += _doubles(block)
            elif key == "3b":
                sums[key] += _triples(block)
            else:
                sums[key] += _number(block, key)

    ab, bb, hbp, sf = sums["ab"], sums["bb"], sums["hbp"], sums["sf"]
    hits = sums["h"]
    # Total bases is normally recorded; reconstruct it when it is not.
    total_bases = sums["tb"] or (
        (hits - sums["2b"] - sums["3b"] - sums["hr"])
        + 2 * sums["2b"]
        + 3 * sums["3b"]
        + 4 * sums["hr"]
    )

    avg = _rate(hits, ab)
    obp = _rate(hits + bb + hbp, ab + bb + hbp + sf)
    slg = _rate(total_bases, ab)
    out: Dict[str, Any] = {key: _as_int(sums[key]) for key in _BATTING_COUNTS}
    out.update(
        {
            "avg": avg,
            "obp": obp,
            "slg": slg,
            "ops": None if obp is None or slg is None else round(obp + slg, 3),
        }
    )
    return {key: out.get(key) for key in BATTING_TOTALS}


def pitching_totals(blocks: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Sum a roster's pitching lines, recomputing ERA and WHIP."""

    sums = {key: 0.0 for key in _PITCHING_COUNTS}
    innings = 0.0
    for block in blocks:
        for key in _PITCHING_COUNTS:
            sums[key] += _number(block, key)
        # Outs are exact; ``ip`` is a float that accumulates error, so prefer
        # outs and fall back only when a block predates them.
        outs = _number(block, "outs")
        innings += outs / 3.0 if outs else _number(block, "ip")

    era = _rate(9.0 * sums["er"], innings, places=2)
    whip = _rate(sums["h"] + sums["bb"], innings)
    out: Dict[str, Any] = {key: _as_int(sums[key]) for key in _PITCHING_COUNTS}
    out.update({"ip": round(innings, 1), "era": era, "whip": whip})
    return {key: out.get(key) for key in PITCHING_TOTALS}


def roster_totals(
    batter_blocks: Iterable[Mapping[str, Any]],
    pitcher_blocks: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    return {
        "batting": batting_totals(batter_blocks),
        "pitching": pitching_totals(pitcher_blocks),
    }


__all__ = [
    "BATTING_TOTALS",
    "PITCHING_TOTALS",
    "batting_totals",
    "pitching_totals",
    "roster_totals",
]
