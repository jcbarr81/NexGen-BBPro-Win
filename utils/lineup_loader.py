import csv
import random
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Tuple

from playbalance.simulation import TeamState
from models.player import Player
from models.pitcher import Pitcher
from models.roster import Roster
from utils.path_utils import resolve_app_path
from .player_loader import load_players_from_csv
from .roster_loader import load_roster
from .pitcher_role import get_role
from .rotation import choose_rotation, game_staff_roles
from .staff_roles import canonical_relief_role
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


def _resolve_players(
    ids: Iterable[str], all_players: dict[str, Player], seen: set[str]
) -> List[Player]:
    """Resolve ``ids`` against ``all_players``, skipping ids already in ``seen``."""

    found: List[Player] = []
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        player = all_players.get(pid)
        if player is not None:
            found.append(player)
    return found


def _default_hitters(
    team_id: str, roster: Roster, all_players: dict[str, Player]
) -> Tuple[List[Player], List[Player]]:
    """Return ``(lineup, bench)`` for ``team_id``'s default game state.

    Nine position players are selected for the lineup based on descending
    ``ph`` (power hitting) rating; the remaining hitters form the bench.
    """

    # A big-league game uses the ACTIVE roster. 3.2.12 widened this pool to
    # every level, and for the whole 2026 alpha-test season AAA and Low-A
    # players -- and players on the DL -- started in MLB lineups and pitched
    # out of MLB bullpens: the best nine hitters in the organisation made the
    # default lineup, and half the CPU clubs fielded 3-5 minor leaguers every
    # game. Injured players are never eligible; healthy minor leaguers only
    # fill in when the active roster cannot field a team.
    seen_ids: set[str] = set()
    hitters, _ = _separate_players(_resolve_players(roster.act, all_players, seen_ids))
    if len(hitters) < 9:
        minor_hitters, _ = _separate_players(
            _resolve_players(list(roster.aaa) + list(roster.low), all_players, seen_ids)
        )
        minor_hitters.sort(key=lambda p: getattr(p, "ph", 0), reverse=True)
        hitters.extend(minor_hitters[: max(0, 9 - len(hitters))])
    if len(hitters) < 9:
        all_hitters, _ = _separate_players(all_players.values())
        used_ids = {p.player_id for p in hitters}
        fallback_hitters = [p for p in all_hitters if p.player_id not in used_ids]
        rng = random.Random(f"{team_id}-fallback-hitters")
        rng.shuffle(fallback_hitters)
        needed = 9 - len(hitters)
        hitters.extend(fallback_hitters[:needed])

    hitters.sort(key=lambda p: getattr(p, "ph", 0), reverse=True)
    lineup = hitters[:9]
    bench = hitters[9:]
    return lineup, bench


def _default_pitchers(
    team_id: str, roster_dir: str, roster: Roster, all_players: dict[str, Player]
) -> List[Pitcher]:
    """Return ``team_id``'s pitchers, the five-man rotation first.

    The rotation comes from :func:`utils.rotation.choose_rotation` and is
    labelled SP1-SP5; it is followed by the bullpen in staff-file order, then
    the unlisted arms by endurance. Each arm's ``assigned_pitching_role`` is
    its :func:`utils.rotation.game_staff_roles` label.
    """

    # Active roster first; healthy minor leaguers only when it has no arms
    # (see _default_hitters).
    seen_ids: set[str] = set()
    _, pitchers = _separate_players(_resolve_players(roster.act, all_players, seen_ids))
    if not pitchers:
        _, minor_pitchers = _separate_players(
            _resolve_players(list(roster.aaa) + list(roster.low), all_players, seen_ids)
        )
        minor_pitchers.sort(key=lambda p: getattr(p, "endurance", 0), reverse=True)
        pitchers.extend(minor_pitchers[:10])
    if not pitchers:
        _, all_pitchers = _separate_players(all_players.values())
        fallback_pitchers = list(all_pitchers)
        rng = random.Random(f"{team_id}-fallback-pitchers")
        rng.shuffle(fallback_pitchers)
        pitchers.extend(fallback_pitchers[:10])

    pitcher_lookup = {p.player_id: p for p in pitchers}
    staff_entries = _load_pitching_staff(team_id, roster_dir, set(pitcher_lookup))
    staff_labels: dict[str, str] = {}
    eligible: List[str] = []
    for pid, role in staff_entries:
        if pid in pitcher_lookup and pid not in staff_labels:
            staff_labels[pid] = role.strip().upper()
            eligible.append(pid)
    # Arms the staff file leaves out, strongest arm first.
    unlisted = sorted(
        (p for pid, p in pitcher_lookup.items() if pid not in staff_labels),
        key=lambda p: getattr(p, "endurance", 0),
        reverse=True,
    )
    eligible.extend(p.player_id for p in unlisted)

    # One rotation builder for the whole game path (Release 3): the tracker
    # picks from the same five. The closer is never promoted into it; a thin
    # staff spot-starts its long man or the strongest other arm instead.
    saved = sorted(
        (
            (role, pid)
            for pid, role in staff_labels.items()
            if role in {"SP1", "SP2", "SP3", "SP4", "SP5"}
        ),
    )
    rotation = choose_rotation(
        saved_rotation=[pid for _, pid in saved],
        existing_rotation=[],
        starter_capable=[
            (pid, int(getattr(pitcher_lookup[pid], "endurance", 0) or 0))
            for pid in eligible
            if get_role(pitcher_lookup[pid]) == "SP"
        ],
        staff_roles=staff_labels,
        built=[],
        eligible=[
            pid
            for pid in eligible
            if canonical_relief_role(staff_labels.get(pid)) != "CL"
        ],
    )
    # The rotation is SP1-SP5, staff-file relief labels stand, and anyone else
    # (an unlisted arm, a listed starter outside the five) is a middle
    # reliever -- never the stale stored ``role`` column. The labels are set
    # afresh for every arm on every call, so the result never depends on what
    # an earlier game left on the cached player objects (S1-10).
    roles = game_staff_roles(staff_labels, eligible, rotation)
    for pid in eligible:
        setattr(pitcher_lookup[pid], "assigned_pitching_role", roles[pid])

    in_rotation = set(rotation)
    return [pitcher_lookup[pid] for pid in rotation] + [
        pitcher_lookup[pid] for pid in eligible if pid not in in_rotation
    ]


def _build_default_lists(
    team_id: str, players_file: str, roster_dir: str
) -> Tuple[List[Player], List[Player], List[Pitcher]]:
    """Return ``(lineup, bench, pitchers)`` for ``team_id``.

    The active roster is loaded from ``roster_dir`` and players are resolved via
    ``players_file``. The hitters come from :func:`_default_hitters` and the
    pitchers, a single starter first followed by the remaining bullpen arms,
    from :func:`_default_pitchers`.
    """

    all_players = {p.player_id: p for p in load_players_from_csv(players_file)}
    roster = load_roster(team_id, roster_dir)
    # Hitters first: their pool is chosen before any pitcher's
    # ``assigned_pitching_role`` is (re)labelled, as it always was.
    lineup, bench = _default_hitters(team_id, roster, all_players)
    pitchers = _default_pitchers(team_id, roster_dir, roster, all_players)
    return lineup, bench, pitchers


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
