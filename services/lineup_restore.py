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
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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


def _plan_substitution(
    rows: List[Tuple[str, str, str]],
    injured_id: str,
    active: Sequence[str],
    players_by_id: Mapping[str, object],
    ranked: Sequence[str],
) -> Optional[List[Tuple[str, str, str]]]:
    """New lineup rows covering *injured_id*'s slot, or None if impossible.

    1. A free (bench) active player who can play the position, preferring the
       ``ranked`` order (chosen backup, then depth chart), then the best fit.
    2. Else a player already in the lineup who can play it moves over, and a
       free player who can play HIS old position (DH: any bat) fills in --
       the backup catcher batting DH goes behind the plate.
    3. Else None: the slot is left for the game-time rebuild rather than
       filled by someone who cannot play it (a centre fielder catching).
    """

    from services.roster_fill import can_play, player_score

    slot = next((i for i, (_o, pid, _p) in enumerate(rows) if pid == injured_id), None)
    if slot is None:
        return list(rows)
    position = rows[slot][2].strip().upper()
    in_lineup = {pid for _o, pid, _p in rows}
    free = [pid for pid in active if pid not in in_lineup]

    def _pick(pool: Sequence[str], pos: str) -> Optional[str]:
        fits = [
            pid for pid in pool
            if can_play(players_by_id.get(pid), pos)
            and not getattr(players_by_id.get(pid), "injured", False)
        ]
        if not fits:
            return None
        for pid in ranked:
            if pid in fits:
                return pid
        return max(fits, key=lambda pid: player_score(players_by_id.get(pid)))

    choice = _pick(free, position)
    new_rows = list(rows)
    active_set = set(active)
    if choice is not None:
        new_rows[slot] = (rows[slot][0], choice, rows[slot][2])
        return new_rows

    movers = [
        (i, pid, pos) for i, (_o, pid, pos) in enumerate(rows)
        if i != slot and pid in active_set
        and not getattr(players_by_id.get(pid), "injured", False)
        and can_play(players_by_id.get(pid), position)
    ]
    rank = {pid: n for n, pid in enumerate(ranked)}
    movers.sort(key=lambda m: (rank.get(m[1], len(rank)), -player_score(players_by_id.get(m[1]))))
    for idx, mover, old_pos in movers:
        filler = _pick(free, old_pos.strip().upper())
        if filler is None:
            continue
        new_rows[slot] = (rows[slot][0], mover, rows[slot][2])
        new_rows[idx] = (rows[idx][0], filler, rows[idx][2])
        return new_rows
    return None


def uncovered_positions(
    team_id: str,
    injured_id: str,
    *,
    active_ids: Iterable[str],
    players_by_id: Mapping[str, object],
    preferred_id: Optional[str] = None,
    lineup_dir: str | Path = "data/lineups",
) -> List[str]:
    """Lineup positions he held that the active roster cannot cover.

    Empty when every slot can be covered -- or when he is in no saved lineup
    (a bench player leaves no hole). A call-up for an owner's club targets
    THESE positions: the hole may be at 1B even though he is a shortstop.
    """

    injured_id = str(injured_id or "").strip()
    active = [str(p) for p in active_ids if str(p) != injured_id]
    lineup_root = resolve_app_path(lineup_dir)
    ranked = _ranked_backups(team_id, injured_id, preferred_id, lineup_root)
    missing: List[str] = []
    for hand in LINEUP_HANDS:
        rows = _read_lineup(_lineup_path(team_id, hand, lineup_root))
        slot = next((r for r in rows if r[1] == injured_id), None)
        if slot is None:
            continue
        if _plan_substitution(rows, injured_id, active, players_by_id, ranked.get(hand, [])) is None:
            pos = slot[2].strip().upper()
            if pos not in missing:
                missing.append(pos)
    return missing


def can_cover_injury(
    team_id: str,
    injured_id: str,
    *,
    active_ids: Iterable[str],
    players_by_id: Mapping[str, object],
    preferred_id: Optional[str] = None,
    lineup_dir: str | Path = "data/lineups",
) -> bool:
    """Whether the active roster can cover every lineup slot he held.

    True when he is in no saved lineup (a bench player leaves no hole).
    """

    injured_id = str(injured_id or "").strip()
    active = [str(p) for p in active_ids if str(p) != injured_id]
    lineup_root = resolve_app_path(lineup_dir)
    ranked = _ranked_backups(team_id, injured_id, preferred_id, lineup_root)
    for hand in LINEUP_HANDS:
        rows = _read_lineup(_lineup_path(team_id, hand, lineup_root))
        if not rows or not any(pid == injured_id for _o, pid, _p in rows):
            continue
        if _plan_substitution(rows, injured_id, active, players_by_id, ranked.get(hand, [])) is None:
            return False
    return True


def _ranked_backups(team_id, injured_id, preferred_id, lineup_root) -> Dict[str, List[str]]:
    try:
        chart = load_depth_chart(team_id)
    except Exception:  # pragma: no cover - defensive
        chart = {}
    ranked: Dict[str, List[str]] = {}
    for hand in LINEUP_HANDS:
        rows = _read_lineup(_lineup_path(team_id, hand, lineup_root))
        slot = next((r for r in rows if r[1] == injured_id), None)
        order = list(depth_order_for_position(chart, slot[2]) or []) if slot else []
        ranked[hand] = ([preferred_id] if preferred_id else []) + order
    return ranked


def substitute_injured_player(
    team_id: str,
    injured_id: str,
    *,
    active_ids: Iterable[str],
    players_by_id: Mapping[str, object],
    preferred_id: Optional[str] = None,
    lineup_dir: str | Path = "data/lineups",
) -> Dict[str, str]:
    """Cover each lineup slot *injured_id* held, changing as little as possible.

    The other half of :func:`restore_depth_chart_starter`, and just as
    surgical: only his slot changes (or, when an eligible starter has to move
    over, that starter's old slot too), so an owner's batting order survives.
    See :func:`_plan_substitution` for the order of preference. Returns
    ``{vs_hand: player_id}`` for the player now in his slot; a lineup nobody
    can cover properly is left for the game-time rebuild.
    """

    injured_id = str(injured_id or "").strip()
    if not injured_id:
        return {}
    active = [str(p) for p in active_ids if str(p) != injured_id]
    lineup_root = resolve_app_path(lineup_dir)
    ranked = _ranked_backups(team_id, injured_id, preferred_id, lineup_root)
    changed: Dict[str, str] = {}
    for hand in LINEUP_HANDS:
        path = _lineup_path(team_id, hand, lineup_root)
        rows = _read_lineup(path)
        slot = next((i for i, (_o, pid, _p) in enumerate(rows) if pid == injured_id), None)
        if slot is None:
            continue
        plan = _plan_substitution(rows, injured_id, active, players_by_id, ranked.get(hand, []))
        if plan is None:
            continue
        _write_lineup(path, plan)
        changed[hand] = plan[slot][1]
    return changed


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
