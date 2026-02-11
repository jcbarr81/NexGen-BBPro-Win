import csv
import random
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Tuple

from playbalance.simulation import TeamState
from models.player import Player
from models.pitcher import Pitcher
from utils.path_utils import resolve_app_path
from .player_loader import load_players_from_csv
from .roster_loader import load_roster
from .pitcher_role import get_role
from utils.team_loader import load_teams


def load_lineup(team_id: str, vs: str = "lhp", lineup_dir: str | Path = "data/lineups") -> List[Tuple[str, str]]:
    """Load a lineup from ``lineup_dir`` for the given team.

    Files are expected to follow the naming pattern
    ``{team_id}_vs_{vs}.csv`` and contain columns
    ``order,player_id,position`` where ``player_id`` uses IDs like
    ``P1000``.
    """
    suffix = f"vs_{vs.lower()}"
    lineup_dir = resolve_app_path(lineup_dir)
    file_path = lineup_dir / f"{team_id}_{suffix}.csv"
    if not file_path.exists():
        raise FileNotFoundError(f"Lineup file not found: {file_path}")

    lineup: List[Tuple[str, str]] = []
    with file_path.open(newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            player_id = row.get("player_id", "").strip()
            position = row.get("position", "").strip()
            lineup.append((player_id, position))
    return lineup


def _separate_players(players: Iterable[Player]) -> Tuple[List[Player], List[Pitcher]]:
    """Return hitters and pitchers from ``players``.

    Pitchers are identified using :func:`utils.pitcher_role.get_role`.  Players
    for which ``get_role`` returns ``"SP"`` or ``"RP"`` are treated as
    pitchers, everything else is considered a position player.
    """

    hitters: List[Player] = []
    pitchers: List[Pitcher] = []
    for p in players:
        role = get_role(p)
        if role in {"SP", "RP"}:
            pitchers.append(p)  # type: ignore[arg-type]
        else:
            hitters.append(p)
    return hitters, pitchers


def _load_pitching_staff(
    team_id: str,
    roster_dir: str,
    valid_pitchers: set[str],
) -> List[tuple[str, str]]:
    """Return ordered pitching staff entries from ``*_pitching.csv``."""

    roster_path = resolve_app_path(roster_dir)
    file_path = roster_path / f"{team_id}_pitching.csv"
    entries: List[tuple[str, str]] = []
    if not file_path.exists():
        return entries
    seen: set[str] = set()
    try:
        with file_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            for row in reader:
                if len(row) < 2:
                    continue
                pid = row[0].strip()
                role = row[1].strip()
                if not pid or pid in seen or pid not in valid_pitchers:
                    continue
                entries.append((pid, role))
                seen.add(pid)
    except OSError:
        return []
    return entries


def _build_default_lists(
    team_id: str, players_file: str, roster_dir: str
) -> Tuple[List[Player], List[Player], List[Pitcher]]:
    """Return ``(lineup, bench, pitchers)`` for ``team_id``.

    The active roster is loaded from ``roster_dir`` and players are resolved via
    ``players_file``.  Nine position players are selected for the lineup based
    on descending ``ph`` (power hitting) rating.  Pitchers are ordered with a
    single starter first followed by the remaining bullpen arms.
    """

    all_players = {p.player_id: p for p in load_players_from_csv(players_file)}
    roster = load_roster(team_id, roster_dir)

    candidate_ids = []
    for group in (roster.act, roster.aaa, roster.low, roster.dl, roster.ir):
        candidate_ids.extend(group)
    seen_ids: set[str] = set()
    candidates: List[Player] = []
    for pid in candidate_ids:
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        player = all_players.get(pid)
        if player is not None:
            candidates.append(player)

    hitters, pitchers = _separate_players(candidates)
    if len(hitters) < 9 or not pitchers:
        all_hitters, all_pitchers = _separate_players(all_players.values())
        used_ids = {p.player_id for p in hitters + pitchers}
        if len(hitters) < 9:
            fallback_hitters = [p for p in all_hitters if p.player_id not in used_ids]
            rng = random.Random(f"{team_id}-fallback-hitters")
            rng.shuffle(fallback_hitters)
            needed = 9 - len(hitters)
            hitters.extend(fallback_hitters[:needed])
            used_ids.update(p.player_id for p in fallback_hitters[:needed])
        if not pitchers:
            fallback_pitchers = [
                p for p in all_pitchers if p.player_id not in used_ids
            ]
            rng = random.Random(f"{team_id}-fallback-pitchers")
            rng.shuffle(fallback_pitchers)
            pitchers.extend(fallback_pitchers[:10])
            used_ids.update(p.player_id for p in fallback_pitchers[:10])

    hitters.sort(key=lambda p: getattr(p, "ph", 0), reverse=True)
    lineup = hitters[:9]
    bench = hitters[9:]

    pitcher_lookup = {p.player_id: p for p in pitchers}
    staff_entries = _load_pitching_staff(team_id, roster_dir, set(pitcher_lookup))
    ordered_pitchers: List[Pitcher] = []

    for pid, role in staff_entries:
        pitcher = pitcher_lookup.pop(pid, None)
        if pitcher is None:
            continue
        setattr(pitcher, "assigned_pitching_role", role)
        ordered_pitchers.append(pitcher)

    remaining = list(pitcher_lookup.values())
    for pitcher in remaining:
        assigned = getattr(pitcher, "assigned_pitching_role", None)
        if not assigned:
            derived = get_role(pitcher)
            setattr(pitcher, "assigned_pitching_role", derived or "")
    remaining.sort(key=lambda p: getattr(p, "endurance", 0), reverse=True)
    ordered_pitchers.extend(remaining)

    if not ordered_pitchers:
        pitchers.sort(key=lambda p: getattr(p, "endurance", 0), reverse=True)
        ordered_pitchers = pitchers
        for pitcher in ordered_pitchers:
            assigned = getattr(pitcher, "assigned_pitching_role", None)
            if not assigned:
                derived = get_role(pitcher)
                setattr(pitcher, "assigned_pitching_role", derived or "")

    # Ensure a five-man rotation exists and starters do not clutter the bullpen.
    rotation: List[Pitcher] = []
    bullpen: List[Pitcher] = []
    for pitcher in ordered_pitchers:
        role = str(getattr(pitcher, "assigned_pitching_role", "") or "").upper()
        if role.startswith("SP"):
            rotation.append(pitcher)
        else:
            bullpen.append(pitcher)

    if len(rotation) < 5:
        bullpen_sorted = sorted(
            bullpen, key=lambda p: getattr(p, "endurance", 0), reverse=True
        )
        while len(rotation) < 5 and bullpen_sorted:
            promote = bullpen_sorted.pop(0)
            if promote in bullpen:
                bullpen.remove(promote)
            rotation.append(promote)

    # Keep exactly five rotation slots, push any extras to the bullpen group.
    extra_rotation = rotation[5:]
    if extra_rotation:
        for pitcher in extra_rotation:
            setattr(pitcher, "assigned_pitching_role", "MR")
        bullpen = extra_rotation + bullpen
        rotation = rotation[:5]

    # Label rotation spots consistently (SP1..SP5) for downstream consumers.
    for idx, pitcher in enumerate(rotation, start=1):
        setattr(pitcher, "assigned_pitching_role", f"SP{idx}")

    for pitcher in bullpen:
        role = str(getattr(pitcher, "assigned_pitching_role", "") or "").upper()
        if role == "SP":
            setattr(pitcher, "assigned_pitching_role", "MR")

    ordered_pitchers = rotation + bullpen

    return lineup, bench, ordered_pitchers


@lru_cache(maxsize=None)
def _teams_lookup(path: str) -> dict[str, object]:
    try:
        teams = load_teams(path)
    except Exception:
        return {}
    return {t.team_id: t for t in teams}


def build_default_game_state(
    team_id: str,
    players_file: str = "data/players.csv",
    roster_dir: str = "data/rosters",
    teams_file: str | Path = "data/teams.csv",
) -> TeamState:
    """Return a :class:`~playbalance.simulation.TeamState` for ``team_id``.

    The state uses nine best hitters for the lineup, remaining hitters as the
    bench and pitchers ordered with a starter first followed by the bullpen.
    """

    lineup, bench, pitchers = _build_default_lists(team_id, players_file, roster_dir)

    if len(lineup) < 9:
        raise ValueError(f"Team {team_id} does not have enough position players")
    if not pitchers:
        raise ValueError(f"Team {team_id} does not have any pitchers")

    team_obj = None
    if teams_file:
        lookup_path = resolve_app_path(teams_file)
        team_obj = _teams_lookup(str(lookup_path)).get(team_id)

    state = TeamState(lineup=lineup, bench=bench, pitchers=pitchers, team=team_obj)
    if team_obj is not None:
        season = getattr(team_obj, "season_stats", None)
        if season:
            state.team_stats = dict(season)
    return state
