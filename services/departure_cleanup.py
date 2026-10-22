"""Take a player who left a club off its lineups, depth chart and staff (8.4.1).

A club's saved lineups, depth chart and pitching staff used to keep naming a
player after he was traded, released, let go when his contract expired, or
retired: in alpha-test, six of seven owners' lineups still named players
who had left at the 2027 rollover. Now, the moment a roster write takes a
player off a club (``utils.roster_loader._write_checked_rosters``, the one
path every trade, release, contract expiry, waiver and CPU move goes
through, and ``services.player_retirement._scrub_rosters``), this runs for
that club:

* **Lineups** (vs LHP / vs RHP): his slot goes to the best active player who
  can play the position, the rest of the batting order untouched
  (``services.lineup_restore._plan_substitution``, the injured-list swap).
  When nobody can cover the slot properly, that lineup is rebuilt by the
  auto-fill instead, so he never stays in it.
* **Depth chart**: he is removed from every position. The chart keeps its
  auto / hand-saved marker.
* **Pitching staff**: his row is removed; the role is open until the owner
  (or, for a CPU club, the staff auto-fill) fills it. Games already ignored a
  role held by a pitcher not on the active roster.

Moves inside the organisation (sent down, injured list) are not departures
and change nothing here. An owner's club gets one news item naming who took
each lineup spot. Never raises: a failure is logged and the roster write it
follows stands.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

_LOGGER = logging.getLogger(__name__)

__all__ = ["clear_departed", "clear_departures", "org_player_ids"]

HANDS = ("lhp", "rhp")


def org_player_ids(path: Path) -> set:
    """Player ids in a roster file (every level); empty when unreadable."""

    ids: set = set()
    try:
        with Path(path).open("r", encoding="utf-8", newline="") as fh:
            for row in csv.reader(fh):
                if row and (row[0] or "").strip():
                    ids.add(row[0].strip())
    except OSError:
        pass
    return ids


def _read_lineup(path: Path) -> List[tuple]:
    from services.lineup_restore import _read_lineup as read

    return read(path)


def _write_lineup(path: Path, rows: Sequence[tuple]) -> None:
    from utils.atomic_write import atomic_text_writer

    with atomic_text_writer(path, newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["order", "player_id", "position"])
        for order, pid, pos in rows:
            writer.writerow([order, pid, pos])


def _players_by_id(data_dir: Path) -> Dict[str, Any]:
    from utils.player_loader import load_players_from_csv

    return {
        str(p.player_id): p
        for p in load_players_from_csv(str(data_dir / "players.csv"))
    }


def _name(players: Mapping[str, Any], pid: str) -> str:
    p = players.get(pid)
    name = f"{getattr(p, 'first_name', '')} {getattr(p, 'last_name', '')}".strip()
    return name or pid


def _ranked(chart: Mapping[str, List[str]], position: str) -> List[str]:
    return list(chart.get(str(position or "").strip().upper(), []) or [])


def _clear_lineups(
    team_id: str,
    gone: set,
    active: Sequence[str],
    data_dir: Path,
    chart: Mapping[str, List[str]],
    players_cache: Dict[str, Any],
) -> Dict[str, List[Dict[str, str]]]:
    """``{hand: [{gone, replacement, position}]}`` for each lineup changed;
    ``replacement`` is "" when the lineup was rebuilt instead."""

    from services.lineup_restore import _plan_substitution

    changes: Dict[str, List[Dict[str, str]]] = {}
    lineup_dir = data_dir / "lineups"
    for hand in HANDS:
        path = lineup_dir / f"{team_id}_vs_{hand}.csv"
        rows = _read_lineup(path)
        hits = [pid for _o, pid, _p in rows if pid in gone]
        if not hits:
            continue
        if not players_cache:
            players_cache.update(_players_by_id(data_dir))
        made: List[Dict[str, str]] = []
        plan: Optional[List[tuple]] = list(rows)
        for pid in hits:
            slot = next(i for i, r in enumerate(plan) if r[1] == pid)
            position = plan[slot][2]
            plan = _plan_substitution(
                plan, pid, list(active), players_cache, _ranked(chart, position)
            )
            if plan is None:
                break
            made.append({"gone": pid, "replacement": plan[slot][1],
                         "position": position.strip().upper()})
        if plan is not None:
            _write_lineup(path, plan)
        else:
            # Nobody on the active roster can take the slot properly: rebuild
            # this side rather than leave him in it.
            from utils.lineup_autofill import auto_fill_lineup_for_team

            auto_fill_lineup_for_team(
                team_id,
                vs=hand,
                players_file=data_dir / "players.csv",
                roster_dir=data_dir / "rosters",
                lineup_dir=lineup_dir,
            )
            made = [{"gone": pid, "replacement": "", "position": ""} for pid in hits]
        changes[hand] = made
    return changes


def _clear_depth_chart(team_id: str, gone: set, data_dir: Path) -> List[str]:
    path = data_dir / "depth_charts" / f"{team_id}.json"
    if not path.exists():
        return []
    try:
        chart = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(chart, dict):
        return []
    removed: List[str] = []
    for pos, ids in chart.items():
        if not isinstance(ids, list):
            continue
        kept = [pid for pid in ids if pid not in gone]
        if len(kept) != len(ids):
            removed += [pid for pid in ids if pid in gone and pid not in removed]
            chart[pos] = kept
    if removed:
        from utils.atomic_write import atomic_text_writer

        # The format utils.depth_chart.save_depth_chart writes; the auto /
        # hand-saved marker (_auto.json) is left as it is.
        with atomic_text_writer(path, encoding="utf-8") as fh:
            fh.write(json.dumps(chart, indent=2, sort_keys=True))
    return removed


def _clear_staff(team_id: str, gone: set, data_dir: Path) -> List[Dict[str, str]]:
    path = data_dir / "rosters" / f"{team_id}_pitching.csv"
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            rows = [row for row in csv.reader(fh) if row]
    except OSError:
        return []
    kept = [row for row in rows if (row[0] or "").strip() not in gone]
    if len(kept) == len(rows):
        return []
    from utils.atomic_write import atomic_text_writer

    with atomic_text_writer(path, newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for row in kept:
            writer.writerow(row)
    return [
        {"player_id": row[0].strip(), "role": (row[1] if len(row) > 1 else "").strip().upper()}
        for row in rows if (row[0] or "").strip() in gone
    ]


def _owner_news(team_id: str, data_dir: Path, result: Mapping[str, Any],
                players: Mapping[str, Any]) -> None:
    """One news item for an owner's club whose lineup changed."""

    lineups = result.get("lineups") or {}
    if not lineups:
        return
    try:
        from services.team_ownership import human_owned_team_ids_strict

        owners = human_owned_team_ids_strict(data_dir)
    except Exception:
        return
    if not owners or team_id.upper() not in owners:
        return
    if not players:
        players = _players_by_id(data_dir)
    swaps: Dict[tuple, List[str]] = {}
    rebuilt: List[str] = []
    for hand, made in lineups.items():
        for m in made:
            if m["replacement"]:
                swaps.setdefault((m["gone"], m["replacement"], m["position"]), []).append(hand.upper())
            elif hand.upper() not in rebuilt:
                rebuilt.append(hand.upper())
    parts = []
    for (gone, repl, pos), hands in swaps.items():
        sides = " and ".join(f"vs {h}" for h in hands)
        parts.append(
            f"{_name(players, repl)} replaces {_name(players, gone)} at {pos} ({sides})"
        )
    if rebuilt:
        parts.append(
            "your lineup " + " and ".join(f"vs {h}" for h in rebuilt)
            + " was rebuilt by auto-fill"
        )
    message = (
        f"{team_id}: lineups updated for players who left the club: "
        + "; ".join(parts) + ". Review them on the Lineup page."
    )
    if result.get("staff"):
        roles = ", ".join(e["role"] for e in result["staff"] if e["role"])
        if roles:
            message += f" Open pitching-staff roles: {roles}."
    try:
        from utils.news_logger import log_news_event

        log_news_event(message, category="lineup", team_id=team_id,
                       file_path=data_dir / "news_feed.txt")
    except Exception:
        _LOGGER.exception("departure cleanup: could not post news for %s", team_id)


def clear_departed(
    team_id: str,
    player_ids: Iterable[str],
    *,
    data_dir: Path | str,
    active_ids: Optional[Sequence[str]] = None,
    notify: bool = True,
) -> Dict[str, Any]:
    """Remove ``player_ids`` (who have left ``team_id``) from its lineups,
    depth chart and pitching staff. ``active_ids``: the club's active roster
    after the move (read from its roster file when omitted).

    Returns ``{"lineups": {hand: [...]}, "depth_chart": [ids],
    "staff": [{player_id, role}]}``; empty lists when nothing named them.
    Never raises.
    """

    tid = str(team_id or "").strip()
    gone = {str(p).strip() for p in player_ids or () if str(p).strip()}
    result: Dict[str, Any] = {"lineups": {}, "depth_chart": [], "staff": []}
    if not tid or not gone:
        return result
    root = Path(data_dir)
    players: Dict[str, Any] = {}
    try:
        if active_ids is None:
            active_ids = _active_from_file(root / "rosters" / f"{tid}.csv")
        try:
            chart = json.loads((root / "depth_charts" / f"{tid}.json").read_text(encoding="utf-8"))
            chart = chart if isinstance(chart, dict) else {}
        except (OSError, json.JSONDecodeError):
            chart = {}
        # Lineups first: the depth chart (with him still on it, skipped as
        # inactive) ranks who takes his slot.
        result["lineups"] = _clear_lineups(tid, gone, active_ids, root, chart, players)
        result["depth_chart"] = _clear_depth_chart(tid, gone, root)
        result["staff"] = _clear_staff(tid, gone, root)
    except Exception:
        _LOGGER.exception("departure cleanup: failed for %s", tid)
        return result
    if notify:
        _owner_news(tid, root, result, players)
    return result


def _active_from_file(path: Path) -> List[str]:
    act: List[str] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.reader(fh):
                if len(row) >= 2 and row[1].strip().upper() == "ACT":
                    act.append(row[0].strip())
    except OSError:
        pass
    return act


def clear_departures(
    departed: Mapping[str, Iterable[str]], *, data_dir: Path | str
) -> Dict[str, Dict[str, Any]]:
    """:func:`clear_departed` for each ``{team_id: player ids}``."""

    out: Dict[str, Dict[str, Any]] = {}
    for tid, ids in departed.items():
        ids = list(ids or ())
        if ids:
            out[tid] = clear_departed(tid, ids, data_dir=data_dir)
    return out
