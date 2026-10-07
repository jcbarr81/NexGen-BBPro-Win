"""Who covers for an injured player: the depth chart first (audit decision 14).

When a player goes on the injured list:

1. the next healthy player behind him on the team's depth chart who is
   already on the active roster takes his place -- no roster move;
2. the open active-roster spot: an owner's team leaves it open for the owner,
   a CPU team calls up a like-for-like replacement;
3. a promotion happens for an owner's team only when nobody active can cover
   the position, and then from the team's own minor leaguers (chart-listed
   first, never a pitcher for a hitter, never another club's player).

This used to consult the chart only to pick a minor leaguer to PROMOTE and
skipped backups already on the active roster; with nothing promoted the
caller fell back to popping AAA[0] -- often a pitcher -- which is how active
rosters drifted pitcher-heavy until a sim day stalled (audit H9).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Set

from models.roster import Roster
from services.roster_fill import (
    callup_candidates,
    can_play,
    is_pitcher,
    player_score,
)
from utils.depth_chart import depth_order_for_position, load_depth_chart

__all__ = [
    "InjuryCoverage",
    "handle_injury_replacement",
    "promote_depth_chart_replacement",
]


@dataclass
class InjuryCoverage:
    """What happened when a player was placed on the injured list."""

    position: str
    backup_id: Optional[str] = None      # active player who takes his place
    promoted_id: Optional[str] = None    # minor leaguer called up, if any
    promoted_from: Optional[str] = None  # "aaa" or "low"
    left_open: bool = False              # owner's team: spot left for the owner


def _position_of(player: object) -> str:
    if is_pitcher(player):
        return "P"
    return str(getattr(player, "primary_position", "") or "").strip().upper()


def _is_starter(roster: Roster, pitcher: object) -> bool:
    """Whether the injured pitcher is one of the club's starters.

    The staff file (``rosters/{team}_pitching.csv``) decides when it lists
    him: an SP slot is a starter, any relief slot is not. Otherwise his
    pitcher role (``utils.pitcher_role.get_role``) does.
    """

    pid = str(getattr(pitcher, "player_id", "") or "")
    team_id = str(getattr(roster, "team_id", "") or "").strip()
    if pid and team_id:
        try:
            from utils.path_utils import get_data_dir
            from utils.staff_roles import canonical_relief_role

            path = get_data_dir() / "rosters" / f"{team_id}_pitching.csv"
            if path.exists():
                with path.open(newline="", encoding="utf-8") as fh:
                    for row in csv.reader(fh):
                        if len(row) >= 2 and row[0].strip() == pid:
                            return canonical_relief_role(row[1]).startswith("SP")
        except Exception:  # pragma: no cover - fall back to the role
            pass
    from utils.pitcher_role import get_role

    return get_role(pitcher) == "SP"


def handle_injury_replacement(
    roster: Roster,
    injured: object,
    *,
    players_by_id: Mapping[str, object],
    cpu_owned: bool,
    chart: Optional[dict] = None,
    allowed: Optional[Callable[[str, str], bool]] = None,
    covered_check: Optional[Callable[[Optional[str]], object]] = None,
) -> InjuryCoverage:
    """Cover for ``injured`` (already moved off the active roster).

    ``allowed(player_id, from_level)`` vetoes promotions the prospect rules
    forbid. ``covered_check(backup_id)`` returns the lineup positions he held
    that the active roster cannot cover (see
    ``services.lineup_restore.uncovered_positions``; empty = covered); a
    call-up then targets that position, which may differ from his primary.
    Without it, any active player who can play his position counts. Mutates
    ``roster`` only when a promotion happens.
    """

    injured_id = str(getattr(injured, "player_id", "") or "")
    want_pitcher = is_pitcher(injured)
    position = _position_of(injured)
    coverage = InjuryCoverage(position=position)

    if chart is None:
        try:
            chart = load_depth_chart(roster.team_id)
        except Exception:
            chart = {}
    order = [] if want_pitcher else list(depth_order_for_position(chart or {}, position) or [])

    active = [pid for pid in roster.act if pid != injured_id]
    covered = False
    if want_pitcher:
        covered = any(is_pitcher(players_by_id.get(pid)) for pid in active)
    else:
        for pid in order:
            if pid in active and not getattr(players_by_id.get(pid), "injured", False):
                coverage.backup_id = pid
                break
        if coverage.backup_id is None:
            fits = [
                pid for pid in active
                if can_play(players_by_id.get(pid), position)
                and not getattr(players_by_id.get(pid), "injured", False)
            ]
            if fits:
                coverage.backup_id = max(
                    fits, key=lambda pid: player_score(players_by_id.get(pid))
                )
        covered = coverage.backup_id is not None
        if covered_check is not None:
            # A backup who already starts elsewhere cannot simply step in;
            # the lineup plan knows whether a swap works -- and which hole is
            # left (he may have been playing out of position).
            try:
                result = covered_check(coverage.backup_id)
                if isinstance(result, bool):
                    covered = result
                else:
                    missing = [str(p).upper() for p in (result or [])]
                    covered = not missing
                    if missing:
                        position = missing[0]
                        coverage.position = position
                        order = list(depth_order_for_position(chart or {}, position) or [])
            except Exception:
                pass

    if not cpu_owned and covered:
        coverage.left_open = True
        return coverage

    candidates = callup_candidates(
        roster,
        players_by_id,
        want_pitcher=want_pitcher,
        position=None if want_pitcher else position,
        chart_order=order,
        exclude={injured_id},
        allowed=allowed,
        # An owner's open spot is filled only by someone who can play the
        # position (rule 3); otherwise it stays open for the owner.
        position_only=not cpu_owned,
        # A starter is replaced by a starter-capable arm (Release 3).
        want_starter=want_pitcher and _is_starter(roster, injured),
    )
    if not candidates:
        coverage.left_open = True
        return coverage
    pid, level = candidates[0]
    getattr(roster, level).remove(pid)
    roster.act.append(pid)
    coverage.promoted_id = pid
    coverage.promoted_from = level
    if coverage.backup_id is None and not want_pitcher:
        coverage.backup_id = pid
    return coverage


def promote_depth_chart_replacement(
    roster: Roster,
    position: str | None,
    *,
    exclude: Iterable[str] | None = None,
) -> bool:
    """Back-compat: promote the next chart-listed minor leaguer at *position*.

    Kept for callers outside the injury path. The injury path uses
    :func:`handle_injury_replacement`, which also honours active backups.
    """

    team_id = getattr(roster, "team_id", None)
    if not team_id or not position:
        return False
    try:
        chart = load_depth_chart(team_id)
    except Exception:
        return False
    skip: Set[str] = {str(pid) for pid in (exclude or []) if pid}
    for pid in depth_order_for_position(chart, position) or []:
        if not pid or pid in skip or pid in roster.act:
            continue
        for level in ("aaa", "low"):
            source = getattr(roster, level)
            if pid in source:
                source.remove(pid)
                roster.act.append(pid)
                return True
    return False
