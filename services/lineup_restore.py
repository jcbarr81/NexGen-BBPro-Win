"""Put a returning starter back in the lineup when the depth chart says so.

When a player goes on the injured list he leaves the active roster, which
leaves the stored lineup a man short. The sim notices that (``resolve_lineup``
reports a missing batter) and rebuilds the lineup, so a replacement slots in on
his own.

Coming back is not symmetrical. Activation returns the player to the active
roster, but the lineup is still nine valid players, so nothing rebuilds it and
the regular starter sits on the bench behind the man who covered for him —
indefinitely, however clearly the depth chart says he is the starter.

This module closes that half of the cycle. It is deliberately surgical: it
swaps the returning player into the slot he should own and leaves the rest of
the batting order untouched, rather than regenerating the lineup and throwing
away an order the owner may have set by hand.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from utils.depth_chart import depth_order_for_position, load_depth_chart
from utils.path_utils import resolve_app_path

LINEUP_HANDS = ("lhp", "rhp")


def _lineup_path(team_id: str, vs: str, lineup_dir: Path) -> Path:
    return lineup_dir / f"{team_id}_vs_{vs.lower()}.csv"


def _read_lineup(path: Path) -> List[Tuple[str, str, str]]:
    """Return ``[(order, player_id, position), ...]`` as stored."""
    rows: List[Tuple[str, str, str]] = []
    if not path.exists():
        return rows
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                rows.append(
                    (
                        str(row.get("order", "") or "").strip(),
                        str(row.get("player_id", "") or "").strip(),
                        str(row.get("position", "") or "").strip(),
                    )
                )
    except OSError:
        return []
    return rows


def _write_lineup(path: Path, rows: Sequence[Tuple[str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["order", "player_id", "position"])
        for order, pid, pos in rows:
            writer.writerow([order, pid, pos])


def positions_led_by(team_id: str, player_id: str) -> List[str]:
    """Positions where *player_id* sits first on the team's depth chart."""

    try:
        chart = load_depth_chart(team_id)
    except Exception:  # pragma: no cover - defensive
        return []
    led: List[str] = []
    for position in chart:
        order = depth_order_for_position(chart, position)
        if order and order[0] == player_id:
            led.append(position)
    return led


def restore_depth_chart_starter(
    team_id: str,
    player_id: str,
    *,
    lineup_dir: str | Path = "data/lineups",
    active_ids: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Reinstate *player_id* at any position he tops the depth chart for.

    Returns ``{vs_hand: position}`` for each lineup actually changed. A player
    who is already in the lineup, tops no position, or whose slot is held by
    someone the depth chart ranks ahead of him is left alone — as is a lineup
    that does not exist yet, since the sim will build one from scratch.
    """

    player_id = str(player_id or "").strip()
    if not player_id:
        return {}

    led = positions_led_by(team_id, player_id)
    if not led:
        return {}

    lineup_root = resolve_app_path(lineup_dir)
    active = {str(p) for p in active_ids} if active_ids is not None else None
    changed: Dict[str, str] = {}

    for hand in LINEUP_HANDS:
        path = _lineup_path(team_id, hand, lineup_root)
        rows = _read_lineup(path)
        if not rows:
            continue
        if any(pid == player_id for _order, pid, _pos in rows):
            continue  # already playing

        for position in led:
            slot = next(
                (i for i, (_o, _p, pos) in enumerate(rows) if pos == position),
                None,
            )
            if slot is None:
                continue
            incumbent = rows[slot][1]
            # Never bump someone the depth chart puts ahead of him. (It cannot
            # normally happen — he is first — but a chart edited between the
            # injury and the activation could say otherwise.)
            order_for_pos = depth_order_for_position(load_depth_chart(team_id), position)
            if incumbent in order_for_pos and order_for_pos.index(incumbent) == 0:
                continue
            # Don't install someone who isn't actually available to play.
            if active is not None and player_id not in active:
                continue
            rows[slot] = (rows[slot][0], player_id, position)
            _write_lineup(path, rows)
            changed[hand] = position
            break

    return changed
