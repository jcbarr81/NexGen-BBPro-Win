"""Which position players can cover which spots (Release 3, audit M12/M16).

Two tables, both dependency-free so the physics engine, the lineup auto-fill
and the default game lineup share them:

* :data:`REST_SIMILAR_SOURCES` -- the owner's "similar positions" for rest
  substitutes (DECISIONS.md, Release 3 decision 9): LF and RF swap, a CF moves
  to a corner, a SS moves to 2B or 3B, and any infielder moves to 1B. Keyed by
  the position being filled; the value lists the positions a player may come
  FROM. Catchers are never on it, and nobody moves to C or SS or CF.
* :data:`FILL_FAMILY` -- the wider family the lineup auto-fill prefers when a
  position has nobody listed for it (a 2B or 3B at SS, a corner outfielder in
  CF), so a missing shortstop is not replaced by the best bat on the bench.

The engine still fields any out-of-position player at the flat
``defense_out_of_pos_scale``; the families only decide who is asked to play
there. Release 6's adjacency penalty is expected to read the same tables.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "FIELD_POSITIONS",
    "FILL_ORDER",
    "DIFFICULTY_ORDER",
    "REST_SIMILAR_SOURCES",
    "FILL_FAMILY",
    "player_positions",
    "can_cover_similar",
    "in_fill_family",
    "fielding_fit",
]

FIELD_POSITIONS: tuple[str, ...] = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
# Coverage-first fill order of the lineup auto-fill (catcher first).
FILL_ORDER: tuple[str, ...] = ("C", "SS", "CF", "3B", "2B", "1B", "LF", "RF")
# Hardest position first: an open spot is filled in this order, and a
# player only ever slides from an easier spot to a harder one.
DIFFICULTY_ORDER: tuple[str, ...] = ("C", "SS", "CF", "2B", "3B", "RF", "LF", "1B")

REST_SIMILAR_SOURCES: dict[str, frozenset[str]] = {
    "LF": frozenset({"RF", "CF"}),
    "RF": frozenset({"LF", "CF"}),
    "2B": frozenset({"SS"}),
    "3B": frozenset({"SS"}),
    "1B": frozenset({"2B", "3B", "SS"}),
}

FILL_FAMILY: dict[str, frozenset[str]] = {
    "SS": frozenset({"2B", "3B"}),
    "2B": frozenset({"SS", "3B"}),
    "3B": frozenset({"SS", "2B", "1B"}),
    "1B": frozenset({"3B", "2B", "SS"}),
    "CF": frozenset({"LF", "RF"}),
    "LF": frozenset({"RF", "CF"}),
    "RF": frozenset({"LF", "CF"}),
}


def _field(player: Any, name: str) -> Any:
    if isinstance(player, Mapping):
        return player.get(name)
    return getattr(player, name, None)


def player_positions(player: Any) -> set[str]:
    """Primary position plus every listed one, upper-cased."""

    out: set[str] = set()
    primary = str(_field(player, "primary_position") or "").strip().upper()
    if primary:
        out.add(primary)
    raw = _field(player, "other_positions")
    if isinstance(raw, str):
        text = raw.strip().strip("[]")
        for sep in ("|", "/"):
            text = text.replace(sep, ",")
        items: list[Any] = text.split(",")
    elif raw is None:
        items = []
    else:
        try:
            items = list(raw)
        except TypeError:
            items = [raw]
    for item in items:
        token = str(item or "").strip().strip("'\"").strip().upper()
        if token:
            out.add(token)
    return out


def can_cover_similar(player: Any, position: str) -> bool:
    """True when ``player`` may fill ``position`` as a similar-position rest
    substitute (owner decision 9). Never true for C, SS or CF."""

    sources = REST_SIMILAR_SOURCES.get(str(position or "").upper())
    if not sources:
        return False
    return bool(player_positions(player) & sources)


def in_fill_family(player: Any, position: str) -> bool:
    """True when ``player`` plays a position in ``position``'s fill family."""

    family = FILL_FAMILY.get(str(position or "").upper())
    if not family:
        return False
    return bool(player_positions(player) & family)


def _rating(player: Any, *names: str) -> float:
    for name in names:
        value = _field(player, name)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def fielding_fit(player: Any, position: str) -> float:
    """How well ``player`` should field ``position`` from ratings alone:
    fielding, plus arm where the throw matters (C, SS, 3B, CF, RF). Works on
    a players.csv-style player (``fa``/``arm``) or engine ratings
    (``fielding``/``arm``)."""

    pos = str(position or "").upper()
    field = _rating(player, "fa", "fielding")
    arm = _rating(player, "arm")
    if pos in {"C", "SS", "3B", "CF", "RF"}:
        return 0.6 * field + 0.4 * arm
    return 0.85 * field + 0.15 * arm
