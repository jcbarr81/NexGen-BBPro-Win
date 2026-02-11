from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
import csv
import re

from utils.path_utils import get_data_dir
from .models import BatterRatings, PitcherRatings


@dataclass(frozen=True)
class LineupSlot:
    order: int
    player_id: str
    position: str


@dataclass(frozen=True)
class PitcherAssignment:
    player_id: str
    role: str


@dataclass
class TeamInputs:
    team_id: str
    lineup: List[BatterRatings]
    lineup_positions: Dict[str, str]
    pitchers: List[PitcherRatings]
    pitcher_roles: Dict[str, str]
    missing_batters: List[str]
    missing_pitchers: List[str]


def _resolve_data_root(base_dir: Path | None) -> Path:
    if base_dir is None:
        return get_data_dir()
    base = Path(base_dir)
    if (base / "rosters").exists() and not (base / "data").exists():
        return base
    return base / "data"


def _normalize_team_id(team_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", team_id or "").upper()


def _normalize_hand(vs_hand: str) -> str:
    hand = (vs_hand or "R").strip().lower()
    if hand in {"l", "lh", "lhp", "left"}:
        return "lhp"
    return "rhp"


def load_roster_status(team_id: str, base_dir: Path | None = None) -> Dict[str, str]:
    base = _resolve_data_root(base_dir)
    team = _normalize_team_id(team_id)
    path = base / "rosters" / f"{team}.csv"
    statuses: Dict[str, str] = {}
    if not path.exists():
        return statuses
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row:
                continue
            player_id = (row[0] or "").strip()
            status = (row[1] if len(row) > 1 else "").strip().upper()
            if player_id:
                statuses[player_id] = status
    return statuses


def active_roster_ids(statuses: Dict[str, str]) -> set[str]:
    return {pid for pid, status in statuses.items() if status == "ACT"}


def load_pitching_staff(
    team_id: str, base_dir: Path | None = None
) -> List[PitcherAssignment]:
    base = _resolve_data_root(base_dir)
    team = _normalize_team_id(team_id)
    path = base / "rosters" / f"{team}_pitching.csv"
    staff: List[PitcherAssignment] = []
    if not path.exists():
        return staff
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row:
                continue
            player_id = (row[0] or "").strip()
            role = (row[1] if len(row) > 1 else "").strip().upper()
            if player_id:
                staff.append(PitcherAssignment(player_id=player_id, role=role))
    return staff


def load_lineup(
    team_id: str, vs_hand: str, base_dir: Path | None = None
) -> List[LineupSlot]:
    base = _resolve_data_root(base_dir)
    team = _normalize_team_id(team_id)
    hand = _normalize_hand(vs_hand)
    path = base / "lineups" / f"{team}_vs_{hand}.csv"
    slots: List[LineupSlot] = []
    if not path.exists():
        return slots
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                order = int(row.get("order") or 0)
            except (TypeError, ValueError):
                continue
            player_id = (row.get("player_id") or "").strip()
            position = (row.get("position") or "").strip().upper()
            if player_id:
                slots.append(
                    LineupSlot(order=order, player_id=player_id, position=position)
                )
    return sorted(slots, key=lambda s: s.order)


def resolve_lineup(
    slots: Iterable[LineupSlot],
    batters_by_id: Dict[str, BatterRatings],
) -> Tuple[List[BatterRatings], Dict[str, str], List[str]]:
    lineup: List[BatterRatings] = []
    positions: Dict[str, str] = {}
    missing: List[str] = []
    for slot in slots:
        batter = batters_by_id.get(slot.player_id)
        if batter is None:
            missing.append(slot.player_id)
            continue
        lineup.append(batter)
        positions[batter.player_id] = slot.position
    return lineup, positions, missing


def _sp_sort_key(role: str) -> Tuple[int, str]:
    role = role or ""
    match = re.match(r"SP(\d+)", role)
    if match:
        return int(match.group(1)), role
    return 99, role


def _normalize_assignment_role(role: str) -> str:
    role = (role or "").strip().upper()
    if role in {"RP", "R"}:
        return "MR"
    return role


def _normalize_extra_role(role: str) -> str:
    role = _normalize_assignment_role(role)
    if not role:
        return "MR"
    if role.startswith("SP"):
        return "MR"
    if role in {"CL", "SU", "MR", "LR"}:
        return role
    return "MR"


def build_staff(
    assignments: Iterable[PitcherAssignment],
    pitchers_by_id: Dict[str, PitcherRatings],
    active_ids: set[str] | None = None,
    game_day: int | None = None,
) -> Tuple[List[PitcherRatings], Dict[str, str], List[str]]:
    starters: List[Tuple[str, PitcherRatings]] = []
    bullpen: List[PitcherRatings] = []
    roles_by_id: Dict[str, str] = {}
    missing: List[str] = []
    assigned_ids: set[str] = set()

    for assignment in assignments:
        if active_ids is not None and assignment.player_id not in active_ids:
            continue
        pitcher = pitchers_by_id.get(assignment.player_id)
        if pitcher is None:
            missing.append(assignment.player_id)
            continue
        role = _normalize_assignment_role(assignment.role)
        roles_by_id[pitcher.player_id] = role
        assigned_ids.add(pitcher.player_id)
        if role.startswith("SP"):
            starters.append((role, pitcher))
        else:
            bullpen.append(pitcher)

    if active_ids is not None:
        for player_id in sorted(active_ids):
            if player_id in assigned_ids:
                continue
            pitcher = pitchers_by_id.get(player_id)
            if pitcher is None:
                continue
            role = _normalize_extra_role(
                pitcher.preferred_role or pitcher.role or ""
            )
            roles_by_id[pitcher.player_id] = role
            bullpen.append(pitcher)

    starters_sorted = sorted(starters, key=lambda item: _sp_sort_key(item[0]))
    ordered: List[PitcherRatings] = []
    if starters_sorted:
        index = 0
        if game_day is not None:
            index = game_day % len(starters_sorted)
        starter = starters_sorted[index][1]
        ordered.append(starter)
        ordered.extend(
            pitcher for idx, (_, pitcher) in enumerate(starters_sorted) if idx != index
        )
    ordered.extend(bullpen)
    return ordered, roles_by_id, missing


def build_team_inputs(
    *,
    team_id: str,
    vs_hand: str,
    batters_by_id: Dict[str, BatterRatings],
    pitchers_by_id: Dict[str, PitcherRatings],
    base_dir: Path | None = None,
    game_day: int | None = None,
) -> TeamInputs:
    lineup_slots = load_lineup(team_id, vs_hand, base_dir=base_dir)
    lineup, positions, missing_batters = resolve_lineup(
        lineup_slots, batters_by_id
    )
    statuses = load_roster_status(team_id, base_dir=base_dir)
    active_ids = active_roster_ids(statuses) if statuses else None
    assignments = load_pitching_staff(team_id, base_dir=base_dir)
    pitchers, roles, missing_pitchers = build_staff(
        assignments,
        pitchers_by_id,
        active_ids=active_ids,
        game_day=game_day,
    )
    return TeamInputs(
        team_id=_normalize_team_id(team_id),
        lineup=lineup,
        lineup_positions=positions,
        pitchers=pitchers,
        pitcher_roles=roles,
        missing_batters=missing_batters,
        missing_pitchers=missing_pitchers,
    )


def build_bench(
    *,
    team_id: str,
    batters_by_id: Dict[str, BatterRatings],
    lineup_ids: Iterable[str],
    base_dir: Path | None = None,
) -> List[BatterRatings]:
    statuses = load_roster_status(team_id, base_dir=base_dir)
    if not statuses:
        return []
    active_ids = active_roster_ids(statuses)
    lineup_set = set(lineup_ids)
    bench: List[BatterRatings] = []
    for player_id in active_ids:
        if player_id in lineup_set:
            continue
        batter = batters_by_id.get(player_id)
        if batter is None:
            continue
        bench.append(batter)
    return bench
