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

Release 6a adds the out-of-position table (audit M12, owner decision 8):

* :data:`POSITION_MOVE_PENALTY` -- fielding points a player loses when he
  moves FROM his primary position (the outer key) TO another one. A listed
  second position costs :data:`SECONDARY_PENALTY_SCALE` of the table value,
  and a position he does not list costs the cheapest route from any
  position he does list (:func:`move_penalty`).
* :func:`position_fielding` -- the ONE function that turns a fielding
  rating into the rating at a position: ``position_fit_model`` 0 is the
  flat multipliers the engine has always used (x1.0 primary, x0.9 listed,
  x0.75 otherwise), 1 subtracts the table's points. The engine
  (``physics_sim.fielding.adjusted_fielding_rating``, and through it the
  defensive-substitution and injury-replacement scorers) and
  :func:`fielding_fit` both go through it.
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
    "POSITION_MOVE_PENALTY",
    "SECONDARY_PENALTY_SCALE",
    "move_penalty",
    "position_fielding",
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

# Fielding points lost moving FROM a primary position (outer key) TO another
# (Release 6a, RELEASE6_PLAN.md 2.3). Sized from the range and error slopes
# so a point is about one out per 150 games at the new spot: a centre
# fielder loses nothing in a corner, a shortstop a point or two anywhere in
# the infield, a first baseman or an outfielder 14 at short (about 10 runs
# a season), and nobody catches without being a catcher. Every
# ``REST_SIMILAR_SOURCES`` move costs 2 or less and every ``FILL_FAMILY``
# move 7 or less. ``DH`` is the row of a player with no fielding position
# of his own (a DH, a pitcher, an unknown code).
POSITION_MOVE_PENALTY: dict[str, dict[str, float]] = {
    "SS": {"2B": 1, "3B": 2, "1B": 2, "LF": 6, "RF": 6, "CF": 9, "C": 25},
    "2B": {"SS": 6, "3B": 4, "1B": 2, "LF": 6, "RF": 7, "CF": 9, "C": 25},
    "3B": {"SS": 7, "2B": 4, "1B": 2, "LF": 6, "RF": 6, "CF": 11, "C": 25},
    "1B": {"SS": 14, "2B": 9, "3B": 6, "LF": 7, "RF": 8, "CF": 13, "C": 25},
    "LF": {"SS": 14, "2B": 10, "3B": 10, "1B": 4, "RF": 2, "CF": 7, "C": 25},
    "RF": {"SS": 14, "2B": 10, "3B": 10, "1B": 4, "LF": 1, "CF": 7, "C": 25},
    "CF": {"SS": 13, "2B": 9, "3B": 10, "1B": 4, "LF": 0, "RF": 0, "C": 25},
    "C": {"SS": 16, "2B": 12, "3B": 10, "1B": 5, "LF": 9, "RF": 9, "CF": 14},
    "DH": {
        "SS": 16, "2B": 12, "3B": 10, "1B": 6, "LF": 8, "RF": 9, "CF": 14,
        "C": 25,
    },
}
# A listed second position costs this share of the table value (owner
# decision 8); the engine reads it as ``position_secondary_penalty_scale``.
SECONDARY_PENALTY_SCALE = 0.25
# A move the table has no entry for (to DH or P, or an unknown code).
_UNLISTED_MOVE_PENALTY = 10.0


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


def _table_row(position: str) -> dict[str, float]:
    return POSITION_MOVE_PENALTY.get(position) or POSITION_MOVE_PENALTY["DH"]


def move_penalty(
    player: Any,
    position: str,
    secondary_scale: float = SECONDARY_PENALTY_SCALE,
) -> float:
    """Fielding points ``player`` loses at ``position`` (Release 6a).

    Nothing at his primary position. Otherwise the cheapest of:

    * the table's move from his primary position -- times
      ``secondary_scale`` when he lists ``position`` as a second position;
    * for each second position ``q`` he lists, standing at ``q``
      (``secondary_scale`` of the move from his primary to ``q``) and
      moving on from there at the table's full cost.

    So a second baseman who lists third base is charged a quarter of
    2B -> 3B at third, and reaches shortstop by whichever is cheaper of
    2B -> SS and 3B -> SS plus that quarter.
    """

    pos = str(position or "").strip().upper()
    primary = str(_field(player, "primary_position") or "").strip().upper()
    if not pos or pos == primary:
        return 0.0
    listed = player_positions(player) - {primary}
    row = _table_row(primary)
    best = float(row.get(pos, _UNLISTED_MOVE_PENALTY))
    if pos in listed:
        best *= secondary_scale
    for via in sorted(listed):
        if via == pos or via not in POSITION_MOVE_PENALTY:
            continue
        onward = POSITION_MOVE_PENALTY[via].get(pos)
        if onward is None:
            continue
        stand = secondary_scale * float(row.get(via, _UNLISTED_MOVE_PENALTY))
        best = min(best, float(onward) + stand)
    return best


def position_fielding(
    player: Any,
    position: str,
    *,
    model: float = 0.0,
    primary_scale: float = 1.0,
    secondary_scale: float = 0.9,
    out_of_position_scale: float = 0.75,
    secondary_penalty_scale: float = SECONDARY_PENALTY_SCALE,
    fielding: float | None = None,
) -> float:
    """``player``'s fielding rating as he plays ``position``.

    ``model`` 0 (``position_fit_model`` off): the flat multipliers --
    ``primary_scale`` at his primary position, ``secondary_scale`` at a
    listed one, ``out_of_position_scale`` anywhere else -- with the engine's
    own comparisons (``position`` against ``primary_position`` and
    ``other_positions`` as stored), so the number is the one the engine has
    always computed. ``model`` 1: the rating less :func:`move_penalty`.
    ``fielding`` overrides the rating read off the player.
    """

    rating = _rating(player, "fielding", "fa") if fielding is None else fielding
    if model >= 0.5:
        return rating - move_penalty(player, position, secondary_penalty_scale)
    if position == _field(player, "primary_position"):
        return rating * primary_scale
    if position in (_field(player, "other_positions") or ()):
        return rating * secondary_scale
    return rating * out_of_position_scale


def fielding_fit(player: Any, position: str, tuning: Any = None) -> float:
    """How well ``player`` should field ``position`` from ratings alone:
    fielding, plus arm where the throw matters (C, SS, 3B, CF, RF). Works on
    a players.csv-style player (``fa``/``arm``) or engine ratings
    (``fielding``/``arm``).

    Release 6a: with ``tuning`` on ``position_fit_model`` 1 the fielding
    rating is first charged the out-of-position table (:func:`move_penalty`,
    at the tuning's ``position_secondary_penalty_scale``), so the lineup
    auto-fill ranks a stand-in the way the engine will field him. Without
    ``tuning``, or with the model off, the value is unchanged."""

    pos = str(position or "").upper()
    field = _rating(player, "fa", "fielding")
    if tuning is not None and tuning.get("position_fit_model", 0.0) >= 0.5:
        field -= move_penalty(
            player,
            pos,
            tuning.get("position_secondary_penalty_scale", SECONDARY_PENALTY_SCALE),
        )
    arm = _rating(player, "arm")
    if pos in {"C", "SS", "3B", "CF", "RF"}:
        return 0.6 * field + 0.4 * arm
    return 0.85 * field + 0.15 * arm
